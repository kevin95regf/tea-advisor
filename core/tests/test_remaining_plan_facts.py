"""`docs/food-properties-remaining-plan.md` 的数字守卫 —— E6。

为什么单列一个文件（而不并进 `test_doc_facts.py`）
--------------------------------------------------
`test_doc_facts.py` 守的是「三份入口文档」的通用事实（测试项数／文件数／引用路径）。
本文需要的判据是**这份文档专属**的：分层条数必须等于**从数据现算**出来的值。
硬塞进去会让那个通用守卫长出一堆特例。

守什么
------
① 文档 §0／§1 里写的数字 == 从 `docs/food-properties-sources.json` +
   `core/data/food_properties.json` **现算**出来的值（不写死数字，数据一变就红）；
② **「原估」对照栏还在** —— 2026-09-21 的裁定是「重写数字但保留原估」，
   防止后来人「顺手把对照删了」（那会丢掉「估数错在哪」这条信息）。

⚠️ 一条**先验实测否定掉**的想法：本想断言「53 条派生条目的 `note` 都以『派生：』开头」——
实测 **只有 49/53**（`shengyu`／`pijiu`／`liangcha`／`qubing_naicha` 四条不是），
所以本文件**不**做这条断言。派生条数的口径就是**纯算术**：全表 − 已登记。
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
PLAN = ROOT / "docs/food-properties-remaining-plan.md"
SOURCES = ROOT / "docs/food-properties-sources.json"
FOOD_TABLE = ROOT / "core/data/food_properties.json"


def _text(rel: Path) -> str:
    """**单一入口**读文档（变异检验要顶替的就是它）。"""
    return rel.read_text(encoding="utf-8")


def _sources() -> dict[str, Any]:
    return json.loads(SOURCES.read_text(encoding="utf-8"))


def _food_table() -> dict[str, Any]:
    return json.loads(FOOD_TABLE.read_text(encoding="utf-8"))


def _facts(data: dict[str, Any], food: dict[str, Any]) -> dict[str, Any]:
    """从数据现算本文要写的数字。"""
    entries = list(data.get("entries") or [])
    records = list(food.get("foods") or []) + list((food.get("tea_drinks") or {}).get("items") or [])
    registered = len(entries)
    total = len(records)
    layers = Counter(str(e.get("layer")) for e in entries)
    batches = Counter(str(e.get("batch")) for e in entries)
    return {
        "total": total,
        "registered": registered,
        "derived": total - registered,
        "layer1": layers.get("①", 0),
        "layer2": layers.get("②", 0),
        "layer3": layers.get("③", 0),
        "batch_first": batches.get("第一批", 0),
        "batch_later": batches.get("后续", 0),
    }


def test_plan_numbers_match_the_data():
    f = _facts(_sources(), _food_table())
    text = _text(PLAN)

    expected = [
        f"全表 **{f['total']}** 条 = 已登记 **{f['registered']}** 条 ＋ B4 派生 `note` **{f['derived']}** 条",
        f"登记表按 `layer`：**①{f['layer1']} / ②{f['layer2']} / ③{f['layer3']}**",
        f"**B4 派生 {f['derived']} 条**",
        f"登记表 `layer=①` **{f['layer1']}** 条",
        f"登记表 `layer=③` **{f['layer3']}** 条",
        f"**第一批 {f['batch_first']} / 后续 {f['batch_later']}**",
    ]
    missing = [s for s in expected if s not in text]
    assert not missing, (
        f"本文写的数字与数据现算不符（数据若变过，请同步 §0／§1）：\n  " + "\n  ".join(missing)
    )

    # 非真空：这些数字得真有分量，否则判据可能只是「空表也对得上」
    assert f["total"] > 100 and f["registered"] > 50, f"数据规模骤降，判据失去意义：{f}"


def test_original_estimates_are_still_present():
    """「原估」对照栏必须还在 —— 2026-09-21 的裁定是「重写数字 + 保留原估」。"""
    text = _text(PLAN)
    for marker in ("原估（2026-09-18）", "原估条数", "（原估 32）", "（原估 33）"):
        assert marker in text, f"原估对照被删掉了：找不到 {marker!r}"


def test_plan_no_longer_claims_100_remaining():
    """旧的错口径不得复活：文档不应再出现「剩余 100 条」「**100 条**」这类断言。"""
    text = _text(PLAN)
    for stale in ("剩余 100 条", "**100 条**", "能引来源的 35 条"):
        assert stale not in text, f"旧口径复活了：{stale!r}"


def test_negative_control_mutation_via_single_entry(monkeypatch):
    """从**唯一入口** `_text` 改数据 ⇒ 断言必须变红（防「守卫看着在跑」）。

    再配一条负控制：改无关文案（不是数字）应仍绿。
    """
    real = _text(PLAN)
    f = _facts(_sources(), _food_table())

    good_line = f"全表 **{f['total']}** 条 = 已登记 **{f['registered']}** 条"
    assert good_line in real

    # 变异：把登记条数改错
    broken = real.replace(good_line, f"全表 **{f['total']}** 条 = 已登记 **{f['registered'] + 1}** 条")
    monkeypatch.setattr(sys.modules[__name__], "_text", lambda rel: broken)
    try:
        test_plan_numbers_match_the_data()
    except AssertionError:
        pass
    else:
        raise AssertionError("把登记条数改错后守卫仍绿 ⇒ 它没在读这份文档")

    # 负控制：改一处与数字无关的文案 ⇒ 仍绿
    harmless = real.replace("## 0. 结论先行：四个答案", "## 0. 结论先行：四个答案（附原估对照）")
    monkeypatch.setattr(sys.modules[__name__], "_text", lambda rel: harmless)
    test_plan_numbers_match_the_data()
    test_original_estimates_are_still_present()
