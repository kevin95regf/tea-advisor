"""阶段 2 ①：推荐优先级（MealPlan）的派生 —— 零行为变化，测透后再接线。

范式＝**派生不变式 + 负控制 + 内存注入**，不写快照断言。

最关键的一条是 `test_*_injected_*`：口径⑥ 定护脾胃为**空集** ⇒ 生产上恒关闭，
「方向开放」这条分支**在当前数据下永远走不到**。不注入子集就测不到它，
将来往数据里加药时代码错了也没人知道（方案 §1.5③ / §6）。
"""

from __future__ import annotations

import copy

import pytest

from app.domain import diet_signals as ds
from app.domain.diet_signals import (
    build_meal_signals,
    derive_meal_plan,
    load_meal_plan_rules,
)
from app.domain.enums import Constitution
from app.domain.models import ParsedFood, ParsedMeal
from app.domain.safety import MissingConstitutionDataError, filter_by_constitution
from app.services.food_lookup import match_foods, resolve_in_context

# 样本刻意覆盖三种触发形状（实测值见 core/var/probe_plan_values.py）：
#   IMPACT：只有冲击度触发（冰啤酒 impact=3 / damp=1）
#   DAMP：只有湿气度触发（蛋糕冰奶茶 impact=1 / damp=3）
#   CONFLICT：三项全触发（麻辣烫配冰可乐 impact=3 / damp=2 / conflict=True）
#   QUIET：一项都不触发（热牛奶 impact=0 / damp=1）
IMPACT_CASE = "喝了一瓶冰啤酒"
DAMP_CASE = "下午吃了蛋糕喝了冰奶茶"
CONFLICT_CASE = "中午吃了麻辣烫配冰可乐"
QUIET_CASE = "早上喝了热牛奶"


def _foods(text: str) -> list[ParsedFood]:
    """用**真实的**解析原语装配 foods，不在测试里合成四性。"""
    out: list[ParsedFood] = []
    for entry in match_foods(text):
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        resolved = resolve_in_context(text, entry)
        out.append(ParsedFood(name=name, nature=resolved.nature, flavors=resolved.flavors))
    return out


def _signals(text: str):
    return build_meal_signals(text, _foods(text))


def _rules() -> dict:
    return copy.deepcopy(load_meal_plan_rules())


def _direction(rules: dict, direction_id: str) -> dict:
    return (rules.get("directions") or {})[direction_id]


def _plan_text(rules: dict, key: str) -> str:
    """中文字串全部从数据文件反查——测试里不写死「护脾胃暂未开放」这种句子。"""
    return str((rules.get("plan") or {}).get(key) or "")


# ---------------------------------------------------------------
# 1. 零行为变化：默认 None ⇒ 既有构造方逐字节不变
# ---------------------------------------------------------------
def test_parsed_meal_plan_defaults_to_none() -> None:
    assert ParsedMeal(foods=_foods(IMPACT_CASE)).plan is None


# ---------------------------------------------------------------
# 2. 负控制：不触发 ⇒ 不派生
# ---------------------------------------------------------------
def test_quiet_meal_yields_no_plan() -> None:
    signals = _signals(QUIET_CASE)
    assert signals.impact is not None and signals.dampness is not None
    assert signals.impact.score == 0, "样本失效：这条应当是「冲击度不触发」"
    assert derive_meal_plan(signals, Constitution.BALANCED.value) is None


def test_without_signals_scores_are_zero_and_no_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    """负控制：识别器被清空 ⇒ 分数归零 ⇒ 计划也不该派生（证明不是硬编码）。"""
    monkeypatch.setattr(ds, "identify_signals", lambda *a, **k: [])
    for text in (IMPACT_CASE, DAMP_CASE):
        assert derive_meal_plan(_signals(text), Constitution.BALANCED.value) is None


def test_missing_rules_file_yields_no_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ds, "load_meal_plan_rules", lambda: {})
    assert derive_meal_plan(_signals(DAMP_CASE), Constitution.BALANCED.value) is None


