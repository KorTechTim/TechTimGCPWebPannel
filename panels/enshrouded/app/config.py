from dataclasses import dataclass
from pathlib import Path
from typing import Literal
import os

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


PANEL_VERSION = "1.0.9"
STEAM_APP_ID = "2278520"
DEFAULT_RUNTIME_IMAGE = "ghcr.io/kortechtim/enshrouded-runtime:wine-v1"
UPSTREAM_RUNTIME_IMAGE = (
    "mornedhels/enshrouded-server:1.8.1-wine@"
    "sha256:002a8ac3387eddc5151b18ab5e7c02f9382f8e941dcfc75e56fa5134bd18f283"
)
LANGUAGES = ("ko", "en", "zh", "ja")

DEFAULT_GAME_SETTINGS = {
    "playerHealthFactor": 1.0,
    "playerManaFactor": 1.0,
    "playerStaminaFactor": 1.0,
    "playerBodyHeatFactor": 1.0,
    "playerDivingTimeFactor": 1.0,
    "enableDurability": True,
    "enableStarvingDebuff": False,
    "foodBuffDurationFactor": 1.0,
    "fromHungerToStarving": 600_000_000_000,
    "shroudTimeFactor": 1.0,
    "tombstoneMode": "AddBackpackMaterials",
    "enableGliderTurbulences": True,
    "weatherFrequency": "Normal",
    "fishingDifficulty": "Normal",
    "miningDamageFactor": 1.0,
    "plantGrowthSpeedFactor": 1.0,
    "resourceDropStackAmountFactor": 1.0,
    "factoryProductionSpeedFactor": 1.0,
    "perkUpgradeRecyclingFactor": 0.5,
    "perkCostFactor": 1.0,
    "experienceCombatFactor": 1.0,
    "experienceMiningFactor": 1.0,
    "experienceExplorationQuestsFactor": 1.0,
    "randomSpawnerAmount": "Automatic",
    "aggroPoolAmount": "Normal",
    "enemyDamageFactor": 1.0,
    "enemyHealthFactor": 1.0,
    "enemyStaminaFactor": 1.0,
    "enemyPerceptionRangeFactor": 1.0,
    "bossDamageFactor": 1.0,
    "bossHealthFactor": 1.0,
    "threatBonus": 1.0,
    "pacifyAllEnemies": False,
    "tamingStartleRepercussion": "LoseSomeProgress",
    "dayTimeDuration": 1_800_000_000_000,
    "nightTimeDuration": 720_000_000_000,
    "curseModifier": "Normal",
}

GAME_SETTING_RANGES = {
    "playerHealthFactor": (0.25, 4), "playerManaFactor": (0.25, 4),
    "playerStaminaFactor": (0.25, 4), "playerBodyHeatFactor": (0.5, 2),
    "playerDivingTimeFactor": (0.5, 2), "foodBuffDurationFactor": (0.5, 2),
    "fromHungerToStarving": (300_000_000_000, 1_200_000_000_000),
    "shroudTimeFactor": (0.5, 2), "miningDamageFactor": (0.5, 2),
    "plantGrowthSpeedFactor": (0.25, 2), "resourceDropStackAmountFactor": (0.25, 2),
    "factoryProductionSpeedFactor": (0.25, 2), "perkUpgradeRecyclingFactor": (0, 1),
    "perkCostFactor": (0.25, 2), "experienceCombatFactor": (0.25, 2),
    "experienceMiningFactor": (0, 2), "experienceExplorationQuestsFactor": (0.25, 2),
    "enemyDamageFactor": (0.25, 5), "enemyHealthFactor": (0.25, 4),
    "enemyStaminaFactor": (0.5, 2), "enemyPerceptionRangeFactor": (0.5, 2),
    "bossDamageFactor": (0.2, 5), "bossHealthFactor": (0.2, 5),
    "threatBonus": (0.25, 4), "dayTimeDuration": (120_000_000_000, 3_600_000_000_000),
    "nightTimeDuration": (120_000_000_000, 3_600_000_000_000),
}

