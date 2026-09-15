"""json_guard 的容错测试。

这些用例覆盖了 LLM 实际会犯的错：加围栏、加闲聊、字段缺失、枚举越界、
JSON 被 max_tokens 截断、顶层是数组而不是对象。
"""

from __future__ import annotations

import pytest

from app.agents.json_guard import (
    JsonGuardError,
    extract_json_object,
    parse_lenient,
    strip_fence,
    validate,
    validate_with_retry,
)
from app.domain.models import ParsedMeal

GOOD = '{"foods":[{"name":"麻辣烫","amount_desc":"一碗","nature":"hot"}],"confidence":0.9}'


def test_strip_fence_removes_markdown() -> None:
    raw = "```json\n{\"a\":1}\n```"
    assert strip_fence(raw) == '{"a":1}'


def test_strip_fence_noop_without_fence() -> None:
    assert strip_fence('{"a":1}') == '{"a":1}'


def test_extract_json_object_from_chatter() -> None:
    raw = '好的，结果如下：{"a":{"b":1}} 希望有帮助'
    assert extract_json_object(raw) == '{"a":{"b":1}}'


def test_extract_ignores_braces_inside_strings() -> None:
    raw = '{"note":"含有 } 和 { 的文字","n":1}'
    assert extract_json_object(raw) == raw


def test_extract_raises_on_unclosed_object() -> None:
    with pytest.raises(JsonGuardError, match="未闭合"):
        extract_json_object('{"a":1')


def test_extract_raises_without_object() -> None:
    with pytest.raises(JsonGuardError, match="未找到"):
        extract_json_object("今天天气不错")


def test_parse_lenient_handles_fence_and_chatter() -> None:
    raw = '结果：\n```json\n{"a":1}\n```\n完成'
    assert parse_lenient(raw) == {"a": 1}


def test_parse_lenient_rejects_top_level_array() -> None:
    with pytest.raises(JsonGuardError, match="顶层不是 JSON 对象"):
        parse_lenient("[1,2,3]")


def test_validate_accepts_valid_payload() -> None:
    meal = validate(ParsedMeal, GOOD)
    assert meal.foods[0].name == "麻辣烫"
    assert meal.confidence == pytest.approx(0.9)


def test_validate_rejects_bad_enum() -> None:
    with pytest.raises(JsonGuardError, match="字段校验失败"):
        validate(ParsedMeal, '{"foods":[{"name":"饭","nature":"超级热"}]}')


def test_validate_rejects_truncated_json() -> None:
    with pytest.raises(JsonGuardError):
        validate(ParsedMeal, '{"foods":[{"name":"饭"')


def test_validate_rejects_out_of_range_confidence() -> None:
    with pytest.raises(JsonGuardError):
        validate(ParsedMeal, '{"foods":[],"confidence":1.5}')


def test_validate_with_retry_recovers_on_second_attempt() -> None:
    calls: list[str] = []

    def retry_runner(prompt: str) -> str:
        calls.append(prompt)
        return GOOD

    meal, retries = validate_with_retry(
        ParsedMeal,
        "这不是 JSON",
        retry_runner=retry_runner,
        original_prompt="原始提示词",
        max_retry=1,
    )
    assert retries == 1
    assert meal.foods[0].name == "麻辣烫"
    assert len(calls) == 1
    assert "原始提示词" in calls[0]


def test_validate_with_retry_gives_up_after_max_retry() -> None:
    def always_bad(prompt: str) -> str:
        return "还是不是 JSON"

    with pytest.raises(JsonGuardError):
        validate_with_retry(
            ParsedMeal,
            "不是 JSON",
            retry_runner=always_bad,
            original_prompt="p",
            max_retry=1,
        )
