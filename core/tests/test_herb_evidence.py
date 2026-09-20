"""饮片侧「逐味公开依据」链的派生不变式与负控制。

守的是三类**静默**缺陷：

1. **登记表与事实源漂移。** 域 I 的逐味条目由 `build_herb_sources.py` 从
   `herb_nature_reference.json` 与 `herbs.json` 派生，所以「project 块与 herbs.json 现值一致」
   「verbatim 能逐字回到参照表」这两条本该自动成立 —— 但前提是**没人手工改过 JSON**。
   这两条就是钉住「有人手工改了」。
2. **来源与判定混用。** 域 II 只登记「哪条来源点名了哪味」，**不是**判定。
   一旦带 `field` 键，它就成了 `herbs.json` 的 `rulings`（软约束豁免登记）的重复账本，
   两处必然漂移。另外 `nhc-food-medicine-2021` 只证明合规身份，永不作体质依据。
3. **推荐了某味、引文里却没有它。** 这是这条链最难发现的错：输出表面完全正常。
   分叉批次用「逐位映射必须精确相等」挡它，本项目用「推荐里的每一味都要有依据」移植过来。

按项目成文纪律：**不写数据快照式断言**（`assert len(missing) == 3` 之类 —— 数据补齐后必红，
且分不清「数据坏了」还是「活儿干完了」），只用派生不变式 + 负控制；
每条关键检查都配一条**人造数据**的负控制，否则「真实数据上没报错」与「检查根本没跑」
长得一模一样。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from app.domain.enums import Constitution
from app.domain.models import AnalyzeRequest, BrewGuide, HerbInBlend, Recommendation
from app.domain.safety import herb_evidence
from app.services import orchestrator

CORE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = CORE_DIR / "app"
DATA_DIR = CORE_DIR / "data"
EVIDENCE_PATH = DATA_DIR / "herb_evidence_sources.json"
HERBS_PATH = DATA_DIR / "herbs.json"
REF_PATH = DATA_DIR / "herb_nature_reference.json"
ORCHESTRATOR_PATH = APP_DIR / "services" / "orchestrator.py"

# 只证明合规身份、不含四气也不含体质适配 —— 永不作体质依据
FORBIDDEN_SOURCE = "nhc-food-medicine-2021"

# `herbs.json` 里 rulings 用的字段名。域 II 出现它就意味着「来源登记」被写成了「判定登记」
RULING_FIELD_KEYS = ("field", "verdict", "cell")


# ============================================================
# 载入
# ============================================================
def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def evidence() -> dict:
    return _load(EVIDENCE_PATH)


@pytest.fixture(scope="module")
def herbs() -> list[dict]:
    return _load(HERBS_PATH)["herbs"]


@pytest.fixture(scope="module")
def reference() -> dict:
    return _load(REF_PATH)


# ============================================================
# 纯函数：正向测试与负控制共用同一份判定
# ============================================================
def _id_set_mismatch(prop_entries: list[dict], herbs: list[dict]) -> dict[str, list[str]]:
    """登记表的饮片 id 集合 vs herbs.json 的 id 集合，两边各自多出来的。"""
    listed = {e.get("id") for e in prop_entries}
    actual = {h["id"] for h in herbs}
    return {"missing_in_registry": sorted(actual - listed), "extra_in_registry": sorted(listed - actual)}


def _project_mismatches(prop_entries: list[dict], herbs: list[dict]) -> list[str]:
    """`project` 块与 herbs.json 现值不一致的饮片名。"""
    by_id = {h["id"]: h for h in herbs}
    out: list[str] = []
    for entry in prop_entries:
        herb = by_id.get(entry.get("id"))
        if herb is None:
            out.append(f"{entry.get('id')}（herbs.json 里没有这个 id）")
            continue
        project = entry.get("project") or {}
        for field in ("nature", "flavors", "meridians"):
            if list(project.get(field) or []) != list(herb.get(field) or []):
                out.append(f"{herb['name']}.{field}")
    return out


def _verbatim_mismatches(prop_entries: list[dict], reference: dict) -> list[str]:
    """每条 `evidence[0]` 必须逐字等于**同一味**在参照表里的药典原文。

    比对的是「同一味」而不是「整份参照表里有没有这个串」—— 后者会让
    「把陈皮的原文挂到茯苓头上」照样通过。
    """
    ref_by_name = {h["herb"]: h for h in reference["herbs"]}
    out: list[str] = []
    for entry in prop_entries:
        evidence_list = entry.get("evidence") or []
        if not evidence_list:
            continue
        rc = ref_by_name.get(entry.get("name"))
        if rc is None:
            out.append(f"{entry.get('name')}（参照表里没有这味）")
            continue
        ph = rc.get("pharmacopoeia") or {}
        ev = evidence_list[0]
        if ev.get("verbatim") != ph.get("xingwei_verbatim"):
            out.append(f"{entry['name']}.verbatim")
        if ev.get("matched_name") != ph.get("matched_title"):
            out.append(f"{entry['name']}.matched_name")
    return out


def _unregistered_herb_ids(entries: list[dict], herbs: list[dict]) -> list[str]:
    """域 II 挂在白名单外的饮片 id（`herb_id` 必须是 herbs.json 的 id）。"""
    valid = {h["id"] for h in herbs}
    return sorted({str(e.get("herb_id")) for e in entries} - valid)


def _dangling_source_ids(entries: list[dict], registry: dict) -> list[str]:
    """域 II 引用了未登记的来源（悬空来源会被运行时静默丢弃）。"""
    return sorted({str(e.get("source_id")) for e in entries} - set(registry))


def _duplicate_triples(entries: list[dict]) -> list[tuple[str, str, str]]:
    """重复登记的 `(体质, 饮片, 来源)` 三元组。

    **判据是三元组而不是二元组** —— 同一 (体质, 饮片) 挂在两条不同来源下是
    合法的「多来源互证」（矩阵本身就是这么写的：气虚质 × 山药 同时有国家标准委
    与临沂卫健委两条）。把它判成重复，等于把「两条独立来源相互印证」这个优点
    当成缺陷。真正要挡的是**同一格的同一来源被登记了两遍**。
    """
    seen: set[tuple[str, str, str]] = set()
    dup: list[tuple[str, str, str]] = []
    for e in entries:
        key = (str(e.get("constitution")), str(e.get("herb_id")), str(e.get("source_id")))
        if key in seen:
            dup.append(key)
        seen.add(key)
    return dup


def _forbidden_source_hits(entries: list[dict], forbidden: str) -> list[dict]:
    return [e for e in entries if e.get("source_id") == forbidden]


def _entries_with_ruling_keys(entries: list[dict]) -> list[dict]:
    return [e for e in entries if any(k in e for k in RULING_FIELD_KEYS)]


def _uncovered_herbs(recs: list[Recommendation], references: list[dict]) -> list[str]:
    """推荐里出现、却在 `references` 的 `supports` 里找不到的饮片。

    这正是「推荐了某味但引文里没有它」——最难从输出表面看出来的那一类错。
    """
    covered = {name for ref in references for name in (ref.get("supports") or [])}
    out: list[str] = []
    for rec in recs:
        for herb in rec.herbs:
            if herb.name not in covered and herb.name not in out:
                out.append(herb.name)
    return out


# ============================================================
# 0. 登记表自身可载入
# ============================================================
def test_evidence_file_is_loadable(evidence: dict) -> None:
    for key in ("_meta", "property_entries", "constitution_entries"):
        assert key in evidence, f"登记表缺少 {key}"
    assert evidence["_meta"].get("source_registry"), "来源注册表为空"


# ============================================================
# 1~3. 域 I：属性依据
# ============================================================
def test_property_entries_cover_every_herb(evidence: dict, herbs: list[dict]) -> None:
    """登记表的 id 集合必须与 herbs.json **精确相等**（不多不少）。

    派生不变式，不写死 34：加了第 35 味而登记表没跟上，这条自动变红。
    """
    mismatch = _id_set_mismatch(evidence["property_entries"], herbs)
    assert not mismatch["missing_in_registry"], (
        f"这些饮片在 herbs.json 里却没有属性依据条目：{mismatch['missing_in_registry']}。"
        "跑了 `python scripts/build_herb_sources.py --write` 吗？"
    )
    assert not mismatch["extra_in_registry"], (
        f"登记表里有 herbs.json 已不存在的饮片：{mismatch['extra_in_registry']}"
    )


def test_id_coverage_negative_control(evidence: dict, herbs: list[dict]) -> None:
    """砍掉一条必须被报出来 —— 否则上一条可能只是碰巧两边都为空。"""
    trimmed = [e for e in evidence["property_entries"] if e["id"] != herbs[0]["id"]]
    mismatch = _id_set_mismatch(trimmed, herbs)
    assert mismatch["missing_in_registry"] == [herbs[0]["id"]]


def test_property_block_matches_herbs_json_live_values(evidence: dict, herbs: list[dict]) -> None:
    """`project` 块必须是 herbs.json 的**现值**（挡住手工改 JSON 造成的漂移）。"""
    bad = _project_mismatches(evidence["property_entries"], herbs)
    assert not bad, f"这些字段与 herbs.json 现值不一致：{bad}"


def test_project_block_negative_control(evidence: dict, herbs: list[dict]) -> None:
    """把某味的四气改成药典值（项目值不同）必须被报出来。

    样本用**已知与药典不一致**的那 7 味之一，避免「改了但两边本来就一样」的假阴性。
    """
    inconsistent = [e for e in evidence["property_entries"] if e["status"] == "不一致"]
    assert inconsistent, "登记表里没有「不一致」条目，样本异常"
    sample = inconsistent[0]
    tampered = json.loads(json.dumps(evidence["property_entries"]))
    for entry in tampered:
        if entry["id"] == sample["id"]:
            entry["project"]["nature"] = "cold" if entry["project"]["nature"] != "cold" else "hot"
    assert _project_mismatches(tampered, herbs), "改了 project 却没被报出来"


def test_property_verbatim_traces_back_to_reference(evidence: dict, reference: dict) -> None:
    """每条有来源的 `evidence[0]` 必须逐字来自参照表的**同一味**。"""
    bad = _verbatim_mismatches(evidence["property_entries"], reference)
    assert not bad, f"这些引用无法回到 herb_nature_reference.json：{bad}"


def test_verbatim_trace_negative_control(evidence: dict, reference: dict) -> None:
    """把某一味的药典原文换成别一味的，必须被报出来（只查「串在不在全表里」会放过它）。"""
    ref_by_name = {h["herb"]: h for h in reference["herbs"]}
    donor = next(
        h for h in reference["herbs"] if (h.get("pharmacopoeia") or {}).get("xingwei_verbatim")
    )
    tampered = json.loads(json.dumps(evidence["property_entries"]))
    target = next(e for e in tampered if e["evidence"])
    if target["name"] == donor["herb"]:
        target = next(e for e in tampered if e["evidence"] and e["name"] != donor["herb"])
    target["evidence"][0]["verbatim"] = ref_by_name[donor["herb"]]["pharmacopoeia"][
        "xingwei_verbatim"
    ]
    assert _verbatim_mismatches(tampered, reference), "串换了却没被报出来"


# ============================================================
# 4~8. 域 II：体质适配依据
# ============================================================
def test_constitution_herb_ids_are_whitelisted(evidence: dict, herbs: list[dict]) -> None:
    bad = _unregistered_herb_ids(evidence["constitution_entries"], herbs)
    assert not bad, f"域 II 挂了白名单外的饮片 id：{bad}"


def test_herb_id_negative_control(evidence: dict, herbs: list[dict]) -> None:
    tampered = json.loads(json.dumps(evidence["constitution_entries"]))
    tampered.append({**tampered[0], "herb_id": "buzai-bailist"})
    assert _unregistered_herb_ids(tampered, herbs) == ["buzai-bailist"]


def test_constitution_sources_are_registered(evidence: dict) -> None:
    registry = evidence["_meta"]["source_registry"]
    bad = _dangling_source_ids(evidence["constitution_entries"], registry)
    assert not bad, f"域 II 引用了未登记的来源：{bad}"


def test_dangling_source_negative_control(evidence: dict) -> None:
    registry = evidence["_meta"]["source_registry"]
    tampered = json.loads(json.dumps(evidence["constitution_entries"]))
    tampered.append({**tampered[0], "source_id": "kxyj-mouwang"})
    assert _dangling_source_ids(tampered, registry) == ["kxyj-mouwang"]


def test_constitution_triples_are_unique(evidence: dict) -> None:
    """`(体质, 饮片, 来源)` 不得重复登记。"""
    dup = _duplicate_triples(evidence["constitution_entries"])
    assert not dup, f"同一格的同一来源被登记多次：{dup}"


def test_duplicate_triple_negative_control(evidence: dict) -> None:
    entries = evidence["constitution_entries"]
    assert entries, "样本不足"
    tampered = entries + [dict(entries[0])]
    assert _duplicate_triples(tampered) == [
        (str(entries[0]["constitution"]), str(entries[0]["herb_id"]), str(entries[0]["source_id"]))
    ]


def test_same_pair_may_have_two_sources(evidence: dict) -> None:
    """同一 (体质, 饮片) 允许有**多条来源**，且 `herb_evidence` 要全部给出。

    这条是上一条的边界说明：判据用三元组，正是为了不误伤「两条独立来源互证」。
    数据里确实存在这种格子（矩阵自身就给了两条），所以用例从真实数据里取，
    取不到就跳过并提示 —— 而不是凭空造一个假样本。
    """
    counts: dict[tuple[str, str], int] = {}
    for e in evidence["constitution_entries"]:
        key = (str(e["constitution"]), str(e["herb_id"]))
        counts[key] = counts.get(key, 0) + 1
    multi = [k for k, n in counts.items() if n > 1]
    if not multi:
        pytest.skip("当前数据里没有「同一格两条来源」的样本")

    constitution, herb_id = multi[0]
    herb_name = next(
        e["herb_name"] for e in evidence["constitution_entries"]
        if e["constitution"] == constitution and e["herb_id"] == herb_id
    )
    sources = {r["id"] for r in herb_evidence({herb_name}, constitution)}
    expected = {
        e["source_id"] for e in evidence["constitution_entries"]
        if e["constitution"] == constitution and e["herb_id"] == herb_id
    }
    assert expected <= sources, f"{herb_name}×{constitution} 的来源没全给出：缺 {expected - sources}"


def test_nhc_source_is_never_constitution_evidence(evidence: dict) -> None:
    """`nhc-food-medicine-2021` 只证明合规身份，**永不作体质依据**（铁律守卫）。

    它在 `source_registry` 里登记在册（要说明「为什么不能用」），但
    `constitution_entries` 引用次数必须为 0。
    """
    assert FORBIDDEN_SOURCE in evidence["_meta"]["source_registry"], (
        "该来源应在注册表里登记在册（并写明「永不作体质依据」）"
    )
    hits = _forbidden_source_hits(evidence["constitution_entries"], FORBIDDEN_SOURCE)
    assert not hits, f"nhc 目录被当成体质依据用了：{hits}"


def test_forbidden_source_negative_control(evidence: dict) -> None:
    tampered = json.loads(json.dumps(evidence["constitution_entries"]))
    tampered.append({**tampered[0], "source_id": FORBIDDEN_SOURCE})
    assert _forbidden_source_hits(tampered, FORBIDDEN_SOURCE), "拿 nhc 当依据却没被报出来"


def test_constitution_entries_carry_no_ruling_keys(evidence: dict) -> None:
    """域 II 是**来源登记**，不是判定登记 —— 带 `field` 就成了 rulings 的第二本账。

    两本账必然漂移，且方向总是「测试放过、数据漏了」。
    """
    bad = _entries_with_ruling_keys(evidence["constitution_entries"])
    assert not bad, f"这些条目带了判定用的键：{[sorted(b) for b in bad][:3]}"


def test_ruling_keys_negative_control(evidence: dict) -> None:
    tampered = json.loads(json.dumps(evidence["constitution_entries"]))
    tampered[0]["field"] = "suitable_constitutions"
    assert _entries_with_ruling_keys(tampered), "带了 field 键却没被报出来"


# ============================================================
# 9~12. `herb_evidence()` 的行为
# ============================================================
def test_only_requested_herbs_are_supported() -> None:
    """只返回命中本次原料的来源，且 `supports` 只含本次点名的味。"""
    refs = herb_evidence({"茯苓"}, "balanced")
    assert refs, "茯苓应有属性依据"
    by_id = {r["id"]: r for r in refs}
    assert "chp2020" in by_id
    assert by_id["chp2020"]["supports"] == ["茯苓"]
    for r in refs:
        assert r["supports"] == ["茯苓"], f"{r['id']} 的 supports 不该含别的味"


def test_constitution_sources_need_a_constitution() -> None:
    """体质依据**必须**与当前体质对应，不能把「这味适合别人」当成「适合你」。

    茯苓是矩阵 14 味之一，但它那一格属于**湿热质**而不是平和质：
    所以平和质只拿得到属性依据，湿热质才多出 `linyi-wjw-2017`。
    这条同时钉住「体质级概述被当成单味依据」——若实现把整个注册表倒出来，
    supports 里就会出现本次没用的味。
    """
    assert [r["id"] for r in herb_evidence({"茯苓"}, "balanced")] == ["chp2020"]
    assert [r["id"] for r in herb_evidence({"茯苓"}, None)] == ["chp2020"]

    damp_heat_ids = [r["id"] for r in herb_evidence({"茯苓"}, "damp_heat")]
    assert "linyi-wjw-2017" in damp_heat_ids, f"湿热质的体质依据没接上：{damp_heat_ids}"


def test_multi_herb_same_source_is_merged() -> None:
    """同一来源命中多味时合并成一条，`supports` 累加。"""
    refs = herb_evidence({"山药", "红枣"}, "qi_deficiency")
    ids = [r["id"] for r in refs]
    assert len(ids) == len(set(ids)), f"同一来源出现了多次：{ids}"

    by_id = {r["id"]: r for r in refs}
    for sid in ("sac-2026", "linyi-wjw-2017"):
        assert sid in by_id, f"{sid} 应同时支持山药与红枣"
        assert set(by_id[sid]["supports"]) == {"山药", "红枣"}


def test_empty_or_unknown_input_returns_nothing() -> None:
    assert herb_evidence(set(), "balanced") == []
    assert herb_evidence({"完全不存在的饮片"}, "balanced") == []


def test_herb_without_property_source_returns_nothing() -> None:
    """茉莉花药典未收载、也不在矩阵 14 味里 —— 如实返回空，不编一条依据出来。"""
    assert herb_evidence({"茉莉花"}, "balanced") == []


def test_missing_registry_degrades_quietly() -> None:
    """登记表缺文件时返回空列表而不是抛异常（依据链是增强项，不该让请求 500）。"""
    assert herb_evidence({"茯苓"}, "balanced", data={}) == []


# ============================================================
# 13. 端到端：推荐里的每一味都必须有依据
# ============================================================
def _fake_parsed():
    from app.domain.models import ParsedFood, ParsedMeal

    return ParsedMeal(
        foods=[ParsedFood(name="山药粥", amount_desc="一碗")],
        confidence=0.9,
        summary="早餐喝了山药粥",
    )


def _fake_recs(stub_herbs: tuple[str, ...] = ("山药", "红枣")):
    rec = Recommendation(
        title="山药红枣健脾饮",
        herbs=[HerbInBlend(name=n, amount_g=6) for n in stub_herbs],
        brew=BrewGuide(),
        fit_reason="测试用",
        score=0.8,
    )
    return [rec], "测试说明", 1


@pytest.fixture
def stub_agents(monkeypatch: pytest.MonkeyPatch):
    """照 test_key_handling.stub_agents 的形状把两个 Agent 换成离线桩。"""
    from app.config import get_settings

    monkeypatch.setattr(orchestrator, "parse_diet", lambda *a, **kw: (_fake_parsed(), 1, "sid"))
    monkeypatch.setattr(orchestrator, "agent2_recommend", lambda *a, **kw: _fake_recs())
    monkeypatch.setattr(get_settings(), "backend", "direct")
    return get_settings()


def test_end_to_end_every_recommended_herb_has_a_reference(stub_agents) -> None:
    """走完整 `analyze`：推荐里的每一味都要在 `basis.references` 里找到依据。

    这是分叉批次那条「逐位映射必须精确相等」的移植，**挡的正是最难发现的错**：
    推荐了某味、引文里却没有它 —— 输出表面完全正常。
    """
    resp = orchestrator.analyze(
        AnalyzeRequest(text="早餐喝了山药粥", constitution_override=Constitution.QI_DEFICIENCY),
        api_key="sk-SENTINEL-DO-NOT-LEAK",
    )
    assert resp.recommendations, "桩应给出推荐"
    refs = [r.model_dump() for r in resp.basis.references]
    assert refs, "正常路径必须携带依据"
    assert _uncovered_herbs(resp.recommendations, refs) == []


def test_end_to_end_carries_both_domains(stub_agents) -> None:
    """端到端要同时带上域 I（药典）与域 II（气虚质来源）。"""
    resp = orchestrator.analyze(
        AnalyzeRequest(text="早餐喝了山药粥", constitution_override=Constitution.QI_DEFICIENCY),
        api_key="sk-SENTINEL-DO-NOT-LEAK",
    )
    ids = {r.id for r in resp.basis.references}
    assert "chp2020" in ids, "缺属性依据（域 I）"
    assert ids & {"sac-2026", "linyi-wjw-2017"}, f"缺体质依据（域 II）：{ids}"


def test_uncovered_herb_negative_control() -> None:
    """推荐里带一味没依据的饮片，必须被报出来。

    用**人造数据**而不是「真实数据里本来就没有的那一味」：后者会随数据补齐而失效，
    而且分不清「检查生效了」还是「这味本来就无依据」。
    """
    recs, _, _ = _fake_recs(("山药", "甘草"))
    refs = herb_evidence({"山药"}, "qi_deficiency")  # 刻意不含甘草
    assert _uncovered_herbs(recs, refs) == ["甘草"]


# ============================================================
# 14. 源码守卫：统一构造点 + 死代码不许复活
# ============================================================
def _basis_call_lines(path: Path) -> list[int]:
    """用 AST 数真实调用点，**不**数源码里的字符串 —— 文档字符串与注释里的
    ``Basis(...)`` 例子会让朴素 grep 计数虚高（那正是「断言数量而不是断言位置」的老坑）。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Basis"
    ]


