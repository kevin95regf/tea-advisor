"""三层架构接线的测试：校准、来源标记、Agent2 隔离。

这些测试都不调用模型——用构造出来的 ParsedMeal 验证确定性逻辑，
所以能稳定跑、也适合放进 CI。
"""

from __future__ import annotations

from app.agents.agent1_diet import calibrate_parsed
from app.agents.agent2_recommend import build_user_prompt
from app.domain.enums import Constitution, CookingMethod, Nature
from app.domain.models import ParsedFood, ParsedMeal
from app.services.food_lookup import (
    CONF_COMPOSED,
    CONF_LLM,
    CONF_RULE,
    CONF_UNRESOLVED,
    resolve_food,
)


def make_meal(*foods: ParsedFood) -> ParsedMeal:
    return ParsedMeal(foods=list(foods), confidence=0.99)


# ============================================================
# 校准：表命中时覆盖模型的判断
# ============================================================
def test_table_overrides_wrong_model_judgement() -> None:
    """复现用户实测的 bug：模型把性温的茉莉花茶判成凉。"""
    meal = make_meal(
        ParsedFood(name="茉莉花茶", nature=Nature.COOL, cooking=CookingMethod.BOILED)
    )
    out = calibrate_parsed(meal, "喝了茉莉花茶")
    assert out.foods[0].nature == Nature.WARM, "应以表为准，覆盖模型判的凉"
    assert out.foods[0].verification.source == "rule"


def test_neutral_foods_corrected_from_model_warm_bias() -> None:
    """模型对平性主食有偏温倾向，应被表纠正为平。"""
    meal = make_meal(
        ParsedFood(name="小笼包", nature=Nature.WARM, cooking=CookingMethod.STEAMED),
        ParsedFood(name="兰州拉面", nature=Nature.WARM, cooking=CookingMethod.BOILED),
    )
    out = calibrate_parsed(meal, "吃了小笼包和兰州拉面")
    assert [f.nature for f in out.foods] == [Nature.NEUTRAL, Nature.NEUTRAL]


def test_foreign_food_not_mismatched_to_generic_entry() -> None:
    """希腊酸奶不应被当成普通酸奶（平），表里有它自己的条目（凉）。"""
    resolved = resolve_food("希腊酸奶", "unknown", "warm")
    assert resolved.entry is not None
    assert resolved.entry["name"] == "希腊酸奶"
    assert resolved.nature == Nature.COOL.value


def test_variant_layer_applies_before_cooking_layer() -> None:
    """食材变体层优先：红薯烤制走变体表（温），不是通用 +1。"""
    resolved = resolve_food("红薯", "grilled")
    assert resolved.nature == Nature.WARM.value
    assert "食材变体层" in (resolved.verification.detail or "")


def test_cooking_layer_used_when_no_variant() -> None:
    """表里没写变体的条目才走烹饪修正层，来源标记为 composed。

    注意：仅当食物名**未精确命中**表内规范名时才走这一层。
    「炸馒头」这个名字不在表里，靠关键词"馒头"识别到 → 走烹饪层 +1 → 温。
    """
    resolved = resolve_food("炸馒头", "deep_fried")
    assert resolved.nature == Nature.WARM.value
    assert resolved.verification.source == "composed"
    assert resolved.verification.confidence == CONF_COMPOSED


def test_exact_name_hit_does_not_apply_model_cooking_guess() -> None:
    """已知局限：规范名精确命中时，不叠加模型给的烹饪修正。

    原因是无法从模型输出可靠区分「可靠证据」与「猜测」——
    「希腊酸奶」模型可能给 cold、「火腿三明治」可能给 grilled，
    照单全收会把表值污染成错误的档位。
    代价：「冰啤酒」这种真实存在的冰镇修正也拿不到（表内「啤酒」为凉）。
    要覆盖冰镇场景，应把「冰啤酒」单独收录进表并写 variant_nature。
    """
    # 表值优先，不受模型 cooking 影响
    greek = resolve_food("希腊酸奶", "cold", "warm")
    assert greek.nature == Nature.COOL.value, "希腊酸奶应维持表值凉"

    sandwich = resolve_food("火腿三明治", "grilled", "warm")
    assert sandwich.nature == Nature.NEUTRAL.value, "火腿三明治应维持表值平"

    # 代价：冰镇修正不再生效
    beer = resolve_food("啤酒", "cold", "warm")
    assert beer.nature == Nature.COOL.value, "表内啤酒为凉，冰镇修正不叠加"
    assert "未叠加模型推测的处理方式修正" in (beer.verification.detail or "")


def test_ice_beer_needs_its_own_entry() -> None:
    """冰镇类饮品要拿到「寒」，需要在表里单独收录。这里固化当前行为。"""
    resolved = resolve_food("冰啤酒", "cold", "cold")
    # 「冰啤酒」不在表内 → 靠关键词"啤酒"识别 → 走烹饪层 -1 → 寒
    assert resolved.nature == Nature.COLD.value
    assert resolved.verification.source == "composed"


def test_not_in_table_keeps_llm_value_but_marks_unverified() -> None:
    meal = make_meal(ParsedFood(name="祖母秘制卷饼", nature=Nature.WARM))
    out = calibrate_parsed(meal)
    food = out.foods[0]
    assert food.nature == Nature.WARM, "未覆盖时应保留模型判断"
    assert food.verification.source == "llm"
    assert food.verification.confidence == CONF_LLM
    assert food.verification.unverified is True


