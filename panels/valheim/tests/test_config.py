import unittest
from pydantic import ValidationError
from app.config import Permissions, RestartSchedule, ServerConfig, server_arguments


class ConfigTests(unittest.TestCase):
    def test_official_arguments_and_default_save_options(self):
        args = server_arguments(ServerConfig(password="viking-secret"))
        self.assertEqual(args[args.index("-port") + 1], "2456")
        self.assertEqual(args[args.index("-saveinterval") + 1], "1800")
        self.assertEqual(args[args.index("-backups") + 1], "4")
        self.assertIn("-crossplay", args)
        self.assertNotIn("-preset", args)  # Preserve existing world modifiers by default.
        self.assertNotIn("-players", args)

    def test_names_are_individual_arguments_not_shell_code(self):
        name = 'Vikings "quoted" $(touch /tmp/never)'
        args = server_arguments(ServerConfig(server_name=name, password="private-secret"))
        self.assertEqual(args[args.index("-name") + 1], name)

    def test_steam_only_hidden_server_and_preset(self):
        args = server_arguments(ServerConfig(password="private-secret", crossplay=False, public=False, preset="hard"))
        self.assertNotIn("-crossplay", args)
        self.assertEqual(args[args.index("-public") + 1], "0")
        self.assertEqual(args[-2:], ["-preset", "hard"])

    def test_world_modifiers_and_rules_are_official_arguments(self):
        config = ServerConfig(password="private-secret", preset="hard", combat="veryhard",
                              death_penalty="casual", resources="most", raids="none",
                              portals="hard", no_build_cost=True, player_events=True,
                              passive_mobs=True, no_map=True)
        args = server_arguments(config)
        self.assertLess(args.index("-preset"), args.index("-modifier"))
        for pair in (("combat", "veryhard"), ("deathpenalty", "casual"),
                     ("resources", "most"), ("raids", "none"), ("portals", "hard")):
            self.assertIn(["-modifier", *pair], [args[i:i + 3] for i in range(len(args) - 2)])
        for rule in ("nobuildcost", "playerevents", "passivemobs", "nomap"):
            self.assertIn(["-setkey", rule], [args[i:i + 2] for i in range(len(args) - 1)])
        with self.assertRaises(ValidationError):
            ServerConfig(combat="impossible")

    def test_world_paths_control_characters_and_unsupported_fields_are_rejected(self):
        for value in ("../world", "a/b", "a\\b", "..", "a\n", " world", "a:"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                ServerConfig(world=value)
        with self.assertRaises(ValidationError): ServerConfig(max_players=100)
        with self.assertRaises(ValidationError): ServerConfig(preset="unsupported")

    def test_password_and_adjacent_port_validation(self):
        for data in ({"password": "1234"}, {"server_name": "secret-server", "password": "secret"}, {"port": 65535}):
            with self.subTest(data=data), self.assertRaises(ValidationError): ServerConfig(**data)
        with self.assertRaises(ValueError): server_arguments(ServerConfig())
        self.assertEqual(ServerConfig(world="우리 월드").world, "우리 월드")

    def test_schedule_times_are_validated_sorted_and_deduplicated(self):
        self.assertEqual(RestartSchedule(times=["12:00", "04:00", "04:00"]).times, ["04:00", "12:00"])
        for times in (["24:00"], [], ["1:00"], ["01:00", "02:00", "03:00", "04:00"]):
            with self.assertRaises(ValidationError): RestartSchedule(times=times)

    def test_permission_ids_are_not_arbitrary_file_content(self):
        self.assertEqual(Permissions(kind="admin", ids=["Steam_76561198000000000", "Steam_76561198000000000"]).ids, ["Steam_76561198000000000"])
        with self.assertRaises(ValidationError): Permissions(kind="../auth", ids=[])
        with self.assertRaises(ValidationError): Permissions(kind="admin", ids=["Steam_1\nSteam_2"])
