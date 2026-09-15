"""食材属性查表：从 food_properties.json 里按用户口述匹配条目，注入 Agent1 提示词。

设计意图
--------
在此之前 Agent1 完全靠模型的语感判断食物属性，实测有系统性偏差
（例如把性温的茉莉花茶判成"凉"，把中性食材普遍判成"温"）。

这一层的做法是：把用户提到的那几样东西的属性**从表里查出来喂给模型**，
让属性判定从"凭感觉"变成"照抄表"。表里没有的仍然允许模型按经验判断，
但必须标记为低把握度，而不是假装确定。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from app.config import get_settings
from app.domain.enums import FLAVOR_LABELS, NATURE_LABELS, Nature
from app.domain.models import Verification
from app.domain.nature_math import (
    COOKING_DELTA,
    TemperatureSignal,
    apply_cooking_fallback,
    shift_nature,
)
from app.domain.nature_math import resolve_temperature as nature_math_resolve

logger = logging.getLogger(__name__)

# ============================================================
# 置信度约定（由使用者确认，低到高）
#   低于 0.3 → 界面不显示寒热属性
#   非 rule 来源 → 界面必须标注"待验证"
# ============================================================
CONF_RULE = 0.9             # 硬规则库：命中食性表（已审核则 unverified=False）
CONF_COMPOSED = 0.6         # 组合推理 / 烹饪修正算出来的
CONF_LLM = 0.3              # 模型推测
CONF_UNRESOLVED = 0.1       # 无法判定
CONF_SHOW_THRESHOLD = 0.3   # 低于此值不显示寒热属性


@dataclass
class ResolvedFood:
    """单个食物的确定性判定结果。"""

    name: str
    nature: str
    flavors: list[str] = field(default_factory=list)
    entry: dict | None = None
    verification: Verification = field(default_factory=Verification)

# 处理方式 → 该方式下的属性变化（来自表里的 nature_change_rules 与条目 variant_nature）
COOKING_LABELS = {
    "raw": "生食",
    "cold": "冰镇/加冰",
    "deep_fried": "油炸",
    "grilled": "烧烤",
    "stir_fried": "炒制",
    "boiled": "炖煮",
    "steamed": "清蒸",
    "pickled": "腌制",
}


@lru_cache(maxsize=1)
def load_food_table() -> dict[str, Any]:
    """加载食材表。文件不存在时返回空表，不抛异常。"""
    path = get_settings().data_dir / "food_properties.json"
    if not path.exists():
        logger.warning("缺少 food_properties.json，Agent1 将退回无参考表模式")
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _entries() -> list[dict]:
    """所有可查条目（普通食材 + 茶饮）。"""
    table = load_food_table()
    foods = list(table.get("foods", []))
    drinks = list(table.get("tea_drinks", {}).get("items", []))
    return foods + drinks


def reload_food_table() -> dict[str, Any]:
    load_food_table.cache_clear()
    return load_food_table()


def match_foods(text: str, limit: int = 12) -> list[dict]:
    """在用户口述里找出表中有记录的条目。

    匹配策略：关键词命中即算，按关键词长度降序优先（长词更具体，
    例如「麻辣香锅」应优先于「麻辣」）。
    """
    if not text:
        return []

    scored: list[tuple[int, dict]] = []
    for entry in _entries():
        keywords = entry.get("keywords") or [entry.get("name", "")]
        hits = [kw for kw in keywords if kw and kw in text]
        if not hits:
            continue
        # 用最长命中关键词的长度作为排序权重，其次按命中数量
        weight = max(len(kw) for kw in hits) * 10 + len(hits)
        scored.append((weight, entry))

    scored.sort(key=lambda pair: pair[0], reverse=True)

    # 去重（同一 id 只保留一次）
    seen: set[str] = set()
    result: list[dict] = []
    for _, entry in scored:
        eid = entry.get("id") or entry.get("name")
        if eid in seen:
            continue
        seen.add(eid)
        result.append(entry)
        if len(result) >= limit:
            break
    return result


def names_match(expected: str, actual: str) -> bool:
    """判断两个食物名是否指同一样东西。

    用途：校验 Agent 输出时，"兰州拉面"（用户原话）与"面条"（表里规范名）
    应被视为同一物；"冰美式"与"冰美式咖啡"也是。

    规则（任一满足即可）：
      1. 一方是另一方的子串（"白米饭" 含 "米饭"）；
      2. 两字以上且前两字相同（"龙眼" vs "龙眼肉"）；
      3. expected 是某条目的规范名、别名或关键词之一
         （"拉面""兰州拉面" 都是「面条」条目的关键词）。
    """
    a = (actual or "").replace(" ", "").strip()
    e = (expected or "").replace(" ", "").strip()
    if not a or not e:
        return False
    if e in a or a in e:
        return True
    if len(e) >= 2 and len(a) >= 2 and e[:2] == a[:2]:
        return True

    # 名称→条目 的别名/关键词比对：条目规范名与 actual 一致时，
    # 只要 expected 命中了该条目的别名或关键词，就算同一物。
    for entry in _entries():
        entry_name = (entry.get("name") or "").replace(" ", "").strip()
        if not names_match_basic(entry_name, a):
            continue
        candidates = [entry_name] + list(entry.get("aliases") or []) + list(entry.get("keywords") or [])
        for cand in candidates:
            c = (cand or "").replace(" ", "").strip()
            if c and names_match_basic(c, e):
                return True
    return False


def names_match_basic(x: str, y: str) -> bool:
    """只做子串与前两字比较，不查表（供 names_match 内部递归使用，避免死循环）。"""
    if not x or not y:
        return False
    if x in y or y in x:
        return True
    return len(x) >= 2 and len(y) >= 2 and x[:2] == y[:2]


def resolve_temperature_fields(name: str, note: str = "") -> TemperatureSignal | None:
    """解析用的温度判定入口：带"须能锚定到表内条目"的准入校验。

    扫描 name 与 note 两个字段（判定本身由 nature_math.resolve_temperature 实现，
    新增前缀只改那一处的 CHILL_PREFIXES / HEAT_PREFIXES）。

    准入校验分两种情形：
      - 温度来自**食物名**：剥掉前缀后剩下的词必须是一个完整表内食物名
        （「冰啤酒→啤酒」✅，「冰淇淋→淇淋」❌），否则丢弃——这样温度字
        属于菜名的词不会被误判。
      - 温度来自**备注**：名字本身就是完整的（如 name=奶茶），温度词是独立
        描述，所以不要求 note 剥完还剩什么，只要名字能在表里锚定即可。
    """
    signal = nature_math_resolve(name=name, note=note)
    if signal is None:
        return None

    if signal.from_field == "name":
        # 名字通道：剥后必须锚定到表内条目
        if not _is_full_entry_name(signal.stripped):
            return None
        return signal

    # 备注通道：用"查表时的名字"做锚定校验。
    # 名字本身没有温度前缀时，锚定对象就是 name 自身。
    anchor = signal.stripped or name
    if not _is_full_entry_name(anchor) and not _find_entry(anchor)[0]:
        return None
    return signal


def temperature_signal(name: str = "", note: str = "") -> TemperatureSignal | None:
    """提示词层用的温度判定入口：只识别，不做表达名校验。

    与 resolve_temperature_fields 共用同一套前缀表与判定逻辑，
    区别只是不做"剥后须为完整食物名"的严格准入——提示词里给出的是
    泛化提醒（"这里的冰表示冰镇"），不需要精确锚定到某个表内条目。

    两个入口都只是 nature_math.resolve_temperature 的薄包装，
    新增前缀仍然只改一处。
    """
    return nature_math_resolve(name=name, note=note)


def _is_full_entry_name(candidate: str) -> bool:
    """candidate 是否**恰好等于**某个条目的规范名或别名。

    用于温度前缀的准入判断：只有剥掉前缀后剩下的词本身就是一个完整的
    表内食物名（「啤酒」「牛奶」「红茶」），温度前缀才可信。
    「淇淋」（来自冰淇淋）、「干面」（来自热干面）都不是完整食物名，
    所以它们的温度字属于菜名，不该被当作温度指令。
    """
    target = (candidate or "").replace(" ", "").strip()
    if not target:
        return False
    for entry in _entries():
        if (entry.get("name") or "").replace(" ", "").strip() == target:
            return True
        for alias in entry.get("aliases") or []:
            if (alias or "").replace(" ", "").strip() == target:
                return True
    return False


def _find_entry(
    name: str, cooking: str | None = None
) -> tuple[dict | None, str | None, str]:
    """按名称查条目。返回 (条目, 命中的词, 命中方式)。

    命中方式 `match_kind` 有两种：
      - `"name"`：命中条目**规范名**（含精确同名与包含关系）
      - `"keyword"`：仅命中关键词/别名

    区分这两种很重要：温度前缀只在 `"name"` 命中时才允许叠加。
    「热干面」是靠关键词"面"匹配到「面条」的，它的"热"属于菜名而不是
    让我们升温的指令；而「冰啤酒」是命中规范名「啤酒」加上前缀，应当叠加。

    匹配优先级（**顺序不可颠倒**）：
      0. 条目规范名与 name **完全相同** —— 最高优先，直接返回。
         这一级必须有，否则「希腊酸奶」会被「酸奶」抢走、「牛肉汉堡」会被「汉堡」抢走。
      1. 条目规范名与 name 有包含关系。多个候选时取**包含关系更精确**的：
         先比"规范名长度与该名字的差距"，差距小者胜；再比规范名长度。
      2. 条目**关键词/别名**精确包含匹配（这一级永远低于名字匹配）。

    为什么要严格分级：此前把名字与关键词混在一起按"命中词长度"打分，
    导致「寿司」被匹配到「生鱼片」（其关键词含"寿司"）、
    「薯条」被匹配到「炸鱼薯条」（其关键词含"薯条"，且名字更长而胜出）。
    """
    if not name:
        return None, None, ""

    target = name.replace(" ", "").strip()
    if not target:
        return None, None, ""

    name_match: tuple[int, int, dict, str] | None = None   # (gap, 长度, 条目, 命中词)
    keyword_match: tuple[int, dict, str] | None = None     # (命中词长度, 条目, 命中词)

    for entry in _entries():
        entry_name = (entry.get("name") or "").replace(" ", "").strip()
        if not entry_name:
            continue

        # 第 0 级：完全同名
        if entry_name == target:
            return entry, entry_name, "name"

        # 第 1 级：包含关系，按 gap 最小者优先
        if entry_name in target or target in entry_name:
            gap = abs(len(entry_name) - len(target))
            key = (gap, len(entry_name))
            if name_match is None or key < (name_match[0], name_match[1]):
                name_match = (gap, len(entry_name), entry, entry_name)

        # 第 2 级：关键词/别名匹配
        for kw in list(entry.get("keywords") or []) + list(entry.get("aliases") or []):
            k = (kw or "").replace(" ", "").strip()
            if not k or k not in target:
                continue
            if keyword_match is None or len(k) > keyword_match[0]:
                keyword_match = (len(k), entry, k)

    if name_match is not None:
        return name_match[2], name_match[3], "name"
    if keyword_match is not None:
        return keyword_match[1], keyword_match[2], "keyword"
    return None, None, ""


def strip_temperature_prefix(name: str, note: str = "") -> tuple[str, int, str]:
    """兼容包装：委托给唯一入口 resolve_temperature_fields。"""
    signal = resolve_temperature_fields(name, note)
    if signal is None:
        return name, 0, ""
    return signal.stripped, signal.delta, signal.prefix


def resolve_food(
    name: str,
    cooking: str | None = None,
    llm_nature: str | None = None,
    text_hint: str = "",
    note: str = "",
) -> ResolvedFood:
    """确定性判定单个食物的四性。这就是三层架构的入口。

    返回的 ResolvedFood 直接对应接口里的 verification 块。

    判定顺序：
      1. 未命中表 → 保留 LLM 的判断但标 source=llm / 未验证 / 置信度 0.3；
         若 LLM 也判不出（unknown）则降为 unresolved / 0.1。
      2. 命中表 + 条目有该烹饪方式的变体 → **食材变体层**，直接用变体值。
      3. 命中表 + 无变体 → **烹饪修正层**，按 ±1 通用规则做兜底。
      4. 温度前缀层（纯规则）→ 在以上结果上再叠加 ±1。
    """
    # ---- 温度前缀：纯规则，先于查表剥掉 ----
    # 必须在查表**之前**做，否则「冰啤酒」会因包含匹配直接命中「啤酒」条目，
    # 温度信息就被丢掉了。
    # 判定走唯一入口 resolve_temperature_fields（同时扫描 name 与 note），
    # 它内含"剥后须为完整表内食物名"的准入校验。
    signal = resolve_temperature_fields(name, note)
    if signal is not None:
        stripped_name = signal.stripped
        temp_delta = signal.delta
        temp_prefix = signal.prefix
        temp_field = signal.from_field
    else:
        stripped_name, temp_delta, temp_prefix, temp_field = name, 0, "", ""

    # 查表统一用"剥掉温度前缀后的名字"。
    # 即使温度来自 note（name 本身不含前缀），也要用同一个名字查表，
    # 否则会出现"查表用 name、叠加用 stripped"的不一致，
    # 导致「name=奶茶, note=去冰」这种输入的温度增量白算。
    lookup_name = stripped_name if temp_delta else name

    entry, hit_word, match_kind = _find_entry(lookup_name, cooking)

    if entry is None and temp_delta:
        # 剥掉前缀后仍查不到，用原名再试一次（温度仍保留，靠后面的锚定校验保证不误判）
        entry, hit_word, match_kind = _find_entry(name, cooking)

    if entry is None:
        # 表未覆盖：保留模型判断，但明确标记为推测
        if llm_nature and llm_nature != Nature.UNKNOWN.value:
            return ResolvedFood(
                name=name,
                nature=llm_nature,
                flavors=[],
                verification=Verification(
                    source="llm",
                    confidence=CONF_LLM,
                    unverified=True,
                    detail=f"「{name}」不在食性表内，属性为模型推测，未经中医食性验证",
                ),
            )
        return ResolvedFood(
            name=name,
            nature=Nature.UNKNOWN.value,
            flavors=[],
            verification=Verification(
                source="unresolved",
                confidence=CONF_UNRESOLVED,
                unverified=True,
                detail=f"「{name}」不在食性表内，且无法推测属性",
            ),
        )

    # 命中表：先看这一烹饪方式有没有专门的变体记录（食材变体层）
    variants = entry.get("variant_nature") or {}
    cooking_key = ""
    if cooking is not None:
        cooking_key = cooking.value if hasattr(cooking, "value") else str(cooking)

    # 「模型给的名称」与「条目规范名」完全相同 → 表里就是这个食物本身，
    # 它的 nature 是权威基线，**不叠加模型猜的烹饪修正**（否则模型随口给个
    # grilled 就能把火腿三明治从平污染成温）。
    #
    # 注意这里比较的是**名称整体**，不是命中词：
    # 「炸馒头」靠关键词"馒头"识别、「冰啤酒」靠包含关系识别，
    # 两者名称与规范名都不同，属于"带烹饪信息的派生名称"，应当让烹饪层生效。
    exact_name_hit = name.replace(" ", "").strip() == (entry.get("name") or "").replace(" ", "").strip()

    base_nature = entry.get("nature") or Nature.UNKNOWN.value
    nature = base_nature
    layer_detail = ""
    source = "rule"
    cooking_cn = COOKING_LABELS.get(cooking_key, cooking_key) if cooking_key else ""

    if cooking_key and cooking_key in variants:
        nature = variants[cooking_key]
        layer_detail = (
            f"「{entry['name']}」{cooking_cn}后属性为{_cn(nature)}（食材变体层，查表直取）"
        )
    elif exact_name_hit:
        form = f"{cooking_cn}后" if cooking_cn else "原形态下"
        layer_detail = f"「{entry['name']}」{form}属性为{_cn(nature)}（查表直取）"
        if cooking_key and COOKING_DELTA.get(cooking_key, 0):
            layer_detail += "，未叠加模型推测的处理方式修正"
    else:
        # 由别名/关键词识别到，或名字与规范名不同 → 烹饪修正层兜底
        adjusted, notes = apply_cooking_fallback(base_nature, cooking_key, text_hint)
        if adjusted is not None:
            nature = adjusted.value
        if notes:
            source = "composed"
            layer_detail = f"「{entry['name']}」本为{_cn(base_nature)}，{'；'.join(notes)}"
        else:
            form = f"{cooking_cn}后" if cooking_cn else "原形态下"
            layer_detail = f"「{entry['name']}」{form}属性为{_cn(nature)}"

    # ---- 温度前缀叠加（纯规则）----
    # 放在最后：变体层与烹饪层都算完之后，温度再修正一档。
    # 用 shift_nature 自动夹取，不会溢出到 ±2 之外。
    #
    # 温度增量已在前面通过准入条件校验（剥后须为完整表内食物名），
    # 这里直接叠加即可，不需要再判断温度字是否属于菜名。
    if temp_delta:
        before = nature
        shifted = shift_nature(nature, temp_delta)
        if shifted is not None:
            nature = shifted.value
            source = "composed"
            where = "食物名" if temp_field == "name" else "备注"
            layer_detail += (
                f"；{temp_prefix}修正 {temp_delta:+d}：{_cn(before)} → {_cn(nature)}"
                f"（温度前缀由{where}识别，纯规则判定，不经模型）"
            )

    # 置信度取决于审核状态（三态）：
    #   approved → 硬规则库，高置信度且不打"待验证"
    #   pending  → 高置信度但必须标"待验证"（方案 X）
    #   rejected → 审核不通过，按组合推理档处理，不作为硬规则
    status = entry.get("review_status")
    if status is None:
        # 兼容旧数据：只有 reviewed 布尔字段时按它推断
        status = "approved" if entry.get("reviewed") else "pending"

    if status == "approved":
        confidence = CONF_RULE
        unverified = False
    elif status == "rejected":
        confidence = CONF_COMPOSED
        unverified = True
        layer_detail += "（该条目审核未通过，仅供参考）"
    else:  # pending
        confidence = CONF_COMPOSED if source == "composed" else CONF_RULE
        unverified = True
        layer_detail += "（该条目尚未通过人工审核）"

    if hit_word and hit_word != entry.get("name"):
        layer_detail += f"（由「{hit_word}」识别为「{entry['name']}」）"

    return ResolvedFood(
        name=name,
        nature=nature,
        flavors=list(entry.get("flavors") or []),
        entry=entry,
        verification=Verification(
            source=source,
            confidence=confidence,
            unverified=unverified,
            detail=layer_detail or None,
        ),
    )


def _cn(nature: str | None) -> str:
    return NATURE_LABELS.get(nature or "unknown", "未知")


def render_reference(text: str) -> str:
    """把命中的条目渲染成提示词里的参考表文本。没命中就返回空串。"""
    entries = match_foods(text)
    if not entries:
        return ""

    lines: list[str] = []
    for e in entries:
        nature = NATURE_LABELS.get(e.get("nature", "unknown"), "未知")
        # 五味也要转中文——提示词全中文时，英文枚举值会增加模型误解的可能
        flavors = "/".join(
            FLAVOR_LABELS.get(f, f) for f in (e.get("flavors") or [])
        )
        lines.append(f"- {e['name']}：{nature}，{flavors}")

        # 处理方式带来的属性变化
        variants = e.get("variant_nature") or {}
        if variants:
            parts = []
            for cooking, nat in variants.items():
                parts.append(f"{COOKING_LABELS.get(cooking, cooking)}→{NATURE_LABELS.get(nat, nat)}")
            lines.append(f"    （{'；'.join(parts)}）")

        # 茶饮类条目附一句说明，帮模型理解它对应什么
        if e.get("note"):
            lines.append(f"    说明：{e['note']}")

    # 口述里出现温度前缀时，提示属性要相应调整。
    # 这里**不再自己写一套判定**，统一走 temperature_signal——
    # 此前这里用子串匹配（"冰" in text），与解析层的前缀匹配不一致，
    # 会把「冰淇淋」也当成冰镇，两层结论可能相互矛盾。
    # 现在新增前缀只需改 nature_math 里的 CHILL_PREFIXES / HEAT_PREFIXES。
    signal = temperature_signal(text)
    if signal is not None:
        direction = "寒凉" if signal.delta < 0 else "温热"
        shift_desc = "平→凉、温→凉或平、凉→寒" if signal.delta < 0 else "平→温、凉→平、温→热"
        lines.append(
            f"\n注意：口述里的「{signal.prefix}」是温度前缀，"
            f"「{signal.stripped}」的属性应在此基础上向{direction}方向调整"
            f"（{shift_desc}），并在 `note` 里写明「{signal.prefix}」。"
        )

    return "\n".join(lines)


def render_nature_change_rules() -> str:
    """渲染处理方式的通用规则，帮助模型处理表里没写 variant 的条目。

    注意：规则在文件的 `_meta.nature_change_rules` 下，不在顶层。
    """
    table = load_food_table()
    meta = table.get("_meta") or {}
    rules = meta.get("nature_change_rules") or table.get("nature_change_rules") or {}
    if not rules:
        logger.warning("food_properties.json 缺少 nature_change_rules，通用处理规则不可用")
        return ""
    lines = []
    for cooking, desc in rules.items():
        lines.append(f"- {COOKING_LABELS.get(cooking, cooking)}：{desc}")
    return "\n".join(lines)


def table_stats() -> dict[str, int]:
    """表规模统计，用于自检与提示词里的规模说明。"""
    table = load_food_table()
    return {
        "foods": len(table.get("foods", [])),
        "tea_drinks": len(table.get("tea_drinks", {}).get("items", [])),
        "total": len(_entries()),
    }
