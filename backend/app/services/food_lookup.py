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
from functools import lru_cache
from typing import Any

from app.config import get_settings
from app.domain.enums import FLAVOR_LABELS, NATURE_LABELS

logger = logging.getLogger(__name__)

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

    # 口述里出现冰镇/加冰时，明确提示属性要下调——
    # 光靠 system 提示词里的规则，模型有时仍然照抄基础属性。
    if any(kw in text for kw in ("冰", "加冰", "冰镇", "冰饮", "冷饮", "雪糕", "冰淇淋")):
        lines.append(
            "\n注意：这次口述里含冰镇/加冰的饮品，"
            "相关条目的属性应在此基础上向寒凉方向调整（平→凉、温→凉或平、凉→寒），"
            "并在 `note` 里写明「冰镇」。"
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