def _functions_named(name: str, root: Path | None = None) -> list[str]:
    """`root` 下所有叫这个名字的函数（模块级或方法）。默认扫 `core/app/`。"""
    base = root or APP_DIR
    found: list[str] = []
    for path in sorted(base.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                rel = path.relative_to(base) if root is None else path.name
                found.append(f"{rel}:{node.lineno}")
    return found


def test_basis_is_constructed_in_exactly_one_place() -> None:
    """整个应用里 `Basis(...)` 只能有 1 处，且必须在 `_build_basis` 内。

    「真实构造点」与「唯一构造点」合一，新增第四处返回路径就不可能漏掉 `references`。
    """
    outside = {
        path.relative_to(APP_DIR).as_posix(): found
        for path in sorted(APP_DIR.rglob("*.py"))
        if path != ORCHESTRATOR_PATH and (found := _basis_call_lines(path))
    }
    assert not outside, f"orchestrator._build_basis 之外出现了 Basis(...)：{outside}"

    lines = _basis_call_lines(ORCHESTRATOR_PATH)
    assert len(lines) == 1, (
        f"orchestrator.py 里 Basis(...) 有 {len(lines)} 处（第 {lines} 行）—— "
        "必须全部经 `_build_basis`，否则新增的构造点会静默漏掉 references"
    )

    tree = ast.parse(ORCHESTRATOR_PATH.read_text(encoding="utf-8"))
    owner = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_build_basis"
    )
    assert owner.lineno <= lines[0] <= (owner.end_lineno or owner.lineno), (
        f"第 {lines[0]} 行的 Basis(...) 不在 `_build_basis` 内"
    )


