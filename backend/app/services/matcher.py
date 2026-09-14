"""规则匹配：Agent2 失败时的确定性兜底，也为 Agent2 提供候选收敛。

这一层的价值是把"模型不可用"从故障变成降级：用户拿到的仍是合法、安全、
不超剂量的搭配，只是措辞没有模型写得细。
"""

from __future__ import annotations

import logging

from app.domain.enums import Constitution, Nature
from app.domain.models import (
    Basis,
    BrewGuide,
    HerbInBlend,
    ParsedMeal,
    Recommendation,
)
from app.domain.safety import herb_by_name

logger = logging.getLogger(__name__)

# 场景 → 首选搭配（饮片名 + 克数）
RULES: list[dict] = [
    {
        "id": "greasy",
        "label": "油腻餐后偏消食",
        "priority": 3,
        "match_natures": {Nature.WARM, Nature.HOT},
        "keywords": ("麻辣", "炸", "烤", "烧烤", "油", "红烧", "火锅", "肉", "肥", "奶油"),
        "blend": [("陈皮", 5), ("山楂", 6)],
        "title": "陈皮山楂消食饮",
        "reason": "这餐偏油腻，陈皮与山楂偏于理气消食，餐后温饮较合适。",
    },
    {
        "id": "cold_intake",
        "label": "生冷之后偏温中",
        "priority": 2,
        "match_natures": {Nature.COLD, Nature.COOL},
        "keywords": ("冰", "冷", "凉", "雪糕", "冰淇淋", "生鱼", "刺身", "沙拉", "冷饮"),
        "blend": [("生姜", 5), ("红枣", 6)],
        "title": "生姜红枣温中饮",
        "reason": "这餐偏生冷，生姜与红枣偏温，适合暖一暖胃。",
    },
    {
        "id": "spicy",
        "label": "辛辣燥热偏生津",
        "priority": 2,
        "match_natures": {Nature.HOT},
        "keywords": ("辣", "麻辣", "椒", "烧烤", "孜然"),
        "blend": [("麦冬", 6), ("罗汉果", 3)],
        "title": "麦冬罗汉果润喉饮",
        "reason": "这餐辛辣偏燥，麦冬与罗汉果偏于生津润喉。",
    },
    {
        "id": "sweet_heavy",
        "label": "甜腻餐后偏化湿",
        "priority": 2,
        "match_natures": {Nature.NEUTRAL, Nature.WARM},
        "keywords": ("蛋糕", "奶茶", "甜", "糖", "巧克力", "冰淇淋", "奶"),
        "blend": [("茯苓", 6), ("陈皮", 4)],
        "title": "茯苓陈皮化湿饮",
        "reason": "这餐偏甜腻，茯苓与陈皮偏于健脾化湿，适合痰湿或湿热体质。",
    },
    {
        "id": "late_night",
        "label": "夜宵偏和胃安神",
        "priority": 1,
        "match_natures": {Nature.UNKNOWN},
        "keywords": (),
        "blend": [("陈皮", 4), ("茯苓", 6)],
        "title": "陈皮茯苓和胃饮",
        "reason": "夜里吃得多，偏于理气和胃的温性搭配更稳妥，量宜少。",
    },
]

# 体质 → 首选搭配（无场景匹配时使用）
CONSTITUTION_DEFAULT: dict[str, tuple[list[tuple[str, float]], str, str]] = {
    Constitution.BALANCED.value: (
        [("枸杞子", 8), ("菊花", 4)],
        "枸杞菊花清润饮",
        "平和体质随餐调整即可，这组偏清润平和。",
    ),
    Constitution.QI_DEFICIENCY.value: (
        [("红枣", 8), ("枸杞子", 8)],
        "红枣枸杞益气饮",
        "气虚方向偏于健脾益气，温平为主。",
    ),
    Constitution.YANG_DEFICIENCY.value: (
        [("生姜", 4), ("红枣", 8)],
        "生姜红枣温阳饮",
        "阳虚方向偏温，避开寒凉饮片。",
    ),
    Constitution.PHLEGM_DAMP.value: (
        [("茯苓", 8), ("陈皮", 5)],
        "茯苓陈皮化湿饮",
        "痰湿方向偏于健脾利湿，少用甜腻补品。",
    ),
    Constitution.DAMP_HEAT.value: (
        [("菊花", 4), ("荷叶", 5)],
        "菊花荷叶清利饮",
        "湿热方向偏于清热利湿，避开温燥补品。",
    ),
}

