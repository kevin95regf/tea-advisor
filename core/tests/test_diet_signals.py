"""饮食信号识别与两维打分的测试（阶段 0）。

范式＝**派生不变式 + 负控制 + 结构守卫**，不写快照断言。三件必须守住的事：
  1. 每个 signal 都有样本能触发它 —— 加了信号忘加样本就变红；
  2. 所有者给出的四条规格样例逐个成立；
  3. **负控制**：把参数换成内存副本（cap / weights / 聚合方式），结果必须跟着变
     —— 否则「封顶 3」这类断言可能恒真。
"""

from __future__ import annotations

import copy

import pytest

from app.domain.diet_signals import (
    DIMENSION_DAMPNESS,
    DIMENSION_IMPACT,
    EVIDENCE_ORDER,
    identify_signals,
    load_diet_signals,
    score_dimension,
)
from app.domain.enums import Flavor, Nature
from app.domain.models import ParsedFood


# ============================================================
# 工具
# ============================================================
def F(name: str, nature: Nature = Nature.NEUTRAL, flavors=()) -> ParsedFood:
    return ParsedFood(name=name, nature=nature, flavors=list(flavors))


def spec() -> dict:
    data = load_diet_signals()
    assert data, "core/data/diet_signals.json 缺失或为空"
    return data


def ids_of(hits) -> set[str]:
    return {h.id for h in hits}


def dims_copy() -> dict:
    """维度的**内存副本**——变异检验用，绝不落盘。"""
    return copy.deepcopy(spec()["dimensions"])


# 每个样本只求「能触发目标信号」，不要求互斥
SAMPLES: list[tuple[str, str, list[ParsedFood]]] = [
    ("iced／位置语义", "炸鸡 冰可乐", [F("炸鸡", Nature.HOT, [Flavor.SALTY]), F("可乐", Nature.COOL, [Flavor.SWEET])]),
    ("iced／名字自带前缀", "", [F("冰可乐", Nature.COOL, [Flavor.SWEET])]),
    ("frozen", "", [F("冰淇淋", Nature.COLD, [Flavor.SWEET])]),
    ("cold_raw", "", [F("生鱼片", Nature.COOL)]),
    ("fried", "", [F("炸鸡", Nature.HOT, [Flavor.SALTY])]),
    ("greasy", "", [F("红烧肉", Nature.WARM)]),
    ("spicy", "", [F("火锅", Nature.HOT, [Flavor.PUNGENT])]),
    ("carbonated", "", [F("可乐", Nature.COOL, [Flavor.SWEET])]),
    ("alcohol", "", [F("红酒", Nature.WARM, [Flavor.SWEET])]),
    ("high_sugar", "", [F("蛋糕", Nature.NEUTRAL, [Flavor.SWEET])]),
    ("dairy", "", [F("牛奶", Nature.NEUTRAL, [Flavor.SWEET])]),
    (
        "temp_shock",
        "火锅 冰可乐",
        [F("火锅", Nature.HOT, [Flavor.PUNGENT]), F("可乐", Nature.COOL, [Flavor.SWEET])],
    ),
]


# ============================================================
# 1. 覆盖度：每个 signal 都要有样本
# ============================================================
def test_every_signal_has_a_triggering_sample():
    declared = {s["id"] for s in spec()["signals"]}
    covered: set[str] = set()
    for _label, text, foods in SAMPLES:
        covered |= ids_of(identify_signals(text, foods))

    missing = sorted(declared - covered)
    assert not missing, f"这些信号没有任何样本能触发：{missing}"

    # 反向守卫：样本触发了数据里没声明的 id ⇒ 数据被改过、测试没跟上
    extra = sorted(covered - declared)
    assert not extra, f"样本触发了未声明的信号：{extra}"

    # 「至少测到 N 组」——防止有人把样本删到只剩一两组还全绿
    assert len(SAMPLES) >= len(declared), "样本组数应不少于信号数"


# ============================================================
# 2. 结构守卫：weights 引用完整性
# ============================================================
def test_dimension_weights_only_reference_declared_signals():
    data = spec()
    declared = {s["id"] for s in data["signals"]}
    for name, dim in data["dimensions"].items():
        unknown = sorted(set(dim["weights"]) - declared)
        assert not unknown, f"维度 {name} 的 weights 引用了未声明的信号：{unknown}"


def test_every_signal_is_used_by_at_least_one_dimension():
    data = spec()
    used: set[str] = set()
    for dim in data["dimensions"].values():
        used |= set(dim["weights"])
    unused = sorted({s["id"] for s in data["signals"]} - used)
    assert not unused, f"这些信号没有被任何维度使用（死信号）：{unused}"


