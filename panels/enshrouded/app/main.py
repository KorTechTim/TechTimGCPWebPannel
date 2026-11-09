from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
import logging
import os
import shutil
import tempfile

from fastapi import BackgroundTasks, Body, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from starlette.background import BackgroundTask

from .auth import Auth, SESSION_COOKIE, SESSION_SECONDS
from .config import PANEL_VERSION, BackupSchedule, RestartSchedule, Settings
from .discord_webhook import normalize_webhook_url
from .service import BusyError, PanelService
from .storage import inside


STATIC_DIR = Path(__file__).parent / "static"
TEXT_EDITOR_MAX_BYTES = 2 * 1024 * 1024
EDITABLE_SUFFIXES = {".json", ".txt", ".log", ".cfg", ".conf", ".ini", ".yaml", ".yml"}


class Login(BaseModel):
    username: str = Field(max_length=128)
    password: str = Field(max_length=128)


class Password(BaseModel):
    new_password: str = Field(min_length=4, max_length=128)


class BackupRestore(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class DirectoryCreate(BaseModel):
    path: str = ""
    name: str = Field(min_length=1, max_length=255)


class TextFileUpdate(BaseModel):
    content: str = Field(max_length=4 * 1024 * 1024)


class DiscordConfigUpdate(BaseModel):
    enabled: bool = False
    webhook_url: str = Field(default="", max_length=500)
    clear_webhook: bool = False
    username: str = Field(default="TechTim Enshrouded Server", min_length=1, max_length=80)
    notify_server_start: bool = True
    notify_server_stop: bool = True
    notify_server_restart: bool = True
    notify_backup: bool = True
    notify_migration: bool = True
    notify_errors: bool = True


def create_app(settings=None, docker_factory=None):
    settings = settings or Settings.from_env()
    service = PanelService(settings, docker_factory)
    auth = Auth(settings.data_dir)

    @asynccontextmanager
    async def lifespan(_app):
        service.start_scheduler()
        yield
        service.stop_event.set()
        if service.scheduler:
            service.scheduler.join(timeout=6)

    app = FastAPI(
        title="TechTim Enshrouded GCP Panel", version=PANEL_VERSION,
        lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None,
    )
    app.state.service = service
    app.state.auth = auth
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.middleware("http")
    async def headers(request, call_next):
        origin = request.headers.get("origin")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin:
            source = urlsplit(origin)
            if source.netloc != request.headers.get("host") or source.scheme not in {"http", "https"}:
                return JSONResponse({"detail": "다른 사이트에서 보낸 요청은 허용되지 않습니다."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.path in {"/static/app.js", "/static/app.css", "/static/login.js", "/static/i18n.js"}:
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        elif not request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(BusyError)
    async def busy_error(_request, error):
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.exception_handler(ValueError)
    async def value_error(_request, error):
        return JSONResponse({"detail": str(error)}, status_code=400)

    @app.exception_handler(ValidationError)
    async def validation_error(_request, error):
        details = [f"{'.'.join(map(str, item['loc']))}: {item['msg']}" for item in error.errors(include_input=False)]
        return JSONResponse({"detail": " / ".join(details)}, status_code=400)

    @app.exception_handler(FileNotFoundError)
    async def missing(_request, _error):
        return JSONResponse({"detail": "파일을 찾을 수 없습니다."}, status_code=404)

    @app.exception_handler(Exception)
    async def unexpected(_request, error):
        logging.getLogger("enshrouded-panel").exception("Panel request failed")
        return JSONResponse({"detail": f"작업을 완료하지 못했습니다: {error}"}, status_code=503)

    def cookie(response, token, request):
        response.set_cookie(
            SESSION_COOKIE, token, httponly=True, samesite="strict",
            secure=request.url.scheme == "https", max_age=SESSION_SECONDS,
        )

    def queued(request, tasks, name, action):
        auth.require(request)
        handle = service.reserve(name)
        tasks.add_task(service.run_reserved, handle, name, action)
        return JSONResponse({"status": "queued", "message": f"{name} 요청을 접수했습니다."}, status_code=202)

    def data_path(relative=""):
        return service.data.resolve() if not relative else inside(service.data, relative)

    def relative(path):
        resolved = path.resolve()
        root = service.data.resolve()
        return "" if resolved == root else resolved.relative_to(root).as_posix()

    def safe_name(value):
        name = str(value or "").strip()
        if not name or name in {".", ".."} or any(char in name for char in "/\\\x00"):
            raise ValueError("파일 또는 폴더 이름을 확인해주세요.")
        return name

    @app.get("/health")
    def health():
        return {"status": "ok", "game": "enshrouded", "version": PANEL_VERSION}

    @app.get("/login")
    @app.get("/change-password")
    def login_page():
        return FileResponse(STATIC_DIR / "login.html")

    @app.get("/")
    def dashboard(request: Request):
        try:
            user = auth.require(request)
        except HTTPException:
            return RedirectResponse("/login", status_code=303)
        if user["must_change_password"]:
            return RedirectResponse("/change-password", status_code=303)
        return FileResponse(STATIC_DIR / "dashboard.html")

    @app.post("/api/auth/login")
    def login(payload: Login, request: Request, response: Response):
        token, must_change = auth.login(payload.username, payload.password, request.client.host if request.client else "unknown")
        cookie(response, token, request)
        return {"status": "ok", "must_change_password": must_change}

    @app.post("/api/auth/change-password")
    def change_password(payload: Password, request: Request, response: Response):
        token = auth.change_password(request, payload.new_password)
        cookie(response, token, request)
        return {"status": "ok"}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response):
        auth.logout(request)
        response.delete_cookie(SESSION_COOKIE)
        return {"status": "ok"}

    @app.get("/api/status")
    def status(request: Request):
        auth.require(request)
        return service.status()

    @app.get("/api/resources")
    def resources(request: Request):
        auth.require(request)
        return service.resources()

    @app.post("/api/install")
    def install(request: Request, tasks: BackgroundTasks):
        return queued(request, tasks, "서버 설치", service.install)

    @app.post("/api/server/{action}")
    def server_action(action: Literal["start", "stop", "restart"], request: Request, tasks: BackgroundTasks):
        actions = {"start": ("서버 시작", service.start), "stop": ("서버 중지", service.stop), "restart": ("서버 재시작", service.restart)}
        name, function = actions[action]
        return queued(request, tasks, name, function)

    @app.get("/api/config")
    def get_config(request: Request):
        auth.require(request)
        return service.config().model_dump()

    @app.post("/api/config")
    def save_config(request: Request, payload: dict = Body(...)):
        auth.require(request)
        return service.save_config(payload).model_dump()

    @app.get("/api/schedule")
    def get_schedule(request: Request):
        auth.require(request)
        return service.schedule().model_dump()

    @app.post("/api/schedule")
    def save_schedule(payload: RestartSchedule, request: Request):
        auth.require(request)
        return service.save_schedule(payload).model_dump()

    @app.get("/api/backups/settings")
    def get_backup_schedule(request: Request):
        auth.require(request)
        return service.backup_schedule().model_dump()

    @app.post("/api/backups/settings")
    def save_backup_schedule(payload: BackupSchedule, request: Request):
        auth.require(request)
        return service.save_backup_schedule(payload).model_dump()

    @app.get("/api/logs")
    def logs(request: Request, kind: Literal["all", "server", "install", "control"] = "all"):
        auth.require(request)
        return {"log": service.logs(kind)}

    @app.get("/api/logs/export")
    def export_support_logs(request: Request):
        auth.require(request)
        name = f"techtim-enshrouded-support-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
        return Response(
            service.support_log_report(), media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    @app.get("/api/backups")
    def backups(request: Request):
        auth.require(request)
        return {"backups": service.backups_list()}

    @app.post("/api/backups")
    def backup(request: Request, tasks: BackgroundTasks):
        return queued(request, tasks, "수동 백업", lambda: service.create_backup("manual"))

    @app.post("/api/backups/restore")
    def restore_backup(payload: BackupRestore, request: Request, tasks: BackgroundTasks):
        return queued(request, tasks, "백업 복원", lambda: service.restore_backup(payload.name))

    @app.get("/api/backups/download")
    def download_backup(name: str, request: Request):
        auth.require(request)
        path = service._safe_named_file(service.backups, name)
        return FileResponse(path, filename=path.name, media_type="application/zip")

    @app.get("/api/discord")
    def get_discord_config(request: Request):
        auth.require(request)
        return {"config": service.public_discord_config()}

    @app.post("/api/discord")
    def save_discord_config(payload: DiscordConfigUpdate, request: Request):
        auth.require(request)
        data = payload.model_dump()
        if data.get("webhook_url"):
            data["webhook_url"] = normalize_webhook_url(data["webhook_url"])
        return {"config": service.save_discord_config(data)}

    @app.post("/api/discord/test")
    def test_discord_webhook(request: Request):
        auth.require(request)
        service.deliver_discord_event("test", "연동 테스트", "TechTim Enshrouded 패널과 정상적으로 연결되었습니다.")
        return {"status": "ok", "message": "테스트 알림을 전송했습니다."}

    @app.get("/api/migration/export")
    def migration_export(request: Request):
        auth.require(request)
        path = service.create_migration_archive()
        return FileResponse(
            path, filename=path.name, media_type="application/zip",
            background=BackgroundTask(path.unlink, missing_ok=True),
        )

    @app.post("/api/migration/import")
    async def migration_import(request: Request, file: UploadFile = File(...)):
        auth.require(request)
        if not file.filename or not file.filename.lower().endswith(".zip"):
            raise ValueError("ZIP 형식의 이사 파일을 선택해주세요.")
        descriptor, temporary_name = tempfile.mkstemp(prefix="enshrouded-migration-", suffix=".zip")
        os.close(descriptor)
        temporary = Path(temporary_name)
        size = 0
        try:
            with temporary.open("wb") as writer:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > settings.max_upload_bytes:
                        raise ValueError("이사 파일이 업로드 제한을 초과했습니다.")
                    writer.write(chunk)
            service.import_migration_archive(temporary)
            return {"status": "ok", "message": "세이브와 설정을 가져왔습니다."}
        finally:
            temporary.unlink(missing_ok=True)

    @app.get("/api/files")
    def list_files(request: Request, path: str = ""):
        auth.require(request)
        target = data_path(path)
        if not target.is_dir() or target.is_symlink():
            raise ValueError("폴더를 찾을 수 없습니다.")
        entries = []
        for item in sorted(target.iterdir(), key=lambda value: (not value.is_dir(), value.name.casefold())):
            if item.is_symlink():
                continue
            entries.append({
                "name": item.name, "path": relative(item), "type": "folder" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else None,
                "modified_at": item.stat().st_mtime,
                "editable": item.is_file() and item.suffix.lower() in EDITABLE_SUFFIXES and item.stat().st_size <= TEXT_EDITOR_MAX_BYTES,
            })
        return {"root": "/data", "path": relative(target), "entries": entries, "locked": service.is_running()}

    def editable_text_file(path):
        target = data_path(path)
        if not target.is_file() or target.is_symlink():
            raise FileNotFoundError(path)
        if target.suffix.lower() not in EDITABLE_SUFFIXES:
            raise ValueError("지원하지 않는 텍스트 파일 형식입니다.")
        if target.stat().st_size > TEXT_EDITOR_MAX_BYTES:
            raise ValueError("편집 가능한 파일 크기를 초과했습니다.")
        content = target.read_bytes()
        if b"\x00" in content:
            raise ValueError("바이너리 파일은 편집할 수 없습니다.")
        return target, content.decode("utf-8")

    @app.get("/api/files/text")
    def read_explorer_text_file(path: str, request: Request):
        auth.require(request)
        target, content = editable_text_file(path)
        return {"path": relative(target), "content": content, "locked": service.is_running()}

    @app.post("/api/files/text")
    def write_explorer_text_file(path: str, payload: TextFileUpdate, request: Request):
        auth.require(request)
        service.require_stopped()
        target, _ = editable_text_file(path)
        encoded = payload.content.encode("utf-8")
        if len(encoded) > TEXT_EDITOR_MAX_BYTES:
            raise ValueError("편집 가능한 파일 크기를 초과했습니다.")
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_bytes(encoded)
        temporary.replace(target)
        return {"status": "ok", "path": relative(target)}

    @app.post("/api/files/directory")
    def create_directory(payload: DirectoryCreate, request: Request):
        auth.require(request)
        service.require_stopped()
        target = data_path(payload.path) / safe_name(payload.name)
        if target.exists():
            raise ValueError("같은 이름의 파일 또는 폴더가 있습니다.")
        target.mkdir()
        return {"status": "ok"}

    @app.post("/api/files/upload")
    async def upload_file(request: Request, file: UploadFile = File(...), path: str = Form("")):
        auth.require(request)
        service.require_stopped()
        target = data_path(path) / safe_name(file.filename)
        if target.exists() or target.is_symlink():
            raise ValueError("같은 이름의 파일이 있습니다.")
        size = 0
        try:
            with target.open("xb") as writer:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > settings.max_upload_bytes:
                        raise ValueError("업로드 제한을 초과했습니다.")
                    writer.write(chunk)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return {"status": "ok", "size": size}

    @app.get("/api/files/download")
    def download_file(path: str, request: Request):
        auth.require(request)
        target = data_path(path)
        if not target.is_file() or target.is_symlink():
            raise FileNotFoundError(path)
        return FileResponse(target, filename=target.name)

    @app.delete("/api/files")
    def delete_file(path: str, request: Request):
        auth.require(request)
        service.require_stopped()
        target = data_path(path)
        if target == service.data.resolve() or target.is_symlink() or not target.exists():
            raise ValueError("삭제할 수 없는 경로입니다.")
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return {"status": "ok"}

    @app.get("/api/panel-update")
    def panel_update(request: Request):
        auth.require(request)
        return service.panel_update_status()

    @app.post("/api/panel-update")
    def apply_panel_update(request: Request):
        auth.require(request)
        service.update_panel()
        return {"status": "queued", "message": "패널 업데이트를 시작했습니다."}

    return app


app = create_app()
