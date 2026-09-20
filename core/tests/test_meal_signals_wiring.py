"""阶段 1 ①：整餐信号（ParsedMeal.signals）的装配与接线。

范式＝**派生不变式 + 负控制**，不写快照断言：

- 派生不变式：装配层的 `conflict` 必须与直接调 `detect_nature_conflict` 逐字段相等
  ⇒ 证明装配层没有另判一套（这是本轮最要紧的一条：另判就会重演「两份实现」）。
- 负控制：`monkeypatch` 掉识别/判定后分数必须归零 ⇒ 证明分数不是硬编码。
- 变异检验：AST 守卫对「改回未接线」的源码副本必须变红（内存改副本，不落盘）。

跨链路一致（LLM / API 离线 / 终端离线）测试不在这里——它依赖 `ui/terminal/chat.py`，
按提交切分落在 ③（`test_shell_signals_render.py`）。
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest

from app.domain import diet_signals as ds
from app.domain.diet_signals import build_meal_signals, load_diet_signals
from app.domain.models import ParsedFood, ParsedMeal
from app.domain.nature_math import NatureConflict, detect_nature_conflict
from app.services.food_lookup import match_foods, resolve_in_context

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 现实口述。刻意含「冰啤酒」（裁定样例：冰+酒精+碳酸=3）与「麻辣烫配冰可乐」（寒热错杂）。
CASES: tuple[str, ...] = (
    "喝了一瓶冰啤酒",
    "中午吃了麻辣烫配冰可乐",
    "下午吃了蛋糕喝了冰奶茶",
    "早上喝了热牛奶",
    "晚上吃了炸鸡",
)

CONFLICT_CASE = "中午吃了麻辣烫配冰可乐"
BEER_CASE = "喝了一瓶冰啤酒"


def _foods(text: str) -> list[ParsedFood]:
    """用**真实的**解析原语装配 foods（与离线端点同一组调用），不在测试里合成四性。"""
    out: list[ParsedFood] = []
    for entry in match_foods(text):
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        resolved = resolve_in_context(text, entry)
        out.append(ParsedFood(name=name, nature=resolved.nature, flavors=resolved.flavors))
    return out


def _dim_spec(dim_id: str) -> dict:
    return (load_diet_signals().get("dimensions") or {})[dim_id]


def _label_of(dim_id: str, action: str) -> str:
    """中文标签从数据文件反查——测试里不写死「重点护脾胃」这种字串。"""
    for level in _dim_spec(dim_id).get("levels") or []:
        if str(level.get("action")) == action:
            return str(level.get("label") or "")
    raise AssertionError(f"数据文件里没有 action={action} 的档位")


def _wiring_present(source: str, func_name: str) -> bool:
    """结构判据：指定函数体内存在 `parsed.signals = build_meal_signals(...)`。

    按**函数体**判而不是按整个文件判——文件里还可能有别处的 `signals`，
    按文件判会互相蒙混（`test_terminal_offline_path.py` 里踩过同形状的问题）。
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != func_name:
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Assign):
                continue
            func = sub.value.func if isinstance(sub.value, ast.Call) else None
            if not isinstance(func, ast.Name) or func.id != "build_meal_signals":
                continue
            for target in sub.targets:
                if (
                    isinstance(target, ast.Attribute)
                    and target.attr == "signals"
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "parsed"
                ):
                    return True
    return False


# ---------------------------------------------------------------
# 1. 派生不变式：装配层不另判冲突
# ---------------------------------------------------------------
def test_conflict_is_passed_through_unchanged() -> None:
    seen_conflict = 0
    for text in CASES:
        foods = _foods(text)
        assembled = build_meal_signals(text, foods).conflict
        direct = detect_nature_conflict([(f.name, f.nature) for f in foods])
        assert assembled is not None
        assert assembled.conflict == direct.conflict
        assert assembled.heat_side == list(direct.heat_side)
        assert assembled.cold_side == list(direct.cold_side)
        seen_conflict += int(direct.conflict)

    # 防「恒真」：样本必须真的覆盖到 conflict=True，否则这条断言等于没测。
    assert seen_conflict >= 1, "样本里没有一个寒热错杂用例，判据形同虚设"


def test_conflict_sides_are_disjoint_and_from_foods() -> None:
    foods = _foods(CONFLICT_CASE)
    names = {f.name for f in foods}
    conflict = build_meal_signals(CONFLICT_CASE, foods).conflict
    assert conflict is not None and conflict.conflict is True
    assert set(conflict.heat_side).isdisjoint(set(conflict.cold_side))
    assert set(conflict.heat_side) <= names
    assert set(conflict.cold_side) <= names


# ---------------------------------------------------------------
# 2. 默认 None ⇒ 既有调用方逐字节不变
# ---------------------------------------------------------------
def test_parsed_meal_signals_defaults_to_none() -> None:
    assert ParsedMeal(foods=_foods(BEER_CASE)).signals is None


