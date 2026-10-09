from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
import html
import json
import logging
import os
import secrets
import tempfile
import zipfile

from fastapi import BackgroundTasks, Body, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from starlette.background import BackgroundTask

from .auth import Auth, SESSION_COOKIE, SESSION_SECONDS
from .config import PANEL_VERSION, Permissions, RestartSchedule, Settings, server_arguments, world_name
from .recommended_mods import RecommendedModError, download_recommended_bepinex
from .service import BusyError, PanelService
from .steam_openid import SteamOpenID, SteamOpenIDError
from .storage import inside, read_json, worlds

STATIC_DIR = Path(__file__).parent / "static"
SERVER_TEXT_EDITOR_MAX_BYTES = 2 * 1024 * 1024
SERVER_TEXT_EXTENSIONS = {
    ".cfg", ".conf", ".config", ".env", ".ini", ".json", ".lua", ".properties",
    ".sh", ".toml", ".txt", ".xml", ".yaml", ".yml",
}
SERVER_TEXT_NAMES = {".env", "dockerfile"}


class Login(BaseModel):
    username: str = Field(max_length=128)
    password: str = Field(max_length=128)


class Password(BaseModel):
    new_password: str = Field(min_length=4, max_length=128)


class FileExplorerCreateDirectory(BaseModel):
    path: str = ""
    name: str = Field(min_length=1, max_length=255)


class FileExplorerFolderDownload(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=100)


class FileExplorerTextUpdate(BaseModel):
    content: str = Field(max_length=SERVER_TEXT_EDITOR_MAX_BYTES)


class ModToggle(BaseModel):
    enabled: bool


