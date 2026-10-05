import tempfile
import unittest
from pathlib import Path

from app.config import SandboxConfig, ServerConfig, Settings, ini_values, sandbox_values


class ConfigTests(unittest.TestCase):
    def test_default_ports_and_app_values(self):
        values = ini_values(ServerConfig())
        self.assertEqual(values["DefaultPort"], "16261")
        self.assertEqual(values["UDPPort"], "16262")
        self.assertEqual(values["Map"], "Muldraugh, KY")

    def test_password_minimum_is_four(self):
        with self.assertRaises(ValueError):
            ServerConfig(admin_password="abc")
        self.assertEqual(ServerConfig(admin_password="abcd").admin_password, "abcd")

    def test_workshop_ids_are_numeric_and_unique(self):
        config = ServerConfig(workshop_items=["123456", "123456", "987654"])
        self.assertEqual(config.workshop_items, ["123456", "987654"])
        with self.assertRaises(ValueError):
            ServerConfig(workshop_items=["not-a-number"])

    def test_sandbox_values_include_dotted_build42_keys(self):
        values = sandbox_values(SandboxConfig(respawn_multiplier=.25, drag_down=False))
        self.assertEqual(values["ZombieConfig.RespawnMultiplier"], "0.25")
        self.assertEqual(values["ZombieLore.DragDown"], "false")

    def test_settings_runtime_image(self):
        with tempfile.TemporaryDirectory() as root:
            settings = Settings(data_dir=Path(root), host_data_dir=Path(root))
            self.assertIn("zomboid-runtime", settings.runtime_image)

    def test_installer_uses_project_zomboid_verification_key(self):
        repository = Path(__file__).resolve().parents[3]
        installer = (repository / "zomboid" / "zomboid-webui-install.sh").read_text()
        self.assertIn("--data-urlencode 'game=project_zomboid'", installer)
        self.assertNotIn("--data-urlencode 'game=zomboid'", installer)


if __name__ == "__main__":
    unittest.main()