# ---------------------------------------------------------------
# 3. 派生不变式：可用集合 = 方向子集 ∩ filter_by_constitution
# ---------------------------------------------------------------
@pytest.mark.parametrize("constitution", list(Constitution))
def test_picked_herbs_are_subset_of_candidate_set(constitution: Constitution) -> None:
    rules = _rules()
    plan = derive_meal_plan(_signals(DAMP_CASE), constitution.value, rules=rules)
    assert plan is not None, "湿气样本必须派生出计划"
    if plan.first is None or not plan.first.open:
        return  # 该体质方向关闭，下面第 4 组断言另测
    allowed = {
        str(c.get("name"))
        for c in filter_by_constitution(constitution.value, limit=12)
    }
    assert set(plan.first.herbs) <= allowed, "方向给出了候选集外的饮片"


@pytest.mark.parametrize("constitution", list(Constitution))
def test_amounts_and_order_come_from_data(constitution: Constitution) -> None:
    """取中哪几味、各多少克、什么顺序，必须逐字等于数据文件里的定义。"""
    rules = _rules()
    plan = derive_meal_plan(_signals(DAMP_CASE), constitution.value, rules=rules)
    assert plan is not None
    first = plan.first
    if first is None or not first.open:
        return

    spec = _direction(rules, first.direction)
    wanted = [
        (str(h["name"]), float(h["amount_g"])) for h in (spec.get("herbs") or [])
    ]
    allowed = {str(c.get("name")) for c in filter_by_constitution(constitution.value, limit=12)}
    expected = [(n, g) for n, g in wanted if n in allowed][: int(spec.get("take") or 0)]

    assert first.herbs == [n for n, _ in expected]
    assert first.amounts == {n: g for n, g in expected}
    assert first.title == "".join(first.herbs) + str(spec.get("title_suffix") or "")
    assert first.reason == str(spec.get("reason") or "").format(herbs="、".join(first.herbs))
    assert first.label == str(spec.get("label") or "")


def test_title_is_composed_not_hardcoded() -> None:
    """改掉数据文件里的后缀 ⇒ 标题必须跟着变（证明标题是拼出来的，不是写死的）。"""
    rules = _rules()
    plan = derive_meal_plan(_signals(DAMP_CASE), Constitution.BALANCED.value, rules=rules)
    assert plan is not None and plan.first is not None and plan.first.open

    mutated = _rules()
    _direction(mutated, "damp_clear")["title_suffix"] = "XYZ"
    other = derive_meal_plan(_signals(DAMP_CASE), Constitution.BALANCED.value, rules=mutated)
    assert other is not None and other.first is not None
    assert other.first.title == plan.first.title.replace(
        str(_direction(rules, "damp_clear")["title_suffix"]), "XYZ"
    )


# ---------------------------------------------------------------
# 4. 判据非真空：既要有开、也要有关，九型全走到
# ---------------------------------------------------------------
def test_direction_has_both_open_and_closed_constitutions() -> None:
    opened: list[str] = []
    closed: list[str] = []
    for constitution in Constitution:
        plan = derive_meal_plan(_signals(DAMP_CASE), constitution.value)
        assert plan is not None
        (opened if (plan.first and plan.first.open) else closed).append(constitution.value)

    assert opened + closed and len(opened) + len(closed) == len(list(Constitution))
    # 防「恒真」：两边都不能为空，否则判据等于没测。
    assert opened, "没有任何体质的化湿方向开放 —— 交集判据恒假"
    assert closed, "没有任何体质的化湿方向关闭 —— 交集判据恒真"


def test_mutation_clearing_herbs_closes_every_constitution() -> None:
    """变异检验：把方向子集清空 ⇒ 九型必须全部关闭（证明「开放」不是硬编码）。"""
    mutated = _rules()
    _direction(mutated, "damp_clear")["herbs"] = []
    still_open = [
        c.value
        for c in Constitution
        if (p := derive_meal_plan(_signals(DAMP_CASE), c.value, rules=mutated))
        and p.first
        and p.first.open
    ]
    assert still_open == [], f"子集清空后仍有体质开放：{still_open}"


