"""食性表核验单脚本（`build_food_review_sheet.py`）的回归测试。

守三类风险：

1. **产物过期**：数据改了却没重新生成核验单 —— 审核人照着旧单子审，白做一遍。
   这是最隐蔽的一类，因为单子看起来永远「像那么回事」。
2. **输出不确定**：`--check` 靠「重新生成 == 磁盘内容」判定，所以渲染必须是**确定性**的。
   哪天有人往产物里塞一个生成时间戳，`--check` 就会永远红灯（或者更糟：被删掉）。
3. **检查项静默失效**：脚本里的每条检查都要能真的抓出问题，不能是摆设。

第三条用**负控制**测：喂一份人造数据给检查函数，断言它报出预期的问题。
只测「真实数据上没报错」是不够的 —— 那和「检查根本没跑」长得一模一样。

第四条同样靠负控制：**受控词表**（`evidence[].how` / `tier`）是散落在几十条依据里的取值，
写错一个词不会有任何反馈；而核验单 §4.4 的「限定（how）」列还可能因为**取错 evidence**
（`reference` 里根本没有 `how`，同一条目又常有多条依据）而**静默显示错值**。
另加一条**事实源漂移**：`docs/food-properties-sources.json` 是 ①②③ 层的事实源，
它和 `food_properties.json` 一旦不同步，审核人就会照旧值判断（比没依据更危险）。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from app.domain.enums import NATURE_LABELS

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
    """非正名映射的裁定必须逐条登记，且与 layer 自洽。

    这里刻意**不再写「被否／待确认两类都要有真实例子」**：那要求真实数据里永远存在一个
    待确认的条目，`jiangyou` 一裁定就红，而且红的信息分不清「数据坏了」还是「活儿干完了」
    —— 正是本项目反对的**数据快照式断言**。

    职责这样分工：**派生不变式**（`mapping_layer_gaps`，规则写在被调函数里）管真实数据，
    「两类不自洽都必须被抓出来」由**合成数据**的负控制管（见下一条）。
    """
    entries = mod.source_entries(sources)
    reviewed = [s for s in entries if s.get("mapping_review")]
    assert len(reviewed) >= 16, f"登记过裁定的非正名映射只有 {len(reviewed)} 条，疑似漏记"
    for s in reviewed:
        review = s["mapping_review"]
        assert "accepted" in review, f"{s['id']} 的裁定没有 accepted 字段"
        assert review["accepted"] in (True, False, None)
        assert review.get("reason"), f"{s['id']} 的裁定没有理由"
    gaps = mod.mapping_layer_gaps(entries)
    assert not gaps, f"映射裁定与 layer 不自洽：{gaps}"


def test_mapping_layer_gaps_negative_control(mod) -> None:
    """负控制：两类不自洽都必须被 `mapping_layer_gaps` 报出来。

    只测「真实数据上返回空」是不够的 —— 那和「这个函数根本没跑」长得一模一样。
    顺带钉住一件事：**没登记 `mapping_review` 的条目不参与判定**，外部不必先行过滤
    （这正是当年 `(s.get("mapping_review") or {}).get("accepted") is None` 那个写法的坑：
    `{}` 的 `.get` 同样返回 None，会把几十条压根没登记的条目一起算进来）。
    """
    synthetic = [
        {"id": "rej_no_demote", "layer": "①", "mapping_review": {"accepted": False}},
        {"id": "pending_as_consistent", "layer": "①", "mapping_review": {"accepted": None}},
        {"id": "no_review_at_all", "layer": "①"},
    ]
    gaps = mod.mapping_layer_gaps(synthetic)
    assert any("rej_no_demote" in g for g in gaps), "映射被否却没降级到 ③，没被抓出来"
    assert any("pending_as_consistent" in g for g in gaps), "待确认却记成 ①，没被抓出来"
    assert not any("no_review_at_all" in g for g in gaps), "没登记裁定的条目不该参与判定"


# ============================================================
# 6. 受控词表（`how` / `tier`）与核验单 §4.4
# ============================================================
def _vocab(sources: dict, key: str) -> dict:
    vocab = (sources.get("_meta") or {}).get("controlled_vocab") or {}
    assert key in vocab, f"`_meta.controlled_vocab` 缺少 `{key}`"
    return vocab[key]


def _evidence_rows(sources: dict) -> list[tuple[str, dict]]:
    """(条目 id, 该条目的每条 evidence)，供词表类断言遍历。"""
    return [
        (s.get("id"), ev)
        for s in (sources.get("entries") or [])
        for ev in (s.get("evidence") or [])
    ]


def test_how_values_are_in_controlled_vocab(mod, sources) -> None:
    allowed = set(_vocab(sources, "how")["取值"])
    bad = mod.out_of_vocab([ev.get("how") for _, ev in _evidence_rows(sources)], allowed)
    assert not bad, (
        "evidence[].how 出现词表外取值 —— 新增取值必须先登记进 "
        f"`_meta.controlled_vocab.how`：{bad}"
    )


def test_how_vocab_negative_control(mod, sources) -> None:
    """负控制：旧混用值「别名/等价名」必须仍被判为词表外。

    2026-09-18 归一前，8 处 `how` 就是这个混用值 —— 它把「别名」与「等价名」两种
    不同的对当关系糅在一格里，「限定」形同虚设。若哪天有人把它加回词表，这条会红。
    """
    allowed = set(_vocab(sources, "how")["取值"])
    assert mod.out_of_vocab(["别名/等价名", "别名"], allowed) == ["别名/等价名"]


def test_tier_values_are_in_controlled_vocab(mod, sources) -> None:
    allowed = set(_vocab(sources, "tier")["取值"])
    bad = mod.out_of_vocab([ev.get("tier") for _, ev in _evidence_rows(sources)], allowed)
    assert not bad, f"evidence[].tier 出现词表外取值（先登记进 controlled_vocab.tier）：{bad}"


def test_tier_vocab_negative_control(mod, sources) -> None:
    """负控制：注册表的档名（`官方`）不是**条目**的档名，必须被判为词表外。

    这两个层级容易被混：`_meta.source_registry` 给**强度档**（官方／通行·教材／通行·经典），
    `evidence[].tier` 给「档＋限定」（官方·药典／官方·目录(仅身份)／通行·教材(有冲突)／…）。
    """
    allowed = set(_vocab(sources, "tier")["取值"])
    assert mod.out_of_vocab(["官方", "通行·教材"], allowed) == ["官方"]
    assert "通行·教材" in allowed


def test_tier_maps_to_registry(sources) -> None:
    """每个用到的 `tier` 都必须能映射到 `_meta.source_registry` 里的档位之一。

    守的是「tier 被随手新造、注册表里根本没这个强度档」—— 那样来源强度就无从核对，
    而核验单上只显示一个看起来很像真的档名。
    """
    mapping = _vocab(sources, "tier").get("对应") or {}
    registry = set(((sources.get("_meta") or {}).get("source_registry") or {}).keys())
    assert registry, "source_registry 为空"
    used = {ev.get("tier") for _, ev in _evidence_rows(sources)}
    missing = sorted(t for t in used if t not in mapping)
    assert not missing, f"tier 没有登记对应档位：{missing}"
    bad = sorted(f"{t} → {mapping.get(t)}" for t in used if mapping.get(t) not in registry)
    assert not bad, f"tier 对应的档位不在 source_registry 里：{bad}"


def test_evidence_how_aligns_to_reference_not_first(mod) -> None:
    """`evidence_how` 必须按 `reference` 对齐取 `how`，**不能取 `evidence[0]`**。

    造一条「第一条是别的来源」的合成数据：只有按 (source_id, matched_name) 对齐才会
    拿到「别名」，取 `[0]` 会错拿成「正名（药典收载名）」。真实数据里 `mogu`（2 条）、
    `jiang`/`longyan`/`shanzha_guo`（各 3 条）都是多条 evidence —— 取错**不会报错**，
    只会把错误的限定静默渲染给审核人看。
    """
    evidence = [
        {"source_id": "chp2020", "matched_name": "生姜", "how": "正名（药典收载名）"},
        {"source_id": "s1_dietetics", "matched_name": "生姜", "how": "别名"},
    ]
    assert mod.evidence_how({"source_id": "s1_dietetics", "matched_name": "生姜"}, evidence) == "别名"
    assert mod.evidence_how({"source_id": "chp2020", "matched_name": "生姜"}, evidence) == "正名（药典收载名）"
    assert mod.evidence_how({"matched_name": "查无此名"}, evidence) == "—"
    assert mod.evidence_how(None, evidence) == "—"


def test_sheet_44_row_count_matches_sources(mod, sources) -> None:
    """核验单 §4.4 的行数与 id 集合必须**精确等于**事实源里登记过裁定的条目。

    防「渲染漏条目」：少一行时审核人不会发现 —— 表格看起来永远是完整的。
    （原先只测「§4.4 这个标题存在」，那连「一条都没渲染」都拦不住。）
    """
    text = SHEET_PATH.read_text(encoding="utf-8")
    assert "### 4.4" in text, "核验单缺少 §4.4"
    section = _section_between(text, "### 4.4")
    rows = [ln for ln in section.splitlines() if ln.startswith("| `")]
    expected = {s["id"] for s in mod.source_entries(sources) if s.get("mapping_review")}
    got = {ln.split("`")[1] for ln in rows}
    assert got == expected, (
        f"§4.4 渲染了 {len(got)} 条、事实源里有 {len(expected)} 条；"
        f"缺={sorted(expected - got)} 多={sorted(got - expected)}"
    )


def test_outcome_counts_match_actual(sources) -> None:
    """`_meta.mapping_review.outcome` 的三态计数必须等于**实算**。

    这条有来由：`scope` 当年把 `xianggu`（拆条新增的第 18 条）漏在编号体系外，
    于是 `outcome` 只数了 17 条 —— 文件内部自相矛盾，但读的人不会去核对。
    现在计数与实算绑在一起：加一条裁定就必须同步，改不了「悄悄少一条」。
    """
    reviewed = [s for s in (sources.get("entries") or []) if s.get("mapping_review")]
    outcome = ((sources.get("_meta") or {}).get("mapping_review") or {}).get("outcome") or {}
    actual = {
        "accepted": sum(1 for s in reviewed if s["mapping_review"].get("accepted") is True),
        "rejected": sum(1 for s in reviewed if s["mapping_review"].get("accepted") is False),
        "pending": sum(1 for s in reviewed if s["mapping_review"].get("accepted") is None),
    }
    assert sum(actual.values()) == len(reviewed), "有 accepted 取值既不是 True/False/None"
    for key, n in actual.items():
        assert outcome.get(key) == n, f"outcome.{key} 记 {outcome.get(key)}，实算 {n}"


# ============================================================
# 6b. §4.5 / §4.6 —— B4 派生产物必须真的进核验单（挂起项 D13）
# ============================================================
# 为什么单列：A1 的人工审核**以核验单为唯一依据**，而 B4 的 53 条 `note` 与 4 条
# `_meta.derivation_conflicts` 原先在核验单里**一个字都不出现**（实测「派生：」「属性冲突」
# 各 0 次）—— 审核人看不到「这个值是怎么推出来的」。表格看起来永远是完整的，
# 所以「漏渲染」和「渲染对了」从产物表面分不出来，必须用派生不变式钉住。
def _cn(value: object) -> str:
    """四气标识 → 中文标签。**独立于脚本实现**：用它验证渲染，而不是拿实现验自己。"""
    if value is None:
        return "—"
    return NATURE_LABELS.get(str(value), str(value))


def _section_between(text: str, heading: str) -> str:
    """取 heading 之后、到**下一个同级或更高级**标题为止的正文。

    边界必须同时认 `###` 与 `##`：§4.5／§4.6 是 D13 新增的**三级**节，若只认 `##`，
    它们会被算进 §4.4 的正文里（§4.4 的 id 集合守卫会因此假红 —— 表格行被并进下一节）。
    """
    body = text.split(heading, 1)[1]
    for stop in ("\n### ", "\n## "):
        idx = body.find(stop)
        if idx != -1:
            body = body[:idx]
    return body


def _section_of(heading: str) -> str:
    text = SHEET_PATH.read_text(encoding="utf-8")
    assert heading in text, f"核验单缺少小节：{heading}"
    return _section_between(text, heading)


def _table_rows(section: str) -> list[list[str]]:
    """取 `| `…|` 数据行并切列（首尾竖线已剥掉）。"""
    return [
        [c.strip() for c in ln.strip().strip("|").split("|")]
        for ln in section.splitlines()
        if ln.startswith("| `")
    ]


