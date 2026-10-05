import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen


STEAM_WORKSHOP_API = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
PROJECT_ZOMBOID_APP_ID = 108600
WORKSHOP_ID_RE = re.compile(r"[0-9]{5,20}")
MOD_ID_LINE_RE = re.compile(r"(?im)^\s*Mod\s+ID\s*:\s*([^\r\n]+)$")


class WorkshopLookupError(RuntimeError):
    pass


def workshop_id_from_input(value: str) -> str:
    value = str(value or "").strip()
    if WORKSHOP_ID_RE.fullmatch(value):
        return value
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "steamcommunity.com", "www.steamcommunity.com",
    }:
        raise ValueError("Steam 창작마당 URL 또는 숫자 ID를 입력해주세요.")
    workshop_id = parse_qs(parsed.query).get("id", [""])[0]
    if not WORKSHOP_ID_RE.fullmatch(workshop_id):
        raise ValueError("Steam 창작마당 URL에서 숫자 ID를 찾을 수 없습니다.")
    return workshop_id


def mod_ids_from_description(description: str) -> list[str]:
    plain_text = re.sub(r"\[[^\]]+\]", "", str(description or ""))
    result = []
    for match in MOD_ID_LINE_RE.finditer(plain_text):
        for value in re.split(r"\s*[;,]\s*", match.group(1).strip()):
            value = value.strip()
            if value and len(value) <= 128 and value not in result:
                result.append(value)
    return result


def lookup_workshop_item(value: str, timeout: int = 10) -> dict:
    workshop_id = workshop_id_from_input(value)
    request = Request(
        STEAM_WORKSHOP_API,
        data=urlencode({"itemcount": "1", "publishedfileids[0]": workshop_id}).encode(),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "TechTim-Zomboid-Panel/1.0",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise WorkshopLookupError("Steam 창작마당 정보를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.") from error

    details = payload.get("response", {}).get("publishedfiledetails", [])
    item = details[0] if details else {}
    if item.get("result") != 1 or str(item.get("publishedfileid", "")) != workshop_id:
        raise ValueError("해당 Steam 창작마당 항목을 찾을 수 없습니다.")
    app_ids = {str(item.get("creator_app_id", "")), str(item.get("consumer_app_id", ""))}
    if str(PROJECT_ZOMBOID_APP_ID) not in app_ids:
        raise ValueError("Project Zomboid용 창작마당 항목만 추가할 수 있습니다.")

    return {
        "workshop_id": workshop_id,
        "title": str(item.get("title") or f"Workshop {workshop_id}").strip()[:200],
        "mod_ids": mod_ids_from_description(item.get("description", "")),
        "preview_url": str(item.get("preview_url") or ""),
        "workshop_url": f"https://steamcommunity.com/sharedfiles/filedetails/?id={workshop_id}",
    }
