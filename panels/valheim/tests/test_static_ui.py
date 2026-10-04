from pathlib import Path
import unittest


STATIC_DIR = Path(__file__).resolve().parents[1] / "app" / "static"


class StaticUiTests(unittest.TestCase):
    def read(self, name):
        return (STATIC_DIR / name).read_text(encoding="utf-8")

    def test_valheim_visual_assets_are_packaged(self):
        for name in (
            "valheim-panel-bg-v2.png",
            "valheim-panel-mark-v2.png",
            "valheim-settings-mark-v2.png",
        ):
            asset = STATIC_DIR / name
            with self.subTest(asset=name):
                self.assertTrue(asset.is_file())
                self.assertGreater(asset.stat().st_size, 1_000)
                self.assertEqual(asset.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_dashboard_keeps_palworld_style_operational_hub(self):
        html = self.read("dashboard.html")
        self.assertIn("valheim-palshell.css", html)
        self.assertIn('id="quick-settings-form"', html)
        self.assertIn('id="detail-view"', html)
        self.assertEqual(html.count('class="management-shortcut"'), 8)
        for target in (
            "modifiers-dialog",
            "worlds-dialog",
            "backups-dialog",
            "permissions-dialog",
            "schedule-dialog",
            "mods-dialog",
            "discord-dialog",
            "panel-update-dialog",
        ):
            with self.subTest(target=target):
                self.assertIn(f'data-open="{target}"', html)

    def test_detail_navigation_and_quick_settings_are_wired(self):
        script = self.read("app.js")
        self.assertIn("function openDetail", script)
        self.assertIn("function closeDetail", script)
        self.assertIn("async function loadQuickSettings", script)
        self.assertIn("quick-settings-form", script)

    def test_responsive_shell_has_mobile_breakpoints(self):
        css = self.read("valheim-palshell.css")
        self.assertIn("valheim-panel-bg-v2.png", css)
        self.assertIn("@media (max-width: 760px)", css)
        self.assertIn("@media (max-width: 440px)", css)
        self.assertIn("grid-template-columns: 1fr", css)


if __name__ == "__main__":
    unittest.main()
