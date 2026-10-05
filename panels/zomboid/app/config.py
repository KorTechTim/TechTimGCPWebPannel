from dataclasses import dataclass
from pathlib import Path
from typing import Literal
import json
import os
import re

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

PANEL_VERSION = "1.0.0"
STEAM_APP_ID = "380870"
WORKSHOP_APP_ID = "108600"
DEFAULT_RUNTIME_IMAGE = "ghcr.io/kortechtim/zomboid-runtime:steamcmd-nonroot-v1"
LEGACY_RUNTIME_IMAGE = "ghcr.io/kortechtim/zomboid-runtime:latest"
SERVER_PROFILE = "servertest"
BRANCHES = ("public", "legacy41")


def resolve_runtime_image(value: str | None) -> str:
    normalized = str(value or "").strip()
    return DEFAULT_RUNTIME_IMAGE if normalized in {"", LEGACY_RUNTIME_IMAGE} else normalized


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    host_data_dir: Path
    runtime_image: str = DEFAULT_RUNTIME_IMAGE
    panel_image: str = "ghcr.io/kortechtim/zomboid-panel:latest"
    server_container: str = "zomboid-server"
    panel_container: str = "zomboid-panel"
    proxy_container: str = "zomboid-panel-proxy"
    stop_timeout: int = 180
    install_timeout: int = 3600
    max_upload_bytes: int = 2 * 1024**3
    scheduler_enabled: bool = True
    pull_runtime: bool = True
    storage_cleanup_threshold: int = 80
    storage_cleanup_target: int = 75
    storage_cleanup_interval: int = 300
    storage_min_backups: int = 3

    @classmethod
    def from_env(cls):
        threshold = max(50, min(95, int(os.getenv("STORAGE_CLEANUP_THRESHOLD_PERCENT", "80"))))
        target = max(40, min(threshold - 1, int(os.getenv("STORAGE_CLEANUP_TARGET_PERCENT", "75"))))
        return cls(
            data_dir=Path(os.getenv("DATA_DIR", "/data")),
            host_data_dir=Path(os.getenv("HOST_DATA_DIR", "/opt/techtim/zomboid/data")),
            runtime_image=resolve_runtime_image(os.getenv("ZOMBOID_RUNTIME_IMAGE")),
            panel_image=os.getenv("PANEL_IMAGE", cls.panel_image),
            server_container=os.getenv("ZOMBOID_SERVER_CONTAINER", cls.server_container),
            panel_container=os.getenv("PANEL_CONTAINER_NAME", cls.panel_container),
            proxy_container=os.getenv("PANEL_PROXY_CONTAINER", cls.proxy_container),
            stop_timeout=max(60, int(os.getenv("SERVER_STOP_TIMEOUT", "180"))),
            install_timeout=max(600, int(os.getenv("INSTALL_TIMEOUT", "3600"))),
            max_upload_bytes=max(1024**2, int(os.getenv("MAX_UPLOAD_BYTES", str(2 * 1024**3)))),
            scheduler_enabled=os.getenv("SCHEDULER_ENABLED", "1") == "1",
            pull_runtime=os.getenv("PULL_RUNTIME_IMAGE", "1") == "1",
            storage_cleanup_threshold=threshold,
            storage_cleanup_target=target,
            storage_cleanup_interval=max(60, int(os.getenv("STORAGE_CLEANUP_INTERVAL_SECONDS", "300"))),
            storage_min_backups=max(1, int(os.getenv("STORAGE_MIN_BACKUPS", "3"))),
        )


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    server_name: str = Field(default="TechTim Project Zomboid", min_length=1, max_length=64)
    description: str = Field(default="TechTim 생존 서버", max_length=256)
    password: str = Field(default="", max_length=64)
    admin_password: str = Field(default="", max_length=64)
    max_players: int = Field(default=20, ge=1, le=100)
    default_port: int = Field(default=16261, ge=1024, le=65534)
    udp_port: int = Field(default=16262, ge=1024, le=65534)
    rcon_port: int = Field(default=27015, ge=1024, le=65535)
    rcon_password: str = Field(default="", max_length=128)
    public: bool = False
    open: bool = True
    pvp: bool = True
    pause_empty: bool = True
    steam_vac: bool = True
    auto_whitelist: bool = False
    display_username: bool = True
    announce_death: bool = True
    branch: Literal["public", "legacy41"] = "public"
    memory_gb: int = Field(default=8, ge=2, le=64)
    welcome_message: str = Field(default="TechTim Project Zomboid 서버에 오신 것을 환영합니다.", max_length=512)
    workshop_items: list[str] = Field(default_factory=list, max_length=200)
    mod_ids: list[str] = Field(default_factory=list, max_length=500)
    map_order: list[str] = Field(default_factory=lambda: ["Muldraugh, KY"], max_length=100)
    backup_before_start: bool = False
    backup_before_update: bool = True
    backup_retention_count: int = Field(default=20, ge=3, le=100)
    backup_retention_days: int = Field(default=30, ge=1, le=365)

    @field_validator("server_name", "description", "welcome_message")
    @classmethod
    def text_fields(cls, value, info):
        if any(ord(c) < 32 and c != "\t" for c in value):
            raise ValueError(f"{info.field_name}에 제어 문자를 사용할 수 없습니다.")
        return value.strip()

    @field_validator("password", "admin_password", "rcon_password")
    @classmethod
    def passwords(cls, value):
        if any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("비밀번호는 공백 없는 영문, 숫자, 기호만 사용할 수 있습니다.")
        return value

    @field_validator("workshop_items")
    @classmethod
    def workshop_ids(cls, values):
        values = list(dict.fromkeys(str(v).strip() for v in values if str(v).strip()))
        if any(not re.fullmatch(r"[0-9]{5,20}", value) for value in values):
            raise ValueError("Workshop ID는 숫자만 입력해주세요.")
        return values

    @field_validator("mod_ids", "map_order")
    @classmethod
    def list_values(cls, values):
        values = list(dict.fromkeys(str(v).strip() for v in values if str(v).strip()))
        if any(";" in value or "\n" in value or "\r" in value for value in values):
            raise ValueError("항목 안에는 세미콜론이나 줄바꿈을 사용할 수 없습니다.")
        return values

    @model_validator(mode="after")
    def validate_ports_and_passwords(self):
        if len({self.default_port, self.udp_port, self.rcon_port}) != 3:
            raise ValueError("게임, 추가 UDP, RCON 포트는 서로 달라야 합니다.")
        if self.password and len(self.password) < 4:
            raise ValueError("게임 비밀번호는 4자 이상 입력해주세요.")
        if self.admin_password and len(self.admin_password) < 4:
            raise ValueError("관리자 비밀번호는 4자 이상 입력해주세요.")
        if self.rcon_password and len(self.rcon_password) < 8:
            raise ValueError("RCON 비밀번호는 8자 이상 입력해주세요.")
        return self


