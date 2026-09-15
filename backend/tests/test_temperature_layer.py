"""温度前缀纯规则层的测试。

设计意图：冰镇/加热这类温度信息，用**字符串规则**判定比让模型判断可靠得多。
模型给的 cooking 无法区分"可靠证据"与"猜测"（会给希腊酸奶 cold、火腿三明治 grilled），
而「冰啤酒」「热牛奶」里的"冰/热"本身就在名字里。

安全边界：只在"剥掉前缀后剩下的名字能在表内查到"时才叠加，
天然排除「热狗」「热干面」「凉皮」这类温度字属于菜名的误伤。
"""

from __future__ import annotations

import pytest

from app.domain.enums import Nature
from app.domain.nature_math import detect_temperature_prefix, resolve_temperature
from app.services.food_lookup import resolve_food, strip_temperature_prefix
from app.services.food_lookup import CONF_COMPOSED


# ============================================================
# 前缀识别
# ============================================================
@pytest.mark.parametrize(
    "name",
    ["冰啤酒", "冰镇啤酒", "冰的酸奶", "加冰可乐", "去冰奶茶", "冷藏牛奶", "冻酸奶"],
)
def test_chill_prefixes_detected(name: str) -> None:
    detected = detect_temperature_prefix(name)
    assert detected is not None, f"{name} 应识别出降温前缀"
    assert detected[0] == -1


@pytest.mark.parametrize(
    "name",
    ["热牛奶", "温热的黄酒", "加热的豆浆", "烫的汤", "热腾腾的豆浆"],
)
def test_heat_prefixes_detected(name: str) -> None:
    detected = detect_temperature_prefix(name)
    assert detected is not None, f"{name} 应识别出升温前缀"
    assert detected[0] == 1


@pytest.mark.parametrize("name", ["啤酒", "牛奶", "正常可乐", "常温酸奶", ""])
def test_no_prefix_on_plain_names(name: str) -> None:
    assert detect_temperature_prefix(name) is None


def test_longer_prefix_wins() -> None:
    """「冰镇」优先于「冰」，否则会剥出"镇啤酒"这种残词。"""
    delta, prefix, rest = detect_temperature_prefix("冰镇啤酒")
    assert prefix == "冰镇"
    assert rest == "啤酒"
    assert delta == -1


def test_strip_helper_returns_original_when_no_prefix() -> None:
    name, delta, prefix = strip_temperature_prefix("啤酒")
    assert (name, delta, prefix) == ("啤酒", 0, "")


# ============================================================
# 叠加结果
# ============================================================
def test_iced_beer_gets_chill_adjustment() -> None:
    """凉 -1 → 寒。这是此前"已知局限"里拿不到的场景，现在由纯规则覆盖。"""
    resolved = resolve_food("冰啤酒", None, "warm", "喝了两瓶冰啤酒")
    assert resolved.nature == Nature.COLD.value
    assert resolved.verification.source == "composed"
    assert resolved.verification.confidence == CONF_COMPOSED
    assert "纯规则判定" in (resolved.verification.detail or "")
    assert "食物名" in (resolved.verification.detail or "")


# ============================================================
# 备注通道（方案 B）：温度信息在 note 里也要识别
# ============================================================
def test_temperature_in_note_is_detected() -> None:
    """模型可能输出 name=奶茶, note=去冰，温度信息在备注里。"""
    resolved = resolve_food("奶茶", None, "warm", "", "去冰")
    assert resolved.nature == Nature.COOL.value, "平 -1 应为凉"
    assert resolved.verification.source == "composed"
    assert "备注" in (resolved.verification.detail or "")


@pytest.mark.parametrize(
    "name,note,want",
    [
        ("啤酒", "冰镇", Nature.COLD),
        ("牛奶", "热", Nature.WARM),
        ("奶茶", "去冰", Nature.COOL),
        ("酸奶", "冷藏", Nature.COOL),  # 平 -1 = 凉
        ("奶茶", "常温", Nature.NEUTRAL),  # 常温不含温度词，不修正
    ],
)
def test_note_channel_matrix(name: str, note: str, want: Nature) -> None:
    resolved = resolve_food(name, None, "warm", "", note)
    assert resolved.nature == want, f"{name}+{note} 期望 {want}，实际 {resolved.nature}"


