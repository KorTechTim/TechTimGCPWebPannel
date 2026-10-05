from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Lock, Thread
import json
import os
import re
import shutil
import sqlite3
import time
import zipfile

import docker
from docker.errors import APIError, DockerException, NotFound

from .config import (PANEL_VERSION, SERVER_PROFILE, STEAM_APP_ID, DiscordConfig,
                     SandboxConfig, ServerConfig, RestartSchedule, Settings,
                     ini_values, migrate_sandbox_payload, sandbox_values)
from .discord_webhook import (build_webhook_payload, execute_webhook,
                              masked_webhook_url, normalize_webhook_url)
from .storage import read_json, write_json

KST = timezone(timedelta(hours=9), name="KST")
DISCORD_EVENT_SETTINGS = {
    "server_start": "notify_server_start",
    "server_stop": "notify_server_stop",
    "server_restart": "notify_server_restart",
    "backup": "notify_backup",
    "error": "notify_errors",
}
DISCORD_EVENT_COLORS = {
    "server_start": 0x4F8B65,
    "server_stop": 0x96564C,
    "server_restart": 0xC58C3F,
    "backup": 0x4B8495,
    "error": 0xB7463F,
    "test": 0x5865F2,
}
DISCORD_OPERATION_EVENTS = {
    "서버 시작": ("server_start", "Project Zomboid 서버 시작", "게임 서버가 정상적으로 시작되었습니다."),
    "서버 중지": ("server_stop", "Project Zomboid 서버 중지", "게임 서버가 정상적으로 중지되었습니다."),
    "서버 재시작": ("server_restart", "Project Zomboid 서버 재시작", "게임 서버가 정상적으로 재시작되었습니다."),
    "예약 재시작": ("server_restart", "예약 재시작 완료", "예약된 게임 서버 재시작을 완료했습니다."),
    "수동 백업": ("backup", "서버 백업 완료", "세이브와 설정 파일 백업을 생성했습니다."),
    "백업 복원": ("backup", "서버 백업 복원 완료", "선택한 백업을 서버에 복원했습니다."),
}


class BusyError(RuntimeError):
    pass


