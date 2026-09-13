from pathlib import Path
import stat
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from app.storage import create_archive, extract_archive, inside, read_json, replace_directory, worlds, write_json
from helpers import ServiceCase


class StorageTests(ServiceCase):
    def test_json_updates_are_complete_and_private(self):
        path = self.root / "private.json"
        write_json(path, {"one": 1})
        write_json(path, {"two": 2})
        self.assertEqual(read_json(path, {}), {"two": 2})
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertFalse(list(self.root.glob(".*.tmp")))

    def test_corrupt_existing_json_does_not_reset_to_defaults(self):
        path = self.root / "broken.json"
        path.write_text("invalid")
        with self.assertRaises(ValueError): read_json(path, {"password": "admin"})

    def test_paths_cannot_escape_root_or_follow_symlinks(self):
        (self.service.saves / "link").symlink_to(self.root)
        for name in ("../auth.json", "/etc/passwd", "a/../../file", "a\\file", "link/valheim-config.json"):
            with self.subTest(name=name), self.assertRaises(ValueError): inside(self.service.saves, name)

    def test_world_inventory_reports_incomplete_pairs(self):
        self.world()
        (self.service.saves / "worlds_local" / "Incomplete.db").write_bytes(b"db")
        inventory = {w["name"]: w for w in worlds(self.service.saves)}
        self.assertTrue(inventory["Dedicated"]["complete"])
        self.assertFalse(inventory["Incomplete"]["complete"])

    def test_backup_and_restore_roundtrip_only_save_data(self):
        self.world()
        archive = self.service.backups / "test.zip"
        create_archive(self.service.saves, archive)
        target = self.root / "extract"
        extract_archive(archive, target, 10000)
        self.assertEqual((target / "worlds_local/Dedicated.db").read_bytes(), b"original db")
        self.assertFalse((target / "valheim-config.json").exists())

    def test_archive_rejects_traversal_links_duplicate_entries_and_size_limit(self):
        scenarios = [("../escape", b"unsafe", None), ("link", b"target", stat.S_IFLNK | 0o777),
                     ("large", b"x" * 101, None)]
        for index, (name, value, mode) in enumerate(scenarios):
            archive = self.root / f"bad{index}.zip"
            with zipfile.ZipFile(archive, "w") as output:
                entry = zipfile.ZipInfo(name)
                if mode: entry.external_attr = mode << 16
                output.writestr(entry, value)
            with self.assertRaises(ValueError): extract_archive(archive, self.root / f"out{index}", 100)
        self.assertFalse((self.root / "escape").exists())

    def test_world_pair_import_requires_explicit_overwrite_and_creates_backup(self):
        self.world()
        staged = self.root / "incoming"
        staged.mkdir()
        for ext in (".db", ".fwl"): (staged / ("Dedicated" + ext)).write_bytes(b"new")
        from app.service import BusyError
        with self.assertRaises(BusyError): self.service.import_world(staged, "Dedicated", False)
        self.service.import_world(staged, "Dedicated", True)
        self.assertEqual((self.service.saves / "worlds_local/Dedicated.db").read_bytes(), b"new")
        backup = next(self.service.backups.glob("*.zip"))
        with zipfile.ZipFile(backup) as archive:
            self.assertEqual(archive.read("worlds_local/Dedicated.db"), b"original db")

    def test_failed_directory_swap_restores_previous_data(self):
        current, staged = self.root / "current", self.root / "staged"
        current.mkdir(); staged.mkdir()
        (current / "value").write_text("original")
        original = Path.rename
        def rename(path, target):
            if path == staged: raise OSError("disk error")
            return original(path, target)
        with patch.object(Path, "rename", rename), self.assertRaises(OSError): replace_directory(current, staged)
        self.assertEqual((current / "value").read_text(), "original")

    def test_restore_makes_safety_backup_and_invalid_archive_leaves_world_untouched(self):
        self.world()
        first = self.service.backup()
        (self.service.saves / "worlds_local/Dedicated.db").write_bytes(b"new adventure")
        self.service.restore(first)
        self.assertEqual((self.service.saves / "worlds_local/Dedicated.db").read_bytes(), b"original db")
        self.assertEqual(len(self.service.list_backups()), 2)
        with zipfile.ZipFile(self.service.backups / "bad.zip", "w") as out: out.writestr("notes", "not a world")
        with self.assertRaises(ValueError): self.service.restore("bad.zip")
        self.assertEqual((self.service.saves / "worlds_local/Dedicated.db").read_bytes(), b"original db")
