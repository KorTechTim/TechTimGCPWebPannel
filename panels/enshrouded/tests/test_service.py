import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from docker.errors import NotFound

from app.config import Settings
from app.service import PanelService


class MissingContainers:
    def get(self, _name):
        raise NotFound("missing")


class FakeClient:
    def __init__(self):
        self.containers = MissingContainers()
    def close(self):
        pass


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.service = PanelService(
            Settings(data_dir=self.root, host_data_dir=self.root, scheduler_enabled=False, pull_runtime=False),
            lambda: FakeClient(),
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_render_preserves_future_official_settings(self):
        existing = json.loads(self.service.game_config_path.read_text())
        existing["futureOfficialSetting"] = {"enabled": True}
        existing["gameSettings"] = {"playerHealthFactor": 1.5}
        self.service.game_config_path.write_text(json.dumps(existing), encoding="utf-8")

        payload = self.service.config().model_dump()
        payload["server_name"] = "Ember Valley"
        payload["roles"][0]["password"] = "admin-new-password"
        payload["roles"][1]["password"] = "friend-new-password"
        payload["roles"][2]["password"] = "guest-new-password"
        self.service.save_config(payload)

        rendered = json.loads(self.service.game_config_path.read_text())
        self.assertEqual(rendered["name"], "Ember Valley")
        self.assertEqual(rendered["futureOfficialSetting"], {"enabled": True})
        self.assertEqual(rendered["gameSettings"]["playerHealthFactor"], 1.5)

    def test_start_rejects_placeholder_role_passwords(self):
        with self.assertRaisesRegex(ValueError, "역할별 접속 비밀번호"):
            self.service.validate_start_requirements()

    def test_backup_and_migration_round_trip(self):
        self.service.savegame.joinpath("world0.ksd").write_bytes(b"world-data")
        payload = self.service.config().model_dump()
        payload["server_name"] = "Old Cloud Realm"
        payload["roles"][0]["password"] = "admin-secret"
        payload["roles"][1]["password"] = "friend-secret"
        payload["roles"][2]["password"] = "guest-secret"
        self.service.save_config(payload)
        archive = self.service.create_migration_archive()

        second_root = self.root / "new-account"
        second = PanelService(
            Settings(data_dir=second_root, host_data_dir=second_root, scheduler_enabled=False, pull_runtime=False),
            lambda: FakeClient(),
        )
        second.import_migration_archive(archive)

        self.assertEqual(second.config().server_name, "Old Cloud Realm")
        self.assertEqual((second.savegame / "world0.ksd").read_bytes(), b"world-data")
        self.assertEqual(second.config().roles[0].password, "admin-secret")

    def test_empty_savegame_backup_keeps_restore_directory(self):
        backup = self.service.create_backup("empty")
        with zipfile.ZipFile(backup) as archive:
            self.assertIn("savegame/", archive.namelist())
        self.service.restore_backup(backup.name)
        self.assertTrue(self.service.savegame.is_dir())

    def test_migration_rejects_unrelated_zip(self):
        archive = self.root / "bad.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("notes.txt", "not a migration")
        with self.assertRaises(ValueError):
            self.service.import_migration_archive(archive)


if __name__ == "__main__":
    unittest.main()
