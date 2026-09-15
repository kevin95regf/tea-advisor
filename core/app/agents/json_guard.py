"""JSON 解析护栏。

LLM 只会返回字符串，"输出结构化 JSON"必须靠这一层兜住：
剥离代码围栏 → 提取 JSON 主体 → schema 校验 → 失败重试一次。

本文件是整个项目最容易被低估的部分，务必配测试（tests/test_json_guard.py）。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# 匹配 ```json ... ``` 或 ``` ... ``` 围栏
_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.*?)\s*```", re.DOTALL)


class JsonGuardError(ValueError):
    """所有无法得到合法 JSON 的情况都抛这个，附带原始文本便于排查。"""

    def __init__(self, message: str, raw: str = "", errors: Any = None) -> None:
        super().__init__(message)
        self.raw = raw
        self.errors = errors


def strip_fence(text: str) -> str:
    """剥离 markdown 代码围栏。"""
    text = (text or "").strip()
    match = _FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    return text


def extract_json_object(text: str) -> str:
    """从任意文本中提取第一个完整的 JSON 对象（大括号配平，忽略字符串内的括号）。"""
    text = strip_fence(text)
    start = text.find("{")
    if start == -1:
        raise JsonGuardError("未找到 JSON 起始符 '{'", raw=text)

    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]

    raise JsonGuardError("JSON 对象未闭合（可能被 max_tokens 截断）", raw=text)


def parse_lenient(text: str) -> dict:
    """宽松解析：先原样试，再剥围栏，再提取对象。"""
    candidates: list[str] = []
    raw = (text or "").strip()
    candidates.append(raw)
    candidates.append(strip_fence(raw))
    try:
        candidates.append(extract_json_object(raw))
    except JsonGuardError:
        pass

    last_error: Exception | None = None
    for candidate in candidates:
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if isinstance(data, dict):
            return data
        last_error = JsonGuardError(f"顶层不是 JSON 对象，而是 {type(data).__name__}")

    raise JsonGuardError(
        f"无法解析为 JSON：{last_error}", raw=raw, errors=str(last_error)
    )


def validate(model: type[T], text: str) -> T:
    """解析 + 校验。任一步失败抛 JsonGuardError。"""
    data = parse_lenient(text)
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise JsonGuardError(
            f"字段校验失败：{exc.error_count()} 处问题", raw=text, errors=exc.errors()
        ) from exc


def repair_prompt(original_prompt: str, bad_text: str, errors: Any) -> str:
    """构造重试提示：把错误原文和校验信息回灌给模型。"""
    detail = ""
    if errors:
        try:
            detail = json.dumps(errors, ensure_ascii=False, default=str)[:1200]
        except Exception:
            detail = str(errors)[:1200]

    return (
        f"{original_prompt}\n\n"
        "---\n\n"
        "你上一次的输出无法通过校验，请修正后只输出一个 JSON 对象（不要解释，不要代码围栏）。\n\n"
        f"上一次的输出：\n{bad_text[:1500]}\n\n"
        f"校验报错：\n{detail}\n"
    )


def validate_with_retry(
    model: type[T],
    text: str,
    *,
    retry_runner=None,
    original_prompt: str = "",
    max_retry: int = 1,
) -> tuple[T, int]:
    """校验失败时重试。

    返回 (校验后的对象, 重试次数)。
    retry_runner 是一个可调用对象：接收修正后的提示词，返回模型文本。
    不传 retry_runner 时只做一次解析（用于单元测试）。
    """
    attempt = 0
    current = text
    last_error: JsonGuardError | None = None

    while attempt <= max_retry:
        try:
            return validate(model, current), attempt
        except JsonGuardError as exc:
            last_error = exc
            attempt += 1
            if attempt > max_retry or retry_runner is None:
                break
            logger.warning("JSON 校验失败，准备重试（第 %d 次）：%s", attempt, exc)
            current = retry_runner(
                repair_prompt(original_prompt, current, exc.errors)
            )

    assert last_error is not None
    raise last_error
