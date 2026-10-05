import unittest
from pathlib import Path


class StaticUiTests(unittest.TestCase):
    def test_required_detail_pages_exist(self):
        html = (Path(__file__).parents[1] / "app/static/dashboard.html").read_text()
        for page in ("settings", "sandbox", "mods", "players", "backups", "advanced", "schedule", "files", "monitor", "panel-update"):
            self.assertIn(f'data-page="{page}"', html)

    def test_generated_assets_are_referenced(self):
        html = (Path(__file__).parents[1] / "app/static/dashboard.html").read_text()
        css = (Path(__file__).parents[1] / "app/static/app.css").read_text()
        self.assertIn("zomboid-panel-mark.png", html)
        self.assertIn("zomboid-panel-bg.png", css)
        for asset in (
            "zomboid-nav-discord-v1.png",
            "zomboid-nav-youtube-v1.png",
            "zomboid-nav-guide-v1.png",
            "zomboid-nav-update-v1.png",
            "zomboid-nav-logout-v1.png",
            "zomboid-status-install-v1.png",
            "zomboid-status-server-v1.png",
            "zomboid-status-panel-v1.png",
        ):
            self.assertIn(asset, html)

    def test_header_uses_shared_panel_order(self):
        html = (Path(__file__).parents[1] / "app/static/dashboard.html").read_text()
        expected = ["테크팀 디스코드", "테크팀 유튜브", "공식 가이드", "패널 업데이트", "로그아웃"]
        positions = [html.index(label) for label in expected]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn('data-view="panel-update"><b>', html)


if __name__ == "__main__":
    unittest.main()
