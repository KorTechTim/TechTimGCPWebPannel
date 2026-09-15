from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import fcntl
import json
import re
import secrets
import shutil
import tempfile
import threading
import time

import docker
from docker.types import LogConfig

from .config import PANEL_VERSION, Permissions, RestartSchedule, ServerConfig, Settings, server_arguments, world_name
from .storage import create_archive, extract_archive, inside, read_json, replace_directory, worlds, write_bytes, write_json

KST = timezone(timedelta(hours=9), name="KST")
LABELS = {"kr.techtim.game": "valheim", "kr.techtim.managed": "true"}
RUNNING = {"running", "restarting", "paused", "removing"}
PERMISSION_FILES = {"admin": "adminlist.txt", "banned": "bannedlist.txt", "permitted": "permittedlist.txt"}


class BusyError(Exception):
    pass


class PanelService:
    def __init__(self, settings: Settings, docker_factory=None):
        self.settings = settings
        self.root = settings.data_dir
        self.server = self.root / "server"
        self.saves = self.root / "saves"
        self.backups = self.root / "backups"
        self.exports = self.root / "exports"
        self.config_file = self.root / "valheim-config.json"
        self.job_file = self.root / "operation.json"
        self.schedule_file = self.root / "restart-schedule.json"
        self.installer_name = settings.server_container + "-installer"
        self.update_name = settings.panel_container + "-updater"
        self.docker_factory = docker_factory or (lambda: docker.from_env(timeout=30))
        self.lock = threading.Lock()
        self.resource_lock = threading.Lock()
        self.network_sample = None
        self.ready_identity = None
        self.join_code_identity = None
        self.join_code = ""
        self.stop_event = threading.Event()
        self.scheduler = None
        for path in (self.root, self.server, self.saves / "worlds_local", self.backups, self.exports):
            path.mkdir(parents=True, exist_ok=True)
        if not self.config_file.exists():
            write_json(self.config_file, ServerConfig().model_dump())

    @contextmanager
    def client(self):
        client = self.docker_factory()
        try:
            yield client
        finally:
            client.close()

    @staticmethod
    def container(client, name):
        try:
            found = client.containers.get(name)
        except docker.errors.NotFound:
            return None
        if any(found.labels.get(key) != value for key, value in LABELS.items()):
            raise BusyError(f"같은 이름의 다른 컨테이너가 있습니다: {name}")
        found.reload()
        return found

    def config(self):
        return ServerConfig.model_validate(read_json(self.config_file, {}))

    def public_config(self):
        config = self.config().model_dump()
        config["password_set"] = bool(config.pop("password"))
        return config

    def save_config(self, payload: dict):
        with self.operation("설정 저장"):
            self.require_stopped()
            merged = self.config().model_dump()
            merged.update(payload)
            config = ServerConfig.model_validate(merged)
            write_json(self.config_file, config.model_dump())
        return self.public_config()

    def log(self, message, kind="control"):
        text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", str(message))
        password = self.config().password
        if password:
            text = text.replace(password, "[비밀번호 숨김]")
        path = self.root / f"{kind}.log"
        if path.exists() and path.stat().st_size > 2 * 1024**2:
            path.replace(path.with_suffix(".log.1"))
        with path.open("a", encoding="utf-8") as stream:
            stream.write(f"[{datetime.now(KST).isoformat(timespec='seconds')}] {text}\n")

    def job(self, status, name, message):
        write_json(self.job_file, {"status": status, "name": name, "message": str(message),
                                   "updated_at": datetime.now(KST).isoformat(timespec="seconds")})

    def reserve(self, name):
        if not self.lock.acquire(blocking=False):
            raise BusyError("다른 작업이 진행 중입니다. 완료 후 다시 시도해주세요.")
        handle = None
        try:
            handle = (self.root / ".maintenance.lock").open("a")
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise BusyError("다른 패널 작업이 진행 중입니다.")
            with self.client() as client:
                for helper in (self.installer_name, self.update_name):
                    existing = self.container(client, helper)
                    if existing and existing.status in RUNNING:
                        raise BusyError("설치 또는 패널 업데이트가 진행 중입니다.")
            self.job("running", name, f"{name} 작업을 진행하고 있습니다.")
            return handle
        except BaseException:
            if handle:
                handle.close()
            self.lock.release()
            raise

    @contextmanager
    def operation(self, name):
        handle = self.reserve(name)
        try:
            yield
            self.job("completed", name, f"{name} 완료")
        except Exception as error:
            self.job("failed", name, str(error))
            raise
        finally:
            handle.close()
            self.lock.release()

    def run_reserved(self, handle, name, action):
        try:
            action()
            self.job("completed", name, f"{name} 완료")
        except Exception as error:
            self.log(f"{name} 실패: {error}")
            self.job("failed", name, str(error))
        finally:
            handle.close()
            self.lock.release()

    def require_stopped(self):
        with self.client() as client:
            server = self.container(client, self.settings.server_container)
            if server and server.status in RUNNING:
                raise BusyError("서버를 중지한 뒤 변경해주세요. 월드 저장이 끝나야 합니다.")

    def engine(self):
        marker = self.server / ".techtim-installed.json"
        binary = self.server / "valheim_server.x86_64"
        marker_data = read_json(marker, {}) if marker.is_file() else {}
        installed = (
            binary.is_file()
            and binary.stat().st_size > 0
            and str(marker_data.get("app_id") or "") == "896660"
            and str(marker_data.get("runtime_user") or "") == "valheim"
        )
        build_id = ""
        manifest = self.server / "steamapps" / "appmanifest_896660.acf"
        if manifest.is_file():
            match = re.search(r'"buildid"\s+"(\d+)"', manifest.read_text(errors="replace"))
            build_id = match.group(1) if match else ""
        return {"installed": installed, "build_id": build_id, "branch": "Steam 정식 배포"}

    def status(self):
        config = self.config()
        result = {"engine": self.engine(), "panel_version": PANEL_VERSION,
                  "world": config.world, "crossplay": config.crossplay,
                  "port": config.port, "join_code": "", "max_players": 10,
                  "operation": read_json(self.job_file, {"status": "idle"}),
                  "server_status": "missing", "ready": False, "busy": self.lock.locked()}
        try:
            with self.client() as client:
                client.ping()
                server = self.container(client, self.settings.server_container)
                result["docker_available"] = True
                for name in (self.installer_name, self.update_name):
                    helper = self.container(client, name)
                    if helper and helper.status in RUNNING:
                        result["busy"] = True
                if server:
                    result["server_status"] = server.status
                    logs = server.logs(tail=150).decode(errors="replace")
                    identity = (server.id, server.attrs.get("State", {}).get("StartedAt"))
                    if self.join_code_identity != identity:
                        self.join_code_identity = identity
                        self.join_code = ""
                    codes = re.findall(r"\bjoin code\s+[\"']?([A-Z0-9]{4,12})\b", logs, re.I)
                    if codes:
                        self.join_code = codes[-1]
                    if server.status == "running" and "Game server connected" in logs:
                        self.ready_identity = identity
                    result["ready"] = server.status == "running" and self.ready_identity == identity
                    if server.status == "running" and config.crossplay:
                        result["join_code"] = self.join_code
                    version = re.search(r"Valheim version[:\s]+([\d.]+)", logs, re.I)
                    result["game_version"] = version.group(1) if version else ""
                    result["oom_killed"] = bool(server.attrs.get("State", {}).get("OOMKilled"))
            if not result["busy"] and result["operation"]["status"] == "running":
                result["operation"] = {"status": "interrupted", "message": "이전 패널 작업이 종료되었습니다. 설치 상태와 로그를 확인해주세요."}
        except Exception as error:
            result.update(docker_available=False, server_status="unavailable", message=str(error))
        return result

    def install(self):
        self.require_stopped()
        if worlds(self.saves):
            self.backup("before-update")
        write_bytes(self.root / "install.log", b"")
        self.log("Steam 정식 브랜치의 Valheim Dedicated Server 설치를 시작합니다.", "install")
        # Invalidate before updating binaries, so interrupted updates cannot be started.
        (self.server / ".techtim-installed.json").unlink(missing_ok=True)
        with self.client() as client:
            self.log("서버 실행 환경 이미지를 다운로드하고 있습니다.", "install")
            if self.settings.pull_runtime:
                repository, tag = docker.utils.parse_repository_tag(self.settings.runtime_image)
                for event in client.api.pull(repository, tag=tag or "latest", stream=True, decode=True):
                    if event.get("error"):
                        raise RuntimeError(event["error"])
                    if event.get("status") and not event.get("progressDetail"):
                        self.log(event["status"], "install")
            else:
                client.images.get(self.settings.runtime_image)
            old = self.container(client, self.installer_name)
            if old:
                old.remove()
            installer = client.containers.run(
                self.settings.runtime_image, command=["install"], name=self.installer_name,
                detach=True, labels=LABELS, init=True,
                volumes={str(self.settings.host_data_dir / "server"): {"bind": "/server", "mode": "rw"}},
                log_config=LogConfig(type="json-file", config={"max-size": "10m", "max-file": "2"}),
            )
            deadline = time.monotonic() + self.settings.install_timeout
            cursor = 0
            while True:
                output = installer.logs()
                if len(output) < cursor:
                    cursor = 0
                if len(output) > cursor:
                    self.log(output[cursor:].decode(errors="replace").rstrip(), "install")
                    cursor = len(output)
                installer.reload()
                if installer.status not in {"running", "created"}:
                    exit_code = installer.attrs.get("State", {}).get("ExitCode", -1)
                    if exit_code != 0 or not self.engine()["installed"]:
                        raise RuntimeError("SteamCMD 설치를 완료하지 못했습니다. 설치 로그를 확인하고 다시 설치해주세요.")
                    installer.remove()
                    break
                if time.monotonic() > deadline:
                    raise RuntimeError("설치 대기 시간이 초과되었습니다. 진행 중인 설치 컨테이너가 종료된 후 다시 확인해주세요.")
                time.sleep(2)
        self.log("공식 서버 설치 완료. 설정을 저장한 뒤 서버를 시작해주세요.", "install")

    def start(self):
        self.require_stopped()
        if not self.engine()["installed"]:
            raise BusyError("먼저 엔진 설치를 완료해주세요.")
        config = self.config()
        arguments = server_arguments(config)
        selected = next((w for w in worlds(self.saves) if w["name"] == config.world), None)
        if selected and not selected["complete"]:
            raise ValueError("선택한 월드의 .db 또는 .fwl 파일이 없습니다. 두 파일을 함께 업로드해주세요.")
        with self.client() as client:
            image = client.images.get(self.settings.runtime_image)
            old = self.container(client, self.settings.server_container)
            if old:
                old.remove()  # Never force-remove a running game container.
            client.containers.run(
                image.id, command=arguments, name=self.settings.server_container, detach=True,
                init=True, stop_signal="SIGINT", labels=LABELS,
                restart_policy={"Name": "unless-stopped"},
                volumes={
                    str(self.settings.host_data_dir / "server"): {"bind": "/server", "mode": "rw"},
                    str(self.settings.host_data_dir / "saves"): {"bind": "/saves", "mode": "rw"},
                },
                ports={f"{port}/udp": port for port in (config.port, config.port + 1)},
                cap_drop=["ALL"], security_opt=["no-new-privileges:true"],
                log_config=LogConfig(type="json-file", config={"max-size": "10m", "max-file": "3"}),
            )
        self.log(f"월드 '{config.world}' 시작 요청 완료. Game server connected 로그를 기다려주세요.")

    def stop(self):
        with self.client() as client:
            server = self.container(client, self.settings.server_container)
            if not server or server.status not in RUNNING:
                return
            if server.status == "paused":
                server.unpause()
            server.update(restart_policy={"Name": "no"})
            # The official manual specifies Ctrl+C. Do not silently escalate to SIGKILL.
            server.kill(signal="SIGINT")
            self.log("정상 종료 신호 전송. 월드 저장과 프로세스 종료를 기다립니다.")
            deadline = time.monotonic() + self.settings.stop_timeout
            while True:
                server.reload()
                if server.status in {"exited", "dead"}:
                    self.log("서버 프로세스 종료 확인. 월드 파일을 관리할 수 있습니다.")
                    return
                if time.monotonic() >= deadline:
                    raise BusyError("종료를 아직 확인하지 못했습니다. 서버 로그를 확인해주세요. 강제 종료하지 않았습니다.")
                time.sleep(1)

    def restart(self):
        self.stop()
        self.start()

    def backup(self, reason="manual"):
        self.require_stopped()
        if not worlds(self.saves):
            raise ValueError("백업할 월드 파일이 없습니다.")
        name = f"valheim-{datetime.now(KST):%Y%m%d-%H%M%S}-{reason}-{secrets.token_hex(3)}.zip"
        create_archive(self.saves, self.backups / name)
        self.log(f"월드 백업 완료: {name}")
        return name

    def list_backups(self):
        return [{"name": p.name, "size": p.stat().st_size, "modified_at": p.stat().st_mtime}
                for p in sorted(self.backups.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
                if not p.is_symlink()]

    def restore(self, name):
        self.require_stopped()
        source = inside(self.backups, name, file_only=True)
        with tempfile.TemporaryDirectory(prefix=".restore-", dir=self.root) as directory:
            staged = Path(directory) / "saves"
            extract_archive(source, staged, self.settings.max_upload_bytes * 2)
            if worlds(self.saves):
                self.backup("before-restore")
            replace_directory(self.saves, staged)
        self.log(f"월드 백업 복원 완료: {name}")

    def import_world(self, staged: Path, name: str, overwrite: bool):
        world_name(name)
        self.require_stopped()
        current = self.saves / "worlds_local"
        if any((current / (name + suffix)).exists() for suffix in (".db", ".fwl")) and not overwrite:
            raise BusyError("같은 이름의 월드가 있습니다. 덮어쓰기를 선택해주세요.")
        if worlds(self.saves):
            self.backup("before-import")
        # Stage the entire directory, then replace it once so the pair changes together.
        with tempfile.TemporaryDirectory(prefix=".world-import-", dir=self.root) as directory:
            replacement = Path(directory) / "worlds_local"
            for path in current.rglob("*"):
                if path.is_symlink():
                    raise ValueError("월드 디렉터리에 심볼릭 링크가 있습니다.")
            shutil.copytree(current, replacement)
            for suffix in (".db", ".fwl"):
                shutil.copyfile(staged / (name + suffix), replacement / (name + suffix))
            replace_directory(current, replacement)
        self.log(f"월드 업로드 완료: {name}")

    def permission_lists(self):
        result = {}
        for kind, filename in PERMISSION_FILES.items():
            path = inside(self.saves, filename)
            text = path.read_text(encoding="utf-8-sig") if path.exists() else ""
            result[kind] = [line.strip() for line in text.splitlines()
                            if line.strip() and not line.strip().startswith(("//", "#"))]
        return result

    def save_permissions(self, payload: Permissions):
        with self.operation("권한 목록 저장"):
            self.require_stopped()
            target = inside(self.saves, PERMISSION_FILES[payload.kind])
            write_bytes(target, ("\n".join(payload.ids) + "\n").encode())

    def schedule(self):
        stored = read_json(self.schedule_file, {})
        config = RestartSchedule.model_validate({k: stored[k] for k in ("enabled", "times") if k in stored})
        return {**stored, **config.model_dump(), "timezone": "Asia/Seoul"}

    def save_schedule(self, config: RestartSchedule):
        with self.operation("예약 재시작 설정"):
            self.require_stopped()
            previous = self.schedule()
            write_json(self.schedule_file, {**previous, **config.model_dump()})
        return self.schedule()

    def scheduled_restart(self, now=None):
        now = now or datetime.now(KST)
        schedule = self.schedule()
        key = f"{now:%Y-%m-%d}|{now:%H:%M}"
        if not schedule["enabled"] or now.strftime("%H:%M") not in schedule["times"] or schedule.get("last_run_key") == key:
            return
        # Save before execution: a panel restart must not repeat today's restart.
        try:
            with self.operation("예약 재시작"):
                schedule.update(last_run_key=key, last_result="running")
                write_json(self.schedule_file, schedule)
                with self.client() as client:
                    server = self.container(client, self.settings.server_container)
                    running = server and server.status == "running"
                if running:
                    self.restart()
                schedule.update(last_result="completed" if running else "skipped",
                                last_message="예약 재시작 완료" if running else "서버가 꺼져 있어 건너뛰었습니다.")
                write_json(self.schedule_file, schedule)
        except BusyError as error:
            if schedule.get("last_run_key") == key:
                schedule.update(last_result="failed", last_message=str(error))
                write_json(self.schedule_file, schedule)
            # A foreground operation owns the state. Retry during this minute only.
            return
        except Exception as error:
            schedule.update(last_run_key=key, last_result="failed", last_message=str(error))
            write_json(self.schedule_file, schedule)

    def start_scheduler(self):
        def loop():
            while not self.stop_event.wait(5):
                try:
                    self.scheduled_restart()
                except Exception as error:
                    self.log(f"예약 확인 오류: {error}")
        if self.settings.scheduler_enabled:
            self.scheduler = threading.Thread(target=loop, name="valheim-scheduler", daemon=True)
            self.scheduler.start()

    def logs(self, kind):
        if kind in {"control", "install"}:
            path = self.root / f"{kind}.log"
            if not path.exists():
                return "아직 기록된 로그가 없습니다."
            with path.open("rb") as stream:
                stream.seek(max(0, path.stat().st_size - 32000))
                text = stream.read().decode(errors="replace")
        else:
            with self.client() as client:
                server = self.container(client, self.settings.server_container)
                text = server.logs(tail=200).decode(errors="replace") if server else "서버 시작 후 로그가 표시됩니다."
        password = self.config().password
        return text.replace(password, "[비밀번호 숨김]") if password else text

    def resources(self):
        disk = shutil.disk_usage(self.root)
        result = {"disk_used": disk.used, "disk_total": disk.total, "available": False}
        with self.client() as client:
            server = self.container(client, self.settings.server_container)
            if not server or server.status != "running":
                return result
            stats = server.stats(stream=False)
            cpu = stats.get("cpu_stats", {})
            previous = stats.get("precpu_stats", {})
            used = cpu.get("cpu_usage", {}).get("total_usage", 0) - previous.get("cpu_usage", {}).get("total_usage", 0)
            total = cpu.get("system_cpu_usage", 0) - previous.get("system_cpu_usage", 0)
            cores = cpu.get("online_cpus") or len(cpu.get("cpu_usage", {}).get("percpu_usage", [])) or 1
            memory = stats.get("memory_stats", {})
            cache = memory.get("stats", {}).get("inactive_file", memory.get("stats", {}).get("total_inactive_file", 0))
            networks = stats.get("networks", {}).values()
            received = sum(n.get("rx_bytes", 0) for n in networks)
            sent = sum(n.get("tx_bytes", 0) for n in stats.get("networks", {}).values())
            now = time.monotonic()
            rx = tx = 0
            with self.resource_lock:
                before = self.network_sample
                if before and before[0] == server.id and now > before[1]:
                    rx = max(0, received - before[2]) / (now - before[1])
                    tx = max(0, sent - before[3]) / (now - before[1])
                self.network_sample = (server.id, now, received, sent)
            result.update(available=True, cpu_percent=round(max(0, used / total * cores * 100), 1) if total > 0 else 0,
                          memory_used=max(0, memory.get("usage", 0) - cache), memory_total=memory.get("limit", 0),
                          network_rx=round(rx), network_tx=round(tx))
        return result

    def update_panel(self):
        status_file = self.root / "panel-update-status.json"
        try:
            self.require_stopped()
            write_json(status_file, {"status": "running", "message": "최신 패널 이미지를 확인하고 있습니다."})
            with self.client() as client:
                current = client.containers.get(self.settings.panel_container)
                current_image = current.image.id
                latest = client.images.pull(self.settings.panel_image)
                if latest.id == current_image:
                    self.log("웹패널이 이미 최신 버전입니다.")
                    write_json(status_file, {"status": "completed", "message": "이미 최신 웹패널입니다."})
                    return
                old = self.container(client, self.update_name)
                if old:
                    old.remove()
                write_json(status_file, {"status": "running", "message": "웹패널을 교체하고 있습니다."})
                client.containers.run(
                    latest.id, command=["python", "-m", "app.self_update"], name=self.update_name,
                    detach=True, auto_remove=True, labels=LABELS,
                    environment={"TARGET_CONTAINER": self.settings.panel_container,
                                 "PROXY_CONTAINER": self.settings.proxy_container,
                                 "TARGET_IMAGE": latest.id},
                    volumes={"/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"},
                             str(self.settings.host_data_dir): {"bind": "/update-data", "mode": "rw"}},
                )
        except Exception as error:
            write_json(status_file, {"status": "failed", "message": f"구동기 업데이트를 시작하지 못했습니다: {error}"})
            raise
