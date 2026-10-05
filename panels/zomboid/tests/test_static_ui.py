import unittest
from pathlib import Path


class StaticUiTests(unittest.TestCase):
    def test_required_detail_pages_exist(self):
        html = (Path(__file__).parents[1] / "app/static/dashboard.html").read_text()
        for page in ("settings", "sandbox", "mods", "players", "backups", "advanced", "schedule", "files", "discord"):
            self.assertIn(f'data-page="{page}"', html)
        self.assertNotIn('data-page="panel-update"', html)
        self.assertNotIn('data-page="monitor"', html)
        self.assertNotIn('data-view="monitor"', html)
        self.assertIn("샌드박스 배율 직접 수정", html)
        self.assertNotIn("설정파일 직접수정", html)
        self.assertNotIn("고급 파일 설정", html)

    def test_generated_assets_are_referenced(self):
        html = (Path(__file__).parents[1] / "app/static/dashboard.html").read_text()
        css = (Path(__file__).parents[1] / "app/static/app.css").read_text()
        self.assertIn("zomboid-panel-mark.png", html)
        self.assertIn('<a class="brand" href="https://www.youtube.com/@kortechtim" target="_blank" rel="noreferrer"', html)
        self.assertNotIn('<a class="brand" href="#overview" data-view="overview">', html)
        self.assertIn('<img src="/static/techtim-profile.png?v=1"', html)
        self.assertIn("나만의 서버 만들기 채널", html)
        self.assertIn("나만의 서버 만들기 채널", (Path(__file__).parents[1] / "app/static/login.html").read_text())
        self.assertNotIn("ZOMBOID SERVER PANEL", html)
        self.assertIn('class="top-brand-icon"><img src="/static/t2-header-avatar-v1.png"', html)
        self.assertTrue((Path(__file__).parents[1] / "app/static/t2-header-avatar-v1.png").is_file())
        self.assertIn("zomboid-panel-bg.png", css)
        self.assertIn("zomboid-hero-zombie-hand-v1.png", css)
        self.assertIn("bottom:-96px", css)
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

    def test_server_control_uses_zombie_background_art(self):
        root = Path(__file__).parents[1]
        html = (root / "app/static/dashboard.html").read_text()
        css = (root / "app/static/app.css").read_text()
        self.assertIn('class="control-card-art"', html)
        self.assertIn('/static/zomboid-control-zombies-v1.png?v=1', html)
        self.assertIn('.control-card-art img{', css)
        self.assertTrue((root / "app/static/zomboid-control-zombies-v1.png").is_file())

    def test_header_uses_shared_panel_order(self):
        html = (Path(__file__).parents[1] / "app/static/dashboard.html").read_text()
        expected = ["테크팀 디스코드", "테크팀 유튜브", "공식 가이드", "패널 업데이트", "로그아웃"]
        positions = [html.index(label) for label in expected]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn('data-view="panel-update"><b>', html)

    def test_panel_update_opens_as_dialog(self):
        root = Path(__file__).parents[1]
        html = (root / "app/static/dashboard.html").read_text()
        script = (root / "app/static/app.js").read_text()
        css = (root / "app/static/app.css").read_text()
        self.assertIn('id="panel-update-dialog" class="app-dialog panel-update-dialog"', html)
        self.assertNotIn('id="panel-update-button" data-view=', html)
        self.assertIn("openPanelUpdateDialog", script)
        self.assertIn("showDialog(dialog)", script)
        self.assertIn(".panel-update-dialog{", css)
        self.assertIn('id="panel-update-progress"', html)
        self.assertIn('role="progressbar"', html)
        self.assertIn('data-update-step="download"', html)
        self.assertIn('data-update-step="complete"', html)
        self.assertIn("renderPanelUpdate", script)
        self.assertIn("startPanelUpdatePolling", script)
        self.assertIn("status: 'reconnecting'", script)
        self.assertIn(".panel-update-progress-track", css)

    def test_logout_requires_confirmation_dialog(self):
        root = Path(__file__).parents[1]
        html = (root / "app/static/dashboard.html").read_text()
        script = (root / "app/static/app.js").read_text()
        css = (root / "app/static/app.css").read_text()
        self.assertIn('id="logout-confirm-dialog" class="app-dialog confirm-dialog"', html)
        self.assertIn('id="confirm-logout"', html)
        self.assertIn("showDialog($('#logout-confirm-dialog'))", script)
        self.assertIn("/api/auth/logout", script)
        self.assertIn(".confirm-dialog{", css)

    def test_status_summary_is_overview_only(self):
        root = Path(__file__).parents[1]
        html = (root / "app/static/dashboard.html").read_text()
        script = (root / "app/static/app.js").read_text()
        self.assertIn('id="overview-status"', html)
        self.assertIn("$('#overview-status').hidden = name !== 'overview';", script)
        self.assertIn('<span>홈(HOME)</span>', html)
        self.assertIn("overview:'홈(HOME)'", script)
        self.assertNotIn("서버 개요", html)
        self.assertNotIn('class="operation"', html)
        self.assertNotIn("operation-name", script)

    def test_cpu_and_memory_show_eight_hour_history(self):
        root = Path(__file__).parents[1]
        html = (root / "app/static/dashboard.html").read_text()
        script = (root / "app/static/app.js").read_text()
        css = (root / "app/static/app.css").read_text()
        self.assertIn('id="cpu-history-chart"', html)
        self.assertIn('id="memory-history-chart"', html)
        self.assertIn("RESOURCE_REFRESH_MS = 1000", script)
        self.assertIn("RESOURCE_HISTORY_WINDOW_MS = 8 * 60 * 60 * 1000", script)
        self.assertIn("setInterval(() => refreshResources().catch(() => {}), RESOURCE_REFRESH_MS)", script)
        self.assertIn("RESOURCE_HISTORY_STORAGE_KEY", script)
        self.assertIn(".history-chart", css)
        self.assertIn(".monitor-grid.compact header strong{font-size:28px", css)
        self.assertIn(".monitor-grid.compact .history-metric b{font-size:44px}", css)
        self.assertIn(".monitor-grid.compact article>span{margin-top:18px!important;color:#8bbcaf;font-size:32px", css)
        self.assertIn("@media(max-width:1600px){.monitor-grid.compact{grid-template-columns:repeat(2", css)

    def test_copy_endpoint_copies_ip_and_shows_temporary_tooltip(self):
        root = Path(__file__).parents[1]
        html = (root / "app/static/dashboard.html").read_text()
        script = (root / "app/static/app.js").read_text()
        css = (root / "app/static/app.css").read_text()
        self.assertIn('id="copy-endpoint-tooltip"', html)
        self.assertIn("클립보드에 IP가 저장되었습니다.", html)
        self.assertIn("await copyText(location.hostname)", script)
        self.assertIn("navigator.clipboard?.writeText", script)
        self.assertIn("document.execCommand('copy')", script)
        self.assertIn("setTimeout(() => tooltip.classList.remove('visible'), 2000)", script)
        self.assertIn(".copy-tooltip.visible", css)
        self.assertNotIn("navigator.clipboard.writeText(`${location.hostname}:", script)

    def test_running_server_locks_stopped_only_pages(self):
        root = Path(__file__).parents[1]
        html = (root / "app/static/dashboard.html").read_text()
        script = (root / "app/static/app.js").read_text()
        css = (root / "app/static/app.css").read_text()
        self.assertIn('id="server-running-lock-dialog"', html)
        self.assertIn('data-persistent="true"', html)
        self.assertIn("서버 기동중에는 조작할 수 없습니다.", html)
        self.assertIn("설정을 원하실 경우 서버를 종료해주세요.", html)
        self.assertIn("STOPPED_ONLY_VIEWS = new Set(['settings', 'sandbox', 'mods', 'players', 'backups', 'advanced', 'files'])", script)
        self.assertIn("if (STOPPED_ONLY_VIEWS.has(name))", script)
        self.assertIn("if (serverIsRunning()) { showServerRunningLock(); return; }", script)
        self.assertIn(".server-running-lock-dialog{", css)

    def test_start_without_engine_shows_installation_dialog(self):
        root = Path(__file__).parents[1]
        html = (root / "app/static/dashboard.html").read_text()
        script = (root / "app/static/app.js").read_text()
        css = (root / "app/static/app.css").read_text()
        self.assertIn('id="engine-required-dialog"', html)
        self.assertIn("아직 게임이 설치되지 않았습니다.", html)
        self.assertIn("먼저 게임엔진부터 설치해주세요.", html)
        self.assertIn('id="confirm-engine-required"', html)
        self.assertIn("if (!status.engine.installed) { showDialog($('#engine-required-dialog')); return; }", script)
        self.assertIn(".engine-required-dialog{", css)

    def test_sidebar_places_system_tools_below_basic_settings(self):
        html = (Path(__file__).parents[1] / "app/static/dashboard.html").read_text()
        positions = [html.index(label) for label in ("기본 설정", "예약 작업", "서버 폴더 탐색기", "디스코드 연동", "SETTINGS &amp; WORLD")]
        self.assertEqual(positions, sorted(positions))
        world_positions = [html.index(label) for label in ("샌드박스 배율</span>", "샌드박스 배율 직접 수정", "모드 · 워크숍")]
        self.assertEqual(world_positions, sorted(world_positions))
        self.assertIn('<p class="nav-group">SETTINGS &amp; WORLD</p>', html)
        self.assertNotIn('<p class="nav-group">SYSTEM</p>', html)

    def test_file_explorer_uses_game_specific_icons(self):
        root = Path(__file__).parents[1]
        script = (root / "app/static/app.js").read_text()
        css = (root / "app/static/app.css").read_text()
        self.assertIn("zomboid-file-folder-v1.png", script)
        self.assertIn("zomboid-file-document-v1.png", script)
        self.assertIn("file-entry-icon", css)

    def test_file_explorer_typography_is_doubled(self):
        css = (Path(__file__).parents[1] / "app/static/app.css").read_text()
        self.assertIn('.view[data-page="files"] .breadcrumbs button{padding:5px 8px;font-size:24px}', css)
        self.assertIn('.view[data-page="files"] .explorer-tools button{padding:11px 15px;font-size:22px}', css)
        self.assertIn('.view[data-page="files"] .file-entry-name{font-size:22px', css)
        self.assertIn('.view[data-page="files"] .file-row small{font-size:20px', css)
        self.assertIn('.view[data-page="files"] .file-row button,.view[data-page="files"] .file-row a{padding:8px 10px;font-size:22px', css)

    def test_file_explorer_opens_text_editor_dialog(self):
        root = Path(__file__).parents[1]
        html = (root / "app/static/dashboard.html").read_text()
        script = (root / "app/static/app.js").read_text()
        css = (root / "app/static/app.css").read_text()
        self.assertIn('id="file-editor-dialog"', html)
        self.assertIn('id="file-editor-content"', html)
        self.assertIn('id="save-file-editor"', html)
        self.assertIn("async function openFileEditor(path)", script)
        self.assertIn("/api/files/text?path=", script)
        self.assertIn("openFileEditor(entry.path)", script)
        self.assertIn("event.ctrlKey || event.metaKey", script)
        self.assertIn(".file-editor-dialog{", css)

    def test_file_explorer_supports_folder_uploads(self):
        root = Path(__file__).parents[1]
        html = (root / "app/static/dashboard.html").read_text()
        script = (root / "app/static/app.js").read_text()
        css = (root / "app/static/app.css").read_text()
        self.assertIn('id="folder-upload"', html)
        self.assertIn("webkitdirectory directory multiple", html)
        self.assertIn("file.webkitRelativePath || file.name", script)
        self.assertIn("/api/files/upload-folder", script)
        self.assertIn(".file-upload-actions{", css)

    def test_settings_legends_are_inside_frames(self):
        css = (Path(__file__).parents[1] / "app/static/app.css").read_text()
        self.assertIn(".form-sections legend{float:left;width:100%", css)
        self.assertIn(".form-sections legend+*{clear:both}", css)
        self.assertIn('.view[data-page="settings"] .form-grid input', css)
        self.assertIn('.view[data-page="settings"] .toggle-grid label', css)
        self.assertIn('.view[data-page="settings"] .toggle-grid+.form-grid{margin-top:18px}', css)
        self.assertIn('.view[data-page="schedule"] .schedule-times input', css)
        self.assertIn('.view[data-page="schedule"] .callout', css)

    def test_sandbox_editor_is_schema_driven_and_categorized(self):
        root = Path(__file__).parents[1]
        html = (root / "app/static/dashboard.html").read_text()
        script = (root / "app/static/app.js").read_text()
        css = (root / "app/static/app.css").read_text()
        self.assertIn('id="sandbox-categories"', html)
        self.assertIn('id="sandbox-search"', html)
        self.assertIn('id="reset-sandbox"', html)
        self.assertIn("/api/sandbox/schema", script)
        self.assertIn("sandbox-category-panel", script)
        self.assertIn("sandboxSchemaCache.fields.map", script)
        self.assertIn("전체 설정 저장을 눌러 적용하세요", script)
        self.assertIn(".sandbox-categories", css)
        self.assertIn(".sandbox-page-actions", css)
        self.assertIn(".sandbox-field-title{overflow:hidden;font-size:13px", css)
        self.assertIn("-webkit-line-clamp:3", css)

    def test_mod_editor_pairs_workshop_and_mod_ids(self):
        root = Path(__file__).parents[1]
        html = (root / "app/static/dashboard.html").read_text()
        script = (root / "app/static/app.js").read_text()
        self.assertIn('id="mod-pair-list"', html)
        self.assertIn('id="add-mod-pair"', html)
        self.assertIn('id="lookup-workshop"', html)
        self.assertIn("창작 마당ID로 바로 추가", html)
        self.assertIn('class="panel map-order-panel"', html)
        self.assertIn('https://steamcommunity.com/app/108600/workshop/', html)
        self.assertNotIn('id="workshop-items"', html)
        self.assertNotIn('id="mod-ids"', html)
        self.assertIn("function collectModPairs()", script)
        self.assertIn("/api/workshop/lookup", script)
        self.assertIn("config.workshop_mod_pairs = pairs.items", script)
        self.assertIn("payload.workshop_mod_pairs = configCache?.workshop_mod_pairs || []", script)
        self.assertIn("workshop.workshop_mod_pairs", script)
        self.assertIn("config.workshop_items = pairs.workshopItems", script)
        self.assertIn("config.mod_ids = pairs.modIds", script)

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
        self.assertEqual(html.count('class="nav-icon"'), 11)
        self.assertIn(".nav-item .nav-icon img", css)

    def test_sidebar_uses_survivor_background_art(self):
        root = Path(__file__).parents[1]
        css = (root / "app/static/app.css").read_text()
        asset = root / "app/static/zomboid-sidebar-survivor-v1.jpg"
        self.assertTrue(asset.is_file())
        self.assertIn("zomboid-sidebar-survivor-v1.jpg", css)
        self.assertIn("@media(max-width:820px){.sidebar{background:#121917}}", css)

    def test_discord_integration_has_menu_and_controls(self):
        root = Path(__file__).parents[1]
        html = (root / "app/static/dashboard.html").read_text()
        script = (root / "app/static/app.js").read_text()
        css = (root / "app/static/app.css").read_text()
        self.assertIn('data-view="discord"', html)
        self.assertIn('data-page="discord"', html)
        self.assertIn('id="discord-form"', html)
        self.assertIn('id="test-discord"', html)
        self.assertIn("/api/discord/test", script)
        self.assertIn("discordWebhookConfigured", script)
        self.assertIn('id="discord-status" class="discord-status" role="status" aria-live="polite" hidden', html)
        self.assertNotIn("Discord 채널에서 생성한 웹훅 URL을 등록해주세요.", script)
        self.assertIn('.view[data-page="discord"]', css)
        self.assertIn(".sidebar nav{min-height:0;overflow-y:auto", css)

    def test_overview_hero_copy_is_top_aligned(self):
        root = Path(__file__).parents[1]
        html = (root / "app/static/dashboard.html").read_text()
        css = (root / "app/static/app.css").read_text()
        self.assertIn('class="hero-copy"', html)
        self.assertIn(".hero-copy{align-self:flex-start}", css)

    def test_management_terminal_has_command_controls_and_help(self):
        root = Path(__file__).parents[1]
        html = (root / "app/static/dashboard.html").read_text()
        script = (root / "app/static/app.js").read_text()
        css = (root / "app/static/app.css").read_text()
        self.assertIn("관리 터미널", html)
        self.assertIn('id="terminal-command-form"', html)
        self.assertIn('id="command-help-dialog"', html)
        self.assertIn('id="export-support-log"', html)
        self.assertIn('href="/api/logs/export"', html)
        self.assertIn("/api/console/command", script)
        self.assertIn(".command-help-grid dd{font-size:12px", css)
        self.assertNotIn("<span>실시간 로그</span>", html)

    def test_log_panels_default_to_all_category(self):
        root = Path(__file__).parents[1]
        html = (root / "app/static/dashboard.html").read_text()
        script = (root / "app/static/app.js").read_text()
        self.assertEqual(html.count('class="log-tab active" data-log="all"'), 2)
        self.assertIn("let currentLog = 'all';", script)

    def test_server_start_uses_fast_log_refresh_without_overlapping_requests(self):
        root = Path(__file__).parents[1]
        script = (root / "app/static/app.js").read_text()
        self.assertIn("const LOG_REFRESH_ACTIVE_MS = 1000;", script)
        self.assertIn("const LOG_REFRESH_START_WINDOW_MS = 2 * 60 * 1000;", script)
        self.assertIn("if (logRefreshPending) return;", script)
        self.assertIn("if (action === 'start' || action === 'restart') startFastLogRefresh();", script)
        self.assertNotIn("setInterval(() => loadLogs().catch(() => {}), 5000);", script)

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
        self.assertIn('id="panel-update-dialog" class="app-dialog panel-update-dialog"', html)
        self.assertIn('id="logout-confirm-dialog" class="app-dialog confirm-dialog"', html)
        self.assertNotIn("window.prompt", script)


if __name__ == "__main__":
    unittest.main()
