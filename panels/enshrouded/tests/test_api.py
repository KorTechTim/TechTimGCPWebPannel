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
        self.assertEqual(status.json()["uptime_seconds"], 0)
        self.assertIn("query_port", status.json())
        config = self.client.get("/api/config").json()
        self.assertEqual(config["backup_retention_count"], 10)
        self.assertEqual(len(config["roles"]), 3)
        resources = self.client.get("/api/resources").json()
        self.assertIn("network_receive_bps", resources)
        self.assertIn("network_transmit_bps", resources)

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
        self.assertIn('<option value="zh">🇨🇳 中文</option>', login)
        self.assertIn('TechTim(T2) 인슈어라오디드 구글클라우드 구동기 관리페이지', login)
        self.assertIn('초기 계정 패스워드는 admin / admin 입니다.', login)
        self.assertIn('name="confirm_password"', login)
        self.assertIn('data-i18n="confirm_password"', login)
        self.assertIn("data.new_password !== data.confirm_password", self.client.get('/static/login.js').text)
        self.assertIn('© 2026 TechTim(T2). All rights reserved.', login)
        self.assertIn('<option value="ja">🇯🇵 日本語</option>', dashboard)
        self.assertIn('data-view="migration"', dashboard)
        self.assertIn('/static/enshrouded-menu-atlas-v1.png', self.client.get('/static/app.css').text)
        self.assertIn('/static/enshrouded-status-atlas-v1.png', self.client.get('/static/app.css').text)
        self.assertIn('https://discord.gg/Awy6Uh38KW', dashboard)
        self.assertIn('https://www.youtube.com/@kortechtim', dashboard)
        self.assertIn('https://enshrouded.zendesk.com/hc/en-us/sections/16050842957085-Multiplayer-Server-Hosting', dashboard)
        self.assertIn('/static/enshrouded-nav-discord-v1.png', dashboard)
        self.assertIn('/static/enshrouded-nav-youtube-v1.png', dashboard)
        self.assertIn('/static/enshrouded-nav-guide-v1.png', dashboard)
        self.assertIn('class="schedule-weekdays"', dashboard)
        self.assertIn('id="panel-update-dialog" class="panel-update-dialog"', dashboard)
        self.assertIn('id="panel-update-button"', dashboard)
        self.assertNotIn('id="view-update"', dashboard)
        self.assertIn('id="text-input-dialog"', dashboard)
        self.assertIn('id="notice-dialog"', dashboard)
        self.assertIn('id="running-lock-dialog"', dashboard)
        self.assertIn('id="install-progress-dialog"', dashboard)
        self.assertIn('id="install-progress-percent"', dashboard)
        self.assertIn('id="install-log-output"', dashboard)
        self.assertIn('/static/enshrouded-install-character-v1.png', self.client.get('/static/app.css').text)
        self.assertIn('© 2026 TechTim(T2)', dashboard)
        self.assertNotIn('STEAM APP 2278520', dashboard)
        self.assertNotIn('prompt(', self.client.get('/static/app.js').text)
        self.assertIn('backdrop-filter:blur(12px)', self.client.get('/static/app.css').text)
        self.assertIn('.section-head>div:first-child{display:block!important', self.client.get('/static/app.css').text)
        self.assertIn('.status-icon{width:33px;height:44px', self.client.get('/static/app.css').text)
        self.assertIn("url('/static/enshrouded-panel-bg-v1.png') center 42%/cover", self.client.get('/static/app.css').text)
        self.assertIn('.weekday-options input{display:block', self.client.get('/static/app.css').text)
        self.assertIn('/static/enshrouded-difficulty-default-v1.png', dashboard)
        self.assertIn('/static/enshrouded-difficulty-survival-v1.png', dashboard)
        self.assertIn('class="preset-description"', dashboard)
        self.assertIn('id="game-settings-groups"', dashboard)
        self.assertIn('id="game-settings-count"', dashboard)
        self.assertIn('class="discord-demo"', dashboard)
        self.assertIn('id="discord-preview-name"', dashboard)
        self.assertIn('id="discord-notifications-title"', dashboard)
        self.assertNotIn('<fieldset class="notification-grid">', dashboard)
        self.assertIn('관리로그 및 터미널', dashboard)
        self.assertIn('서버 기본 설정', dashboard)
        self.assertIn('서버 역활 및 접속비밀번호', dashboard)
        self.assertIn('class="server-summary"', dashboard)
        self.assertIn('id="summary-uptime"', dashboard)
        self.assertIn('id="network-chart"', dashboard)
        self.assertIn('/static/techtim-profile.png', dashboard)
        app_js = self.client.get('/static/app.js').text
        self.assertIn('RUNNING_LOCKED_VIEWS', app_js)
        self.assertIn('SAVE_REMINDER_SCOPES', app_js)
        self.assertIn('file-entry-name', app_js)
        self.assertIn('GAME_SETTING_GROUPS', app_js)
        self.assertIn('collectGameSettings', app_js)
        self.assertIn('pollInstallProgress', app_js)
        self.assertIn('scheduleInstallPoll(1000)', app_js)
        self.assertIn("dialog.showModal()", app_js)
        self.assertNotIn("$('#global-message')", app_js)
        self.assertIn('class="server-control"', dashboard)
        self.assertIn('@media(min-width:761px){.section-head>div:first-child>p:not(.eyebrow){white-space:nowrap}}', self.client.get('/static/app.css').text)

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
