"""late_night 兜底的叙述不得再提「夜里 / 夜宵」（**D31**，选 β：只改文案）。

`RULES.late_night` 名字叫 late_night，**实际不是夜宵规则**：`keywords` 是空元组、
只靠 `match_natures={UNKNOWN}` 拿分 ⇒ 它是「没判出任何场景」的兜底。实测中午
「米饭炒青菜」、早餐「面包牛奶」都会走到这里，却给用户一句「夜里吃得多」——
一句**凭空的时间叙述**。本轮不碰判据（(α) 依赖 D28），只把叙述改掉。

判据刻意钉在**文案**上而不是"命中哪条规则"：命中不该变（那是要单独立项的 (α)），
要守的只是"不许再给用户编一个时间"。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

CORE_DIR = Path(__file__).resolve().parent.parent
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from app.api.analyze_offline import _match_nature_from_text  # noqa: E402
from app.domain.meal_time import guess_meal_time  # noqa: E402
from app.domain.models import Constitution, ParsedFood, ParsedMeal  # noqa: E402
from app.services.food_lookup import match_foods, resolve_in_context  # noqa: E402
from app.services.matcher import RULES, _pick_rule, fallback_recommend  # noqa: E402

TIME_WORDS = ("夜里", "夜宵")
# 实测会落到 late_night 兜底的**非夜宵**样本
FALLBACK_SAMPLES = ("中午吃了米饭和炒青菜", "早餐吃了面包和牛奶")


def _parsed(text: str) -> ParsedMeal:
    foods = []
    for entry in match_foods(text):
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        resolved = resolve_in_context(text, entry)
        foods.append(
            ParsedFood(
                name=name,
                nature=resolved.nature,
                flavors=resolved.flavors,
                verification=resolved.verification,
            )
        )
    return ParsedMeal(
        foods=foods,
        meal_time=guess_meal_time(text),
        overall_nature=_match_nature_from_text(text),
        confidence=0.9 if foods else 0.3,
    )


def _recommend(text: str):
    return fallback_recommend(_parsed(text), Constitution.BALANCED)


def test_samples_really_hit_the_fallback():
    """前置：这两条样本确实走 late_night 兜底 —— 否则下面的断言是空跑。"""
    hits = sum(
        1
        for t in FALLBACK_SAMPLES
        if (r := _pick_rule(_parsed(t))) and r["id"] == "late_night"
    )
    assert hits >= 1, "样本不再命中 late_night 兜底（判据或数据变了），本文件该更新"


@pytest.mark.parametrize("text", FALLBACK_SAMPLES)
def test_fallback_wording_has_no_time_claim(text):
    recs, _, hits = _recommend(text)
    assert recs, "兜底必须给得出搭配"
    blob = recs[0].fit_reason + "".join(hits)
    assert not any(w in blob for w in TIME_WORDS), f"兜底叙述又提时间了：{blob}"


def test_fallback_still_gives_the_same_blend():
    """只改文案 —— 搭配与判据一点都不许动。"""
    recs, _, _ = _recommend(FALLBACK_SAMPLES[0])
    assert {h.name for h in recs[0].herbs} == {"陈皮", "茯苓"}


def test_real_late_night_meal_still_gets_a_conclusion():
    """别为了去掉「夜里」把真正的夜宵场景也一起弄丢。"""
    recs, _, hits = _recommend("宵夜吃了烧烤")
    assert recs and recs[0].herbs, "夜宵样本必须有推荐"
    assert hits, "夜宵样本应有规则命中留痕"


def test_guard_catches_a_time_wording_regression(monkeypatch):
    """变异检验：把文案改回含「夜里」，上面的判据必须抓得到 —— 否则它是恒真的。"""
    rule = next(r for r in RULES if r["id"] == "late_night")
    monkeypatch.setitem(rule, "reason", "夜里吃得多，偏于理气和胃的温性搭配更稳妥，量宜少。")
    recs, _, hits = _recommend(FALLBACK_SAMPLES[0])
    blob = recs[0].fit_reason + "".join(hits)
    assert any(w in blob for w in TIME_WORDS), "文案改回含「夜里」却没被抓到 ⇒ 判据恒真"
