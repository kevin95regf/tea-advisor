"""Agent 1：饮食解析器。

职责边界（不可越界）
------------------
输入：用户原始口述文本
输出：ParsedMeal（结构化 JSON）
不做：不推荐茶饮、不判断体质、不评价饮食好坏、不臆造没识别出的食物
"""

from __future__ import annotations

import logging
import time
from functools import lru_cache

from app.agents import json_guard
from app.agents.runtime import get_runtime
from app.config import get_settings
from app.domain.enums import Flavor, MealTime, Nature
from app.domain.models import ParsedMeal
from app.services.food_lookup import (
    render_nature_change_rules,
    render_reference,
    resolve_food,
)

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def load_system_prompt() -> str:
    """加载系统提示词。改提示词后需重启进程（或调用 cache_clear）。"""
    path = get_settings().prompts_dir / "agent1_system.md"
    return path.read_text(encoding="utf-8")


def build_user_prompt(
    text: str,
    meal_time: MealTime | None = None,
    reference: str = "",
) -> str:
    """构造用户提示词。

    reference 是从 food_properties.json 查出的属性参考表（可能为空）。
    它放在 user 消息里而不是 system 提示词里，有两个原因：
      1. 保持 system 前缀稳定，KV 缓存继续命中；
      2. 参考表只包含用户提到的那几样食物，token 开销很小。
    """
    parts = [f"用户口述：{text}"]
    if meal_time and meal_time is not MealTime.UNKNOWN:
        parts.append(f"（已知时段：{meal_time.value}）")

    if reference:
        parts.append(
            "\n## 参考表\n"
            "下列食物的属性已经查证，**必须原样采用表中的值**，"
            "即使你的判断不同也以表为准：\n"
            f"{reference}"
        )
    else:
        parts.append(
            "\n## 参考表\n"
            "（本次没有命中预设参考表。请按烹饪方式与经验判断；"
            "拿不准的填 unknown 并放进 uncertain_items，不要猜。）"
        )

    # 处理方式对属性的影响（表里没写 variant 的条目靠这条兜）
    rules = render_nature_change_rules()
    if rules:
        parts.append(f"\n## 处理方式对属性的影响\n{rules}")

    parts.append("\n请按要求输出 JSON。")
    return "\n".join(parts)


def calibrate_parsed(parsed: ParsedMeal, text: str = "") -> ParsedMeal:
    """用确定性判定校准 LLM 的输出，并写入来源与置信度。

    这是三层架构的落地点：
      - 命中食性表 → source=rule/composed，属性以表为准（覆盖模型的值）
      - 未命中 → 保留模型判断，但标 source=llm / unverified=True / 置信度 0.3
      - 连模型也判不出 → source=unresolved / 置信度 0.1

    为什么必须覆盖而不是"参考"：模型有系统性偏差（曾把性温的茉莉花茶判成凉），
    表是人工整理的，出现分歧时以表为准。
    """
    if not parsed.foods:
        return parsed

    resolved_any = 0
    for food in parsed.foods:
        # text_hint 只取**该食物自己**的名字与备注。
        # 曾经这里传的是整句用户口述，导致跨食材串味：
        # 「中午吃了碗兰州拉面，还喝了杯麻辣烫」里的"辣"会把兰州拉面判成温。
        hint = " ".join(filter(None, [food.name, food.note or ""]))
        try:
            resolved = resolve_food(
                name=food.name,
                cooking=food.cooking.value if hasattr(food.cooking, "value") else food.cooking,
                llm_nature=food.nature.value if hasattr(food.nature, "value") else food.nature,
                text_hint=hint,
                # note 要一起传：模型可能把温度信息放在 note 里
                # （实测「去冰奶茶」会输出 name=奶茶, note=去冰）
                note=food.note or "",
            )
        except Exception:
            # 校准失败不能让整个解析失败，但必须留下可排查的痕迹
            logger.error("校准「%s」时出错，保留模型判断", food.name, exc_info=True)
            continue

        food.verification = resolved.verification
        if resolved.verification.source in ("rule", "composed"):
            resolved_any += 1
            # 表里有记录就以表为准，覆盖模型的值
            food.nature = Nature(resolved.nature)
            if resolved.flavors:
                food.flavors = [Flavor(f) for f in resolved.flavors if f in {x.value for x in Flavor}]

    # 整餐把握度：按逐项置信度重算，比模型自报的 confidence 更可解释
    confidences = [f.verification.confidence for f in parsed.foods]
    if confidences:
        parsed.confidence = round(sum(confidences) / len(confidences), 2)

    logger.info(
        "校准完成：%d/%d 项命中食性表，整餐把握度 %.2f",
        resolved_any,
        len(parsed.foods),
        parsed.confidence,
    )
    return parsed


def parse_diet(
    text: str,
    meal_time: MealTime | None = None,
    session_id: str | None = None,
    *,
    api_key: str | None = None,
) -> tuple[ParsedMeal, int, str]:
    """解析饮食口述。

    返回 (ParsedMeal, 耗时毫秒, session_id)。
    解析或校验失败会抛 JsonGuardError / RuntimeError，由上层决定是否降级。

    `api_key`：用户自带的 Key（HTTP 层从 Authorization 头取）。
    为空则由运行时回退到服务端兜底 Key。
    """
    settings = get_settings()
    runtime = get_runtime()
    system_prompt = load_system_prompt()
    # 先查表，把用户提到的食物属性作为参考注入
    reference = render_reference(text)
    user_prompt = build_user_prompt(text, meal_time, reference)
    # 会话 id 必须每次唯一。
    # 原因：dsh 的语义是「复用 harness + session id 就延续同一段持久对话」，
    # 若按内容 hash 生成，用户重复说同一句话会累积上文，污染解析结果。
    # （direct 后端无状态，此 id 只用于日志串联。）
    sid = session_id or f"ta-a1-{time.time_ns()}"

    first = runtime.run(
        user_prompt,
        system_prompt=system_prompt,
        session_id=sid,
        timeout_s=settings.agent1_timeout_s,
        api_key=api_key,
    )

    def retry_runner(fix_prompt: str) -> str:
        again = runtime.run(
            fix_prompt,
            system_prompt=system_prompt,
            session_id=f"{sid}-fix-{time.time_ns()}",
            timeout_s=settings.agent1_timeout_s,
            api_key=api_key,
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

    # 三层架构：用确定性判定校准模型的属性，并写入来源与置信度
    parsed = calibrate_parsed(parsed, text)

    return parsed, first.elapsed_ms, sid
