"""四性数值编码与修正运算的测试。

这里的规则由使用者确认，属于产品语义的一部分，不是实现细节：
  编码：寒-2 / 凉-1 / 平0 / 温+1 / 热+2
  两层修正：食材变体（查表优先）→ 烹饪修正（±1 兜底）
  合成：取绝对值最大者为主导，同向累加封顶 ±2，反向只做 50% 抵消且不翻转主导方向
"""

from __future__ import annotations

import pytest

from app.domain.enums import Nature
from app.domain.nature_math import (
    NATURE_MAX,
    NATURE_MIN,
    apply_cooking_fallback,
    clamp,
    combine,
    has_spicy_marker,
    nature_to_num,
    num_to_nature,
    num_to_nature_with_dominant,
    shift_nature,
)


# ============================================================
# 编码
# ============================================================
@pytest.mark.parametrize(
    "nature,num",
    [
        (Nature.COLD, -2),
        (Nature.COOL, -1),
        (Nature.NEUTRAL, 0),
        (Nature.WARM, 1),
        (Nature.HOT, 2),
    ],
)
def test_nature_to_num(nature: Nature, num: int) -> None:
    assert nature_to_num(nature) == num


def test_nature_to_num_accepts_plain_string() -> None:
    assert nature_to_num("warm") == 1
    assert nature_to_num("cold") == -2


def test_unknown_has_no_number() -> None:
    """unknown 表示"没有值"，必须返回 None 而不是 0——否则会被当成平性参与运算。"""
    assert nature_to_num(Nature.UNKNOWN) is None
    assert nature_to_num(None) is None
    assert nature_to_num("不存在的值") is None


def test_num_to_nature_roundtrip() -> None:
    for nature, num in [
        (Nature.COLD, -2),
        (Nature.COOL, -1),
        (Nature.NEUTRAL, 0),
        (Nature.WARM, 1),
        (Nature.HOT, 2),
    ]:
        assert num_to_nature(num) == nature


def test_num_to_nature_rounds_to_nearest() -> None:
    assert num_to_nature(0.4) == Nature.NEUTRAL
    assert num_to_nature(-0.4) == Nature.NEUTRAL
    assert num_to_nature(1.4) == Nature.WARM
    assert num_to_nature(-1.6) == Nature.COLD


def test_num_to_nature_clamps_out_of_range() -> None:
    """溢出必须夹取：性热的羊肉再油炸仍是热，不能变成"超热"。"""
    assert num_to_nature(5) == Nature.HOT
    assert num_to_nature(-5) == Nature.COLD
    assert num_to_nature(100) == Nature.HOT


def test_boundary_half_goes_to_dominant_direction() -> None:
    """±0.5 的边界值归到主导方向，避免反向抵消把偏性抹成平性。"""
    assert num_to_nature_with_dominant(-0.5, -1) == Nature.COOL
    assert num_to_nature_with_dominant(0.5, 1) == Nature.WARM
    # 非边界值不受主导方向影响
    assert num_to_nature_with_dominant(-1.4, -1) == Nature.COOL
    assert num_to_nature_with_dominant(0.4, 1) == Nature.NEUTRAL


def test_clamp() -> None:
    assert clamp(0) == 0
    assert clamp(3) == NATURE_MAX
    assert clamp(-3) == NATURE_MIN
    assert clamp(2) == NATURE_MAX


# ============================================================
# shift_nature
# ============================================================
def test_shift_within_range() -> None:
    assert shift_nature(Nature.NEUTRAL, 1) == Nature.WARM
    assert shift_nature(Nature.NEUTRAL, -1) == Nature.COOL
    assert shift_nature(Nature.COOL, 1) == Nature.NEUTRAL


def test_shift_saturates_at_bounds() -> None:
    assert shift_nature(Nature.HOT, 1) == Nature.HOT
    assert shift_nature(Nature.COLD, -1) == Nature.COLD
    assert shift_nature(Nature.WARM, 5) == Nature.HOT


def test_shift_unknown_stays_none() -> None:
    assert shift_nature(Nature.UNKNOWN, 1) is None
    assert shift_nature(None, -1) is None


# ============================================================
# 辛辣识别
# ============================================================
@pytest.mark.parametrize(
    "text", ["麻辣烫", "重辣", "加了辣椒", "花椒很多", "咖喱味", "孜然羊肉", "芥末"]
)
def test_spicy_markers_detected(text: str) -> None:
    assert has_spicy_marker(text)


@pytest.mark.parametrize("text", ["白粥", "清蒸鱼", "苹果", ""])
def test_non_spicy_text(text: str) -> None:
    assert not has_spicy_marker(text)


# ============================================================
# 烹饪修正（第 2 层兜底）
# ============================================================
def test_steam_and_boil_are_zero() -> None:
    """蒸煮 ≈ 0：不改变原属性。"""
    for cooking in ("steamed", "boiled"):
        result, notes = apply_cooking_fallback(Nature.COOL, cooking)
        assert result == Nature.COOL, f"{cooking} 不应改变属性"
        assert notes == []


def test_deep_fried_adds_one() -> None:
    result, notes = apply_cooking_fallback(Nature.NEUTRAL, "deep_fried")
    assert result == Nature.WARM
    assert notes and "煎炸" in notes[0]


