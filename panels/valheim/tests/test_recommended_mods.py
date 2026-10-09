from io import BytesIO
from pathlib import Path
import json
import tempfile
import unittest

from app.recommended_mods import RecommendedModError, download_recommended_bepinex


class Response(BytesIO):
    def __init__(self, content, url, content_length=None):
        super().__init__(content)
        self.url = url
        self.headers = {"Content-Length": str(content_length if content_length is not None else len(content))}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def geturl(self):
        return self.url


class RecommendedModTests(unittest.TestCase):
    def test_downloads_latest_official_bepinex_archive(self):
        metadata = json.dumps({"latest": {
            "namespace": "denikson", "name": "BepInExPack_Valheim", "version_number": "5.4.2351",
            "download_url": "https://thunderstore.io/package/download/denikson/BepInExPack_Valheim/5.4.2351/",
        }}).encode()
        responses = iter([
            Response(metadata, "https://thunderstore.io/api/experimental/package/denikson/BepInExPack_Valheim/"),
            Response(b"zip-data", "https://gcdn.thunderstore.io/live/repository/packages/bepinex.zip"),
        ])

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "bepinex.zip"
            package = download_recommended_bepinex(destination, lambda *_args, **_kwargs: next(responses))
            self.assertEqual(destination.read_bytes(), b"zip-data")
            self.assertEqual(package["version"], "5.4.2351")
            self.assertTrue(package["filename"].endswith(".zip"))

    def test_rejects_download_redirect_outside_thunderstore(self):
        metadata = json.dumps({"latest": {
            "namespace": "denikson", "name": "BepInExPack_Valheim", "version_number": "5.4.2351",
            "download_url": "https://thunderstore.io/package/download/denikson/BepInExPack_Valheim/5.4.2351/",
        }}).encode()
        responses = iter([
            Response(metadata, "https://thunderstore.io/api/experimental/package/denikson/BepInExPack_Valheim/"),
            Response(b"zip-data", "https://example.com/bepinex.zip"),
        ])

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "bepinex.zip"
            with self.assertRaisesRegex(RecommendedModError, "허용되지 않은 주소"):
                download_recommended_bepinex(destination, lambda *_args, **_kwargs: next(responses))
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