def test_substring_can_pull_unrelated_name_into_table() -> None:
    """已知局限：名字里含表内关键词就会被匹配。

    例如「某个沙拉卷」含"沙拉"，会被判成表内「沙拉」的属性。
    这是关键词匹配的固有代价——要避免只能把这类菜品单独收录进表。
    本测试固化该行为，避免以后误以为是 bug 而改坏匹配逻辑。
    """
    resolved = resolve_food("某个沙拉卷", "unknown", Nature.WARM.value)
    assert resolved.verification.source == "rule"
    assert resolved.entry is not None
    assert resolved.entry["name"] == "沙拉"


def test_unresolved_when_neither_table_nor_llm() -> None:
    meal = make_meal(ParsedFood(name="谜之料理", nature=Nature.UNKNOWN))
    out = calibrate_parsed(meal)
    food = out.foods[0]
    assert food.nature == Nature.UNKNOWN
    assert food.verification.source == "unresolved"
    assert food.verification.confidence == CONF_UNRESOLVED


def test_low_confidence_keeps_unknown_nature() -> None:
    """低于阈值时数据层保留 unknown，由前端决定不显示——
    这样 Agent2 仍能看出"这项没判出来"，而不是以为它不存在。"""
    resolved = resolve_food("谜之料理", "unknown", None)
    assert resolved.nature == Nature.UNKNOWN.value
    assert resolved.verification.confidence == CONF_UNRESOLVED


def test_no_cross_food_contamination_from_sentence() -> None:
    """整句口述里的信息不得串到其他食物上。

    回归用例：`calibrate_parsed` 曾把整句用户口述当作 text_hint 传给每一项，
    于是「中午吃了碗兰州拉面，还喝了杯麻辣烫」里的"辣"会把**兰州拉面**判成温。
    修复后 text_hint 只取该食物自己的名字与备注。
    """
    meal = make_meal(
        ParsedFood(name="兰州拉面", nature=Nature.WARM, cooking=CookingMethod.BOILED),
        ParsedFood(name="麻辣烫", nature=Nature.HOT, cooking=CookingMethod.BOILED, note="麻辣汤底"),
    )
    out = calibrate_parsed(meal, "中午吃了碗兰州拉面，还喝了杯麻辣烫")
    by_name = {f.name: f for f in out.foods}
    assert by_name["兰州拉面"].nature == Nature.NEUTRAL, "不应被邻项的辣味串味成温"
    assert by_name["麻辣烫"].nature == Nature.HOT


def test_spicy_note_still_applies_to_own_food() -> None:
    """该食物自己的备注里有辛辣信号时，修正仍然生效。"""
    meal = make_meal(
        ParsedFood(name="烤馒头", nature=Nature.NEUTRAL, cooking=CookingMethod.GRILLED, note="撒了辣椒面"),
    )
    out = calibrate_parsed(meal)
    assert out.foods[0].nature in (Nature.WARM, Nature.HOT)


# ============================================================
# 置信度与把握度
# ============================================================
def test_table_hit_has_rule_confidence() -> None:
    resolved = resolve_food("米饭", "steamed")
    assert resolved.verification.confidence == CONF_RULE


def test_unreviewed_table_entry_is_marked_unverified() -> None:
    """方案 X：表命中但未审核 → 保留 0.9 置信度，但必须标"待验证"。"""
    resolved = resolve_food("米饭", "steamed")
    assert resolved.verification.unverified is True, "当前表尚未人工审核，应标记"
    assert resolved.verification.confidence == CONF_RULE


def test_meal_confidence_recomputed_from_items() -> None:
    """整餐把握度按逐项置信度重算，不再采信模型自报的 0.99。"""
    meal = make_meal(
        ParsedFood(name="米饭", nature=Nature.NEUTRAL),          # rule 0.9
        ParsedFood(name="谜之料理", nature=Nature.UNKNOWN),        # unresolved 0.1
    )
    out = calibrate_parsed(meal)
    assert out.confidence == 0.5, f"期望 (0.9+0.1)/2=0.5，实际 {out.confidence}"


def test_empty_meal_is_untouched() -> None:
    meal = ParsedMeal(foods=[], confidence=0.0)
    out = calibrate_parsed(meal)
    assert out.foods == []


# ============================================================
# Agent2 隔离（方案 B：可见但禁用）
# ============================================================
def test_agent2_prompt_lists_unverified_separately() -> None:
    meal = make_meal(
        ParsedFood(name="茉莉花茶", nature=Nature.WARM, cooking=CookingMethod.BOILED),
        ParsedFood(name="谜之料理", nature=Nature.UNKNOWN),
    )
    meals = calibrate_parsed(meal, "喝了茉莉花茶")
    prompt = build_user_prompt(meals, Constitution.PHLEGM_DAMP)
    assert "食性未经验证" in prompt
    assert "不得作为搭配计算依据" in prompt
    assert "此项食性未经验证" in prompt, "需包含与推荐直接相关时的注明要求"


def test_agent2_prompt_omits_section_when_all_verified() -> None:
    """全部可信时不应出现该节，避免提示词里塞无用内容。"""
    meal = ParsedMeal(foods=[ParsedFood(name="米饭", nature=Nature.NEUTRAL)])
    # 手工把标记改成已验证，模拟审核完成后的状态
    meal.foods[0].verification.unverified = False
    prompt = build_user_prompt(meal, Constitution.PHLEGM_DAMP)
    assert "食性未经验证" not in prompt


def test_agent2_prompt_marks_below_threshold_as_not_accepted() -> None:
    meal = calibrate_parsed(make_meal(ParsedFood(name="谜之料理", nature=Nature.UNKNOWN)))
    prompt = build_user_prompt(meal, Constitution.PHLEGM_DAMP)
    assert "低于阈值" in prompt
