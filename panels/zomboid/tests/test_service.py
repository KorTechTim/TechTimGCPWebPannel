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


if __name__ == "__main__":
    unittest.main()
