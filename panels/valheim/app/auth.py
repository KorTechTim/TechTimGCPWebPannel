from pathlib import Path
import hashlib
import secrets
import threading
import time

from fastapi import HTTPException, Request

from .storage import read_json, write_json

SESSION_COOKIE = "techtim_valheim_session"
SESSION_SECONDS = 7 * 24 * 3600


class Auth:
    def __init__(self, data_dir: Path):
        self.auth_file = data_dir / "auth.json"
        self.sessions_file = data_dir / "sessions.json"
        self.lock = threading.RLock()
        self.attempts: dict[str, list[float]] = {}
        with self.lock:
            if not self.auth_file.exists():
                self.set_password("admin", must_change=True)

    @staticmethod
    def digest(password, salt):
        return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 210_000).hex()

    def set_password(self, password: str, *, must_change: bool = False):
        salt = secrets.token_hex(16)
        write_json(self.auth_file, {"username": "admin", "salt": salt,
                                   "password_hash": self.digest(password, salt),
                                   "must_change_password": must_change})

    @staticmethod
    def key(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def login(self, username, password, address):
        with self.lock:
            now = time.time()
            self.attempts = {key: [t for t in values if t > now - 300]
                             for key, values in self.attempts.items() if values and values[-1] > now - 300}
            attempts = self.attempts.setdefault(address, [])
            if len(attempts) >= 10:
                raise HTTPException(429, "로그인 시도가 많습니다. 5분 뒤 다시 시도해주세요.")
            auth = read_json(self.auth_file, {})
            if username != auth.get("username") or not secrets.compare_digest(
                self.digest(password, auth["salt"]), auth["password_hash"]
            ):
                attempts.append(now)
                raise HTTPException(401, "아이디 또는 비밀번호를 확인해주세요.")
            self.attempts.pop(address, None)
            token = self.create_session()
            return token, auth["must_change_password"]

    def create_session(self):
        token = secrets.token_urlsafe(32)
        now = time.time()
        sessions = {k: v for k, v in read_json(self.sessions_file, {}).items() if v["expires_at"] > now}
        sessions[self.key(token)] = {"expires_at": now + SESSION_SECONDS}
        write_json(self.sessions_file, sessions)
        return token

    def require(self, request: Request, *, allow_initial=False):
        token = request.cookies.get(SESSION_COOKIE, "")
        with self.lock:
            session = read_json(self.sessions_file, {}).get(self.key(token))
            if not session or session["expires_at"] <= time.time():
                raise HTTPException(401, "로그인이 필요합니다.")
            initial = read_json(self.auth_file, {})["must_change_password"]
            if initial and not allow_initial:
                raise HTTPException(403, "최초 비밀번호를 변경해주세요.")
        return {"username": "admin", "must_change_password": initial}

    def change_password(self, request, password):
        self.require(request, allow_initial=True)
        if len(password) < 8 or len(password) > 128 or password == "admin":
            raise HTTPException(400, "새 패널 비밀번호는 8~128자로 입력해주세요.")
        with self.lock:
            self.set_password(password)
            write_json(self.sessions_file, {})
            return self.create_session()

    def logout(self, request):
        with self.lock:
            sessions = read_json(self.sessions_file, {})
            sessions.pop(self.key(request.cookies.get(SESSION_COOKIE, "")), None)
            write_json(self.sessions_file, sessions)
