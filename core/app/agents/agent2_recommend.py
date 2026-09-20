"""Agent 2：中医推荐器。

职责边界（不可越界）
------------------
输入：Agent1 的 ParsedMeal + 用户体质 + 白名单候选饮片
输出：Recommendation 列表（含用量、冲泡、理由、注意）
不做：不开方剂、不诊断、不承诺疗效、不推荐白名单外的药材、不超剂量
"""

from __future__ import annotations

import json
import logging
import time
from functools import lru_cache
from typing import Sequence

from pydantic import BaseModel, Field

from app.agents import json_guard
from app.agents.runtime import get_runtime
from app.config import get_settings
from app.domain.enums import CONSTITUTION_LABELS, NATURE_LABELS, Constitution
from app.domain.models import BrewGuide, HerbInBlend, ParsedMeal, Recommendation
from app.domain.safety import filter_by_constitution, herb_requires_cooking
from app.services.food_lookup import CONF_SHOW_THRESHOLD

logger = logging.getLogger(__name__)


class Agent2Output(BaseModel):
    """Agent2 的原始输出结构（比接口层薄一层）。"""

    recommendations: list[Recommendation] = Field(default_factory=list)
    user_message: str = ""


@lru_cache(maxsize=1)
def load_system_prompt() -> str:
    path = get_settings().prompts_dir / "agent2_system.md"
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def load_constitution_table() -> dict:
    path = get_settings().data_dir / "constitution.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _constitution_brief(constitution: Constitution) -> dict:
    table = load_constitution_table()
    for item in table.get("constitutions", []):
        if item["id"] == constitution.value:
            return item
    return {"id": constitution.value, "label": CONSTITUTION_LABELS.get(constitution.value, "")}


def _candidate_lines(
    constitution: Constitution,
    limit: int = 12,
    *,
    avoid: Sequence[str] = (),
) -> str:
    """把候选饮片渲染成紧凑清单，注入提示词。这是收敛模型自由度的关键。

    标了 `brewing.requires_cooking` 的饮片额外带一句「⚠️ 须煎煮」——
    这类饮片质地坚实，保温杯焖泡出不了味，而模型看不到 `brewing` 原文
    （曾因此把「茯苓 + 保温杯焖 8 分钟」当成正面示例教出去）。
    未标记须煎煮的饮片渲染结果**逐字节不变**，提示词 diff 最小。

    `avoid`（兼体质屏蔽集）直接透传给 `filter_by_constitution`：模型**看不到**它，
    屏蔽发生在候选集构造阶段 —— 看不见的饮片就不可能被选上。默认空 ⇒ 渲染结果不变。
    """
    candidates = filter_by_constitution(
        constitution.value, limit=limit, avoid=[str(a) for a in avoid]
    )
    lines: list[str] = []
    for item in candidates:
        nature = NATURE_LABELS.get(item.get("nature", "unknown"), "未知")
        flavors = "/".join(item.get("flavors", []))
        effects = "、".join(item.get("effects", []))
        cook_hint = "｜⚠️ 须煎煮，不可只冲泡" if herb_requires_cooking(item) else ""
        lines.append(
            f"- {item['name']}（{nature}，{flavors}，归{'/'.join(item.get('meridians', []))}）"
            f"｜功效方向：{effects}｜单日上限：{item.get('max_daily_g')}g{cook_hint}"
        )
    return "\n".join(lines)


def _build_unverified_section(parsed: ParsedMeal) -> str:
    """把"未经验证"的食物单独列成一节，明确禁止作为搭配计算依据。

    这是三层架构第三层的隔离手段：推测结果保留在解析结果里（信息不丢失），
    但告知推荐器不得据此计算，避免未经审核的属性影响推荐方向。
    """
    unverified = [
        f
        for f in parsed.foods
        if getattr(f, "verification", None) and f.verification.unverified
    ]
    if not unverified:
        return ""

    lines = ["## 以下食物的食性未经验证（不得作为搭配计算依据）"]
    for food in unverified:
        v = food.verification
        reason = {
            "llm": "模型推测",
            "unresolved": "无法判定",
        }.get(v.source, "表内条目尚未人工审核")
        if v.confidence is not None and v.confidence < CONF_SHOW_THRESHOLD:
            nature_text = "低于阈值，不予采信"
        else:
            nature_text = NATURE_LABELS.get(food.nature.value, "未知")
        lines.append(f"- {food.name}：{nature_text}（{reason}，置信度 {v.confidence}）")

    lines.append(
        "\n约束：\n"
        "1. 上述食物**不得作为选择饮片或计算用量的依据**，也不要因为它们而改变搭配方向。\n"
        "2. 但如果你的推荐与该食物**直接相关**（例如正因为它偏于寒凉才要温中），"
        "必须在 `fit_reason` 或 `cautions` 中注明「**此项食性未经验证**」。"
    )
    return "\n".join(lines)


