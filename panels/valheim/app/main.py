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
from .config import PANEL_VERSION, Permissions, RestartSchedule, Settings, server_arguments, world_name
from .service import BusyError, PanelService
from .storage import inside, read_json, worlds

STATIC_DIR = Path(__file__).parent / "static"


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


def create_app(settings=None, docker_factory=None):
    settings = settings or Settings.from_env()
    service = PanelService(settings, docker_factory)
    auth = Auth(settings.data_dir)

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

    def server_file_entry(path):
        stat = path.stat()
        return {
            "name": path.name,
            "path": server_file_relative(path),
            "type": "dir" if path.is_dir() else "file",
            "size": stat.st_size if path.is_file() else 0,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
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

    @app.get("/api/server/status")
    @app.get("/api/install/status")
    def status(request: Request):
        auth.require(request)
        return service.status()

    @app.post("/api/install")
    def install(request: Request, tasks: BackgroundTasks):
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