def test_sheet_45_derivation_notes_are_rendered_verbatim(mod, entries) -> None:
    """§4.5 必须逐字渲染数据里全部派生类 `note`。

    防两类失效：**漏条目**（审核人看不到这一条的推导过程）与**改文案**（审核人看到的
    不是系统实际在用的那句 —— 而 `note` 会被渲染进 Agent1 提示词，两处必须同一份）。
    """
    expected = {
        e["id"]: (e.get("note") or "").strip()
        for e in entries
        if (e.get("note") or "").strip().startswith(mod.DERIVATION_PREFIXES)
    }
    assert len(expected) >= 53, f"数据里的派生类 note 少于 53 条（样本被偷？）：{len(expected)}"
    has_pipe = sorted(i for i, n in expected.items() if "|" in n)
    assert not has_pipe, f"派生 note 含表格分隔符 `|`，会破坏核验单表格：{has_pipe}"

    rows = _table_rows(_section_of("### 4.5"))
    got = {r[0].strip("`") for r in rows}
    assert got == set(expected), (
        f"§4.5 渲染 {len(got)} 条、数据里 {len(expected)} 条；"
        f"缺={sorted(set(expected) - got)} 多={sorted(got - set(expected))}"
    )

    by_id = {r[0].strip("`"): r for r in rows}
    drift = sorted(i for i, want in expected.items() if by_id[i][-1] != want)
    assert not drift, f"§4.5 的 note 与数据不再逐字一致（前 3 条：{drift[:3]}）"


