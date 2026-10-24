import tempfile
import unittest
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from app.config import Settings
from app.service import KST, PanelService


class MissingContainers:
    def get(self, _name):
        from docker.errors import NotFound
        raise NotFound("missing")


class FakeClient:
    def __init__(self): self.containers = MissingContainers()
    def close(self): pass


class ConsoleContainer:
    status = "running"

    def __init__(self):
        self.exec_calls = []

    def reload(self): pass

    def exec_run(self, command, **kwargs):
        self.exec_calls.append((command, kwargs))
        return type("ExecResult", (), {"exit_code": 0, "output": b""})()


class ConsoleClient:
    def __init__(self, container):
        self.container = container
        self.containers = self

    def get(self, _name): return self.container
    def close(self): pass


class StartContainers:
    def __init__(self):
        self.run_calls = []

    def get(self, _name):
        from docker.errors import NotFound
        raise NotFound("missing")

    def run(self, image, **kwargs):
        if "stop_timeout" in kwargs:
            raise TypeError("run() got an unexpected keyword argument 'stop_timeout'")
        self.run_calls.append((image, kwargs))


class StartClient:
    def __init__(self, containers): self.containers = containers
    def close(self): pass


class InstallContainer:
    def __init__(self, status_code, on_success=None):
        self.status_code = status_code
        self.on_success = on_success
        self.removed = False

    def logs(self, **_kwargs):
        return [b"SteamCMD install output\n"]

    def wait(self, **_kwargs):
        if self.status_code == 0 and self.on_success:
            self.on_success()
        return {"StatusCode": self.status_code}

    def remove(self, **_kwargs):
        self.removed = True


class InstallContainers:
    def __init__(self, status_codes, on_success=None):
        self.status_codes = list(status_codes)
        self.on_success = on_success
        self.run_calls = []
        self.created = []

    def get(self, _name):
        from docker.errors import NotFound
        raise NotFound("missing")

    def run(self, image, **kwargs):
        self.run_calls.append((image, kwargs))
        container = InstallContainer(self.status_codes.pop(0), self.on_success)
        self.created.append(container)
        return container


class LogContainer:
    def logs(self, **_kwargs):
        return b"2026-10-05T08:00:00Z \x1b[0mlive server output\n"


