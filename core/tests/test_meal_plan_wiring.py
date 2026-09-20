"""阶段 2 ②：matcher 的优先级链接线（L0–L4）+ D25 移除 sweet_heavy。

范式＝**派生不变式 + 负控制 + 变异检验**，不写快照断言。

最关键的三条：
- `test_conflict_meal_drops_counter_rules`：这是阶段 2 存在的理由——
  阶段 1 改了提示词口径（不对冲），离线路径没跟上 ⇒ 有 Key / 没 Key 拿到相反方向。
  不钉住它，改回 `_pick_rule` 也没人知道。
- `test_scene_rule_beats_damp_direction`：湿气方向**不能**压过场景规则。
  实测教训：写成能压 ⇒ 90 条样本里 69 条变，连炸鸡可乐都拿到化湿饮。
- `test_*_never_falls_back_to_late_night`：late_night 的 keywords 是空元组，
  它不是场景结论，拿它顶上会给用户「夜里吃得多」的错误时间叙述。
"""

from __future__ import annotations

import re

import pytest

from app.domain.diet_signals import build_meal_signals, load_meal_plan_rules
from app.domain.enums import Constitution
from app.domain.models import ParsedFood, ParsedMeal
from app.domain.safety import filter_by_constitution
from app.services import matcher
from app.services.food_lookup import match_foods, resolve_in_context

# 四种触发形状（实测值见 core/var/probe_stage2_before_after.py 的输出）：
#   CONFLICT：impact=3 / damp=2 / conflict=True
#   DAMP：    impact=1 / damp=3 —— 且没有关键词命中的场景规则（湿气方向接管）
#   SCENE：   impact=2 / damp=2 —— 但 greasy 命中「油」 ⇒ 场景规则优先
#   IMPACT：  impact=3 / damp=1 —— 护脾胃方向暂未开放（口径⑥）
# ⚠️ DAMP 不能写成「冰奶茶」：带「冰」就会被 cold_intake 命中（按设计该走温中），
#    这条样本要的是「纯湿气、没有场景关键词」的形状。
CONFLICT_CASE = "中午吃了麻辣烫配冰可乐"
DAMP_CASE = "下午茶一块蛋糕和一杯奶茶"
SCENE_CASE = "早餐油条加冰豆浆"
IMPACT_CASE = "喝了一瓶冰啤酒"


def _parsed(text: str) -> ParsedMeal:
    """用**真实的**解析原语装配，并装上 signals（与离线端点同一组调用）。"""
    foods: list[ParsedFood] = []
    for entry in match_foods(text):
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        resolved = resolve_in_context(text, entry)
        foods.append(
            ParsedFood(name=name, nature=resolved.nature, flavors=resolved.flavors)
        )
    parsed = ParsedMeal(foods=foods, summary=text)
    parsed.signals = build_meal_signals(text, foods)
    return parsed


def _recommend(text: str, constitution: Constitution):
    parsed = _parsed(text)
    recs, _msg, hits = matcher.fallback_recommend(parsed, constitution)
    assert recs, "契约要求永远给出一条合法搭配"
    return parsed, recs[0], hits


def _plan_text(key: str) -> str:
    return str((load_meal_plan_rules().get("plan") or {}).get(key) or "")


# ---------------------------------------------------------------
# 1. D25：sweet_heavy 已被湿气轴接管
# ---------------------------------------------------------------
def test_sweet_heavy_rule_is_gone() -> None:
    ids = [r["id"] for r in matcher.RULES]
    assert "sweet_heavy" not in ids, "D25 要求：两套化湿逻辑不能并存"
    assert ids, "RULES 被清空了"


def test_sweet_heavy_never_appears_in_hits() -> None:
    for text in (DAMP_CASE, SCENE_CASE, CONFLICT_CASE):
        _parsed_obj, _rec, hits = _recommend(text, Constitution.BALANCED)
        assert "sweet_heavy" not in hits


# ---------------------------------------------------------------
# 2. L0：没有 signals ⇒ 逐字节走老路
# ---------------------------------------------------------------
def test_without_signals_legacy_path_is_unchanged() -> None:
    parsed = _parsed(SCENE_CASE)
    parsed.signals = None
    recs_a, _msg, hits_a = matcher.fallback_recommend(parsed, Constitution.BALANCED)

    # 同一餐装上 signals 后走新链；老路的结果必须等于直接调 _pick_rule 的既有结论
    rule = matcher._pick_rule(parsed)
    assert rule is not None
    assert recs_a[0].title == rule["title"]
    assert hits_a[0] == rule["id"]
    assert "conflict_no_counter" not in hits_a
    assert "direction_" not in "".join(hits_a)


