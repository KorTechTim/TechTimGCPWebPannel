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


if __name__ == "__main__":
    unittest.main()
