from dataclasses import dataclass
from pathlib import Path
from typing import Literal
import os
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PANEL_VERSION = "1.0.0"
STEAM_APP_ID = "896660"
DEFAULT_RUNTIME_IMAGE = "ghcr.io/kortechtim/valheim-runtime:steamcmd-nonroot-v1"
LEGACY_RUNTIME_IMAGE = "ghcr.io/kortechtim/valheim-runtime:latest"
PRESETS = ("", "normal", "casual", "easy", "hard", "hardcore", "immersive", "hammer")


def resolve_runtime_image(value: str | None) -> str:
    normalized = str(value or "").strip()
    if normalized in {"", LEGACY_RUNTIME_IMAGE}:
        return DEFAULT_RUNTIME_IMAGE
    return normalized


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    host_data_dir: Path
    runtime_image: str = DEFAULT_RUNTIME_IMAGE
    panel_image: str = "ghcr.io/kortechtim/valheim-panel:latest"
    server_container: str = "valheim-server"
    panel_container: str = "valheim-panel"
    proxy_container: str = "valheim-panel-proxy"
    stop_timeout: int = 120
    install_timeout: int = 1800
    max_upload_bytes: int = 2 * 1024**3
    scheduler_enabled: bool = True
    pull_runtime: bool = True

    @classmethod
    def from_env(cls):
        return cls(
            data_dir=Path(os.getenv("DATA_DIR", "/data")),
            host_data_dir=Path(os.getenv("HOST_DATA_DIR", "/opt/techtim/valheim/data")),
            runtime_image=resolve_runtime_image(os.getenv("VALHEIM_RUNTIME_IMAGE")),
            panel_image=os.getenv("PANEL_IMAGE", cls.panel_image),
            server_container=os.getenv("VALHEIM_SERVER_CONTAINER", cls.server_container),
            panel_container=os.getenv("PANEL_CONTAINER_NAME", cls.panel_container),
            proxy_container=os.getenv("PANEL_PROXY_CONTAINER", cls.proxy_container),
            stop_timeout=max(30, int(os.getenv("SERVER_STOP_TIMEOUT", "120"))),
            scheduler_enabled=os.getenv("SCHEDULER_ENABLED", "1") == "1",
            pull_runtime=os.getenv("PULL_RUNTIME_IMAGE", "1") == "1",
        )


def world_name(value: str) -> str:
    if (not value or len(value) > 64 or value != value.strip()
            or value in {".", ".."} or any(c in value for c in '/\\:<>"|?*')
            or any(ord(c) < 32 for c in value) or value.endswith(".")):
        raise ValueError("월드 이름은 경로 문자 없이 1~64자로 입력해주세요.")
    return value


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    server_name: str = Field(default="TechTim Valheim Server", min_length=1, max_length=64)
    world: str = "Dedicated"
    password: str = Field(default="", max_length=128)
    port: int = Field(default=2456, ge=1024, le=65534)
    public: bool = True
    crossplay: bool = True
    preset: str = ""
    combat: Literal["", "veryeasy", "easy", "hard", "veryhard"] = ""
    death_penalty: Literal["", "casual", "veryeasy", "easy", "hard", "hardcore"] = ""
    resources: Literal["", "muchless", "less", "more", "muchmore", "most"] = ""
    raids: Literal["", "none", "muchless", "less", "more", "muchmore"] = ""
    portals: Literal["", "casual", "hard", "veryhard"] = ""
    no_build_cost: bool = False
    player_events: bool = False
    passive_mobs: bool = False
    no_map: bool = False
    save_interval: int = Field(default=1800, ge=60, le=86400)
    backups: int = Field(default=4, ge=1, le=50)
    backup_short: int = Field(default=7200, ge=60, le=604800)
    backup_long: int = Field(default=43200, ge=60, le=2592000)

    _world_name = field_validator("world")(world_name)

    @field_validator("server_name", "password")
    @classmethod
    def no_control_characters(cls, value):
        if any(ord(c) < 32 for c in value):
            raise ValueError("제어 문자는 사용할 수 없습니다.")
        return value

    @field_validator("preset")
    @classmethod
    def known_preset(cls, value):
        if value not in PRESETS:
            raise ValueError("지원하지 않는 월드 프리셋입니다.")
        return value

    @model_validator(mode="after")
    def validate_password(self):
        if not self.server_name.strip():
            raise ValueError("서버 이름을 입력해주세요.")
        if self.password and (len(self.password) < 5 or self.password.casefold() in self.server_name.casefold()):
            raise ValueError("게임 비밀번호는 5자 이상이며 서버 이름에 포함되지 않아야 합니다.")
        return self


def server_arguments(config: ServerConfig) -> list[str]:
    if not config.password:
        raise ValueError("서버 설정에서 게임 접속 비밀번호를 먼저 저장해주세요.")
    args = [
        "serve", "-name", config.server_name, "-port", str(config.port),
        "-world", config.world, "-password", config.password,
        "-public", "1" if config.public else "0",
        "-saveinterval", str(config.save_interval), "-backups", str(config.backups),
        "-backupshort", str(config.backup_short), "-backuplong", str(config.backup_long),
    ]
    if config.crossplay:
        args.append("-crossplay")
    if config.preset:
        args.extend(["-preset", config.preset])
    for name, value in (("combat", config.combat), ("deathpenalty", config.death_penalty),
                        ("resources", config.resources), ("raids", config.raids),
                        ("portals", config.portals)):
        if value:
            args.extend(["-modifier", name, value])
    for enabled, name in ((config.no_build_cost, "nobuildcost"),
                          (config.player_events, "playerevents"),
                          (config.passive_mobs, "passivemobs"),
                          (config.no_map, "nomap")):
        if enabled:
            args.extend(["-setkey", name])
    return args


class RestartSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    times: list[str] = Field(default_factory=lambda: ["04:00"], min_length=1, max_length=3)

    @field_validator("times")
    @classmethod
    def valid_times(cls, values):
        if any(not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", v) for v in values):
            raise ValueError("재시작 시각은 HH:MM 형식으로 입력해주세요.")
        return sorted(set(values))


class Permissions(BaseModel):
    kind: Literal["admin", "banned", "permitted"]
    ids: list[str] = Field(default_factory=list, max_length=200)

    @field_validator("ids")
    @classmethod
    def platform_ids(cls, values):
        values = [v.strip() for v in values if v.strip()]
        if any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_.:-]{1,120}", v) for v in values):
            raise ValueError("Steam_76561198000000000과 같은 Platform_UserID를 한 줄에 하나씩 입력해주세요.")
        return list(dict.fromkeys(values))
