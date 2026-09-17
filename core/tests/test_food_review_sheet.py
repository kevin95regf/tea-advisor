"""食性表核验单脚本（`build_food_review_sheet.py`）的回归测试。

守三类风险：

1. **产物过期**：数据改了却没重新生成核验单 —— 审核人照着旧单子审，白做一遍。
   这是最隐蔽的一类，因为单子看起来永远「像那么回事」。
2. **输出不确定**：`--check` 靠「重新生成 == 磁盘内容」判定，所以渲染必须是**确定性**的。
   哪天有人往产物里塞一个生成时间戳，`--check` 就会永远红灯（或者更糟：被删掉）。
3. **检查项静默失效**：脚本里的每条检查都要能真的抓出问题，不能是摆设。

第三条用**负控制**测：喂一份人造数据给检查函数，断言它报出预期的问题。
只测「真实数据上没报错」是不够的 —— 那和「检查根本没跑」长得一模一样。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

CORE_DIR = Path(__file__).resolve().parent.parent
SCRIPT_PATH = CORE_DIR / "scripts" / "build_food_review_sheet.py"
FOOD_PATH = CORE_DIR / "data" / "food_properties.json"
HERBS_PATH = CORE_DIR / "data" / "herbs.json"
SHEET_PATH = CORE_DIR.parent / "docs" / "food-properties-review-sheet.md"

EXPECTED_TOTAL = 146
EXPECTED_FOODS = 128
EXPECTED_TEA = 18


def _load_module():
    spec = importlib.util.spec_from_file_location("build_food_review_sheet", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_food_review_sheet"] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


@pytest.fixture(scope="module")
def mod():
    return _load_module()


@pytest.fixture(scope="module")
def entries(mod):
    _, items = mod.load_foods(FOOD_PATH)
    return items


@pytest.fixture(scope="module")
def issues(mod, entries):
    return mod.run_checks(entries, mod.load_herb_nature(HERBS_PATH))


# ============================================================
# 1. 产物与数据同步
# ============================================================
def test_sheet_is_up_to_date() -> None:
    """核验单必须与当前数据一致。

    数据改了（加条目、改四气、补审核状态）却没重新生成核验单时，本测试失败。
    修法就一句：`cd core && python scripts/build_food_review_sheet.py --out ../docs/…`。
    """
    assert SHEET_PATH.exists(), f"核验单不存在：{SHEET_PATH}"
    import subprocess

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--check"],
        cwd=str(CORE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, f"核验单已过期或有误：\n{result.stdout}\n{result.stderr}"


def test_render_is_deterministic(mod, entries):
    """同一份数据渲染两次必须逐字相同。

    `--check` 的判据就是「重新生成 == 磁盘内容」，所以渲染里**不能有**时间戳、
    `set` 迭代顺序这类不确定成分。这条测试是 `--check` 自身可信的前提。
    """
    meta, _ = mod.load_foods(FOOD_PATH)
    herbs = mod.load_herb_nature(HERBS_PATH)
    first = mod.render(entries, meta, mod.run_checks(entries, herbs), FOOD_PATH)
    second = mod.render(entries, meta, mod.run_checks(entries, herbs), FOOD_PATH)
    assert first == second


def test_sheet_has_no_timestamp(mod):
    """产物里不得出现生成时间戳 —— 它会让 `--check` 永远失败。"""
    text = SHEET_PATH.read_text(encoding="utf-8")
    for token in ("生成时间", "generated at", "2026-", "2025-"):
        assert token not in text, f"核验单里出现了疑似时间戳的内容：{token!r}"


# ============================================================
# 2. 数据规模与字段
# ============================================================
def test_total_count_and_split(entries) -> None:
    assert len(entries) == EXPECTED_TOTAL
    assert sum(1 for e in entries if e["_group"] == "foods") == EXPECTED_FOODS
    assert sum(1 for e in entries if e["_group"] == "tea_drinks") == EXPECTED_TEA


def test_every_entry_has_a_known_nature(mod, entries) -> None:
    """四气必须是 5 档之一。多了「微寒」「大热」这类词会让判定层无法映射。"""
    for e in entries:
        assert e.get("nature") in mod.NATURE_ORDER, f"{e['id']} 的四气异常：{e.get('nature')!r}"


def test_review_status_falls_back_without_crashing(mod, entries) -> None:
    """缺 `review_status` 的条目靠旧布尔字段回退，不能抛异常、不能被当成 approved。

    这里只断言**回退行为**，不断言「有几条缺字段」—— 那是个待清理的数据现状
    （pending-items E1），清掉之后本测试不该跟着失败。
    """
    for e in entries:
        status = mod.review_status_of(e)
        assert status in mod.VALID_REVIEW_STATUS
        if "review_status" not in e:
            assert status == ("approved" if e.get("reviewed") else "pending")


# ============================================================
# 3. 真实数据上应当成立的两条不变式
# ============================================================
def test_temperature_variants_match_the_code_rule(issues) -> None:
    """「冰奶茶/热奶茶」这类独立条目与基条目的差值，必须与 `nature_math` 的规则一致。

    `nature_math` 是温度语义的唯一载体（冰镇 -1 / 加热 +1）。数据侧拆出独立条目时
    最容易各写各的，于是同一杯奶茶在两个地方给出相反方向。
    """
    bad = [i for i in issues if i["kind"] == "温度变体不一致"]
    assert not bad, f"温度变体与规则不符：{[r for i in bad for r in i['rows']]}"


def test_cross_table_nature_agrees_with_herbs(issues) -> None:
    """茶饮条目与 `herbs.json` 同名饮片的四气必须一致。

    同一味东西（茉莉花茶 vs 茉莉花饮片）在两个文件里属性不同，用户在两处会拿到
    相反方向。这是两个数据文件之间**唯一能用机器守住的硬关系**。
    """
    bad = [i for i in issues if i["kind"] == "跨表不一致"]
    assert not bad, f"茶饮与饮片四气不一致：{[r for i in bad for r in i['rows']]}"


# ============================================================
# 4. 负控制：每条检查都必须真的能抓出问题
# ============================================================
def _entry(**over) -> dict:
    base = {
        "id": "x",
        "name": "某物",
        "category": "主食",
        "nature": "neutral",
        "flavors": ["sweet"],
        "aliases": [],
        "keywords": [],
        "reviewed": False,
        "reviewed_by": None,
        "reviewed_at": None,
        "review_note": None,
        "review_status": "pending",
        "_group": "foods",
    }
    base.update(over)
    return base


def test_alias_ambiguity_check_detects_conflict(mod) -> None:
    """同一别名指向两条**四气不同**的条目时必须报矛盾。"""
    items = [
        _entry(id="a", name="甲", nature="warm", aliases=["炸物"]),
        _entry(id="b", name="乙", nature="hot", aliases=["炸物"]),
    ]
    kinds = [i["kind"] for i in mod.check_alias_ambiguity(items)]
    assert "别名歧义" in kinds, "四气不同的别名歧义没被抓出来"


def test_alias_ambiguity_check_ignores_same_nature(mod) -> None:
    """四气相同的重复别名只算存疑，不算矛盾 —— 它不会让判定结果漂移。"""
    items = [
        _entry(id="a", name="甲", nature="warm", aliases=["别名"]),
        _entry(id="b", name="乙", nature="warm", aliases=["别名"]),
    ]
    out = mod.check_alias_ambiguity(items)
    assert [i["kind"] for i in out] == ["别名重复登记"]


def test_variant_rule_check_detects_mismatch(mod) -> None:
    """variant_nature 与 layer_2 兜底规则差一档时必须报矛盾（咖啡就是真实一例）。"""
    items = [_entry(id="c", nature="warm", variant_nature={"cold": "cool"})]
    kinds = [i["kind"] for i in mod.check_variant_against_rules(items)]
    assert "变体与规则不一致" in kinds


def test_variant_rule_check_accepts_consistent_value(mod) -> None:
    """符合规则的变体不该被报出来 —— 否则这条检查会淹没在噪音里。"""
    items = [_entry(id="c", nature="warm", variant_nature={"cold": "neutral"})]
    assert mod.check_variant_against_rules(items) == []


def test_temperature_sibling_check_detects_wrong_delta(mod) -> None:
    """「冰 X」的实测差值与规则不符时必须报矛盾。"""
    items = [
        _entry(id="naicha", name="奶茶", nature="neutral"),
        _entry(id="bing", name="冰奶茶", nature="warm"),  # 应为 cool
    ]
    kinds = [i["kind"] for i in mod.check_temperature_siblings(items)]
    assert "温度变体不一致" in kinds


def test_missing_review_status_check_detects_field_loss(mod) -> None:
    """缺 `review_status` 必须被报出来（pending-items E1 就是这个形态）。"""
    items = [_entry(id="a")]
    items[0].pop("review_status")
    kinds = [i["kind"] for i in mod.check_schema_fields(items)]
    assert "缺 review_status" in kinds


def test_duplicate_key_check_detects_duplicate_id(mod) -> None:
    items = [_entry(id="same", name="甲"), _entry(id="same", name="乙")]
    kinds = [i["kind"] for i in mod.check_duplicate_keys(items)]
    assert "重复" in kinds


def test_checks_are_not_vacuous_on_real_data(issues) -> None:
    """真实数据上，至少有一条检查报出「矛盾」——否则说明整条流水线是摆设。

    ⚠️ 这条断言会在 ④ 层全部修完后**必然失败**。那时正确的做法是把它删掉，
    而不是把检查关掉：④ 层清零是本工作的目标之一。这里保留它，是为了防止
    「检查跑是跑了，但一条都没命中」被当成通过。
    """
    contradictions = [i for i in issues if i["level"] == "矛盾"]
    assert contradictions, (
        "④层矛盾清零了。若确实是修完了，请删除本测试（而不是放宽它）；"
        "若只是检查失效了，请修检查。"
    )
