"""只读加载家用食疗汤模板（soup_templates.json）。

与 constitution_medication 同哲学：数据落地供策展/只读查询；
**默认不**进入 Agent2 自动推荐（全部 pending 时尤其如此）。
可供将来 tool-calling 注册的纯函数见 ``list_soup_templates`` /
``get_soup_template``（亦见 ``app.agents.tool_registry_stub``）。
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from app.config import get_settings

DATA_FILENAME = "soup_templates.json"
ALLOWED_KIND = "food_therapy"
ALLOWED_REVIEW = frozenset({"pending", "approved", "rejected"})


class SoupTemplatesError(RuntimeError):
    """``soup_templates.json`` 缺失或结构不合法。"""


class SoupTemplateNotFound(LookupError):
    """白名单外或未知的模板 id。"""


def _herb_ids() -> set[str]:
    path = get_settings().data_dir / "herbs.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {h["id"] for h in raw.get("herbs") or [] if isinstance(h, dict) and "id" in h}


def _food_ids() -> set[str]:
    path = get_settings().data_dir / "food_properties.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    ids: set[str] = set()
    foods = raw.get("foods")
    if isinstance(foods, list):
        for item in foods:
            if isinstance(item, dict) and item.get("id"):
                ids.add(item["id"])
    elif isinstance(foods, dict):
        for item in foods.get("items") or []:
            if isinstance(item, dict) and item.get("id"):
                ids.add(item["id"])
    tea = raw.get("tea_drinks")
    if isinstance(tea, dict):
        for item in tea.get("items") or []:
            if isinstance(item, dict) and item.get("id"):
                ids.add(item["id"])
    elif isinstance(tea, list):
        for item in tea:
            if isinstance(item, dict) and item.get("id"):
                ids.add(item["id"])
    return ids


def _validate_component(template_id: str, comp: dict, herb_ids: set[str], food_ids: set[str]) -> None:
    if not isinstance(comp, dict):
        raise SoupTemplatesError(f"{template_id}: component 必须是对象")
    has_herb = "herb_id" in comp and comp["herb_id"] is not None
    has_food = "food_id" in comp and comp["food_id"] is not None
    if has_herb == has_food:
        raise SoupTemplatesError(
            f"{template_id}: 每个 component 必须且只能有 herb_id 或 food_id 之一"
        )
    if comp.get("role") != "ingredient":
        raise SoupTemplatesError(f"{template_id}: role 必须为 ingredient")
    if has_herb:
        hid = comp["herb_id"]
        if hid not in herb_ids:
            raise SoupTemplatesError(f"{template_id}: herb_id={hid!r} 不在 herbs.json")
    else:
        fid = comp["food_id"]
        if fid not in food_ids:
            raise SoupTemplatesError(
                f"{template_id}: food_id={fid!r} 不在 food_properties.json"
            )


def validate_soup_templates_payload(data: dict[str, Any]) -> None:
    """校验整份 payload；失败抛 ``SoupTemplatesError``。"""
    if not isinstance(data, dict) or "templates" not in data:
        raise SoupTemplatesError(f"{DATA_FILENAME} 缺少 templates 数组")
    if not isinstance(data["templates"], list):
        raise SoupTemplatesError("templates 必须是数组")
    herb_ids = _herb_ids()
    food_ids = _food_ids()
    seen: set[str] = set()
    for t in data["templates"]:
        if not isinstance(t, dict):
            raise SoupTemplatesError("template 必须是对象")
        tid = t.get("id")
        if not isinstance(tid, str) or not tid.strip():
            raise SoupTemplatesError("template 缺少 id")
        if tid in seen:
            raise SoupTemplatesError(f"重复 template id: {tid}")
        seen.add(tid)
        if t.get("kind") != ALLOWED_KIND:
            raise SoupTemplatesError(f"{tid}: kind 必须为 {ALLOWED_KIND}")
        if t.get("review_status") not in ALLOWED_REVIEW:
            raise SoupTemplatesError(f"{tid}: review_status 非法")
        hint = t.get("kitchen_amount_hint")
        if not isinstance(hint, str) or not hint.strip():
            raise SoupTemplatesError(f"{tid}: 缺少 kitchen_amount_hint")
        comps = t.get("components")
        if not isinstance(comps, list) or not comps:
            raise SoupTemplatesError(f"{tid}: components 不能为空")
        for c in comps:
            _validate_component(tid, c, herb_ids, food_ids)


@lru_cache(maxsize=1)
def load_soup_templates() -> dict:
    path = get_settings().data_dir / DATA_FILENAME
    if not path.is_file():
        raise SoupTemplatesError(f"缺少 {DATA_FILENAME}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SoupTemplatesError(f"{DATA_FILENAME} 不是合法 JSON：{exc}") from exc
    validate_soup_templates_payload(data)
    return data


def list_food_therapy_templates() -> list[dict]:
    """返回 kind==food_therapy 的模板列表（浅拷贝条目）。"""
    data = load_soup_templates()
    out = []
    for t in data["templates"]:
        if not isinstance(t, dict):
            continue
        if t.get("kind") != ALLOWED_KIND:
            continue
        out.append(dict(t))
    return out


def list_soup_templates(*, include_pending: bool = True) -> list[dict]:
    """只读工具：列出食疗模板（结构化 dict 浅拷贝）。

    ``include_pending=False`` 时只返回 ``review_status==approved``。
    当前库内均为 pending → 默认列表仍可查，但调用方须自行展示免责声明，
    **不得**把 pending 模板自动写入 Agent2 ``recommendations``。
    """
    out = []
    for t in list_food_therapy_templates():
        status = t.get("review_status")
        if not include_pending and status != "approved":
            continue
        out.append(t)
    return out


def get_soup_template(template_id: str) -> dict:
    """只读工具：按 id 取一条模板；白名单外 id 明确失败。

    返回中附带 ``_query_meta``：说明 pending 不得自动推荐进 Agent2。
    """
    if not isinstance(template_id, str) or not template_id.strip():
        raise SoupTemplateNotFound("模板 id 不能为空")
    tid = template_id.strip()
    for t in list_food_therapy_templates():
        if t.get("id") == tid:
            payload = dict(t)
            status = payload.get("review_status")
            payload["_query_meta"] = {
                "auto_recommend_allowed": status == "approved",
                "disclaimer": (
                    "本条为策展食疗模板查询结果，不是中药处方。"
                    + (
                        "当前 review_status=pending，仅供查阅，不得自动写入推荐列表，不得按方剂加减。"
                        if status == "pending"
                        else "引用时仅可使用 display_name 与 kitchen_amount_hint，不得编造超出约量的剂量。"
                    )
                ),
            }
            return payload
    raise SoupTemplateNotFound(f"未知或不允许的食疗模板 id: {tid}")


def soup_templates_disclaimer() -> str:
    return (
        "以下为药食同源范围内的家用食疗汤模板，仅供查阅与厨房参考，"
        "不构成中药处方或医疗建议；不得按君臣佐使加减，不得抄成门诊汤剂剂量。"
        "review_status=pending 的条目默认不进入自动茶饮推荐。"
    )


def clear_soup_templates_cache() -> None:
    load_soup_templates.cache_clear()
