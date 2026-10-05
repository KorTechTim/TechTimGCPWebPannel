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
        self.assertIn("ZombieConfig.RespawnHours", sandbox.read_text())

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


if __name__ == "__main__":
    unittest.main()