def build_user_prompt(
    parsed: ParsedMeal,
    constitution: Constitution,
    exclude_herbs: list[str] | None = None,
    *,
    avoid: Sequence[str] = (),
) -> str:
    """构造 Agent2 的输入。注意：这里传的是 Agent1 的 JSON，不是用户原话。"""
    brief = _constitution_brief(constitution)
    exclude = "、".join(exclude_herbs) if exclude_herbs else "无"

    parts = [
        "## 用户背景\n"
        f"体质：{brief.get('label')}（{brief.get('one_line', '')}）\n"
        f"饮食原则：{'；'.join(brief.get('principles', []))}\n"
        f"应避免：{'、'.join(brief.get('avoid', []))}\n"
        f"用户已排除的饮片：{exclude}",
        "## 这一餐（由解析器输出）\n"
        f"```json\n{parsed.model_dump_json(indent=2)}\n```",
        "## 可选饮片清单（只能从这里挑，不得超出）\n"
        f"{_candidate_lines(constitution, avoid=avoid)}",
    ]

    unverified_section = _build_unverified_section(parsed)
    if unverified_section:
        parts.append(unverified_section)

    parts.append("请按要求输出 JSON。")
    return "\n\n".join(parts)


def recommend(
    parsed: ParsedMeal,
    constitution: Constitution,
    exclude_herbs: list[str] | None = None,
    session_id: str | None = None,
    *,
    api_key: str | None = None,
    avoid: Sequence[str] = (),
) -> tuple[list[Recommendation], str, int]:
    """生成推荐。

    返回 (推荐列表, user_message, 耗时毫秒)。

    `api_key`：调用方提供的 Key（HTTP 层从 Authorization 头取，
    终端与脚本从环境变量取）。本项目**不使用服务端内置 Key**，为空会直接失败。

    `avoid`：兼体质屏蔽集（B2 接入）。只影响候选集，不影响体质简述与饮食原则 ——
    收敛方向仍由 `constitution` 唯一决定。
    """
    settings = get_settings()
    runtime = get_runtime()
    system_prompt = load_system_prompt()
    user_prompt = build_user_prompt(parsed, constitution, exclude_herbs, avoid=avoid)
    # 每次调用都用全新会话 id，避免重复内容累积上文（见 agent1 同样说明）
    sid = session_id or f"ta-a2-{time.time_ns()}"

    first = runtime.run(
        user_prompt,
        system_prompt=system_prompt,
        session_id=sid,
        timeout_s=settings.agent2_timeout_s,
        api_key=api_key,
    )

    def retry_runner(fix_prompt: str) -> str:
        again = runtime.run(
            fix_prompt,
            system_prompt=system_prompt,
            session_id=f"{sid}-fix-{time.time_ns()}",
            timeout_s=settings.agent2_timeout_s,
            api_key=api_key,
        )
        return again.text

    output, retries = json_guard.validate_with_retry(
        Agent2Output,
        first.text,
        retry_runner=retry_runner,
        original_prompt=user_prompt,
        max_retry=1,
    )
    if retries:
        logger.info("Agent2 第 %d 次重试后解析成功", retries)

    return output.recommendations, output.user_message, first.elapsed_ms


__all__ = [
    "Agent2Output",
    "BrewGuide",
    "HerbInBlend",
    "build_user_prompt",
    "load_constitution_table",
    "load_system_prompt",
    "recommend",
]
