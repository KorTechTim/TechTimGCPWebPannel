import json
import unittest
from unittest.mock import patch

from app.workshop import lookup_workshop_item, mod_ids_from_description, workshop_id_from_input


class WorkshopTests(unittest.TestCase):
    def test_accepts_workshop_url_or_numeric_id(self):
        self.assertEqual(workshop_id_from_input("3796373365"), "3796373365")
        self.assertEqual(
            workshop_id_from_input("https://steamcommunity.com/sharedfiles/filedetails/?id=3796373365"),
            "3796373365",
        )
        with self.assertRaises(ValueError):
            workshop_id_from_input("https://example.com/sharedfiles/filedetails/?id=3796373365")

    def test_extracts_unique_mod_ids_from_description(self):
        description = "[b]Workshop ID:[/b] 123456\n[b]Mod ID:[/b] FirstMod; SecondMod\nMod ID: FirstMod"
        self.assertEqual(mod_ids_from_description(description), ["FirstMod", "SecondMod"])

    @patch("app.workshop.urlopen")
    def test_lookup_uses_steam_api_and_returns_zomboid_mod_ids(self, mocked_urlopen):
        payload = {"response": {"publishedfiledetails": [{
            "publishedfileid": "3796373365",
            "result": 1,
            "creator_app_id": 108600,
            "consumer_app_id": 108600,
            "title": "It is of interest to me!",
            "description": "Workshop ID: 3796373365\nMod ID: ItIsOfInterestToMe",
            "preview_url": "https://example.invalid/preview.png",
        }]}}
        response = mocked_urlopen.return_value.__enter__.return_value
        response.read.return_value = json.dumps(payload).encode()

        item = lookup_workshop_item("3796373365")

        self.assertEqual(item["mod_ids"], ["ItIsOfInterestToMe"])
        self.assertEqual(item["title"], "It is of interest to me!")
        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/")
        self.assertIn(b"publishedfileids%5B0%5D=3796373365", request.data)


if __name__ == "__main__":
    unittest.main()