def test_signal_specs_have_required_fields():
    for signal in spec()["signals"]:
        for key in ("id", "label", "judge", "arity", "evidence", "rule"):
            assert key in signal, f"{signal.get('id')} 缺字段 {key}"
        assert signal["evidence"] in EVIDENCE_ORDER, f"{signal['id']} 的 evidence 非法"
        assert signal["arity"] in ("item", "meal"), f"{signal['id']} 的 arity 非法"


# ============================================================
# 3. 规格样例（所有者给定的四条）
# ============================================================
def test_spec_ice_beer_impact_is_3():
    hits = identify_signals("冰啤酒", [F("冰啤酒", Nature.COOL, [Flavor.BITTER, Flavor.SWEET])])
    assert ids_of(hits) >= {"iced", "alcohol", "carbonated"}
    result = score_dimension(DIMENSION_IMPACT, hits)
    assert result.score == 3
    assert result.action == "protect_stomach_plus"


def test_spec_hotpot_with_iced_cola():
    foods = [F("火锅", Nature.HOT, [Flavor.PUNGENT]), F("可乐", Nature.COOL, [Flavor.SWEET])]
    hits = identify_signals("火锅 冰可乐", foods)

    impact = score_dimension(DIMENSION_IMPACT, hits)
    # 单品最大 2（冰可乐：冰＋碳酸），再叠 per-meal 寒热急变 +1
    assert "temp_shock" in ids_of(hits)
    assert impact.score == 3

    # 冰可乐同时命中 iced 与 high_sugar（可乐在高糖名单里）⇒ 湿气度 2
    assert ids_of(hits) >= {"iced", "high_sugar"}
    assert score_dimension(DIMENSION_DAMPNESS, hits).score == 2


def test_spec_small_cake():
    hits = identify_signals("一小块蛋糕", [F("蛋糕", Nature.NEUTRAL, [Flavor.SWEET])])
    assert score_dimension(DIMENSION_IMPACT, hits).score == 0
    assert score_dimension(DIMENSION_DAMPNESS, hits).score == 1


def test_spec_cake_and_iced_milk_tea_dampness_caps_at_3():
    foods = [F("蛋糕", Nature.NEUTRAL, [Flavor.SWEET]), F("冰奶茶", Nature.COOL, [Flavor.SWEET])]
    hits = identify_signals("三块奶油蛋糕加冰奶茶", foods)
    assert score_dimension(DIMENSION_DAMPNESS, hits).score == 3


# ============================================================
# 4. 负控制（变异检验，全部作用在内存副本上）
# ============================================================
def test_negative_control_cap_is_actually_applied():
    foods = [F("蛋糕", Nature.NEUTRAL, [Flavor.SWEET]), F("冰奶茶", Nature.COOL, [Flavor.SWEET])]
    hits = identify_signals("三块奶油蛋糕加冰奶茶", foods)
    dims = dims_copy()

    assert score_dimension(DIMENSION_DAMPNESS, hits, dims).score == 3

    dims["dampness"]["cap"] = 99
    # 未封顶时原始求和是 4（蛋糕高糖 1 ＋ 冰奶茶高糖/乳制品/iced 各 1）
    # ——同时证明「封顶 3」不是恒真，且 sum 真的在累加
    assert score_dimension(DIMENSION_DAMPNESS, hits, dims).score == 4


def test_negative_control_removing_high_sugar_zeroes_the_cake():
    hits = identify_signals("一小块蛋糕", [F("蛋糕", Nature.NEUTRAL, [Flavor.SWEET])])
    dims = dims_copy()
    assert score_dimension(DIMENSION_DAMPNESS, hits, dims).score == 1

    del dims["dampness"]["weights"]["high_sugar"]
    assert score_dimension(DIMENSION_DAMPNESS, hits, dims).score == 0


def test_impact_takes_max_across_items_not_global_sum():
    """冲击度是「先单品求和、再跨条目取最大」。

    两条各自只有 1 分的单品 ⇒ 结果必须是 1；若退化成全局求和就是 2。
    """
    foods = [F("薯条", Nature.HOT), F("可乐", Nature.COOL, [Flavor.SWEET])]
    hits = identify_signals("薯条和可乐", foods)
    # 可乐还带 high_sugar（在湿气名单里），但它不在 impact.weights 中，不影响冲击度
    assert ids_of(hits) == {"fried", "carbonated", "high_sugar"}
    assert score_dimension(DIMENSION_IMPACT, hits).score == 1