def test_grilled_adds_one() -> None:
    result, _ = apply_cooking_fallback(Nature.COOL, "grilled")
    assert result == Nature.NEUTRAL


def test_iced_subtracts_one() -> None:
    result, notes = apply_cooking_fallback(Nature.NEUTRAL, "cold")
    assert result == Nature.COOL
    assert notes and "冰镇" in notes[0]


def test_deep_fried_on_hot_saturates() -> None:
    """羊肉本身是热，油炸后仍是热（夹取，不溢出）。"""
    result, _ = apply_cooking_fallback(Nature.HOT, "deep_fried")
    assert result == Nature.HOT


def test_spicy_adds_one() -> None:
    result, notes = apply_cooking_fallback(Nature.NEUTRAL, "boiled", text_hint="重辣")
    assert result == Nature.WARM
    assert any("辛辣" in n for n in notes)


def test_iced_plus_spicy_cancels() -> None:
    """冰镇 -1 与辛辣 +1 累加后归零。"""
    result, _ = apply_cooking_fallback(Nature.NEUTRAL, "cold", text_hint="麻辣")
    assert result == Nature.NEUTRAL


def test_unknown_base_stays_none() -> None:
    result, _ = apply_cooking_fallback(Nature.UNKNOWN, "deep_fried")
    assert result is None


# ============================================================
# 第二层合成
# ============================================================
def test_empty_returns_neutral() -> None:
    value, sign = combine([])
    assert value == 0.0
    assert sign == 0


def test_all_neutral_returns_neutral() -> None:
    value, sign = combine([0, 0, 0])
    assert value == 0.0
    assert sign == 0


def test_single_item() -> None:
    value, sign = combine([-1])
    assert value == -1.0
    assert sign == -1


def test_tomato_egg_is_cool() -> None:
    """用户给的例子：番茄(凉-1) + 鸡蛋(平0) + 炒(0) → 偏凉。"""
    value, sign = combine([-1, 0])
    assert sign == -1
    assert num_to_nature_with_dominant(value, sign) == Nature.COOL


def test_same_direction_accumulates() -> None:
    """同向累加：凉 + 凉 → 寒。"""
    value, sign = combine([-1, -1])
    assert value == -2.0
    assert num_to_nature(value) == Nature.COLD


def test_same_direction_caps_at_two() -> None:
    """同向累加封顶 ±2，不溢出。"""
    value, _ = combine([2, 2, 2])
    assert value == 2.0
    value, _ = combine([-2, -2, -2])
    assert value == -2.0


def test_opposite_does_not_flip_dominant() -> None:
    """核心规则：羊肉(热+2) + 苦瓜(寒-2) 不得翻转成寒凉。"""
    value, sign = combine([2, -2])
    assert sign == 1, "主导方向应为正（羊肉先出现）"
    assert value > 0, f"不得翻转为负，实际 {value}"
    nature = num_to_nature_with_dominant(value, sign)
    assert nature in (Nature.WARM, Nature.HOT), f"应为温或热，实际 {nature}"


def test_opposite_halves_the_dominant() -> None:
    """反向只做 50% 抵消：+2 遇 -2 → 2 + 0.5×(-2) = 1（温）。"""
    value, sign = combine([2, -2])
    assert value == 1.0
    assert num_to_nature_with_dominant(value, sign) == Nature.WARM


def test_cool_plus_warm_leans_cool() -> None:
    """凉(-1) 主导，遇温(+1) 抵消 50% → -0.5 → 仍是凉（不翻转）。"""
    value, sign = combine([-1, 1])
    assert sign == -1
    assert value == -0.5
    assert num_to_nature_with_dominant(value, sign) == Nature.COOL


def test_dominant_is_largest_absolute_value() -> None:
    """主导项取绝对值最大者，与出现顺序无关。"""
    # 温(+1) 在前，热(+2) 在后 → 主导是热
    value, sign = combine([1, 2])
    assert sign == 1
    assert value == 2.0 or value == 3.0
    # 寒(-2) 在后也应成为主导
    value, sign = combine([1, -2])
    assert sign == -1


def test_tie_broken_by_first_occurrence() -> None:
    """并列时取先出现的（通常是主料），保证同样输入结果稳定。"""
    _, sign_a = combine([2, -2])
    _, sign_b = combine([-2, 2])
    assert sign_a == 1
    assert sign_b == -1


def test_neutral_does_not_dilute() -> None:
    """平性食材既不贡献方向也不稀释——不能因为加了米饭就把凉性拉平。"""
    only_cool, _ = combine([-1])
    with_rice, sign = combine([-1, 0, 0])
    assert only_cool == with_rice
    assert sign == -1


def test_multiple_opposite_offsets() -> None:
    """多个反向项各抵消 50%：热+2 遇 凉-1 与 寒-2 → 2 + 0.5×(-3) = 0.5。"""
    value, sign = combine([2, -1, -2])
    assert sign == 1
    assert value == 0.5
    assert num_to_nature_with_dominant(value, sign) == Nature.WARM


def test_cooking_applied_after_combine() -> None:
    """烹饪修正最后叠加：番茄炒蛋（偏凉）再冰镇 → 寒。"""
    value, sign = combine([-1, 0])
    nature = num_to_nature_with_dominant(value, sign)
    assert nature == Nature.COOL
    final, _ = apply_cooking_fallback(nature, "cold")
    assert final == Nature.COLD