def test_sheet_46_conflict_rows_match_registry(mod) -> None:
    """§4.6 的 id 集合与四个字段必须等于 `_meta.derivation_conflicts`。"""
    meta, _ = mod.load_foods(FOOD_PATH)
    registry = meta.get("derivation_conflicts") or {}
    assert len(registry) >= 4, f"冲突登记少于 4 条（样本被偷？）：{len(registry)}"

    rows = _table_rows(_section_of("### 4.6"))
    assert len(rows) == len(registry), f"§4.6 行数 {len(rows)} ≠ 登记 {len(registry)} 条（有重复或缺漏）"
    by_id = {r[0].strip("`"): r for r in rows}
    assert set(by_id) == set(registry), (
        f"§4.6 与登记 id 集不一致：缺={sorted(set(registry) - set(by_id))} "
        f"多={sorted(set(by_id) - set(registry))}"
    )

    for eid, rec in registry.items():
        cells = by_id[eid]  # 列序：id | 名称 | 现值 | 派生值 | 冲突原因 | 状态
        assert cells[1] == rec.get("name"), f"{eid}: 名称不符（{cells[1]!r} vs {rec.get('name')!r}）"
        assert cells[2] == _cn(rec.get("current")), f"{eid}: 现值不符（{cells[2]!r} vs {_cn(rec.get('current'))!r}）"
        assert cells[3] == _cn(rec.get("derived")), f"{eid}: 派生值不符（{cells[3]!r} vs {_cn(rec.get('derived'))!r}）"
        assert cells[4] == rec.get("reason"), f"{eid}: 冲突原因不符"
        assert cells[5] == rec.get("status"), f"{eid}: 状态不符（{cells[5]!r} vs {rec.get('status')!r}）"


