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
from pydantic import BaseModel, Field, ValidationError, field_validator
from starlette.background import BackgroundTask

from .auth import Auth, SESSION_COOKIE, SESSION_SECONDS
from .config import PANEL_VERSION, RestartSchedule, SandboxConfig, Settings, sandbox_schema
from .discord_webhook import normalize_webhook_url
from .service import BusyError, PanelService
from .storage import inside
from .workshop import WorkshopLookupError, lookup_workshop_item

STATIC_DIR = Path(__file__).parent / "static"
TEXT_EDITOR_MAX_BYTES = 2 * 1024 * 1024


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


class ConsoleCommand(BaseModel):
    command: str = Field(min_length=1, max_length=512)

    @field_validator("command")
    @classmethod
    def valid_command(cls, value):
        command = value.strip()
        if not command or any(ord(char) < 32 for char in command):
            raise ValueError("명령어에는 줄바꿈이나 제어 문자를 사용할 수 없습니다.")
        return command


class WorkshopLookupRequest(BaseModel):
    value: str = Field(min_length=1, max_length=300)


class DiscordConfigUpdate(BaseModel):
    enabled: bool = False
    webhook_url: str = Field(default="", max_length=500)
    clear_webhook: bool = False
    username: str = Field(default="TechTim Project Zomboid Server", min_length=1, max_length=80)
    notify_server_start: bool = True
    notify_server_stop: bool = True
    notify_server_restart: bool = True
    notify_backup: bool = True
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
        for worker in (service.scheduler, service.maintenance):
            if worker:
                worker.join(timeout=6)

    app = FastAPI(title="T2 Zomboid Server Pannel", version=PANEL_VERSION,
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

    @app.get("/api/sandbox/schema")
    def get_sandbox_schema(request: Request):
        auth.require(request); return sandbox_schema()

    @app.post("/api/sandbox")
    def save_sandbox(payload: SandboxConfig, request: Request):
        auth.require(request); return service.save_sandbox(payload.model_dump())

    @app.get("/api/schedule")
    def get_schedule(request: Request):
        auth.require(request); return service.schedule().model_dump()

    @app.post("/api/schedule")
    def save_schedule(payload: RestartSchedule, request: Request):
        auth.require(request); return service.save_schedule(payload.model_dump())

    @app.get("/api/discord")
    def get_discord_config(request: Request):
        auth.require(request)
        return {"status": "ok", "config": service.public_discord_config()}

    @app.post("/api/discord")
    def save_discord_config(payload: DiscordConfigUpdate, request: Request):
        auth.require(request)
        existing = service.discord_config()
        webhook_url = existing.webhook_url
        if payload.clear_webhook:
            webhook_url = ""
        elif payload.webhook_url.strip():
            webhook_url = normalize_webhook_url(payload.webhook_url)
        if payload.enabled and not webhook_url:
            raise ValueError("Discord 연동을 사용하려면 웹훅 URL을 먼저 등록해주세요.")
        values = payload.model_dump(exclude={"clear_webhook"})
        values["webhook_url"] = webhook_url
        return {
            "status": "ok",
            "message": "Discord 연동 설정이 저장되었습니다.",
            "config": service.save_discord_config(values),
        }

    @app.post("/api/discord/test")
    def test_discord_webhook(request: Request):
        auth.require(request)
        try:
            service.deliver_discord_event(
                "test",
                "Discord 연동 테스트 성공",
                "T2 Zomboid Server Pannel과 Discord 채널이 정상적으로 연결되었습니다.",
                [{"name": "알림 상태", "value": "정상", "inline": True}],
            )
        except Exception as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        return {"status": "sent", "message": "Discord 테스트 메시지를 전송했습니다."}

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
    def logs(request: Request, kind: Literal["all", "server", "install", "control"] = "all"):
        auth.require(request); return {"log": service.logs(kind)}

    @app.get("/api/logs/export")
    def export_support_logs(request: Request):
        auth.require(request)
        filename = f"techtim-zomboid-support-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
        return Response(
            service.support_log_report(),
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.post("/api/console/command")
    def console_command(payload: ConsoleCommand, request: Request):
        auth.require(request); return service.console_command(payload.command)

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
                "workshop_mod_pairs": [pair.model_dump() for pair in config.workshop_mod_pairs],
                "map_order": config.map_order, "installed": sorted(set(installed))}

    @app.post("/api/workshop/lookup")
    def workshop_lookup(payload: WorkshopLookupRequest, request: Request):
        auth.require(request)
        try:
            return lookup_workshop_item(payload.value)
        except WorkshopLookupError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

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

    def editable_text_file(path):
        target = data_path(path)
        if not target.is_file():
            raise FileNotFoundError(path)
        if target.stat().st_size > TEXT_EDITOR_MAX_BYTES:
            raise HTTPException(413, "2MB 이하의 텍스트 파일만 편집할 수 있습니다.")
        raw = target.read_bytes()
        if b"\x00" in raw:
            raise ValueError("바이너리 파일은 텍스트 편집기로 열 수 없습니다.")
        try:
            return target, raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("UTF-8 텍스트 파일만 편집할 수 있습니다.") from error

    @app.get("/api/files/text")
    def read_explorer_text_file(path: str, request: Request):
        auth.require(request); service.require_stopped()
        target, content = editable_text_file(path)
        return {"path": relative(target), "name": target.name, "content": content,
                "size": target.stat().st_size}

    @app.post("/api/files/text")
    def write_explorer_text_file(path: str, payload: TextFileUpdate, request: Request):
        auth.require(request); service.require_stopped()
        target, _content = editable_text_file(path)
        encoded = payload.content.encode("utf-8")
        if len(encoded) > TEXT_EDITOR_MAX_BYTES:
            raise HTTPException(413, "2MB 이하의 텍스트 파일만 편집할 수 있습니다.")
        service._atomic_text(target, payload.content)
        return {"status": "ok", "path": relative(target), "name": target.name,
                "size": len(encoded), "message": "파일을 저장했습니다."}

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

    @app.post("/api/files/upload-folder")
    async def upload_folder(request: Request, files: list[UploadFile] = File(...), path: str = Form("")):
        auth.require(request); service.require_stopped()
        target_root = data_path(path)
        if not target_root.is_dir():
            raise FileNotFoundError(path)
        if len(files) > 10000:
            raise HTTPException(413, "한 번에 10,000개 이하의 파일만 업로드할 수 있습니다.")
        written = 0
        uploaded = []
        seen = set()
        try:
            with tempfile.TemporaryDirectory(prefix=".folder-upload-", dir=target_root) as staging_name:
                staging_root = Path(staging_name)
                for upload in files:
                    relative_name = str(upload.filename or "")
                    if relative_name in seen:
                        raise ValueError("폴더에 중복된 파일 경로가 있습니다.")
                    seen.add(relative_name)
                    staged = inside(staging_root, relative_name)
                    staged.parent.mkdir(parents=True, exist_ok=True)
                    with staged.open("xb") as output:
                        while chunk := await upload.read(1024 * 1024):
                            written += len(chunk)
                            if written > settings.max_upload_bytes:
                                raise HTTPException(413, "업로드 제한을 초과했습니다.")
                            output.write(chunk)
                    uploaded.append(relative_name)
                for relative_name in uploaded:
                    staged = inside(staging_root, relative_name, file_only=True)
                    destination = inside(target_root, relative_name)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    staged.replace(destination)
        finally:
            for upload in files:
                await upload.close()
        return {"status": "ok", "files": len(uploaded), "size": written,
                "message": f"폴더의 파일 {len(uploaded)}개를 업로드했습니다."}

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
