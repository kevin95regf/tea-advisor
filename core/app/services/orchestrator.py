"""编排器：双 Agent 串行调度 + 护栏 + 降级。

流程
----
1. 高风险人群检查（命中则直接返回提示，不调用推荐）
2. Agent1 解析饮食 → ParsedMeal
3. Agent2 基于 ParsedMeal + 体质生成推荐
4. 护栏校验（白名单 / 剂量 / 禁用表述 / 体质契合）
5. Agent2 失败则降级到规则匹配（degraded=True）
"""

from __future__ import annotations

import logging
import time
import uuid

from app.agents.agent1_diet import parse_diet
from app.agents.agent2_recommend import recommend as agent2_recommend
from app.agents.runtime import CredentialError
from app.config import get_settings
from app.domain.enums import CONSTITUTION_LABELS, Constitution, MealTime
from app.domain.models import (
    AnalyzeRequest,
    AnalyzeResponse,
    Basis,
    Disclaimer,
    Meta,
    ParsedMeal,
    Recommendation,
)
from app.domain.safety import (
    check_blend,
    check_constitution_fit,
    detect_high_risk,
    scan_free_text,
)
from app.services import matcher

logger = logging.getLogger(__name__)


class AnalyzeError(Exception):
    """编排失败，携带对外错误码。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _constitution_of(request: AnalyzeRequest) -> Constitution:
    # demo 阶段：请求里带就用，否则默认平和质（正式版从用户画像读）
    return request.constitution_override or Constitution.BALANCED


def _sanitize_recommendations(
    recs: list[Recommendation],
    constitution: Constitution,
    exclude_herbs: list[str],
) -> tuple[list[Recommendation], list[str]]:
    """护栏过滤。返回 (清洗后的推荐, 护栏说明)。"""
    applied: list[str] = []
    cleaned: list[Recommendation] = []

    for rec in recs:
        herbs = [h.model_dump() for h in rec.herbs]
        result = check_blend(herbs, exclude_herbs)

        blocked_names = {
            item.split("：", 1)[0] for item in result.blocked
        }
        applied.extend(result.blocked)
        applied.extend(result.warnings)

        if blocked_names:
            # 剔除被拦的饮片；剔空则整条推荐作废
            kept = [h for h in rec.herbs if h.name not in blocked_names]
            if not kept:
                logger.warning("推荐「%s」的饮片全部被护栏拦截，作废", rec.title)
                continue
            rec.herbs = kept

        # 文案层禁用表述检查
        text_blob = " ".join([rec.title, rec.fit_reason, *rec.cautions])
        text_result = scan_free_text(text_blob)
        if not text_result.ok:
            applied.extend(text_result.blocked)
            logger.warning("推荐「%s」含禁用表述，作废", rec.title)
            continue

        # 体质契合度提示
        fit = check_constitution_fit([h.model_dump() for h in rec.herbs], constitution.value)
        for warning in fit.warnings:
            if warning not in rec.cautions:
                rec.cautions.append(warning)
        applied.extend(fit.warnings)

        cleaned.append(rec)

    return cleaned, applied


def analyze(request: AnalyzeRequest, *, api_key: str | None = None) -> AnalyzeResponse:
    """执行完整分析流程。

    `api_key`：调用方传入的 API Key（HTTP 层从 `Authorization` 头取，
    终端与脚本从环境变量取）。**本项目不使用服务端内置 Key**，所以这里为空
    就意味着这次请求无法调用模型，直接报 `NO_API_KEY`。
    """
    settings = get_settings()
    request_id = uuid.uuid4().hex[:16]
    started = time.perf_counter()

    user_key = (api_key or "").strip()
    # 只要走到调用模型这一步，用的就是调用方的 Key。字段保留是为了让前端
    # 能区分"本次用了你的 Key"与"本次根本没调用模型"（高风险分支）。
    key_source = "user" if user_key else "not_used"

    constitution = _constitution_of(request)
    label = CONSTITUTION_LABELS.get(constitution.value, constitution.value)
    disclaimer = Disclaimer()

    # ---------- 0. 高风险人群（放在凭据校验【之前】）----------
    # 这个分支不调用模型、不花一分钱，所以必须无条件可用：
    # 一个还没填 Key 的用户输入"我怀孕了"，应该看到"请先咨询执业医师"，
    # 而不是"缺少 API Key"。安全提示的优先级高于配置校验。
    high_risk = detect_high_risk(request.text)
    if high_risk:
        parsed = ParsedMeal(
            meal_time=request.meal_time or MealTime.UNKNOWN,
            summary="你提到了需要特别留意的情况",
        )
        return AnalyzeResponse(
            request_id=request_id,
            parsed=parsed,
            recommendations=[],
            basis=Basis(
                constitution=constitution,
                constitution_label=label,
                guardrail_applied=[f"命中高风险关键词：{'、'.join(high_risk)}"],
            ),
            disclaimer=disclaimer,
            meta=Meta(
                total_ms=int((time.perf_counter() - started) * 1000),
                model=settings.model,
                degraded=True,
                degraded_reason="high_risk_group",
                # 本分支不调用模型，key_source 如实标 not_used，
                # 免得前端显示"本次使用你的 Key"却根本没有调用
                key_source="not_used",
                backend=settings.backend,
            ),
            user_message=(
                "你提到的孕期/哺乳/经期/儿童或慢性病、正在服药等情况，"
                "不适合按日常茶饮自行调理，请先咨询执业医师或药师。"
            ),
        )

    # ---------- 凭据校验（刻意放在安全分支之后）----------
    # 本项目不使用服务端内置 Key，所以没带 Key 就无法调用模型。
    if not user_key:
        raise AnalyzeError("NO_API_KEY", settings.missing_credentials_hint())
    if not settings.user_key_supported:
        raise AnalyzeError(
            "USER_KEY_UNSUPPORTED",
            f"当前后端（{settings.backend}）不支持逐请求 API Key"
            "（dsh 的 Key 与子进程绑定，一个进程只能有一个 Key）。"
            "请把 TA_BACKEND 设为 direct（默认）后重试。",
        )

    # ---------- 1. Agent1 ----------
    try:
        parsed, agent1_ms, _ = parse_diet(
            request.text, request.meal_time, api_key=user_key
        )
    except CredentialError as exc:
        # 凭据被拒（Key 无效 / 余额不足 / 无权限）——这不是"没看懂你吃了什么"，
        # 必须回一个让人去改 Key 的错误码，前端据此把焦点移到 Key 输入框。
        logger.warning("凭据被模型服务方拒绝")
        raise AnalyzeError("API_KEY_REJECTED", str(exc)) from exc
    except Exception as exc:
        logger.exception("Agent1 失败")
        raise AnalyzeError(
            "AGENT1_FAILED", f"饮食解析失败：{exc}"
        ) from exc

    # 完全没识别出食物
    if not parsed.foods:
        return AnalyzeResponse(
            request_id=request_id,
            parsed=parsed,
            recommendations=[],
            basis=Basis(constitution=constitution, constitution_label=label),
            disclaimer=disclaimer,
            meta=Meta(
                agent1_ms=agent1_ms,
                total_ms=int((time.perf_counter() - started) * 1000),
                model=settings.model,
                key_source=key_source,
                backend=settings.backend,
            ),
            user_message="没太看明白你吃了什么，可以再说具体一点，比如「中午吃了碗牛肉面加一杯冰可乐」。",
        )

    # ---------- 2. Agent2 ----------
    degraded = False
    degraded_reason: str | None = None
    agent2_ms: int | None = None
    rule_hits: list[str] = []
    user_message = ""

    try:
        recs, user_message, agent2_ms = agent2_recommend(
            parsed, constitution, request.exclude_herbs, api_key=user_key or None
        )
        if not recs:
            raise RuntimeError("Agent2 返回空推荐")
    except Exception as exc:
        logger.warning("Agent2 失败，降级为规则匹配：%s", exc)
        degraded = True
        degraded_reason = str(exc)[:200]
        recs, user_message, rule_hits = matcher.fallback_recommend(
            parsed, constitution, request.exclude_herbs
        )

    # ---------- 3. 护栏 ----------
    cleaned, applied = _sanitize_recommendations(
        recs, constitution, request.exclude_herbs
    )

    # 护栏把推荐清空了 → 再用规则兜底一次
    if not cleaned and not degraded:
        degraded = True
        degraded_reason = "guardrail_removed_all"
        cleaned, user_message, rule_hits = matcher.fallback_recommend(
            parsed, constitution, request.exclude_herbs
        )
        cleaned, applied2 = _sanitize_recommendations(
            cleaned, constitution, request.exclude_herbs
        )
        applied.extend(applied2)

    total_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "analyze 完成 request_id=%s agent1=%sms agent2=%sms total=%sms degraded=%s",
        request_id, agent1_ms, agent2_ms, total_ms, degraded,
    )

    return AnalyzeResponse(
        request_id=request_id,
        parsed=parsed,
        recommendations=cleaned,
        basis=Basis(
            constitution=constitution,
            constitution_label=label,
            rule_hits=rule_hits,
            guardrail_applied=applied,
        ),
        disclaimer=disclaimer,
        meta=Meta(
            agent1_ms=agent1_ms,
            agent2_ms=agent2_ms,
            total_ms=total_ms,
            model=settings.model,
            degraded=degraded,
            degraded_reason=degraded_reason,
            key_source=key_source,
            backend=settings.backend,
        ),
        user_message=user_message,
    )
