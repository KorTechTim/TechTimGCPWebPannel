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
            "valheim-status-install-v1.png",
            "valheim-status-server-v1.png",
            "valheim-status-panel-v1.png",
            "valheim-nav-guide-v1.png",
            "valheim-nav-update-v1.png",
            "valheim-nav-logout-v1.png",
            "techtim-avatar.png",
        ):
            asset = STATIC_DIR / name
            with self.subTest(asset=name):
                self.assertTrue(asset.is_file())
                self.assertGreater(asset.stat().st_size, 1_000)
                self.assertEqual(asset.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

        html = self.read("dashboard.html")
        self.assertIn('id="panel-version">확인 중', html)
        self.assertNotIn('id="panel-version">1.0.0', html)
        self.assertIn('class="brand-icon profile-avatar"', html)
        self.assertIn('src="/static/techtim-avatar.png?v=1"', html)
        for name in ("install", "server", "panel"):
            self.assertIn(f"valheim-status-{name}-v1.png", html)
        for name in ("guide", "update", "logout"):
            self.assertIn(f"valheim-nav-{name}-v1.png", html)
        for label in ("공식 가이드", "패널 업데이트", "로그아웃"):
            self.assertIn(f'class="top-action-label">{label}', html)
        self.assertIn('id="panel-update-notice"', html)
        self.assertIn('id="panel-update-button"', html)

    def test_dashboard_keeps_palworld_style_operational_hub(self):
        html = self.read("dashboard.html")
        self.assertIn("valheim-palshell.css", html)
        self.assertIn('id="quick-settings-form"', html)
        self.assertIn('id="detail-view"', html)
        self.assertIn('class="resource-grid"', html)
        self.assertIn('id="network-rx"', html)
        self.assertIn('id="network-tx"', html)
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
        self.assertLess(html.index('id="install"'), html.index('id="start"'))

    def test_detail_navigation_and_quick_settings_are_wired(self):
        script = self.read("app.js")
        self.assertIn("function openDetail", script)
        self.assertIn("function closeDetail", script)
        self.assertIn("async function loadQuickSettings", script)
        self.assertIn("quick-settings-form", script)
        self.assertIn("['completed', 'failed'].includes(update.status)", script)
        self.assertIn("async function checkPanelUpdate", script)

    def test_responsive_shell_has_mobile_breakpoints(self):
        css = self.read("valheim-palshell.css")
        self.assertIn("valheim-panel-bg-v2.png", css)
        self.assertIn("@media (max-width: 760px)", css)
        self.assertIn("@media (max-width: 440px)", css)
        self.assertIn("grid-template-columns: 1fr", css)


if __name__ == "__main__":
    unittest.main()
