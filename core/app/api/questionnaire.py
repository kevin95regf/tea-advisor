"""中医九种体质问卷 API。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.domain.constitution_resolver import (
    UndeterminedConstitutionError,
    resolve_from_scores,
)

router = APIRouter()


def _require_questionnaire() -> tuple[Any, dict, Any]:
    """按需加载可选问卷子包；缺失时只禁用问卷端点。"""
    try:
        from tcm_constitution import score_questionnaire
        from tcm_constitution.questions import ANSWER_LABELS, questions_for_sex
    except ModuleNotFoundError as exc:
        if exc.name not in {"tcm_constitution", "tcm_constitution.questions"}:
            raise
        raise HTTPException(
            status_code=501,
            detail=(
                "体质问卷子包未安装；请在仓库根目录执行 "
                "core\\.venv\\Scripts\\python.exe -m pip install -e "
                "tcm-constitution-questionnaire"
            ),
        ) from exc
    return score_questionnaire, ANSWER_LABELS, questions_for_sex


class QuestionnaireRequest(BaseModel):
    sex: str = Field(pattern="^(female|male)$")
    answers: dict[str, int]


class ConstitutionResult(BaseModel):
    id: str
    name: str
    score: float
    status: str


class QuestionnaireResponse(BaseModel):
    dominant_constitution: str | None
    dominant_constitution_name: str | None
    avoid_constitutions: list[str] = Field(default_factory=list)
    resolution_note: str = ""
    requires_manual_selection: bool = False
    scores: list[ConstitutionResult]
    summary: dict


@router.post(
    "/questionnaire",
    response_model=QuestionnaireResponse,
    summary="提交九种体质问卷",
)
async def questionnaire_endpoint(request: QuestionnaireRequest) -> QuestionnaireResponse:
    score_questionnaire, _, _ = _require_questionnaire()
    try:
        result = score_questionnaire(request.answers, request.sex)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    scores = [
        ConstitutionResult(
            id=scale_key,
            name=info["name"],
            score=info["transformed_score"],
            status=info.get("status", "否"),
        )
        for scale_key, info in result["scores"].items()
    ]

    normalized_scores = dict(result["scores"])
    try:
        resolution = resolve_from_scores(normalized_scores)
    except UndeterminedConstitutionError as exc:
        return QuestionnaireResponse(
            dominant_constitution=None,
            dominant_constitution_name=None,
            resolution_note=str(exc),
            requires_manual_selection=True,
            scores=scores,
            summary=result["summary"],
        )

    return QuestionnaireResponse(
        dominant_constitution=resolution.primary.value,
        dominant_constitution_name=next(
            (
                item.name
                for item in scores
                if item.id == resolution.primary.value
            ),
            resolution.primary.value,
        ),
        avoid_constitutions=[item.value for item in resolution.avoid],
        resolution_note=resolution.note,
        scores=scores,
        summary=result["summary"],
    )


@router.get("/questionnaire/questions", summary="获取问卷题目")
async def get_questions(
    sex: str = Query(default="male", pattern="^(female|male)$"),
) -> dict:
    _, answer_labels, questions_for_sex = _require_questionnaire()
    try:
        questions = questions_for_sex(sex)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="sex 必须是 female 或 male") from exc
    return {
        "answer_labels": answer_labels,
        "questions": [
            {"id": item.id, "text": item.text, "sex": item.sex}
            for item in questions
        ],
    }
