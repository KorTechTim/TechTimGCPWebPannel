import json
import tempfile
import unittest
from pathlib import Path

from panels.palworld.app import main


class EngineUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.original_paths = {
            "DATA_DIR": main.DATA_DIR,
            "INSTALL_REQUEST_FILE": main.INSTALL_REQUEST_FILE,
            "STEAM_INSTALL_MARKER_FILE": main.STEAM_INSTALL_MARKER_FILE,
            "STEAM_APP_MANIFEST_FILE": main.STEAM_APP_MANIFEST_FILE,
        }
        main.DATA_DIR = self.root
        main.INSTALL_REQUEST_FILE = self.root / "install-request.txt"
        main.STEAM_INSTALL_MARKER_FILE = self.root / "server" / ".techtim-installed.json"
        main.STEAM_APP_MANIFEST_FILE = (
            self.root / "server" / "steamapps" / f"appmanifest_{main.PALWORLD_STEAM_APP_ID}.acf"
        )

    def tearDown(self):
        for name, value in self.original_paths.items():
            setattr(main, name, value)
        self.temporary_directory.cleanup()

    def write_current_install(self):
        server_root = self.root / "server"
        server_root.mkdir(parents=True, exist_ok=True)
        (server_root / "PalServer.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        main.STEAM_INSTALL_MARKER_FILE.write_text(
            json.dumps({"app_id": main.PALWORLD_STEAM_APP_ID}),
            encoding="utf-8",
        )
        main.INSTALL_REQUEST_FILE.write_text(
            "distribution=steamcmd-official\n"
            f"app_id={main.PALWORLD_STEAM_APP_ID}\n"
            f"runtime_image={main.PALWORLD_RUNTIME_IMAGE}\n",
            encoding="utf-8",
        )

    def test_app_id_matches_official_palworld_dedicated_server(self):
        self.assertEqual(main.PALWORLD_STEAM_APP_ID, "2394010")

    def test_legacy_official_image_configuration_migrates_to_steamcmd_runtime(self):
        self.assertEqual(
            main.resolve_palworld_runtime_image(main.LEGACY_PALWORLD_RUNTIME_IMAGE),
            main.DEFAULT_PALWORLD_RUNTIME_IMAGE,
        )

    def test_legacy_install_is_recognized_but_requires_update(self):
        main.INSTALL_REQUEST_FILE.write_text(
            "distribution=pocketpair-official-docker\n",
            encoding="utf-8",
        )

        self.assertTrue(main.has_any_official_runtime_install_marker())
        self.assertFalse(main.has_official_runtime_install_marker())

    def test_current_install_requires_valid_steamcmd_engine_files(self):
        self.write_current_install()

        self.assertTrue(main.has_any_official_runtime_install_marker())
        self.assertTrue(main.has_official_runtime_install_marker())

        main.STEAM_INSTALL_MARKER_FILE.unlink()
        self.assertFalse(main.has_official_runtime_install_marker())

    def test_reads_installed_build_id_from_steam_manifest(self):
        main.STEAM_APP_MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
        main.STEAM_APP_MANIFEST_FILE.write_text(
            '"AppState"\n{\n  "appid" "2394010"\n  "buildid" "20485731"\n}\n',
            encoding="utf-8",
        )

        self.assertEqual(main.installed_steam_build_id(), "20485731")

    def test_runtime_installer_runs_official_steamcmd_update(self):
        runtime_root = Path(main.__file__).resolve().parents[1] / "runtime"
        entrypoint = (runtime_root / "entrypoint.sh").read_text(encoding="utf-8")

        self.assertIn('APP_ID="2394010"', entrypoint)
        self.assertIn('+app_update "$APP_ID" validate +quit', entrypoint)

    def test_runtime_drops_root_before_starting_palworld(self):
        runtime_root = Path(main.__file__).resolve().parents[1] / "runtime"
        dockerfile = (runtime_root / "Dockerfile").read_text(encoding="utf-8")
        entrypoint = (runtime_root / "entrypoint.sh").read_text(encoding="utf-8")

        self.assertIn("gosu", dockerfile)
        self.assertIn("useradd --uid 1000", dockerfile)
        self.assertIn('exec gosu "$PALWORLD_USER"', entrypoint)
        self.assertIn('chown -R "$PALWORLD_USER:$PALWORLD_USER" /server', entrypoint)
        self.assertIn('exec ./PalServer.sh "$@"', entrypoint)
        self.assertNotIn("/root/.steam", entrypoint)


if __name__ == "__main__":
    unittest.main()
