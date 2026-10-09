from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import Mock, patch

from app.discord_webhook import (
    DiscordIntegration,
    build_webhook_payload,
    execute_webhook,
    masked_webhook_url,
    normalize_webhook_url,
    webhook_execute_url,
)


WEBHOOK = "https://discord.com/api/webhooks/123456789012345678/abcdefghijklmnopqrstuvwxyz_ABCDEFG-123456"


class Response:
    status = 204

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class DiscordWebhookTests(unittest.TestCase):
    def test_only_official_discord_webhook_urls_are_accepted(self):
        self.assertEqual(normalize_webhook_url(WEBHOOK + "/"), WEBHOOK)
        self.assertTrue(webhook_execute_url(WEBHOOK).endswith("?wait=true"))
        self.assertEqual(masked_webhook_url(WEBHOOK), "Discord 웹훅 · 1234...5678")
        for invalid in (
            "http://discord.com/api/webhooks/123/token",
            "https://example.com/api/webhooks/123456789012345678/token-token-token-token",
            "https://discord.com/channels/123/456",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                normalize_webhook_url(invalid)

    def test_payload_disables_mentions_and_limits_fields(self):
        payload = build_webhook_payload(
            username="TechTim Valheim Server", title="테스트", description="정상",
            color=0x5865F2, fields=[{"name": "월드", "value": "Dedicated"}],
        )
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        self.assertEqual(payload["embeds"][0]["fields"][0]["value"], "Dedicated")
        self.assertEqual(payload["embeds"][0]["footer"]["text"], "TechTim Valheim Server Panel")

    @patch("app.discord_webhook.urlopen", return_value=Response())
    def test_webhook_posts_json_and_waits_for_discord_result(self, mocked_urlopen):
        execute_webhook(WEBHOOK, {"content": "test"})
        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.method, "POST")
        self.assertIn("wait=true", request.full_url)
        self.assertEqual(request.headers["Content-type"], "application/json")

    def test_saved_secret_is_masked_from_public_response(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "discord-config.json"
            integration = DiscordIntegration(path, Mock())
            public = integration.save({
                **integration.defaults(), "enabled": True, "webhook_url": WEBHOOK,
                "clear_webhook": False,
            })
            self.assertTrue(public["webhook_configured"])
            self.assertNotIn(WEBHOOK, str(public))
            self.assertIn(WEBHOOK, path.read_text(encoding="utf-8"))
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_enabled_integration_requires_a_saved_webhook(self):
        with tempfile.TemporaryDirectory() as directory:
            integration = DiscordIntegration(Path(directory) / "discord-config.json", Mock())
            with self.assertRaisesRegex(ValueError, "웹훅 URL"):
                integration.save({**integration.defaults(), "enabled": True})


if __name__ == "__main__":
    unittest.main()