def test_sheet_46_negative_control_registry_drift_is_detected(mod) -> None:
    """负控制：登记被改坏时，§4.6 的比对必须真的会红 —— 否则上一条是空转。

    三种坏法各测一次（删一条 / 登记值撒谎 / 凭空多一条），都用**真实产品行**比对。
    """
    meta, _ = mod.load_foods(FOOD_PATH)
    registry = meta.get("derivation_conflicts") or {}
    rows = {r[0].strip("`"): r for r in _table_rows(_section_of("### 4.6"))}

    def gaps(reg: dict) -> set[str]:
        """登记 ⟷ 核验单的对称差：id 集合差异，加上「派生值」栏与登记不符的。"""
        common = set(reg) & set(rows)
        value_drift = {eid for eid in common if rows[eid][3] != _cn((reg[eid] or {}).get("derived"))}
        return (set(reg) ^ set(rows)) | value_drift

    assert gaps(registry) == set(), "真实数据下 §4.6 与登记就已不一致"
    dropped = {k: v for k, v in registry.items() if k != "pijiu"}
    assert gaps(dropped) == {"pijiu"}, "删掉一条登记竟未被发现"
    lied = {k: dict(v) for k, v in registry.items()}
    lied["liangcha"]["derived"] = "hot"
    assert gaps(lied) == {"liangcha"}, "登记里的派生值撒谎竟未被发现"
    extra = dict(registry, fictitious={
        "name": "虚构项", "current": "cool", "derived": "cool", "reason": "x", "status": "待裁定",
    })
    assert gaps(extra) == {"fictitious"}, "凭空多出一条登记竟未被发现"


# ============================================================
# 7. A2 落定后的数据侧守卫
# ============================================================
# ⚠️ 这个词表**刻意放在测试里，不放运行时模块**：它是一次性清理的**历史集合**
# （A2 ② 的落定结果），放进 `food_lookup` 只会变成没人调用的死代码 ——
# 本项目刚因「死代码被误当成入口」踩过坑（见 `matcher.build_basis` 的先例）。
A2_REMOVED_MUSHROOM_WORDS = ("金针菇", "杏鲍菇", "平菇")

# 匹配面有三个字段。之所以三个都要扫，是因为 `_find_entry` 的第 2 级把
# `keywords` 与 `aliases` **合并**成一处扫描（core/app/services/food_lookup.py:286）——
# 「只删 keywords」是无效的，词只要还挂在任一处就仍会命中。
def bound_words(entries: list[dict], words) -> list[str]:
    """返回仍被任何条目 `name`/`aliases`/`keywords` 挂着的词（空 = 已清干净）。"""
    out = []
    for word in words:
        for e in entries:
            fields = [e.get("name")] + list(e.get("aliases") or []) + list(e.get("keywords") or [])
            if any((f or "").strip() == word for f in fields):
                out.append(f"{word} ← `{e.get('id')}`")
                break
    return sorted(out)


def test_removed_mushroom_words_are_bound_to_no_entry(entries) -> None:
    """A2 ② 走 (C)：金针菇 / 杏鲍菇 / 平菇 必须已从**所有**条目移出（两处都清）。

    移出后这 3 个词走「表未覆盖」的模型推测分支（界面标「食性未经验证」，置信度
    由表内命中的 0.9 降为 0.3）。选择移出而不是暂留的理由正是这条：**以 0.9 的置信度
    呈现一个无来源的四气，比以 0.3 诚实标注「未经验证」更危险。**
    """
    stray = bound_words(entries, A2_REMOVED_MUSHROOM_WORDS)
    assert not stray, f"这 3 个词又挂回条目上了（会以 0.9 置信度呈现无来源的四气）：{stray}"


def test_removed_words_scanner_covers_both_fields() -> None:
    """负控制：扫描器必须**同时**覆盖 `aliases` 与 `keywords`。

    这正是踩过的坑：确认稿 (B) 选项写「移除 `keywords` 后落到 unknown」，而
    `_find_entry` 把两处合并扫描 —— 只删一处，词照旧命中，问题看起来「已修」。
    只喂一种字段的负控制测不出这个坑，所以这里造两条：**只挂 `aliases`** 与
    **只挂 `keywords`**。
    """
    synthetic = [
        {"id": "only_aliases", "name": "甲", "aliases": ["金针菇"], "keywords": []},
        {"id": "only_keywords", "name": "乙", "aliases": [], "keywords": ["平菇"]},
        {"id": "clean", "name": "丙", "aliases": ["蘑菰"], "keywords": ["蘑菇"]},
    ]
    stray = bound_words(synthetic, A2_REMOVED_MUSHROOM_WORDS)
    assert any("only_aliases" in s for s in stray), "只挂在 aliases 上的没被抓出来"
    assert any("only_keywords" in s for s in stray), "只挂在 keywords 上的没被抓出来"
    assert not any("clean" in s for s in stray), "没挂这些词的条目不该被报出来"


def test_first_batch_conflicts_have_note(mod, entries, sources) -> None:
    """第一批 ② 层（口径分歧）条目必须在**数据**里有 `note` 留痕。

    核验单 §4.2 表下注写着「一律保留项目值并在数据里加 `note` 留痕」—— 这句在
    `jiangyou` 补 `note` 之前是**假陈述**（4 条里只有 3 条有）。核验单是审核人的依据来源，
    「说了不做」比「不说」更坏。这条把那句话变成**机器可验**的。

    名单从 `sources.json` 的 `layer` 派生，**不写死条目**；只查「有没有 note」，
    不查 note 的内容（内容归审核人判断）。
    """
    by_id = {e["id"]: e for e in entries}
    expected = [
        s for s in mod.source_entries(sources)
        if s.get("batch") == mod.BATCH_PRIMARY and s.get("layer") == "②"
    ]
    assert expected, "第一批 ② 层一条都没有？`sources.json` 的 layer 字段可能坏了"
    missing = [
        s["id"] for s in expected
        if not ((by_id.get(s["id"]) or {}).get("note") or "").strip()
    ]
    assert not missing, (
        f"第一批 ② 层条目缺 `note` 留痕（核验单 §4.2 声称「一律加 note」）：{missing}"
    )


