from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
import re
import secrets
import ssl
import threading
import time

import certifi


STEAM_OPENID_ENDPOINT = "https://steamcommunity.com/openid/login"
OPENID_NAMESPACE = "http://specs.openid.net/auth/2.0"
OPENID_IDENTIFIER = f"{OPENID_NAMESPACE}/identifier_select"
STEAM_CLAIMED_ID = re.compile(r"^https?://steamcommunity\.com/openid/id/(?P<steam_id>\d{17})/?$")


class SteamOpenIDError(RuntimeError):
    pass


class SteamOpenID:
    def __init__(self, lifetime=300):
        self.lifetime = lifetime
        self.pending = {}
        self.lock = threading.Lock()

    def begin(self, origin: str, callback_url: str) -> str:
        parsed_origin = urlsplit(origin)
        parsed_callback = urlsplit(callback_url)
        if (parsed_origin.scheme not in {"http", "https"} or not parsed_origin.netloc
                or parsed_origin.username or parsed_origin.password
                or (parsed_callback.scheme, parsed_callback.netloc) != (parsed_origin.scheme, parsed_origin.netloc)):
            raise SteamOpenIDError("Steam 인증을 시작할 패널 주소를 확인하지 못했습니다.")
        state = secrets.token_urlsafe(32)
        return_to = f"{callback_url}?{urlencode({'state': state})}"
        now = time.time()
        with self.lock:
            self.pending = {key: value for key, value in self.pending.items() if value["expires_at"] > now}
            self.pending[state] = {"expires_at": now + self.lifetime, "origin": origin, "return_to": return_to}
        query = urlencode({
            "openid.ns": OPENID_NAMESPACE,
            "openid.mode": "checkid_setup",
            "openid.return_to": return_to,
            "openid.realm": f"{origin}/",
            "openid.identity": OPENID_IDENTIFIER,
            "openid.claimed_id": OPENID_IDENTIFIER,
        })
        return f"{STEAM_OPENID_ENDPOINT}?{query}"

    def verify(self, state: str, parameters: dict[str, str], opener=urlopen) -> tuple[str, str]:
        now = time.time()
        with self.lock:
            pending = self.pending.pop(state, None)
        if not pending or pending["expires_at"] <= now:
            raise SteamOpenIDError("SteamID 확인 요청이 만료되었습니다. 원래 화면에서 다시 시도해주세요.")
        if parameters.get("openid.mode") == "cancel":
            raise SteamOpenIDError("Steam 로그인이 취소되었습니다.")
        if parameters.get("openid.mode") != "id_res":
            raise SteamOpenIDError("Steam에서 올바른 인증 응답을 받지 못했습니다.")
        if parameters.get("openid.op_endpoint", "").rstrip("/") != STEAM_OPENID_ENDPOINT.rstrip("/"):
            raise SteamOpenIDError("Steam 인증 서버 주소가 올바르지 않습니다.")
        if parameters.get("openid.return_to") != pending["return_to"]:
            raise SteamOpenIDError("Steam 인증의 돌아올 주소가 일치하지 않습니다.")
        claimed_id = parameters.get("openid.claimed_id", "")
        match = STEAM_CLAIMED_ID.fullmatch(claimed_id)
        if not match or parameters.get("openid.identity") != claimed_id:
            raise SteamOpenIDError("SteamID 형식을 확인하지 못했습니다.")

        verification = {key: value for key, value in parameters.items() if key.startswith("openid.")}
        verification["openid.mode"] = "check_authentication"
        request = Request(
            STEAM_OPENID_ENDPOINT,
            data=urlencode(verification).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "TechTim-Valheim-Panel/1.0"},
        )
        try:
            context = ssl.create_default_context(cafile=certifi.where())
            with opener(request, timeout=20, context=context) as response:
                raw = response.read(16 * 1024 + 1)
            if len(raw) > 16 * 1024:
                raise SteamOpenIDError("Steam 인증 응답이 허용 범위를 초과했습니다.")
            values = dict(line.split(":", 1) for line in raw.decode("utf-8").splitlines() if ":" in line)
        except SteamOpenIDError:
            raise
        except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError, ValueError) as error:
            raise SteamOpenIDError("Steam 인증 결과를 확인하지 못했습니다. 잠시 후 다시 시도해주세요.") from error
        if values.get("is_valid") != "true":
            raise SteamOpenIDError("Steam에서 인증되지 않은 응답을 받았습니다.")
        return match.group("steam_id"), pending["origin"]
