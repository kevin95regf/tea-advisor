"""POST /api/analyze：饮食口述 → 茶饮推荐。

凭据来源
--------
用户的 API Key 通过 `Authorization: Bearer <key>` 头传入（前端填的 Key）。
**本项目不使用服务端内置 Key**：没带 Key 就返回 400 `NO_API_KEY`，
不会回退到任何配置文件里的凭据（曾有的「服务端兜底 Key」已按需求移除）。

安全约定（硬规则，配套测试见 tests/test_key_handling.py）
-------------------------------------------------------
* 本文件**不记录** Authorization 头，也不记录 Key。
* 异常详情里不得出现 Key：下面回传的 message 只来自 AnalyzeError，
  而 AnalyzeError 的构造方（orchestrator / 运行时）都不得拼接 Key。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException

from app.api.auth import extract_api_key
from app.domain.models import AnalyzeRequest, AnalyzeResponse
from app.services.orchestrator import AnalyzeError, analyze

logger = logging.getLogger(__name__)

router = APIRouter()

# 这些错误码属于"配置 / 凭据"问题，用 400 比 422 更贴切：
# 换个说法重试也没用，得先改配置或补 Key。
_CONFIG_ERROR_CODES = {"NO_API_KEY", "USER_KEY_UNSUPPORTED", "API_KEY_REJECTED"}


@router.post(
    "/analyze",
    response_model=AnalyzeResponse,
    summary="解析饮食并推荐药食同源茶饮",
    description=(
        "输入用户原始口述与体质，返回结构化解析结果与 1-3 条茶饮推荐。"
        "必须用 Authorization: Bearer ^<你的 DeepSeek API Key^> 头传入你自己的 Key；"
        "本服务不内置 Key，所以不带这个头会返回 400 NO_API_KEY。"
        "所有响应均携带 disclaimer 字段，不构成医疗建议。"
    ),
)
async def analyze_endpoint(
    request: AnalyzeRequest,
    authorization: str | None = Header(default=None),
) -> AnalyzeResponse:
    # 只取出裸 Key。这个值绝不进日志、绝不进响应体。
    user_key = extract_api_key(authorization)

    try:
        return analyze(request, api_key=user_key)
    except AnalyzeError as exc:
        # 注意：detail 里不放 authorization，也不放 user_key
        status = 400 if exc.code in _CONFIG_ERROR_CODES else 422
        raise HTTPException(
            status_code=status,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except Exception as exc:  # pragma: no cover - 兜底
        logger.exception("analyze 未预期错误")
        raise HTTPException(
            status_code=500,
            detail={"code": "INTERNAL_ERROR", "message": str(exc)[:200]},
        ) from exc
