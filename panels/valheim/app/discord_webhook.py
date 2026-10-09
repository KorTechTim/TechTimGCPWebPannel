from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
import json
import re
import ssl
import threading

import certifi

from .storage import read_json, write_json


DISCORD_WEBHOOK_HOSTS = {
    "discord.com",
    "ptb.discord.com",
    "canary.discord.com",
    "discordapp.com",
}
DISCORD_WEBHOOK_PATH_RE = re.compile(
    r"^/api(?:/v\d+)?/webhooks/(?P<webhook_id>\d{17,20})/(?P<token>[A-Za-z0-9._-]{20,})/?$"
)
EVENT_SETTINGS = {
    "server_start": "notify_server_start",
    "server_stop": "notify_server_stop",
    "server_restart": "notify_server_restart",
    "backup": "notify_backup",
    "error": "notify_errors",
}
EVENT_COLORS = {
    "server_start": 0x2F9E72,
    "server_stop": 0xB6493D,
    "server_restart": 0xD49A3A,
    "backup": 0x3D78A8,
    "error": 0xB13C45,
    "test": 0x5865F2,
}


def normalize_webhook_url(value: str) -> str:
    raw = str(value or "").strip()
    try:
        parsed = urlsplit(raw)
    except ValueError as error:
        raise ValueError("올바른 Discord 웹훅 URL을 입력해주세요.") from error
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or hostname not in DISCORD_WEBHOOK_HOSTS:
        raise ValueError("Discord 공식 HTTPS 웹훅 URL만 사용할 수 있습니다.")
    if parsed.username or parsed.password or parsed.port or parsed.fragment:
        raise ValueError("올바른 Discord 웹훅 URL을 입력해주세요.")
    if not DISCORD_WEBHOOK_PATH_RE.fullmatch(parsed.path):
        raise ValueError("Discord 채널에서 생성한 웹훅 URL을 입력해주세요.")
    return urlunsplit(("https", hostname, parsed.path.rstrip("/"), parsed.query, ""))


def masked_webhook_url(value: str) -> str:
    if not value:
        return ""
    matched = DISCORD_WEBHOOK_PATH_RE.fullmatch(urlsplit(value).path)
    if not matched:
        return "등록된 웹훅"
    webhook_id = matched.group("webhook_id")
    return f"Discord 웹훅 · {webhook_id[:4]}...{webhook_id[-4:]}"


def webhook_execute_url(value: str) -> str:
    parsed = urlsplit(normalize_webhook_url(value))
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["wait"] = "true"
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))


def build_webhook_payload(*, username: str, title: str, description: str, color: int,
                          fields: list[dict[str, Any]] | None = None,
                          timestamp: datetime | None = None) -> dict[str, Any]:
    safe_fields = []
    for field in (fields or [])[:25]:
        safe_fields.append({
            "name": str(field.get("name") or "-")[:256],
            "value": str(field.get("value") or "-")[:1024],
            "inline": bool(field.get("inline", True)),
        })
    sent_at = timestamp or datetime.now(timezone.utc)
    if sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=timezone.utc)
    return {
        "username": str(username or "TechTim Valheim Server")[:80],
        "allowed_mentions": {"parse": []},
        "embeds": [{
            "title": str(title or "Valheim 서버 알림")[:256],
            "description": str(description or "서버 상태가 변경되었습니다.")[:4096],
            "color": max(0, min(0xFFFFFF, int(color))),
            "fields": safe_fields,
            "footer": {"text": "TechTim Valheim Server Panel"},
            "timestamp": sent_at.astimezone(timezone.utc).isoformat(timespec="seconds"),
        }],
    }


