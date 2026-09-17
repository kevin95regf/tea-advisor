"""领域枚举。所有中医属性的取值都必须来自这里，避免模型自由发挥。"""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """便于 JSON 序列化的字符串枚举基类。"""

    def __str__(self) -> str:  # pragma: no cover - 仅展示用
        return self.value


class Nature(StrEnum):
    """四气（寒热属性）。unknown 表示未能判定，禁止猜测。"""

    COLD = "cold"        # 寒
    COOL = "cool"        # 凉
    NEUTRAL = "neutral"  # 平
    WARM = "warm"        # 温
    HOT = "hot"          # 热
    UNKNOWN = "unknown"  # 未知


class Flavor(StrEnum):
    """五味（含淡、涩）。"""

    SOUR = "sour"            # 酸
    BITTER = "bitter"        # 苦
    SWEET = "sweet"          # 甘
    PUNGENT = "pungent"      # 辛
    SALTY = "salty"          # 咸
    BLAND = "bland"          # 淡
    ASTRINGENT = "astringent"  # 涩


class MealTime(StrEnum):
    """用餐时段。"""

    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"
    LATE_NIGHT = "late_night"
    UNKNOWN = "unknown"


class CookingMethod(StrEnum):
    """烹饪方式。油炸/烧烤偏燥热，生冷偏寒，会影响整餐判断。"""

    RAW = "raw"                # 生
    BOILED = "boiled"          # 煮/炖
    STEAMED = "steamed"        # 蒸
    STIR_FRIED = "stir_fried"  # 炒
    DEEP_FRIED = "deep_fried"  # 油炸
    GRILLED = "grilled"        # 烤
    COLD = "cold"              # 冰镇/冷藏
    PICKLED = "pickled"        # 腌制
    UNKNOWN = "unknown"


class Constitution(StrEnum):
    """体质类型，顺序与 GB/T 46939-2025 的九型名录一致。

    ⚠️ 顺序不是随意排的：国标名录为 平和/气虚/阳虚/阴虚/痰湿/湿热/血瘀/气郁/特禀。
    阴虚插在阳虚与痰湿之间，血瘀/气郁/特禀接在湿热之后。
    `tests/test_constitution_readiness.py` 会断言本枚举与 constitution.json、
    docs/constitution-9-types.json 的 id 与顺序三者一致，改动需同步三处。

    ⚠️ 收录进枚举 ≠ 可以对用户开放。能否对外服务由 herbs.json 是否备齐数据决定，
    见 `safety.ready_constitutions()`。
    """

    BALANCED = "balanced"                # 平和质
    QI_DEFICIENCY = "qi_deficiency"      # 气虚质
    YANG_DEFICIENCY = "yang_deficiency"  # 阳虚质
    YIN_DEFICIENCY = "yin_deficiency"    # 阴虚质
    PHLEGM_DAMP = "phlegm_damp"          # 痰湿质
    DAMP_HEAT = "damp_heat"              # 湿热质
    BLOOD_STASIS = "blood_stasis"        # 血瘀质
    QI_STAGNATION = "qi_stagnation"      # 气郁质
    SPECIAL_DIATHESIS = "special_diathesis"  # 特禀质


CONSTITUTION_LABELS: dict[str, str] = {
    Constitution.BALANCED.value: "平和质",
    Constitution.QI_DEFICIENCY.value: "气虚质",
    Constitution.YANG_DEFICIENCY.value: "阳虚质",
    Constitution.YIN_DEFICIENCY.value: "阴虚质",
    Constitution.PHLEGM_DAMP.value: "痰湿质",
    Constitution.DAMP_HEAT.value: "湿热质",
    Constitution.BLOOD_STASIS.value: "血瘀质",
    Constitution.QI_STAGNATION.value: "气郁质",
    Constitution.SPECIAL_DIATHESIS.value: "特禀质",
}

NATURE_LABELS: dict[str, str] = {
    Nature.COLD.value: "寒",
    Nature.COOL.value: "凉",
    Nature.NEUTRAL.value: "平",
    Nature.WARM.value: "温",
    Nature.HOT.value: "热",
    Nature.UNKNOWN.value: "未知",
}

FLAVOR_LABELS: dict[str, str] = {
    Flavor.SOUR.value: "酸",
    Flavor.BITTER.value: "苦",
    Flavor.SWEET.value: "甘",
    Flavor.PUNGENT.value: "辛",
    Flavor.SALTY.value: "咸",
    Flavor.BLAND.value: "淡",
    Flavor.ASTRINGENT.value: "涩",
}

MEAL_TIME_LABELS: dict[str, str] = {
    MealTime.BREAKFAST.value: "早餐",
    MealTime.LUNCH.value: "午餐",
    MealTime.DINNER.value: "晚餐",
    MealTime.SNACK.value: "加餐",
    MealTime.LATE_NIGHT.value: "夜宵",
    MealTime.UNKNOWN.value: "未指明",
}

# 属性来源（Verification.source）→ 中文。与 models.Verification 的取值一一对应。
# 这是「这个属性是怎么判出来的」的对外说法，界面必须原样展示，
# 让用户能区分「查表」与「模型推测」——三层架构的可信度就靠它传达。
SOURCE_LABELS: dict[str, str] = {
    "rule": "查表",
    "composed": "按烹饪方式推算",
    "llm": "模型推测",
    "unresolved": "无法判定",
}
