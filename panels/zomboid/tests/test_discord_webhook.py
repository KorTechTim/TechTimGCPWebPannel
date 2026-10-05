import unittest
from unittest.mock import patch

from app.discord_webhook import (build_webhook_payload, execute_webhook,
                                 masked_webhook_url, normalize_webhook_url,
                                 webhook_execute_url)


WEBHOOK = "https://discord.com/api/webhooks/123456789012345678/abcdefghijklmnopqrstuvwxyz_ABCDEFG-123456"


class DiscordWebhookTests(unittest.TestCase):
    def test_normalizes_and_masks_official_webhook(self):
        self.assertEqual(normalize_webhook_url(f"{WEBHOOK}/"), WEBHOOK)
        self.assertEqual(masked_webhook_url(WEBHOOK), "Discord 웹훅 · 1234...5678")
        self.assertEqual(webhook_execute_url(WEBHOOK), f"{WEBHOOK}?wait=true")

    def test_rejects_non_discord_webhook(self):
        with self.assertRaisesRegex(ValueError, "Discord 공식 HTTPS"):
            normalize_webhook_url("https://example.com/api/webhooks/123/token")

    def test_payload_disables_mentions(self):
        payload = build_webhook_payload(
            username="TechTim Zomboid", title="서버 시작", description="정상 시작",
            color=0x5865F2, fields=[{"name": "서버", "value": "servertest"}],
        )
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        self.assertEqual(payload["embeds"][0]["fields"][0]["value"], "servertest")

    @patch("app.discord_webhook.urlopen")
    def test_execute_webhook_posts_json_and_waits(self, mocked_urlopen):
        response = mocked_urlopen.return_value.__enter__.return_value
        response.status = 200
        execute_webhook(WEBHOOK, {"content": "test"})
        request = mocked_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, f"{WEBHOOK}?wait=true")
        self.assertEqual(request.method, "POST")


if __name__ == "__main__":
    unittest.main()
