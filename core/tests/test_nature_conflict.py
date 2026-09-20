"""寒热错杂判定的测试（阶段 0）。

`detect_nature_conflict` 只回答「这餐是不是寒热错杂」，**不做加法**——
整餐偏性的合成是 `combine()` 的事，两者并列、互不越界。
"""

from __future__ import annotations

import pytest

from app.domain.enums import Nature
from app.domain.nature_math import CONFLICT_THRESHOLD, detect_nature_conflict


def test_both_sides_extreme_is_conflict():
    result = detect_nature_conflict([("炸鸡", Nature.HOT), ("冰可乐", Nature.COLD)])
    assert result.conflict is True
    assert result.heat_side == ["炸鸡"]
    assert result.cold_side == ["冰可乐"]


def test_threshold_is_two():
    assert CONFLICT_THRESHOLD == 2


def test_warm_and_cool_are_below_threshold():
    """温(+1) 与 凉(-1) 都不够极端 ⇒ 不算错杂。"""
    result = detect_nature_conflict([("羊肉", Nature.WARM), ("黄瓜", Nature.COOL)])
    assert result.conflict is False
    assert result.heat_side == []
    assert result.cold_side == []


def test_boundary_exactly_at_threshold():
    """恰好 ±2 触发，±1 不触发——边界必须钉住，否则阈值定义会漂。"""
    assert detect_nature_conflict([("麻辣烫", Nature.HOT), ("凉拌菜", Nature.COOL)]).conflict is False
    assert detect_nature_conflict([("麻辣烫", Nature.HOT), ("冰啤酒", Nature.COLD)]).conflict is True


def test_one_side_only_is_not_conflict():
    result = detect_nature_conflict([("炸鸡", Nature.HOT), ("米饭", Nature.NEUTRAL)])
    assert result.conflict is False
    assert result.heat_side == ["炸鸡"]
    assert result.cold_side == []


def test_negative_side_never_leaks_into_heat_side():
    """负数侧不能因为 `abs()` 被算进 heat 侧——这正是刻意不写 abs() 的原因。"""
    result = detect_nature_conflict([("冰镇西瓜", Nature.COLD)])
    assert result.heat_side == []
    assert result.cold_side == ["冰镇西瓜"]


def test_unknown_does_not_count():
    """四性判不出（unknown）既不进热侧也不进寒侧，且不能凑成「错杂」。"""
    result = detect_nature_conflict(
        [("某不明物", Nature.UNKNOWN), ("炸鸡", Nature.HOT), ("冰可乐", Nature.COLD)]
    )
    assert result.conflict is True
    assert "某不明物" not in result.heat_side + result.cold_side

    only_unknown = detect_nature_conflict([("某不明物", Nature.UNKNOWN)])
    assert only_unknown.conflict is False


def test_accepts_plain_strings():
    """调用方传字符串值（非枚举）也要能判。"""
    result = detect_nature_conflict([("炸鸡", "hot"), ("冰可乐", "cold")])
    assert result.conflict is True


def test_empty_input():
    result = detect_nature_conflict([])
    assert result.conflict is False
    assert result.heat_side == []
    assert result.cold_side == []


def test_side_lists_keep_input_order():
    result = detect_nature_conflict(
        [("麻辣香锅", Nature.HOT), ("冰可乐", Nature.COLD), ("辣椒", Nature.HOT)]
    )
    assert result.heat_side == ["麻辣香锅", "辣椒"]
    assert result.cold_side == ["冰可乐"]


@pytest.mark.parametrize("nature", [Nature.COLD, Nature.HOT, Nature.UNKNOWN, None])
def test_never_raises(nature):
    detect_nature_conflict([("x", nature)])
