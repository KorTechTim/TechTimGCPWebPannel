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
            "valheim-nav-discord-v1.png",
            "valheim-nav-youtube-v1.png",
            "valheim-nav-update-v1.png",
            "valheim-nav-logout-v1.png",
            "valheim-control-viking-server-v1.png",
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
        for name in ("discord", "youtube", "guide", "update", "logout"):
            self.assertIn(f"valheim-nav-{name}-v1.png", html)
        for label in ("테크팀 디스코드", "테크팀 유튜브", "공식 가이드", "패널 업데이트", "로그아웃"):
            self.assertIn(f'class="top-action-label">{label}', html)
        self.assertEqual(html.count('href="https://www.youtube.com/@kortechtim"'), 1)
        self.assertIn('class="brand" href="#overview"', html)
        self.assertIn('href="https://discord.gg/Awy6Uh38KW"', html)
        self.assertIn('id="panel-update-notice"', html)
        self.assertIn('id="panel-update-button"', html)
        self.assertIn('src="/static/valheim-control-viking-server-v1.png"', html)

    def test_server_control_uses_artwork_instead_of_helper_messages(self):
        html = self.read("dashboard.html")
        script = self.read("app.js")
        css = self.read("valheim-palshell.css")
        self.assertNotIn('id="control-hint"', html)
        self.assertNotIn("Steam 정식 배포 서버를 설치합니다.", html)
        self.assertNotIn("$('control-hint')", script)
        self.assertIn('class="control-art"', html)
        self.assertIn(".control-art img", css)
        self.assertIn("opacity: .38", css)

    def test_management_shortcut_text_is_enlarged(self):
        css = self.read("valheim-palshell.css")
        self.assertIn(".management-shortcut b { font-size: 18px;", css)
        self.assertIn("font-size: 13.5px; line-height: 1.25;", css)

    def test_dashboard_keeps_palworld_style_operational_hub(self):
        html = self.read("dashboard.html")
        self.assertIn("valheim-palshell.css", html)
        self.assertIn('id="quick-settings-form"', html)
        self.assertIn('id="detail-view"', html)
        self.assertIn('class="resource-grid"', html)
        self.assertIn('id="network-rx"', html)
        self.assertIn('id="network-tx"', html)
        self.assertEqual(html.count("VM TOTAL · 24H"), 2)
        self.assertEqual(html.count('class="management-shortcut"'), 8)
        self.assertIn('id="panel-update-button"', html)
        for target in (
            "modifiers-dialog",
            "worlds-dialog",
            "server-files-dialog",
            "backups-dialog",
            "permissions-dialog",
            "schedule-dialog",
            "mods-dialog",
            "discord-dialog",
            "panel-update-dialog",
        ):
            with self.subTest(target=target):
                self.assertIn(f'data-open="{target}"', html)
        self.assertNotIn('id="open-settings"', html)
        self.assertLess(html.index('id="install"'), html.index('id="start"'))

    def test_resources_refresh_each_second_with_24_hour_history(self):
        html = self.read("dashboard.html")
        script = self.read("app.js")
        css = self.read("valheim-palshell.css")
        self.assertIn("실시간 · 1초", html)
        self.assertIn('id="cpu-history-chart"', html)
        self.assertIn('id="memory-history-chart"', html)
        self.assertIn("const RESOURCE_REFRESH_MS = 1000;", script)
        self.assertIn("const RESOURCE_HISTORY_WINDOW_MS = 24 * 60 * 60 * 1000;", script)
        self.assertIn("RESOURCE_HISTORY_STORAGE_KEY", script)
        self.assertIn("appendResourceHistory", script)
        self.assertIn("setInterval(() => { if (!document.hidden) refreshResources(); }, RESOURCE_REFRESH_MS);", script)
        self.assertIn(".resource-history-chart canvas", css)

    def test_running_server_blurs_configuration_sections(self):
        html = self.read("dashboard.html")
        script = self.read("app.js")
        css = self.read("valheim-palshell.css")
        self.assertGreaterEqual(html.count("data-running-lock"), 12)
        self.assertIn("function serverConfigurationLocked()", script)
        self.assertIn("function updateRunningLocks()", script)
        self.assertIn("!serverConfigurationLocked()", script)
        self.assertIn("actions.setAttribute('data-running-lock', '')", script)
        self.assertIn(".is-running-locked[data-running-lock]", css)
        self.assertIn("cursor: not-allowed", css)
        self.assertIn("filter: blur(2px)", css)

    def test_missing_game_password_uses_modal_notice(self):
        html = self.read("dashboard.html")
        script = self.read("app.js")
        css = self.read("valheim-palshell.css")
        self.assertIn('id="notice-dialog"', html)
        self.assertIn('id="notice-ok"', html)
        self.assertIn("function showNotice(title, text)", script)
        self.assertIn("if (gamePasswordSet === false)", script)
        self.assertIn("if (passwordProvided) gamePasswordSet = true;", script)
        self.assertIn("게임 접속 비밀번호를 먼저 저장해주세요.", script)
        self.assertIn("backdrop-filter: blur(7px)", css)

    def test_detail_navigation_and_quick_settings_are_wired(self):
        script = self.read("app.js")
        self.assertIn("function openDetail", script)
        self.assertIn("function closeDetail", script)
        self.assertIn("async function loadQuickSettings", script)
        self.assertIn("quick-settings-form", script)
        self.assertIn("['completed', 'failed'].includes(update.status)", script)
        self.assertIn("async function checkPanelUpdate", script)
        self.assertIn("async function loadServerFiles", script)
        self.assertIn("function renderServerFilesPath", script)
        self.assertIn("button.onclick = () => loadServerFiles(location.path)", script)
        self.assertIn("async function uploadServerFile", script)
        self.assertIn("async function uploadServerFolder", script)
        self.assertIn("async function loadMods", script)
        self.assertIn("function renderModPackages", script)
        self.assertIn("/api/mods/install", script)
        self.assertIn("/api/mods/cleanup", script)
        html = self.read("dashboard.html")
        self.assertIn('aria-label="현재 서버 폴더 경로"', html)
        for control in ("mods-install", "mods-search", "mods-filter", "mods-list", "mods-config-editor",
                        "mods-export", "mods-import", "mods-disable-all", "mods-diagnose", "mods-cleanup"):
            self.assertIn(f'id="{control}"', html)

    def test_responsive_shell_has_mobile_breakpoints(self):
        css = self.read("valheim-palshell.css")
        self.assertIn("valheim-panel-bg-v2.png", css)
        self.assertIn("@media (max-width: 760px)", css)
        self.assertIn("@media (max-width: 440px)", css)
        self.assertIn("grid-template-columns: 1fr", css)
        self.assertIn(".explorer-shell", css)
        self.assertIn(".mod-manager-shell", css)
        self.assertIn("#panel-update-dialog .callout { width: 100%; max-width: none; }", css)


if __name__ == "__main__":
    unittest.main()
