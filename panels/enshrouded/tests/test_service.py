import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from docker.errors import NotFound

from app.config import Settings
from app.service import PanelService


class MissingContainers:
    def get(self, _name):
        raise NotFound("missing")


class FakeClient:
    def __init__(self):
        self.containers = MissingContainers()
    def close(self):
        pass


class LogContainer:
    def logs(self, **_kwargs):
        return b"2099-01-01T00:00:00.000000000Z SERVER-LATEST\n"


class LogClient:
    def __init__(self):
        self.containers = self
    def get(self, _name):
        return LogContainer()
    def close(self):
        pass


class CreatedContainer:
    id = "created-container"


class CreateContainers:
    def __init__(self):
        self.create_calls = []
    def get(self, _name):
        raise NotFound("missing")
    def create(self, image, **kwargs):
        if "stop_timeout" in kwargs:
            raise TypeError("run() got an unexpected keyword argument 'stop_timeout'")
        self.create_calls.append((image, kwargs))
        return CreatedContainer()


class CreateClient:
    def __init__(self, containers):
        self.containers = containers
    def close(self):
        pass


class PullApi:
    def __init__(self):
        self.call = None
    def pull(self, repository, tag=None, stream=False, decode=False):
        self.call = (repository, tag, stream, decode)
        return iter([
            {"status": "Pulling fs layer", "id": "abc123"},
            {"status": "Downloading", "id": "abc123", "progress": "[====> ] 42%"},
            {"status": "Pull complete", "id": "abc123"},
        ])


class PullClient:
    def __init__(self):
        self.api = PullApi()
    def close(self):
        pass


class UpdateImage:
    id = "sha256:local-image-id"
    attrs = {"RepoDigests": ["ghcr.io/kortechtim/enshrouded-panel@sha256:current-digest"]}


class UpdateContainer:
    image = UpdateImage()
    def reload(self):
        pass


class RegistryImage:
    def __init__(self, digest):
        self.id = digest


