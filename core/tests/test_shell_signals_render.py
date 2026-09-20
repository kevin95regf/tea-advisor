"""阶段 1 ③：两个壳的整餐信号渲染 + 跨链路一致（API 离线 vs 终端离线）。

守的是三类漂移：

1. **壳忘了渲染。** 信号算出来却没人显示，等于没做（E7 的形状）。
2. **壳自己翻译档位。** 一旦出现 `protect_stomach` 这类 token 字面量，就说明
   中文有了第二份 —— 与「中文只有一份、在定义档位的数据文件里」相反。
3. **两条离线链路再次分叉。** B（API）与 C（终端）过去就分叉过（E15：C 是漏网）。
   这里用**真实函数**比对，不用合成复述。

跨链路一致的测试放在本文件而不是 ①，因为它依赖 `ui/terminal/chat.py`，
按提交切分属于 ui 这一次。
"""

from __future__ import annotations

import ast
import asyncio
import sys
from pathlib import Path

import pytest

from app.domain.enums import Constitution

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHAT_PATH = PROJECT_ROOT / "ui" / "terminal" / "chat.py"
INDEX_PATH = PROJECT_ROOT / "ui" / "web" / "index.html"

# 与 ① 同一批现实口述，另加两条终端用户常见说法。
CASES: tuple[str, ...] = (
    "中午吃了麻辣烫配冰可乐",
    "晚上吃了火锅配冰啤酒",
    "喝了一瓶冰啤酒",
    "炸鸡配冰可乐",
    "下午吃了蛋糕喝了冰奶茶",
    "早上喝了热牛奶",
)

CONFLICT_CASE = "中午吃了麻辣烫配冰可乐"


def _import_chat() -> object:
    """真 import 终端壳（S0 验收就是这么做的：合成复述不能当证据）。"""
    for path in (str(PROJECT_ROOT / "ui" / "terminal"), str(PROJECT_ROOT / "core")):
        if path not in sys.path:
            sys.path.insert(0, path)
    import chat  # noqa: PLC0415

    return chat


def _terminal_parsed(text: str) -> object:
    chat = _import_chat()
    bundle, err = chat._offline_analyze(text, Constitution.DAMP_HEAT)  # type: ignore[attr-defined]
    assert not err, f"终端离线解析失败：{err}"
    return bundle[0]


def _api_parsed(text: str) -> object:
    async def call() -> object:
        from app.api.analyze_offline import (  # noqa: PLC0415
            OfflineAnalyzeRequest,
            analyze_offline_endpoint,
        )

        return await analyze_offline_endpoint(OfflineAnalyzeRequest(text=text))

    return asyncio.run(call()).parsed  # type: ignore[attr-defined]


# ============================================================
# 1. 终端壳：render_parsed 必须打出来
# ============================================================
def _terminal_renders_signals(source: str) -> bool:
    """结构判据：render_parsed 调用 _render_meal_signals，且后者读 parsed.signals。

    按**函数体**判，不按整个文件判 —— 文件里 `_offline_analyze` 也在碰 signals，
    按文件判会互相蒙混（与 test_terminal_offline_path.py 同一条教训）。
    """
    tree = ast.parse(source)
    funcs = {
        n.name: n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    render = funcs.get("render_parsed")
    helper = funcs.get("_render_meal_signals")
    if render is None or helper is None:
        return False

    calls_helper = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_render_meal_signals"
        for node in ast.walk(render)
    )
    reads_signals = any(
        isinstance(node, ast.Attribute) and node.attr == "signals"
        for node in ast.walk(helper)
    )
    return calls_helper and reads_signals


def test_terminal_shell_renders_signals() -> None:
    assert CHAT_PATH.is_file(), "终端壳文件不存在"
    source = CHAT_PATH.read_text(encoding="utf-8")
    assert _terminal_renders_signals(source), "render_parsed 没有渲染整餐信号"

    # 变异检验（内存副本）：拆掉那一行调用必须判不出来。
    mutated = source.replace("    _render_meal_signals(parsed)\n", "")
    assert mutated != source, "替换没生效，变异检验形同虚设"
    assert not _terminal_renders_signals(mutated)


