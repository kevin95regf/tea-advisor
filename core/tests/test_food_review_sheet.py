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
    section = text.split("### 4.4", 1)[1].split("\n## ", 1)[0]
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


