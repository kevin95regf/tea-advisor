"""编排器：双 Agent 串行调度 + 护栏 + 降级。

流程
----
1. 高风险人群检查（命中则直接返回提示，不调用推荐）
2. Agent1 解析饮食 → ParsedMeal
3. Agent2 基于 ParsedMeal + 体质生成推荐
4. 护栏校验（白名单 / 剂量 / 禁用表述 / 体质契合 / 冲泡方式）
5. Agent2 失败则降级到规则匹配（degraded=True）
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Sequence

from app.agents.agent1_diet import parse_diet
from app.agents.agent2_recommend import recommend as agent2_recommend
from app.agents.runtime import CredentialError
from app.config import get_settings
from app.domain.diet_signals import build_meal_signals, derive_meal_plan
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
    check_brew_adequacy,
    check_constitution_fit,
    detect_high_risk,
    herb_evidence,
    ready_constitutions,
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


def _ensure_constitution_ready(
    constitution: Constitution,
    avoid: Sequence[Constitution] | Sequence[str] = (),
) -> None:
    """挡住「数据未备齐」的体质，不让它走到需要配伍数据的那几步。

    这里是 HTTP / 终端 / 脚本的**唯一入口**（三者都经 `analyze`），
    闸门放在这一层，手搓 API 传 `constitution_override` 也绕不过去。

    **为什么不采用「回落平和质」**：终端对**未知 id** 确实是那么做的
    （`chat.py:pick_constitution`），但那是输入错误，退到默认值合理。
    这里不是输入错误，而是「这个体质的饮片数据还没备齐」——回落等于用平和质的
    答案冒充阴虚质的答案。项目讲的「降级而非失败」针对的是基础设施故障
    （没 Key、模型挂、JSON 解析失败），那些情况下降级还能给出有用的东西；
    而阴虚与平和需要的是不同的饮片，降级没有有意义的答案，只能显式拒绝。

    调用时机很讲究：**必须排在高风险分支之后**。安全提示（孕期/服药/儿童等）
    是"无条件可用"的，不该被数据就绪这种配置问题挡在前面——
    而它排在凭据校验之前，是因为体质问题连"填个 Key"都解决不了。

    **兼体质（`avoid`）同样要过闸**（B2 接入）。主导体质备齐、屏蔽集里某一型没备齐
    是可能的：屏蔽靠的是 `unsuitable_for`，而就绪判据看的是 `suitable_constitutions`，
    两者不是同一份数据。放过去就会出现"体质没数据却照样被拿来屏蔽"的静默不一致。
    """
    ready = ready_constitutions()
    for cid in [constitution, *avoid]:
        value = cid.value if isinstance(cid, Constitution) else str(cid)
        if value in ready:
            continue
        label = CONSTITUTION_LABELS.get(value, value)
        raise AnalyzeError(
            "CONSTITUTION_NOT_READY",
            f"「{label}」暂未启用：尚无可用的饮片配伍数据。"
            "请先补齐该体质的标注，在此之前该体质不会出现在选项中。",
        )


def _build_basis(
    constitution: Constitution,
    label: str,
    *,
    recs: list[Recommendation] | None = None,
    rule_hits: list[str] | None = None,
    guardrail_applied: list[str] | None = None,
) -> Basis:
    """`Basis` 的**唯一**构造点 —— 三处返回路径全走这里。

    统一入口让「新增一处 `Basis(...)` 却忘了带 `references`」在结构上不可能发生。
    这个风险是本项目真实踩过的形状：`matcher.build_basis` 曾是一份**没有任何调用点**
    的同名实现，改它等于没改，而输出表面完全看不出来。

    注意两点：
    - `references` 由**本次真正留下的推荐**（`recs`）决定，不看 Agent 原始输出 ——
      被护栏拦掉的饮片不该出现在公开依据里。
    - 高风险分支与「没识别出食物」分支**天然为空**（没有推荐），不要在这里补空列表，
      传空与不传等价，写了反而制造「这里也要管」的错觉。
    """
    names = {h.name for rec in (recs or []) for h in rec.herbs}
    return Basis(
        constitution=constitution,
        constitution_label=label,
        rule_hits=rule_hits or [],
        guardrail_applied=guardrail_applied or [],
        references=herb_evidence(names, constitution.value) if names else [],
    )


def _sanitize_recommendations(
    recs: list[Recommendation],
    constitution: Constitution,
    exclude_herbs: list[str],
    avoid: Sequence[str] = (),
) -> tuple[list[Recommendation], list[str]]:
    """护栏过滤。返回 (清洗后的推荐, 护栏说明)。

    `avoid`：兼体质屏蔽集（第 ④ 处接入点）。LLM 路径的候选集、离线路径的默认搭配
    都已各自硬剔除过，这里是最后一道 —— 兼体质同样要参与契合度提示。
    """
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
        fit = check_constitution_fit(
            [h.model_dump() for h in rec.herbs], constitution.value, avoid=avoid
        )
        for warning in fit.warnings:
            if warning not in rec.cautions:
                rec.cautions.append(warning)
        applied.extend(fit.warnings)

        # 冲泡方式要跟着饮片走：模型可能给须煎煮的饮片配了保温杯焖泡
        # （提示词已标「⚠️ 须煎煮」，但模型不保证听）。与剂量处理同构——
        # **自动换成煎煮方式并留痕**，不静默、也不整条作废。
        brew_fix = check_brew_adequacy([h.model_dump() for h in rec.herbs], rec.brew)
        if brew_fix.warnings:
            rec.brew = matcher.COOK_BREW
            for warning in brew_fix.warnings:
                applied.append(f"冲泡方式已调整为煎煮：{warning}")

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
    # 兼体质屏蔽集（B2 接入）。默认空 ⇒ 与既有调用方行为完全一致。
    avoid = [c.value for c in request.avoid_constitutions]
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
            basis=_build_basis(
                constitution,
                label,
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

    # ---------- 体质就绪闸门（刻意放在安全分支之后、凭据校验之前）----------
    # 放在安全分支之后：安全提示不该被"数据没备齐"这种配置问题挡掉。
    # 放在凭据校验之前：体质不可用不是填个 Key 能解决的，先报更根本的那一条。
    _ensure_constitution_ready(constitution, avoid)

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
            basis=_build_basis(constitution, label),
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

    # 确定性信号（冲击度 / 湿气度 / 寒热错杂）：Agent2 之前装配好，
    # 这样它会随 parsed 一起进提示词与响应体。口径⑦要求三条链路都显式接线。
    parsed.signals = build_meal_signals(request.text, parsed.foods)
    # 推荐优先级同样由代码派生（口径⑧），随 parsed 一起进提示词与响应体。
    parsed.plan = derive_meal_plan(parsed.signals, constitution.value, avoid=avoid)

    # ---------- 2. Agent2 ----------
    degraded = False
    degraded_reason: str | None = None
    agent2_ms: int | None = None
    rule_hits: list[str] = []
    user_message = ""

    try:
        recs, user_message, agent2_ms = agent2_recommend(
            parsed,
            constitution,
            request.exclude_herbs,
            api_key=user_key or None,
            avoid=avoid,
        )
        if not recs:
            raise RuntimeError("Agent2 返回空推荐")
    except Exception as exc:
        logger.warning("Agent2 失败，降级为规则匹配：%s", exc)
        degraded = True
        degraded_reason = str(exc)[:200]
        recs, user_message, rule_hits = matcher.fallback_recommend(
            parsed, constitution, request.exclude_herbs, avoid=avoid
        )

    # ---------- 3. 护栏 ----------
    cleaned, applied = _sanitize_recommendations(
        recs, constitution, request.exclude_herbs, avoid
    )

    # 护栏把推荐清空了 → 再用规则兜底一次
    if not cleaned and not degraded:
        degraded = True
        degraded_reason = "guardrail_removed_all"
        cleaned, user_message, rule_hits = matcher.fallback_recommend(
            parsed, constitution, request.exclude_herbs, avoid=avoid
        )
        cleaned, applied2 = _sanitize_recommendations(
            cleaned, constitution, request.exclude_herbs, avoid
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
        basis=_build_basis(
            constitution,
            label,
            recs=cleaned,
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
