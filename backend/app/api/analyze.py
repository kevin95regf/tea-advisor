"""POST /api/analyze：饮食口述 → 茶饮推荐。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.domain.models import AnalyzeRequest, AnalyzeResponse
from app.services.orchestrator import AnalyzeError, analyze

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/analyze",
    response_model=AnalyzeResponse,
    summary="解析饮食并推荐药食同源茶饮",
    description=(
        "输入用户原始口述与体质，返回结构化解析结果与 1-3 条茶饮推荐。"
        "所有响应均携带 disclaimer 字段，不构成医疗建议。"
    ),
)
async def analyze_endpoint(request: AnalyzeRequest) -> AnalyzeResponse:
    try:
        return analyze(request)
    except AnalyzeError as exc:
        # 解析失败：422 语义正确，前端可提示用户换个说法
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except Exception as exc:  # pragma: no cover - 兜底
        logger.exception("analyze 未预期错误")
        raise HTTPException(
            status_code=500,
            detail={"code": "INTERNAL_ERROR", "message": str(exc)[:200]},
        ) from exc
