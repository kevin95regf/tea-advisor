"""家用食疗汤模板的只读接口。

与 medication-reference 同隔离：仅供查阅，不进入茶饮 recommend / Agent2 自动拼方。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.services import soup_templates as soups

router = APIRouter()


@router.get("/soup-templates", summary="家用食疗汤模板目录")
async def soup_templates_index(include_pending: bool = True) -> dict:
    templates = soups.list_soup_templates(include_pending=include_pending)
    return {
        "templates": [
            {
                "id": t["id"],
                "display_name": t.get("display_name"),
                "kind": t.get("kind"),
                "review_status": t.get("review_status"),
                "component_count": len(t.get("components") or []),
            }
            for t in templates
        ],
        "disclaimer": soups.soup_templates_disclaimer(),
        "usage_policy": (
            "本接口只读；不进入 /api/analyze 推荐链路。"
            "pending 模板不得自动写入 recommendations；"
            "禁止把模板当方剂加减或编造超出 kitchen_amount_hint 的剂量。"
        ),
    }


@router.get("/soup-templates/{template_id}", summary="按 id 读取食疗汤模板")
async def soup_template_detail(template_id: str) -> dict:
    try:
        template = soups.get_soup_template(template_id)
    except soups.SoupTemplateNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "template": template,
        "disclaimer": soups.soup_templates_disclaimer(),
        "usage_policy": (
            "查询结果供查阅；若 review_status 非 approved，不得自动推荐。"
            "仅可引用 display_name 与 kitchen_amount_hint，不得自由加减组成。"
        ),
    }
