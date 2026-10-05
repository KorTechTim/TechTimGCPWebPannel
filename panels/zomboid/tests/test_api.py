import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


DISCORD_WEBHOOK = "https://discord.com/api/webhooks/123456789012345678/abcdefghijklmnopqrstuvwxyz_ABCDEFG-123456"


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
        self.root = root
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

    @patch("app.main.lookup_workshop_item")
    def test_workshop_lookup_accepts_url_and_returns_mod_pair(self, mocked_lookup):
        mocked_lookup.return_value = {
            "workshop_id": "3796373365",
            "title": "It is of interest to me!",
            "mod_ids": ["ItIsOfInterestToMe"],
            "preview_url": "",
            "workshop_url": "https://steamcommunity.com/sharedfiles/filedetails/?id=3796373365",
        }
        response = self.client.post("/api/workshop/lookup", json={
            "value": "https://steamcommunity.com/sharedfiles/filedetails/?id=3796373365",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mod_ids"], ["ItIsOfInterestToMe"])
        mocked_lookup.assert_called_once_with(
            "https://steamcommunity.com/sharedfiles/filedetails/?id=3796373365"
        )

    def test_file_explorer_is_rooted_in_data(self):
        root = self.client.get("/api/files")
        self.assertEqual(root.status_code, 200)
        self.assertEqual(root.json()["root"], "/data")
        escaped = self.client.get("/api/files", params={"path": "../"})
        self.assertEqual(escaped.status_code, 400)

    def test_file_explorer_text_editor_reads_writes_and_rejects_binary(self):
        text_file = self.root / "notes.json"
        text_file.write_text('{"enabled": false}\n', encoding="utf-8")
        opened = self.client.get("/api/files/text", params={"path": "notes.json"})
        self.assertEqual(opened.status_code, 200)
        self.assertEqual(opened.json()["content"], '{"enabled": false}\n')

        saved = self.client.post("/api/files/text", params={"path": "notes.json"},
                                 json={"content": '{"enabled": true}\n'})
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(text_file.read_text(encoding="utf-8"), '{"enabled": true}\n')

        binary_file = self.root / "world.bin"
        binary_file.write_bytes(b"world\x00data")
        rejected = self.client.get("/api/files/text", params={"path": "world.bin"})
        self.assertEqual(rejected.status_code, 400)
        self.assertIn("바이너리", rejected.json()["detail"])

    def test_folder_upload_preserves_relative_paths(self):
        uploaded = self.client.post("/api/files/upload-folder", data={"path": ""}, files=[
            ("files", ("WorkshopPack/config/settings.ini", b"Enabled=true\n", "text/plain")),
            ("files", ("WorkshopPack/mods/readme.txt", b"Project Zomboid\n", "text/plain")),
        ])
        self.assertEqual(uploaded.status_code, 200)
        self.assertEqual(uploaded.json()["files"], 2)
        self.assertEqual((self.root / "WorkshopPack/config/settings.ini").read_text(), "Enabled=true\n")
        self.assertEqual((self.root / "WorkshopPack/mods/readme.txt").read_text(), "Project Zomboid\n")

        escaped = self.client.post("/api/files/upload-folder", data={"path": ""}, files=[
            ("files", ("../outside.txt", b"blocked", "text/plain")),
        ])
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

    def test_logs_default_to_all_categories(self):
        requested = []
        self.client.app.state.service.logs = lambda kind: requested.append(kind) or "combined logs"
        response = self.client.get("/api/logs")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"log": "combined logs"})
        self.assertEqual(requested, ["all"])

    def test_discord_config_is_saved_masked_and_testable(self):
        saved = self.client.post("/api/discord", json={
            "enabled": True,
            "webhook_url": DISCORD_WEBHOOK,
            "username": "TechTim Survivors",
            "notify_server_start": True,
            "notify_server_stop": False,
            "notify_server_restart": True,
            "notify_backup": True,
            "notify_errors": True,
        })
        self.assertEqual(saved.status_code, 200)
        self.assertNotIn(DISCORD_WEBHOOK, saved.text)
        self.assertTrue(saved.json()["config"]["webhook_configured"])
        self.assertEqual(saved.json()["config"]["webhook_hint"], "Discord 웹훅 · 1234...5678")
        stored = self.client.app.state.service.discord_config()
        self.assertEqual(stored.webhook_url, DISCORD_WEBHOOK)

        calls = []
        self.client.app.state.service.deliver_discord_event = lambda *args: calls.append(args)
        tested = self.client.post("/api/discord/test")
        self.assertEqual(tested.status_code, 200)
        self.assertEqual(calls[0][0], "test")

        cleared = self.client.post("/api/discord", json={"clear_webhook": True})
        self.assertEqual(cleared.status_code, 200)
        self.assertFalse(cleared.json()["config"]["webhook_configured"])

    def test_discord_rejects_invalid_or_missing_webhook(self):
        invalid = self.client.post("/api/discord", json={"webhook_url": "https://example.com/hook"})
        self.assertEqual(invalid.status_code, 400)
        missing = self.client.post("/api/discord", json={"enabled": True})
        self.assertEqual(missing.status_code, 400)


if __name__ == "__main__":
    unittest.main()
