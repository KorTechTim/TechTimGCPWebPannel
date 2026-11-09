from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from threading import Event, Lock, Thread
import json
import os
import re
import shutil
import stat
import tempfile
import time
import zipfile

import docker
from docker.errors import DockerException, NotFound

from .config import (
    PANEL_VERSION, STEAM_APP_ID, BackupSchedule, DiscordConfig, RestartSchedule,
    ServerConfig, Settings,
)
from .discord_webhook import build_webhook_payload, execute_webhook, masked_webhook_url
from .storage import read_json, write_json


KST = timezone(timedelta(hours=9), name="KST")
ANSI_ESCAPE_PATTERN = re.compile(r"(?:\x1b\[|\x9b|\[)[0-?]*[ -/]*[@-~]")
MIGRATION_SCHEMA = "techtim-enshrouded-migration"
MIGRATION_VERSION = 1
READY_MARKERS = ("'HostOnline' (up)!", "Host_Online")
DISCORD_EVENT_SETTINGS = {
    "server_start": "notify_server_start",
    "server_stop": "notify_server_stop",
    "server_restart": "notify_server_restart",
    "backup": "notify_backup",
    "migration": "notify_migration",
    "error": "notify_errors",
}
DISCORD_EVENT_COLORS = {
    "server_start": 0xD28C42, "server_stop": 0x705D56,
    "server_restart": 0x4A8A82, "backup": 0x8B6E3F,
    "migration": 0x4C78A8, "error": 0xA9483E, "test": 0x5865F2,
}


class BusyError(RuntimeError):
    pass


