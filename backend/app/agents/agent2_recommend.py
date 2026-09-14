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
from functools import lru_cache

from pydantic import BaseModel, Field

from app.agents import json_guard
from app.agents.runtime import get_runtime
from app.config import get_settings
from app.domain.enums import CONSTITUTION_LABELS, NATURE_LABELS, Constitution
from app.domain.models import BrewGuide, HerbInBlend, ParsedMeal, Recommendation
from app.domain.safety import filter_by_constitution

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


def _candidate_lines(constitution: Constitution, limit: int = 12) -> str:
    """把候选饮片渲染成紧凑清单，注入提示词。这是收敛模型自由度的关键。"""
    candidates = filter_by_constitution(constitution.value, limit=limit)
    lines: list[str] = []
    for item in candidates:
        nature = NATURE_LABELS.get(item.get("nature", "unknown"), "未知")
        flavors = "/".join(item.get("flavors", []))
        effects = "、".join(item.get("effects", []))
        lines.append(
            f"- {item['name']}（{nature}，{flavors}，归{'/'.join(item.get('meridians', []))}）"
            f"｜功效方向：{effects}｜单日上限：{item.get('max_daily_g')}g"
        )
    return "\n".join(lines)


def build_user_prompt(
    parsed: ParsedMeal,
    constitution: Constitution,
    exclude_herbs: list[str] | None = None,
) -> str:
    """构造 Agent2 的输入。注意：这里传的是 Agent1 的 JSON，不是用户原话。"""
    brief = _constitution_brief(constitution)
    exclude = "、".join(exclude_herbs) if exclude_herbs else "无"

    return (
        "## 用户背景\n"
        f"体质：{brief.get('label')}（{brief.get('one_line', '')}）\n"
        f"饮食原则：{'；'.join(brief.get('principles', []))}\n"
        f"应避免：{'、'.join(brief.get('avoid', []))}\n"
        f"用户已排除的饮片：{exclude}\n\n"
        "## 这一餐（由解析器输出）\n"
        f"```json\n{parsed.model_dump_json(indent=2)}\n```\n\n"
        "## 可选饮片清单（只能从这里挑，不得超出）\n"
        f"{_candidate_lines(constitution)}\n\n"
        "请按要求输出 JSON。"
    )


def recommend(
    parsed: ParsedMeal,
    constitution: Constitution,
    exclude_herbs: list[str] | None = None,
    session_id: str | None = None,
) -> tuple[list[Recommendation], str, int]:
    """生成推荐。

    返回 (推荐列表, user_message, 耗时毫秒)。
    """
    settings = get_settings()
    runtime = get_runtime()
    system_prompt = load_system_prompt()
    user_prompt = build_user_prompt(parsed, constitution, exclude_herbs)
    sid = session_id or f"ta-a2-{abs(hash(user_prompt)) % 10**8}"

    first = runtime.run(
        user_prompt,
        system_prompt=system_prompt,
        session_id=sid,
        timeout_s=settings.agent2_timeout_s,
    )

    def retry_runner(fix_prompt: str) -> str:
        again = runtime.run(
            fix_prompt,
            system_prompt=system_prompt,
            session_id=f"{sid}-fix",
            timeout_s=settings.agent2_timeout_s,
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
