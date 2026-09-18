"""规则匹配：Agent2 失败时的确定性兜底，也为 Agent2 提供候选收敛。

这一层的价值是把"模型不可用"从故障变成降级：用户拿到的仍是合法、安全、
不超剂量的搭配，只是措辞没有模型写得细。
"""

from __future__ import annotations

import logging

from app.domain.enums import CONSTITUTION_LABELS, Constitution, Nature
from app.domain.models import (
    Basis,
    BrewGuide,
    HerbInBlend,
    ParsedMeal,
    Recommendation,
)
from app.domain.safety import blend_needs_cooking, herb_by_name

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
    # 2026-09-18：本组原为「茯苓 8g + 陈皮 5g（茯苓陈皮化湿饮）」。
    # 茯苓须煮透才出味，而默认搭配走的是保温杯焖泡 → 按「默认搭配选择纪律」
    # （见本文件末尾注释）换成不必煎煮的等价搭配：陈皮理气健脾燥湿 + 荷叶清暑化湿，
    # 两味都在痰湿质的 suitable 段里。
    Constitution.PHLEGM_DAMP.value: (
        [("陈皮", 5), ("荷叶", 5)],
        "陈皮荷叶化湿饮",
        "痰湿方向偏于健脾利湿，少用甜腻补品。",
    ),
    Constitution.DAMP_HEAT.value: (
        [("菊花", 4), ("荷叶", 5)],
        "菊花荷叶清利饮",
        "湿热方向偏于清热利湿，避开温燥补品。",
    ),
    Constitution.YIN_DEFICIENCY.value: (
        [("枸杞子", 8), ("麦冬", 5)],
        "枸杞麦冬养阴饮",
        "阴虚方向偏于甘凉滋润，避开温燥辛温之品。",
    ),
    Constitution.BLOOD_STASIS.value: (
        [("山楂", 6), ("红枣", 8)],
        "山楂红枣活血饮",
        "血瘀方向偏于行气活血，少用涩滞收敛之物。",
    ),
    Constitution.QI_STAGNATION.value: (
        [("陈皮", 5), ("玫瑰花", 4)],
        "陈皮玫瑰理气饮",
        "气郁方向偏于理气解郁，避开酸涩收敛之物。",
    ),
    Constitution.SPECIAL_DIATHESIS.value: (
        [("山药", 10), ("红枣", 8)],
        "山药红枣平补饮",
        "特禀方向偏于平补固表，用量宜少而稳；个体过敏原优先。",
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

# ---- 煎煮路径（2026-09-18，见 docs/agent2-9types-brew-plan.md）----
# 含「须煎煮」饮片的搭配不能走保温杯焖泡：这类饮片质地坚实，焖泡出不了味
# （茯苓的数据原文就是「需先煎或久煮 10 分钟以上才易出味，直接冲泡效果差」）。
# 与 DEFAULT_BREW **并存**，由 `blend_needs_cooking` 决定用哪一份，不是全局替换——
# 不标须煎煮的 28 味行为完全不变。
COOK_BREW = BrewGuide(
    vessel="养生壶或小锅",
    water_ml=600,
    water_temp_c=100,
    steps=[
        "原料温水快速冲洗，质地坚硬的先浸泡 20 分钟",
        "放入壶中，加约 600 ml 清水煮开",
        "转小火煮 20–30 分钟，豆类与薏苡仁须彻底熟透",
        "温热饮用，当天喝完不留隔夜",
    ],
    steep_min=30,
    refill_times=0,
)

# ---- 默认搭配选择纪律（2026-09-18）----
# 默认搭配（CONSTITUTION_DEFAULT 与 RULES）**优先选不必煎煮的饮片**：
# 主路径仍是「保温杯焖泡」，不该因为一条默认推荐就要求用户备一口养生壶。
#
# 例外：该方向在候选集里找不到等价的非煎煮饮片时，**保留原味并走 COOK_BREW**
# （不是删掉它 —— 删了等于承认「这个产品给不出茯苓」）。目前三处例外：
#   · 特禀质默认（山药 10 + 红枣 8）：平补固表方向只有「红枣、山药」两味 suitable，
#     山药是其中唯一的平补味，没有替代。
#   · RULES.sweet_heavy（茯苓 6 + 陈皮 4）：茯苓在此承担渗湿，与陈皮燥湿是两层；
#     且它已由 CONSTITUTION_DEFAULT 的痰湿搭配改用陈皮荷叶 —— 两处同时换成同一组
#     会让「甜腻餐后」与「痰湿体质」给出完全一样的搭配，反而丢掉区分度。
#   · RULES.late_night（陈皮 4 + 茯苓 6）：「和胃安神」依赖茯苓的宁心，
#     白名单内没有不必煎煮的等价物。
#
# 「模型自选」这条路不受本条约束（模型是自由选料的），由 `check_brew_adequacy`
# 在护栏层兜住 —— 这正是方案 C「两条都做」的第二条。


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


# 体质默认搭配缺失时退到哪个体质。选平和质：
# 它的搭配是清润平和方向、不温不燥，对任何体质都不会造成方向性偏差。
GENERIC_FALLBACK_KEY = "balanced"


def _constitution_default(
    constitution: Constitution,
) -> tuple[list[tuple[str, float]], str, str, str]:
    """取该体质的默认搭配，返回 (blend, title, reason, 说明)。

    为什么不用 `CONSTITUTION_DEFAULT[constitution.value]` 直接查：
    这是"模型不可用"时的**最后一条兜底路径**，契约是"永远给出合法且安全的搭配"。
    字典直接查，遇到没收录的体质会抛 KeyError，顺着 orchestrator 冒出去变成 500 ——
    用户什么都拿不到，而这时他本来至少能拿到一份安全的通用搭配。

    所以缺数据时退到 `GENERIC_FALLBACK_KEY`，并返回一句说明写进理由，
    不能让用户误以为这是针对他体质配的。
    """
    entry = CONSTITUTION_DEFAULT.get(constitution.value)
    if entry is not None:
        blend, title, reason = entry
        return blend, title, reason, ""

    fallback = CONSTITUTION_DEFAULT.get(GENERIC_FALLBACK_KEY)
    if fallback is None:  # pragma: no cover - 数据表被改坏才会走到
        raise RuntimeError(
            f"体质「{constitution.value}」没有默认搭配，"
            f"通用兜底「{GENERIC_FALLBACK_KEY}」也缺失：请检查 CONSTITUTION_DEFAULT"
        )
    logger.warning(
        "体质 %s 没有默认搭配，退到 %s 的通用搭配", constitution.value, GENERIC_FALLBACK_KEY
    )
    blend, title, reason = fallback
    label = CONSTITUTION_LABELS.get(GENERIC_FALLBACK_KEY, GENERIC_FALLBACK_KEY)
    return blend, title, reason, f"该体质的专属搭配尚未收录，已改用{label}的通用搭配"


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
        fallback_note = ""
    else:
        blend, title, reason, fallback_note = _constitution_default(constitution)
        hits = ["constitution_default", constitution.value]
        if fallback_note:
            # 让 basis.rule_hits 也看得出用的是"通用兜底"，便于事后归因
            hits = ["constitution_default_missing", constitution.value]

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

    # 含须煎煮的饮片就换煎煮方式：保温杯焖泡出不了味（茯苓、百合等质地坚实）。
    # 换法记进 rule_hits —— 事后归因看得出这组为什么不是焖泡。
    cook_names = blend_needs_cooking([h.name for h in herbs])
    if cook_names:
        brew = COOK_BREW
        hits = [*hits, "brew_cook_required"]
    else:
        brew = DEFAULT_BREW

    # 通用兜底时把原因写进理由，别让用户以为这是为他体质配的
    reason_suffix = "（此建议来自规则匹配）"
    if fallback_note:
        reason_suffix = f"（此建议来自规则匹配；{fallback_note}）"

    rec = Recommendation(
        title=title,
        herbs=herbs,
        brew=brew,
        fit_reason=f"{reason}{reason_suffix}",
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
