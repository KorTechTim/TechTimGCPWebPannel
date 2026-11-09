import unittest

from app.config import PANEL_VERSION, ServerConfig, ServerRole


class ConfigTests(unittest.TestCase):
    def test_initial_version_and_defaults(self):
        config = ServerConfig()
        self.assertEqual(PANEL_VERSION, "1.0.6")
        self.assertEqual(config.backup_retention_count, 10)
        self.assertEqual(config.backup_retention_days, 15)
        self.assertEqual(config.slot_count, 16)
        self.assertEqual(config.game_settings["playerHealthFactor"], 1.0)
        self.assertEqual(config.game_settings["nightTimeDuration"], 720_000_000_000)

    def test_game_config_uses_official_role_shape(self):
        config = ServerConfig(roles=[ServerRole(
            name="Admins", password="strong-password", can_kick_ban=True,
            can_access_inventories=True, can_edit_world=True,
            can_edit_base=True, can_extend_base=True, reserved_slots=1,
        )])
        game = config.game_dict()
        self.assertEqual(game["queryPort"], 15637)
        self.assertEqual(game["userGroups"][0]["canKickBan"], True)
        self.assertNotIn("serverPassword", game)
        self.assertIn("gameSettings", game)

    def test_game_settings_validate_official_ranges(self):
        config = ServerConfig(game_settings={"enemyDamageFactor": 5, "weatherFrequency": "Often"})
        self.assertEqual(config.game_settings["enemyDamageFactor"], 5)
        with self.assertRaises(ValueError):
            ServerConfig(game_settings={"enemyDamageFactor": 5.1})
        with self.assertRaises(ValueError):
            ServerConfig(game_settings={"weatherFrequency": "Constant"})

    def test_roles_require_unique_names_passwords_and_valid_reserved_slots(self):
        with self.assertRaises(ValueError):
            ServerConfig(roles=[
                ServerRole(name="Admin", password="same"),
                ServerRole(name="admin", password="different"),
            ])
        with self.assertRaises(ValueError):
            ServerConfig(slot_count=2, roles=[
                ServerRole(name="Admin", password="one", reserved_slots=2),
                ServerRole(name="Friend", password="two", reserved_slots=1),
            ])


if __name__ == "__main__":
    unittest.main()
