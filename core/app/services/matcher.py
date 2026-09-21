"""规则匹配：Agent2 失败时的确定性兜底，也为 Agent2 提供候选收敛。

这一层的价值是把"模型不可用"从故障变成降级：用户拿到的仍是合法、安全、
不超剂量的搭配，只是措辞没有模型写得细。
"""

from __future__ import annotations

import logging
from typing import Sequence

from app.domain.enums import CONSTITUTION_LABELS, Constitution, Nature
from app.domain.diet_signals import derive_meal_plan, load_meal_plan_rules
from app.domain.models import (
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
        "id": "late_night",
        # ⚠️ 名字叫 late_night，但它**不是夜宵规则**：keywords 是空元组、只靠
        # `match_natures={UNKNOWN}` 拿分 ⇒ 实际是「没判出任何场景」的**兜底**。
        # 所以 label 与 reason 一律不许提「夜里/夜宵」—— 实测中午「米饭炒青菜」、
        # 早餐「面包牛奶」都会走到这里（D31）。
        "label": "未判出偏向·和胃安神",
        "priority": 1,
        "match_natures": {Nature.UNKNOWN},
        "keywords": (),
        "blend": [("陈皮", 4), ("茯苓", 6)],
        "title": "陈皮茯苓和胃饮",
        "reason": "这一餐没判出明显的寒热偏向，先用偏于理气和胃的温性搭配，量宜少。",
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
# 不标须煎煮的饮片行为完全不变。
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
#   · RULES.late_night（陈皮 4 + 茯苓 6）：「和胃安神」依赖茯苓的宁心，
#     白名单内没有不必煎煮的等价物。
#
# 2026-09-20：`RULES.sweet_heavy`（茯苓 6 + 陈皮 4）已由**湿气轴接管**并移除（D25）。
# 湿气度 ≥2 时走 `meal_plan_rules.json` 的化湿方向，可用饮片 = 方向子集 ∩ 候选集，
# 不再是一条写死的搭配——既消除两套化湿逻辑，也让化湿方向过体质
# （原先的 `sweet_heavy` 与 RULES 其它规则一样完全不过体质）。
#
# 「模型自选」这条路不受本条约束（模型是自由选料的），由 `check_brew_adequacy`
# 在护栏层兜住 —— 这正是方案 C「两条都做」的第二条。


def _meal_text(parsed: ParsedMeal) -> str:
    """规则关键词的匹配面：条目名 + note。"""
    return " ".join(
        [f.name for f in parsed.foods] + [f.note or "" for f in parsed.foods]
    )


def _pick_rule(parsed: ParsedMeal, *, allowed_ids: set[str] | None = None) -> dict | None:
    """按关键词与寒热打分选一条规则。

    `allowed_ids`：只在这些 id 里选（阶段 2 的 L1「不对冲」用它排除对冲型规则）。
    **既有调用方不传** ⇒ 行为逐字节不变。
    """
    text = _meal_text(parsed)

    # 打分相同时用 priority 决定优先级（消食 > 温中/生津/化湿 > 和胃）
    best: tuple[tuple[int, int], dict] | None = None
    for rule in RULES:
        if allowed_ids is not None and rule["id"] not in allowed_ids:
            continue
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


# ============================================================
# 阶段 2：推荐优先级链（L0–L4）
# ============================================================
# 为什么要在 `_pick_rule` **之上**再叠一层，而不是改它内部：
# `_pick_rule` 只认 keywords + overall_nature，**完全不读 `parsed.signals`** ⇒
# 阶段 1 改了提示词口径（不对冲）之后，没 Key 的用户走的还是被否掉的旧口径
# ——同一个用户「有 Key / 没 Key」拿到相反的推荐方向，是 E4 的同形。
#
# 优先级（口径⑧/⑨）：
#   L0 signals 缺失        ⇒ 完全走老路（既有测试与既有行为逐字节不变）
#   L1 寒热错杂            ⇒ 排除「对冲型」规则；没有可保留的 ⇒ 退体质默认
#   L2/L3 方向接管         ⇒ 用 方向子集 ∩ 候选集 的饮片（护脾胃 → 化湿）
#   L4 触发了但方向不可用  ⇒ 湿气方向：退体质默认（sweet_heavy 已删，老路只剩 late_night 误命中）
#                            其余：走老路 + 如实说明（Q3 α：仍给搭配，不静默替换）
COLD_NATURES = {Nature.COLD, Nature.COOL}
WARM_NATURES = {Nature.WARM, Nature.HOT}


def _blend_natures(rule: dict) -> list[Nature]:
    """规则搭配里每味的四气。取不到就记 unknown ⇒ 不会被判成对冲。"""
    catalog = herb_by_name()
    out: list[Nature] = []
    for name, _amount in rule["blend"]:
        entry = catalog.get(name) or {}
        try:
            out.append(Nature(entry.get("nature")))
        except ValueError:
            out.append(Nature.UNKNOWN)
    return out


def _is_counter_rule(rule: dict, heat_side: list[str], cold_side: list[str]) -> bool:
    """这一条规则是不是在「对冲」。

    判据：搭配**整体**偏一侧，而这一餐的**对侧**非空 ⇒ 它是拿偏性去找平。
    例如「麻辣烫+冰可乐」heat=麻辣烫 ⇒ 「麦冬+罗汉果」（皆凉）是对冲；
    「陈皮+山楂」（皆温）对 cold=可乐 也是对冲。混合寒热的搭配不算。
    """
    natures = _blend_natures(rule)
    if not natures:
        return False
    all_cold = all(n in COLD_NATURES for n in natures)
    all_warm = all(n in WARM_NATURES for n in natures)
    return (all_cold and bool(heat_side)) or (all_warm and bool(cold_side))


def _scene_rule_ids(parsed: ParsedMeal, conflict: object) -> set[str]:
    """冲突餐可用的场景规则 id：**有关键词命中**且**非对冲**。

    要求关键词命中这一条是实测逼出来的（`probe_stage2c` §E/F）：
    `late_night` 的 keywords 是空元组，只靠 `match_natures={UNKNOWN}` 拿 1 分就能赢。
    不设这条门槛，冲突餐会退到这条兜底规则，给用户一句「夜里吃得多」
    的错误时间叙述——兜底规则不是场景结论（**D31**：该叙述已改为不提时间）。
    """
    text = _meal_text(parsed)
    heat_side = list(getattr(conflict, "heat_side", None) or [])
    cold_side = list(getattr(conflict, "cold_side", None) or [])
    return {
        rule["id"]
        for rule in RULES
        if any(kw in text for kw in rule["keywords"])
        and not _is_counter_rule(rule, heat_side, cold_side)
    }


def _scene_rule(parsed: ParsedMeal, conflict: object | None) -> dict | None:
    """老路里**有关键词命中**的最佳规则；没有就返回 None（late_night 这类兜底不算）。"""
    allowed = _scene_rule_ids(parsed, conflict)
    return _pick_rule(parsed, allowed_ids=allowed) if allowed else None


def _overrides_scene(direction_id: str) -> bool:
    """这个方向能不能压过场景规则。判据在数据文件里（护脾胃＝能，化湿＝不能）。"""
    direction = (load_meal_plan_rules().get("directions") or {}).get(direction_id) or {}
    return bool(direction.get("overrides_scene"))


def _from_stage(
    stage: object, plan_note: str
) -> tuple[list[tuple[str, float]], str, str, list[str], str, str]:
    blend = [(name, float(stage.amounts.get(name, 0))) for name in stage.herbs]
    return (
        blend,
        stage.title,
        stage.reason,
        [f"direction_{stage.direction}", stage.label],
        "",
        plan_note,
    )


def _trigger_min(key: str) -> int:
    """阈值从数据文件读，本文件不写死 2。"""
    return int((load_meal_plan_rules().get("trigger") or {}).get(key) or 0)


def _choose_blend(
    parsed: ParsedMeal,
    constitution: Constitution,
    *,
    avoid: Sequence[str],
) -> tuple[list[tuple[str, float]], str, str, list[str], str, str]:
    """选出本次用哪一组搭配。返回 (blend, title, reason, hits, fallback_note, plan_note)。

    抽出这一层后，`fallback_recommend` 后面的 `_make_herbs` / `blend_needs_cooking` /
    cautions / 兼体质硬剔除 **完全不动** ⇒ 煎煮、用量、护栏自动复用新分支。
    """
    signals = getattr(parsed, "signals", None)

    # ---- 老路（L0）：没有 signals 就逐字节保持原行为 ----
    def legacy() -> tuple[list[tuple[str, float]], str, str, list[str], str]:
        rule = _pick_rule(parsed)
        if rule:
            return rule["blend"], rule["title"], rule["reason"], [rule["id"], rule["label"]], ""
        blend, title, reason, note = _constitution_default(constitution)
        hits = ["constitution_default", constitution.value]
        if note:
            hits = ["constitution_default_missing", constitution.value]
        return blend, title, reason, hits, note

    if signals is None:
        blend, title, reason, hits, note = legacy()
        return blend, title, reason, hits, note, ""

    plan = derive_meal_plan(
        signals, constitution.value, avoid=avoid
    )
    if plan is None:
        # 一项都没触发 ⇒ 没有方向接管，老路照走
        blend, title, reason, hits, note = legacy()
        return blend, title, reason, hits, note, ""

    stage = plan.first if (plan.first is not None and plan.first.open) else None
    conflict = signals.conflict

    # ---- L1：寒热错杂 ⇒ 不对冲（口径⑨，先于一切方向）----
    # 例外：护脾胃方向 overrides_scene=true 时它本身就是「护脾胃、平和」，先给它。
    if stage is not None and _overrides_scene(stage.direction):
        return _from_stage(stage, plan.note)

    if conflict is not None and conflict.conflict:
        allowed = _scene_rule_ids(parsed, conflict)
        rule = _pick_rule(parsed, allowed_ids=allowed) if allowed else None
        if rule is not None:
            return (
                rule["blend"],
                rule["title"],
                rule["reason"],
                [rule["id"], rule["label"]],
                "",
                plan.note,
            )
        # 没有非对冲的场景结论 ⇒ 退体质默认，不再用「夜宵和胃」这类兜底顶上
        blend, title, reason, note = _constitution_default(constitution)
        return (
            blend,
            title,
            reason,
            ["constitution_default", constitution.value, "conflict_no_counter"],
            note,
            plan.note,
        )

    # ---- 老路的场景结论：要求**关键词命中** ----
    # （late_night 的 keywords 是空元组，只靠 match_natures={UNKNOWN} 拿分，
    #   它不是场景结论，不能拿来压住方向）
    scene = _scene_rule(parsed, conflict)
    if scene is not None:
        return (
            scene["blend"],
            scene["title"],
            scene["reason"],
            [scene["id"], scene["label"]],
            "",
            plan.note,
        )

    # ---- L3：湿气方向接管（取代 sweet_heavy 的位置）----
    if stage is not None:
        return _from_stage(stage, plan.note)

    # ---- L4：湿气触发但方向不可用 ⇒ 退体质默认，不走 late_night 兜底 ----
    damp_hit = bool(
        signals.dampness and signals.dampness.score >= _trigger_min("dampness_min")
    )
    if damp_hit:
        blend, title, reason, note = _constitution_default(constitution)
        return (
            blend,
            title,
            reason,
            ["constitution_default", constitution.value, "damp_clear_closed"],
            note,
            plan.note,
        )

    # 其余（冲击度触发而护脾胃暂未开放）：走老路，但如实说明（Q3 α）
    blend, title, reason, hits, note = legacy()
    if plan.note:
        hits = [*hits, "stomach_guard_closed"]
    return blend, title, reason, hits, note, plan.note


def _herbs_unsuitable_for_any(constitutions: set[str]) -> set[str]:
    """把**任一**给定体质标进 `unsuitable_for` 的饮片名集合（B2 兼体质屏蔽集）。

    与 LLM 路径 `filter_by_constitution(avoid=...)` 用的是**同一份判据**
    （`unsuitable_for`）——两条路径对屏蔽集的结论必须一致，
    否则同一个兼体质用户「有 Key / 没 Key」会拿到不同的安全边界。
    这条一致性由 `tests/test_constitution_integration.py` 钉死。
    """
    if not constitutions:
        return set()
    catalog = herb_by_name()
    blocked: set[str] = set()
    for key, entry in catalog.items():
        unsuitable = {str(x) for x in (entry.get("unsuitable_for") or [])}
        if unsuitable & constitutions:
            blocked.add(str(entry.get("name") or key))
    return blocked


def fallback_recommend(
    parsed: ParsedMeal,
    constitution: Constitution,
    exclude_herbs: list[str] | None = None,
    *,
    avoid: Sequence[str] = (),
) -> tuple[list[Recommendation], str, list[str]]:
    """确定性兜底推荐。

    返回 (推荐列表, user_message, rule_hits)。

    `avoid`：兼体质屏蔽集（B2 接入，D6-A′ **硬剔除**）。命中的饮片直接从搭配里去掉，
    与 LLM 路径的候选集过滤保持一致 —— 不是追加一句提示就完事。
    ⚠️ 过滤必须放在 **blend 确定之后**：`_pick_rule` 命中的场景搭配**完全不经过体质**，
    塞进 `_constitution_default` 里会漏掉整个 rule 分支。
    默认空 ⇒ 既有行为不变。
    """
    exclude = set(exclude_herbs or [])
    blocked_by_avoid = _herbs_unsuitable_for_any({str(a) for a in avoid})
    blend, title, reason, hits, fallback_note, plan_note = _choose_blend(
        parsed, constitution, avoid=avoid
    )

    blend = [(name, amount) for name, amount in blend if name not in exclude]
    if not blend:
        return [], "你排除的饮片正好是这组搭配的全部，换一组或去掉排除项再试试。", hits

    if blocked_by_avoid:
        kept = [(name, amount) for name, amount in blend if name not in blocked_by_avoid]
        if not kept:
            # 硬剔除把整组剔空了 ⇒ 退通用兜底。契约是「永远给出合法且安全的搭配」，
            # 不能返回空推荐，也不能把剔空的原因藏起来。
            generic = CONSTITUTION_DEFAULT.get(GENERIC_FALLBACK_KEY)
            g_kept: list[tuple[str, float]] = []
            if generic:
                g_blend = generic[0]
                g_kept = [
                    (name, amount)
                    for name, amount in g_blend
                    if name not in exclude and name not in blocked_by_avoid
                ]
            if not g_kept:
                return [], "按你的体质（含兼夹体质）筛下来没有可用饮片，请换个说法或咨询医师。", hits
            blend = g_kept
            title, reason = generic[1], generic[2]
            fallback_note = "原搭配对兼夹体质不宜，已改用平和质的通用搭配"
            hits = [*hits, "avoid_cleared_blend"]
        else:
            blend = kept

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

    # 通用兜底时把原因写进理由，别让用户以为这是为他体质配的；
    # plan_note（方向关闭／寒热错杂）同样如实写进来——不打出来就是只留痕在数据里。
    reason_suffix = "（此建议来自规则匹配）"
    notes = [n for n in (fallback_note, plan_note) if n]
    if notes:
        reason_suffix = f"（此建议来自规则匹配；{'；'.join(notes)}）"

    rec = Recommendation(
        title=title,
        herbs=herbs,
        brew=brew,
        fit_reason=f"{reason}{reason_suffix}",
        cautions=cautions[:3],
        score=0.6,
    )
    return [rec], "这次用的是简化匹配，搭配安全但说明比较简略。", hits