# ============================================================
# 8. B1 落定后的守卫：「制品·原料继承」必须指向真实存在的同名饮片
# ============================================================
# ⚠️ 这组helper**刻意放在测试里，不放脚本**：它只在「判定继承链是否成立」这一处用，
# 放进 `build_food_review_sheet.py` 会变成没人调用的死代码 —— 本项目刚因「死代码被误
# 当成入口」踩过坑（见 `matcher.build_basis` 的先例）。这与 `A2_REMOVED_MUSHROOM_WORDS`
# 的处置一致：一次性/单处的判定逻辑留在守卫它的测试里。
INHERITANCE_HOW = "制品·原料继承"


def _herb_natures() -> dict[str, str]:
    """`herbs.json` 的 {饮片名: 四气}。"""
    data = json.loads(HERBS_PATH.read_text(encoding="utf-8"))
    return {h["name"]: h.get("nature") for h in data["herbs"]}


def inheritance_rows(sources: dict) -> list[tuple[str, str, str]]:
    """(条目 id, matched_name, 该条目登记的 project.nature)，只取 how=制品·原料继承 的依据。"""
    return [
        (s.get("id"), ev.get("matched_name"), (s.get("project") or {}).get("nature"))
        for s in (sources.get("entries") or [])
        for ev in (s.get("evidence") or [])
        if ev.get("how") == INHERITANCE_HOW
    ]


def inheritance_gaps(rows, herb_natures: dict[str, str]) -> tuple[list[str], list[str]]:
    """返回（指向不存在饮片的、四气与原料不符的）；两空 = 继承链成立。"""
    unknown = sorted({f"`{i}` → {m}" for i, m, _ in rows if m not in herb_natures})
    mismatched = sorted(
        f"`{i}` → {m}（饮片 {herb_natures[m]} vs 登记 {n}）"
        for i, m, n in rows if m in herb_natures and herb_natures[m] != n
    )
    return unknown, mismatched


def test_product_inheritance_points_at_a_real_herb(sources) -> None:
    """标了「制品·原料继承」的依据，必须指向 `herbs.json` 里**存在且四气相同**的饮片。

    这是继承链唯一能用机器守住的地方。50 号文件 §5.2 明令「凡『茶』『糖』『汁』『粉』类
    后缀，**不可默认继承原料的四气**」，B1 是按项目所有者裁定**推翻**了它（推翻理由逐条
    写在 `mapping_review.reason`，不是「没看到那条规则」）。既然开了这个口子，「继承」
    两个字就必须承重：否则将来有人把「水果茶」「奶盖茶」也标成继承，指向一个不存在的
    原料、或四气根本对不上，一样能通过其余所有检查 —— 那才是把推翻变成漏洞。
    """
    herb_natures = _herb_natures()
    assert herb_natures, f"没从 {HERBS_PATH.name} 读出饮片"
    rows = inheritance_rows(sources)
    assert rows, f"sources.json 里没有任何 how={INHERITANCE_HOW} 的依据（B1 的茶饮 10 条？）"
    unknown, mismatched = inheritance_gaps(rows, herb_natures)
    assert not unknown, f"标了「{INHERITANCE_HOW}」却指向不存在的饮片：{unknown}"
    assert not mismatched, f"继承值与原料四气不符：{mismatched}"


def test_product_inheritance_guard_negative_control() -> None:
    """负控制：**不存在**的原料与**四气对不上**的原料都必须被上一条抓出来。

    只测「真实数据上没报错」是不够的 —— 那和「这段逻辑根本没跑」长得一模一样。
    三种样本缺一不可：正常继承（必须放过）、不存在的原料、四气不符的原料。
    """
    herb_natures = {"菊花": "cool"}
    rows = [
        ("ok_inherit", "菊花", "cool"),
        ("ghost_herb", "no_such_herb", "cool"),
        ("wrong_nature", "菊花", "warm"),
    ]
    unknown, mismatched = inheritance_gaps(rows, herb_natures)
    assert any("ghost_herb" in x for x in unknown), "指向不存在饮片的没被抓出来"
    assert any("wrong_nature" in x for x in mismatched), "继承值与原料四气不符的没被抓出来"
    assert not any("ok_inherit" in x for x in unknown + mismatched), "正常的继承不该被报出来"


# ============================================================
# 9. B2 落定后的守卫：「制品·原料继承（语料原料）」必须落在白名单且四气一致
# ============================================================
# ⚠️ 与 §8 一样，这组 helper **刻意放在测试里、不放脚本**：它只在「语料继承链是否成立」这一处用，
# 放进 `build_food_review_sheet.py` 会变成没人调用的死代码（见 §7 与 `matcher.build_basis` 的先例）。
CORPUS_INHERITANCE_HOW = "制品·原料继承（语料原料）"


def corpus_ancestors(sources: dict) -> dict[str, str]:
    """`_meta.corpus_ancestors.ancestors` 的 {语料条目名: 四气}。"""
    node = (sources.get("_meta") or {}).get("corpus_ancestors") or {}
    return {k: (v or {}).get("nature") for k, v in (node.get("ancestors") or {}).items()}