class PanelService:
    def __init__(self, settings: Settings, docker_factory=None):
        self.settings = settings
        self.docker_factory = docker_factory or (lambda: docker.from_env(timeout=60))
        self.data = settings.data_dir
        self.server = self.data / "server"
        self.zomboid = self.data / "Zomboid"
        self.server_config_dir = self.zomboid / "Server"
        self.saves = self.zomboid / "Saves" / "Multiplayer" / SERVER_PROFILE
        self.database = self.zomboid / "db"
        self.backups = self.data / "backups"
        self.exports = self.data / "exports"
        self.logs_dir = self.data / "logs"
        self.config_path = self.data / "config.json"
        self.sandbox_path = self.data / "sandbox.json"
        self.schedule_path = self.data / "restart-schedule.json"
        self.discord_path = self.data / "discord-config.json"
        self.operation_path = self.data / "operation.json"
        self.update_status_path = self.data / "panel-update-status.json"
        self.lock = Lock()
        self.busy = False
        self.scheduler = None
        self.maintenance = None
        self.stop_event = Event()
        self._network_sample = None
        for path in (self.server, self.server_config_dir, self.saves, self.database,
                     self.backups, self.exports, self.logs_dir):
            path.mkdir(parents=True, exist_ok=True)
        if not self.config_path.exists():
            write_json(self.config_path, ServerConfig().model_dump())
        if not self.sandbox_path.exists():
            write_json(self.sandbox_path, SandboxConfig().model_dump())
        if not self.schedule_path.exists():
            write_json(self.schedule_path, RestartSchedule().model_dump())
        if not self.discord_path.exists():
            write_json(self.discord_path, DiscordConfig().model_dump())
        self.render_game_files()

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
            self._notify_completed_operation(name)
        except Exception as error:
            self._log("control", f"[{name}] 실패: {error}")
            self._operation("failed", name, str(error))
            self.notify_discord_event("error", f"{name} 실패", str(error))
        finally:
            with self.lock:
                self.busy = False

    @contextmanager
    def operation(self, name):
        handle = self.reserve(name)
        try:
            yield
            self._operation("completed", name, "작업을 완료했습니다.")
            self._notify_completed_operation(name)
        except Exception as error:
            self._operation("failed", name, str(error))
            self.notify_discord_event("error", f"{name} 실패", str(error))
            raise
        finally:
            del handle
            with self.lock:
                self.busy = False

    def _operation(self, status, name, message):
        write_json(self.operation_path, {"status": status, "name": name, "message": message,
                                        "updated_at": datetime.now(KST).isoformat(timespec="seconds")})

    def _log(self, kind, message):
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        with (self.logs_dir / f"{kind}.log").open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] {message.rstrip()}\n")

    def logs(self, kind="server", tail=600):
        if kind == "all":
            sections = []
            # Auto-scrolling log panels should land on the live game output.
            for log_kind, title in (("install", "설치 로그"), ("control", "작업 기록"), ("server", "서버 로그")):
                sections.extend((f"===== {title} =====", self.logs(log_kind, tail=tail).rstrip(), ""))
            return "\n".join(sections).rstrip() + "\n"
        if kind == "server":
            try:
                with self.client() as client:
                    container = client.containers.get(self.settings.server_container)
                    return container.logs(tail=tail, timestamps=True).decode(errors="replace")
            except (NotFound, DockerException):
                pass
        path = self.logs_dir / f"{kind}.log"
        if not path.exists():
            return "아직 기록된 로그가 없습니다."
        return "".join(path.read_text(encoding="utf-8", errors="replace").splitlines(True)[-tail:])

    def _redact_support_text(self, value):
        text = str(value or "")
        config = self.config()
        for secret in (config.password, config.admin_password, config.rcon_password):
            if secret:
                text = text.replace(secret, "[REDACTED]")
        return re.sub(
            r"(?i)((?:password|passwd|token|secret|authorization)\s*[:=]\s*)([^\s,;]+)",
            r"\1[REDACTED]",
            text,
        )

    def support_log_report(self):
        status = self.status()
        diagnostic = {
            "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
            "panel_version": PANEL_VERSION,
            "steam_app_id": STEAM_APP_ID,
            "runtime_image": self.settings.runtime_image,
            "server_container": self.settings.server_container,
            "profile": SERVER_PROFILE,
            "server_status": status["server"],
            "engine": status["engine"],
            "operation": status["operation"],
            "resources": self.resources(),
        }
        sections = [
            "TechTim Project Zomboid Support Log",
            "This report removes configured passwords and common secret fields.",
            "",
            "===== DIAGNOSTICS =====",
            json.dumps(diagnostic, ensure_ascii=False, indent=2, default=str),
        ]
        for kind, title in (("server", "SERVER LOG"), ("install", "INSTALL LOG"), ("control", "CONTROL LOG")):
            sections.extend(("", f"===== {title} =====", self.logs(kind, tail=5000).rstrip()))
        return self._redact_support_text("\n".join(sections).rstrip() + "\n")

    def console_command(self, command):
        command = str(command or "").strip()
        if command.startswith("/"):
            command = command[1:].lstrip()
        if not command or len(command) > 512 or any(ord(char) < 32 for char in command):
            raise ValueError("관리 명령어를 확인해주세요.")
        verb = command.split(None, 1)[0].lower()
        if verb in {"quit", "exit", "shutdown"}:
            raise ValueError("서버 종료는 서버 제어 메뉴를 이용해주세요.")
        try:
            with self.client() as client:
                container = client.containers.get(self.settings.server_container)
                container.reload()
                if container.status not in {"running", "restarting"}:
                    raise BusyError("서버가 실행 중일 때만 관리 명령을 보낼 수 있습니다.")
                result = container.exec_run(
                    ["/usr/bin/timeout", "5s", "/bin/bash", "-c",
                     'printf "%s\\n" "$PZ_COMMAND" > /tmp/zomboid-console'],
                    user="zomboid", environment={"PZ_COMMAND": command},
                )
        except NotFound as error:
            raise BusyError("서버가 실행 중일 때만 관리 명령을 보낼 수 있습니다.") from error
        if int(result.exit_code) != 0:
            detail = result.output.decode(errors="replace").strip() if result.output else ""
            raise RuntimeError(detail or "서버 콘솔에 명령을 전달하지 못했습니다.")
        self._log("control", f"[관리 터미널] {verb} 명령 전송")
        return {"status": "ok", "message": "관리 명령을 서버에 전송했습니다.", "command": command}

    def config(self):
        return ServerConfig.model_validate(read_json(self.config_path, {}))

    def sandbox_config(self):
        return SandboxConfig.model_validate(migrate_sandbox_payload(read_json(self.sandbox_path, {})))

    def schedule(self):
        return RestartSchedule.model_validate(read_json(self.schedule_path, {}))

    def discord_config(self):
        stored = read_json(self.discord_path, {})
        defaults = DiscordConfig().model_dump()
        values = {key: stored.get(key, default) for key, default in defaults.items()}
        webhook_url = str(values.get("webhook_url") or "").strip()
        if webhook_url:
            try:
                webhook_url = normalize_webhook_url(webhook_url)
            except ValueError:
                webhook_url = ""
        values["webhook_url"] = webhook_url
        return DiscordConfig.model_validate(values)

    def public_discord_config(self):
        config = self.discord_config()
        data = config.model_dump(exclude={"webhook_url"})
        data["webhook_configured"] = bool(config.webhook_url)
        data["webhook_hint"] = masked_webhook_url(config.webhook_url)
        return data

    def save_discord_config(self, payload):
        config = DiscordConfig.model_validate(payload)
        write_json(self.discord_path, config.model_dump())
        try:
            os.chmod(self.discord_path, 0o600)
        except OSError:
            pass
        return self.public_discord_config()

    def public_config(self):
        data = self.config().model_dump()
        for key in ("password", "admin_password", "rcon_password"):
            data[key] = "" if not data[key] else "********"
        return data

    @staticmethod
    def _merge_secret(existing, payload, key):
        if payload.get(key) in {None, "", "********"}:
            payload[key] = getattr(existing, key)

    def save_config(self, payload):
        self.require_stopped()
        existing = self.config()
        payload = dict(payload)
        for key in ("password", "admin_password", "rcon_password"):
            self._merge_secret(existing, payload, key)
        config = ServerConfig.model_validate(payload)
        write_json(self.config_path, config.model_dump())
        self.render_game_files()
        return self.public_config()

    def save_sandbox(self, payload):
        self.require_stopped()
        config = SandboxConfig.model_validate(payload)
        write_json(self.sandbox_path, config.model_dump())
        self.render_game_files()
        return config.model_dump()

    def save_schedule(self, payload):
        schedule = RestartSchedule.model_validate(payload)
        write_json(self.schedule_path, schedule.model_dump())
        return schedule.model_dump()

    def discord_event_fields(self, extra_fields=None):
        return [
            {"name": "서버", "value": self.config().server_name, "inline": True},
            {"name": "프로필", "value": SERVER_PROFILE, "inline": True},
            {"name": "발생 시각", "value": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST"), "inline": True},
            *(extra_fields or []),
        ]

    def deliver_discord_event(self, event, title, message, fields=None):
        config = self.discord_config()
        if not config.webhook_url:
            raise ValueError("테스트할 Discord 웹훅 URL을 먼저 저장해주세요.")
        payload = build_webhook_payload(
            username=config.username,
            title=title,
            description=message,
            color=DISCORD_EVENT_COLORS.get(event, DISCORD_EVENT_COLORS["test"]),
            fields=self.discord_event_fields(fields),
        )
        execute_webhook(config.webhook_url, payload)

    def notify_discord_event(self, event, title, message, fields=None):
        config = self.discord_config()
        setting = DISCORD_EVENT_SETTINGS.get(event)
        if not config.enabled or not config.webhook_url or (setting and not getattr(config, setting, False)):
            return

        def send():
            try:
                self.deliver_discord_event(event, title, message, fields)
            except Exception as error:
                self._log("control", f"Discord 알림 전송 실패: {error}")

        Thread(target=send, daemon=True, name=f"zomboid-discord-{event}").start()

    def _notify_completed_operation(self, name):
        event = DISCORD_OPERATION_EVENTS.get(name)
        if event:
            self.notify_discord_event(*event)

    def render_game_files(self):
        self.server_config_dir.mkdir(parents=True, exist_ok=True)
        ini = self.server_config_dir / f"{SERVER_PROFILE}.ini"
        values = ini_values(self.config())
        self._merge_key_value_file(ini, values)
        sandbox = self.server_config_dir / f"{SERVER_PROFILE}_SandboxVars.lua"
        existing = sandbox.read_text(encoding="utf-8", errors="replace") if sandbox.exists() else "SandboxVars = {\n    VERSION = 6,\n}\n"
        original_sandbox = existing
        if re.match(r"^\s*return\s*\{", existing):
            existing = re.sub(r"^\s*return\s*\{", "SandboxVars = {", existing, count=1)
        if not re.search(r"(?m)^\s*SandboxVars\s*=\s*\{", existing):
            existing = "SandboxVars = {\n    VERSION = 6,\n}\n"
        existing = re.sub(r"(?m)^(\s*VERSION\s*=\s*)\d+(,?)", r"\g<1>6\g<2>", existing, count=1)
        existing, migrated_values = self._migrate_legacy_sandbox_values(existing)
        for key, value in sandbox_values(self.sandbox_config()).items():
            existing = self._merge_sandbox_value(existing, key, value)
        if migrated_values:
            backup = sandbox.with_name(f"{sandbox.name}.legacy-flat.bak")
            if not backup.exists():
                self._atomic_text(backup, original_sandbox)
        self._atomic_text(sandbox, existing)
        if migrated_values:
            self._log("control", f"구형 샌드박스 설정 {migrated_values}개를 백업 후 Build 42 형식으로 자동 복구했습니다.")
        spawnpoints = self.server_config_dir / f"{SERVER_PROFILE}_spawnpoints.lua"
        spawnregions = self.server_config_dir / f"{SERVER_PROFILE}_spawnregions.lua"
        if not spawnpoints.exists():
            self._atomic_text(spawnpoints, "function SpawnPoints()\n    return {}\nend\n")
        if not spawnregions.exists():
            self._atomic_text(spawnregions,
                "function SpawnRegions()\n    return { { name = 'Muldraugh, KY', file = 'media/maps/Muldraugh, KY/spawnpoints.lua' } }\nend\n")

    @classmethod
    def _migrate_legacy_sandbox_values(cls, content):
        aliases = {
            "ZombieLore.DragDown": "ZombieLore.ZombiesDragDown",
            "ZombieLore.FenceLunge": "ZombieLore.ZombiesFenceLunge",
        }
        pattern = re.compile(
            r"^    (?P<table>[A-Za-z_][A-Za-z0-9_]*)\."
            r"(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>.+?)\s*,?\s*$"
        )
        kept_lines = []
        legacy_values = []
        for line in content.splitlines(keepends=True):
            match = pattern.fullmatch(line.rstrip("\r\n"))
            if not match:
                kept_lines.append(line)
                continue
            key = f"{match.group('table')}.{match.group('key')}"
            legacy_values.append((aliases.get(key, key), match.group("value")))
        migrated = "".join(kept_lines)
        for key, value in legacy_values:
            migrated = cls._merge_sandbox_value(migrated, key, value)
        return migrated, len(legacy_values)

    @staticmethod
    def _merge_sandbox_value(content, dotted_key, value):
        parts = dotted_key.split(".", 1)
        if len(parts) == 1:
            key = parts[0]
            pattern = rf"(?m)^(    {re.escape(key)}\s*=\s*).*$"
            if re.search(pattern, content):
                return re.sub(pattern, lambda match: f"{match.group(1)}{value},", content, count=1)
            closing = content.rfind("\n}")
            if closing < 0:
                raise ValueError("샌드박스 설정 파일의 끝을 찾지 못했습니다.")
            return content[:closing] + f"\n    {key} = {value}," + content[closing:]

        table, key = parts
        block_pattern = rf"(?ms)^(    {re.escape(table)}\s*=\s*\{{\n)(.*?)(^    \}},?)"
        block = re.search(block_pattern, content)
        if block:
            body = block.group(2)
            value_pattern = rf"(?m)^(        {re.escape(key)}\s*=\s*).*$"
            if re.search(value_pattern, body):
                body = re.sub(value_pattern, lambda match: f"{match.group(1)}{value},", body, count=1)
            else:
                body += f"        {key} = {value},\n"
            return content[:block.start(2)] + body + content[block.end(2):]

        closing = content.rfind("\n}")
        if closing < 0:
            raise ValueError("샌드박스 설정 파일의 끝을 찾지 못했습니다.")
        table_text = f"\n    {table} = {{\n        {key} = {value},\n    }},"
        return content[:closing] + table_text + content[closing:]

    def _merge_key_value_file(self, path, values):
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines() if path.exists() else []
        pending = dict(values)
        output = []
        for line in lines:
            if "=" not in line or line.lstrip().startswith(("#", ";")):
                output.append(line)
                continue
            key = line.split("=", 1)[0].strip()
            if key in pending:
                output.append(f"{key}={pending.pop(key)}")
            else:
                output.append(line)
        output.extend(f"{key}={value}" for key, value in pending.items())
        self._atomic_text(path, "\n".join(output).rstrip() + "\n")

    @staticmethod
    def _atomic_text(path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)

    def engine(self):
        executable = self.server / "start-server.sh"
        manifest = self.server / "steamapps" / f"appmanifest_{STEAM_APP_ID}.acf"
        build_id = "-"
        if manifest.exists():
            match = re.search(r'"buildid"\s+"([0-9]+)"', manifest.read_text(errors="ignore"))
            if match:
                build_id = match.group(1)
        return {"installed": executable.exists(), "build_id": build_id, "branch": self.config().branch}

    def container_status(self):
        try:
            with self.client() as client:
                container = client.containers.get(self.settings.server_container)
                container.reload()
                return container.status
        except NotFound:
            return "missing"
        except DockerException:
            return "unavailable"

    def is_running(self):
        return self.container_status() in {"running", "restarting"}

    def require_stopped(self):
        if self.is_running():
            raise BusyError("서버를 먼저 중지해주세요.")

    def _mounts(self):
        return {
            str(self.settings.host_data_dir / "server"): {"bind": "/server", "mode": "rw"},
            str(self.settings.host_data_dir / "Zomboid"): {"bind": "/home/zomboid/Zomboid", "mode": "rw"},
        }

    def _pull_runtime(self, client):
        if self.settings.pull_runtime:
            self._log("install", f"런타임 이미지 확인: {self.settings.runtime_image}")
            client.images.pull(self.settings.runtime_image)

    def install(self):
        self.require_stopped()
        config = self.config()
        if config.backup_before_update and self.saves.exists() and any(self.saves.iterdir()):
            self.create_backup("update")
        with self.client() as client:
            self._pull_runtime(client)
            try:
                old = client.containers.get(f"{self.settings.server_container}-installer")
                old.remove(force=True)
            except NotFound:
                pass
            container = client.containers.run(
                self.settings.runtime_image, command=["install", config.branch],
                name=f"{self.settings.server_container}-installer", detach=True,
                volumes=self._mounts(), environment={"STEAM_APP_ID": STEAM_APP_ID},
                cap_drop=["ALL"], cap_add=["CHOWN", "DAC_OVERRIDE", "SETGID", "SETUID"],
                security_opt=["no-new-privileges:true"],
            )
            try:
                for line in container.logs(stream=True, follow=True):
                    self._log("install", line.decode(errors="replace"))
                result = container.wait(timeout=self.settings.install_timeout)
                if int(result.get("StatusCode", 1)) != 0:
                    raise RuntimeError("SteamCMD 설치 또는 검증에 실패했습니다. 설치 로그를 확인해주세요.")
            finally:
                try:
                    container.remove(force=True)
                except APIError:
                    pass
        if not self.engine()["installed"]:
            raise RuntimeError("설치 후 start-server.sh를 찾지 못했습니다.")
        self.render_game_files()

    def start(self):
        if not self.engine()["installed"]:
            raise RuntimeError("먼저 엔진을 설치해주세요.")
        config = self.config()
        if not config.admin_password:
            raise ValueError("최초 관리자 비밀번호를 먼저 저장해주세요.")
        if config.backup_before_start and self.saves.exists() and any(self.saves.iterdir()):
            self.create_backup("start")
        self.render_game_files()
        with self.client() as client:
            self._pull_runtime(client)
            try:
                old = client.containers.get(self.settings.server_container)
                old.reload()
                if old.status == "running":
                    raise BusyError("서버가 이미 실행 중입니다.")
                old.remove(force=True)
            except NotFound:
                pass
            client.containers.run(
                self.settings.runtime_image,
                command=["serve", str(config.memory_gb), config.admin_password],
                name=self.settings.server_container, detach=True, network_mode="host",
                volumes=self._mounts(), environment={"SERVER_PROFILE": SERVER_PROFILE},
                restart_policy={"Name": "unless-stopped"},
                cap_drop=["ALL"], cap_add=["CHOWN", "DAC_OVERRIDE", "SETGID", "SETUID"],
                security_opt=["no-new-privileges:true"],
                labels={"com.techtim.game": "zomboid", "com.techtim.managed": "true"},
            )
        self._log("control", "서버 시작 요청 완료")

    def stop(self):
        with self.client() as client:
            try:
                container = client.containers.get(self.settings.server_container)
            except NotFound:
                return
            container.stop(timeout=self.settings.stop_timeout)
        self._log("control", "서버 정상 종료 완료")

    def restart(self):
        self.stop()
        self.start()

    def status(self):
        operation = read_json(self.operation_path, {"status": "idle", "name": "대기", "message": "작업 대기 중"})
        return {"panel_version": PANEL_VERSION, "server": self.container_status(), "engine": self.engine(),
                "operation": operation, "busy": self.busy,
                "config_ready": bool(self.config().admin_password),
                "profile": SERVER_PROFILE, "endpoint_port": self.config().default_port}

    def create_backup(self, reason="manual"):
        self.require_stopped()
        timestamp = datetime.now(KST).strftime("%Y%m%d-%H%M%S")
        target = self.backups / f"{SERVER_PROFILE}-{reason}-{timestamp}.zip"
        roots = [(self.server_config_dir, "Server"), (self.saves, f"Saves/Multiplayer/{SERVER_PROFILE}"),
                 (self.database, "db")]
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            for root, prefix in roots:
                if not root.exists():
                    continue
                for source in root.rglob("*"):
                    if source.is_file() and not source.is_symlink():
                        archive.write(source, f"{prefix}/{source.relative_to(root).as_posix()}")
        self._prune_backups()
        return {"name": target.name, "size": target.stat().st_size,
                "created": datetime.fromtimestamp(target.stat().st_mtime, KST).isoformat(timespec="seconds")}

    def backups_list(self):
        results = []
        for path in sorted(self.backups.glob("*.zip"), key=lambda item: item.stat().st_mtime, reverse=True):
            results.append({"name": path.name, "size": path.stat().st_size,
                            "created": datetime.fromtimestamp(path.stat().st_mtime, KST).isoformat(timespec="seconds")})
        return results

    def restore_backup(self, name):
        self.require_stopped()
        source = (self.backups / Path(name).name).resolve()
        if source.parent != self.backups.resolve() or not source.is_file():
            raise FileNotFoundError(name)
        self.create_backup("before-restore")
        with zipfile.ZipFile(source) as archive:
            for member in archive.infolist():
                destination = (self.zomboid / member.filename).resolve()
                if self.zomboid.resolve() not in destination.parents and destination != self.zomboid.resolve():
                    raise ValueError("안전하지 않은 백업 경로입니다.")
            archive.extractall(self.zomboid)

    def _prune_backups(self):
        config = self.config()
        backups = sorted(self.backups.glob("*.zip"), key=lambda item: item.stat().st_mtime, reverse=True)
        cutoff = time.time() - config.backup_retention_days * 86400
        for index, path in enumerate(backups):
            if index >= config.backup_retention_count or (index >= self.settings.storage_min_backups and path.stat().st_mtime < cutoff):
                path.unlink(missing_ok=True)

    @staticmethod
    def _quote_identifier(value):
        return '"' + str(value).replace('"', '""') + '"'

    def _account_schema(self, connection):
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
        for table in tables:
            quoted = self._quote_identifier(table)
            columns = [row[1] for row in connection.execute(f"PRAGMA table_info({quoted})").fetchall()]
            by_name = {name.casefold(): name for name in columns}
            username = next((by_name[key] for key in ("username", "user", "name") if key in by_name), None)
            if not username:
                continue
            return {"table": table, "username": username,
                    "steam_id": next((by_name[key] for key in ("steamid", "steam_id") if key in by_name), None),
                    "access_level": next((by_name[key] for key in ("accesslevel", "access_level") if key in by_name), None),
                    "whitelisted": next((by_name[key] for key in ("whitelisted", "whitelist") if key in by_name), None),
                    "banned": next((by_name[key] for key in ("banned", "ban") if key in by_name), None)}
        return None

    def player_accounts(self):
        path = self.database / f"{SERVER_PROFILE}.db"
        if not path.exists():
            return {"supported": False, "message": "servertest.db가 아직 생성되지 않았습니다.", "accounts": []}
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            schema = self._account_schema(connection)
            if not schema:
                return {"supported": False, "message": "지원 가능한 계정 테이블을 찾지 못했습니다.", "accounts": []}
            selected = [("username", schema["username"]), ("steam_id", schema["steam_id"]),
                        ("access_level", schema["access_level"]), ("whitelisted", schema["whitelisted"]),
                        ("banned", schema["banned"])]
            expressions = [f"{self._quote_identifier(column)} AS {alias}" if column else f"NULL AS {alias}"
                           for alias, column in selected]
            table = self._quote_identifier(schema["table"])
            username = self._quote_identifier(schema["username"])
            rows = connection.execute(f"SELECT {', '.join(expressions)} FROM {table} ORDER BY {username} COLLATE NOCASE").fetchall()
            accounts = [{"username": row[0] or "", "steam_id": row[1] or "", "access_level": row[2] or "none",
                         "whitelisted": bool(row[3]) if row[3] is not None else None,
                         "banned": bool(row[4]) if row[4] is not None else None} for row in rows]
            return {"supported": True, "message": f"{schema['table']} · {len(accounts)}개 계정", "accounts": accounts,
                    "capabilities": {key: bool(schema[key]) for key in ("steam_id", "access_level", "whitelisted", "banned")}}
        finally:
            connection.close()

    def update_player(self, username, field, value):
        self.require_stopped()
        username = str(username or "").strip()
        if not username or len(username) > 128 or any(ord(char) < 32 for char in username):
            raise ValueError("사용자 이름을 확인해주세요.")
        allowed_access = {"none", "admin", "moderator", "overseer", "gm", "observer"}
        if field == "access_level":
            value = str(value or "none").strip().lower()
            if value not in allowed_access:
                raise ValueError("지원하지 않는 권한입니다.")
        elif field in {"whitelisted", "banned"}:
            value = 1 if bool(value) else 0
        else:
            raise ValueError("지원하지 않는 계정 변경입니다.")
        path = self.database / f"{SERVER_PROFILE}.db"
        if not path.exists():
            raise FileNotFoundError(path)
        self.create_backup("database-safety")
        connection = sqlite3.connect(path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            schema = self._account_schema(connection)
            if not schema or not schema.get(field):
                raise ValueError("현재 DB 스키마는 이 계정 변경을 지원하지 않습니다.")
            table = self._quote_identifier(schema["table"])
            column = self._quote_identifier(schema[field])
            user_column = self._quote_identifier(schema["username"])
            cursor = connection.execute(f"UPDATE {table} SET {column}=? WHERE {user_column}=?", (value, username))
            if cursor.rowcount != 1:
                raise ValueError("변경할 계정을 정확히 한 개 찾지 못했습니다.")
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if str(integrity).casefold() != "ok":
                raise RuntimeError(f"DB 무결성 검사 실패: {integrity}")
            connection.commit()
            self._log("control", f"계정 변경: {username} / {field}")
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _proc_cpu():
        try:
            fields = Path("/host/proc/stat").read_text().splitlines()[0].split()[1:]
            values = [int(value) for value in fields]
            return sum(values), values[3] + (values[4] if len(values) > 4 else 0)
        except (OSError, ValueError, IndexError):
            return None

    @staticmethod
    def _proc_memory():
        try:
            values = {}
            for line in Path("/host/proc/meminfo").read_text().splitlines():
                key, value = line.split(":", 1)
                values[key] = int(value.split()[0]) * 1024
            total = values["MemTotal"]
            available = values.get("MemAvailable", values.get("MemFree", 0))
            return total, total - available
        except (OSError, ValueError, KeyError):
            return None

    @staticmethod
    def _network_bytes():
        try:
            down = up = 0
            for line in Path("/host/proc/net/dev").read_text().splitlines()[2:]:
                name, fields = line.split(":", 1)
                if name.strip() == "lo":
                    continue
                values = fields.split()
                down += int(values[0]); up += int(values[8])
            return down, up
        except (OSError, ValueError, IndexError):
            return None

    def resources(self):
        now = time.monotonic()
        cpu_sample = self._proc_cpu()
        previous = getattr(self, "_cpu_sample", None)
        cpu_percent = None
        if cpu_sample and previous:
            total_delta = cpu_sample[0] - previous[1][0]
            idle_delta = cpu_sample[1] - previous[1][1]
            if total_delta > 0:
                cpu_percent = round(max(0, min(100, 100 * (total_delta - idle_delta) / total_delta)), 1)
        if cpu_sample:
            self._cpu_sample = (now, cpu_sample)
        memory = self._proc_memory()
        usage = shutil.disk_usage(self.data)
        network = self._network_bytes()
        down_rate = up_rate = None
        if network and self._network_sample:
            seconds = max(.1, now - self._network_sample[0])
            down_rate = max(0, (network[0] - self._network_sample[1][0]) / seconds)
            up_rate = max(0, (network[1] - self._network_sample[1][1]) / seconds)
        if network:
            self._network_sample = (now, network)
        return {
            "cpu": {"percent": cpu_percent},
            "memory": {"used": memory[1] if memory else None, "total": memory[0] if memory else None,
                       "percent": round(memory[1] * 100 / memory[0], 1) if memory else None},
            "disk": {"used": usage.used, "total": usage.total, "free": usage.free,
                     "percent": round(usage.used * 100 / usage.total, 1)},
            "network": {"down": down_rate, "up": up_rate},
        }

    def cleanup_storage(self):
        usage = shutil.disk_usage(self.data)
        percent = usage.used * 100 / usage.total
        if percent < self.settings.storage_cleanup_threshold:
            return
        self._log("control", f"디스크 사용률 {percent:.1f}%: 오래된 백업과 Docker 캐시 정리")
        self._prune_backups()
        backups = sorted(self.backups.glob("*.zip"), key=lambda item: item.stat().st_mtime)
        while len(backups) > self.settings.storage_min_backups:
            usage = shutil.disk_usage(self.data)
            if usage.used * 100 / usage.total <= self.settings.storage_cleanup_target:
                break
            backups.pop(0).unlink(missing_ok=True)
        try:
            with self.client() as client:
                client.images.prune(filters={"dangling": True})
                client.containers.prune()
        except APIError as error:
            self._log("control", f"Docker 캐시 정리 건너뜀: {error}")

    def start_scheduler(self):
        if not self.settings.scheduler_enabled or self.scheduler:
            return
        self.scheduler = Thread(target=self._scheduler_loop, name="zomboid-scheduler", daemon=True)
        self.maintenance = Thread(target=self._maintenance_loop, name="zomboid-maintenance", daemon=True)
        self.scheduler.start(); self.maintenance.start()

    def _scheduler_loop(self):
        completed = set()
        while not self.stop_event.wait(20):
            now = datetime.now(KST)
            marker = now.strftime("%Y-%m-%d %H:%M")
            schedule = self.schedule()
            if schedule.enabled and now.strftime("%H:%M") in schedule.times and marker not in completed and self.is_running():
                completed.add(marker)
                try:
                    with self.operation("예약 재시작"):
                        self.restart()
                except (BusyError, Exception) as error:
                    self._log("control", f"예약 재시작 실패: {error}")
            completed = {value for value in completed if value.startswith(now.strftime("%Y-%m-%d"))}

    def _maintenance_loop(self):
        while not self.stop_event.wait(self.settings.storage_cleanup_interval):
            try:
                self.cleanup_storage()
            except Exception as error:
                self._log("control", f"스토리지 점검 실패: {error}")

    def panel_update_status(self):
        status = read_json(self.update_status_path, {})
        if status.get("status") in {"running", "downloading", "preparing", "replacing", "verifying"}:
            return {**status, "available": True, "current_version": PANEL_VERSION}
        try:
            with self.client() as client:
                image = client.images.pull(self.settings.panel_image)
                current = client.containers.get(self.settings.panel_container).image.id
                available = image.id != current
                return {**status, "available": available, "current_version": PANEL_VERSION,
                        "current_image": current.removeprefix("sha256:")[:12],
                        "latest_image": image.id.removeprefix("sha256:")[:12]}
        except DockerException as error:
            return {**status, "available": False, "current_version": PANEL_VERSION, "error": str(error)}

    def _write_panel_update_status(self, status, stage, progress, message, **extra):
        previous = read_json(self.update_status_path, {})
        started_at = previous.get("started_at")
        if status == "downloading" or not started_at:
            started_at = datetime.now(KST).isoformat(timespec="seconds")
        write_json(self.update_status_path, {
            "status": status,
            "stage": stage,
            "progress": progress,
            "message": message,
            "started_at": started_at,
            "updated_at": datetime.now(KST).isoformat(timespec="seconds"),
            **extra,
        })

    def update_panel(self):
        self._write_panel_update_status(
            "downloading", "download", 8, "최신 구동기 이미지를 다운로드하고 있습니다."
        )
        try:
            with self.client() as client:
                image = client.images.pull(self.settings.panel_image)
                image_id = image.id.removeprefix("sha256:")[:12]
                self._write_panel_update_status(
                    "preparing", "prepare", 30, "이미지 다운로드를 완료했습니다. 패널 교체를 준비합니다.",
                    image_id=image_id,
                )
                helper_name = f"{self.settings.panel_container}-updater"
                try:
                    client.containers.get(helper_name).remove(force=True)
                except NotFound:
                    pass
                client.containers.run(
                    image.id, command=["python", "-m", "app.self_update"], name=helper_name, detach=True,
                    environment={"TARGET_CONTAINER": self.settings.panel_container, "TARGET_IMAGE": self.settings.panel_image,
                                 "PROXY_CONTAINER": self.settings.proxy_container},
                    volumes={"/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"},
                             str(self.settings.host_data_dir): {"bind": "/update-data", "mode": "rw"}},
                    remove=True,
                )
        except Exception as error:
            self._write_panel_update_status(
                "failed", "failed", 0, f"업데이트를 시작하지 못했습니다: {error}"
            )
            raise