# ---------------------------------------------------------------
# 3. 负控制：分数不是硬编码
# ---------------------------------------------------------------
def test_without_signals_scores_are_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ds, "identify_signals", lambda *a, **k: [])
    signals = build_meal_signals(BEER_CASE, _foods(BEER_CASE))
    assert signals.impact is not None and signals.dampness is not None
    assert signals.impact.score == 0
    assert signals.impact.action == "none"
    assert signals.impact.signals == []
    assert signals.dampness.score == 0


def test_conflict_can_be_turned_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ds, "detect_nature_conflict", lambda items: NatureConflict(False, [], [])
    )
    signals = build_meal_signals(CONFLICT_CASE, _foods(CONFLICT_CASE))
    assert signals.conflict is not None
    assert signals.conflict.conflict is False
    assert signals.conflict.heat_side == []
    assert signals.conflict.cold_side == []


# ---------------------------------------------------------------
# 4. 钉值（数字从数据派生，不写死；样例为你的裁定：冰啤酒=3）
# ---------------------------------------------------------------
def test_iced_beer_scores_three() -> None:
    signals = build_meal_signals(BEER_CASE, _foods(BEER_CASE))
    assert signals.impact is not None
    spec = _dim_spec("impact")

    # cap / label 都来自数据文件，测试不写死 3 与「脾胃冲击度」
    assert signals.impact.cap == int(spec["cap"])
    assert signals.impact.label == str(spec["label"])
    assert signals.impact.score == int(spec["cap"]), "冰镇+酒精+碳酸 应打满"
    assert signals.impact.action == "protect_stomach_plus"
    assert signals.impact.action_label == _label_of("impact", "protect_stomach_plus")
    assert signals.impact.action_label, "档位必须有中文标签"


def test_action_label_always_present_for_every_level() -> None:
    """中文标签只有一份、在定义档位的数据文件里——每个档位都必须有。"""
    for dim_id in ("impact", "dampness"):
        levels = _dim_spec(dim_id).get("levels") or []
        assert levels, f"{dim_id} 没有档位定义"
        for level in levels:
            assert str(level.get("label") or ""), f"{dim_id}/{level['action']} 缺中文标签"
        assert ds._action_labels(levels) == {
            str(lv["action"]): str(lv["label"]) for lv in levels
        }


def test_evidence_floor_is_reported_honestly() -> None:
    """carbonated 是「名单近似」（evidence: none），装配结果必须照样如实标出来。"""
    signals = build_meal_signals(BEER_CASE, _foods(BEER_CASE))
    assert signals.impact is not None
    assert signals.impact.evidence_floor == "none"
    assert signals.impact.basis  # 依据说明不能为空


# ---------------------------------------------------------------
# 5. 接线守卫（A 与 B）+ 变异检验
# ---------------------------------------------------------------
@pytest.mark.parametrize(
    "rel_path,func_name",
    [
        ("core/app/services/orchestrator.py", "analyze"),
        ("core/app/api/analyze_offline.py", "analyze_offline_endpoint"),
    ],
)
def test_core_paths_are_wired(rel_path: str, func_name: str) -> None:
    path = PROJECT_ROOT / rel_path
    assert path.is_file(), f"接线目标文件不存在：{rel_path}"
    source = path.read_text(encoding="utf-8")
    assert _wiring_present(source, func_name), f"{rel_path}::{func_name} 未装配 parsed.signals"

    # 变异检验（内存副本）：把接线行拆掉后必须判不出来，否则判据恒真。
    mutated = source.replace(
        "parsed.signals = build_meal_signals", "# parsed.signals = build_meal_signals"
    )
    assert mutated != source, "替换没生效，变异检验形同虚设"
    assert not _wiring_present(mutated, func_name)


# ---------------------------------------------------------------
# 6. 真跑离线端点（B 链路的端到端证据，不是合成复述）
# ---------------------------------------------------------------
def test_offline_endpoint_returns_signals() -> None:
    async def call() -> object:
        from app.api.analyze_offline import (
            OfflineAnalyzeRequest,
            analyze_offline_endpoint,
        )

        return await analyze_offline_endpoint(OfflineAnalyzeRequest(text=CONFLICT_CASE))

    response = asyncio.run(call())
    parsed = response.parsed  # type: ignore[attr-defined]
    assert parsed.signals is not None, "离线端点没有装配 signals"
    assert parsed.signals.conflict is not None
    assert parsed.signals.conflict.conflict is True

    # 与直接装配的结果一致 ⇒ 端点没走另一套
    direct = build_meal_signals(CONFLICT_CASE, _foods(CONFLICT_CASE))
    assert parsed.signals.impact == direct.impact
    assert parsed.signals.dampness == direct.dampness