class ModConfigurationUpdate(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    content: str = Field(max_length=1024 * 1024)


class ModCleanupRequest(BaseModel):
    token: str = Field(pattern=r"^[0-9a-f]{64}$")


class DiscordConfigUpdate(BaseModel):
    enabled: bool = False
    webhook_url: str = Field(default="", max_length=500)
    clear_webhook: bool = False
    username: str = Field(default="TechTim Valheim Server", min_length=1, max_length=80)
    notify_server_start: bool = True
    notify_server_stop: bool = True
    notify_server_restart: bool = True
    notify_backup: bool = True
    notify_errors: bool = True


def create_app(settings=None, docker_factory=None):
    settings = settings or Settings.from_env()
    service = PanelService(settings, docker_factory)
    auth = Auth(settings.data_dir)
    steam_openid = SteamOpenID()

    @asynccontextmanager
    async def lifespan(app):
        service.start_scheduler()
        yield
        service.stop_event.set()
        if service.scheduler:
            service.scheduler.join(timeout=6)
        if service.maintenance:
            service.maintenance.join(timeout=6)

    app = FastAPI(title="TechTim Valheim Server Panel", version=PANEL_VERSION,
                  lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.service = service
    app.state.auth = auth
    app.state.steam_openid = steam_openid
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
        if not request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(BusyError)
    async def busy_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.exception_handler(ValueError)
    async def value_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=400)

    @app.exception_handler(ValidationError)
    async def validation_error(request, error):
        # Avoid echoing submitted passwords via Pydantic's default input representations.
        details = [f"{'.'.join(map(str, item['loc']))}: {item['msg']}" for item in error.errors(include_input=False)]
        return JSONResponse({"detail": " / ".join(details)}, status_code=400)

    @app.exception_handler(FileNotFoundError)
    async def missing_file(request, error):
        return JSONResponse({"detail": "파일을 찾을 수 없습니다."}, status_code=404)

    @app.exception_handler(Exception)
    async def unexpected_error(request, error):
        logging.getLogger("valheim-panel").exception("Panel request failed")
        return JSONResponse({"detail": "작업을 완료하지 못했습니다. Docker 연결과 패널 로그를 확인해주세요."}, status_code=503)

    def cookie(response, token, request):
        response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="strict",
                            secure=request.url.scheme == "https", max_age=SESSION_SECONDS)

    def queued(request, tasks, name, action):
        auth.require(request)
        handle = service.reserve(name)
        tasks.add_task(service.run_reserved, handle, name, action)
        return JSONResponse({"status": "queued", "message": f"{name} 요청을 접수했습니다."}, status_code=202)

    def steam_popup(title, message, *, steam_id="", origin=""):
        nonce = secrets.token_urlsafe(18)
        payload = json.dumps({"type": "techtim-steam-id", "steamId": steam_id,
                              "platformId": f"Steam_{steam_id}"}, ensure_ascii=False).replace("<", "\\u003c")
        target = json.dumps(origin).replace("<", "\\u003c")
        safe_title = html.escape(title)
        safe_message = html.escape(message)
        safe_id = html.escape(f"Steam_{steam_id}") if steam_id else ""
        notify = f"if(window.opener)window.opener.postMessage({payload}, {target});" if steam_id and origin else ""
        body = f"""<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>{safe_title}</title><style nonce=\"{nonce}\">body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#0b191b;color:#edf4f0;font-family:Inter,'Noto Sans KR',sans-serif}}main{{width:min(420px,calc(100% - 32px));padding:28px;border:1px solid #8b693c;border-radius:8px;background:#142a2a;text-align:center;box-shadow:0 18px 60px #0008}}h1{{margin:0 0 12px;font-size:22px}}p{{margin:0;color:#b9c9c4;line-height:1.7}}strong{{display:block;margin:18px 0;padding:13px;border:1px solid #57766e;border-radius:6px;background:#0c2021;color:#f2c77d;font:700 16px ui-monospace,monospace;overflow-wrap:anywhere}}button{{margin-top:20px;padding:10px 24px;border:1px solid #b58a4e;border-radius:6px;background:#a66a34;color:#fff;font-weight:700;cursor:pointer}}</style></head><body><main><h1>{safe_title}</h1><p>{safe_message}</p>{f'<strong>{safe_id}</strong>' if safe_id else ''}<button id=\"close\" type=\"button\">창 닫기</button></main><script nonce=\"{nonce}\">{notify}document.getElementById('close').addEventListener('click',()=>window.close());</script></body></html>"""
        return HTMLResponse(body, headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": f"default-src 'none'; style-src 'nonce-{nonce}'; script-src 'nonce-{nonce}'",
        })

    def server_file_path(relative_path=""):
        if not relative_path:
            return service.server.resolve()
        return inside(service.server, relative_path)

    def server_file_relative(path):
        resolved = path.resolve()
        root = service.server.resolve()
        return "" if resolved == root else resolved.relative_to(root).as_posix()

    def server_file_name(value):
        name = str(value or "").strip()
        if (not name or name in {".", ".."} or "/" in name or "\\" in name or "\x00" in name
                or any(ord(character) < 32 for character in name)):
            raise ValueError("파일 또는 폴더 이름을 확인해주세요.")
        return name

    def server_file_is_editable(path):
        return path.is_file() and (path.suffix.casefold() in SERVER_TEXT_EXTENSIONS
                                   or path.name.casefold() in SERVER_TEXT_NAMES)

    def editable_server_text_file(relative_path):
        target = server_file_path(relative_path)
        if not target.is_file():
            raise FileNotFoundError("편집할 파일을 찾을 수 없습니다.")
        if not server_file_is_editable(target):
            raise ValueError("환경설정과 관련된 텍스트 파일만 편집할 수 있습니다.")
        if target.stat().st_size > SERVER_TEXT_EDITOR_MAX_BYTES:
            raise HTTPException(413, "2MB 이하의 텍스트 파일만 편집할 수 있습니다.")
        raw = target.read_bytes()
        if b"\x00" in raw:
            raise ValueError("바이너리 파일은 텍스트 편집기로 열 수 없습니다.")
        try:
            return target, raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("UTF-8 텍스트 파일만 편집할 수 있습니다.") from error

    def write_server_text_file(target, content):
        encoded = content.encode("utf-8")
        if len(encoded) > SERVER_TEXT_EDITOR_MAX_BYTES:
            raise HTTPException(413, "2MB 이하의 텍스트 파일만 편집할 수 있습니다.")
        original = target.stat()
        temporary = tempfile.NamedTemporaryFile(prefix=f".{target.name}.", suffix=".tmp",
                                                dir=target.parent, delete=False)
        temporary_path = Path(temporary.name)
        try:
            with temporary:
                temporary.write(encoded)
                temporary.flush()
                os.fsync(temporary.fileno())
                os.fchmod(temporary.fileno(), original.st_mode)
                try:
                    os.fchown(temporary.fileno(), original.st_uid, original.st_gid)
                except PermissionError:
                    pass
            temporary_path.replace(target)
        finally:
            temporary_path.unlink(missing_ok=True)
        return len(encoded)

    def server_file_entry(path):
        stat = path.stat()
        return {
            "name": path.name,
            "path": server_file_relative(path),
            "type": "dir" if path.is_dir() else "file",
            "size": stat.st_size if path.is_file() else 0,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            "editable": server_file_is_editable(path),
        }

    def server_folder_archive(targets):
        service.exports.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"valheim-server-folders-{timestamp}.zip"
        handle = tempfile.NamedTemporaryFile(prefix=".server-folders-", suffix=".zip", dir=service.exports, delete=False)
        archive_path = Path(handle.name)
        handle.close()
        try:
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
                for target in targets:
                    for current_dir, dirnames, filenames in os.walk(target, followlinks=False):
                        current = Path(current_dir)
                        dirnames[:] = [name for name in dirnames if not (current / name).is_symlink()]
                        relative_dir = server_file_relative(current)
                        archive.writestr(relative_dir.rstrip("/") + "/", b"")
                        for name in filenames:
                            source = current / name
                            if source.is_symlink() or not source.is_file():
                                continue
                            safe_source = server_file_path(server_file_relative(source))
                            archive.write(safe_source, arcname=server_file_relative(safe_source))
            return archive_path, filename
        except Exception:
            archive_path.unlink(missing_ok=True)
            raise

    @app.get("/health")
    def health():
        return {"status": "ok", "game": "valheim", "version": PANEL_VERSION}

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
        auth.logout(request)
        response.delete_cookie(SESSION_COOKIE)
        return {"redirect": "/login"}

    @app.get("/api/steam/openid/start")
    def steam_openid_start(request: Request):
        auth.require(request)
        callback_url = str(request.url_for("steam_openid_callback"))
        callback = urlsplit(callback_url)
        origin = f"{callback.scheme}://{callback.netloc}"
        return {"status": "ok", "auth_url": steam_openid.begin(origin, callback_url)}

    @app.get("/api/steam/openid/callback", name="steam_openid_callback")
    def steam_openid_callback(request: Request):
        state = request.query_params.get("state", "")
        parameters = {key: value for key, value in request.query_params.items() if key.startswith("openid.")}
        try:
            steam_id, origin = steam_openid.verify(state, parameters)
        except SteamOpenIDError as error:
            return steam_popup("SteamID 확인 실패", str(error))
        return steam_popup("SteamID 확인 완료", "인증된 Steam 플랫폼 사용자 ID입니다.",
                           steam_id=steam_id, origin=origin)

    @app.get("/api/auth/me")
    def me(request: Request):
        return auth.require(request, allow_initial=True)

    @app.get("/api/config")
    def get_config(request: Request):
        auth.require(request)
        return service.public_config()

    @app.post("/api/config")
    def save_config(request: Request, payload: dict = Body(...)):
        auth.require(request)
        return service.save_config(payload)

    @app.get("/api/discord")
    def get_discord_config(request: Request):
        auth.require(request)
        return {"status": "ok", "config": service.discord.public()}

    @app.post("/api/discord")
    def save_discord_config(payload: DiscordConfigUpdate, request: Request):
        auth.require(request)
        config = service.discord.save(payload.model_dump())
        return {"status": "ok", "message": "Discord 연동 설정을 저장했습니다.", "config": config}

    @app.post("/api/discord/test")
    def test_discord_config(request: Request):
        auth.require(request)
        try:
            service.test_discord()
        except ValueError:
            raise
        except Exception as error:
            raise HTTPException(502, str(error)) from error
        return {"status": "sent", "message": "Discord 테스트 메시지를 전송했습니다."}

    @app.get("/api/server/status")
    @app.get("/api/install/status")
    def status(request: Request):
        auth.require(request)
        return service.status()

    @app.get("/api/install/check")
    def install_check(request: Request):
        auth.require(request)
        service.require_stopped()
        return service.engine_update_check(force=True)

    @app.post("/api/install")
    def install(request: Request, tasks: BackgroundTasks):
        auth.require(request)
        service.require_stopped()
        update = service.engine_update_check()
        if update["installed"] and not update["update_available"]:
            return {**update, "status": "current", "message": "이미 엔진이 최신 버전입니다"}
        return queued(request, tasks, "엔진 설치·업데이트", service.install)

    @app.post("/api/server/{action}")
    def server_action(action: Literal["start", "stop", "restart"], request: Request, tasks: BackgroundTasks):
        auth.require(request)
        if action in {"start", "restart"}:
            if not service.engine()["installed"]:
                raise HTTPException(409, "먼저 엔진 설치를 완료해주세요.")
            server_arguments(service.config())
        names = {"start": "서버 시작", "stop": "서버 중지", "restart": "서버 재시작"}
        return queued(request, tasks, names[action], getattr(service, action))

    @app.get("/api/logs")
    def logs(request: Request, kind: Literal["server", "install", "control"] = "server"):
        auth.require(request)
        return {"log": service.logs(kind)}

    @app.get("/api/logs/export")
    def export_support_logs(request: Request):
        auth.require(request)
        filename = f"techtim-valheim-support-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
        return Response(
            service.support_log_report(),
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/server/resources")
    def resources(request: Request):
        auth.require(request)
        return service.resources()

    @app.get("/api/worlds")
    def list_worlds(request: Request):
        auth.require(request)
        return {"worlds": worlds(service.saves), "selected": service.config().world}

    @app.get("/api/server-files")
    def list_server_files(request: Request, path: str = ""):
        auth.require(request)
        service.require_stopped()
        target = server_file_path(path)
        if not target.exists():
            raise FileNotFoundError("경로를 찾을 수 없습니다.")
        if not target.is_dir():
            raise ValueError("폴더 경로만 열 수 있습니다.")
        entries = []
        for child in target.iterdir():
            try:
                if child.is_symlink():
                    continue
                entries.append(server_file_entry(child))
            except OSError:
                continue
        entries.sort(key=lambda item: (item["type"] != "dir", item["name"].casefold()))
        relative = server_file_relative(target) if target != service.server.resolve() else ""
        parent = server_file_relative(target.parent) if relative else ""
        return {"status": "ok", "root": "/server", "path": relative, "parent": parent, "entries": entries}

    @app.get("/api/server-files/download")
    def download_server_file(request: Request, path: str):
        auth.require(request)
        service.require_stopped()
        target = server_file_path(path)
        if not target.is_file():
            raise FileNotFoundError("다운로드할 파일을 찾을 수 없습니다.")
        return FileResponse(target, filename=target.name, media_type="application/octet-stream")

    @app.get("/api/server-files/text")
    def read_server_text_file(request: Request, path: str):
        auth.require(request)
        service.require_stopped()
        target, content = editable_server_text_file(path)
        return {"status": "ok", "path": server_file_relative(target), "name": target.name,
                "content": content, "size": target.stat().st_size}

    @app.put("/api/server-files/text")
    def update_server_text_file(payload: FileExplorerTextUpdate, request: Request, path: str):
        auth.require(request)
        with service.operation("서버 설정 파일 저장"):
            service.require_stopped()
            target, _content = editable_server_text_file(path)
            size = write_server_text_file(target, payload.content)
        return {"status": "ok", "path": server_file_relative(target), "name": target.name,
                "size": size, "message": "파일을 저장했습니다."}

    @app.post("/api/server-files/download-folders")
    def download_server_folders(payload: FileExplorerFolderDownload, request: Request):
        auth.require(request)
        with service.operation("서버 폴더 다운로드 준비"):
            service.require_stopped()
            root = service.server.resolve()
            targets = []
            for relative_path in dict.fromkeys(payload.paths):
                target = server_file_path(relative_path)
                if target == root or not target.is_dir():
                    raise FileNotFoundError("다운로드할 폴더를 찾을 수 없습니다.")
                if any(target.is_relative_to(parent) for parent in targets):
                    continue
                targets = [parent for parent in targets if not parent.is_relative_to(target)]
                targets.append(target)
            archive, filename = server_folder_archive(targets)
        return FileResponse(archive, filename=filename, media_type="application/zip",
                            background=BackgroundTask(archive.unlink, missing_ok=True))

    @app.post("/api/server-files/upload")
    async def upload_server_file(request: Request, path: str = "", overwrite: bool = Form(False),
                                 file: UploadFile = File(...)):
        auth.require(request)
        with service.operation("서버 파일 업로드"):
            service.require_stopped()
            target_dir = server_file_path(path)
            if not target_dir.is_dir():
                raise FileNotFoundError("업로드할 폴더를 찾을 수 없습니다.")
            target = server_file_path("/".join(filter(None, (server_file_relative(target_dir), server_file_name(file.filename)))))
            if target.is_dir():
                raise HTTPException(409, "같은 이름의 폴더가 있습니다.")
            if target.exists() and not overwrite:
                raise HTTPException(409, "같은 이름의 항목이 있습니다. 덮어쓰기를 확인해주세요.")
            temporary = tempfile.NamedTemporaryFile(prefix=".server-upload-", dir=service.root, delete=False)
            temporary_path = Path(temporary.name)
            size = 0
            try:
                with temporary:
                    while chunk := await file.read(1024 * 1024):
                        size += len(chunk)
                        if size > settings.max_upload_bytes:
                            raise HTTPException(413, "한 번에 업로드할 수 있는 최대 크기는 2GB입니다.")
                        temporary.write(chunk)
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary_path.replace(target)
            finally:
                temporary_path.unlink(missing_ok=True)
        return {"status": "ok", "message": "파일 업로드가 완료되었습니다.", "path": server_file_relative(target)}

    @app.post("/api/server-files/upload-folder")
    async def upload_server_folder(request: Request, path: str = "", overwrite: bool = Form(False),
                                   files: list[UploadFile] = File(...), relative_paths: list[str] = Form(...)):
        auth.require(request)
        with service.operation("서버 폴더 업로드"):
            service.require_stopped()
            target_dir = server_file_path(path)
            if not target_dir.is_dir():
                raise FileNotFoundError("업로드할 폴더를 찾을 수 없습니다.")
            if not files or len(files) != len(relative_paths):
                raise ValueError("업로드 파일과 폴더 경로 정보가 일치하지 않습니다.")
            targets = []
            seen = set()
            for relative_path in relative_paths:
                cleaned = str(relative_path or "").replace("\\", "/")
                if not cleaned or cleaned.startswith("/") or any(part in {"", ".", ".."} for part in cleaned.split("/")):
                    raise ValueError("폴더 업로드 경로를 확인해주세요.")
                combined = "/".join(filter(None, (server_file_relative(target_dir), cleaned)))
                target = server_file_path(combined)
                if target in seen:
                    raise ValueError("중복된 파일 경로가 포함되어 있습니다.")
                if target.is_dir():
                    raise HTTPException(409, "업로드 경로와 같은 이름의 폴더가 있습니다.")
                if target.exists() and not overwrite:
                    raise HTTPException(409, "같은 이름의 항목이 있습니다. 덮어쓰기를 확인해주세요.")
                seen.add(target)
                targets.append(target)
            with tempfile.TemporaryDirectory(prefix=".server-folder-upload-", dir=service.root) as directory:
                staged_root = Path(directory)
                staged_files = []
                total_size = 0
                for index, upload in enumerate(files):
                    staged = staged_root / str(index)
                    with staged.open("xb") as stream:
                        while chunk := await upload.read(1024 * 1024):
                            total_size += len(chunk)
                            if total_size > settings.max_upload_bytes:
                                raise HTTPException(413, "한 번에 업로드할 수 있는 최대 크기는 2GB입니다.")
                            stream.write(chunk)
                    staged_files.append(staged)
                for staged, target in zip(staged_files, targets):
                    target.parent.mkdir(parents=True, exist_ok=True)
                    staged.replace(target)
        return {"status": "ok", "message": f"폴더 업로드가 완료되었습니다. 파일 {len(targets)}개",
                "uploaded_count": len(targets)}

    @app.post("/api/server-files/mkdir")
    def create_server_directory(payload: FileExplorerCreateDirectory, request: Request):
        auth.require(request)
        with service.operation("서버 폴더 생성"):
            service.require_stopped()
            parent = server_file_path(payload.path)
            if not parent.is_dir():
                raise FileNotFoundError("폴더를 생성할 위치를 찾을 수 없습니다.")
            target = server_file_path("/".join(filter(None, (server_file_relative(parent), server_file_name(payload.name)))))
            if target.exists():
                raise HTTPException(409, "같은 이름의 항목이 있습니다.")
            target.mkdir(parents=False, exist_ok=False)
        return {"status": "ok", "message": "폴더를 생성했습니다.", "path": server_file_relative(target)}

    @app.get("/api/mods")
    def list_mods(request: Request):
        auth.require(request)
        return service.mods.public_packages()

    @app.get("/api/mods/cleanup")
    def preview_mod_cleanup(request: Request):
        auth.require(request)
        service.require_stopped()
        return service.mods.cleanup_plan()

    @app.post("/api/mods/cleanup")
    def cleanup_mods(payload: ModCleanupRequest, request: Request):
        auth.require(request)
        with service.operation("기존 모드 정리"):
            service.require_stopped()
            result = service.mods.cleanup_existing(payload.token)
        return {"status": "ok", "message": "기존 BepInEx와 모드를 정리하고 원본을 보관했습니다.", **result}

    @app.post("/api/mods/install")
    async def install_mods(request: Request, files: list[UploadFile] = File(...)):
        auth.require(request)
        if not files or len(files) > 50:
            raise ValueError("한 번에 1~50개의 모드 파일을 선택해주세요.")
        with service.operation("모드 설치"):
            service.require_stopped()
            if not service.engine()["installed"]:
                raise BusyError("서버 엔진을 먼저 설치해주세요.")
            with tempfile.TemporaryDirectory(prefix=".mod-upload-", dir=service.root) as directory:
                uploads = []
                total = 0
                for index, upload in enumerate(files):
                    name = server_file_name(upload.filename)
                    destination = Path(directory) / str(index)
                    with destination.open("xb") as stream:
                        while chunk := await upload.read(1024 * 1024):
                            total += len(chunk)
                            if total > settings.max_upload_bytes:
                                raise HTTPException(413, "한 번에 업로드할 수 있는 최대 크기는 2GB입니다.")
                            stream.write(chunk)
                    uploads.append((destination, name))
                results = service.mods.install_files(uploads)
        return {"status": "ok", "message": "모드 파일 확인을 완료했습니다.", "results": results,
                **service.mods.public_packages()}

    @app.post("/api/mods/recommended/bepinex")
    def install_recommended_bepinex(request: Request):
        auth.require(request)
        with service.operation("필수 모드 설치"):
            service.require_stopped()
            if not service.engine()["installed"]:
                raise BusyError("서버 엔진을 먼저 설치해주세요.")
            if service.mods.loader_ready():
                return {"status": "ok", "message": "BepInEx 필수 모드가 이미 설치되어 있습니다.",
                        **service.mods.public_packages()}
            loader = next((item for item in service.mods.packages() if item["is_loader"]), None)
            if loader:
                service.mods.set_enabled(loader["id"], True)
                return {"status": "ok", "message": "보관 중인 BepInEx 필수 모드를 다시 켰습니다.",
                        **service.mods.public_packages()}
            with tempfile.TemporaryDirectory(prefix=".recommended-mod-", dir=service.root) as directory:
                archive = Path(directory) / "bepinex.zip"
                try:
                    package = download_recommended_bepinex(archive)
                except RecommendedModError as error:
                    raise HTTPException(502, str(error)) from error
                results = service.mods.install_files([(archive, package["filename"])])
            if not service.mods.loader_ready():
                detail = " / ".join(item["message"] for item in results) or "설치 결과를 확인하지 못했습니다."
                raise ValueError(f"BepInEx 필수 모드를 설치하지 못했습니다. {detail}")
        return {"status": "ok", "message": f"BepInEx 필수 모드 {package['version']} 설치를 완료했습니다.",
                "results": results, **service.mods.public_packages()}

    @app.post("/api/mods/{package_id}/toggle")
    def toggle_mod(package_id: str, payload: ModToggle, request: Request):
        auth.require(request)
        with service.operation("모드 켜기" if payload.enabled else "모드 끄기"):
            service.require_stopped()
            package = service.mods.set_enabled(package_id, payload.enabled)
        return {"status": "ok", "message": f"{package['name']} 모드를 {'켰습니다' if payload.enabled else '껐습니다'}."}

    @app.post("/api/mods/{package_id}/update")
    async def update_mod(package_id: str, request: Request, file: UploadFile = File(...)):
        auth.require(request)
        name = server_file_name(file.filename)
        with service.operation("모드 업데이트"):
            service.require_stopped()
            temporary = tempfile.NamedTemporaryFile(prefix=".mod-update-", dir=service.root, delete=False)
            temporary_path = Path(temporary.name)
            size = 0
            try:
                with temporary:
                    while chunk := await file.read(1024 * 1024):
                        size += len(chunk)
                        if size > settings.max_upload_bytes:
                            raise HTTPException(413, "업로드할 수 있는 최대 크기는 2GB입니다.")
                        temporary.write(chunk)
                package = service.mods.update(package_id, temporary_path, name)
            finally:
                temporary_path.unlink(missing_ok=True)
        return {"status": "ok", "message": f"{package['name']} 모드를 업데이트했습니다."}

    @app.delete("/api/mods/{package_id}")
    def remove_mod(package_id: str, request: Request):
        auth.require(request)
        with service.operation("모드 삭제"):
            service.require_stopped()
            name = service.mods.package(package_id)["name"]
            service.mods.remove(package_id)
        return {"status": "ok", "message": f"{name} 모드를 보관함으로 이동했습니다."}

    @app.post("/api/mods/disable-all")
    def disable_all_mods(request: Request):
        auth.require(request)
        with service.operation("모드 전체 끄기"):
            service.require_stopped()
            count = service.mods.disable_all()
        return {"status": "ok", "message": f"모드 {count}개를 껐습니다. 등록 파일과 설정은 유지됩니다."}

    @app.get("/api/mods/configs")
    def list_mod_configurations(request: Request):
        auth.require(request)
        return {"files": service.mods.configuration_files()}

    @app.get("/api/mods/config")
    def read_mod_configuration(request: Request, path: str):
        auth.require(request)
        return {"path": path, "content": service.mods.read_configuration(path)}

    @app.put("/api/mods/config")
    def write_mod_configuration(payload: ModConfigurationUpdate, request: Request):
        auth.require(request)
        with service.operation("모드 설정 저장"):
            service.require_stopped()
            service.mods.write_configuration(payload.path, payload.content)
        return {"status": "ok", "message": "모드 설정을 저장하고 기존 파일을 백업했습니다."}

    @app.get("/api/mods/export")
    def export_modpack(request: Request):
        auth.require(request)
        with service.operation("모드팩 내보내기"):
            service.require_stopped()
            archive, filename = service.mods.export_pack()
        return FileResponse(archive, filename=filename, media_type="application/zip",
                            background=BackgroundTask(archive.unlink, missing_ok=True))

    @app.post("/api/mods/import")
    async def import_modpack(request: Request, file: UploadFile = File(...)):
        auth.require(request)
        name = server_file_name(file.filename)
        if Path(name).suffix.casefold() != ".zip":
            raise ValueError("TechTim 모드팩 ZIP 파일을 선택해주세요.")
        with service.operation("모드팩 가져오기"):
            service.require_stopped()
            temporary = tempfile.NamedTemporaryFile(prefix=".modpack-upload-", dir=service.root, delete=False)
            temporary_path = Path(temporary.name)
            size = 0
            try:
                with temporary:
                    while chunk := await file.read(1024 * 1024):
                        size += len(chunk)
                        if size > settings.max_upload_bytes:
                            raise HTTPException(413, "업로드할 수 있는 최대 크기는 2GB입니다.")
                        temporary.write(chunk)
                count = service.mods.import_pack(temporary_path)
            finally:
                temporary_path.unlink(missing_ok=True)
        return {"status": "ok", "message": f"모드팩에서 {count}개 패키지를 가져왔습니다. 필요한 모드를 켜주세요."}

    @app.get("/api/mods/diagnose")
    def diagnose_mods(request: Request):
        auth.require(request)
        return {"report": service.mods.diagnose()}

    @app.post("/api/worlds/upload")
    def upload_world(request: Request, db: UploadFile = File(...), fwl: UploadFile = File(...), overwrite: bool = Form(False)):
        auth.require(request)
        db_name, fwl_name = db.filename or "", fwl.filename or ""
        if not db_name.endswith(".db") or not fwl_name.endswith(".fwl") or db_name[:-3] != fwl_name[:-4]:
            raise HTTPException(400, "이름이 같은 .db와 .fwl 파일을 함께 선택해주세요.")
        name = world_name(db_name[:-3])
        with service.operation("월드 업로드"):
            service.require_stopped()
            with tempfile.TemporaryDirectory(prefix=".upload-", dir=service.root) as directory:
                staged = Path(directory)
                count = 0
                for upload, filename in ((db, db_name), (fwl, fwl_name)):
                    size = 0
                    with (staged / filename).open("xb") as stream:
                        while chunk := upload.file.read(1024 * 1024):
                            size += len(chunk)
                            count += len(chunk)
                            if count > settings.max_upload_bytes:
                                raise HTTPException(413, "월드 업로드는 합계 2GB까지 가능합니다.")
                            stream.write(chunk)
                    if not size:
                        raise HTTPException(400, "빈 월드 파일은 업로드할 수 없습니다.")
                service.import_world(staged, name, overwrite)
        return {"status": "ok", "world": name, "message": "월드를 업로드했습니다. 서버 설정에서 선택해주세요."}

    @app.get("/api/backups")
    def backups(request: Request):
        auth.require(request)
        return {"backups": service.list_backups()}

    @app.post("/api/backups")
    def backup(request: Request, tasks: BackgroundTasks):
        return queued(request, tasks, "월드 백업", service.backup)

    @app.post("/api/backups/{filename}/restore")
    def restore(filename: str, request: Request, tasks: BackgroundTasks):
        return queued(request, tasks, "월드 복원", lambda: service.restore(filename))

    @app.get("/api/backups/{filename}/download")
    def download_backup(filename: str, request: Request):
        auth.require(request)
        return FileResponse(inside(service.backups, filename, file_only=True), filename=filename, media_type="application/zip")

    @app.delete("/api/backups/{filename}")
    def delete_backup(filename: str, request: Request):
        auth.require(request)
        with service.operation("백업 삭제"):
            inside(service.backups, filename, file_only=True).unlink()
        return {"status": "ok"}

    @app.get("/api/worlds/{name}/download")
    def download_world(name: str, request: Request):
        auth.require(request)
        world_name(name)
        with service.operation("월드 다운로드 준비"):
            service.require_stopped()
            files = [inside(service.saves, f"worlds_local/{name}{ext}", file_only=True) for ext in (".db", ".fwl")]
            handle = tempfile.NamedTemporaryFile(prefix="world-", suffix=".zip", dir=service.exports, delete=False)
            archive = Path(handle.name)
            handle.close()
            try:
                with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
                    for path in files:
                        output.write(path, path.name)
            except Exception:
                archive.unlink(missing_ok=True)
                raise
        return FileResponse(archive, filename=name + ".zip", media_type="application/zip",
                            background=BackgroundTask(archive.unlink, missing_ok=True))

    @app.get("/api/permissions")
    def permissions(request: Request):
        auth.require(request)
        return service.permission_lists()

    @app.post("/api/permissions")
    def save_permissions(payload: Permissions, request: Request):
        auth.require(request)
        service.save_permissions(payload)
        return {"status": "ok"}

    @app.get("/api/restart-schedule")
    def schedule(request: Request):
        auth.require(request)
        return service.schedule()

    @app.post("/api/restart-schedule")
    def save_schedule(payload: RestartSchedule, request: Request):
        auth.require(request)
        return service.save_schedule(payload)

    @app.post("/api/panel/update")
    def update_panel(request: Request, tasks: BackgroundTasks):
        return queued(request, tasks, "웹패널 업데이트", service.update_panel)

    @app.get("/api/panel/update/status")
    def panel_update_status(request: Request):
        auth.require(request)
        return read_json(service.root / "panel-update-status.json", {"status": "idle"})

    @app.get("/api/panel/update/check")
    def panel_update_check(request: Request, force: bool = False):
        auth.require(request)
        return service.panel_update_check(force=force)

    return app


app = create_app()
