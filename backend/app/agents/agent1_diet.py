"""Agent 1：饮食解析器。

职责边界（不可越界）
------------------
输入：用户原始口述文本
输出：ParsedMeal（结构化 JSON）
不做：不推荐茶饮、不判断体质、不评价饮食好坏、不臆造没识别出的食物
"""

from __future__ import annotations

import logging
from functools import lru_cache

from app.agents import json_guard
from app.agents.runtime import get_runtime
from app.config import get_settings
from app.domain.enums import MealTime
from app.domain.models import ParsedMeal

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def load_system_prompt() -> str:
    """加载系统提示词。改提示词后需重启进程（或调用 cache_clear）。"""
    path = get_settings().prompts_dir / "agent1_system.md"
    return path.read_text(encoding="utf-8")


def build_user_prompt(text: str, meal_time: MealTime | None = None) -> str:
    """构造用户提示词。"""
    parts = [f"用户口述：{text}"]
    if meal_time and meal_time is not MealTime.UNKNOWN:
        parts.append(f"（已知时段：{meal_time.value}）")
    parts.append("\n请按要求输出 JSON。")
    return "\n".join(parts)


def parse_diet(
    text: str,
    meal_time: MealTime | None = None,
    session_id: str | None = None,
) -> tuple[ParsedMeal, int, str]:
    """解析饮食口述。

    返回 (ParsedMeal, 耗时毫秒, session_id)。
    解析或校验失败会抛 JsonGuardError / RuntimeError，由上层决定是否降级。
    """
    settings = get_settings()
    runtime = get_runtime()
    system_prompt = load_system_prompt()
    user_prompt = build_user_prompt(text, meal_time)
    sid = session_id or f"ta-a1-{abs(hash(text)) % 10**8}"

    first = runtime.run(
        user_prompt,
        system_prompt=system_prompt,
        session_id=sid,
        timeout_s=settings.agent1_timeout_s,
    )

    def retry_runner(fix_prompt: str) -> str:
        again = runtime.run(
            fix_prompt,
            system_prompt=system_prompt,
            session_id=f"{sid}-fix",
            timeout_s=settings.agent1_timeout_s,
        )
        return again.text

    parsed, retries = json_guard.validate_with_retry(
        ParsedMeal,
        first.text,
        retry_runner=retry_runner,
        original_prompt=user_prompt,
        max_retry=1,
    )
    if retries:
        logger.info("Agent1 第 %d 次重试后解析成功", retries)

    # 用户显式给了时段就尊重用户
    if meal_time and meal_time is not MealTime.UNKNOWN:
        parsed.meal_time = meal_time

    return parsed, first.elapsed_ms, sid