# ---------------------------------------------------------------
# 5. 方向关闭 ⇒ 如实说，不静默退化成别的方向
# ---------------------------------------------------------------
def test_empty_direction_is_closed_and_notes_honestly() -> None:
    """护脾胃是空集（口径⑥：药材暂不定）⇒ 触发了也只说「暂未开放」。"""
    rules = _rules()
    assert _direction(rules, "stomach_guard")["herbs"] == [], "数据前提变了：护脾胃不再是空集"
    plan = derive_meal_plan(_signals(IMPACT_CASE), Constitution.BALANCED.value, rules=rules)
    assert plan is not None
    assert plan.first is None, "方向关闭时不该给 first"
    assert plan.note == _plan_text(rules, "closed_note")
    assert plan.note, "关闭时必须给出如实说明，不能静默"


def test_conflict_meal_yields_conflict_note_not_damp_direction() -> None:
    """冲突餐：damp 也达标，但 unless=conflict ⇒ 不得落到化湿方向（方案 §2-② L1 优先）。"""
    rules = _rules()
    signals = _signals(CONFLICT_CASE)
    assert signals.conflict is not None and signals.conflict.conflict is True
    assert signals.dampness is not None and signals.dampness.score >= 2, "样本需满足 damp≥2"

    plan = derive_meal_plan(signals, Constitution.BALANCED.value, rules=rules)
    assert plan is not None
    assert plan.first is None, "冲突餐不该被化湿方向接管"
    assert plan.note == _plan_text(rules, "conflict_note")
    assert plan.note != _plan_text(rules, "closed_note"), "冲突说明的优先级必须高于关闭说明"


# ---------------------------------------------------------------
# 6. 内存注入：护脾胃当前恒关闭 ⇒ 开放分支只能这样测
# ---------------------------------------------------------------
def test_injected_subset_opens_stomach_guard() -> None:
    injected = _rules()
    _direction(injected, "stomach_guard")["herbs"] = [
        {"name": "陈皮", "amount_g": 5},
        {"name": "茯苓", "amount_g": 6},
    ]
    plan = derive_meal_plan(_signals(IMPACT_CASE), Constitution.BALANCED.value, rules=injected)
    assert plan is not None and plan.first is not None
    assert plan.first.direction == "stomach_guard"
    assert plan.first.open is True
    assert plan.first.herbs == ["陈皮", "茯苓"], "顺序必须按数据文件"
    assert plan.first.amounts == {"陈皮": 5.0, "茯苓": 6.0}
    assert set(plan.first.herbs) <= {
        str(c.get("name")) for c in filter_by_constitution(Constitution.BALANCED.value, limit=12)
    }
    assert plan.note == "", "方向开放时不该再说「暂未开放」"


def test_injected_subset_still_respects_candidate_window() -> None:
    """注入的两味在湿热质候选集里都没有 ⇒ 该体质仍必须关闭，不得直接取子集。"""
    injected = _rules()
    # 陈皮、茯苓：平和质候选集里两味都在，湿热质候选集里两味都不在（实测 probe_stage2c §G）
    _direction(injected, "stomach_guard")["herbs"] = [
        {"name": "陈皮", "amount_g": 5},
        {"name": "茯苓", "amount_g": 6},
    ]
    allowed = {str(c.get("name")) for c in filter_by_constitution(Constitution.DAMP_HEAT.value, limit=12)}
    assert not ({"陈皮", "茯苓"} & allowed), "数据前提变了：湿热质候选集已含这两味"

    plan = derive_meal_plan(_signals(IMPACT_CASE), Constitution.DAMP_HEAT.value, rules=injected)
    assert plan is not None
    assert plan.first is None, "交集为空时不得取子集里的药"
    assert plan.note == _plan_text(injected, "closed_note")

    # 同一份注入在平和质下必须开放 ⇒ 证明差异来自候选集窗口，不是别的
    other = derive_meal_plan(_signals(IMPACT_CASE), Constitution.BALANCED.value, rules=injected)
    assert other is not None and other.first is not None and other.first.open
    assert other.first.herbs == ["陈皮", "茯苓"]