def corpus_inheritance_rows(sources: dict) -> list[tuple[str, str, str]]:
    """(条目 id, matched_name, evidence 的 qi_mapped)，只取 how=制品·原料继承（语料原料）的依据。"""
    return [
        (s.get("id"), ev.get("matched_name"), ev.get("qi_mapped"))
        for s in (sources.get("entries") or [])
        for ev in (s.get("evidence") or [])
        if ev.get("how") == CORPUS_INHERITANCE_HOW
    ]


def corpus_inheritance_gaps(rows, whitelist: dict[str, str]) -> tuple[list[str], list[str], list[str]]:
    """返回（白名单外的原料、与白名单四气不符的、白名单里没被任何依据引用的）。三空 = 成立。"""
    unknown = sorted({f"`{i}` → {m}" for i, m, _ in rows if m not in whitelist})
    mismatched = sorted(
        f"`{i}` → {m}（白名单 {whitelist[m]} vs 登记 {q}）"
        for i, m, q in rows if m in whitelist and whitelist[m] != q
    )
    used = {m for _, m, _ in rows}
    unused = sorted(set(whitelist) - used)
    return unknown, mismatched, unused


def test_corpus_inheritance_matches_the_whitelist(sources) -> None:
    """标了「制品·原料继承（语料原料）」的依据，必须指向白名单内的语料条目、且四气等于登记值。

    B1 给「制品·原料继承」立了守卫：原料必须是 `herbs.json` 里**真实存在且四气相同**的饮片
    （§8）。B2 的面制品/米饭/白粥套不上那条 ——「面」「粳米」「米粥」都不在那 34 味里。既然又开了
    一个「原料是**语料条目**」的口子，本守卫就补上同样的承重：同一个原料（如「面」被 6 条面制品
    引用）必须记同一个四气，写错一个不会有别的反馈。白名单同时**不许有死条目** ——
    登记了却没被任何依据引用，它就会变成一份没人核对的名单。

    样本从**数据反推**（不写死条目），并断言「至少测到 N 组」：否则这批依据一旦被清空，
    守卫会在空集上恒真 —— 那正是本项目反复踩过的「守卫恒真」坑。
    """
    whitelist = corpus_ancestors(sources)
    assert whitelist, "sources.json 缺少 _meta.corpus_ancestors.ancestors"
    rows = corpus_inheritance_rows(sources)
    assert len(rows) >= 6, f"how={CORPUS_INHERITANCE_HOW} 的依据只有 {len(rows)} 条，样本太少"
    assert len({m for _, m, _ in rows}) >= 2, "只覆盖 1 个语料原料，测不到『跨条目漂移』"
    unknown, mismatched, unused = corpus_inheritance_gaps(rows, whitelist)
    assert not unknown, f"标了「{CORPUS_INHERITANCE_HOW}」却指向白名单外的语料条目：{unknown}"
    assert not mismatched, f"继承值与白名单登记的四气不符：{mismatched}"
    assert not unused, f"白名单里有登记了但没被任何依据引用的死条目：{unused}"


def test_corpus_inheritance_guard_negative_control() -> None:
    """负控制：白名单外的原料、四气不符、白名单死条目，三种都必须被抓出来。

    只测「真实数据上没报错」是不够的 —— 那和「这段逻辑根本没跑」长得一模一样。
    四种样本缺一不可：正常继承（必须放过）、白名单外原料、四气不符、白名单没用到的条目。
    """
    whitelist = {"面": "warm", "粳米": "neutral", "死条目": "cool"}
    rows = [
        ("ok", "面", "warm"),
        ("ok2", "粳米", "neutral"),
        ("ghost", "米粥", "neutral"),
        ("wrong", "面", "cool"),
    ]
    unknown, mismatched, unused = corpus_inheritance_gaps(rows, whitelist)
    assert any("ghost" in x for x in unknown), "白名单外的原料没被抓出来"
    assert any("wrong" in x for x in mismatched), "四气与白名单不符的没被抓出来"
    assert unused == ["死条目"], "白名单里没被引用的条目没被抓出来"
    assert not any(("ok" in x) or ("ok2" in x) for x in unknown + mismatched), "正常的继承不该被报出来"


# ============================================================
# 10. B3 落定后的守卫
# ============================================================
# ⚠️ 与 §7/§8/§9 同理：只被守卫用到的判定逻辑刻意留在测试里，不放 `build_food_review_sheet.py`
# —— 放进脚本会变成没人调用的死代码（见 `matcher.build_basis` 的先例）。

# --- 组 1：网页来源必须「可核」（B3 拍板点 E）--------------------------------
# ⚠️ 这四个档名**刻意写在测试里**（与 `A2_REMOVED_MUSHROOM_WORDS` 同一处置）：
# 它们是 B3 一次性引入的历史集合，放进脚本只会变成没人调用的死代码。
WEB_TIERS = ("官方·审核词条", "官方·卫健科普", "通行·官媒科普", "通行·医院科普")

# 「强度高于网页来源」的档：按 B3 采纳的强度序，药典与教材都排在科普类之前。
# ⚠️ 这两个档名必须仍在 `tier.取值` 里 —— 否则档名一改，越级检查就在空集上**恒真**
# （这正是本项目反复踩过的「守卫恒真」坑）。
STRONG_TIERS = ("官方·药典", "通行·教材", "通行·教材(有冲突)")


