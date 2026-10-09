from io import BytesIO
from urllib.parse import parse_qs, urlsplit
import unittest

from app.steam_openid import SteamOpenID, SteamOpenIDError


class Response(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class SteamOpenIDTests(unittest.TestCase):
    def openid_response(self, helper):
        auth_url = helper.begin("https://panel.example:8080", "https://panel.example:8080/api/steam/openid/callback")
        auth_query = parse_qs(urlsplit(auth_url).query)
        return_to = auth_query["openid.return_to"][0]
        state = parse_qs(urlsplit(return_to).query)["state"][0]
        claimed_id = "https://steamcommunity.com/openid/id/76561198000000000"
        return state, {
            "openid.mode": "id_res",
            "openid.op_endpoint": "https://steamcommunity.com/openid/login",
            "openid.return_to": return_to,
            "openid.claimed_id": claimed_id,
            "openid.identity": claimed_id,
            "openid.response_nonce": "2026-10-09T00:00:00Znonce",
            "openid.signed": "op_endpoint,claimed_id,identity,return_to,response_nonce",
            "openid.sig": "signature",
        }

    def test_verifies_claimed_id_with_steam_provider(self):
        helper = SteamOpenID()
        state, parameters = self.openid_response(helper)
        captured = {}

        def opener(request, **_kwargs):
            captured["body"] = request.data.decode()
            return Response(b"ns:http://specs.openid.net/auth/2.0\nis_valid:true\n")

        steam_id, origin = helper.verify(state, parameters, opener)
        self.assertEqual(steam_id, "76561198000000000")
        self.assertEqual(origin, "https://panel.example:8080")
        self.assertIn("openid.mode=check_authentication", captured["body"])
        self.assertNotIn(state, helper.pending)

    def test_rejects_changed_return_address(self):
        helper = SteamOpenID()
        state, parameters = self.openid_response(helper)
        parameters["openid.return_to"] = "https://attacker.example/callback"
        with self.assertRaisesRegex(SteamOpenIDError, "돌아올 주소"):
            helper.verify(state, parameters, lambda *_args, **_kwargs: Response(b"is_valid:true\n"))

    def test_rejects_unverified_provider_response(self):
        helper = SteamOpenID()
        state, parameters = self.openid_response(helper)
        with self.assertRaisesRegex(SteamOpenIDError, "인증되지 않은"):
            helper.verify(state, parameters, lambda *_args, **_kwargs: Response(b"is_valid:false\n"))


if __name__ == "__main__":
    unittest.main()