def test_name_channel_wins_over_note() -> None:
    """名字与备注冲突时以名字为准——名字是用户最直接的表达。"""
    resolved = resolve_food("冰啤酒", None, "warm", "", "热")
    assert resolved.nature == Nature.COLD.value
    assert "食物名" in (resolved.verification.detail or "")


def test_note_temperature_word_position_flexible() -> None:
    """备注里的温度词位置不固定，任意位置都要能识别。"""
    for note in ["去冰", "加了冰", "冰箱里拿出来的", "要热的", "温热一下"]:
        signal = resolve_temperature("奶茶", note)
        assert signal is not None, f"备注 {note!r} 未识别出温度词"
        assert signal.from_field == "note"


def test_note_channel_still_requires_anchor_in_table() -> None:
    """备注通道也要锚定表内条目：名字查不到表时不应凭 note 造出属性。"""
    resolved = resolve_food("祖母秘制卷饼", None, "warm", "", "冰镇")
    # 名字不在表内 → 落到 LLM 推测，不应因 note 里的"冰镇"改写
    assert resolved.verification.source == "llm"


def test_ice_cream_with_ice_note_not_double_counted() -> None:
    """「冰淇淋」本来带冰，备注再写"冰镇"也不该连扣两档。"""
    resolved = resolve_food("冰淇淋", None, "warm", "", "冰镇")
    assert resolved.nature == Nature.COLD.value
    detail = resolved.verification.detail or ""
    assert "修正" not in detail, f"冰淇淋不应被温度规则改写：{detail}"


def test_iced_cola_gets_chill_adjustment() -> None:
    resolved = resolve_food("加冰可乐", None, "warm", "加冰可乐")
    assert resolved.nature == Nature.COLD.value


def test_hot_milk_gets_heat_adjustment() -> None:
    """平 +1 → 温。"""
    resolved = resolve_food("热牛奶", None, "warm", "热牛奶")
    assert resolved.nature == Nature.WARM.value


def test_heat_adjustment_saturates() -> None:
    """性热的黄酒再加热仍是热（夹取，不溢出）。"""
    resolved = resolve_food("温热的黄酒", None, "warm", "温热的黄酒")
    assert resolved.nature == Nature.HOT.value


def test_remove_ice_still_cools() -> None:
    """去冰仍有降温语义（相对常温）。平 -1 → 凉。"""
    resolved = resolve_food("去冰奶茶", None, "warm", "去冰奶茶")
    assert resolved.nature == Nature.COOL.value


def test_warm_base_iced_becomes_neutral() -> None:
    """温 + 冰镇 -1 → 平。冰红茶不是凉茶。"""
    resolved = resolve_food("冰红茶", None, "warm", "喝了冰红茶")
    assert resolved.nature == Nature.NEUTRAL.value


def test_no_prefix_means_no_adjustment() -> None:
    resolved = resolve_food("啤酒", None, "warm", "啤酒")
    assert resolved.nature == Nature.COOL.value
    assert resolved.verification.source == "rule"