# ---------------------------------------------------------------
# 3. L1：寒热错杂 ⇒ 不对冲（本阶段存在的理由）
# ---------------------------------------------------------------
def test_conflict_meal_drops_counter_rules() -> None:
    parsed, rec, hits = _recommend(CONFLICT_CASE, Constitution.BALANCED)
    signals = parsed.signals
    assert signals is not None and signals.conflict is not None
    assert signals.conflict.conflict is True
    assert signals.conflict.heat_side and signals.conflict.cold_side

    # 改前这一餐拿的是 spicy（麦冬+罗汉果，皆凉）⇒ 正是口径⑨否掉的对冲
    assert "spicy" not in hits, "冲突餐还在用寒凉去压热 —— 对冲没修掉"
    assert "greasy" not in hits, "冲突餐还在用温热去压寒 —— 对冲没修掉"
    assert "conflict_no_counter" in hits
    assert rec.title == matcher.CONSTITUTION_DEFAULT[Constitution.BALANCED.value][1]


def test_conflict_never_falls_back_to_late_night() -> None:
    """late_night 没有关键词，拿它顶上会给「夜里吃得多」的错误时间叙述。"""
    for constitution in Constitution:
        _parsed_obj, _rec, hits = _recommend(CONFLICT_CASE, constitution)
        assert "late_night" not in hits, f"{constitution.value} 的冲突餐落到了夜宵兜底"


def test_conflict_note_is_written_into_fit_reason() -> None:
    note = _plan_text("conflict_note")
    assert note, "数据文件缺 conflict_note"
    parsed_obj, rec, _hits = _recommend(CONFLICT_CASE, Constitution.BALANCED)
    assert note in rec.fit_reason, "如实说明没写进理由 —— 只留痕在数据里等于没说"


def test_counter_rule_mutation_turns_guard_red() -> None:
    """变异检验（内存改副本）：判据必须真的依赖 `_is_counter_rule`，否则恒真。"""
    original = matcher._is_counter_rule
    try:
        matcher._is_counter_rule = lambda rule, heat, cold: False  # type: ignore[assignment]
        _parsed_obj, _rec, hits = _recommend(CONFLICT_CASE, Constitution.BALANCED)
        assert "conflict_no_counter" not in hits, "对冲判据被摘掉后断言竟然还成立 ⇒ 判据恒真"
    finally:
        matcher._is_counter_rule = original  # type: ignore[assignment]


def test_scene_keyword_gate_mutation_turns_guard_red() -> None:
    """变异检验：去掉「必须关键词命中」这道门槛 ⇒ 冲突餐会落到 late_night。"""
    parsed = _parsed(CONFLICT_CASE)
    conflict = parsed.signals.conflict
    loose = {
        rule["id"]
        for rule in matcher.RULES
        if not matcher._is_counter_rule(rule, conflict.heat_side, conflict.cold_side)
    }
    assert "late_night" in loose, "前提失效：late_night 本该在不设门槛时被选中"

    gated = matcher._scene_rule_ids(parsed, conflict)
    assert "late_night" not in gated, "门槛没挡住无关键词的兜底规则"


# ---------------------------------------------------------------
# 4. L3：湿气方向只取代 sweet_heavy 的**位置**，不压过场景规则
# ---------------------------------------------------------------
def test_damp_meal_is_taken_over_by_direction() -> None:
    parsed, rec, hits = _recommend(DAMP_CASE, Constitution.BALANCED)
    from app.domain.diet_signals import derive_meal_plan

    plan = derive_meal_plan(parsed.signals, Constitution.BALANCED.value)
    assert plan is not None and plan.first is not None and plan.first.open
    # 派生不变式：离线给出的搭配 == 纯函数派生的方向（同源，不是两份实现）
    assert rec.title == plan.first.title
    assert [h.name for h in rec.herbs] == plan.first.herbs
    assert "direction_damp_clear" in hits


