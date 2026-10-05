import tempfile
import unittest
from pathlib import Path
import sqlite3

from app.config import Settings
from app.service import PanelService


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


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.service = PanelService(Settings(data_dir=root, host_data_dir=root, scheduler_enabled=False), lambda: FakeClient())

    def tearDown(self): self.temp.cleanup()

    def test_initial_files_are_rendered(self):
        ini = self.service.server_config_dir / "servertest.ini"
        sandbox = self.service.server_config_dir / "servertest_SandboxVars.lua"
        self.assertIn("DefaultPort=16261", ini.read_text())
        content = sandbox.read_text()
        self.assertIn("VERSION = 6", content)
        self.assertIn("ZombieConfig = {", content)
        self.assertIn("        RespawnHours =", content)
        self.assertNotIn("ZombieConfig.RespawnHours", content)
        self.assertIn("MultiplierConfig = {", content)

    def test_status_is_safe_without_docker_container(self):
        status = self.service.status()
        self.assertEqual(status["server"], "missing")
        self.assertEqual(status["profile"], "servertest")

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

    def test_all_logs_combines_server_install_and_control(self):
        self.service._log("server", "server ready")
        self.service._log("install", "install ready")
        self.service._log("control", "control ready")
        combined = self.service.logs("all")
        self.assertIn("===== 서버 로그 =====", combined)
        self.assertIn("server ready", combined)
        self.assertIn("===== 설치 로그 =====", combined)
        self.assertIn("install ready", combined)
        self.assertIn("===== 작업 기록 =====", combined)
        self.assertIn("control ready", combined)

    def test_completed_server_operation_maps_to_discord_event(self):
        events = []
        self.service.notify_discord_event = lambda *args: events.append(args)
        self.service._notify_completed_operation("서버 시작")
        self.assertEqual(events[0][0], "server_start")
        self.assertIn("서버 시작", events[0][1])


if __name__ == "__main__":
    unittest.main()
