import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


class MissingContainers:
    def get(self, _name):
        from docker.errors import NotFound
        raise NotFound("missing")


class FakeClient:
    def __init__(self): self.containers = MissingContainers()
    def close(self): pass


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        app = create_app(Settings(data_dir=root, host_data_dir=root, scheduler_enabled=False), lambda: FakeClient())
        self.client = TestClient(app)
        login = self.client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        self.assertEqual(login.status_code, 200)
        changed = self.client.post("/api/auth/change-password", json={"new_password": "test-pass"})
        self.assertEqual(changed.status_code, 200)

    def tearDown(self): self.temp.cleanup()

    def test_health_and_status(self):
        self.assertEqual(self.client.get("/health").json()["game"], "zomboid")
        status = self.client.get("/api/status")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["profile"], "servertest")

    def test_config_and_sandbox_round_trip(self):
        config = self.client.get("/api/config").json()
        config["server_name"] = "Test Survivors"
        config["admin_password"] = "abcd"
        saved = self.client.post("/api/config", json=config)
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["server_name"], "Test Survivors")
        sandbox = self.client.get("/api/sandbox").json()
        sandbox["xp_multiplier"] = 2.5
        self.assertEqual(self.client.post("/api/sandbox", json=sandbox).status_code, 200)
        schema = self.client.get("/api/sandbox/schema")
        self.assertEqual(schema.status_code, 200)
        self.assertGreaterEqual(len(schema.json()["fields"]), 260)

    def test_file_explorer_is_rooted_in_data(self):
        root = self.client.get("/api/files")
        self.assertEqual(root.status_code, 200)
        self.assertEqual(root.json()["root"], "/data")
        escaped = self.client.get("/api/files", params={"path": "../"})
        self.assertEqual(escaped.status_code, 400)

    def test_console_command_endpoint(self):
        commands = []
        self.client.app.state.service.console_command = lambda command: commands.append(command) or {
            "status": "ok", "message": "sent", "command": command,
        }
        response = self.client.post("/api/console/command", json={"command": "players"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(commands, ["players"])
        invalid = self.client.post("/api/console/command", json={"command": "players\nquit"})
        self.assertEqual(invalid.status_code, 422)

    def test_support_log_export_is_text_attachment(self):
        self.client.app.state.service.support_log_report = lambda: "support report\n"
        response = self.client.get("/api/logs/export")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "support report\n")
        self.assertTrue(response.headers["content-type"].startswith("text/plain"))
        self.assertIn("attachment;", response.headers["content-disposition"])
        self.assertIn("techtim-zomboid-support-", response.headers["content-disposition"])


if __name__ == "__main__":
    unittest.main()
