"""食性表核验单脚本（`build_food_review_sheet.py`）的回归测试。

守三类风险：

1. **产物过期**：数据改了却没重新生成核验单 —— 审核人照着旧单子审，白做一遍。
   这是最隐蔽的一类，因为单子看起来永远「像那么回事」。
2. **输出不确定**：`--check` 靠「重新生成 == 磁盘内容」判定，所以渲染必须是**确定性**的。
   哪天有人往产物里塞一个生成时间戳，`--check` 就会永远红灯（或者更糟：被删掉）。
3. **检查项静默失效**：脚本里的每条检查都要能真的抓出问题，不能是摆设。

第三条用**负控制**测：喂一份人造数据给检查函数，断言它报出预期的问题。
只测「真实数据上没报错」是不够的 —— 那和「检查根本没跑」长得一模一样。

另外守一条**事实源漂移**：`docs/food-properties-sources.json` 是 ①②③ 层的事实源，
它和 `food_properties.json` 一旦不同步，审核人就会照旧值判断（比没依据更危险）。
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
SOURCES_PATH = CORE_DIR.parent / "docs" / "food-properties-sources.json"
SHEET_PATH = CORE_DIR.parent / "docs" / "food-properties-review-sheet.md"

# 128 foods + 1（香菇 xianggu，由「蘑菇」拆条新增）+ 18 tea_drinks = 147
EXPECTED_TOTAL = 147
EXPECTED_FOODS = 129
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
def sources(mod):
    return mod.load_sources(SOURCES_PATH)


@pytest.fixture(scope="module")
def issues(mod, entries, sources):
    return mod.run_checks(entries, mod.load_herb_nature(HERBS_PATH), sources)


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


def test_render_is_deterministic(mod, entries, sources):
    """同一份数据渲染两次必须逐字相同。

    `--check` 的判据就是「重新生成 == 磁盘内容」，所以渲染里**不能有**时间戳、
    `set` 迭代顺序这类不确定成分。这条测试是 `--check` 自身可信的前提。
    """
    meta, _ = mod.load_foods(FOOD_PATH)
    herbs = mod.load_herb_nature(HERBS_PATH)
    first = mod.render(entries, meta, mod.run_checks(entries, herbs, sources), FOOD_PATH, sources)
    second = mod.render(entries, meta, mod.run_checks(entries, herbs, sources), FOOD_PATH, sources)
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
    """variant_nature 与 layer_2 兜底规则差一档时必须报矛盾。

    咖啡曾是真实一例（温 + 冰镇应得平，却记了凉），已修；这里用现场造的数据守检查本身。
    """
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


def test_sources_consistency_check_detects_nature_drift(mod) -> None:
    """来源登记表登记的 project 值与数据现值不一致时必须报矛盾。

    **负控制**：真实数据上这条检查是安静的（已同步），所以必须现场造一份漂移数据，
    否则「检查没跑」和「检查通过」长得一模一样。
    """
    items = [_entry(id="a", nature="cool")]
    fake_sources = {"entries": [{"id": "a", "name": "某物", "project": {"nature": "cold"}, "layer": "①"}]}
    out = mod.check_sources_consistency(items, fake_sources)
    assert [i["kind"] for i in out] == ["来源登记漂移"]


def test_sources_consistency_check_detects_missing_id(mod) -> None:
    """来源登记表里的 id 已不在数据表里时必须报矛盾（改数据忘了同步文档）。"""
    items = [_entry(id="a")]
    fake_sources = {"entries": [{"id": "gone", "name": "已删条目", "project": {}, "layer": "①"}]}
    out = mod.check_sources_consistency(items, fake_sources)
    assert [i["kind"] for i in out] == ["来源登记漂移"]


def test_sources_consistency_check_detects_bad_layer(mod) -> None:
    """layer 取值非法时必须报矛盾（合法值只有 ①②③④）。"""
    items = [_entry(id="a", nature="cool")]
    fake_sources = {"entries": [{"id": "a", "name": "某物", "project": {"nature": "cool"}, "layer": "层一"}]}
    out = mod.check_sources_consistency(items, fake_sources)
    assert [i["kind"] for i in out] == ["来源登记漂移"]


def test_sources_consistency_is_clean_on_real_data(issues) -> None:
    """真实数据上，来源登记表与数据表必须已同步（否则审核人会照旧值判断）。"""
    drift = [i for i in issues if i["kind"] == "来源登记漂移"]
    assert not drift, f"来源登记表已漂移：{[r for i in drift for r in i['rows']]}"


# ============================================================
# 5. 事实源（sources.json）与「第一批」的定义
# ============================================================
def test_first_batch_is_defined_by_sources_not_category(mod, entries, sources) -> None:
    """「第一批」是 `sources.json` 的属性，**不是类别的属性**。

    旧实现把"主食/乳饮/水产"写死在脚本里，理由是"官方食养指南覆盖得到"——已被证伪
    （全表能沾到官方来源的只有 4 条，那三个大类恰是加工品最密集的区段）。
    这条测试钉住新定义：第一批 = batch 字段标第一批的条目，与 category 无关。
    """
    primary = mod.primary_batch_ids(sources)
    assert primary, "sources.json 里没有任何 batch=第一批 的条目"
    batches = {s.get("batch") for s in mod.source_entries(sources)}
    assert batches <= {"第一批", "后续"}, f"出现未定义的 batch 取值：{batches}"
    # 第一批必须横跨多个类别 —— 若它又变成"某几个类别"，说明定义退回去了
    cats = {e.get("category") for e in entries if e["id"] in primary}
    assert len(cats) >= 3, f"第一批只覆盖 {len(cats)} 个类别，可能又退回按类别定义：{cats}"


def test_sources_ids_all_exist_in_food_table(mod, entries, sources) -> None:
    """来源登记表里的每个 id 都必须能在食性表里找到。"""
    known = {e["id"] for e in entries}
    missing = sorted(s["id"] for s in mod.source_entries(sources) if s.get("id") not in known)
    assert not missing, f"来源登记表里有食性表不存在的 id：{missing}"


def test_sources_layers_are_known(mod, sources) -> None:
    """layer 只能是 ①②③④ 之一。"""
    bad = sorted(
        f"{s.get('id')}={s.get('layer')!r}" for s in mod.source_entries(sources)
        if s.get("layer") not in mod.SOURCE_LAYERS
    )
    assert not bad, f"layer 取值非法：{bad}"


def test_sheet_renders_layers_from_sources(mod, sources) -> None:
    """核验单必须真的把 ①②③ 层渲染出来（否则「已跑完」只是一句话）。"""
    text = SHEET_PATH.read_text(encoding="utf-8")
    assert "### 4.1" in text, "核验单缺少 ① 层逐条表"
    assert "### 4.2" in text, "核验单缺少 ② 层（冲突）表"
    assert "### 4.4" in text, "核验单缺少非正名映射的裁定表"
    # 渲染出来的一级层数必须与事实源一致（防「渲染漏条目」）
    primary = mod.primary_batch_ids(sources)
    assert f"「第一批」**{len(primary)}** 条" in text, "核验单里第一批条数与 sources.json 不一致"


def test_mapping_review_is_recorded_and_consistent(mod, sources) -> None:
    """非正名映射的裁定结果必须逐条记在事实源里，且与 layer 自洽。

    `qingcai` 是第一批里唯一被否掉的映射：它必须同时满足「未采纳」且「已降级为 ③」，
    不能只改一处 —— 只改 mapping_review 不改 layer，就会留下一条假的"一致"。

    注意筛「待确认」时**必须先限定在有 `mapping_review` 的条目里**：写成
    `(s.get("mapping_review") or {}).get("accepted") is None` 会把「压根没登记裁定」
    的条目也算进来（`{}` 的 `.get` 同样返回 None），于是几十条无关条目一起报错。
    """
    entries = mod.source_entries(sources)
    reviewed = [s for s in entries if s.get("mapping_review")]
    assert len(reviewed) >= 16, f"登记过裁定的非正名映射只有 {len(reviewed)} 条，疑似漏记"
    for s in reviewed:
        review = s["mapping_review"]
        assert "accepted" in review, f"{s['id']} 的裁定没有 accepted 字段"
        assert review["accepted"] in (True, False, None)
        assert review.get("reason"), f"{s['id']} 的裁定没有理由"
    rejected = [s for s in reviewed if s["mapping_review"]["accepted"] is False]
    for s in rejected:
        assert s.get("layer") == "③", f"{s['id']} 映射被否却没降级到 ③（仍记 {s.get('layer')}）"
    pending = [s for s in reviewed if s["mapping_review"]["accepted"] is None]
    for s in pending:
        assert s.get("layer") == "②", f"{s['id']} 映射待确认，layer 应为 ②（实际 {s.get('layer')}）"
    assert rejected and pending, "被否／待确认两类都应有例子，否则上面两个循环是空转"