def web_source_gaps(sources: dict, web_tiers=WEB_TIERS, strong_tiers=STRONG_TIERS):
    """返回 4 类问题（a 档位不可核／b 依据缺地址或原文／c 死档／d 越级），四空 = 成立。

    这四条都盯着同一件事：**B3 是本项目第一次引入「不在本地语料里」的来源**。
    B1／B2 的依据随时能在 50 号文件或纲目里重查（行号可复现），这一批不行 ——
    链接会失效、且不随仓库归档。所以「地址 + 原文句」必须随条目走，不能只有一句
    「人民网说过」。
    """
    meta = sources.get("_meta") or {}
    vocab = (meta.get("controlled_vocab") or {}).get("tier") or {}
    allowed = set(vocab.get("取值") or [])
    mapping = vocab.get("对应") or {}
    registry = meta.get("source_registry") or {}
    rows = [
        (s.get("id"), ev)
        for s in (sources.get("entries") or [])
        for ev in (s.get("evidence") or [])
    ]

    # a) 网页档必须已登记进词表、能映射到 registry，且该 registry 条目有 http 开头的 url。
    #    没有这层，「档名」就只是一个看起来很像真的字符串。
    a: list[str] = []
    for t in web_tiers:
        if t not in allowed:
            a.append(f"档 `{t}` 未登记进 controlled_vocab.tier.取值")
            continue
        key = mapping.get(t)
        if key not in registry:
            a.append(f"档 `{t}` 未映射到 source_registry 里的键（→ {key!r}）")
            continue
        url = str((registry.get(key) or {}).get("url") or "")
        if not url.lower().startswith("http"):
            a.append(f"档 `{t}` 的 registry 条目 `{key}` 缺 http 开头的 url")

    # b) 凡用了网页档的 evidence，`locator` 里必须有 URL、`verbatim` 必须非空。
    b: list[str] = []
    for sid, ev in rows:
        if ev.get("tier") not in web_tiers:
            continue
        if "http" not in str(ev.get("locator") or ""):
            b.append(f"`{sid}` 的网页依据 locator 里没有 URL")
        if not str(ev.get("verbatim") or "").strip():
            b.append(f"`{sid}` 的网页依据缺 verbatim（原文句）")

    # c) 网页档不许有死档 —— 与 `corpus_ancestors`「白名单不许有死条目」同型：
    #    登记了却没人用，就变成一份没人核对的名单。
    used = {ev.get("tier") for _, ev in rows}
    c = [f"档 `{t}` 登记了却没被任何依据引用" for t in web_tiers if t not in used]

    # d) **越级**：`reference` 取网页档时，`evidence[]` 里不得同时存在药典/教材依据。
    #    这条把「科普类来源只在药典与教材均无该条目时才可作基准」从一句
    #    `hard_rules` 变成机器可验的。
    d: list[str] = []
    for s in sources.get("entries") or []:
        ref = s.get("reference") or {}
        if ref.get("tier") not in web_tiers:
            continue
        stronger = sorted({
            ev.get("tier") for ev in (s.get("evidence") or [])
            if ev.get("tier") in strong_tiers
        })
        if stronger:
            d.append(
                f"`{s.get('id')}` 的 reference 取网页档 `{ref.get('tier')}`，"
                f"但 evidence 里有强度更高的依据 {stronger}"
            )
    return a, b, c, d


def test_web_sources_are_citable(sources) -> None:
    """B3 首次引入的网页来源必须「可核」：地址与原文句都在，且不许越级兜底。

    样本从**数据反推**（不写死条目），并断言「至少 4 个档被用到、至少 5 条依据」：
    这批依据一旦被清空，守卫会在空集上恒真 —— 本项目反复踩过的坑。
    """
    vocab = set(
        (((sources.get("_meta") or {}).get("controlled_vocab") or {}).get("tier") or {}).get("取值") or []
    )
    misnamed = [t for t in STRONG_TIERS if t not in vocab]
    assert not misnamed, (
        f"「强度高于网页来源」的档名不在 tier 词表里，越级检查会恒真：{misnamed}"
    )
    web_rows = [(sid, ev) for sid, ev in _evidence_rows(sources) if ev.get("tier") in WEB_TIERS]
    used_web = {ev.get("tier") for _, ev in web_rows}
    assert len(used_web) >= 4, f"实际用到的网页档只有 {len(used_web)} 个（{sorted(used_web)}），样本太少"
    assert len(web_rows) >= 5, f"网页依据只有 {len(web_rows)} 条，样本太少"

    a, b, c, d = web_source_gaps(sources)
    assert not a, f"网页档不可核（档名/映射/URL）：{a}"
    assert not b, f"网页依据缺地址或原文句：{b}"
    assert not c, f"网页档里有死档：{c}"
    assert not d, f"网页来源越级（有药典/教材依据却拿科普当基准）：{d}"