def test_matcher_build_basis_stays_deleted() -> None:
    """`core/app/` 全文不许再有 `def build_basis`。

    它曾是一份**没有任何调用点**的同名实现：改它等于没改，而输出表面完全看不出来。
    真正构造 `Basis` 的地方只有 `orchestrator._build_basis`。
    """
    found = _functions_named("build_basis")
    assert not found, f"又出现了 build_basis（没人调用的同名实现会误导后续改动）：{found}"


def test_source_guard_functions_can_detect_regressions() -> None:
    """负控制：守卫函数本身要能发现「多了一处构造点 / 多了一个同名函数」。

    直接对合成的源码文本跑同一套 AST 逻辑 —— 不这样测，若解析写错导致
    `_basis_call_lines` 恒返回 `[1]`，上面两条会永远变绿。
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "fake.py"
        p.write_text(
            "def a():\n    return Basis(x=1)\n\n\ndef build_basis():\n    return None\n",
            encoding="utf-8",
        )
        assert len(_basis_call_lines(p)) == 1
        assert _functions_named("build_basis", Path(tmp)) == ["fake.py:5"], "同名函数没被扫出来"
        p.write_text("Basis(a=1)\nBasis(b=2)\n", encoding="utf-8")
        assert len(_basis_call_lines(p)) == 2, "两处调用点必须数出 2"

    assert _functions_named("build_basis") == [], "真实代码里不该有 build_basis"


# ============================================================
# 15. 幂等：磁盘内容必须等于「从事实源重新派生」的结果
# ============================================================
def test_disk_content_equals_fresh_derivation(evidence: dict, herbs: list[dict],
                                               reference: dict) -> None:
    """等价于把 `build_herb_sources.py --check` 接进 CI。

    手工改过 JSON 或渲染产物都会在这里变红 —— 事实源只有一个，
    人读登记表与 JSON 都不许被手改。
    """
    import scripts.build_herb_sources as tool

    rebuilt = tool.rebuild(json.loads(json.dumps(evidence)), reference, herbs)
    assert rebuilt["property_entries"] == evidence["property_entries"], (
        "登记表的域 I 与重新派生结果不一致 —— 跑了 `--write` 吗？"
    )
    assert rebuilt["_meta"]["counts"] == evidence["_meta"]["counts"], "_meta.counts 过期"

    md_path = CORE_DIR.parent / "docs" / "herb-evidence-sources.md"
    assert md_path.read_text(encoding="utf-8") == tool.render_md(rebuilt), (
        "docs/herb-evidence-sources.md 与渲染结果不一致（它是生成物，请勿手工编辑）"
    )