def test_terminal_render_output_contains_signals(capsys: pytest.CaptureFixture[str]) -> None:
    """真跑一遍 render_parsed，断言输出里有分数与警示行。"""
    chat = _import_chat()
    parsed = _terminal_parsed(CONFLICT_CASE)
    assert parsed.signals is not None, "终端离线链路没有装配 signals"

    chat.render_parsed(parsed)  # type: ignore[attr-defined]
    out = capsys.readouterr().out
    assert parsed.signals.conflict.conflict is True
    assert "寒热错杂" in out, f"没有渲染寒热错杂行：{out}"
    assert str(parsed.signals.impact.score) in out, f"没有渲染冲击度分数：{out}"


def test_terminal_render_silent_when_no_signals(capsys: pytest.CaptureFixture[str]) -> None:
    """signals 为 None 时一行都不打 —— 未接线的调用方输出不变。"""
    from app.domain.models import ParsedMeal

    chat = _import_chat()
    chat.render_parsed(ParsedMeal(foods=[], summary="空"))  # type: ignore[attr-defined]
    out = capsys.readouterr().out
    assert "寒热错杂" not in out
    assert "冲击" not in out


# ============================================================
# 2. 网页壳：renderParsed 必须打出来
# ============================================================
def _web_render_body(text: str) -> str:
    start = text.find("function renderParsed")
    assert start >= 0, "index.html 里找不到 renderParsed"
    end = text.find("\n}\n", start)
    assert end > start, "renderParsed 没有闭合，无法取函数体"
    return text[start:end]


def _web_renders_signals(text: str) -> bool:
    body = _web_render_body(text)
    return "p.signals" in body and "action_label" in body


def test_web_shell_renders_signals() -> None:
    assert INDEX_PATH.is_file(), "网页壳文件不存在"
    source = INDEX_PATH.read_text(encoding="utf-8")
    assert _web_renders_signals(source), "renderParsed 没有渲染整餐信号"

    mutated = source.replace("const sig = p.signals || null;", "const sig = null;")
    assert mutated != source, "替换没生效，变异检验形同虚设"
    assert not _web_renders_signals(mutated)


# ============================================================
# 3. 壳不得自己维护档位文案
# ============================================================
ACTION_TOKENS = ("protect_stomach", "damp_clear")


@pytest.mark.parametrize("path", [CHAT_PATH, INDEX_PATH])
def test_shells_do_not_translate_action_tokens(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for token in ACTION_TOKENS:
        assert token not in text, (
            f"{path.name} 里出现了档位 token「{token}」—— 说明壳在自己翻译档位，"
            "中文就有了第二份。请用后端给的 action_label。"
        )


# ============================================================
# 4. 跨链路一致：B（API 离线）与 C（终端离线）必须同结论
# ============================================================
def test_two_offline_paths_agree() -> None:
    scored = 0
    for text in CASES:
        terminal = _terminal_parsed(text).signals  # type: ignore[attr-defined]
        api = _api_parsed(text).signals
        assert terminal is not None and api is not None, f"「{text}」有一条链路没装配 signals"
        assert terminal.impact == api.impact, f"「{text}」冲击度不一致：两条链路又分叉了"
        assert terminal.dampness == api.dampness, f"「{text}」湿气度不一致"
        assert terminal.conflict == api.conflict, f"「{text}」寒热错杂判定不一致"
        scored += int(terminal.impact.score > 0)

    # 防恒真：样本必须真的打到分，否则「两边都是 0」也算一致。
    assert scored >= 3, f"只有 {scored} 条打到了冲击度，样本不足以证明一致"


def test_terminal_path_wired_like_api() -> None:
    """终端链路必须真的接上（不只是字段存在）—— 与 API 链路用同一入口。"""
    source = CHAT_PATH.read_text(encoding="utf-8")
    assert "build_meal_signals" in source
    assert "parsed.signals = build_meal_signals" in source, "终端链路没有装配 parsed.signals"
