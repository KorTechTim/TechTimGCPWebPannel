import tempfile
import unittest
from pathlib import Path

from docker.errors import NotFound
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


class MissingContainers:
    def get(self, _name):
        raise NotFound("missing")


class FakeClient:
    def __init__(self):
        self.containers = MissingContainers()
    def close(self):
        pass


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.root = root
        app = create_app(Settings(data_dir=root, host_data_dir=root, scheduler_enabled=False, pull_runtime=False), lambda: FakeClient())
        self.client = TestClient(app)
        self.assertEqual(self.client.post("/api/auth/login", json={"username": "admin", "password": "admin"}).status_code, 200)
        self.assertEqual(self.client.post("/api/auth/change-password", json={"new_password": "panel-pass"}).status_code, 200)

    def tearDown(self):
        self.temp.cleanup()

    def test_health_status_and_config(self):
        self.assertEqual(self.client.get("/health").json()["game"], "enshrouded")
        status = self.client.get("/api/status")
        self.assertEqual(status.status_code, 200)
        self.assertFalse(status.json()["installed"])
        config = self.client.get("/api/config").json()
        self.assertEqual(config["backup_retention_count"], 10)
        self.assertEqual(len(config["roles"]), 3)

    def test_file_editor_is_safe_and_locked_by_server_state(self):
        path = self.root / "server" / "custom.json"
        path.write_text('{"enabled": false}\n', encoding="utf-8")
        opened = self.client.get("/api/files/text", params={"path": "server/custom.json"})
        self.assertEqual(opened.status_code, 200)
        saved = self.client.post("/api/files/text", params={"path": "server/custom.json"}, json={"content": '{"enabled": true}\n'})
        self.assertEqual(saved.status_code, 200)
        self.assertIn("true", path.read_text())
        escaped = self.client.get("/api/files", params={"path": "../"})
        self.assertEqual(escaped.status_code, 400)

    def test_backup_settings_allow_three_times(self):
        response = self.client.post("/api/backups/settings", json={
            "enabled": True, "times": ["03:30", "15:30", "23:00"],
            "retention_count": 10, "retention_days": 15,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["times"], ["03:30", "15:30", "23:00"])

    def test_static_ui_has_languages_and_migration(self):
        login = self.client.get("/login").text
        dashboard = self.client.get("/").text
        self.assertIn('<option value="zh">中文</option>', login)
        self.assertIn('<option value="ja">日本語</option>', dashboard)
        self.assertIn('data-view="migration"', dashboard)
        self.assertIn('/static/enshrouded-menu-atlas-v1.png', self.client.get('/static/app.css').text)

    def test_migration_export_and_import_endpoints(self):
        service = self.client.app.state.service
        service.savegame.joinpath("world0.ksd").write_bytes(b"portable-world")
        config = self.client.get("/api/config").json()
        config["server_name"] = "Portable Embervale"
        for index, role in enumerate(config["roles"]):
            role["password"] = f"migration-secret-{index}"
        self.assertEqual(self.client.post("/api/config", json=config).status_code, 200)

        exported = self.client.get("/api/migration/export")
        self.assertEqual(exported.status_code, 200)
        self.assertEqual(exported.headers["content-type"], "application/zip")

        service.savegame.joinpath("world0.ksd").write_bytes(b"changed")
        imported = self.client.post(
            "/api/migration/import",
            files={"file": ("migration.zip", exported.content, "application/zip")},
        )
        self.assertEqual(imported.status_code, 200)
        self.assertEqual(service.config().server_name, "Portable Embervale")
        self.assertEqual(service.savegame.joinpath("world0.ksd").read_bytes(), b"portable-world")


if __name__ == "__main__":
    unittest.main()