def test_web_source_guard_negative_control() -> None:
    """负控制：a／b／c／d 四类问题都必须被抓出来。

    只测「真实数据上返回空」是不够的 —— 那和「这段逻辑根本没跑」长得一模一样。
    """
    def _meta() -> dict:
        return {
            "controlled_vocab": {
                "tier": {
                    "取值": list(WEB_TIERS) + list(STRONG_TIERS),
                    "对应": {
                        "官方·审核词条": "satcm_terms",
                        "官方·卫健科普": "shwsjkw",
                        "通行·官媒科普": "people_health",
                        "通行·医院科普": "qzzyyy",
                        "官方·药典": "chp2020",
                        "通行·教材": "s1_dietetics",
                        "通行·教材(有冲突)": "s1_dietetics",
                    },
                }
            },
            "source_registry": {
                "satcm_terms": {"url": "https://a.example"},
                "shwsjkw": {"url": "https://b.example"},
                "people_health": {"url": "https://c.example"},
                "qzzyyy": {"url": "https://d.example"},
                "chp2020": {"url": "https://e.example"},
                "s1_dietetics": {"url": None},
            },
        }

    def _ev(tier: str, locator: str = "某页｜https://x.example", verbatim: str = "某句") -> dict:
        return {"tier": tier, "locator": locator, "verbatim": verbatim}

    def _src(entries: list, meta: dict | None = None) -> dict:
        return {"_meta": _meta() if meta is None else meta, "entries": entries}

    # 干净样本：四类问题一个都不该报（否则下面的负控制说明不了什么）
    clean = _src([
        {"id": "c1", "reference": {"tier": "通行·官媒科普"}, "evidence": [_ev("通行·官媒科普")]},
        {"id": "c2", "reference": {"tier": "官方·审核词条"}, "evidence": [_ev("官方·审核词条")]},
        {"id": "c3", "reference": {"tier": "官方·卫健科普"}, "evidence": [_ev("官方·卫健科普")]},
        {"id": "c4", "reference": {"tier": "通行·医院科普"}, "evidence": [_ev("通行·医院科普")]},
    ])
    a, b, c, d = web_source_gaps(clean)
    assert not (a or b or c or d), f"干净样本被误报：a={a} b={b} c={c} d={d}"

    # a) registry 条目缺 url
    meta = _meta()
    meta["source_registry"]["qzzyyy"] = {"url": None}
    a, _, _, _ = web_source_gaps(_src(
        [{"id": "x", "reference": {"tier": "通行·医院科普"}, "evidence": [_ev("通行·医院科普")]}],
        meta,
    ))
    assert any("qzzyyy" in x for x in a), f"registry 条目缺 url 没被抓出来：{a}"

    # a) 档名压根没登记进词表
    meta = _meta()
    meta["controlled_vocab"]["tier"]["取值"] = [
        t for t in meta["controlled_vocab"]["tier"]["取值"] if t != "通行·医院科普"
    ]
    a, _, _, _ = web_source_gaps(_src([], meta))
    assert any("未登记" in x for x in a), f"词表外档名没被抓出来：{a}"

    # b) locator 缺 URL / verbatim 为空
    _, b, _, _ = web_source_gaps(_src([
        {"id": "nourl", "reference": {"tier": "通行·官媒科普"},
         "evidence": [_ev("通行·官媒科普", locator="人民网说过")]},
        {"id": "noverb", "reference": {"tier": "官方·审核词条"},
         "evidence": [_ev("官方·审核词条", verbatim="   ")]},
    ]))
    assert any("nourl" in x for x in b), f"locator 缺 URL 没被抓出来：{b}"
    assert any("noverb" in x for x in b), f"verbatim 为空没被抓出来：{b}"

    # c) 网页档登记了却没人引用
    _, _, c, _ = web_source_gaps(_src([
        {"id": "only", "reference": {"tier": "通行·官媒科普"}, "evidence": [_ev("通行·官媒科普")]},
    ]))
    assert any("官方·审核词条" in x for x in c), f"死档没被抓出来：{c}"

    # d) 越级：reference 取网页档，evidence 里却有药典依据
    _, _, _, d = web_source_gaps(_src([
        {"id": "over", "reference": {"tier": "通行·官媒科普"},
         "evidence": [_ev("通行·官媒科普"), _ev("官方·药典")]},
    ]))
    assert any("over" in x for x in d), f"越级（有药典依据却拿科普当基准）没被抓出来：{d}"


# --- 组 2：§4 图例必须覆盖在用档位（B3 拍板点 F）-----------------------------
def test_priority_legend_covers_used_tiers(mod, sources) -> None:
    """§4 的图例必须覆盖**所有在用**的 `tier`（B3 首次新增 `tier` 才暴露这个坑）。

    图例原先写死在脚本里、且没有任何守卫：新增一个档而忘了补图例时，审核人在 §4.1 看到
    「官方·审核词条」、翻到图例却查不到 —— `_meta` 与产物**静默不一致**。

    断言图例行数 ≥7 是防「图例被清空 ⇒ gaps 恒为空」：本项目的老坑就是守卫在空集上恒真。
    """
    assert len(mod.PRIORITY_LEGEND) >= 7, (
        f"§4 图例只有 {len(mod.PRIORITY_LEGEND)} 行，疑似被清空（那会让 gaps 恒为空）"
    )
    gaps = mod.priority_legend_gaps(sources)
    assert not gaps, f"这些**在用**的档位在 §4 图例里查不到：{gaps}"


def test_priority_legend_gaps_negative_control(mod, sources) -> None:
    """负控制：拿掉覆盖某个**在用**档的那一行，gap 必须报出来。

    同时钉住「完整图例下必须为空」—— 否则上一条的「空」可能只是图例整体失效。
    """
    full = list(mod.PRIORITY_LEGEND)
    assert mod.priority_legend_gaps(sources, full) == [], "完整图例下不该有 gap"

    used = sorted({ev.get("tier") for _, ev in _evidence_rows(sources) if ev.get("tier")})
    assert used, "sources.json 里没有带 tier 的依据（样本被治理偷走了？）"
    target = used[0]
    trimmed = [row for row in full if target not in (row.get("tiers") or ())]
    assert len(trimmed) < len(full), f"没有图例行声明覆盖在用档 `{target}`（测试自身失效）"

    gaps = mod.priority_legend_gaps(sources, trimmed)
    assert target in gaps, f"拿掉覆盖 `{target}` 的图例行后没被报出来：{gaps}"