GAME_SETTING_OPTIONS = {
    "weatherFrequency": {"Disabled", "Rare", "Normal", "Often"},
    "fishingDifficulty": {"VeryEasy", "Easy", "Normal", "Hard", "VeryHard"},
    "randomSpawnerAmount": {"Few", "Normal", "More", "Many", "Automatic"},
    "aggroPoolAmount": {"Few", "Normal", "More", "Many"},
    "tombstoneMode": {"AddBackpackMaterials", "Everything", "NoTombstone"},
    "tamingStartleRepercussion": {"KeepProgress", "LoseSomeProgress", "LoseAllProgress"},
    "curseModifier": {"Easy", "Normal", "Hard"},
}


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    host_data_dir: Path
    runtime_image: str = DEFAULT_RUNTIME_IMAGE
    panel_image: str = "ghcr.io/kortechtim/enshrouded-panel:latest"
    server_container: str = "enshrouded-server"
    panel_container: str = "enshrouded-panel"
    proxy_container: str = "enshrouded-panel-proxy"
    stop_timeout: int = 150
    install_timeout: int = 3600
    max_upload_bytes: int = 4 * 1024**3
    scheduler_enabled: bool = True
    pull_runtime: bool = True
    storage_cleanup_threshold: int = 85
    storage_cleanup_target: int = 78
    storage_min_backups: int = 3

    @classmethod
    def from_env(cls):
        threshold = max(60, min(95, int(os.getenv("STORAGE_CLEANUP_THRESHOLD_PERCENT", "85"))))
        target = max(50, min(threshold - 1, int(os.getenv("STORAGE_CLEANUP_TARGET_PERCENT", "78"))))
        return cls(
            data_dir=Path(os.getenv("DATA_DIR", "/data")),
            host_data_dir=Path(os.getenv("HOST_DATA_DIR", "/opt/techtim/enshrouded/data")),
            runtime_image=os.getenv("ENSHROUDED_RUNTIME_IMAGE", cls.runtime_image),
            panel_image=os.getenv("PANEL_IMAGE", cls.panel_image),
            server_container=os.getenv("ENSHROUDED_SERVER_CONTAINER", cls.server_container),
            panel_container=os.getenv("PANEL_CONTAINER_NAME", cls.panel_container),
            proxy_container=os.getenv("PANEL_PROXY_CONTAINER", cls.proxy_container),
            stop_timeout=max(90, int(os.getenv("SERVER_STOP_TIMEOUT", "150"))),
            install_timeout=max(600, int(os.getenv("INSTALL_TIMEOUT", "3600"))),
            max_upload_bytes=max(1024**2, int(os.getenv("MAX_UPLOAD_BYTES", str(4 * 1024**3)))),
            scheduler_enabled=os.getenv("SCHEDULER_ENABLED", "1") == "1",
            pull_runtime=os.getenv("PULL_RUNTIME_IMAGE", "1") == "1",
            storage_cleanup_threshold=threshold,
            storage_cleanup_target=target,
            storage_min_backups=max(1, int(os.getenv("STORAGE_MIN_BACKUPS", "3"))),
        )


class ServerRole(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=64)
    can_kick_ban: bool = False
    can_access_inventories: bool = False
    can_edit_world: bool = True
    can_edit_base: bool = False
    can_extend_base: bool = False
    reserved_slots: int = Field(default=0, ge=0, le=16)

    @field_validator("name", "password")
    @classmethod
    def clean_text(cls, value):
        value = value.strip()
        if any(ord(char) < 32 for char in value):
            raise ValueError("제어 문자는 사용할 수 없습니다.")
        return value

    def game_dict(self):
        return {
            "name": self.name,
            "password": self.password,
            "canKickBan": self.can_kick_ban,
            "canAccessInventories": self.can_access_inventories,
            "canEditWorld": self.can_edit_world,
            "canEditBase": self.can_edit_base,
            "canExtendBase": self.can_extend_base,
            "reservedSlots": self.reserved_slots,
        }