class LogClient:
    def __init__(self): self.containers = self
    def get(self, _name): return LogContainer()
    def close(self): pass


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.service = PanelService(Settings(data_dir=root, host_data_dir=root, scheduler_enabled=False), lambda: FakeClient())

    def tearDown(self): self.temp.cleanup()

    def test_initial_files_are_rendered(self):
        ini = self.service.server_config_dir / "servertest.ini"
        sandbox = self.service.server_config_dir / "servertest_SandboxVars.lua"
        ini_content = ini.read_text()
        self.assertIn("DefaultPort=16261", ini_content)
        self.assertIn("AntiCheatSpeed=2", ini_content)
        self.assertIn("BackupsCount=5", ini_content)
        self.assertGreater(len(ini_content.splitlines()), 100)
        content = sandbox.read_text()
        self.assertIn("VERSION = 6", content)
        self.assertIn("ZombieConfig = {", content)
        self.assertIn("        RespawnHours =", content)
        self.assertNotIn("ZombieConfig.RespawnHours", content)
        self.assertIn("MultiplierConfig = {", content)

    def test_render_game_files_repairs_short_ini_without_overwriting_existing_values(self):
        ini = self.service.server_config_dir / "servertest.ini"
        ini.write_text(
            "Public=false\n"
            "PublicName=My Existing Server\n"
            "BackupsCount=27\n"
            "CustomModOption=keep-me\n",
            encoding="utf-8",
        )

        self.service.render_game_files()

        content = ini.read_text(encoding="utf-8")
        self.assertIn("PublicName=TechTim Project Zomboid", content)
        self.assertIn("BackupsCount=27", content)
        self.assertIn("CustomModOption=keep-me", content)
        self.assertIn("AntiCheatSpeed=2", content)
        self.assertGreater(len(content.splitlines()), 100)

    def test_legacy_dotted_sandbox_values_are_backed_up_and_migrated(self):
        sandbox = self.service.server_config_dir / "servertest_SandboxVars.lua"
        legacy = (
            "SandboxVars = {\n"
            "    VERSION = 5,\n"
            "    RearVulnerability = 3,\n"
            "    ZombieLore.DragDown = true,\n"
            "    ZombieLore.FenceLunge = true,\n"
            "    ZombieConfig.RespawnHours = 72.0,\n"
            "}\n"
        )
        sandbox.write_text(legacy, encoding="utf-8")

        self.service.render_game_files()

        content = sandbox.read_text(encoding="utf-8")
        backup = sandbox.with_name(f"{sandbox.name}.legacy-flat.bak")
        self.assertEqual(backup.read_text(encoding="utf-8"), legacy)
        self.assertNotIn("ZombieLore.DragDown =", content)
        self.assertNotIn("ZombieLore.FenceLunge =", content)
        self.assertNotIn("ZombieConfig.RespawnHours =", content)
        self.assertIn("ZombieLore = {", content)
        self.assertIn("        ZombiesDragDown = true,", content)
        self.assertIn("        ZombiesFenceLunge = true,", content)
        self.assertNotIn("        DragDown =", content)
        self.assertNotIn("        FenceLunge =", content)
        self.assertIn("ZombieConfig = {", content)
        self.assertIn("        RespawnHours = 0.0,", content)
        self.assertIn("구형 샌드박스 설정 3개를 백업 후 Build 42 형식으로 자동 복구했습니다.", self.service.logs("control"))

    def test_render_game_files_preserves_comma_delimited_string_values(self):
        sandbox = self.service.server_config_dir / "servertest_SandboxVars.lua"
        content = sandbox.read_text(encoding="utf-8")
        correct = next(line for line in content.splitlines() if "WorldItemRemovalList" in line)
        corrupted = correct + ' Base.Glasses, Base.Maggots, Base.Slug2",'
        sandbox.write_text(content.replace(correct, corrupted), encoding="utf-8")

        self.service.render_game_files()
        self.service.render_game_files()

        content = sandbox.read_text(encoding="utf-8")
        removal_line = next(line for line in content.splitlines() if "WorldItemRemovalList" in line)
        self.assertEqual(
            removal_line,
            '    WorldItemRemovalList = "Base.Hat, Base.Glasses, Base.Maggots, Base.Slug, '
            'Base.Slug2, Base.Snail, Base.Worm, Base.Dung_Mouse, Base.Dung_Rat",',
        )
        self.assertNotIn('", Base.Glasses', content)

    def test_status_is_safe_without_docker_container(self):
        status = self.service.status()
        self.assertEqual(status["server"], "missing")
        self.assertEqual(status["profile"], "servertest")

    def test_backup_schedule_prunes_old_files_by_count(self):
        for index in range(5):
            path = self.service.backups / f"backup-{index}.zip"
            path.write_bytes(b"backup")
            timestamp = time.time() - (5 - index) * 60
            os.utime(path, (timestamp, timestamp))

        saved = self.service.save_backup_schedule({
            "enabled": True,
            "times": ["03:00", "15:00"],
            "retention_count": 3,
            "retention_days": 365,
        })

        self.assertEqual(saved["times"], ["03:00", "15:00"])
        self.assertEqual(len(list(self.service.backups.glob("*.zip"))), 3)
        self.assertEqual(self.service.config().backup_retention_count, 3)

    def test_backup_schedule_prunes_expired_files_but_keeps_minimum(self):
        now = time.time()
        for index in range(4):
            path = self.service.backups / f"dated-{index}.zip"
            path.write_bytes(b"backup")
            timestamp = now - (20 * 86400 if index == 0 else index * 60)
            os.utime(path, (timestamp, timestamp))

        self.service.save_backup_schedule({
            "enabled": False,
            "times": ["03:00"],
            "retention_count": 20,
            "retention_days": 7,
        })

        self.assertFalse((self.service.backups / "dated-0.zip").exists())
        self.assertEqual(len(list(self.service.backups.glob("*.zip"))), 3)

    def test_scheduler_runs_matching_backup_once(self):
        now = datetime.now(KST)
        self.service.save_backup_schedule({
            "enabled": True,
            "times": [now.strftime("%H:%M")],
            "retention_count": 20,
            "retention_days": 30,
        })
        calls = []
        self.service.create_backup = lambda *args, **kwargs: calls.append((args, kwargs))

        class OneCycleEvent:
            calls = 0

            def wait(self, _seconds):
                self.calls += 1
                return self.calls > 1

        self.service.stop_event = OneCycleEvent()
        self.service._scheduler_loop()

        self.assertEqual(calls, [(('scheduled',), {'allow_running': True})])

    @patch("app.service.time.sleep")
    def test_online_backup_flushes_world_before_archive(self, _sleep):
        commands = []
        self.service.is_running = lambda: True
        self.service.console_command = lambda command: commands.append(command)
        (self.service.saves / "map.bin").write_bytes(b"world")

        backup = self.service.create_backup(allow_running=True)

        self.assertEqual(commands, ["save"])
        self.assertTrue((self.service.backups / backup["name"]).is_file())
        self.assertFalse(any(self.service.backups.glob("*.part")))

    @patch("app.service.shutil.disk_usage")
    def test_backup_stops_before_filling_disk(self, disk_usage):
        disk_usage.return_value = type("Usage", (), {
            "total": 1024**3,
            "used": 924 * 1024**2,
            "free": 100 * 1024**2,
        })()
        (self.service.saves / "map.bin").write_bytes(b"world")

        with self.assertRaisesRegex(RuntimeError, "디스크 여유 공간"):
            self.service.create_backup()

        self.assertFalse(any(self.service.backups.glob("*.part")))

    def test_active_panel_update_status_does_not_pull_image_again(self):
        self.service._write_panel_update_status(
            "replacing", "replace", 48, "기존 패널을 안전하게 중지하고 있습니다."
        )

        status = self.service.panel_update_status()

        self.assertEqual(status["status"], "replacing")
        self.assertEqual(status["stage"], "replace")
        self.assertEqual(status["progress"], 48)
        self.assertTrue(status["available"])
        self.assertNotIn("error", status)

        self.service._write_panel_update_status(
            "running", "replace", 48, "기존 버전에서 기록한 업데이트 상태입니다."
        )
        self.assertEqual(self.service.panel_update_status()["status"], "running")

    def test_secret_placeholder_preserves_password(self):
        config = self.service.config().model_dump()
        config["admin_password"] = "abcd"
        self.service.save_config(config)
        public = self.service.public_config()
        self.assertEqual(public["admin_password"], "********")
        public["admin_password"] = "********"
        self.service.save_config(public)
        self.assertEqual(self.service.config().admin_password, "abcd")

    def test_player_database_is_discovered_and_safely_updated(self):
        database = self.service.database / "servertest.db"
        connection = sqlite3.connect(database)
        connection.execute("CREATE TABLE whitelist (username TEXT PRIMARY KEY, steamid TEXT, accesslevel TEXT, whitelisted INTEGER, banned INTEGER)")
        connection.execute("INSERT INTO whitelist VALUES ('survivor', '76561198000000000', 'none', 1, 0)")
        connection.commit(); connection.close()
        accounts = self.service.player_accounts()
        self.assertTrue(accounts["supported"])
        self.assertEqual(accounts["accounts"][0]["username"], "survivor")
        self.service.update_player("survivor", "access_level", "moderator")
        self.assertEqual(self.service.player_accounts()["accounts"][0]["access_level"], "moderator")
        self.assertTrue(any(self.service.backups.glob("*database-safety*.zip")))

    def test_console_command_uses_fixed_fifo_writer(self):
        container = ConsoleContainer()
        service = PanelService(self.service.settings, lambda: ConsoleClient(container))
        result = service.console_command('/servermsg "Welcome survivors"')
        self.assertEqual(result["command"], 'servermsg "Welcome survivors"')
        command, options = container.exec_calls[0]
        self.assertEqual(command[:4], ["/usr/bin/timeout", "5s", "/bin/bash", "-c"])
        self.assertEqual(options["user"], "zomboid")
        self.assertEqual(options["environment"], {"PZ_COMMAND": 'servermsg "Welcome survivors"'})
        with self.assertRaisesRegex(ValueError, "서버 제어 메뉴"):
            service.console_command("quit")

    def test_logs_remove_ansi_escape_codes_and_visible_fragments(self):
        self.service._log("install", "\x1b[0mOK")
        self.service._log("control", "[0mcontrol ready")

        self.assertIn(" OK", self.service.logs("install"))
        self.assertIn(" control ready", self.service.logs("control"))
        self.assertNotIn("[0m", (self.service.logs_dir / "control.log").read_text())
        self.assertNotIn("[0m", self.service.logs("all"))

        service = PanelService(self.service.settings, lambda: LogClient())
        server_log = service.logs("server")
        self.assertIn("live server output", server_log)
        self.assertNotIn("[0m", server_log)

    def test_start_uses_compatible_container_options(self):
        containers = StartContainers()
        settings = Settings(
            data_dir=self.service.settings.data_dir,
            host_data_dir=self.service.settings.host_data_dir,
            scheduler_enabled=False,
            pull_runtime=False,
        )
        service = PanelService(settings, lambda: StartClient(containers))
        (service.server / "start-server.sh").write_text("#!/bin/sh\n")
        config = service.config().model_dump()
        config["admin_password"] = "test-password"
        service.save_config(config)

        service.start()

        self.assertEqual(len(containers.run_calls), 1)
        _image, options = containers.run_calls[0]
        self.assertNotIn("stop_timeout", options)
        self.assertEqual(options["restart_policy"], {"Name": "unless-stopped"})

    @patch("app.service.time.sleep")
    def test_install_retries_up_to_three_times_before_succeeding(self, sleep):
        def mark_installed():
            (self.service.server / "start-server.sh").write_text("#!/bin/sh\n")

        containers = InstallContainers([1, 1, 1, 0], mark_installed)
        settings = Settings(
            data_dir=self.service.settings.data_dir,
            host_data_dir=self.service.settings.host_data_dir,
            scheduler_enabled=False,
            pull_runtime=False,
        )
        service = PanelService(settings, lambda: StartClient(containers))

        service.install()

        self.assertEqual(len(containers.run_calls), 4)
        self.assertEqual(sleep.call_count, 3)
        self.assertTrue(all(container.removed for container in containers.created))
        install_log = service.logs("install")
        self.assertIn("재시도 3/3", install_log)
        self.assertIn("SteamCMD 설치 시도 4/4", install_log)

    @patch("app.service.time.sleep")
    def test_install_fails_after_three_retries(self, sleep):
        containers = InstallContainers([1, 1, 1, 1])
        settings = Settings(
            data_dir=self.service.settings.data_dir,
            host_data_dir=self.service.settings.host_data_dir,
            scheduler_enabled=False,
            pull_runtime=False,
        )
        service = PanelService(settings, lambda: StartClient(containers))

        with self.assertRaisesRegex(RuntimeError, "총 4회 시도"):
            service.install()

        self.assertEqual(len(containers.run_calls), 4)
        self.assertEqual(sleep.call_count, 3)
        self.assertTrue(all(container.removed for container in containers.created))

    def test_support_log_report_combines_logs_and_redacts_secrets(self):
        config = self.service.config().model_dump()
        config["admin_password"] = "support-secret"
        self.service.save_config(config)
        self.service._log("install", "password=support-secret install failed")
        self.service._log("control", "maintenance checked")
        report = self.service.support_log_report()
        self.assertIn("===== DIAGNOSTICS =====", report)
        self.assertIn("===== SERVER LOG =====", report)
        self.assertIn("===== INSTALL LOG =====", report)
        self.assertIn("===== CONTROL LOG =====", report)
        self.assertIn("[REDACTED]", report)
        self.assertNotIn("support-secret", report)

    def test_all_logs_combines_each_log_category_once(self):
        self.service._log("server", "server ready")
        self.service._log("install", "install ready")
        self.service._log("control", "control ready")
        combined = self.service.logs("all")
        self.assertIn("[서버] ", combined)
        self.assertIn("[설치] ", combined)
        self.assertIn("[작업] ", combined)
        self.assertEqual(combined.count("server ready"), 1)
        self.assertEqual(combined.count("install ready"), 1)
        self.assertEqual(combined.count("control ready"), 1)

    def test_all_logs_merges_live_server_output_by_timestamp(self):
        self.service.docker_factory = lambda: LogClient()
        (self.service.logs_dir / "install.log").write_text(
            "[2026-10-05 16:59:00] install ready\n", encoding="utf-8"
        )
        (self.service.logs_dir / "control.log").write_text(
            "[2026-10-05 17:01:00] control ready\n", encoding="utf-8"
        )
        combined = self.service.logs("all")
        self.assertIn("[서버] 2026-10-05T08:00:00Z live server output", combined)
        self.assertLess(combined.index("install ready"), combined.index("live server output"))
        self.assertLess(combined.index("live server output"), combined.index("control ready"))

    def test_all_logs_applies_tail_to_every_category(self):
        for kind in ("server", "install", "control"):
            self.service._log(kind, f"{kind} old")
            self.service._log(kind, f"{kind} recent")
        combined = self.service.logs("all", tail=1)
        self.assertNotIn("server old", combined)
        self.assertNotIn("install old", combined)
        self.assertNotIn("control old", combined)
        self.assertIn("server recent", combined)
        self.assertIn("install recent", combined)
        self.assertIn("control recent", combined)

    def test_completed_server_operation_maps_to_discord_event(self):
        events = []
        self.service.notify_discord_event = lambda *args: events.append(args)
        self.service._notify_completed_operation("서버 시작")
        self.assertEqual(events[0][0], "server_start")
        self.assertIn("서버 시작", events[0][1])


if __name__ == "__main__":
    unittest.main()
