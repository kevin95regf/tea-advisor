"""九种体质参考数据与文档生成器的回归测试。

守两类风险：
1. **来源与层次混淆** —— A 栏（国标特征转引）被写成「原文」、B 栏（饮食方向）被写成「国标」。
   GB/T 46939-2025 不含任何饮食建议，这个区分一旦丢掉，文档就开始骗人了。
2. **C 栏与项目数据漂移** —— 文档里写的调养原则和 core/data/constitution.json 对不上。

⚠️ 2026-09-17 说明：本文件原先断言「四型不在项目里」，那是 5 型时期的正确状态。
项目扩到 9 型后，这批断言按新状态更新（`PROJECT_IDS` 补四型、缺失数断言 0）。
**这是配合 5→9 的测试更新，不是修 bug** —— 断言本身没写错，是它编码的旧状态变了。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

CORE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = CORE_DIR.parent
SCRIPT_PATH = CORE_DIR / "scripts" / "build_constitution_doc.py"
REF_PATH = PROJECT_ROOT / "docs" / "constitution-9-types.json"
DOC_PATH = PROJECT_ROOT / "docs" / "constitution-9-types.md"
PROJECT_CONSTITUTIONS = CORE_DIR / "data" / "constitution.json"

# 国标给出的九型名录与顺序（来源：《中国中医药报》2026-01-26、北京中医药大学 2026-02-03）
EXPECTED_LABELS = [
    "平和质", "气虚质", "阳虚质", "阴虚质", "痰湿质",
    "湿热质", "血瘀质", "气郁质", "特禀质",
]

# 项目当前收录的 9 型及其 id（2026-09-17 由 5 型扩为 9 型，顺序同国标）
PROJECT_IDS = {
    "平和质": "balanced",
    "气虚质": "qi_deficiency",
    "阳虚质": "yang_deficiency",
    "阴虚质": "yin_deficiency",
    "痰湿质": "phlegm_damp",
    "湿热质": "damp_heat",
    "血瘀质": "blood_stasis",
    "气郁质": "qi_stagnation",
    "特禀质": "special_diathesis",
}

# 扩到 9 型后已无未收录体质。保留这个常量是因为文档渲染断言要用它的长度。
NOT_IN_PROJECT: list[str] = []


def _load_module():
    spec = importlib.util.spec_from_file_location("build_constitution_doc", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_constitution_doc"] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


@pytest.fixture(scope="module")
def mod():
    return _load_module()


@pytest.fixture(scope="module")
def ref():
    return json.loads(REF_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def project():
    raw = json.loads(PROJECT_CONSTITUTIONS.read_text(encoding="utf-8"))
    return {c["id"]: c for c in raw["constitutions"]}


# ------------------------------ 名录完整性 --------------------------------


def test_nine_constitutions_in_standard_order(ref):
    assert [c["label"] for c in ref["constitutions"]] == EXPECTED_LABELS


def test_project_coverage_matches_project_data(ref, project):
    for c in ref["constitutions"]:
        label = c["label"]
        assert c["id"], label
        if label in PROJECT_IDS:
            assert c["in_project"] is True, label
            assert c["id"] == PROJECT_IDS[label], label
            assert c["id"] in project, label
        else:
            assert c["in_project"] is False, label
            assert c["id"] not in project, label


def test_no_type_missing_from_project(ref):
    """扩到 9 型后，参考数据里不应再有「未收录」的体质。"""
    missing = [c["label"] for c in ref["constitutions"] if not c["in_project"]]
    assert missing == NOT_IN_PROJECT == []


def test_confirmed_ids_for_new_types(ref):
    """四个新体质的 id 已于 2026-09-17 确认。

    这条断言的价值在于**防 id 漂移**，与 in_project 无关：
    即使四型已收录，id 也不得改动（改 id 会让已写好的 herbs.json 标注全部失配）。
    """
    confirmed = {
        "阴虚质": "yin_deficiency",
        "血瘀质": "blood_stasis",
        "气郁质": "qi_stagnation",
        "特禀质": "special_diathesis",
    }
    by = {c["label"]: c for c in ref["constitutions"]}
    for label, cid in confirmed.items():
        assert by[label]["id"] == cid, label
        assert by[label]["in_project"] is True, label


def test_no_leftover_proposed_or_project_id_keys(ref):
    """迁移后不允许 project_id / proposed_id 残留。"""
    for c in ref["constitutions"]:
        assert "project_id" not in c, c["label"]
        assert "proposed_id" not in c, c["label"]


def test_id_matches_project_data_for_covered_types(ref, project):
    for c in ref["constitutions"]:
        if c["in_project"]:
            assert c["id"] in project
            assert project[c["id"]]["label"] == c["label"]


# --------------------------- 层次与来源的诚实性 ----------------------------


def test_every_claim_has_a_registered_source(ref):
    known = {s["key"] for s in ref["sources"]}
    known |= {s["key"] for s in ref["standard"]["sources"]}
    for c in ref["constitutions"]:
        for layer in ("features", "diet_direction"):
            for item in c[layer]:
                assert item["source"] in known, (c["label"], layer, item)
                assert item["text"].strip(), (c["label"], layer)


def test_all_features_and_diet_directions_present(ref):
    for c in ref["constitutions"]:
        assert c["features"], c["label"]
        assert c["diet_direction"], c["label"]


def test_source_urls_are_http(ref):
    for s in ref["sources"]:
        assert s["url"].startswith("http"), s["key"]
        assert s.get("kind"), s["key"]
        assert s.get("date"), s["key"]


def test_standard_metadata_is_complete(ref):
    std = ref["standard"]
    assert std["code"] == "GB/T 46939-2025"
    assert std["effective_at"] == "2026-04-01"
    assert std["published_at"] == "2025-12-31"
    assert std["status"] == "现行"
    assert len(std["key_revisions"]) == 3


def test_fulltext_status_admits_it_is_missing(ref):
    """正文取不到这件事必须写在数据里，不能悄悄当成原文。"""
    fs = ref["standard"]["fulltext_status"]
    assert fs["obtainable"] is False
    assert "未能获取" in fs["detail"]
    assert fs["how_to_fill_layer_a"]


def test_open_items_recorded(ref):
    ids = {i["id"] for i in ref["open_items"]}
    for expected in ("A_layer_not_verbatim", "diet_not_in_standard",
                     "four_types_missing_in_project", "ids_confirmed"):
        assert expected in ids


def test_read_this_first_states_the_three_separations(ref):
    text = " ".join(ref["_meta"]["read_this_first"])
    assert "转引" in text
    assert "不是国标内容" in text
    assert "constitution.json" in text


# -------------------------- C 栏防漂移（核心） -----------------------------


def test_c_column_matches_live_project_data(ref, project):
    """C 栏快照必须与 core/data/constitution.json 实时一致 —— 这是防漂移的关键。"""
    for c in ref["constitutions"]:
        if not c["in_project"]:
            assert c["project_principles"] is None, c["label"]
            continue
        snap = c["project_principles"]
        live = project[c["id"]]
        for field in ("one_line", "principles", "direction", "avoid"):
            assert snap[field] == live[field], f"{c['label']}.{field} 快照已过期"


def test_validate_reports_no_problems(mod, ref, project):
    assert mod.validate(ref, project) == []


def test_validate_catches_stale_snapshot(mod, ref, project):
    """快照过期时必须报出来，而不是静默渲染一份错文档。"""
    import copy

    broken = copy.deepcopy(ref)
    broken["constitutions"][0]["project_principles"]["one_line"] = "被改过了"
    problems = mod.validate(broken, project)
    assert any("快照" in p for p in problems), problems


def test_validate_catches_unknown_id(mod, ref, project):
    import copy

    broken = copy.deepcopy(ref)
    broken["constitutions"][0]["id"] = "no_such_id"
    problems = mod.validate(broken, project)
    assert any("不存在" in p for p in problems), problems


def test_validate_catches_inconsistent_in_project_flag(mod, ref, project):
    """标为未收录、但 id 已在 constitution.json 里 —— 迁移漏改的典型症状。"""
    import copy

    broken = copy.deepcopy(ref)
    broken["constitutions"][0]["in_project"] = False
    problems = mod.validate(broken, project)
    assert any("已在 constitution.json" in p for p in problems), problems


def test_validate_catches_unknown_source(mod, ref, project):
    import copy

    broken = copy.deepcopy(ref)
    broken["constitutions"][0]["features"][0]["source"] = "no_such_source"
    problems = mod.validate(broken, project)
    assert any("未登记" in p for p in problems), problems


def test_validate_catches_wrong_count(mod, ref, project):
    import copy

    broken = copy.deepcopy(ref)
    broken["constitutions"].pop()
    assert any("应为 9" in p for p in mod.validate(broken, project))


def test_check_mode_returns_zero(mod):
    assert mod.main(["--check"]) == 0


# ------------------------------ 渲染产物 ----------------------------------


@pytest.fixture(scope="module")
def doc_text():
    return DOC_PATH.read_text(encoding="utf-8")


def test_doc_has_a_section_per_constitution(doc_text):
    for label in EXPECTED_LABELS:
        assert f"### {label}" in doc_text, label


def test_doc_warns_that_layer_a_is_not_verbatim(doc_text):
    assert "非标准正文" in doc_text
    assert "标准正文未能获取" in doc_text
    assert "不得" not in doc_text or "请勿手工编辑" in doc_text


def test_doc_warns_that_layer_b_is_not_the_standard(doc_text):
    assert "非国标内容" in doc_text
    assert "不提供任何饮食或饮片建议" in doc_text


def test_doc_marks_no_type_as_uncovered(doc_text):
    """9 型全部收录后，文档里不应再出现「暂无（项目未收录此体质）」。

    渲染器靠 `in_project` 决定是否打印这句；若哪天有人把某型的 in_project 翻回假
    却没更新 C 栏快照，这里立刻会红。
    """
    assert doc_text.count("暂无（项目未收录此体质）") == len(NOT_IN_PROJECT) == 0


def test_doc_is_generated_and_says_so(doc_text):
    assert "请勿手工编辑" in doc_text
    assert "build_constitution_doc.py" in doc_text


def test_doc_is_lf_only(doc_text):
    assert "\r\n" not in doc_text


def test_render_is_deterministic(mod, ref, project):
    assert mod.render(ref, project) == mod.render(ref, project)
