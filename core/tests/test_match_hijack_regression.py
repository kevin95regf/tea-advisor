"""第 3 步：菜名被新食材关键词抢走的回归测试。

运行时表已含第 4 步安全批次（212 条）。本文件在测试里临时挂上「第二批 hold-back」影子条目
（调味/易吞并水果/白果），验证启发式仍能挡住劫持，且不改坏既有匹配。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

import pytest

from app.services import food_lookup as fl

CORE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = CORE_DIR.parent
SPLIT = PROJECT_ROOT / "docs" / "food-expansion" / "split" / "food_properties.json"

# 第二批 hold-back（运行时不得出现；影子测试临时挂上）
HOLD_BACK_NAMES = frozenset(
    {
        "花椒", "胡椒", "八角", "桂皮", "孜然", "芝麻", "猪油", "大豆油", "蜂蜜",
        "柚子", "菠萝", "桑葚", "梅子", "白果",
    }
)


def _runtime_table() -> dict:
    return json.loads((CORE_DIR / "data" / "food_properties.json").read_text(encoding="utf-8"))


def _shadow_table() -> dict:
    """运行时 + 仍未入库的高风险条目（batch2 hold-back）。"""
    runtime = _runtime_table()
    expanded = json.loads(SPLIT.read_text(encoding="utf-8"))
    ids = {e["id"] for e in runtime["foods"]} | {
        e["id"] for e in runtime["tea_drinks"]["items"]
    }
    held = [e for e in expanded["foods"] if e["id"] not in ids]
    names = {e["name"] for e in held}
    missing = HOLD_BACK_NAMES - names
    assert not missing, f"hold-back 影子缺少高风险条目：{sorted(missing)}"
    # 运行时不得已含这些高风险名
    runtime_names = {e["name"] for e in runtime["foods"]}
    leaked = HOLD_BACK_NAMES & runtime_names
    assert not leaked, f"高风险条目已误入运行时：{sorted(leaked)}"
    return {
        **runtime,
        "foods": list(runtime["foods"]) + held,
        "tea_drinks": runtime["tea_drinks"],
    }


@pytest.fixture
def shadow_foods(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict]:
    """测试专用：load_food_table → 运行时 + hold-back 影子，不写盘。"""
    table = _shadow_table()
    fl.load_food_table.cache_clear()

    def _fake_loader() -> dict:
        return table

    _fake_loader.cache_clear = lambda: None  # type: ignore[attr-defined]
    monkeypatch.setattr(fl, "load_food_table", _fake_loader)
    yield table
    # monkeypatch 恢复原 lru_cache 函数后再清缓存
    fl.load_food_table.cache_clear()


@pytest.fixture
def runtime_foods(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """确保走真实运行时表（其它 fixture 可能清过缓存）。"""
    fl.load_food_table.cache_clear()
    yield
    fl.load_food_table.cache_clear()


# ---------- 劫持样例：影子表下不得被原料抢走 ----------

HIJACK_CASES = [
    ("黑胡椒牛排", "胡椒"),
    ("桑葚酒", "桑葚"),
    ("菠萝咕咾肉", "菠萝"),
    ("柚子茶", "柚子"),
    ("芝麻酱拌面", "芝麻"),
    ("百香果茶", "百香果"),
]


@pytest.mark.parametrize("text,hijacker", HIJACK_CASES)
def test_shadow_dish_not_hijacked_by_ingredient(
    shadow_foods: dict, text: str, hijacker: str
) -> None:
    names = [e["name"] for e in fl.match_foods(text)]
    assert hijacker not in names, f"{text!r} 仍命中原料 {hijacker}: {names}"
    entry, _, _ = fl._find_entry(text)
    assert entry is None or entry.get("name") != hijacker


def test_runtime_zao_not_stolen_by_xianzao(runtime_foods: None) -> None:
    """单字「枣」不得因鲜枣规范名包含它而改挂到鲜枣（鲜枣已在安全批次）。"""
    entry, _, _ = fl._find_entry("枣")
    assert entry is None or entry.get("name") != "鲜枣"
    assert "鲜枣" not in [e["name"] for e in fl.match_foods("枣")]


def test_runtime_machixian_baozi_keeps_baozi(runtime_foods: None) -> None:
    names = [e["name"] for e in fl.match_foods("马齿苋包子")]
    assert "包子" in names
    entry, _, kind = fl._find_entry("马齿苋包子")
    assert entry is not None and entry["name"] == "包子"
    assert kind == "name"


def test_shadow_zhima_sauce_noodles_keep_noodles(shadow_foods: dict) -> None:
    names = [e["name"] for e in fl.match_foods("芝麻酱拌面")]
    assert "面条" in names
    assert "芝麻" not in names


def test_runtime_baixiang_tea_prefers_fruit_tea(runtime_foods: None) -> None:
    names = [e["name"] for e in fl.match_foods("百香果茶")]
    assert names[0] == "水果茶"
    assert "百香果" not in names


def test_shadow_hongzao_cha_stable(shadow_foods: dict) -> None:
    assert [e["name"] for e in fl.match_foods("红枣茶")][0] == "红枣茶"
    entry, _, _ = fl._find_entry("红枣茶")
    assert entry is not None and entry["name"] == "红枣茶"


# ---------- 对照：既有条目仍应命中 ----------

CONTROL_CASES = [
    ("菊花茶", "菊花茶"),
    ("红枣茶", "红枣茶"),
    ("包子", "包子"),
    ("牛肉面", "面条"),
    ("麻辣烫", "麻辣烫"),
    ("蛋糕", "蛋糕"),
    ("茉莉花茶", "茉莉花茶"),
    ("希腊酸奶", "希腊酸奶"),
]


@pytest.mark.parametrize("text,expected", CONTROL_CASES)
def test_runtime_controls_still_match(runtime_foods: None, text: str, expected: str) -> None:
    names = [e["name"] for e in fl.match_foods(text)]
    assert expected in names, f"{text!r} 应命中 {expected}，实际 {names}"


@pytest.mark.parametrize("text,expected", CONTROL_CASES)
def test_shadow_controls_still_match(shadow_foods: dict, text: str, expected: str) -> None:
    names = [e["name"] for e in fl.match_foods(text)]
    assert expected in names, f"影子表下 {text!r} 应仍命中 {expected}，实际 {names}"


def test_runtime_table_batch1_total(runtime_foods: None) -> None:
    stats = fl.table_stats()
    assert stats["total"] == 212, stats
    assert stats["foods"] == 194 and stats["tea_drinks"] == 18


def test_shadow_does_not_write_runtime_file(shadow_foods: dict) -> None:
    """影子加载不得把 hold-back 写进 core/data。"""
    on_disk = _runtime_table()
    assert len(on_disk["foods"]) == 194
    assert len(on_disk["tea_drinks"]["items"]) == 18
    assert not any(e["name"] in HOLD_BACK_NAMES for e in on_disk["foods"])