class PanelService:
    def __init__(self, settings: Settings, docker_factory=None):
        self.settings = settings
        self.docker_factory = docker_factory or (lambda: docker.from_env(timeout=60))
        self.data = settings.data_dir
        self.server = self.data / "server"
        self.savegame = self.server / "savegame"
        self.server_logs = self.server / "logs"
        self.backups = self.data / "backups"
        self.exports = self.data / "exports"
        self.logs_dir = self.data / "panel-logs"
        self.config_path = self.data / "config.json"
        self.game_config_path = self.server / "enshrouded_server.json"
        self.schedule_path = self.data / "restart-schedule.json"
        self.backup_schedule_path = self.data / "backup-schedule.json"
        self.discord_path = self.data / "discord-config.json"
        self.operation_path = self.data / "operation.json"
        self.update_status_path = self.data / "panel-update-status.json"
        self.lock = Lock()
        self.busy = False
        self.scheduler = None
        self.maintenance = None
        self.stop_event = Event()
        self._network_sample = None
        for path in (self.server, self.savegame, self.server_logs, self.backups, self.exports, self.logs_dir):
            path.mkdir(parents=True, exist_ok=True)
        if not self.config_path.exists():
            write_json(self.config_path, ServerConfig().model_dump())
        if not self.schedule_path.exists():
            write_json(self.schedule_path, RestartSchedule().model_dump())
        if not self.backup_schedule_path.exists():
            config = self.config()
            write_json(self.backup_schedule_path, BackupSchedule(
                retention_count=config.backup_retention_count,
                retention_days=config.backup_retention_days,
            ).model_dump())
        if not self.discord_path.exists():
            write_json(self.discord_path, DiscordConfig().model_dump())
        self.render_game_config()

    def _client(self):
        return self.docker_factory()

    @contextmanager
    def client(self):
        client = self._client()
        try:
            yield client
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()

    def reserve(self, name):
        with self.lock:
            if self.busy:
                raise BusyError("다른 작업이 진행 중입니다.")
            self.busy = True
        self._operation("running", name, "작업을 시작했습니다.")
        return object()

    def run_reserved(self, _handle, name, action):
        try:
            action()
            self._operation("completed", name, "작업을 완료했습니다.")
        except Exception as error:
            self._log("control", f"[{name}] 실패: {error}")
            self._operation("failed", name, str(error))
            self.notify_discord_event("error", f"{name} 실패", str(error))
        finally:
            with self.lock:
                self.busy = False

    def _operation(self, status, name, message):
        write_json(self.operation_path, {
            "status": status, "name": name, "message": message,
            "updated_at": datetime.now(KST).isoformat(timespec="seconds"),
        })

    def _log(self, kind, message):
        timestamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        clean = self._sanitize_log_text(message).rstrip()
        if clean:
            with (self.logs_dir / f"{kind}.log").open("a", encoding="utf-8") as handle:
                handle.write(f"[{timestamp}] {clean}\n")

    @staticmethod
    def _sanitize_log_text(value):
        return ANSI_ESCAPE_PATTERN.sub("", str(value or ""))

    def logs(self, kind="all", tail=700):
        if kind == "all":
            blocks = []
            for log_kind, label in (("server", "서버"), ("install", "설치"), ("control", "작업")):
                text = self.logs(log_kind, tail=tail)
                if text and text != "아직 기록된 로그가 없습니다.":
                    blocks.extend(f"[{label}] {line}" for line in text.splitlines() if line)
            return "\n".join(blocks[-tail:]) + ("\n" if blocks else "") or "아직 기록된 로그가 없습니다."
        if kind == "server":
            try:
                with self.client() as client:
                    container = client.containers.get(self.settings.server_container)
                    return self._sanitize_log_text(container.logs(tail=tail, timestamps=True).decode(errors="replace"))
            except (NotFound, DockerException):
                pass
        path = self.logs_dir / f"{kind}.log"
        if not path.exists():
            return "아직 기록된 로그가 없습니다."
        return self._sanitize_log_text("".join(path.read_text(encoding="utf-8", errors="replace").splitlines(True)[-tail:]))

    def support_log_report(self):
        config = self.config()
        secrets = [role.password for role in config.roles]
        body = [
            "TechTim Enshrouded Support Report",
            f"generated_at={datetime.now(KST).isoformat(timespec='seconds')}",
            f"panel_version={PANEL_VERSION}",
            json.dumps(self.status(), ensure_ascii=False, indent=2),
            "\n--- combined logs ---\n",
            self.logs("all", tail=1200),
        ]
        report = "\n".join(body)
        for secret in secrets:
            if secret:
                report = report.replace(secret, "[REDACTED]")
        return re.sub(r"(?i)((?:password|token|secret)\s*[:=]\s*)([^\s,;]+)", r"\1[REDACTED]", report)

    def config(self):
        return ServerConfig.model_validate(read_json(self.config_path, ServerConfig().model_dump()))

    def schedule(self):
        return RestartSchedule.model_validate(read_json(self.schedule_path, RestartSchedule().model_dump()))

    def backup_schedule(self):
        return BackupSchedule.model_validate(read_json(self.backup_schedule_path, BackupSchedule().model_dump()))

    def discord_config(self):
        return DiscordConfig.model_validate(read_json(self.discord_path, DiscordConfig().model_dump()))

    def public_discord_config(self):
        config = self.discord_config()
        data = config.model_dump(exclude={"webhook_url"})
        data["webhook_configured"] = bool(config.webhook_url)
        data["webhook_hint"] = masked_webhook_url(config.webhook_url)
        return data

    def save_discord_config(self, payload):
        existing = self.discord_config().model_dump()
        incoming = dict(payload)
        clear = bool(incoming.pop("clear_webhook", False))
        webhook = str(incoming.get("webhook_url") or "").strip()
        if clear:
            incoming["webhook_url"] = ""
        elif not webhook:
            incoming["webhook_url"] = existing.get("webhook_url", "")
        config = DiscordConfig.model_validate({**existing, **incoming})
        write_json(self.discord_path, config.model_dump())
        return self.public_discord_config()

    def save_config(self, payload):
        self.require_stopped()
        config = ServerConfig.model_validate(payload)
        write_json(self.config_path, config.model_dump())
        self.render_game_config()
        return config

    def save_schedule(self, payload):
        schedule = RestartSchedule.model_validate(payload)
        write_json(self.schedule_path, schedule.model_dump())
        return schedule

    def save_backup_schedule(self, payload):
        schedule = BackupSchedule.model_validate(payload)
        write_json(self.backup_schedule_path, schedule.model_dump())
        config = self.config().model_copy(update={
            "backup_retention_count": schedule.retention_count,
            "backup_retention_days": schedule.retention_days,
        })
        write_json(self.config_path, config.model_dump())
        self._prune_backups()
        return schedule

    def render_game_config(self):
        current = {}
        if self.game_config_path.exists():
            current = read_json(self.game_config_path, {})
            if not isinstance(current, dict):
                raise ValueError("enshrouded_server.json 형식이 올바르지 않습니다.")
        managed = self.config().game_dict()
        # Preserve future official settings and custom gameSettings entries.
        current.update(managed)
        self.game_config_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(self.game_config_path, current)

    def container_status(self):
        try:
            with self.client() as client:
                container = client.containers.get(self.settings.server_container)
                container.reload()
                return container.status
        except (NotFound, DockerException):
            return "missing"

    def is_running(self):
        return self.container_status() in {"running", "restarting"}

    def require_stopped(self):
        if self.is_running():
            raise ValueError("서버를 중지한 뒤 변경해주세요.")

    def _mounts(self):
        return {str(self.settings.host_data_dir): {"bind": "/opt/enshrouded", "mode": "rw"}}

    def _pull_runtime(self, client):
        if self.settings.pull_runtime:
            self._log("install", f"런타임 이미지를 확인합니다: {self.settings.runtime_image}")
            client.images.pull(self.settings.runtime_image)

    def _container_options(self):
        config = self.config()
        return {
            "name": self.settings.server_container,
            "detach": True,
            "hostname": "enshrouded",
            "environment": {
                "PUID": "4711", "PGID": "4711",
                "UPDATE_CRON": "*/30 * * * *", "UPDATE_CHECK_PLAYERS": "true",
                "SERVER_NAME": config.server_name,
            },
            "volumes": self._mounts(),
            "network_mode": "host",
            "restart_policy": {"Name": "on-failure", "MaximumRetryCount": 3},
            "stop_timeout": self.settings.stop_timeout,
            "labels": {
                "com.techtim.panel": "enshrouded",
                "com.techtim.steam-app-id": STEAM_APP_ID,
            },
        }

    def _ensure_container(self, *, start=True):
        self.validate_start_requirements()
        self.render_game_config()
        with self.client() as client:
            try:
                container = client.containers.get(self.settings.server_container)
            except NotFound:
                self._pull_runtime(client)
                container = client.containers.create(self.settings.runtime_image, **self._container_options())
            if start:
                container.reload()
                if container.status != "running":
                    container.start()
            return container.id

    def install(self):
        self._log("install", "Enshrouded 1.0 Wine 서버 설치를 시작합니다.")
        self._ensure_container(start=True)
        self._log("install", "서버 컨테이너를 시작했습니다. SteamCMD 설치와 Wine 초기화를 진행합니다.")
        self.notify_discord_event("server_start", "Enshrouded 설치 및 시작", "게임 서버 설치를 시작했습니다.")

    def validate_start_requirements(self):
        config = self.config()
        placeholders = {"change-admin-password", "change-friend-password", "change-guest-password", "change-this-password"}
        if any(role.password in placeholders for role in config.roles):
            raise ValueError("역할별 접속 비밀번호를 먼저 변경해주세요.")
        return config

    def start(self):
        self._ensure_container(start=True)
        self._log("control", "서버 시작 요청을 완료했습니다.")
        self.notify_discord_event("server_start", "Enshrouded 서버 시작", "게임 서버를 시작했습니다.")

    def stop(self):
        with self.client() as client:
            try:
                container = client.containers.get(self.settings.server_container)
            except NotFound:
                return
            container.stop(timeout=self.settings.stop_timeout)
        self._log("control", "서버를 안전하게 중지했습니다.")
        self.notify_discord_event("server_stop", "Enshrouded 서버 중지", "게임 서버를 중지했습니다.")

    def restart(self):
        with self.client() as client:
            try:
                container = client.containers.get(self.settings.server_container)
                container.restart(timeout=self.settings.stop_timeout)
            except NotFound:
                self._ensure_container(start=True)
        self._log("control", "서버를 재시작했습니다.")
        self.notify_discord_event("server_restart", "Enshrouded 서버 재시작", "게임 서버를 재시작했습니다.")

    def query_info(self):
        if not self.is_running():
            return {"reachable": False, "players": 0, "max_players": self.config().slot_count}
        try:
            with self.client() as client:
                container = client.containers.get(self.settings.server_container)
                script = (
                    "import a2s,json; i=a2s.info(('127.0.0.1',%d),timeout=1.5); "
                    "print(json.dumps({'players':i.player_count,'max_players':i.max_players,"
                    "'name':i.server_name,'version':i.version}))" % self.config().query_port
                )
                result = container.exec_run(["python3", "-c", script])
                if result.exit_code != 0:
                    raise RuntimeError(result.output.decode(errors="replace"))
                payload = json.loads(result.output.decode())
            return {"reachable": True, **payload}
        except Exception:
            return {"reachable": False, "players": None, "max_players": self.config().slot_count}

    def status(self):
        container = self.container_status()
        recent = self.logs("server", tail=100) if container == "running" else ""
        query = self.query_info() if container == "running" else {
            "reachable": False, "players": 0, "max_players": self.config().slot_count,
        }
        ready = bool(query.get("reachable")) or any(marker in recent for marker in READY_MARKERS)
        operation = read_json(self.operation_path, {"status": "idle", "name": "", "message": ""})
        return {
            "game": "enshrouded", "panel_version": PANEL_VERSION,
            "server": container, "installed": container != "missing",
            "ready": ready, "busy": self.busy, "operation": operation,
            "query": query, "server_name": self.config().server_name,
            "runtime_image": self.settings.runtime_image,
        }

    @staticmethod
    def _proc_cpu():
        values = Path("/host/proc/stat").read_text().splitlines()[0].split()[1:]
        numbers = [int(value) for value in values]
        return sum(numbers), numbers[3] + (numbers[4] if len(numbers) > 4 else 0)

    @staticmethod
    def _proc_memory():
        fields = {}
        for line in Path("/host/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            fields[key] = int(value.strip().split()[0]) * 1024
        total = fields.get("MemTotal", 0)
        available = fields.get("MemAvailable", fields.get("MemFree", 0))
        return total, max(0, total - available)

    def resources(self):
        cpu = memory_total = memory_used = 0
        try:
            total, idle = self._proc_cpu()
            previous = getattr(self, "_cpu_sample", None)
            self._cpu_sample = (total, idle)
            if previous and total > previous[0]:
                cpu = max(0, min(100, (1 - (idle - previous[1]) / (total - previous[0])) * 100))
            memory_total, memory_used = self._proc_memory()
        except (FileNotFoundError, ValueError, IndexError):
            pass
        disk = shutil.disk_usage(self.data)
        return {
            "cpu_percent": round(cpu, 1),
            "memory_used": memory_used, "memory_total": memory_total,
            "memory_percent": round(memory_used / memory_total * 100, 1) if memory_total else 0,
            "disk_used": disk.used, "disk_total": disk.total,
            "disk_percent": round(disk.used / disk.total * 100, 1) if disk.total else 0,
        }

    def create_backup(self, reason="manual", allow_running=True):
        timestamp = datetime.now(KST).strftime("%Y%m%d-%H%M%S")
        destination = self.backups / f"enshrouded-{reason}-{timestamp}.zip"
        temporary = destination.with_suffix(".partial")
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
            archive.writestr("savegame/", b"")
            for path in (self.game_config_path, *sorted(self.savegame.rglob("*"))):
                if path.is_symlink():
                    raise ValueError("심볼릭 링크가 포함된 데이터는 백업할 수 없습니다.")
                if path.is_file():
                    archive.write(path, path.relative_to(self.server).as_posix())
        temporary.replace(destination)
        self._prune_backups()
        self._log("control", f"백업을 생성했습니다: {destination.name}")
        self.notify_discord_event("backup", "Enshrouded 백업 완료", destination.name)
        return destination

    def backups_list(self):
        result = []
        for path in sorted(self.backups.glob("*.zip"), key=lambda item: item.stat().st_mtime, reverse=True):
            result.append({"name": path.name, "size": path.stat().st_size, "modified_at": path.stat().st_mtime})
        return result

    def restore_backup(self, name):
        self.require_stopped()
        source = self._safe_named_file(self.backups, name)
        self.create_backup("before-restore", allow_running=False)
        with tempfile.TemporaryDirectory(dir=self.data) as temporary:
            stage = Path(temporary) / "server"
            stage.mkdir()
            self._safe_extract(source, stage, allowed_prefixes={"savegame", "enshrouded_server.json"})
            if not (stage / "enshrouded_server.json").is_file():
                raise ValueError("백업에 서버 설정 파일이 없습니다.")
            if self.savegame.exists():
                shutil.rmtree(self.savegame)
            shutil.copytree(stage / "savegame", self.savegame, dirs_exist_ok=True)
            shutil.copy2(stage / "enshrouded_server.json", self.game_config_path)
        self._log("control", f"백업을 복원했습니다: {name}")

    def _prune_backups(self):
        schedule = self.backup_schedule()
        files = sorted(self.backups.glob("*.zip"), key=lambda item: item.stat().st_mtime, reverse=True)
        cutoff = time.time() - schedule.retention_days * 86400
        for index, path in enumerate(files):
            if index >= schedule.retention_count or (path.stat().st_mtime < cutoff and index >= self.settings.storage_min_backups):
                path.unlink(missing_ok=True)

    @staticmethod
    def _safe_named_file(root, name):
        if Path(name).name != name or not name.endswith(".zip"):
            raise ValueError("파일 이름을 확인해주세요.")
        path = root / name
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(name)
        return path

    @staticmethod
    def _safe_extract(source, destination, *, allowed_prefixes=None, max_bytes=8 * 1024**3):
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist()
            total = sum(item.file_size for item in entries)
            if len(entries) > 20000 or total > max_bytes:
                raise ValueError("압축파일의 크기 또는 파일 수가 제한을 초과했습니다.")
            for item in entries:
                pure = PurePosixPath(item.filename)
                if pure.is_absolute() or ".." in pure.parts or "\\" in item.filename:
                    raise ValueError("압축파일에 안전하지 않은 경로가 있습니다.")
                if stat.S_ISLNK(item.external_attr >> 16) or item.flag_bits & 1:
                    raise ValueError("링크 또는 암호화 파일은 가져올 수 없습니다.")
                if allowed_prefixes and pure.parts and pure.parts[0] not in allowed_prefixes:
                    raise ValueError("지원하지 않는 파일이 포함되어 있습니다.")
            archive.extractall(destination)

    def create_migration_archive(self):
        timestamp = datetime.now(KST).strftime("%Y%m%d-%H%M%S")
        destination = self.exports / f"techtim-enshrouded-migration-{timestamp}.zip"
        temporary = destination.with_suffix(".partial")
        manifest = {
            "schema": MIGRATION_SCHEMA, "schema_version": MIGRATION_VERSION,
            "panel_version": PANEL_VERSION,
            "created_at": datetime.now(KST).isoformat(timespec="seconds"),
            "contents": ["world save", "server settings", "panel settings", "schedules", "discord settings"],
        }
        files = [
            (self.config_path, "panel/config.json"),
            (self.schedule_path, "panel/restart-schedule.json"),
            (self.backup_schedule_path, "panel/backup-schedule.json"),
            (self.discord_path, "panel/discord-config.json"),
            (self.game_config_path, "server/enshrouded_server.json"),
        ]
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
            archive.writestr("migration-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            archive.writestr("server/savegame/", b"")
            for source, target in files:
                if source.is_file():
                    archive.write(source, target)
            for source in sorted(self.savegame.rglob("*")):
                if source.is_symlink():
                    raise ValueError("세이브에 심볼릭 링크가 포함되어 있습니다.")
                if source.is_file():
                    archive.write(source, f"server/savegame/{source.relative_to(self.savegame).as_posix()}")
        temporary.replace(destination)
        self._log("control", f"이사 내보내기 파일을 생성했습니다: {destination.name}")
        self.notify_discord_event("migration", "이사 파일 생성 완료", destination.name)
        return destination

    def import_migration_archive(self, source):
        self.require_stopped()
        with tempfile.TemporaryDirectory(dir=self.data) as temporary:
            stage = Path(temporary) / "migration"
            stage.mkdir()
            self._safe_extract(source, stage, allowed_prefixes={"migration-manifest.json", "panel", "server"})
            manifest = read_json(stage / "migration-manifest.json", {})
            if manifest.get("schema") != MIGRATION_SCHEMA or manifest.get("schema_version") != MIGRATION_VERSION:
                raise ValueError("TechTim Enshrouded 이사 파일이 아닙니다.")
            required_files = (
                stage / "panel/config.json",
                stage / "panel/restart-schedule.json",
                stage / "panel/backup-schedule.json",
                stage / "panel/discord-config.json",
                stage / "server/enshrouded_server.json",
            )
            if not all(path.is_file() and not path.is_symlink() for path in required_files):
                raise ValueError("이사 파일에 필수 설정 파일이 없습니다.")
            panel_config = ServerConfig.model_validate(read_json(stage / "panel/config.json", {}))
            RestartSchedule.model_validate(read_json(stage / "panel/restart-schedule.json", {}))
            BackupSchedule.model_validate(read_json(stage / "panel/backup-schedule.json", {}))
            DiscordConfig.model_validate(read_json(stage / "panel/discord-config.json", {}))
            game_config = read_json(stage / "server/enshrouded_server.json", {})
            if not isinstance(game_config, dict) or not (stage / "server/savegame").is_dir():
                raise ValueError("이사 파일에 세이브 또는 공식 서버 설정이 없습니다.")
            self.create_backup("before-migration", allow_running=False)
            write_json(self.config_path, panel_config.model_dump())
            for name, target in (
                ("restart-schedule.json", self.schedule_path),
                ("backup-schedule.json", self.backup_schedule_path),
                ("discord-config.json", self.discord_path),
            ):
                shutil.copy2(stage / "panel" / name, target)
            if self.savegame.exists():
                shutil.rmtree(self.savegame)
            shutil.copytree(stage / "server/savegame", self.savegame)
            shutil.copy2(stage / "server/enshrouded_server.json", self.game_config_path)
            self.render_game_config()
        self._log("control", "새 Google Cloud 계정의 데이터를 성공적으로 가져왔습니다.")
        self.notify_discord_event("migration", "이사 가져오기 완료", "세이브와 설정을 복원했습니다.")

    def notify_discord_event(self, event, title, message, fields=None):
        config = self.discord_config()
        setting = DISCORD_EVENT_SETTINGS.get(event)
        if not config.enabled or not config.webhook_url or (setting and not getattr(config, setting)):
            return
        try:
            payload = build_webhook_payload(
                username=config.username, title=title, description=message,
                color=DISCORD_EVENT_COLORS.get(event, 0xD28C42), fields=fields or [],
            )
            execute_webhook(config.webhook_url, payload)
        except Exception as error:
            self._log("control", f"Discord 알림 실패: {error}")

    def deliver_discord_event(self, event, title, message, fields=None):
        config = self.discord_config()
        if not config.webhook_url:
            raise ValueError("Discord 웹훅 URL을 먼저 저장해주세요.")
        payload = build_webhook_payload(
            username=config.username, title=title, description=message,
            color=DISCORD_EVENT_COLORS.get(event, 0xD28C42), fields=fields or [],
        )
        execute_webhook(config.webhook_url, payload)

    def start_scheduler(self):
        if not self.settings.scheduler_enabled or self.scheduler:
            return
        self.scheduler = Thread(target=self._scheduler_loop, daemon=True, name="enshrouded-scheduler")
        self.scheduler.start()

    def _scheduler_loop(self):
        last_keys = set()
        while not self.stop_event.wait(20):
            now = datetime.now(KST)
            minute_key = now.strftime("%Y-%m-%d %H:%M")
            active = set()
            try:
                backup = self.backup_schedule()
                for backup_time in backup.times if backup.enabled else []:
                    key = f"backup:{minute_key}:{backup_time}"
                    if now.strftime("%H:%M") == backup_time:
                        active.add(key)
                        if key not in last_keys and not self.busy:
                            handle = self.reserve("예약 백업")
                            Thread(target=self.run_reserved, args=(handle, "예약 백업", lambda: self.create_backup("scheduled")), daemon=True).start()
                restart = self.schedule()
                key = f"restart:{minute_key}"
                if restart.enabled and now.weekday() in restart.weekdays and now.strftime("%H:%M") == restart.time:
                    active.add(key)
                    players = self.query_info().get("players")
                    if key not in last_keys and not self.busy and not (restart.skip_when_players_online and players):
                        handle = self.reserve("예약 재시작")
                        Thread(target=self.run_reserved, args=(handle, "예약 재시작", self.restart), daemon=True).start()
                last_keys = active
            except Exception as error:
                self._log("control", f"예약 작업 확인 실패: {error}")

    def panel_update_status(self):
        return read_json(self.update_status_path, {
            "status": "idle", "stage": "idle", "progress": 0,
            "message": "업데이트 준비가 완료되었습니다.", "version": PANEL_VERSION,
        })

    def update_panel(self):
        # The helper implementation is shared with the other TechTim panels.
        from . import self_update
        write_json(self.update_status_path, {
            "status": "queued", "stage": "pull", "progress": 5,
            "message": "새 패널 이미지를 확인하고 있습니다.", "version": PANEL_VERSION,
        })
        with self.client() as client:
            client.images.pull(self.settings.panel_image)
            helper_image = self.settings.panel_image
            client.containers.run(
                helper_image,
                command=["python", "-m", "app.self_update"],
                detach=True,
                remove=True,
                environment={
                    "TARGET_CONTAINER": self.settings.panel_container,
                    "TARGET_IMAGE": self.settings.panel_image,
                    "PROXY_CONTAINER": self.settings.proxy_container,
                },
                volumes={
                    "/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"},
                    str(self.settings.host_data_dir): {"bind": "/update-data", "mode": "rw"},
                },
            )
