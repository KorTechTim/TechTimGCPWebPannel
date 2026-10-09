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

        for name in ("valheim-file-folder-v1.svg", "valheim-file-document-v1.svg"):
            asset = STATIC_DIR / name
            with self.subTest(asset=name):
                self.assertTrue(asset.is_file())
                self.assertGreater(asset.stat().st_size, 700)
                self.assertTrue(asset.read_text(encoding="utf-8").startswith("<svg"))

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
        self.assertIn(".management-shortcut b { font-size: 15.6px;", css)
        self.assertIn("font-size: 11.7px; line-height: 1.25;", css)

    def test_panel_update_text_is_compact_and_available_while_server_runs(self):
        html = self.read("dashboard.html")
        script = self.read("app.js")
        css = self.read("valheim-palshell.css")
        self.assertIn("#panel-update-dialog .dialog-head h2 { font-size: 19px; }", css)
        self.assertIn("#panel-update-dialog .feature-status strong { font-size: 17px; }", css)
        self.assertIn("#panel-update-dialog .feature-status p { font-size: 11px;", css)
        self.assertIn("#panel-update-message { font-size: 12px;", css)
        self.assertIn("#panel-update-dialog .dialog-foot button { font-size: 12px; }", css)
        self.assertIn("게임 서버 실행 여부와 관계없이 진행할 수 있으며", html)
        self.assertIn("$('panel-update-action').disabled = !available;", script)

    def test_engine_update_checks_steam_build_before_installing(self):
        script = self.read("app.js")
        self.assertIn("update = await api('/api/install/check');", script)
        self.assertIn("if (update.installed && update.update_available === false)", script)
        self.assertIn("showNotice('서버 업데이트', '이미 엔진이 최신 버전입니다');", script)

    def test_stop_button_uses_danger_styling(self):
        css = self.read("valheim-palshell.css")
        self.assertIn("#stop { border-color: #9d3d36; background: #b94b43; color: #fff; }", css)
        self.assertIn("#stop:disabled { border-color: #d5a49f; background: #ead5d2;", css)

    def test_server_update_button_has_heading_spacing(self):
        css = self.read("valheim-palshell.css")
        self.assertIn(".control-card > .outlined-gold { margin-top: 10px; }", css)

    def test_server_file_table_text_is_reduced_thirty_percent(self):
        css = self.read("valheim-palshell.css")
        self.assertIn("font-size: 14px; text-align: left; vertical-align: middle;", css)
        self.assertIn(".explorer-table th { background: #e9efed; color: #53646a; font-size: 12.6px;", css)
        self.assertIn(".explorer-name { min-width: 0; padding: 4px 0;", css)
        self.assertIn("font-size: 15.4px; text-align: left;", css)
        self.assertIn(".explorer-row-actions button { padding: 10px 14px; font-size: 12.6px; }", css)

    def test_server_file_explorer_uses_icons_and_configuration_editor(self):
        html = self.read("dashboard.html")
        script = self.read("app.js")
        css = self.read("valheim-palshell.css")
        self.assertIn('id="server-file-editor-dialog"', html)
        self.assertIn('id="server-file-editor-content"', html)
        self.assertIn('id="server-file-editor-save"', html)
        self.assertIn("valheim-file-folder-v1.svg", script)
        self.assertIn("valheim-file-document-v1.svg", script)
        self.assertIn("if (entry.editable)", script)
        self.assertIn("async function openServerFileEditor(path)", script)
        self.assertIn("/api/server-files/text?path=", script)
        self.assertIn(".explorer-editable-file').forEach", script)
        self.assertIn("event.ctrlKey || event.metaKey", script)
        self.assertIn(".server-file-editor-dialog {", css)

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
        self.assertNotIn("실행 중인 서버만 정상 종료한 뒤 다시 시작합니다.", html)
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

    def test_permissions_page_can_verify_and_copy_steam_id(self):
        html = self.read("dashboard.html")
        script = self.read("app.js")
        css = self.read("valheim-palshell.css")
        for control in ("steam-id-check", "steam-id-dialog", "steam-platform-id", "steam-id-copy"):
            self.assertIn(f'id="{control}"', html)
        self.assertIn("/api/steam/openid/start", script)
        self.assertIn("techtim-steam-id", script)
        self.assertIn("/^Steam_\\d{17}$/", script)
        self.assertIn(".steam-id-result", css)

    def test_discord_page_has_webhook_settings_and_event_controls(self):
        html = self.read("dashboard.html")
        script = self.read("app.js")
        css = self.read("valheim-palshell.css")
        for control in ("discord-form", "discord-webhook-url", "discord-enabled", "discord-test", "discord-save"):
            self.assertIn(f'id="{control}"', html)
        for event in ("start", "stop", "restart", "backup", "errors"):
            self.assertIn(f'id="discord-notify-{event}"', html)
        self.assertNotIn("Webhook 암호화 저장과 전송 범위 검증을 마친 뒤 활성화됩니다.", html)
        self.assertIn("async function loadDiscord()", script)
        self.assertIn("jsonPost('/api/discord'", script)
        self.assertIn("api('/api/discord/test'", script)
        self.assertIn("'discord-dialog': loadDiscord", script)
        self.assertIn(".discord-event-grid", css)

    def test_settings_callout_has_section_spacing(self):
        html = self.read("dashboard.html")
        css = self.read("valheim-palshell.css")
        self.assertIn('<dialog id="settings-dialog"', html)
        self.assertIn("#settings-dialog .dialog-body > .callout { margin-bottom: 15px; }", css)

    def test_settings_guidance_text_is_thirty_percent_larger(self):
        css = self.read("valheim-palshell.css")
        self.assertIn("#settings-dialog .dialog-body label small { font-size: 14.3px; }", css)
        self.assertIn("#settings-dialog .dialog-body > .micro { font-size: 13px; }", css)

    def test_detail_navigation_and_quick_settings_are_wired(self):
        script = self.read("app.js")
        css = self.read("valheim-palshell.css")
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
        for control in ("mods-install-essential", "mods-install", "mods-search", "mods-filter", "mods-list", "mods-config-editor",
                        "mods-export", "mods-import", "mods-disable-all", "mods-diagnose", "mods-cleanup"):
            self.assertIn(f'id="{control}"', html)
        self.assertNotIn("모드는 서버 실행 코드입니다.", html)
        self.assertIn("valheim-essential-mod-v1.png", html)
        self.assertIn("/api/mods/recommended/bepinex", script)
        self.assertIn(".mod-essential", css)

    def test_responsive_shell_has_mobile_breakpoints(self):
        css = self.read("valheim-palshell.css")
        self.assertIn("valheim-panel-bg-v2.png", css)
        self.assertIn("@media (max-width: 760px)", css)
        self.assertIn("@media (max-width: 440px)", css)
        self.assertIn("grid-template-columns: 1fr", css)
        self.assertIn(".explorer-shell", css)
        self.assertIn(".mod-manager-shell", css)
        self.assertIn("#panel-update-dialog .callout { width: 100%; max-width: none;", css)


if __name__ == "__main__":
    unittest.main()
