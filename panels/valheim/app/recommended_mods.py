from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import certifi
import json
import re
import ssl


BEPINEX_PACKAGE_API = "https://thunderstore.io/api/experimental/package/denikson/BepInExPack_Valheim/"
MAX_METADATA_BYTES = 256 * 1024
MAX_PACKAGE_BYTES = 32 * 1024 * 1024


class RecommendedModError(RuntimeError):
    pass


def _trusted_thunderstore_url(value: str) -> bool:
    parsed = urlsplit(value)
    host = (parsed.hostname or "").casefold()
    return parsed.scheme == "https" and (host == "thunderstore.io" or host.endswith(".thunderstore.io"))


def _read_limited(response, limit: int) -> bytes:
    length = response.headers.get("Content-Length")
    if length and int(length) > limit:
        raise RecommendedModError("Thunderstore 패키지 크기가 허용 범위를 초과했습니다.")
    content = response.read(limit + 1)
    if len(content) > limit:
        raise RecommendedModError("Thunderstore 패키지 크기가 허용 범위를 초과했습니다.")
    return content


def download_recommended_bepinex(destination: Path, opener=urlopen) -> dict:
    headers = {"Accept": "application/json", "User-Agent": "TechTim-Valheim-Panel/1.0"}
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    try:
        with opener(Request(BEPINEX_PACKAGE_API, headers=headers), timeout=20, context=ssl_context) as response:
            metadata = json.loads(_read_limited(response, MAX_METADATA_BYTES))
        latest = metadata.get("latest") if isinstance(metadata, dict) else None
        if not isinstance(latest, dict):
            raise RecommendedModError("Thunderstore의 최신 BepInEx 정보를 확인하지 못했습니다.")
        if latest.get("namespace") != "denikson" or latest.get("name") != "BepInExPack_Valheim":
            raise RecommendedModError("Thunderstore 패키지 정보가 예상한 BepInEx와 다릅니다.")
        version = str(latest.get("version_number") or "")
        download_url = str(latest.get("download_url") or "")
        if not re.fullmatch(r"[0-9A-Za-z.+-]{1,40}", version) or not _trusted_thunderstore_url(download_url):
            raise RecommendedModError("Thunderstore의 BepInEx 다운로드 정보를 신뢰할 수 없습니다.")

        with opener(Request(download_url, headers={"User-Agent": headers["User-Agent"]}), timeout=30,
                    context=ssl_context) as response:
            if not _trusted_thunderstore_url(response.geturl()):
                raise RecommendedModError("BepInEx 다운로드가 허용되지 않은 주소로 연결되었습니다.")
            content = _read_limited(response, MAX_PACKAGE_BYTES)
        destination.write_bytes(content)
        return {
            "name": "BepInExPack_Valheim",
            "version": version,
            "filename": f"denikson-BepInExPack_Valheim-{version}.zip",
        }
    except RecommendedModError:
        destination.unlink(missing_ok=True)
        raise
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as error:
        destination.unlink(missing_ok=True)
        raise RecommendedModError("Thunderstore에서 BepInEx를 내려받지 못했습니다. 잠시 후 다시 시도해주세요.") from error