def test_damp_direction_herbs_are_inside_candidate_set() -> None:
    """D23 的验收条款：方向接管给出的饮片必须来自 filter_by_constitution。"""
    taken = 0
    for constitution in Constitution:
        _parsed_obj, rec, hits = _recommend(DAMP_CASE, constitution)
        if not any(h.startswith("direction_") for h in hits):
            continue  # 该体质方向关闭 ⇒ 走的是体质默认（既有路径，不在本条断言范围）
        taken += 1
        allowed = {
            str(c.get("name")) for c in filter_by_constitution(constitution.value, limit=12)
        }
        assert {h.name for h in rec.herbs} <= allowed, f"{constitution.value} 给了候选集外的饮片"
    # 判据非真空：必须真的有体质被方向接管，否则这条断言等于没测
    assert taken >= 1, "没有任何体质的湿气餐被方向接管"


def test_scene_rule_beats_damp_direction() -> None:
    """油腻餐即使 damp≥2，也该走消食而不是化湿。

    实测教训：写成「湿气方向压过场景规则」⇒ 炸鸡可乐、油条豆浆都拿到化湿饮，
    90 条样本里 69 条变化。这条断言就是那次教训的回归测试。
    """
    parsed, rec, hits = _recommend(SCENE_CASE, Constitution.BALANCED)
    assert parsed.signals is not None and parsed.signals.dampness is not None
    assert parsed.signals.dampness.score >= 2, "样本失效：这条应当 damp≥2"
    assert hits and hits[0] == "greasy", f"湿气方向压过了场景规则：{hits}"
    assert rec.title == "陈皮山楂消食饮"


def test_closed_damp_direction_falls_back_to_constitution_default() -> None:
    """阴虚是化湿死角 ⇒ 退体质默认，而不是落到 late_night 兜底。"""
    parsed, rec, hits = _recommend(DAMP_CASE, Constitution.YIN_DEFICIENCY)
    assert "damp_clear_closed" in hits
    assert "late_night" not in hits
    assert rec.title == matcher.CONSTITUTION_DEFAULT[Constitution.YIN_DEFICIENCY.value][1]


# ---------------------------------------------------------------
# 5. Q3 α：护脾胃暂未开放 ⇒ 仍给搭配，但如实说明
# ---------------------------------------------------------------
def test_closed_stomach_guard_still_gives_a_blend() -> None:
    parsed, rec, hits = _recommend(IMPACT_CASE, Constitution.BALANCED)
    assert parsed.signals is not None and parsed.signals.impact is not None
    assert parsed.signals.impact.score >= 2, "样本失效：这条应当 impact≥2"
    assert rec.herbs, "契约要求永远给出一条合法搭配"
    assert "stomach_guard_closed" in hits

    # 关闭文案来自**被请求的那个方向**（护脾胃＝药材未定），不是 plan 级兜底
    from app.domain.diet_signals import load_meal_plan_rules

    rules = load_meal_plan_rules()
    note = str(((rules.get("directions") or {}).get("stomach_guard") or {}).get("closed_note") or "")
    assert note and note in rec.fit_reason, "关闭时必须如实说明，不能静默"


# ---------------------------------------------------------------
# 6. 契约：任何形状下都给出合法搭配、不超过剂量
# ---------------------------------------------------------------
@pytest.mark.parametrize("constitution", list(Constitution))
@pytest.mark.parametrize(
    "text", [CONFLICT_CASE, DAMP_CASE, SCENE_CASE, IMPACT_CASE]
)
def test_every_shape_returns_a_legal_blend(text: str, constitution: Constitution) -> None:
    parsed, rec, _hits = _recommend(text, constitution)
    assert 1 <= len(rec.herbs) <= 4
    for herb in rec.herbs:
        assert herb.amount_g > 0

    # 须煎煮的饮片必须走煎煮方式（既有护栏，新分支不得绕过）
    cook = set(matcher.blend_needs_cooking([h.name for h in rec.herbs]))
    if cook:
        assert rec.brew.vessel == matcher.COOK_BREW.vessel
        assert rec.brew.steep_min >= 20
    else:
        assert rec.brew.vessel == matcher.DEFAULT_BREW.vessel


def test_no_hit_mentions_removed_rule_or_leaks_internals() -> None:
    for text in (CONFLICT_CASE, DAMP_CASE, SCENE_CASE, IMPACT_CASE):
        _parsed_obj, _rec, hits = _recommend(text, Constitution.BALANCED)
        assert all(not re.match(r"direction_$", h) for h in hits)
        assert "sweet_heavy" not in hits