class UpdateClient:
    def __init__(self, digest):
        self.containers = self
        self.images = self
        self.digest = digest
    def get(self, _name):
        return UpdateContainer()
    def get_registry_data(self, _image):
        return RegistryImage(self.digest)
    def close(self):
        pass


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.service = PanelService(
            Settings(data_dir=self.root, host_data_dir=self.root, scheduler_enabled=False, pull_runtime=False),
            lambda: FakeClient(),
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_render_preserves_future_official_settings(self):
        existing = json.loads(self.service.game_config_path.read_text())
        existing["futureOfficialSetting"] = {"enabled": True}
        existing["gameSettings"] = {"futureGameSetting": "kept"}
        self.service.game_config_path.write_text(json.dumps(existing), encoding="utf-8")

        payload = self.service.config().model_dump()
        payload["server_name"] = "Ember Valley"
        payload["roles"][0]["password"] = "admin-new-password"
        payload["roles"][1]["password"] = "friend-new-password"
        payload["roles"][2]["password"] = "guest-new-password"
        payload["game_settings"]["playerHealthFactor"] = 1.5
        self.service.save_config(payload)

        rendered = json.loads(self.service.game_config_path.read_text())
        self.assertEqual(rendered["name"], "Ember Valley")
        self.assertEqual(rendered["futureOfficialSetting"], {"enabled": True})
        self.assertEqual(rendered["gameSettings"]["playerHealthFactor"], 1.5)
        self.assertEqual(rendered["gameSettings"]["futureGameSetting"], "kept")

    def test_combined_logs_keep_latest_lines_from_every_source(self):
        self.service.docker_factory = lambda: LogClient()
        self.service.logs_dir.joinpath("install.log").write_text(
            "[2026-01-01 00:00:00] INSTALL-MARKER\n", encoding="utf-8",
        )
        self.service.logs_dir.joinpath("control.log").write_text(
            "".join(f"[2026-01-01 00:00:{index % 60:02d}] CONTROL-{index}\n" for index in range(750)),
            encoding="utf-8",
        )

        combined = self.service.logs("all", tail=700)

        self.assertIn("[서버] 2099-01-01T00:00:00.000000000Z SERVER-LATEST", combined)
        self.assertIn("[작업]", combined)

    def test_operation_tracks_install_progress(self):
        self.service._operation(
            "running", "서버 설치", "SteamCMD 설치 중", progress=72, stage="steamcmd",
        )
        operation = self.service.status()["operation"]
        self.assertEqual(operation["progress"], 72)
        self.assertEqual(operation["stage"], "steamcmd")

    def test_container_creation_omits_unsupported_stop_timeout(self):
        containers = CreateContainers()
        service = PanelService(
            Settings(data_dir=self.root, host_data_dir=self.root, scheduler_enabled=False, pull_runtime=False),
            lambda: CreateClient(containers),
        )

        container_id = service._ensure_container(start=False)

        self.assertEqual(container_id, "created-container")
        self.assertEqual(len(containers.create_calls), 1)
        self.assertNotIn("stop_timeout", containers.create_calls[0][1])

    def test_runtime_pull_streams_layer_progress_into_install_log(self):
        service = PanelService(
            Settings(data_dir=self.root, host_data_dir=self.root, scheduler_enabled=False, pull_runtime=True),
            lambda: FakeClient(),
        )
        client = PullClient()

        service._pull_runtime(client)

        install_log = service.logs("install")
        self.assertIn("레이어 abc123", install_log)
        self.assertIn("42%", install_log)
        self.assertEqual(client.api.call, ("ghcr.io/kortechtim/enshrouded-runtime", "wine-v1", True, True))

    def test_panel_update_check_compares_registry_digest(self):
        self.service.docker_factory = lambda: UpdateClient("sha256:current-digest")
        current = self.service.panel_update_status(check=True)
        self.assertTrue(current["checked"])
        self.assertFalse(current["update_available"])
        self.assertIn("최신 버전", current["message"])

        self.service.docker_factory = lambda: UpdateClient("sha256:new-digest")
        available = self.service.panel_update_status(check=True)
        self.assertTrue(available["update_available"])
        self.assertEqual(available["latest_digest"], "new-digest")

    def test_start_allows_default_role_passwords(self):
        config = self.service.validate_start_requirements()
        self.assertEqual(config.roles[0].password, "change-admin-password")

    def test_backup_and_migration_round_trip(self):
        self.service.savegame.joinpath("world0.ksd").write_bytes(b"world-data")
        payload = self.service.config().model_dump()
        payload["server_name"] = "Old Cloud Realm"
        payload["roles"][0]["password"] = "admin-secret"
        payload["roles"][1]["password"] = "friend-secret"
        payload["roles"][2]["password"] = "guest-secret"
        self.service.save_config(payload)
        archive = self.service.create_migration_archive()

        second_root = self.root / "new-account"
        second = PanelService(
            Settings(data_dir=second_root, host_data_dir=second_root, scheduler_enabled=False, pull_runtime=False),
            lambda: FakeClient(),
        )
        second.import_migration_archive(archive)

        self.assertEqual(second.config().server_name, "Old Cloud Realm")
        self.assertEqual((second.savegame / "world0.ksd").read_bytes(), b"world-data")
        self.assertEqual(second.config().roles[0].password, "admin-secret")

    def test_empty_savegame_backup_keeps_restore_directory(self):
        backup = self.service.create_backup("empty")
        with zipfile.ZipFile(backup) as archive:
            self.assertIn("savegame/", archive.namelist())
        self.service.restore_backup(backup.name)
        self.assertTrue(self.service.savegame.is_dir())

    def test_migration_rejects_unrelated_zip(self):
        archive = self.root / "bad.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("notes.txt", "not a migration")
        with self.assertRaises(ValueError):
            self.service.import_migration_archive(archive)


if __name__ == "__main__":
    unittest.main()
