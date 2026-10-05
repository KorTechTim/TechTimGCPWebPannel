from io import BytesIO
import json
import time
import zipfile
from fastapi.testclient import TestClient

from app.auth import SESSION_COOKIE
from app.main import create_app
from app.storage import read_json, write_json
from helpers import ServiceCase


def mod_archive(files):
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return stream.getvalue()


class ApiTests(ServiceCase):
    def setUp(self):
        super().setUp()
        self.app = create_app(self.settings, lambda: self.docker)
        self.service = self.app.state.service
        self.auth = self.app.state.auth
        self.client = self.enterContext(TestClient(self.app))

    def authenticated(self):
        self.auth.set_password("testing-password")
        self.client.cookies.set(SESSION_COOKIE, self.auth.create_session())

    def test_login_password_change_and_dashboard_flow(self):
        self.assertEqual(self.client.get('/api/config').status_code, 401)
        response = self.client.post('/api/auth/login', json={"username": "admin", "password": "admin"})
        self.assertEqual(response.json()["redirect"], "/change-password")
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertEqual(self.client.get('/api/config').status_code, 403)
        old_cookie = self.client.cookies.get(SESSION_COOKIE)
        self.assertEqual(self.client.post('/api/auth/change-password', json={"new_password": "abc"}).status_code, 422)
        response = self.client.post('/api/auth/change-password', json={"new_password": "pass"})
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(self.client.cookies.get(SESSION_COOKIE), old_cookie)
        self.assertEqual(self.client.get('/api/config').status_code, 200)
        self.assertIn('VALHEIM', self.client.get('/').text)
        self.client.post('/api/auth/logout')
        self.assertEqual(self.client.get('/api/config').status_code, 401)

    def test_expired_sessions_are_rejected(self):
        self.auth.set_password("test-password")
        token = self.auth.create_session()
        write_json(self.auth.sessions_file, {self.auth.key(token): {"expires_at": time.time() - 1}})
        self.client.cookies.set(SESSION_COOKIE, token)
        self.assertEqual(self.client.get('/api/config').status_code, 401)

    def test_foreign_origin_post_is_rejected(self):
        response = self.client.post('/api/auth/login', json={"username": "admin", "password": "admin"}, headers={"Origin": "https://example.com"})
        self.assertEqual(response.status_code, 403)

    def test_authentication_applies_to_all_operational_routes(self):
        for method, url, kwargs in [
            ('get', '/api/worlds', {}), ('get', '/api/server/status', {}), ('get', '/api/logs', {}),
            ('get', '/api/backups', {}), ('get', '/api/permissions', {}), ('get', '/api/restart-schedule', {}),
            ('get', '/api/server-files', {}),
            ('get', '/api/mods', {}), ('get', '/api/mods/configs', {}), ('get', '/api/mods/diagnose', {}),
            ('get', '/api/panel/update/check', {}),
            ('post', '/api/install', {}), ('post', '/api/panel/update', {}), ('post', '/api/server/start', {}),
            ('post', '/api/config', {'json': {}}),
            ('post', '/api/server-files/mkdir', {'json': {'name': 'mods'}}),
            ('post', '/api/mods/disable-all', {}),
        ]:
            with self.subTest(url=url): self.assertEqual(getattr(self.client, method)(url, **kwargs).status_code, 401)

    def test_panel_update_check_reports_latest_registry_image(self):
        self.authenticated()
        self.docker.containers.add(self.settings.panel_container)

        current = self.client.get('/api/panel/update/check').json()
        self.assertEqual(current["status"], "ok")
        self.assertFalse(current["update_available"])

        self.docker.images.registry_digest = "sha256:new-image"
        available = self.client.get('/api/panel/update/check?force=true').json()
        self.assertEqual(available["status"], "ok")
        self.assertTrue(available["update_available"])

    def test_start_rejects_missing_engine_before_queuing(self):
        self.authenticated()
        response = self.client.post('/api/server/start')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.docker.containers.runs, [])

    def test_config_save_preserves_hidden_password_and_rejects_runtime_writes(self):
        self.authenticated()
        self.installed()
        response = self.client.post('/api/config', json={"world": "우리 월드", "port": 2480})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('viking-secret', response.text)
        self.assertEqual(self.service.config().password, 'viking-secret')
        self.docker.containers.add()
        self.assertEqual(self.client.post('/api/config', json={"world": "no"}).status_code, 409)

    def test_world_upload_accepts_matching_pair_and_blocks_overwrite(self):
        self.authenticated()
        files = {"db": ("Viking.db", b"db data"), "fwl": ("Viking.fwl", b"metadata")}
        self.assertEqual(self.client.post('/api/worlds/upload', files=files).status_code, 200)
        self.assertEqual(self.client.post('/api/worlds/upload', files=files).status_code, 409)
        self.assertEqual(self.client.post('/api/worlds/upload', files=files, data={"overwrite": "true"}).status_code, 200)
        self.assertEqual(len(self.service.list_backups()), 1)
        self.assertTrue(self.client.get('/api/worlds').json()["worlds"][0]["complete"])

    def test_world_upload_rejects_mismatch_empty_files_and_traversal(self):
        self.authenticated()
        cases = [(("one.db", b"data"), ("two.fwl", b"meta")),
                 (("empty.db", b""), ("empty.fwl", b"meta")),
                 (("../one.db", b"data"), ("../one.fwl", b"meta"))]
        for db, fwl in cases:
            with self.subTest(db=db[0]):
                self.assertEqual(self.client.post('/api/worlds/upload', files={"db": db, "fwl": fwl}).status_code, 400)
        self.assertEqual(self.client.get('/api/worlds').json()["worlds"], [])

    def test_server_file_explorer_browses_uploads_and_downloads(self):
        self.authenticated()
        (self.service.server / "config").mkdir()
        (self.service.server / "config" / "server.cfg").write_bytes(b"server-config")

        listing = self.client.get('/api/server-files').json()
        self.assertEqual(listing["path"], "")
        self.assertEqual(listing["entries"][0]["name"], "config")
        self.assertEqual(listing["entries"][0]["type"], "dir")

        self.assertEqual(self.client.post('/api/server-files/mkdir', json={"path": "config", "name": "mods"}).status_code, 200)
        upload = self.client.post(
            '/api/server-files/upload?path=config/mods',
            files={"file": ("example.dll", b"plugin-data")},
            data={"overwrite": "false"},
        )
        self.assertEqual(upload.status_code, 200)
        self.assertEqual((self.service.server / "config" / "mods" / "example.dll").read_bytes(), b"plugin-data")
        self.assertEqual(
            self.client.post('/api/server-files/upload?path=config/mods', files={"file": ("example.dll", b"new")}).status_code,
            409,
        )
        self.assertEqual(
            self.client.post(
                '/api/server-files/upload?path=config/mods',
                files={"file": ("example.dll", b"new")},
                data={"overwrite": "true"},
            ).status_code,
            200,
        )

        download = self.client.get('/api/server-files/download?path=config/mods/example.dll')
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.content, b"new")

        archive = self.client.post('/api/server-files/download-folders', json={"paths": ["config"]})
        self.assertEqual(archive.status_code, 200)
        with zipfile.ZipFile(BytesIO(archive.content)) as bundle:
            self.assertEqual(bundle.read("config/server.cfg"), b"server-config")
            self.assertEqual(bundle.read("config/mods/example.dll"), b"new")

    def test_server_folder_upload_preserves_browser_relative_paths(self):
        self.authenticated()
        response = self.client.post(
            '/api/server-files/upload-folder',
            files=[
                ("files", ("one.cfg", b"one")),
                ("files", ("two.cfg", b"two")),
                ("relative_paths", (None, "BepInEx/config/one.cfg")),
                ("relative_paths", (None, "BepInEx/plugins/two.cfg")),
                ("overwrite", (None, "false")),
            ],
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((self.service.server / "BepInEx" / "config" / "one.cfg").read_bytes(), b"one")
        self.assertEqual((self.service.server / "BepInEx" / "plugins" / "two.cfg").read_bytes(), b"two")

    def test_server_file_explorer_rejects_traversal_and_running_server(self):
        self.authenticated()
        self.assertEqual(self.client.get('/api/server-files?path=../outside').status_code, 400)
        self.assertEqual(
            self.client.post('/api/server-files/mkdir', json={"path": "", "name": "../outside"}).status_code,
            400,
        )
        self.docker.containers.add()
        self.assertEqual(self.client.get('/api/server-files').status_code, 409)
        self.assertEqual(
            self.client.post('/api/server-files/upload', files={"file": ("blocked.txt", b"blocked")}).status_code,
            409,
        )

    def test_mod_management_install_toggle_config_and_diagnose(self):
        self.authenticated(); self.installed()
        loader_manifest = json.dumps({"name": "BepInExPack_Valheim", "version_number": "5.4.2202", "dependencies": []})
        plugin_manifest = json.dumps({"name": "ExampleMod", "version_number": "1.0.0",
                                      "dependencies": ["denikson-BepInExPack_Valheim-5.4.2202"]})
        loader = mod_archive({
            "manifest.json": loader_manifest,
            "Pack/BepInEx/core/BepInEx.dll": b"loader",
            "Pack/BepInEx/core/BepInEx.Preloader.dll": b"preloader",
            "Pack/doorstop_libs/libdoorstop_x64.so": b"doorstop",
        })
        plugin = mod_archive({"manifest.json": plugin_manifest, "ExampleMod.dll": b"plugin"})
        response = self.client.post('/api/mods/install', files=[
            ("files", ("TechTim-ExampleMod-1.0.0.zip", plugin, "application/zip")),
            ("files", ("denikson-BepInExPack_Valheim-5.4.2202.zip", loader, "application/zip")),
        ])
        self.assertEqual(response.status_code, 200, response.text)
        payload = self.client.get('/api/mods').json()
        self.assertTrue(payload["loader_ready"])
        self.assertEqual(payload["enabled_count"], 1)
        plugin_package = next(item for item in payload["packages"] if item["name"] == "ExampleMod")

        toggled = self.client.post(f'/api/mods/{plugin_package["id"]}/toggle', json={"enabled": False})
        self.assertEqual(toggled.status_code, 200, toggled.text)
        self.assertEqual(self.client.get('/api/mods').json()["enabled_count"], 0)

        config = self.service.server / "BepInEx" / "config" / "example.cfg"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text("enabled=true\n")
        self.assertEqual(self.client.get('/api/mods/config?path=example.cfg').json()["content"], "enabled=true\n")
        saved = self.client.put('/api/mods/config', json={"path": "example.cfg", "content": "enabled=false\n"})
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(config.read_text(), "enabled=false\n")
        self.assertIn("BepInEx 로더", self.client.get('/api/mods/diagnose').json()["report"])

    def test_mod_mutations_are_blocked_while_server_runs(self):
        self.authenticated(); self.installed(); self.docker.containers.add()
        response = self.client.post('/api/mods/install', files={"files": ("mod.dll", b"plugin")})
        self.assertEqual(response.status_code, 409)

    def test_backup_download_is_attachment_and_backup_restoration_is_queued(self):
        self.authenticated(); self.world()
        response = self.client.post('/api/backups')
        self.assertEqual(response.status_code, 202)
        name = self.client.get('/api/backups').json()['backups'][0]['name']
        download = self.client.get(f'/api/backups/{name}/download')
        self.assertEqual(download.headers['content-type'], 'application/zip')
        self.assertIn('attachment', download.headers['content-disposition'])
        self.assertEqual(self.client.post(f'/api/backups/{name}/restore').status_code, 202)
        self.assertEqual(read_json(self.service.job_file, {})['status'], 'completed')

    def test_world_download_is_stopped_only_and_temporary_export_is_cleaned(self):
        self.authenticated(); self.world()
        response = self.client.get('/api/worlds/Dedicated/download')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(self.service.exports.iterdir()), [])
        self.docker.containers.add()
        self.assertEqual(self.client.get('/api/worlds/Dedicated/download').status_code, 409)

    def test_permission_list_save_does_not_touch_authentication(self):
        self.authenticated()
        original = self.auth.auth_file.read_bytes()
        response = self.client.post('/api/permissions', json={"kind": "admin", "ids": ["Steam_76561198000000000"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get('/api/permissions').json()['admin'], ['Steam_76561198000000000'])
        self.assertEqual(self.auth.auth_file.read_bytes(), original)

    def test_failed_background_install_reports_failure_without_success_marker(self):
        self.authenticated()
        self.docker.install_success = False
        self.assertEqual(self.client.post('/api/install').status_code, 202)
        status = self.client.get('/api/server/status').json()
        self.assertFalse(status['engine']['installed'])
        self.assertEqual(status['operation']['status'], 'failed')

    def test_login_rate_limit(self):
        for _ in range(10):
            self.assertEqual(self.client.post('/api/auth/login', json={"username": "admin", "password": "wrong"}).status_code, 401)
        self.assertEqual(self.client.post('/api/auth/login', json={"username": "admin", "password": "wrong"}).status_code, 429)
