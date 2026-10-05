from pathlib import Path
import json
import tempfile
import unittest
import zipfile

from app.mods import ModManager


def package(path: Path, filename: str, files: dict[str, bytes | str]) -> Path:
    destination = path / filename
    with zipfile.ZipFile(destination, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return destination


def manifest(name: str, version: str, dependencies=()) -> str:
    return json.dumps({"name": name, "version_number": version, "dependencies": list(dependencies)})


class ModManagerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.server = self.root / "server"
        self.server.mkdir()
        self.manager = ModManager(self.root, self.server, 20 * 1024**2)

    def loader(self, version="5.4.2351"):
        return package(self.root, f"denikson-BepInExPack_Valheim-{version}.zip", {
            "manifest.json": manifest("BepInExPack_Valheim", version),
            "BepInExPack_Valheim/BepInEx/core/BepInEx.dll": b"loader",
            "BepInExPack_Valheim/BepInEx/core/BepInEx.Preloader.dll": b"preloader",
            "BepInExPack_Valheim/doorstop_libs/libdoorstop_x64.so": b"doorstop",
            "BepInExPack_Valheim/.doorstop_version": b"4.4.0",
            "BepInExPack_Valheim/doorstop_config.ini": b"[General]\nenabled=true\ntarget_assembly=BepInEx\\core\\BepInEx.Preloader.dll\n",
            "BepInExPack_Valheim/start_server_bepinex.sh": b"export DOORSTOP_ENABLED=1\nexport DOORSTOP_TARGET_ASSEMBLY=./BepInEx/core/BepInEx.Preloader.dll\n",
        })

    def plugin(self, name="ExampleMod", version="1.0.0", dependencies=("denikson-BepInExPack_Valheim-5.4.2351",)):
        return package(self.root, f"TechTim-{name}-{version}.zip", {
            "manifest.json": manifest(name, version, dependencies),
            f"{name}.dll": f"{name}-{version}",
            "assets/config.json": "{}",
        })

    def test_install_enables_loader_and_plugin_in_dependency_order(self):
        results = self.manager.install_files([(self.plugin(), "TechTim-ExampleMod-1.0.0.zip"),
                                              (self.loader(), "denikson-BepInExPack_Valheim-5.4.2351.zip")])
        self.assertEqual(len(results), 2)
        self.assertTrue(all(result["enabled"] for result in results), results)
        self.assertTrue(self.manager.loader_ready())
        packages = self.manager.packages()
        self.assertEqual(sum(package["enabled"] for package in packages), 2)
        plugin = next(package for package in packages if not package["is_loader"])
        self.assertTrue(any(path.endswith("ExampleMod.dll") for path in plugin["deployed"]))

    def test_dependency_and_loader_protection_then_disable_all(self):
        self.manager.install_files([(self.loader(), self.loader().name), (self.plugin(), self.plugin().name)])
        loader = next(package for package in self.manager.packages() if package["is_loader"])
        with self.assertRaisesRegex(ValueError, "다른 모드가 사용 중"):
            self.manager.set_enabled(loader["id"], False)
        self.assertEqual(self.manager.disable_all(), 2)
        self.assertFalse(any(package["enabled"] for package in self.manager.packages()))
        self.assertFalse(self.manager.loader_ready())

    def test_missing_dependency_is_retained_disabled_with_issue(self):
        loader = self.loader()
        self.manager.install_files([(loader, loader.name)])
        plugin = self.plugin(dependencies=("TechTim-Absent-1.0.0",))
        results = self.manager.install_files([(plugin, plugin.name)])
        self.assertFalse(results[0]["enabled"])
        self.assertIn("TechTim-Absent-1.0.0", results[0]["message"])
        stored = next(package for package in self.manager.packages() if package["name"] == "ExampleMod")
        self.assertFalse(stored["enabled"])

    def test_update_preserves_enabled_state_and_remove_uses_trash(self):
        loader, old = self.loader(), self.plugin()
        self.manager.install_files([(loader, loader.name), (old, old.name)])
        plugin = next(package for package in self.manager.packages() if package["name"] == "ExampleMod")
        replacement = self.plugin(version="2.0.0")
        updated = self.manager.update(plugin["id"], replacement, replacement.name)
        self.assertTrue(updated["enabled"])
        self.assertEqual(updated["version"], "2.0.0")
        self.manager.remove(updated["id"])
        self.assertFalse(any(package["name"] == "ExampleMod" for package in self.manager.packages()))
        self.assertTrue(any(self.manager.trash.iterdir()))

    def test_existing_mod_cleanup_preserves_server_and_archives_originals(self):
        loader, plugin = self.loader(), self.plugin()
        self.manager.install_files([(loader, loader.name), (plugin, plugin.name)])
        (self.server / "BepInEx" / "config").mkdir(parents=True, exist_ok=True)
        (self.server / "BepInEx" / "config" / "manual.cfg").write_text("enabled=true")
        (self.server / "valheim_server.x86_64").write_bytes(b"server")
        (self.server / "unrelated.dll").write_bytes(b"keep")

        plan = self.manager.cleanup_plan()
        self.assertGreaterEqual(plan["file_count"], 6)
        self.assertIn("/server/BepInEx", [entry["path"] for entry in plan["entries"]])
        with self.assertRaisesRegex(ValueError, "다시 확인"):
            self.manager.cleanup_existing("bad")

        changed_plan = self.manager.cleanup_plan()
        (self.server / "BepInEx" / "config" / "changed.cfg").write_text("changed")
        with self.assertRaisesRegex(ValueError, "변경"):
            self.manager.cleanup_existing(changed_plan["token"])

        result = self.manager.cleanup_existing(self.manager.cleanup_plan()["token"])
        archive = self.server / result["archive"].removeprefix("/server/")
        self.assertEqual(self.manager.packages(), [])
        self.assertFalse(self.manager.loader_ready())
        self.assertTrue((archive / "server" / "BepInEx" / "config" / "manual.cfg").is_file())
        self.assertTrue((archive / "registered-mods").is_dir())
        self.assertEqual((self.server / "valheim_server.x86_64").read_bytes(), b"server")
        self.assertEqual((self.server / "unrelated.dll").read_bytes(), b"keep")

    def test_configuration_edit_creates_backup(self):
        config = self.server / "BepInEx" / "config" / "example.cfg"
        config.parent.mkdir(parents=True)
        config.write_text("enabled=true\n")
        self.assertEqual(self.manager.read_configuration("example.cfg"), "enabled=true\n")
        self.manager.write_configuration("example.cfg", "enabled=false\n")
        self.assertEqual(config.read_text(), "enabled=false\n")
        self.assertEqual(len(list(config.parent.glob("example.cfg.techtim-*.bak"))), 1)

    def test_modpack_roundtrip_imports_packages_disabled(self):
        loader, plugin = self.loader(), self.plugin()
        self.manager.install_files([(loader, loader.name), (plugin, plugin.name)])
        archive, _ = self.manager.export_pack()
        other_root = self.root / "other"
        other_server = other_root / "server"
        other_server.mkdir(parents=True)
        other = ModManager(other_root, other_server, 20 * 1024**2)
        self.assertEqual(other.import_pack(archive), 2)
        self.assertEqual(len(other.packages()), 2)
        self.assertFalse(any(package["enabled"] for package in other.packages()))

    def test_archives_reject_traversal_symlinks_and_windows_only_loader(self):
        traversal = self.root / "traversal.zip"
        with zipfile.ZipFile(traversal, "w") as archive:
            archive.writestr("../escape.dll", b"bad")
        result = self.manager.install_files([(traversal, traversal.name)])
        self.assertFalse(result[0]["enabled"])
        self.assertIn("안전하지 않은 경로", result[0]["message"])

        windows = package(self.root, "denikson-BepInExPack_Valheim-5.4.2202.zip", {
            "manifest.json": manifest("BepInExPack_Valheim", "5.4.2202"),
            "Pack/BepInEx/core/BepInEx.dll": b"loader",
            "Pack/BepInEx/core/BepInEx.Preloader.dll": b"preloader",
            "Pack/winhttp.dll": b"windows",
        })
        result = self.manager.install_files([(windows, windows.name)])
        self.assertFalse(result[0]["enabled"])
        self.assertIn("Linux 서버용", result[0]["message"])

    def test_modpack_cannot_deploy_files_outside_supported_mod_paths(self):
        archive = self.root / "malicious-modpack.zip"
        package_id = "a" * 32
        metadata = {"id": package_id, "name": "BadPack", "enabled": False, "deployed": {}}
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr(f"{package_id}/package.json", json.dumps(metadata))
            bundle.writestr(f"{package_id}/files/valheim_server.x86_64", b"replacement")
            bundle.writestr(f"{package_id}/files/BadPack.dll", b"plugin")
        with self.assertRaisesRegex(ValueError, "허용되지 않은 파일"):
            self.manager.import_pack(archive)
        self.assertEqual(self.manager.packages(), [])


if __name__ == "__main__":
    unittest.main()
