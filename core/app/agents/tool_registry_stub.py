"""Tool-calling 注册点桩（未实现完整 Agent 循环）。

安全闸在循环**外**（白名单校验、pending 不自动推荐、剂量封顶、高风险空推荐），
不依赖模型自觉。完整循环见仓库旁 ``tea-advisor-agent-proposal.md``；
本文件只留下可注册的只读工具签名，便于以后接 registry。

**不要**在此实现自由组方或把 pending 模板塞进 Agent2 recommendations。
"""

from __future__ import annotations

from typing import Any, Callable

# 实际实现：app.services.soup_templates
# list_soup_templates(*, include_pending: bool = True) -> list[dict]
# get_soup_template(template_id: str) -> dict  # 未知 id → SoupTemplateNotFound

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "list_soup_templates",
        "description": (
            "列出策展家用食疗汤模板（food_therapy）。"
            "仅当用户明确问家常汤/药膳名，或口述匹配某模板 display_name 时考虑调用。"
            "返回结构化列表；pending 条目不得自动写入茶饮 recommendations。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "include_pending": {
                    "type": "boolean",
                    "default": True,
                    "description": "为 false 时只返回 review_status=approved",
                }
            },
        },
        "return_type": "list[dict]",
        "safety": (
            "只读；循环外仍须：禁止方剂名、禁止加减组成、"
            "剂量不超过 kitchen_amount_hint / 单味 max_daily_g；"
            "pending → 仅查询展示并带免责，不进 Agent2 自动推荐。"
        ),
        "impl": "app.services.soup_templates.list_soup_templates",
    },
    {
        "name": "get_soup_template",
        "description": (
            "按模板 id 取一条食疗汤详情。白名单外 id 必须失败，不得猜测或编造。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "template_id": {
                    "type": "string",
                    "description": "soup_templates.json 中的 id，如 sishen_tang",
                }
            },
            "required": ["template_id"],
        },
        "return_type": "dict",
        "safety": (
            "未知 id → 明确错误；返回含 _query_meta.disclaimer；"
            "不得把结果当处方加减。"
        ),
        "impl": "app.services.soup_templates.get_soup_template",
    },
    {
        "name": "list_personas",
        "description": (
            "列出用户主画像样本条目（结构化对照层，非向量 RAG）。"
            "仅当需要对照用户自述画像/人群标签时考虑调用。"
            "pending / high_risk 条目不得自动写入茶饮 recommendations。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "include_pending": {
                    "type": "boolean",
                    "default": True,
                    "description": "为 false 时只返回 review_status=approved",
                }
            },
        },
        "return_type": "list[dict]",
        "safety": (
            "只读；high_risk 画像命中时循环外仍须空推荐并引导就医；"
            "不得把画像当开方或体质确诊依据。"
        ),
        "impl": "app.services.personas.list_personas",
    },
    {
        "name": "get_persona",
        "description": (
            "按画像 id 取一条详情。白名单外 id 必须失败，不得猜测或编造。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "persona_id": {
                    "type": "string",
                    "description": "personas.json 中的 id，如 pregnant",
                }
            },
            "required": ["persona_id"],
        },
        "return_type": "dict",
        "safety": (
            "未知 id → 明确错误；返回含 _query_meta.disclaimer；"
            "high_risk → 不得自动推荐。"
        ),
        "impl": "app.services.personas.get_persona",
    },
]


def iter_tool_specs() -> list[dict[str, Any]]:
    """供将来 registry 枚举；当前无副作用。"""
    return [dict(spec) for spec in TOOL_SPECS]


def resolve_tool(name: str) -> Callable[..., Any] | None:
    """按名解析可调用实现；未注册名返回 None（完整 registry 后可改抛错）。"""
    if name == "list_soup_templates":
        from app.services.soup_templates import list_soup_templates

        return list_soup_templates
    if name == "get_soup_template":
        from app.services.soup_templates import get_soup_template

        return get_soup_template
    if name == "list_personas":
        from app.services.personas import list_personas

        return list_personas
    if name == "get_persona":
        from app.services.personas import get_persona

        return get_persona
    return None