def execute_webhook(url: str, payload: dict[str, Any], timeout: float = 8.0) -> None:
    request = Request(
        webhook_execute_url(url),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "TechTim-Valheim-Panel/1.0"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout,
                     context=ssl.create_default_context(cafile=certifi.where())) as response:
            if response.status not in {200, 204}:
                raise RuntimeError(f"Discord가 HTTP {response.status} 응답을 반환했습니다.")
    except HTTPError as error:
        try:
            details = json.loads(error.read().decode("utf-8")).get("message")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            details = None
        raise RuntimeError(f"Discord 웹훅 전송에 실패했습니다: {details or f'HTTP {error.code}'}") from error
    except (URLError, TimeoutError) as error:
        reason = getattr(error, "reason", error)
        raise RuntimeError(f"Discord 웹훅에 연결하지 못했습니다: {reason}") from error


class DiscordIntegration:
    def __init__(self, path: Path, log: Callable[[str], None]):
        self.path = path
        self.log = log
        self.lock = threading.Lock()

    @staticmethod
    def defaults() -> dict[str, Any]:
        return {
            "enabled": False,
            "webhook_url": "",
            "username": "TechTim Valheim Server",
            "notify_server_start": True,
            "notify_server_stop": True,
            "notify_server_restart": True,
            "notify_backup": True,
            "notify_errors": True,
        }

    def normalize(self, raw: Any) -> dict[str, Any]:
        stored = raw if isinstance(raw, dict) else {}
        defaults = self.defaults()
        webhook_url = str(stored.get("webhook_url") or "").strip()
        if webhook_url:
            try:
                webhook_url = normalize_webhook_url(webhook_url)
            except ValueError:
                webhook_url = ""
        username = str(stored.get("username") or defaults["username"]).strip()[:80]
        return {
            "enabled": bool(stored.get("enabled", False)),
            "webhook_url": webhook_url,
            "username": username or defaults["username"],
            **{name: bool(stored.get(name, True)) for name in EVENT_SETTINGS.values()},
        }

    def read(self) -> dict[str, Any]:
        with self.lock:
            return self.normalize(read_json(self.path, {}))

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.read()
        webhook_url = current["webhook_url"]
        if payload.get("clear_webhook"):
            webhook_url = ""
        elif str(payload.get("webhook_url") or "").strip():
            webhook_url = normalize_webhook_url(payload["webhook_url"])
        if payload.get("enabled") and not webhook_url:
            raise ValueError("Discord 연동을 사용하려면 웹훅 URL을 먼저 등록해주세요.")
        saved = self.normalize({**payload, "webhook_url": webhook_url})
        with self.lock:
            write_json(self.path, saved)
        return self.public(saved)

    def public(self, config: dict[str, Any] | None = None) -> dict[str, Any]:
        current = config or self.read()
        return {
            "enabled": current["enabled"],
            "username": current["username"],
            "webhook_configured": bool(current["webhook_url"]),
            "webhook_hint": masked_webhook_url(current["webhook_url"]),
            **{name: current[name] for name in EVENT_SETTINGS.values()},
        }

    def deliver(self, config: dict[str, Any], event: str, title: str, message: str,
                fields: list[dict[str, Any]] | None = None) -> None:
        execute_webhook(config["webhook_url"], build_webhook_payload(
            username=config["username"], title=title, description=message,
            color=EVENT_COLORS.get(event, EVENT_COLORS["test"]), fields=fields,
        ))

    def test(self, fields: list[dict[str, Any]] | None = None) -> None:
        config = self.read()
        if not config["webhook_url"]:
            raise ValueError("테스트할 Discord 웹훅 URL을 먼저 저장해주세요.")
        self.deliver(config, "test", "Discord 연동 테스트 성공",
                     "TechTim Valheim Server Panel과 Discord 채널이 정상적으로 연결되었습니다.", fields)

    def notify(self, event: str, title: str, message: str,
               fields: list[dict[str, Any]] | None = None) -> None:
        config = self.read()
        setting = EVENT_SETTINGS.get(event)
        if not config["enabled"] or not config["webhook_url"] or (setting and not config[setting]):
            return

        def send():
            try:
                self.deliver(config, event, title, message, fields)
            except Exception as error:
                self.log(f"Discord 알림 전송 실패: {error}")

        threading.Thread(target=send, daemon=True, name=f"discord-notify-{event}").start()
