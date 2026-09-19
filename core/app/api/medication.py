"""体质药物调理资料的只读接口。

资料与茶饮推荐链路严格隔离，只展示来源、原文级别和就医提示；
不提供剂量，也不会把方剂送入模型或推荐白名单。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.domain.enums import Constitution
from app.services import medication_reference as medication

router = APIRouter()


@router.get("/medication-reference", summary="药物调理资料目录")
async def medication_index() -> dict:
    return {
        "profiles": [
            {
                "id": item["id"],
                "name": item["label"],
                "clause": item["clause"],
                "principle": item["principle"],
            }
            for item in medication.list_profiles()
        ],
        "disclaimer": medication.medication_disclaimer(),
        "sources": medication.medication_sources(),
    }


@router.get("/medication-reference/{constitution}", summary="按体质读取药物调理资料")
async def medication_profile(constitution: Constitution) -> dict:
    profile = medication.get_profile(constitution.value)
    if profile is None:
        raise HTTPException(status_code=404, detail="未收录该体质的药物调理资料")
    return {
        "profile": profile,
        "display_text": medication.describe_profile(constitution.value),
        "disclaimer": medication.medication_disclaimer(),
        "sources": medication.medication_sources(),
        "usage_policy": (
            "本资料仅用于查看指南原文摘要，不构成用药建议，"
            "不进入茶饮推荐链路；具体用药必须由执业医师辨证决定。"
        ),
    }