DEFAULT_BREW = BrewGuide(
    vessel="保温杯",
    water_ml=400,
    water_temp_c=95,
    steps=[
        "饮片用温水快速冲洗一遍，去浮尘",
        "放入杯中，冲入 95℃ 热水",
        "加盖焖 6–8 分钟",
        "温饮，可续水 1 次",
    ],
    steep_min=8,
    refill_times=1,
)


def _pick_rule(parsed: ParsedMeal) -> dict | None:
    """按关键词与寒热打分选一条规则。"""
    text = " ".join(
        [f.name for f in parsed.foods] + [f.note or "" for f in parsed.foods]
    )

    # 打分相同时用 priority 决定优先级（消食 > 温中/生津/化湿 > 和胃）
    best: tuple[tuple[int, int], dict] | None = None
    for rule in RULES:
        score = 0
        for kw in rule["keywords"]:
            if kw in text:
                score += 2
        if parsed.overall_nature in rule["match_natures"]:
            score += 1
        if not score:
            continue
        key = (score, rule.get("priority", 0))
        if best is None or key > best[0]:
            best = (key, rule)
    return best[1] if best else None


def _make_herbs(blend: list[tuple[str, float]]) -> list[HerbInBlend]:
    catalog = herb_by_name()
    herbs: list[HerbInBlend] = []
    for name, amount in blend:
        entry = catalog.get(name)
        if not entry:
            logger.warning("规则兜底引用了不在白名单的饮片：%s", name)
            continue
        herbs.append(
            HerbInBlend(
                name=name,
                amount_g=amount,
                nature=entry.get("nature", Nature.UNKNOWN),
                flavors=entry.get("flavors", []),
                meridians=entry.get("meridians", []),
                role=(entry.get("effects") or [""])[0],
            )
        )
    return herbs


def fallback_recommend(
    parsed: ParsedMeal,
    constitution: Constitution,
    exclude_herbs: list[str] | None = None,
) -> tuple[list[Recommendation], str, list[str]]:
    """确定性兜底推荐。

    返回 (推荐列表, user_message, rule_hits)。
    """
    exclude = set(exclude_herbs or [])
    rule = _pick_rule(parsed)

    if rule:
        blend, title, reason = rule["blend"], rule["title"], rule["reason"]
        hits = [rule["id"], rule["label"]]
    else:
        blend, title, reason = CONSTITUTION_DEFAULT[constitution.value]
        hits = ["constitution_default", constitution.value]

    blend = [(name, amount) for name, amount in blend if name not in exclude]
    if not blend:
        return [], "你排除的饮片正好是这组搭配的全部，换一组或去掉排除项再试试。", hits

    herbs = _make_herbs(blend)
    if not herbs:
        return [], "候选饮片不可用，请检查 herbs.json。", hits

    cautions: list[str] = []
    catalog = herb_by_name()
    for herb in herbs:
        entry = catalog.get(herb.name) or {}
        cautions.extend(entry.get("cautions", [])[:1])
        if constitution.value in (entry.get("unsuitable_for") or []):
            cautions.append(f"{herb.name} 与你当前体质方向不完全契合，建议减量")

    rec = Recommendation(
        title=title,
        herbs=herbs,
        brew=DEFAULT_BREW,
        fit_reason=f"{reason}（此建议来自规则匹配）",
        cautions=cautions[:3],
        score=0.6,
    )
    return [rec], "这次用的是简化匹配，搭配安全但说明比较简略。", hits


def build_basis(
    constitution: Constitution,
    constitution_label: str,
    rule_hits: list[str] | None = None,
    guardrail_applied: list[str] | None = None,
) -> Basis:
    return Basis(
        constitution=constitution,
        constitution_label=constitution_label,
        rule_hits=rule_hits or [],
        guardrail_applied=guardrail_applied or [],
    )