def default_roles():
    return [
        ServerRole(
            name="Admin", password="change-admin-password", can_kick_ban=True,
            can_access_inventories=True, can_edit_world=True, can_edit_base=True,
            can_extend_base=True, reserved_slots=1,
        ),
        ServerRole(
            name="Friend", password="change-friend-password", can_access_inventories=True,
            can_edit_world=True, can_edit_base=True, can_extend_base=True, reserved_slots=3,
        ),
        ServerRole(
            name="Guest", password="change-guest-password", can_edit_world=True,
        ),
    ]


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    server_name: str = Field(default="TechTim Enshrouded Server", min_length=1, max_length=64)
    slot_count: int = Field(default=16, ge=1, le=16)
    query_port: int = Field(default=15637, ge=1024, le=65535)
    voice_chat_mode: Literal["Proximity", "Global"] = "Proximity"
    enable_voice_chat: bool = False
    enable_text_chat: bool = True
    game_settings_preset: Literal["Default", "Relaxed", "Hard", "Survival", "Custom"] = "Default"
    game_settings: dict[str, bool | int | float | str] = Field(default_factory=lambda: dict(DEFAULT_GAME_SETTINGS))
    tags: list[str] = Field(default_factory=lambda: ["Korean", "Exploration"], max_length=12)
    roles: list[ServerRole] = Field(default_factory=default_roles, min_length=1, max_length=8)
    backup_retention_count: int = Field(default=10, ge=1, le=100)
    backup_retention_days: int = Field(default=15, ge=1, le=365)

    @field_validator("server_name")
    @classmethod
    def clean_name(cls, value):
        value = value.strip()
        if any(ord(char) < 32 for char in value):
            raise ValueError("서버 이름에 제어 문자를 사용할 수 없습니다.")
        return value

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, values):
        cleaned = []
        for value in values:
            item = str(value).strip()
            if item and item not in cleaned:
                cleaned.append(item[:32])
        return cleaned

    @field_validator("game_settings")
    @classmethod
    def validate_game_settings(cls, values):
        if not isinstance(values, dict):
            raise ValueError("상세 게임 설정 형식이 올바르지 않습니다.")
        normalized = {**DEFAULT_GAME_SETTINGS, **values}
        for key, default in DEFAULT_GAME_SETTINGS.items():
            value = normalized[key]
            if isinstance(default, bool):
                if not isinstance(value, bool):
                    raise ValueError(f"{key} 값은 true 또는 false여야 합니다.")
            elif key in GAME_SETTING_OPTIONS:
                if value not in GAME_SETTING_OPTIONS[key]:
                    raise ValueError(f"{key} 값이 지원 범위를 벗어났습니다.")
            elif key in GAME_SETTING_RANGES:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"{key} 값은 숫자여야 합니다.")
                minimum, maximum = GAME_SETTING_RANGES[key]
                if not minimum <= value <= maximum:
                    raise ValueError(f"{key} 값은 {minimum}~{maximum} 범위여야 합니다.")
        return normalized

    @model_validator(mode="after")
    def validate_roles(self):
        names = [role.name.casefold() for role in self.roles]
        passwords = [role.password for role in self.roles]
        if len(names) != len(set(names)):
            raise ValueError("역할 이름은 서로 달라야 합니다.")
        if len(passwords) != len(set(passwords)):
            raise ValueError("역할별 비밀번호는 서로 달라야 합니다.")
        if sum(role.reserved_slots for role in self.roles) > self.slot_count:
            raise ValueError("예약 슬롯 합계가 최대 접속 인원을 넘을 수 없습니다.")
        return self

    def game_dict(self):
        return {
            "name": self.server_name,
            "saveDirectory": "./savegame",
            "logDirectory": "./logs",
            "ip": "0.0.0.0",
            "queryPort": self.query_port,
            "slotCount": self.slot_count,
            "voiceChatMode": self.voice_chat_mode,
            "enableVoiceChat": self.enable_voice_chat,
            "enableTextChat": self.enable_text_chat,
            "gameSettingsPreset": self.game_settings_preset,
            "gameSettings": self.game_settings,
            "tags": self.tags,
            "userGroups": [role.game_dict() for role in self.roles],
        }


class RestartSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    time: str = "04:00"
    weekdays: list[int] = Field(default_factory=lambda: list(range(7)), max_length=7)
    skip_when_players_online: bool = True

    @field_validator("time")
    @classmethod
    def valid_time(cls, value):
        parts = value.split(":")
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            raise ValueError("시간은 HH:MM 형식이어야 합니다.")
        hour, minute = map(int, parts)
        if hour > 23 or minute > 59:
            raise ValueError("시간을 확인해주세요.")
        return f"{hour:02d}:{minute:02d}"


class BackupSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    times: list[str] = Field(default_factory=lambda: ["03:30"], max_length=3)
    retention_count: int = Field(default=10, ge=1, le=100)
    retention_days: int = Field(default=15, ge=1, le=365)

    @field_validator("times")
    @classmethod
    def valid_times(cls, values):
        normalized = []
        for value in values:
            parts = str(value).split(":")
            if len(parts) != 2 or not all(part.isdigit() for part in parts):
                raise ValueError("백업 시간은 HH:MM 형식이어야 합니다.")
            hour, minute = map(int, parts)
            if hour > 23 or minute > 59:
                raise ValueError("백업 시간을 확인해주세요.")
            item = f"{hour:02d}:{minute:02d}"
            if item not in normalized:
                normalized.append(item)
        return sorted(normalized)


class DiscordConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    webhook_url: str = Field(default="", max_length=500)
    username: str = Field(default="TechTim Enshrouded Server", min_length=1, max_length=80)
    notify_server_start: bool = True
    notify_server_stop: bool = True
    notify_server_restart: bool = True
    notify_backup: bool = True
    notify_migration: bool = True
    notify_errors: bool = True