# ============================================================
# 安全边界：温度字属于菜名时不得叠加
# ============================================================
def test_names_whose_temp_char_is_part_of_dish() -> None:
    """温度字属于菜名时不得叠加温度修正。

    「热狗」去掉"热"剩"狗"、「热干面」去掉"热"剩"干面"，都不是完整的表内食物名，
    所以不满足准入条件，温度前缀被丢弃。
    至于之后落到哪一层（LLM 推测 or 靠关键词命中表）不是本测试关心的重点，
    重点是**没有被温度规则改写属性**。
    """
    hotdog = resolve_food("热狗", None, "warm", "吃了个热狗")
    assert "修正" not in (hotdog.verification.detail or ""), "热狗不应被温度规则改写"
    assert hotdog.verification.source == "llm", "热狗不在表内，应落到 LLM 推测"
    assert hotdog.verification.unverified is True

    # 热干面：剥掉"热"后"干面"不是完整食物名 → 温度前缀被丢弃，
    # 之后靠关键词"面"命中「面条」，但**不得**再升温
    noodle = resolve_food("热干面", None, "warm", "吃了热干面")
    assert "修正" not in (noodle.verification.detail or ""), "热干面的热属于菜名，不该升温"
    assert noodle.nature == Nature.NEUTRAL.value, "应保持面条的平性，而不是被升成温"


@pytest.mark.parametrize(
    "name,expected_source",
    [("冰啤酒", "composed"), ("热牛奶", "composed"), ("去冰奶茶", "composed")],
)
def test_admission_requires_full_entry_name_after_stripping(
    name: str, expected_source: str
) -> None:
    """准入条件：剥掉前缀后必须是完整表内食物名，温度前缀才生效。"""
    resolved = resolve_food(name, None, "warm", name)
    assert resolved.verification.source == expected_source


@pytest.mark.parametrize("name", ["冰淇淋", "热干面", "热狗"])
def test_non_full_entry_name_after_stripping_is_rejected(name: str) -> None:
    """剥后不是完整食物名 → 温度前缀不生效。"""
    resolved = resolve_food(name, None, "warm", name)
    assert "修正" not in (resolved.verification.detail or "")


def test_cool_char_not_treated_as_prefix() -> None:
    """「凉皮」「凉茶」的"凉"不是前缀，且它们各自在表内有条目。"""
    assert detect_temperature_prefix("凉皮") is None
    assert detect_temperature_prefix("凉茶") is None
    assert resolve_food("凉茶", None, "warm").nature == Nature.COLD.value


def test_ice_cream_not_double_adjusted() -> None:
    """「冰淇淋」剥成"淇淋"查不到 → 回退原名命中表，**不得再叠加 -1**。

    否则前缀就被算了两遍。这里用守卫条件（剥后名字须与规范名一致）拦住。
    """
    resolved = resolve_food("冰淇淋", None, "warm", "吃了冰淇淋")
    assert resolved.nature == Nature.COLD.value, "表值寒，不应再被扣一档"
    detail = resolved.verification.detail or ""
    assert "修正" not in detail, f"冰淇淋不应出现温度叠加：{detail}"


def test_prefix_does_not_apply_when_stripped_name_matches_entry() -> None:
    """守卫条件的直接验证：剥后名字 == 表内规范名时不叠加。"""
    # 「冰红茶」剥成"红茶"，与表内「红茶」一致 → 这里应当叠加（名称本不同）
    iced = resolve_food("冰红茶", None, "warm")
    assert "修正" in (iced.verification.detail or "")
    # 「冰淇淋」剥成"淇淋"与规范名「冰淇淋」不一致 → 不叠加
    cream = resolve_food("冰淇淋", None, "warm")
    assert "修正" not in (cream.verification.detail or "")


# ============================================================
# 与既有两层的优先级
# ============================================================
def test_table_variant_still_wins_for_same_food() -> None:
    """表里自带变体时（可乐 cold→寒）走变体层，不依赖温度前缀。"""
    resolved = resolve_food("可乐", "cold", "warm")
    assert resolved.nature == Nature.COLD.value
    assert "食材变体层" in (resolved.verification.detail or "")


def test_model_cooking_guess_still_ignored_for_exact_name() -> None:
    """温度规则不改变"精确命中时不信模型 cooking"的既有约定。"""
    greek = resolve_food("希腊酸奶", "cold", "warm")
    assert greek.nature == Nature.COOL.value
    sandwich = resolve_food("火腿三明治", "grilled", "warm")
    assert sandwich.nature == Nature.NEUTRAL.value
