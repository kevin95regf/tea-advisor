"""饮食信号的确定性识别与两维打分（阶段 0）。

定位
----
把「这一餐对脾胃冲击多大 / 会生成多少湿气」从模型自拍改成**可核对的确定性计算**。
阶段 0 只立纯函数与数据（零调用点、测透）；阶段 1 起新增 `build_meal_signals()`
作为三条链路（LLM／API 离线／终端离线）**共用**的装配入口。

三条纪律（都由实测踩出来的，见 core/var/stage0-plan-v2.md §4.1）
------------------------------------------------------------
1. **不裸扫原文**。单字「油」会命中「酱油」，「冰」会命中「冰淇淋」——
   项目自己在 food_lookup.py:622-625 记过这个坑。识别器只长在「解析后的条目名」上，
   词表按完整条目名枚举。
2. **名单写条目规范名，不写别名**。解析层已把 aliases 并入条目（_find_entry 第 2 级），
   名单再列一遍是死代码。
3. **unknown 不是 0**。四性判不出时不参与计分，也不给「平」的暗示。

维度参数（weights / aggregation / cap / levels）全部来自 core/data/diet_signals.json，
本文件不写死任何阈值。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence

from app.config import get_settings
from app.domain.enums import Nature
from app.domain.models import MealConflict, MealDimension, MealSignals, ParsedFood
from app.domain.nature_math import (
    CHILL_PREFIXES,
    detect_nature_conflict,
    detect_temperature_prefix,
    has_spicy_marker,
    trailing_temperature_prefix,
)

# 可核查性由强到弱。evidence_floor 取本次计分信号里**最弱**的一档：
# 只要有一次计分依赖弱档，整条结果就要能被标注。
EVIDENCE_ORDER: tuple[str, ...] = ("full", "partial", "clinical", "none")

# per-meal 信号（跨条目）的 subject 占位
MEAL_SUBJECT = "整餐"

DIMENSION_IMPACT = "impact"
DIMENSION_DAMPNESS = "dampness"


# ============================================================
# 数据结构
# ============================================================
@dataclass(frozen=True)
class SignalHit:
    """一条命中的原子信号。"""

    id: str
    label: str
    weight: int
    evidence: str
    arity: str  # "item" | "meal"
    subject: str  # 归属的条目名；per-meal 信号为 MEAL_SUBJECT


@dataclass(frozen=True)
class DimensionResult:
    """一个维度的打分结果。"""

    id: str
    score: int
    action: str
    hits: list[SignalHit] = field(default_factory=list)
    evidence_floor: str = "full"
    basis: str = ""
    note: str = ""


# ============================================================
# 数据加载
# ============================================================
@lru_cache(maxsize=1)
def load_diet_signals() -> dict[str, Any]:
    """加载信号与维度定义。

    沿 safety.load_* 的惯例：**文件不存在时返回空字典、不抛异常**。
    """
    path: Path = get_settings().data_dir / "diet_signals.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _food_index() -> dict[str, dict]:
    """名字／别名 → 表内条目。

    两个用途：①「名字自带温度前缀」时的准入校验（剥完剩下的词必须是条目）；
    ② 查类目字段（`ParsedFood` 上没有 category）。

    先注册全部规范名、再注册别名，保证别名不会盖掉同名条目。
    """
    path: Path = get_settings().data_dir / "food_properties.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    items: list[dict] = list(raw.get("foods") or [])
    items += list((raw.get("tea_drinks") or {}).get("items") or [])

    index: dict[str, dict] = {}
    for item in items:
        name = item.get("name")
        if name:
            index.setdefault(name, item)
    for item in items:
        for alias in item.get("aliases") or []:
            index.setdefault(alias, item)
    return index


def _signals_by_id() -> dict[str, dict]:
    return {s["id"]: s for s in (load_diet_signals().get("signals") or [])}


def _rule(sid: str) -> dict:
    sig = _signals_by_id().get(sid) or {}
    return sig.get("rule") or {}


def _entries(sid: str) -> set[str]:
    return set(_rule(sid).get("entries") or [])


def _categories(sid: str) -> set[str]:
    return set(_rule(sid).get("categories") or [])


# ============================================================
# 单条目判据
# ============================================================
def _nature_key(food: ParsedFood) -> str:
    """四性的字符串值。Pydantic 一般已转成 Nature，这里对 str 也兼容。"""
    nature = food.nature
    return nature.value if hasattr(nature, "value") else str(nature)


def _flavor_keys(food: ParsedFood) -> set[str]:
    keys: set[str] = set()
    for flavor in food.flavors or []:
        keys.add(flavor.value if hasattr(flavor, "value") else str(flavor))
    return keys


def _has_chill_prefix(name: str, index: dict[str, dict]) -> bool:
    """名字自带降温前缀，且剥掉前缀后剩下的词确实是表内条目。

    准入这一步是必须的：「冰淇淋」命中前缀「冰」、剩下「淇淋」不是条目 ⇒ 拒绝。
    （nature_math.detect_temperature_prefix 本身只识别、不做准入，准入是调用方的职责。）
    """
    detected = detect_temperature_prefix(name)
    if not detected:
        return False
    delta, _prefix, stripped = detected
    return delta < 0 and stripped in index


def _is_iced(text: str, name: str, index: dict[str, dict]) -> bool:
    """两条通道合取「这一条是冰镇的」。

    ① **位置语义**（E15 的结论）：温度词只有紧贴本条目命中词之前，才算在它头上。
       「炸鸡 冰可乐」里的「冰」属于可乐，不属于炸鸡。
    ② **名字自带前缀**：模型/解析层可能直接给出「冰可乐」这样的名字，此时原文里找不到
       完整词，只能从名字本身判，但必须过准入。
    """
    if text:
        idx = text.find(name)
        if idx > 0:
            prefix = trailing_temperature_prefix(text[:idx])
            if prefix and prefix in CHILL_PREFIXES:
                return True
    return _has_chill_prefix(name, index)


def _is_spicy(food: ParsedFood, name: str, canonical: str, category: str | None) -> bool:
    """辛辣**作为主味**。

    绝不用裸 `nature=hot`：实测 15 条 hot 里 4 条不辣（油条／羊肉／薯条／炸鱼薯条）。
    所以判据是「flavors 含 pungent 且 nature=hot」或「条目名含辣词」；
    再排除 category=酒类——「白酒」的辛是酒精的辛烈，已由 alcohol 计分，避免双计。
    """
    # 酒类直接否决：「白酒」的辛是酒精的辛烈，已由 alcohol 计分。
    if category in set(_rule("spicy").get("exclude_categories") or []):
        return False

    for raw in (name, canonical):
        if has_spicy_marker(raw):
            return True

    natures = {str(n) for n in (_rule("spicy").get("natures") or [])}
    if "pungent" in _flavor_keys(food) and _nature_key(food) in natures:
        return True
    return False


# ============================================================
# 公开入口
# ============================================================
def identify_signals(text: str, foods: Sequence[ParsedFood]) -> list[SignalHit]:
    """识别这一餐命中的原子信号。纯函数：不调模型、不抛异常。"""
    by_id = _signals_by_id()
    if not by_id:
        return []
    index = _food_index()
    hits: list[SignalHit] = []

    def add(sid: str, subject: str) -> None:
        spec = by_id.get(sid)
        if spec is None:
            return
        hits.append(
            SignalHit(
                id=sid,
                label=spec["label"],
                weight=1,
                evidence=spec["evidence"],
                arity=spec["arity"],
                subject=subject,
            )
        )

    for food in foods:
        name = (food.name or "").strip()
        if not name:
            continue
        info = index.get(name)
        if info is None:
            # 模型可能直接给出「冰啤酒」这类带前缀的名字，而表内只有「啤酒」。
            # 剥掉前缀后回退查一次，才拿得到它的类目（酒类）与规范名。
            # 回退同样受准入约束：「冰淇淋」剥成「淇淋」查不到，自然落空。
            detected = detect_temperature_prefix(name)
            if detected:
                info = index.get(detected[2])
        info = info or {}
        canonical = str(info.get("name") or name)
        category = info.get("category")

        if _is_iced(text or "", name, index):
            add("iced", canonical)
        if canonical in _entries("frozen"):
            add("frozen", canonical)
        if canonical in _entries("cold_raw"):
            add("cold_raw", canonical)
        if canonical in _entries("fried"):
            add("fried", canonical)
        if canonical in _entries("greasy"):
            add("greasy", canonical)
        if canonical in _entries("carbonated"):
            add("carbonated", canonical)
        if category in _categories("alcohol"):
            add("alcohol", canonical)
        if category in _categories("high_sugar") or canonical in _entries("high_sugar"):
            add("high_sugar", canonical)
        if category in _categories("dairy") or canonical in _entries("dairy"):
            add("dairy", canonical)
        if _is_spicy(food, name, canonical, category):
            add("spicy", canonical)

    # per-meal 信号：热食与冰饮同餐。
    has_hot = any(_nature_key(f) == Nature.HOT.value for f in foods)
    has_iced = any(h.id == "iced" for h in hits)
    if has_hot and has_iced:
        add("temp_shock", MEAL_SUBJECT)

    return hits


def score_dimension(
    dimension_id: str,
    hits: Sequence[SignalHit],
    dimensions: dict[str, Any] | None = None,
) -> DimensionResult:
    """按数据表里的 weights / aggregation 聚合一个维度。

    `dimensions` 仅供测试注入内存副本（变异检验用），生产路径留空即可。
    """
    spec = dimensions if dimensions is not None else (load_diet_signals().get("dimensions") or {})
    dim = (spec or {}).get(dimension_id)
    if not dim:
        return DimensionResult(
            id=dimension_id,
            score=0,
            action="none",
            basis=str(load_diet_signals().get("_meta", {}).get("basis", "")),
            note="维度定义缺失，未计分",
        )

    weights: dict[str, int] = dim.get("weights") or {}
    scored = [h for h in hits if h.id in weights]
    mode = (dim.get("aggregation") or {}).get("mode", "sum")

    if mode == "sum_per_item_then_max":
        # 先单品求和、再跨条目取最大、最后叠 per-meal 信号。
        # 不能直接跨条目取最大：那样「冰啤酒」只有 1（冰、酒精、碳酸在同一单品内）。
        per_item: dict[str, int] = {}
        meal = 0
        for hit in scored:
            if hit.arity == "meal":
                meal += weights[hit.id]
            else:
                per_item[hit.subject] = per_item.get(hit.subject, 0) + weights[hit.id]
        raw = (max(per_item.values()) if per_item else 0) + meal
    else:
        raw = sum(weights[h.id] for h in scored)

    cap = int(dim.get("cap") or 0)
    score = min(raw, cap) if cap else raw
    floor = _evidence_floor(scored)

    return DimensionResult(
        id=dimension_id,
        score=score,
        action=_action_for(dim.get("levels") or [], score),
        hits=list(scored),
        evidence_floor=floor,
        basis=str(load_diet_signals().get("_meta", {}).get("basis", "")),
        note=_floor_note(floor),
    )


def _action_for(levels: Sequence[dict], score: int) -> str:
    for level in levels:
        if int(level.get("min", 0)) <= score <= int(level.get("max", 0)):
            return str(level.get("action", "none"))
    return "none"


def _evidence_floor(hits: Sequence[SignalHit]) -> str:
    """本次参与计分的信号里**最弱**的一档。没有命中则无所谓依赖，记 full。"""
    if not hits:
        return "full"
    worst = 0
    for hit in hits:
        try:
            rank = EVIDENCE_ORDER.index(hit.evidence)
        except ValueError:
            rank = len(EVIDENCE_ORDER) - 1
        worst = max(worst, rank)
    return EVIDENCE_ORDER[worst]


def _floor_note(floor: str) -> str:
    if floor == "full":
        return ""
    return {
        "partial": "部分判据只有相邻字段或名单近似，非表内直接对应。",
        "clinical": "依据体系不同：现代临床经验认同、古籍无载（如乳制品生湿）。",
        "none": "表内无对应字段，判据为条目名单近似，请勿当作确定结论。",
    }.get(floor, "")


# ============================================================
# 阶段 1：整餐信号装配（三条链路共用）
# ============================================================
def build_meal_signals(text: str, foods: Sequence[ParsedFood]) -> MealSignals:
    """把识别与打分的结果装配成 ``ParsedMeal.signals``。

    放在本模块而不是 ``orchestrator``：终端离线链路（``ui/terminal/chat.py``）也要用，
    而 ``ui/`` 只 import ``app.*``，不该反向依赖 services 层。

    ⚠️ **不另判一遍冲突**：`conflict` 三个字段的值原样来自 `detect_nature_conflict`
    （测试用「装配结果 == 直接调判定」这条派生不变式钉住，见 §7.1）。
    """
    hits = identify_signals(text, foods)
    conflict = detect_nature_conflict([(food.name, food.nature) for food in foods])
    return MealSignals(
        impact=_dimension(DIMENSION_IMPACT, hits),
        dampness=_dimension(DIMENSION_DAMPNESS, hits),
        conflict=MealConflict(
            conflict=conflict.conflict,
            heat_side=list(conflict.heat_side),
            cold_side=list(conflict.cold_side),
        ),
    )


def _dimension(dimension_id: str, hits: Sequence[SignalHit]) -> MealDimension | None:
    """把 `DimensionResult` 转成 pydantic 模型。

    维度定义缺失时返回 **None**——宁可不显示，也不臆造一个 0 分结论。
    """
    dim = (load_diet_signals().get("dimensions") or {}).get(dimension_id)
    if not dim:
        return None
    result = score_dimension(dimension_id, hits)
    labels = _action_labels(dim.get("levels") or [])

    seen: list[str] = []
    for hit in result.hits:
        if hit.label not in seen:
            seen.append(hit.label)

    return MealDimension(
        score=result.score,
        cap=int(dim.get("cap") or 0),
        action=result.action,
        action_label=labels.get(result.action, ""),
        signals=seen,
        evidence_floor=result.evidence_floor,
        basis=result.basis,
    )


def _action_labels(levels: Sequence[dict]) -> dict[str, str]:
    """档位 token → 中文标签。

    **中文只有一份，在定义档位的数据文件里**；两个壳只打印、不自己翻译，
    避免出现第二份标签表（项目当初把 `SOURCE_LABELS` 收敛进 `enums.py` 就是为此）。
    """
    return {str(lv.get("action", "")): str(lv.get("label") or "") for lv in levels}