SANDBOX_SCHEMA = json.loads(
    (Path(__file__).with_name("sandbox_schema.json")).read_text(encoding="utf-8")
)
SANDBOX_FIELDS = tuple(SANDBOX_SCHEMA["fields"])


def _sandbox_model_fields():
    python_types = {"boolean": bool, "integer": int, "number": float, "string": str}
    result = {}
    for item in SANDBOX_FIELDS:
        constraints = {}
        if item["type"] in {"integer", "number"}:
            if "min" in item:
                constraints["ge"] = item["min"]
            if "max" in item:
                constraints["le"] = item["max"]
        elif item["type"] == "string":
            constraints["max_length"] = 4096
        result[item["name"]] = (
            python_types[item["type"]],
            Field(default=item["default"], **constraints),
        )
    return result


SandboxConfig = create_model(
    "SandboxConfig",
    __config__=ConfigDict(extra="forbid"),
    **_sandbox_model_fields(),
)


class RestartSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    times: list[str] = Field(default_factory=lambda: ["05:00"], min_length=1, max_length=3)

    @field_validator("times")
    @classmethod
    def valid_times(cls, values):
        if any(not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value) for value in values):
            raise ValueError("재시작 시각은 HH:MM 형식으로 입력해주세요.")
        return sorted(set(values))


class DiscordConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    webhook_url: str = Field(default="", max_length=500)
    username: str = Field(default="TechTim Project Zomboid Server", min_length=1, max_length=80)
    notify_server_start: bool = True
    notify_server_stop: bool = True
    notify_server_restart: bool = True
    notify_backup: bool = True
    notify_errors: bool = True

    @field_validator("username")
    @classmethod
    def clean_username(cls, value):
        value = value.strip()
        if not value or any(ord(char) < 32 for char in value):
            raise ValueError("Discord 표시 이름을 확인해주세요.")
        return value


def ini_values(config: ServerConfig) -> dict[str, str]:
    return {
        "Public": str(config.public).lower(), "PublicName": config.server_name,
        "PublicDescription": config.description, "Password": config.password,
        "MaxPlayers": str(config.max_players), "DefaultPort": str(config.default_port),
        "UDPPort": str(config.udp_port), "RCONPort": str(config.rcon_port),
        "RCONPassword": config.rcon_password, "Open": str(config.open).lower(),
        "AutoCreateUserInWhiteList": str(config.auto_whitelist).lower(),
        "PVP": str(config.pvp).lower(), "PauseEmpty": str(config.pause_empty).lower(),
        "SteamVAC": str(config.steam_vac).lower(),
        "DisplayUserName": str(config.display_username).lower(),
        "AnnounceDeath": str(config.announce_death).lower(),
        "ServerWelcomeMessage": config.welcome_message,
        "WorkshopItems": ";".join(config.workshop_items),
        "Mods": ";".join(config.mod_ids),
        "Map": ";".join(config.map_order or ["Muldraugh, KY"]),
    }


def sandbox_values(config: SandboxConfig) -> dict[str, str]:
    def lua_value(value):
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, str):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    return {
        item["key"]: lua_value(getattr(config, item["name"]))
        for item in SANDBOX_FIELDS
    }


def sandbox_schema() -> dict:
    return SANDBOX_SCHEMA


def migrate_sandbox_payload(payload: dict) -> dict:
    payload = dict(payload or {})
    if "zombie_voronoi_noise" in payload:
        return payload
    legacy_loot_factors = {1: 0.05, 2: 0.2, 3: 0.6, 4: 1.0, 5: 2.0, 6: 3.0}
    for name in ("food_loot", "weapon_loot", "other_loot"):
        value = payload.get(name)
        if isinstance(value, int) and value in legacy_loot_factors:
            payload[name] = legacy_loot_factors[value]
    return payload
