"""阶段 2 ④：两个壳的 plan 渲染 + 跨链路一致（与 test_shell_signals_render 同构）。

守的还是三类漂移（E7 的形状）：
1. **壳忘了渲染。** plan 算出来却没人显示，等于只留痕在数据里。
2. **壳自己翻译方向。** 一旦出现 `stomach_guard` 这类 token 字面量，中文就有了第二份。
3. **两条离线链路分叉。** C（终端）过去就是漏网的那条（E15、S0 修的正是它）。
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

# 湿气餐（会被化湿方向接管）；冲突餐（方向让位、note 是冲突说明）。
DAMP_CASE = "下午茶一块蛋糕和一杯奶茶"
CONFLICT_CASE = "中午吃了麻辣烫配冰可乐"


def _import_chat() -> object:
    for path in (str(PROJECT_ROOT / "ui" / "terminal"), str(PROJECT_ROOT / "core")):
        if path not in sys.path:
            sys.path.insert(0, path)
    import chat  # noqa: PLC0415

    return chat


def _terminal_parsed(text: str, constitution: Constitution = Constitution.DAMP_HEAT) -> object:
    chat = _import_chat()
    bundle, err = chat._offline_analyze(text, constitution)  # type: ignore[attr-defined]
    assert not err, f"终端离线解析失败：{err}"
    return bundle[0]


def _api_parsed(text: str, constitution: Constitution = Constitution.DAMP_HEAT) -> object:
    async def call() -> object:
        from app.api.analyze_offline import (  # noqa: PLC0415
            OfflineAnalyzeRequest,
            analyze_offline_endpoint,
        )

        return await analyze_offline_endpoint(
            OfflineAnalyzeRequest(text=text, constitution=constitution)
        )

    return asyncio.run(call()).parsed  # type: ignore[attr-defined]


# ============================================================
# 1. 终端壳：装配 + 渲染（AST 守卫 + 变异检验）
# ============================================================
def _terminal_renders_plan(source: str) -> bool:
    """结构判据：render_parsed 调用 _render_meal_plan，且后者读 parsed.plan。

    按**函数体**判 —— 文件里 `_offline_analyze` 也在碰 plan，按文件判会蒙混。
    """
    tree = ast.parse(source)
    funcs = {
        n.name: n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    render = funcs.get("render_parsed")
    helper = funcs.get("_render_meal_plan")
    if render is None or helper is None:
        return False
    calls_helper = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_render_meal_plan"
        for node in ast.walk(render)
    )
    reads_plan = any(
        isinstance(node, ast.Attribute) and node.attr == "plan" for node in ast.walk(helper)
    )
    return calls_helper and reads_plan


def test_terminal_shell_renders_plan() -> None:
    source = CHAT_PATH.read_text(encoding="utf-8")
    assert _terminal_renders_plan(source), "render_parsed 没有渲染推荐优先级"

    mutated = source.replace("    _render_meal_plan(parsed)\n", "")
    assert mutated != source, "替换没生效，变异检验形同虚设"
    assert not _terminal_renders_plan(mutated)


def test_terminal_path_assembles_plan() -> None:
    source = CHAT_PATH.read_text(encoding="utf-8")
    assert "parsed.plan = derive_meal_plan" in source, "终端链路没有装配 parsed.plan"
    # ⚠️ 变异方式用重命名（注释掉多行赋值开头会让续行变成 IndentationError）；
    # 断言带开括号 —— 不带的话 `derive_meal_plan_disabled` 仍含本串，恒真。
    mutated = source.replace("derive_meal_plan", "derive_meal_plan_disabled")
    assert "parsed.plan = derive_meal_plan(" not in mutated


def test_terminal_render_output_contains_plan(capsys: pytest.CaptureFixture[str]) -> None:
    """真跑一遍：湿气餐要打出方向与茶饮名，冲突餐要打出如实说明。"""
    chat = _import_chat()

    parsed = _terminal_parsed(DAMP_CASE)
    assert parsed.plan is not None and parsed.plan.first is not None
    chat.render_parsed(parsed)  # type: ignore[attr-defined]
    out = capsys.readouterr().out
    assert parsed.plan.first.title in out, f"没有渲染茶饮名：{out}"
    assert "本餐优先" in out
    assert parsed.plan.second_note in out, "推迟话术没渲染 —— 模型守了、壳没守"

    parsed = _terminal_parsed(CONFLICT_CASE)
    assert parsed.plan is not None and parsed.plan.note
    chat.render_parsed(parsed)  # type: ignore[attr-defined]
    out = capsys.readouterr().out
    assert parsed.plan.note in out, "方向关闭/冲突的如实说明没渲染（只留痕在数据里）"


def test_terminal_render_silent_when_no_plan(capsys: pytest.CaptureFixture[str]) -> None:
    """plan 为 None 时一行都不打 —— 未接线的调用方输出不变。"""
    from app.domain.models import ParsedMeal

    chat = _import_chat()
    chat.render_parsed(ParsedMeal(foods=[], summary="空"))  # type: ignore[attr-defined]
    out = capsys.readouterr().out
    assert "本餐优先" not in out
    assert "下一餐" not in out


# ============================================================
# 2. 网页壳：renderParsed 必须打出来
# ============================================================
def _web_render_body(text: str) -> str:
    start = text.find("function renderParsed")
    assert start >= 0, "index.html 里找不到 renderParsed"
    end = text.find("\n}\n", start)
    assert end > start, "renderParsed 没有闭合，无法取函数体"
    return text[start:end]


def test_web_shell_renders_plan() -> None:
    source = INDEX_PATH.read_text(encoding="utf-8")
    body = _web_render_body(source)
    assert "p.plan" in body, "renderParsed 没有读 p.plan"
    assert "plan.first" in body, "renderParsed 没有渲染第一段"
    assert "second_note" in body, "renderParsed 没有渲染推迟话术"
    assert "${planNote}" in source, "模板里没有插入 planNote"

    mutated = source.replace("const plan = p.plan || null;", "const plan = null;")
    assert mutated != source, "替换没生效，变异检验形同虚设"
    body = _web_render_body(mutated)
    # 变异后函数体里必须读不到 p.plan —— 否则判据对内容不敏感
    assert "p.plan" not in body


# ============================================================
# 3. 壳不得自己翻译方向 token（中文只有一份，在数据文件里）
# ============================================================
DIRECTION_TOKENS = ("stomach_guard", "damp_clear", "constitution_default")


@pytest.mark.parametrize("path", [CHAT_PATH, INDEX_PATH])
def test_shells_do_not_translate_direction_tokens(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for token in DIRECTION_TOKENS:
        assert token not in text, (
            f"{path.name} 里出现了方向 token「{token}」—— 说明壳在自己翻译方向，"
            "中文就有了第二份。请用后端给的 label。"
        )


# ============================================================
# 4. 跨链路一致：B（API 离线）与 C（终端离线）对 plan 必须同结论
# ============================================================
def test_two_offline_paths_agree_on_plan() -> None:
    assert _terminal_parsed(DAMP_CASE).plan == _api_parsed(DAMP_CASE).plan, (
        "两条离线链路派生的 plan 不一致 —— 又分叉了"
    )
    assert _terminal_parsed(CONFLICT_CASE).plan == _api_parsed(CONFLICT_CASE).plan


def test_plan_matches_direct_derivation() -> None:
    """派生不变式：终端装配的 plan == 直接调纯函数（不是壳里另判一套）。"""
    from app.domain.diet_signals import derive_meal_plan
    from app.services.food_lookup import match_foods, resolve_in_context
    from app.domain.models import ParsedFood

    parsed = _terminal_parsed(DAMP_CASE, Constitution.BALANCED)
    direct = derive_meal_plan(parsed.signals, Constitution.BALANCED.value)  # type: ignore[arg-type]
    assert parsed.plan == direct, "终端装配的 plan 与直接派生不一致"

    # 判据非真空：湿气样本必须真的被方向接管，否则上面那条等于没测
    assert direct is not None and direct.first is not None and direct.first.open