def test_dampness_is_sum_not_max():
    """湿气度必须求和：取最大值的话两个蛋糕样例会分不出来。"""
    small = identify_signals("一小块蛋糕", [F("蛋糕", Nature.NEUTRAL, [Flavor.SWEET])])
    big = identify_signals(
        "三块奶油蛋糕加冰奶茶",
        [F("蛋糕", Nature.NEUTRAL, [Flavor.SWEET]), F("冰奶茶", Nature.COOL, [Flavor.SWEET])],
    )
    small_score = score_dimension(DIMENSION_DAMPNESS, small).score
    big_score = score_dimension(DIMENSION_DAMPNESS, big).score
    assert small_score < big_score, "「一小块」与「三块加冰奶茶」必须区分得开"


# ============================================================
# 5. 边界
# ============================================================
def test_empty_input_scores_zero():
    hits = identify_signals("", [])
    assert hits == []
    assert score_dimension(DIMENSION_IMPACT, hits).score == 0
    assert score_dimension(DIMENSION_DAMPNESS, hits).score == 0
    assert score_dimension(DIMENSION_IMPACT, hits).action == "none"


def test_single_signal_is_one():
    hits = identify_signals("", [F("蛋糕", Nature.NEUTRAL, [Flavor.SWEET])])
    assert ids_of(hits) == {"high_sugar"}
    assert score_dimension(DIMENSION_DAMPNESS, hits).score == 1


def test_unknown_dimension_returns_zero_without_crashing():
    result = score_dimension("nonexistent_dimension", [])
    assert result.score == 0
    assert result.note, "维度缺失时必须留痕，不能静默"


# ============================================================
# 6. unknown ≠ 0
# ============================================================
def test_unknown_nature_is_not_treated_as_neutral():
    """四性判不出时不参与计分。

    `火锅` 的 spicy 依赖 `nature=hot`；四性 unknown 时不能命中——
    既不能当「平」，更不能当「热」。
    """
    hits = identify_signals("", [F("火锅", Nature.UNKNOWN, [Flavor.PUNGENT])])
    assert "spicy" not in ids_of(hits)
    assert "temp_shock" not in ids_of(hits)


# ============================================================
# 7. 不裸扫原文（单字子串是这个项目踩过的坑）
# ============================================================
@pytest.mark.parametrize("name", ["酱油", "凉茶", "生菜", "牛油果"])
def test_no_bare_substring_scanning(name: str):
    hits = identify_signals(name, [F(name)])
    assert "fried" not in ids_of(hits), f"{name} 不该因「油」被当成油炸"
    assert "cold_raw" not in ids_of(hits), f"{name} 不该被当成生食"
    assert "iced" not in ids_of(hits), f"{name} 不该被当成冰镇"


def test_icecream_is_not_iced():
    """头号负控制样本。

    food_lookup.py:622-625 记过这个坑：用子串 `"冰" in text` 会把「冰淇淋」判成冰镇。
    正确行为＝冰淇淋命中 frozen，但**不**命中 iced。
    """
    hits = identify_signals("", [F("冰淇淋", Nature.COLD, [Flavor.SWEET])])
    assert "frozen" in ids_of(hits)
    assert "iced" not in ids_of(hits)


def test_spicy_never_uses_bare_nature_hot():
    """`nature=hot` 里有 4 条根本不辣（油条／羊肉／薯条／炸鱼薯条）。

    这条守住「不收编裸 nature=hot」——否则油条会同时得 fried 与 spicy 两份冲击。
    """
    for name, flavors in (("油条", [Flavor.SWEET]), ("羊肉", [Flavor.SWEET]), ("薯条", [Flavor.SALTY])):
        hits = identify_signals("", [F(name, Nature.HOT, flavors)])
        assert "spicy" not in ids_of(hits), f"{name} nature=hot 但不辣，不该命中 spicy"


def test_liquor_pungent_is_not_double_counted():
    """白酒 flavors 含 pungent，但它的「辛」是酒精的辛烈 ⇒ 只走 alcohol。"""
    hits = identify_signals("", [F("白酒", Nature.HOT, [Flavor.PUNGENT, Flavor.SWEET])])
    assert "alcohol" in ids_of(hits)
    assert "spicy" not in ids_of(hits)


# ============================================================
# 8. evidence_floor
# ============================================================
def test_evidence_floor_takes_the_weakest_and_leaves_a_note():
    hits = identify_signals("冰啤酒", [F("冰啤酒", Nature.COOL)])
    result = score_dimension(DIMENSION_IMPACT, hits)
    # iced=full、alcohol=full、carbonated=none ⇒ 最弱是 none
    assert result.evidence_floor == "none"
    assert result.note, "弱档命中时 note 必须非空"


def test_evidence_floor_is_full_when_all_strong():
    hits = identify_signals("", [F("红酒", Nature.WARM, [Flavor.SWEET])])
    result = score_dimension(DIMENSION_IMPACT, hits)
    assert result.evidence_floor == "full"
    assert result.note == ""
