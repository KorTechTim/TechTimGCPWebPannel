from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
import logging
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
    new_password: str = Field(min_length=8, max_length=128)


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

    return app


app = create_app()
