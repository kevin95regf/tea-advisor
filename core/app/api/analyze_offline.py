"""POST /api/analyze-offline：只用本地数据和规则生成建议。"""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.domain.diet_signals import (
    build_meal_signals,
    derive_meal_plan,
    load_nature_keywords,
)
from app.domain.enums import CONSTITUTION_LABELS, Constitution, MealTime, Nature
from app.domain.meal_time import guess_meal_time
from app.domain.models import AnalyzeResponse, Meta, ParsedFood, ParsedMeal, Verification
from app.domain.safety import (
    detect_high_risk,
    ready_constitutions,
    scan_free_text,
)
from app.services import matcher
from app.services.food_lookup import match_foods, resolve_in_context
from app.services.orchestrator import _build_basis

logger = logging.getLogger(__name__)
router = APIRouter()


class OfflineAnalyzeRequest(BaseModel):
    text: str = Field(default="", max_length=500)
    constitution: Constitution | None = None
    constitution_override: Constitution | None = None
    avoid_constitutions: list[Constitution] = Field(default_factory=list)
    exclude_herbs: list[str] = Field(default_factory=list)


def _match_nature_from_text(text: str) -> Nature:
    """按关键词粗判整餐四性（离线路径用）。

    ⚠️ 三组词的**真源在 `core/data/diet_signals.json` 的 `nature_keywords` 段**
    （2026-09-21 搬迁，**值逐字未改**）—— 它们原先是与 `RULES` 并存的**第三份**
    代码常量表，改一处不改另一处就会静默漂移（`docs/analyze-offline-plan.md` 记过这条）。
    权重（cold／hot 各 2、warm 各 1）仍是本函数的评分参数，未下沉。
    """
    words = load_nature_keywords()
    cold_kw = words["cold"]
    hot_kw = words["hot"]
    warm_kw = words["warm"]
    cold = sum(2 for word in cold_kw if word in text)
    hot = sum(2 for word in hot_kw if word in text)
    warm = sum(1 for word in warm_kw if word in text)
    if cold > hot and cold > warm:
        return Nature.COLD
    if hot > cold:
        return Nature.HOT
    if warm > cold:
        return Nature.WARM
    return Nature.UNKNOWN


@router.post(
    "/analyze-offline",
    response_model=AnalyzeResponse,
    summary="离线规则推荐（不需要 API Key）",
)
async def analyze_offline_endpoint(request: OfflineAnalyzeRequest) -> AnalyzeResponse:
    started = time.perf_counter()
    text = request.text.strip()
    constitution = (
        request.constitution_override
        or request.constitution
        or Constitution.BALANCED
    )
    if constitution.value not in ready_constitutions():
        raise HTTPException(
            status_code=422,
            detail={
                "code": "CONSTITUTION_NOT_READY",
                "message": f"{CONSTITUTION_LABELS[constitution.value]}的配伍数据尚未备齐。",
            },
        )

    if not text:
        parsed = ParsedMeal()
        return AnalyzeResponse(
            request_id=uuid.uuid4().hex[:16],
            parsed=parsed,
            recommendations=[],
            basis=_build_basis(constitution, CONSTITUTION_LABELS[constitution.value]),
            meta=Meta(
                total_ms=0,
                model="offline-rules",
                degraded=True,
                degraded_reason="输入为空",
                key_source="not_used",
                backend="offline",
            ),
            user_message="请先说说你吃了什么。",
        )

    foods: list[ParsedFood] = []
    for entry in match_foods(text):
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        # 不能再写 resolve_food(name=name, note=text)：把整句口述当备注喂进
        # 备注通道，温度词会被算到每一样食物头上，且剥掉温度词后的名字会
        # 指向别的条目（实测「炸鸡 冰可乐」里炸鸡被判成寒，见 E15）。
        # 改用按位置归属的入口：每样食物只认领紧贴自己命中词之前的温度词。
        resolved = resolve_in_context(text, entry)
        foods.append(
            ParsedFood(
                name=name,
                nature=resolved.nature,
                flavors=resolved.flavors,
                verification=Verification(
                    source=resolved.verification.source,
                    confidence=resolved.verification.confidence,
                    unverified=resolved.verification.unverified,
                    detail=resolved.verification.detail,
                ),
            )
        )

    parsed = ParsedMeal(
        foods=foods,
        meal_time=guess_meal_time(text),
        overall_nature=_match_nature_from_text(text),
        confidence=0.9 if foods else 0.3,
        summary=(
            "（离线模式：关键词匹配 + 查表）这一餐认出 " + "、".join(f.name for f in foods[:4])
            if foods
            else "（离线模式：关键词匹配 + 查表）没有认出表内食物，结果仅供粗略参考"
        ),
    )
    # 与 LLM 链路（orchestrator）同一装配入口，避免「有 Key / 没 Key 两套结论」（口径⑦）。
    parsed.signals = build_meal_signals(text, foods)
    parsed.plan = derive_meal_plan(
        parsed.signals,
        constitution.value,
        avoid=[item.value for item in request.avoid_constitutions],
    )

    risks = detect_high_risk(text)
    if risks:
        elapsed = int((time.perf_counter() - started) * 1000)
        return AnalyzeResponse(
            request_id=uuid.uuid4().hex[:16],
            parsed=parsed,
            recommendations=[],
            basis=_build_basis(
                constitution,
                CONSTITUTION_LABELS[constitution.value],
                guardrail_applied=[f"命中高风险关键词：{'、'.join(risks)}"],
            ),
            meta=Meta(
                agent1_ms=elapsed,
                agent2_ms=0,
                total_ms=elapsed,
                model="offline-rules",
                degraded=True,
                degraded_reason="高风险拦截",
                key_source="not_used",
                backend="offline",
            ),
            user_message="当前描述涉及需要谨慎处理的情况，本程序不提供茶饮建议，请先咨询执业医师。",
        )

    recs, message, rule_hits = matcher.fallback_recommend(
        parsed,
        constitution,
        request.exclude_herbs,
        avoid=[item.value for item in request.avoid_constitutions],
    )
    guardrail: list[str] = []
    kept = []
    for rec in recs:
        result = scan_free_text(" ".join([rec.title, rec.fit_reason, *rec.cautions]))
        if result.ok:
            kept.append(rec)
        else:
            guardrail.extend(result.blocked)
            logger.warning("离线推荐未通过文案安全检查：%s", result.blocked)
    if guardrail:
        recs = kept
        message = "部分推荐未通过安全检查，已从结果中移除。"

    elapsed = int((time.perf_counter() - started) * 1000)
    return AnalyzeResponse(
        request_id=uuid.uuid4().hex[:16],
        parsed=parsed,
        recommendations=recs,
        basis=_build_basis(
            constitution,
            CONSTITUTION_LABELS[constitution.value],
            recs=recs,
            rule_hits=rule_hits,
            guardrail_applied=guardrail,
        ),
        meta=Meta(
            agent1_ms=elapsed,
            agent2_ms=0,
            total_ms=elapsed,
            model="offline-rules",
            degraded=True,
            degraded_reason="离线模式：不调用模型",
            key_source="not_used",
            backend="offline",
        ),
        user_message=message,
    )
