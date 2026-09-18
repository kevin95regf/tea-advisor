"""确定性安全护栏。模型会飘，护栏不能飘。

原则：任何面向用户的推荐，都必须先过这里，再由接口层返回。
所有硬约束（白名单、剂量、禁用表述、高风险人群）都在本文件。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from app.config import get_settings

# ============================================================
# 常量
# ============================================================
# 高风险人群关键词：命中即不给出具体推荐，改为引导咨询医师
HIGH_RISK_KEYWORDS: tuple[str, ...] = (
    "怀孕", "孕妇", "备孕", "哺乳", "喂奶", "经期", "月经",
    "小孩", "孩子", "儿童", "婴儿", "宝宝", "幼儿",
    "化疗", "手术", "糖尿病", "高血压", "心脏病", "肾病", "肝病",
    "吃药", "服药", "中药", "西药", "过敏",
)

# 绝对禁止出现在输出里的表述
FORBIDDEN_PHRASES: tuple[str, ...] = (
    "治疗", "治愈", "根治", "药到病除", "主治", "疗效",
    "疗程", "处方", "代替吃药", "停药", "包好",
    "确诊", "癌症", "肿瘤", "药方",
)

# 单味饮片日用量硬上限（克）。与 herbs.json 取较小值。
HARD_DOSE_CEILING_G: float = 30.0

# 单次搭配总用量上限（克/日）。超过就显得像方剂，不是茶饮。
TOTAL_DOSE_CEILING_G: float = 45.0

# 单次搭配最多味数（避免"君臣佐使"式处方结构）
MAX_HERBS_PER_BLEND: int = 4


# ============================================================
# 数据结构
# ============================================================
@dataclass(frozen=True)
class GuardrailResult:
    """护栏检查结果。

    blocked  : 致命问题，必须拦截或降级
    warnings : 需要提示用户的注意项
    adjusted : 被自动裁剪的项，用于前端标注
    """

    ok: bool = True
    blocked: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    adjusted: list[str] = field(default_factory=list)


class MissingConstitutionDataError(ValueError):
    """herbs.json 里没有任何饮片标注该体质。

    出现这种情况几乎总是意味着「枚举加了新体质，但 herbs.json 的
    suitable_constitutions 没跟上」。

    这时**必须显式失败**，不能静默降级：
    `filter_by_constitution` 的职责是把候选集收敛到与该体质方向相符的饮片。
    如果一条数据都没有就退化成"目录前 N 味"，模型会拿这份未经筛选的清单去配，
    可能给出方向相反的搭配（例如阴虚质拿到龙眼肉、生姜等温补辛温之品）——
    而这种错误从输出的表面**完全看不出来**，比直接报错危险得多。
    """


# ============================================================
# 数据加载
# ============================================================
@lru_cache(maxsize=1)
def load_herb_catalog() -> dict[str, dict]:
    """加载饮片白名单。key 为饮片 id。文件不存在时返回空字典，不抛异常。"""
    path: Path = get_settings().data_dir / "herbs.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {item["id"]: item for item in raw.get("herbs", [])}


def reload_herb_catalog() -> dict[str, dict]:
    """清缓存后重新加载（改了 herbs.json 之后调用）。"""
    load_herb_catalog.cache_clear()
    return load_herb_catalog()


def herb_whitelist_names() -> set[str]:
    """白名单里的饮片中文名集合。Agent 2 的候选集必须来自这里。"""
    return {item["name"] for item in load_herb_catalog().values()}


def herb_by_name() -> dict[str, dict]:
    return {item["name"]: item for item in load_herb_catalog().values()}


# ============================================================
# 检查函数
# ============================================================
def detect_high_risk(text: str) -> list[str]:
    """从用户原始文本里识别高风险人群关键词。"""
    return [kw for kw in HIGH_RISK_KEYWORDS if kw in text]


def contains_forbidden_phrase(text: str) -> list[str]:
    """检测文本中是否出现禁用表述。"""
    return [p for p in FORBIDDEN_PHRASES if p in text]


def scan_free_text(text: str) -> GuardrailResult:
    """扫描任意自由文本，拦截禁用表述。用于 Agent2 的 fit_reason / cautions。"""
    hits = contains_forbidden_phrase(text)
    if not hits:
        return GuardrailResult()
    return GuardrailResult(
        ok=False,
        blocked=[f"检测到禁用表述：{h}" for h in hits],
    )


def check_blend(
    herbs: list[dict],
    exclude_herbs: list[str] | None = None,
) -> GuardrailResult:
    """校验一组饮片搭配。

    herbs 每项至少包含 name 与 amount_g 字段。
    返回的 blocked 非空表示这组搭配不可直接使用。

    调用方约定：不要静默丢弃 blocked 内容，要么剔除对应饮片后重算，
    要么整条推荐作废并走规则兜底——绝不能把被拦的内容照原样返回给用户。
    """
    blocked: list[str] = []
    warnings: list[str] = []
    adjusted: list[str] = []

    catalog = herb_by_name()
    exclude = {name.strip() for name in (exclude_herbs or []) if name.strip()}

    # 1) 味数上限：超过就整组拒绝，避免像方剂
    if len(herbs) > MAX_HERBS_PER_BLEND:
        blocked.append(
            f"单次搭配 {len(herbs)} 味，超过 {MAX_HERBS_PER_BLEND} 味上限，"
            "已按药食同源茶饮简化处理"
        )

    total = 0.0
    for herb in herbs:
        name = str(herb.get("name", "")).strip()
        amount = float(herb.get("amount_g") or 0)

        # 2) 必须在白名单内
        if name not in catalog:
            blocked.append(f"{name or '(未命名)'}：不在药食同源白名单内，已移除")
            continue

        # 3) 用户手动排除
        if name in exclude:
            blocked.append(f"{name}：用户已排除，已移除")
            continue

        entry = catalog[name]

        # 4) 剂量上限：取 min(目录限量, 硬上限)
        ceiling = min(
            float(entry.get("max_daily_g") or HARD_DOSE_CEILING_G),
            HARD_DOSE_CEILING_G,
        )
        if amount > ceiling:
            warnings.append(f"{name}：{amount:g}g 超过建议上限，已调整为 {ceiling:g}g")
            amount = ceiling
            adjusted.append(name)

        total += amount

        # 5) 饮片自身禁忌逐条转成提示
        for caution in entry.get("cautions", []):
            warnings.append(f"{name}：{caution}")

    # 6) 总量上限
    if total > TOTAL_DOSE_CEILING_G:
        warnings.append(
            f"合计用量约 {total:g}g 偏多，建议控制在 {TOTAL_DOSE_CEILING_G:g}g 以内"
        )
        adjusted.append("总量")

    return GuardrailResult(
        ok=not blocked,
        blocked=blocked,
        warnings=warnings,
        adjusted=adjusted,
    )


def check_constitution_fit(
    herbs: list[dict],
    constitution: str,
) -> GuardrailResult:
    """检查搭配是否与用户体质方向冲突。

    规则简单但有效：饮片标记的不适宜人群命中体质时，给出警告并建议换料。
    """
    warnings: list[str] = []
    catalog = herb_by_name()
    for herb in herbs:
        name = str(herb.get("name", "")).strip()
        entry = catalog.get(name)
        if not entry:
            continue
        if constitution in (entry.get("unsuitable_for") or []):
            warnings.append(f"{name} 与你当前体质方向不完全契合，建议减量或更换")
    return GuardrailResult(ok=True, warnings=warnings)


# ============================================================
# 煎煮 / 焖泡（2026-09-18 落地，见 docs/agent2-9types-brew-plan.md）
# ============================================================
# 判定关键词。刻意**不含「熬」** —— 它会命中麦冬、桑椹的「适合熬夜后口干」，
# 把两味明显不必煎煮的饮片误判进来（第一版方案正是这么误报的）。
COOK_KEYWORDS: tuple[str, ...] = ("煮", "煎", "炖")

# 判定「这算煎煮方式」的下限。低于它就是焖泡，须煎煮的饮片出不了味。
COOK_BREW_MIN_STEEP_MIN: int = 20


def herb_requires_cooking(entry: dict) -> bool:
    """该饮片是否标记为「必须煎煮」。

    读的是**数据标记**而不是现场猜文本：标记与它的依据（`brewing.note` 原文）
    放在同一个对象里，改的时候看得见理由。这也让「百合」这类新增判定
    不必去改代码常量 —— 常量与数据必然漂移，漂移方向总是「数据改了、常量没改」。
    """
    brewing = entry.get("brewing") or {}
    return bool(brewing.get("requires_cooking"))


def cook_required_without_basis(catalog: dict[str, dict]) -> list[str]:
    """纯函数：标记了 `requires_cooking` 却在自身处理要点里找不到「煮/煎/炖」依据的条目。

    派生不变式用 —— 标记不能凭空出现，必须能在自己的 `brewing` 文本里读到依据。
    返回按 id 排序的列表，空列表代表没有这类问题。
    """
    bad: list[str] = []
    for herb_id, entry in catalog.items():
        if not herb_requires_cooking(entry):
            continue
        brewing = entry.get("brewing") or {}
        text = "".join(
            str(brewing.get(k) or "") for k in ("form", "note", "prep")
        )
        if not any(k in text for k in COOK_KEYWORDS):
            bad.append(herb_id)
    return sorted(bad)


def blend_needs_cooking(names: list[str]) -> list[str]:
    """搭配里需要煎煮的饮片名（按传入顺序，去重）。

    经 `herb_by_name()` 查目录，未知名字直接跳过（不报错）：
    调用点在兜底与护栏路径上，这两处的契约都是「永远给出结果」。
    """
    catalog = herb_by_name()
    out: list[str] = []
    for name in names:
        entry = catalog.get(name)
        if entry and herb_requires_cooking(entry) and name not in out:
            out.append(name)
    return out


def _brew_get(brew: object, key: str, default: object = None) -> object:
    """从 BrewGuide 或等价 dict 里取值（护栏要能同时吃两种形状）。"""
    if isinstance(brew, dict):
        return brew.get(key, default)
    return getattr(brew, key, default)


def brew_is_cook_style(brew: object) -> bool:
    """这组冲泡说明是否是「煎煮」而不是「焖泡」。

    三条同时满足才算：水温到 100、焖煮不少于 20 分钟、器具有煮的条件。
    只看时长不看器具会漏判「保温杯焖 30 分钟」——那依然出不了味。
    """
    vessel = str(_brew_get(brew, "vessel", "") or "")
    steep = _brew_get(brew, "steep_min", 0) or 0
    temp = _brew_get(brew, "water_temp_c", 0) or 0
    try:
        steep_ok = float(steep) >= COOK_BREW_MIN_STEEP_MIN
        temp_ok = float(temp) >= 100
    except (TypeError, ValueError):
        return False
    return steep_ok and temp_ok and ("壶" in vessel or "锅" in vessel)


def check_brew_adequacy(herbs: list[dict], brew: object) -> GuardrailResult:
    """搭配里有须煎煮的饮片、而冲泡方式仍是焖泡时，给出改法。

    调用方约定（与 `check_blend` 的剂量处理同构）：**自动换用煎煮方式，
    并把 `warnings` 记进 `guardrail_applied`** —— 项目原则是「不静默改写」，
    不是「不许改写」。换法必须留痕，用户与事后归因都看得见。

    这里只负责*发现*与*措辞*，换哪一份冲泡说明由调用方决定（orchestrator 用
    `matcher.COOK_BREW`）—— 否则 safety 就要反向依赖 matcher，形成循环导入。
    """
    names = blend_needs_cooking([str(h.get("name", "")).strip() for h in herbs])
    if not names:
        return GuardrailResult()
    if brew_is_cook_style(brew):
        return GuardrailResult()
    joined = "、".join(names)
    return GuardrailResult(
        warnings=[
            f"{joined}：须煎煮，保温杯焖泡出不了味，应改用养生壶或小锅煮 20–30 分钟"
        ]
    )


def filter_by_constitution(
    constitution: str,
    limit: int = 12,
) -> list[dict]:
    """按体质筛出候选饮片，供 Agent 2 在受限集合内选择。

    这是把"越界开方"风险锁死的结构性手段：
    模型即使想自由发挥，候选集里也只有药食同源饮片。

    不仅如此，它还负责**方向收敛**：把与该体质不符的饮片挡在候选集之外
    （靠 `unsuitable_for`）并把契合的排在前面（靠 `suitable_constitutions`）。

    如果该体质在数据里一条记录都没有，就**无法完成方向收敛**，
    此时抛 `MissingConstitutionDataError` 而不是退化成未筛选清单 ——
    详见该异常的说明。

    某体质何时算「数据备齐、可以对外」，判据由 `ready_constitutions()` 给出，
    两者用的是同一个条件。
    """
    catalog = load_herb_catalog()
    if not catalog:
        # 整个白名单缺失（herbs.json 没部署）。这是既有设计允许的降级路径
        # （load_herb_catalog 缺文件返回空字典），保持原行为，不在这里报错。
        return []

    suitable: list[dict] = []
    neutral_fallback: list[dict] = []

    for entry in catalog.values():
        unsuitable = entry.get("unsuitable_for") or []
        if constitution in unsuitable:
            continue
        if constitution in (entry.get("suitable_constitutions") or []):
            suitable.append(entry)
        else:
            neutral_fallback.append(entry)

    if not suitable:
        raise MissingConstitutionDataError(
            f"herbs.json 里没有任何饮片把「{constitution}」标进 suitable_constitutions，"
            "无法为该体质收敛候选集。请先补齐该体质的饮片标注（suitable/unsuitable），"
            "在补齐之前不要把这个体质暴露给用户。"
        )

    ordered = suitable + neutral_fallback
    return ordered[:limit]


def ready_constitutions() -> set[str]:
    """可对外服务的体质集合：至少有 1 味饮片把它标进 `suitable_constitutions`。

    为什么用「派生」而不是 `constitution.json` 里的一个手工开关：
    这个条件恰好是 `filter_by_constitution` 不抛 `MissingConstitutionDataError`
    的**充要条件**。手工 flag 会漂移——翻了开关却漏写数据，用户一点就是 500。
    派生的话「数据备齐」与「体质上线」是同一件事，没有开关可以忘记翻。

    新增体质的安全上线顺序因此是：先补 herbs.json，它自动出现在选项里；
    反之，枚举里有但数据没备齐的体质**不会被暴露**。
    """
    catalog = load_herb_catalog()
    if not catalog:
        # 整个白名单缺失（herbs.json 没部署）。这是既有设计允许的降级路径，
        # 但此时没有任何体质能给出有意义的收敛，一律视为未就绪。
        return set()

    ready: set[str] = set()
    for entry in catalog.values():
        for cid in entry.get("suitable_constitutions") or []:
            ready.add(str(cid))
    return ready
