from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
import logging
import os
import tempfile
import zipfile

from fastapi import BackgroundTasks, Body, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from starlette.background import BackgroundTask

from .auth import Auth, SESSION_COOKIE, SESSION_SECONDS
from .config import PANEL_VERSION, RestartSchedule, SandboxConfig, Settings
from .service import BusyError, PanelService
from .storage import inside

STATIC_DIR = Path(__file__).parent / "static"


class Login(BaseModel):
    username: str = Field(max_length=128)
    password: str = Field(max_length=128)


class Password(BaseModel):
    new_password: str = Field(min_length=4, max_length=128)


class DirectoryCreate(BaseModel):
    path: str = ""
    name: str = Field(min_length=1, max_length=255)


class FolderDownload(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=100)


class BackupRestore(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class TextFileUpdate(BaseModel):
    content: str = Field(max_length=4 * 1024 * 1024)


class PlayerUpdate(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    field: Literal["access_level", "whitelisted", "banned"]
    value: str | bool


def create_app(settings=None, docker_factory=None):
    settings = settings or Settings.from_env()
    service = PanelService(settings, docker_factory)
    auth = Auth(settings.data_dir)

    @asynccontextmanager
    async def lifespan(_app):
        service.start_scheduler()
        yield
        service.stop_event.set()
        for worker in (service.scheduler, service.maintenance):
            if worker:
                worker.join(timeout=6)

    app = FastAPI(title="TechTim Project Zomboid Server Panel", version=PANEL_VERSION,
                  lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
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
        if not request.url.path.startswith("/static/"):
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
        logging.getLogger("zomboid-panel").exception("Panel request failed")
        return JSONResponse({"detail": f"작업을 완료하지 못했습니다: {error}"}, status_code=503)

    def cookie(response, token, request):
        response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="strict",
                            secure=request.url.scheme == "https", max_age=SESSION_SECONDS)

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

    def file_name(value):
        name = str(value or "").strip()
        if not name or name in {".", ".."} or any(char in name for char in "/\\\x00"):
            raise ValueError("파일 또는 폴더 이름을 확인해주세요.")
        return name

    @app.get("/health")
    def health():
        return {"status": "ok", "game": "zomboid", "version": PANEL_VERSION}

    @app.get("/login")
    @app.get("/change-password")
    def login_page():
        return FileResponse(STATIC_DIR / "login.html")

    @app.get("/")
    def dashboard(request: Request):
        try:
            user = auth.require(request, allow_initial=True)
        except HTTPException:
            return RedirectResponse("/login", status_code=303)
        if user["must_change_password"]:
            return RedirectResponse("/change-password", status_code=303)
        return FileResponse(STATIC_DIR / "dashboard.html")

    @app.post("/api/auth/login")
    def login(payload: Login, request: Request, response: Response):
        token, initial = auth.login(payload.username, payload.password, request.client.host if request.client else "unknown")
        cookie(response, token, request)
        return {"redirect": "/change-password" if initial else "/"}

    @app.post("/api/auth/change-password")
    def change_password(payload: Password, request: Request, response: Response):
        cookie(response, auth.change_password(request, payload.new_password), request)
        return {"redirect": "/"}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response):
        auth.logout(request); response.delete_cookie(SESSION_COOKIE)
        return {"redirect": "/login"}

    @app.get("/api/config")
    def get_config(request: Request):
        auth.require(request); return service.public_config()

    @app.post("/api/config")
    def save_config(request: Request, payload: dict = Body(...)):
        auth.require(request); return service.save_config(payload)

    @app.get("/api/sandbox")
    def get_sandbox(request: Request):
        auth.require(request); return service.sandbox_config().model_dump()

    @app.post("/api/sandbox")
    def save_sandbox(payload: SandboxConfig, request: Request):
        auth.require(request); return service.save_sandbox(payload.model_dump())

    @app.get("/api/schedule")
    def get_schedule(request: Request):
        auth.require(request); return service.schedule().model_dump()

    @app.post("/api/schedule")
    def save_schedule(payload: RestartSchedule, request: Request):
        auth.require(request); return service.save_schedule(payload.model_dump())

    @app.get("/api/status")
    @app.get("/api/server/status")
    def status(request: Request):
        auth.require(request); return service.status()

    @app.post("/api/install")
    def install(request: Request, tasks: BackgroundTasks):
        return queued(request, tasks, "엔진 설치·업데이트", service.install)

    @app.post("/api/server/{action}")
    def server_action(action: Literal["start", "stop", "restart"], request: Request, tasks: BackgroundTasks):
        names = {"start": "서버 시작", "stop": "서버 중지", "restart": "서버 재시작"}
        return queued(request, tasks, names[action], getattr(service, action))

    @app.get("/api/logs")
    def logs(request: Request, kind: Literal["server", "install", "control"] = "server"):
        auth.require(request); return {"log": service.logs(kind)}

    @app.get("/api/resources")
    @app.get("/api/server/resources")
    def resources(request: Request):
        auth.require(request); return service.resources()

    @app.get("/api/backups")
    def backups(request: Request):
        auth.require(request); return {"backups": service.backups_list()}

    @app.post("/api/backups")
    def backup(request: Request):
        auth.require(request)
        with service.operation("수동 백업"):
            result = service.create_backup()
        return result

    @app.post("/api/backups/restore")
    def restore_backup(payload: BackupRestore, request: Request):
        auth.require(request)
        with service.operation("백업 복원"):
            service.restore_backup(payload.name)
        return {"status": "ok"}

    @app.get("/api/backups/download")
    def download_backup(name: str, request: Request):
        auth.require(request)
        target = inside(service.backups, Path(name).name)
        if not target.is_file():
            raise FileNotFoundError(name)
        return FileResponse(target, filename=target.name, media_type="application/zip")

    @app.get("/api/workshop")
    def workshop(request: Request):
        auth.require(request)
        config = service.config()
        roots = [service.server / "steamapps" / "workshop" / "content" / "108600",
                 service.server / "steamapps" / "workshop" / "content" / "380870"]
        installed = []
        for root in roots:
            if root.exists():
                installed.extend(path.name for path in root.iterdir() if path.is_dir() and path.name.isdigit())
        return {"workshop_items": config.workshop_items, "mod_ids": config.mod_ids,
                "map_order": config.map_order, "installed": sorted(set(installed))}

    @app.get("/api/players")
    def players(request: Request):
        auth.require(request); return service.player_accounts()

    @app.post("/api/players")
    def update_player(payload: PlayerUpdate, request: Request):
        auth.require(request)
        with service.operation("사용자 DB 변경"):
            service.update_player(payload.username, payload.field, payload.value)
        return service.player_accounts()

    allowed_text_files = {
        "server-ini": service.server_config_dir / "servertest.ini",
        "sandbox": service.server_config_dir / "servertest_SandboxVars.lua",
        "spawnpoints": service.server_config_dir / "servertest_spawnpoints.lua",
        "spawnregions": service.server_config_dir / "servertest_spawnregions.lua",
    }

    @app.get("/api/text-file/{kind}")
    def read_text_file(kind: str, request: Request):
        auth.require(request); service.require_stopped()
        path = allowed_text_files.get(kind)
        if not path:
            raise HTTPException(404, "지원하지 않는 파일입니다.")
        return {"kind": kind, "content": path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""}

    @app.post("/api/text-file/{kind}")
    def write_text_file(kind: str, payload: TextFileUpdate, request: Request):
        auth.require(request); service.require_stopped()
        path = allowed_text_files.get(kind)
        if not path:
            raise HTTPException(404, "지원하지 않는 파일입니다.")
        service._atomic_text(path, payload.content)
        return {"status": "ok"}

    @app.get("/api/files")
    def list_files(request: Request, path: str = ""):
        auth.require(request); service.require_stopped()
        target = data_path(path)
        if not target.is_dir():
            raise FileNotFoundError(path)
        entries = []
        for child in target.iterdir():
            try:
                if child.is_symlink():
                    continue
                stat = child.stat()
                entries.append({"name": child.name, "path": relative(child),
                                "type": "dir" if child.is_dir() else "file",
                                "size": stat.st_size if child.is_file() else 0,
                                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")})
            except OSError:
                continue
        entries.sort(key=lambda item: (item["type"] != "dir", item["name"].casefold()))
        return {"root": "/data", "path": relative(target),
                "parent": relative(target.parent) if target != service.data.resolve() else "", "entries": entries}

    @app.post("/api/files/directory")
    def create_directory(payload: DirectoryCreate, request: Request):
        auth.require(request); service.require_stopped()
        target = data_path(payload.path) / file_name(payload.name)
        target.mkdir(parents=False, exist_ok=False)
        return {"status": "ok"}

    @app.post("/api/files/upload")
    async def upload_file(request: Request, file: UploadFile = File(...), path: str = Form("")):
        auth.require(request); service.require_stopped()
        target = data_path(path) / file_name(file.filename)
        written = 0
        temporary = target.with_name(f".{target.name}.upload")
        try:
            with temporary.open("wb") as output:
                while chunk := await file.read(1024 * 1024):
                    written += len(chunk)
                    if written > settings.max_upload_bytes:
                        raise HTTPException(413, "업로드 제한을 초과했습니다.")
                    output.write(chunk)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
            await file.close()
        return {"status": "ok", "size": written}

    @app.get("/api/files/download")
    def download_file(path: str, request: Request):
        auth.require(request); service.require_stopped()
        target = data_path(path)
        if not target.is_file():
            raise FileNotFoundError(path)
        return FileResponse(target, filename=target.name, media_type="application/octet-stream")

    @app.post("/api/files/download-folders")
    def download_folders(payload: FolderDownload, request: Request):
        auth.require(request); service.require_stopped()
        targets = [data_path(path) for path in payload.paths]
        if any(not target.is_dir() for target in targets):
            raise ValueError("폴더만 묶어서 다운로드할 수 있습니다.")
        service.exports.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(prefix="zomboid-folders-", suffix=".zip", dir=service.exports, delete=False)
        archive_path = Path(handle.name); handle.close()
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            for target in targets:
                for source in target.rglob("*"):
                    if source.is_file() and not source.is_symlink():
                        archive.write(source, relative(source))
        return FileResponse(archive_path, filename=f"zomboid-folders-{datetime.now():%Y%m%d-%H%M%S}.zip",
                            media_type="application/zip", background=BackgroundTask(archive_path.unlink, missing_ok=True))

    @app.delete("/api/files")
    def delete_file(path: str, request: Request):
        auth.require(request); service.require_stopped()
        target = data_path(path)
        if target == service.data.resolve():
            raise ValueError("데이터 루트는 삭제할 수 없습니다.")
        if target.is_dir():
            if any(target.iterdir()):
                raise ValueError("비어 있지 않은 폴더는 삭제할 수 없습니다.")
            target.rmdir()
        elif target.is_file():
            target.unlink()
        else:
            raise FileNotFoundError(path)
        return {"status": "ok"}

    @app.get("/api/panel-update")
    def panel_update(request: Request):
        auth.require(request); return service.panel_update_status()

    @app.post("/api/panel-update")
    def apply_panel_update(request: Request):
        auth.require(request)
        with service.operation("웹패널 업데이트"):
            service.update_panel()
        return {"status": "accepted"}

    return app


app = create_app()
