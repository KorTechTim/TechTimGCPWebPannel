#!/usr/bin/env python3
"""Generate the bundled Build 42 sandbox UI schema from a server-created Lua file."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


CATEGORIES = [
    ("population", "좀비 개체수", "전체 개체수, 분포, 자연 재생성과 이동을 설정합니다."),
    ("time", "시간 · 기후", "하루 길이, 시작 시점, 낮과 밤, 날씨 주기를 설정합니다."),
    ("infrastructure", "전기 · 수도 · 발전기", "전기와 수도 중단, 경보기와 발전기 동작을 설정합니다."),
    ("loot", "루팅 · 아이템", "Build 42의 세분화된 전리품 배율과 재생성, 정리 정책을 설정합니다."),
    ("world", "월드 · 자연", "침식, 농사, 식량 부패, 자연 자원과 월드 이벤트를 설정합니다."),
    ("survival", "생존 · 캐릭터", "부상, 체력, 제작, 독성, 읽기와 캐릭터 규칙을 설정합니다."),
    ("vehicles", "차량 · 연료", "차량 생성, 상태, 연료, 충돌과 경보기를 설정합니다."),
    ("animals", "동물 · 사육", "Build 42 동물의 성장, 번식, 추적과 해충을 설정합니다."),
    ("combat", "전투 · 총기", "근접 다중 타격, 총기 명중, 소음과 전투 보정을 설정합니다."),
    ("map", "지도 · 건물", "미니맵, 월드맵, 지하실과 랜덤 월드 스토리를 설정합니다."),
    ("zombie_lore", "좀비 특성", "속도, 감각, 감염, 지능과 공격 행동을 세밀하게 설정합니다."),
    ("zombie_advanced", "고급 좀비 개체수", "최고 개체수, 재생성, 이동과 무리 형성을 설정합니다."),
    ("experience", "기술별 경험치", "전역 또는 기술별 경험치 획득 배율을 설정합니다."),
]


LABELS = {
    "Zombies": "좀비 개체수", "Distribution": "좀비 분포", "ZombieVoronoiNoise": "분포 무작위화",
    "ZombieRespawn": "좀비 재생성 빈도", "ZombieMigrate": "빈 지역으로 이동",
    "DayLength": "하루 길이", "StartYear": "시작 연도", "StartMonth": "시작 월", "StartDay": "시작 일",
    "StartTime": "시작 시간", "DayNightCycle": "낮·밤 주기", "ClimateCycle": "날씨 주기", "FogCycle": "안개 주기",
    "WaterShut": "수도 중단 시점", "ElecShut": "전기 중단 시점", "AlarmDecay": "경보기 배터리 수명",
    "WaterShutModifier": "수도 중단 일수", "ElecShutModifier": "전기 중단 일수", "AlarmDecayModifier": "경보기 배터리 일수",
    "FoodLootNew": "신선 식품", "LiteratureLootNew": "일반 서적", "SkillBookLoot": "기술 서적",
    "RecipeResourceLoot": "레시피 자료", "MedicalLootNew": "의료품", "SurvivalGearsLootNew": "생존 장비",
    "CannedFoodLootNew": "보존 식품", "WeaponLootNew": "근접 무기", "RangedWeaponLootNew": "원거리 무기",
    "AmmoLootNew": "탄약", "MechanicsLootNew": "차량 정비품", "OtherLootNew": "기타 전리품",
    "ClothingLootNew": "의류", "ContainerLootNew": "가방·용기", "KeyLootNew": "열쇠·자물쇠",
    "MediaLootNew": "비디오·음반", "MementoLootNew": "수집품", "CookwareLootNew": "조리 도구",
    "MaterialLootNew": "제작 재료", "FarmingLootNew": "농업 용품", "ToolLootNew": "일반 공구",
    "RollsMultiplier": "루팅 횟수 배율", "LootItemRemovalList": "루팅 제외 아이템", "RemoveStoryLoot": "스토리 전리품 제거",
    "RemoveZombieLoot": "좀비 전리품 제거", "ZombiePopLootEffect": "좀비 수에 따른 루팅 보정",
    "InsaneLootFactor": "극악 희귀 배율", "ExtremeLootFactor": "매우 희귀 배율", "RareLootFactor": "희귀 배율",
    "NormalLootFactor": "보통 배율", "CommonLootFactor": "흔함 배율", "AbundantLootFactor": "풍부함 배율",
    "Temperature": "기온", "Rain": "강우량", "ErosionSpeed": "침식 속도", "ErosionDays": "침식 완료 일수",
    "Farming": "작물 성장 속도", "CompostTime": "퇴비 생성 시간", "StatsDecrease": "허기·갈증 감소 속도",
    "NatureAbundance": "자연 자원", "Alarm": "주택 경보기 빈도", "LockedHouses": "잠긴 건물 빈도",
    "StarterKit": "시작 키트", "Nutrition": "영양 시스템", "FoodRotSpeed": "식품 부패 속도", "FridgeFactor": "냉장고 효율",
    "SeenHoursPreventLootRespawn": "최근 방문 지역 루팅 제한 시간", "HoursForLootRespawn": "전리품 재생성 시간",
    "MaxItemsForLootRespawn": "재생성 제한 아이템 수", "ConstructionPreventsLootRespawn": "건축물이 루팅 재생성 방지",
    "WorldItemRemovalList": "월드 아이템 정리 목록", "HoursForWorldItemRemoval": "바닥 아이템 정리 시간",
    "ItemRemovalListBlacklistToggle": "정리 목록 반전", "TimeSinceApo": "종말 이후 경과 개월",
    "PlantResilience": "작물 생명력", "PlantAbundance": "작물 수확량", "EndRegen": "피로 회복 속도",
    "Helicopter": "헬리콥터 이벤트", "MetaEvent": "메타 이벤트", "SleepingEvent": "수면 이벤트",
    "GeneratorFuelConsumption": "발전기 연료 소비", "GeneratorSpawning": "발전기 생성 빈도",
    "AnnotatedMapChance": "주석 지도 빈도", "CharacterFreePoints": "캐릭터 추가 포인트",
    "ConstructionBonusPoints": "건축물 내구도", "NightDarkness": "밤 밝기", "NightLength": "밤 길이",
    "BoneFracture": "골절 허용", "InjurySeverity": "부상 심각도", "HoursForCorpseRemoval": "시체 제거 시간",
    "DecayingCorpseHealthImpact": "부패 시체 영향", "ZombieHealthImpact": "살아있는 좀비의 건강 영향",
    "BloodLevel": "혈흔 양", "ClothingDegradation": "의류 마모 속도", "FireSpread": "화재 확산",
    "DaysForRottenFoodRemoval": "썩은 음식 제거 일수", "AllowExteriorGenerator": "실외 발전기 허용",
    "MaxFogIntensity": "최대 안개 강도", "MaxRainFxIntensity": "최대 비 효과", "EnableSnowOnGround": "지면 적설",
    "AttackBlockMovements": "공격 중 이동 제한", "SurvivorHouseChance": "생존자 주택 빈도",
    "VehicleStoryChance": "도로 차량 스토리", "ZoneStoryChance": "지역 스토리", "AllClothesUnlocked": "모든 의류 해제",
    "EnableTaintedWaterText": "오염된 물 경고", "EnableVehicles": "차량 활성화", "CarSpawnRate": "차량 생성 빈도",
    "ZombieAttractionMultiplier": "차량 소음 유인 배율", "VehicleEasyUse": "차량 간편 사용", "InitialGas": "초기 차량 연료",
    "FuelStationGasInfinite": "주유소 무한 연료", "FuelStationGasMin": "주유소 최소 연료", "FuelStationGasMax": "주유소 최대 연료",
    "FuelStationGasEmptyChance": "빈 주유기 확률", "LockedCar": "잠긴 차량 빈도", "CarGasConsumption": "차량 연료 소비",
    "CarGeneralCondition": "차량 전체 상태", "CarDamageOnImpact": "충돌 시 차량 피해", "DamageToPlayerFromHitByACar": "차량 충돌 플레이어 피해",
    "TrafficJam": "교통 체증 잔해", "CarAlarm": "차량 경보기 빈도", "PlayerDamageFromCrash": "사고 시 탑승자 피해",
    "SirenShutoffHours": "사이렌 종료 시간", "ChanceHasGas": "차량 연료 보유 확률", "RecentlySurvivorVehicles": "관리된 차량 빈도",
    "MultiHitZombies": "다중 타격", "RearVulnerability": "후방 취약도", "SirenEffectsZombies": "사이렌 좀비 유인",
    "AnimalStatsModifier": "동물 욕구 감소 속도", "AnimalMetaStatsModifier": "비활성 동물 욕구 감소",
    "AnimalPregnancyTime": "동물 임신 기간", "AnimalAgeModifier": "동물 성장 속도", "AnimalMilkIncModifier": "우유 생산 속도",
    "AnimalWoolIncModifier": "털 성장 속도", "AnimalRanchChance": "농장 동물 생성 빈도", "AnimalGrassRegrowTime": "목초 재성장 시간",
    "AnimalMetaPredator": "야간 포식자", "AnimalMatingSeason": "번식기 적용", "AnimalEggHatch": "알 부화 속도",
    "AnimalSoundAttractZombies": "동물 소리 좀비 유인", "AnimalTrackChance": "동물 흔적 빈도", "AnimalPathChance": "사냥 경로 빈도",
    "MaximumRatIndex": "최대 해충 지수", "DaysUntilMaximumRatIndex": "최대 해충 도달 일수",
    "MetaKnowledge": "미확인 미디어 표시", "SeeNotLearntRecipe": "미학습 레시피 표시", "MaximumLootedBuildingRooms": "루팅 건물 최대 방 수",
    "EnablePoisoning": "음식 독성 허용", "MaggotSpawn": "구더기 생성", "LightBulbLifespan": "전구 수명",
    "FishAbundance": "어류 자원", "LevelForMediaXPCutoff": "미디어 경험치 제한 레벨", "LevelForDismantleXPCutoff": "해체 경험치 제한 레벨",
    "BloodSplatLifespanDays": "혈흔 유지 일수", "LiteratureCooldown": "서적 재사용 대기 일수", "NegativeTraitsPenalty": "부정 특성 점수 페널티",
    "MinutesPerPage": "페이지당 읽기 시간", "KillInsideCrops": "실내 작물 고사", "PlantGrowingSeasons": "계절별 작물 성장",
    "PlaceDirtAboveground": "상층 흙 배치", "FarmingSpeedNew": "작물 성장 배율", "FarmingAmountNew": "작물 수확 배율",
    "MaximumLooted": "이미 털린 건물 최대 확률", "DaysUntilMaximumLooted": "최대 털림 확률 도달 일수",
    "RuralLooted": "시골 건물 털림 배율", "MaximumDiminishedLoot": "최대 전리품 감소율", "DaysUntilMaximumDiminishedLoot": "최대 감소 도달 일수",
    "MuscleStrainFactor": "근육 피로 배율", "DiscomfortFactor": "착용 불편 배율", "WoundInfectionFactor": "상처 감염 피해 배율",
    "NoBlackClothes": "과도하게 어두운 의류 방지", "EasyClimbing": "등반 실패 비활성화", "MaximumFireFuelHours": "최대 화로 연료 시간",
    "FirearmUseDamageChance": "총기 피해 판정 방식", "FirearmNoiseMultiplier": "총기 소음 배율", "FirearmJamMultiplier": "총기 걸림 배율",
    "FirearmMoodleMultiplier": "기분 상태 명중 보정", "FirearmWeatherMultiplier": "날씨 명중 보정", "FirearmHeadGearEffect": "머리 장비 명중 영향",
    "ClayLakeChance": "호수 점토 확률", "ClayRiverChance": "강 점토 확률", "GeneratorTileRange": "발전기 수평 범위",
    "GeneratorVerticalPowerRange": "발전기 수직 범위",
}

NESTED_LABELS = {
    "Basement.SpawnFrequency": "지하실 생성 빈도", "Map.AllowMiniMap": "미니맵 허용", "Map.AllowWorldMap": "월드맵 허용",
    "Map.MapAllKnown": "전체 지도 공개", "Map.MapNeedsLight": "지도 열람 시 빛 필요",
    "ZombieLore.Speed": "좀비 이동 속도", "ZombieLore.SprinterPercentage": "질주 좀비 비율", "ZombieLore.Strength": "좀비 공격력",
    "ZombieLore.Toughness": "좀비 내구력", "ZombieLore.Transmission": "감염 전파 방식", "ZombieLore.Mortality": "감염 발병 시간",
    "ZombieLore.Reanimate": "사망 후 부활 시간", "ZombieLore.Cognition": "좀비 지능", "ZombieLore.DoorOpeningPercentage": "문 열기 확률",
    "ZombieLore.CrawlUnderVehicle": "차량 아래 기어가기", "ZombieLore.Memory": "좀비 기억력", "ZombieLore.Sight": "좀비 시야",
    "ZombieLore.Hearing": "좀비 청각", "ZombieLore.SpottedLogic": "고급 은신 판정", "ZombieLore.ThumpNoChasing": "추적 중이 아닐 때 구조물 공격",
    "ZombieLore.ThumpOnConstruction": "플레이어 건축물 파괴", "ZombieLore.ActiveOnly": "활동 시간대", "ZombieLore.TriggerHouseAlarm": "좀비의 주택 경보기 작동",
    "ZombieLore.ZombiesDragDown": "좀비 끌어내리기", "ZombieLore.ZombiesCrawlersDragDown": "기어다니는 좀비 끌어내리기 기여",
    "ZombieLore.ZombiesFenceLunge": "울타리 돌진", "ZombieLore.ZombiesArmorFactor": "좀비 방어구 효과", "ZombieLore.ZombiesMaxDefense": "좀비 최대 방어율",
    "ZombieLore.ChanceOfAttachedWeapon": "부착 무기 확률", "ZombieLore.ZombiesFallDamage": "좀비 낙하 피해", "ZombieLore.DisableFakeDead": "가짜 시체 부활",
    "ZombieLore.PlayerSpawnZombieRemoval": "시작 위치 좀비 제거 범위", "ZombieLore.FenceThumpersRequired": "높은 울타리 파괴 필요 좀비 수",
    "ZombieLore.FenceDamageMultiplier": "울타리 피해 배율",
    "ZombieConfig.PopulationMultiplier": "전체 개체수 배율", "ZombieConfig.PopulationStartMultiplier": "시작 개체수 배율",
    "ZombieConfig.PopulationPeakMultiplier": "최고 개체수 배율", "ZombieConfig.PopulationPeakDay": "최고 개체수 도달 일",
    "ZombieConfig.RespawnHours": "재생성 주기", "ZombieConfig.RespawnUnseenHours": "미확인 지역 재생성 대기",
    "ZombieConfig.RespawnMultiplier": "회차당 재생성 비율", "ZombieConfig.RedistributeHours": "빈 지역 이동 주기",
    "ZombieConfig.FollowSoundDistance": "소리 추적 거리", "ZombieConfig.RallyGroupSize": "무리 크기",
    "ZombieConfig.RallyGroupSizeVariance": "무리 크기 변동률", "ZombieConfig.RallyTravelDistance": "무리 합류 거리",
    "ZombieConfig.RallyGroupSeparation": "무리 간 거리", "ZombieConfig.RallyGroupRadius": "무리 반경",
    "ZombieConfig.ZombiesCountBeforeDelete": "정리 전 최대 추적 좀비 수",
    "MultiplierConfig.Global": "전체 경험치 배율", "MultiplierConfig.GlobalToggle": "전체 경험치 배율 일괄 적용",
}

SKILL_LABELS = {
    "Fitness": "체력", "Strength": "힘", "Sprinting": "달리기", "Lightfoot": "가벼운 발걸음", "Nimble": "민첩함",
    "Sneak": "은신", "Axe": "도끼", "Blunt": "장병기 둔기", "SmallBlunt": "단병기 둔기", "LongBlade": "장검",
    "SmallBlade": "단검", "Spear": "창", "Maintenance": "유지보수", "Woodwork": "목공", "Cooking": "요리",
    "Farming": "농업", "Doctor": "응급처치", "Electricity": "전기", "MetalWelding": "용접", "Mechanics": "차량 정비",
    "Tailoring": "재봉", "Aiming": "조준", "Reloading": "재장전", "Fishing": "낚시", "Trapping": "덫 사냥",
    "PlantScavenging": "채집", "FlintKnapping": "석기 제작", "Masonry": "석공", "Pottery": "도예", "Carving": "조각",
    "Husbandry": "동물 돌보기", "Tracking": "추적", "Blacksmith": "대장장이", "Butchering": "도축", "Glassmaking": "유리 제작",
}

NAME_OVERRIDES = {
    "FoodLootNew": "food_loot", "WeaponLootNew": "weapon_loot", "OtherLootNew": "other_loot",
    "Farming": "farming_speed", "Alarm": "alarm_frequency", "MultiHitZombies": "multi_hit", "ZombieLore.ZombiesDragDown": "drag_down",
    "ZombieLore.ZombiesFenceLunge": "fence_lunge", "ZombieConfig.RespawnHours": "respawn_hours",
    "ZombieConfig.RespawnUnseenHours": "respawn_unseen_hours", "ZombieConfig.RespawnMultiplier": "respawn_multiplier",
    "MultiplierConfig.Global": "xp_multiplier",
}

DEFAULT_OVERRIDES = {
    "StartDay": 9,
    "MultiHitZombies": False,
}


def snake(value: str) -> str:
    value = value.replace(".", "_")
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()


def humanize(value: str) -> str:
    leaf = value.rsplit(".", 1)[-1]
    return re.sub(r"(?<!^)(?=[A-Z])", " ", leaf)


def category_for(key: str, line: int) -> str:
    if key.startswith("ZombieLore."): return "zombie_lore"
    if key.startswith("ZombieConfig."): return "zombie_advanced"
    if key.startswith("MultiplierConfig."): return "experience"
    if key.startswith("Map.") or key.startswith("Basement."): return "map"
    if line <= 24: return "population"
    if line <= 99: return "time"
    if line <= 135: return "infrastructure"
    if line <= 199 or key in {"SeenHoursPreventLootRespawn", "HoursForLootRespawn", "MaxItemsForLootRespawn", "ConstructionPreventsLootRespawn", "WorldItemRemovalList", "HoursForWorldItemRemoval", "ItemRemovalListBlacklistToggle", "MaximumLooted", "DaysUntilMaximumLooted", "RuralLooted", "MaximumDiminishedLoot", "DaysUntilMaximumDiminishedLoot"}: return "loot"
    if key.startswith("Animal") or key in {"MaximumRatIndex", "DaysUntilMaximumRatIndex"}: return "animals"
    if key in {"EnableVehicles", "CarSpawnRate", "ZombieAttractionMultiplier", "VehicleEasyUse", "InitialGas", "FuelStationGasInfinite", "FuelStationGasMin", "FuelStationGasMax", "FuelStationGasEmptyChance", "LockedCar", "CarGasConsumption", "CarGeneralCondition", "CarDamageOnImpact", "DamageToPlayerFromHitByACar", "TrafficJam", "CarAlarm", "PlayerDamageFromCrash", "SirenShutoffHours", "ChanceHasGas", "RecentlySurvivorVehicles", "SirenEffectsZombies"}: return "vehicles"
    if key in {"MultiHitZombies", "RearVulnerability", "AttackBlockMovements", "FirearmUseDamageChance", "FirearmNoiseMultiplier", "FirearmJamMultiplier", "FirearmMoodleMultiplier", "FirearmWeatherMultiplier", "FirearmHeadGearEffect"}: return "combat"
    if key in {"GeneratorFuelConsumption", "GeneratorSpawning", "AllowExteriorGenerator", "LightBulbLifespan", "GeneratorTileRange", "GeneratorVerticalPowerRange"}: return "infrastructure"
    if key in {"SurvivorHouseChance", "VehicleStoryChance", "ZoneStoryChance"}: return "map"
    if key in {"Temperature", "Rain", "ErosionSpeed", "ErosionDays", "Farming", "CompostTime", "NatureAbundance", "TimeSinceApo", "PlantResilience", "PlantAbundance", "Helicopter", "MetaEvent", "SleepingEvent", "MaxFogIntensity", "MaxRainFxIntensity", "EnableSnowOnGround", "FishAbundance", "KillInsideCrops", "PlantGrowingSeasons", "PlaceDirtAboveground", "FarmingSpeedNew", "FarmingAmountNew", "ClayLakeChance", "ClayRiverChance"}: return "world"
    return "survival"


def parse_scalar(raw: str):
    raw = raw.strip()
    if raw == "true": return True
    if raw == "false": return False
    if raw.startswith('"') and raw.endswith('"'): return json.loads(raw)
    return float(raw) if "." in raw else int(raw)


def documented_default(comments: list[str], options: list[dict], fallback):
    for comment in comments:
        match = re.search(r"\bDefault\s*[=:]\s*(.+?)(?:\s+Min:|\s+Max:|$)", comment)
        if not match:
            continue
        raw = match.group(1).strip().rstrip(".")
        for option in options:
            if option["label"].lower() == raw.lower():
                return option["value"]
        if raw.lower() in {"true", "false"}:
            return raw.lower() == "true"
        if re.fullmatch(r"-?\d+(?:\.\d+)?", raw):
            return float(raw) if "." in raw else int(raw)
    return fallback


def generate(source: Path) -> dict:
    comments: list[str] = []
    scope = ""
    fields = []
    table_names = {"Basement", "Map", "ZombieLore", "ZombieConfig", "MultiplierConfig"}
    for line_no, raw_line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        stripped = raw_line.strip()
        if stripped.startswith("--"):
            comments.append(stripped[2:].strip())
            continue
        table = re.match(r"^    ([A-Za-z][A-Za-z0-9_]*) = \{$", raw_line)
        if table and table.group(1) in table_names:
            scope = table.group(1)
            comments = []
            continue
        if scope and raw_line == "    },":
            scope = ""
            comments = []
            continue
        match = re.match(r"^\s{4,8}([A-Za-z][A-Za-z0-9_]*)\s*=\s*(.*),$", raw_line)
        if not match:
            if stripped: comments = []
            continue
        leaf, raw_value = match.groups()
        if leaf == "VERSION":
            comments = []
            continue
        key = f"{scope}.{leaf}" if scope else leaf
        value = parse_scalar(raw_value)
        field_type = "boolean" if isinstance(value, bool) else "integer" if isinstance(value, int) else "number" if isinstance(value, float) else "string"
        joined = " ".join(comments)
        options = []
        for comment in comments:
            option = re.match(r"^(\d+)\s*=\s*(.+)$", comment)
            if option:
                options.append({"value": int(option.group(1)), "label": option.group(2).strip()})
        minimum = re.search(r"\bMin(?:imum)?:\s*(-?\d+(?:\.\d+)?)", joined)
        maximum = re.search(r"\bMax(?:imum)?:\s*(-?\d+(?:\.\d+)?)", joined)
        first_help = next((c for c in comments if not re.match(r"^\d+\s*=", c)), "")
        first_help = re.sub(r"\s*(?:Min(?:imum)?:|Max(?:imum)?:|Default\s*[=:]).*$", "", first_help).strip()
        label = NESTED_LABELS.get(key) or (f"{SKILL_LABELS[leaf]} 경험치 배율" if scope == "MultiplierConfig" and leaf in SKILL_LABELS else LABELS.get(leaf)) or humanize(key)
        name = NAME_OVERRIDES.get(key, snake(key))
        value = DEFAULT_OVERRIDES.get(key, documented_default(comments, options, value))
        field = {"name": name, "key": key, "label": label, "category": category_for(key, line_no), "type": field_type, "default": value}
        if minimum: field["min"] = float(minimum.group(1)) if "." in minimum.group(1) else int(minimum.group(1))
        if maximum: field["max"] = float(maximum.group(1)) if "." in maximum.group(1) else int(maximum.group(1))
        if options:
            field["options"] = options
            field.setdefault("min", options[0]["value"])
            field.setdefault("max", options[-1]["value"])
        if field_type == "number": field["step"] = 0.01
        if first_help: field["help"] = first_help
        fields.append(field)
        comments = []
    names = [field["name"] for field in fields]
    if len(names) != len(set(names)):
        raise RuntimeError("Duplicate generated field names")
    return {
        "version": 6,
        "source": "Project Zomboid Build 42 server-generated SandboxVars.lua",
        "categories": [{"id": category, "title": title, "description": description} for category, title, description in CATEGORIES],
        "fields": fields,
    }


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: generate_sandbox_schema.py INPUT.lua OUTPUT.json")
    output = Path(sys.argv[2])
    output.write_text(json.dumps(generate(Path(sys.argv[1])), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
