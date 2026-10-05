import unittest
from pathlib import Path


class StaticUiTests(unittest.TestCase):
    def test_required_detail_pages_exist(self):
        html = (Path(__file__).parents[1] / "app/static/dashboard.html").read_text()
        for page in ("settings", "sandbox", "mods", "players", "backups", "advanced", "schedule", "files", "panel-update"):
            self.assertIn(f'data-page="{page}"', html)
        self.assertNotIn('data-page="monitor"', html)
        self.assertNotIn('data-view="monitor"', html)
        self.assertIn("설정파일 직접수정", html)
        self.assertNotIn("고급 파일 설정", html)

    def test_generated_assets_are_referenced(self):
        html = (Path(__file__).parents[1] / "app/static/dashboard.html").read_text()
        css = (Path(__file__).parents[1] / "app/static/app.css").read_text()
        self.assertIn("zomboid-panel-mark.png", html)
        self.assertIn('class="top-brand-icon"><img src="/static/techtim-profile.png?v=1"', html)
        self.assertIn("zomboid-panel-bg.png", css)
        self.assertIn("zomboid-hero-zombie-hand-v1.png", css)
        for asset in (
            "zomboid-nav-discord-v1.png",
            "zomboid-nav-youtube-v1.png",
            "zomboid-nav-guide-v1.png",
            "zomboid-nav-update-v1.png",
            "zomboid-nav-logout-v1.png",
            "zomboid-status-install-v1.png",
            "zomboid-status-server-v1.png",
            "zomboid-status-panel-v1.png",
            "zomboid-file-folder-v1.png",
            "zomboid-file-document-v1.png",
        ):
            self.assertIn(asset, html if asset.startswith("zomboid-nav") or asset.startswith("zomboid-status") else (Path(__file__).parents[1] / "app/static/app.js").read_text())

    def test_header_uses_shared_panel_order(self):
        html = (Path(__file__).parents[1] / "app/static/dashboard.html").read_text()
        expected = ["테크팀 디스코드", "테크팀 유튜브", "공식 가이드", "패널 업데이트", "로그아웃"]
        positions = [html.index(label) for label in expected]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn('data-view="panel-update"><b>', html)

    def test_status_summary_is_overview_only(self):
        root = Path(__file__).parents[1]
        html = (root / "app/static/dashboard.html").read_text()
        script = (root / "app/static/app.js").read_text()
        self.assertIn('id="overview-status"', html)
        self.assertIn("$('#overview-status').hidden = name !== 'overview';", script)

    def test_sidebar_places_system_tools_below_basic_settings(self):
        html = (Path(__file__).parents[1] / "app/static/dashboard.html").read_text()
        positions = [html.index(label) for label in ("기본 설정", "예약 작업", "서버 폴더 탐색기", "WORLD")]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn('<p class="nav-group">SYSTEM</p>', html)

    def test_file_explorer_uses_game_specific_icons(self):
        root = Path(__file__).parents[1]
        script = (root / "app/static/app.js").read_text()
        css = (root / "app/static/app.css").read_text()
        self.assertIn("zomboid-file-folder-v1.png", script)
        self.assertIn("zomboid-file-document-v1.png", script)
        self.assertIn("file-entry-icon", css)

    def test_settings_legends_are_inside_frames(self):
        css = (Path(__file__).parents[1] / "app/static/app.css").read_text()
        self.assertIn(".form-sections legend{float:left;width:100%", css)
        self.assertIn(".form-sections legend+*{clear:both}", css)

    def test_sidebar_uses_drawn_image_icons(self):
        root = Path(__file__).parents[1]
        html = (root / "app/static/dashboard.html").read_text()
        css = (root / "app/static/app.css").read_text()
        for asset in (
            "zomboid-menu-overview-v1.png",
            "zomboid-menu-terminal-v1.png",
            "zomboid-menu-settings-v1.png",
            "zomboid-menu-schedule-v1.png",
            "zomboid-file-folder-v1.png",
            "zomboid-menu-sandbox-v1.png",
            "zomboid-menu-mods-v1.png",
            "zomboid-menu-players-v1.png",
            "zomboid-menu-backups-v1.png",
            "zomboid-menu-config-v1.png",
        ):
            self.assertIn(asset, html)
        self.assertEqual(html.count('class="nav-icon"'), 10)
        self.assertIn(".nav-item .nav-icon img", css)

    def test_management_terminal_has_command_controls_and_help(self):
        root = Path(__file__).parents[1]
        html = (root / "app/static/dashboard.html").read_text()
        script = (root / "app/static/app.js").read_text()
        self.assertIn("관리 터미널", html)
        self.assertIn('id="terminal-command-form"', html)
        self.assertIn('id="command-help-dialog"', html)
        self.assertIn('id="export-support-log"', html)
        self.assertIn('href="/api/logs/export"', html)
        self.assertIn("/api/console/command", script)
        self.assertNotIn("<span>실시간 로그</span>", html)

    def test_all_dialogs_use_shared_blurred_backdrop(self):
        root = Path(__file__).parents[1]
        html = (root / "app/static/dashboard.html").read_text()
        script = (root / "app/static/app.js").read_text()
        css = (root / "app/static/app.css").read_text()
        self.assertIn("dialog::backdrop", css)
        self.assertIn("backdrop-filter:blur(8px)", css)
        self.assertIn("body.modal-open", css)
        self.assertIn("syncModalState", script)
        self.assertIn('id="text-input-dialog" class="app-dialog input-dialog"', html)
        self.assertNotIn("window.prompt", script)


if __name__ == "__main__":
    unittest.main()