def test_injected_subset_below_take_is_closed() -> None:
    """交集只有 1 味而 take=2 ⇒ 关闭（不退化成「取到几味算几味」）。"""
    injected = _rules()
    _direction(injected, "stomach_guard")["herbs"] = [
        {"name": "陈皮", "amount_g": 5},
        {"name": "山药", "amount_g": 10},  # 湿热质候选集里没有
    ]
    plan = derive_meal_plan(_signals(IMPACT_CASE), Constitution.DAMP_HEAT.value, rules=injected)
    assert plan is not None and plan.first is None


# ---------------------------------------------------------------
# 7. avoid（兼体质屏蔽集）参与交集
# ---------------------------------------------------------------
def test_avoid_narrows_the_available_set() -> None:
    rules = _rules()
    constitution = Constitution.BALANCED.value
    plain_allowed = {
        str(c.get("name")) for c in filter_by_constitution(constitution, limit=12)
    }
    narrowed_allowed = {
        str(c.get("name"))
        for c in filter_by_constitution(
            constitution, limit=12, avoid=[Constitution.DAMP_HEAT.value]
        )
    }
    narrowed = derive_meal_plan(
        _signals(DAMP_CASE), constitution, avoid=(Constitution.DAMP_HEAT.value,), rules=rules
    )
    assert narrowed is not None
    if narrowed.first and narrowed.first.open:
        # 带 avoid 的计划只能用带 avoid 的候选集里的饮片
        assert set(narrowed.first.herbs) <= narrowed_allowed
    # 判据非真空：avoid 必须真的剔掉了饮片，否则这条断言等于没测。
    # ⚠️ 不能断言 narrowed ⊆ plain：候选集被剔除后会由后面的 neutral 段**补位**到 limit，
    # 所以带 avoid 的候选集会出现原本排在窗口外的味（实测：乌梅／莲子／罗汉果／百合）。
    assert plain_allowed - narrowed_allowed, "avoid 没有剔掉任何饮片，样本失效"


# ---------------------------------------------------------------
# 8. 数据不齐 ⇒ 不抛、如实标
# ---------------------------------------------------------------
def test_missing_constitution_data_is_reported_not_raised() -> None:
    with pytest.raises(MissingConstitutionDataError):
        filter_by_constitution("__nonexistent__", limit=12)

    plan = derive_meal_plan(_signals(DAMP_CASE), "__nonexistent__")
    assert plan is not None
    assert plan.data_missing is True
    assert plan.first is None
    assert plan.note == _plan_text(_rules(), "data_missing_note")


# ---------------------------------------------------------------
# 9. 第二段的表达（Q5：只给一条 + 一句话推迟）
# ---------------------------------------------------------------
def test_second_stage_is_deferred_and_carries_note() -> None:
    rules = _rules()
    plan = derive_meal_plan(_signals(DAMP_CASE), Constitution.BALANCED.value, rules=rules)
    assert plan is not None
    assert plan.second is not None
    assert plan.second.direction == "constitution"
    assert plan.second.open is False, "第二段本餐不执行"
    assert plan.deferred is True
    assert plan.second_note == _plan_text(rules, "second_note")
    assert plan.second_note, "推迟话术必须来自数据文件，不能由调用方自己写"


# ---------------------------------------------------------------
# 10. 数据文件自身的守卫：中文只有一份、方向字段齐
# ---------------------------------------------------------------
def test_data_file_shape_is_complete() -> None:
    rules = load_meal_plan_rules()
    assert rules, "meal_plan_rules.json 没加载出来"
    meta = rules.get("_meta") or {}
    for key in ("version", "basis", "notice", "review_status"):
        assert meta.get(key), f"_meta 缺 {key}"

    assert int((rules.get("trigger") or {}).get("impact_min") or 0) >= 1
    assert int((rules.get("trigger") or {}).get("dampness_min") or 0) >= 1

    for direction_id in rules.get("order") or []:
        direction = _direction(rules, direction_id)
        assert str(direction.get("label") or ""), f"{direction_id} 缺中文 label"
        assert "when" in direction, f"{direction_id} 缺 when"
        for herb in direction.get("herbs") or []:
            assert str(herb.get("name") or ""), f"{direction_id} 的饮片缺名字"
            assert float(herb.get("amount_g") or 0) > 0, f"{direction_id} 的饮片缺克数"
