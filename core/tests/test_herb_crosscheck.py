"""饮片性味归经核对数据与文档生成器的回归测试。

守两类风险：
1. **项目侧快照漂移** —— 改了 herbs.json 却没重建参考数据，文档就会显示错误的「项目当前值」。
2. **把「不一致」悄悄说成「一致」** —— 这是本文件存在的全部意义，一旦失效就白做了。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

CORE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = CORE_DIR.parent
SCRIPT_PATH = CORE_DIR / "scripts" / "build_herb_crosscheck.py"
REF_PATH = CORE_DIR / "data" / "herb_nature_reference.json"
HERBS_PATH = CORE_DIR / "data" / "herbs.json"
DOC_PATH = PROJECT_ROOT / "docs" / "herb-nature-crosscheck.md"

# 当前已知的不一致项。这份清单变化时必须显式确认 —— 要么是项目改了数据，
# 要么是药典检索结果变了，两种都值得看一眼。
EXPECTED_INCONSISTENT = ["红枣", "荷叶", "桑椹", "百合", "淡竹叶", "白扁豆", "佛手"]
EXPECTED_NOT_IN_PHARMACOPOEIA = ["茉莉花"]


def _load_module():
    spec = importlib.util.spec_from_file_location("build_herb_crosscheck", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_herb_crosscheck"] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


@pytest.fixture(scope="module")
def mod():
    return _load_module()


@pytest.fixture(scope="module")
def ref():
    return json.loads(REF_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def herbs():
    return json.loads(HERBS_PATH.read_text(encoding="utf-8"))["herbs"]


@pytest.fixture(scope="module")
def doc_text():
    return DOC_PATH.read_text(encoding="utf-8")


# ------------------------------ 数据完整性 --------------------------------


def test_reference_covers_every_herb(ref, herbs):
    assert len(ref["herbs"]) == len(herbs)
    assert {r["herb"] for r in ref["herbs"]} == {h["name"] for h in herbs}


def test_validate_reports_no_problems(mod, ref, herbs):
    assert mod.validate(ref, herbs) == []


def test_check_mode_returns_zero(mod):
    assert mod.main(["--check"]) == 0


def test_status_values_are_known(ref):
    for r in ref["herbs"]:
        assert r["status"] in {"一致", "不一致", "未收载"}, r["herb"]


def test_every_covered_herb_has_verbatim_source(ref):
    """一致与否不重要，重要的是每条都能追到药典原文。"""
    for r in ref["herbs"]:
        if r["status"] == "未收载":
            continue
        ph = r["pharmacopoeia"]
        assert ph["xingwei_verbatim"], r["herb"]
        assert "归" in ph["xingwei_verbatim"], r["herb"]
        assert isinstance(ph["page"], int) and ph["page"] > 0, r["herb"]
        assert ph["url"].startswith("https://ydz.chp.org.cn/"), r["herb"]


def test_book_is_pharmacopoeia_2020_part1(ref):
    for r in ref["herbs"]:
        if r["status"] == "未收载":
            continue
        assert "2020" in ref["_meta"]["source"]["book"]
        assert ref["_meta"]["source"]["book"] == "中华人民共和国药典：2020年版．一部"


# -------------------- 结论不能被悄悄改写（核心） ---------------------------


def test_known_inconsistencies_are_still_flagged(ref):
    got = [r["herb"] for r in ref["herbs"] if r["status"] == "不一致"]
    assert sorted(got) == sorted(EXPECTED_INCONSISTENT), got


def test_known_missing_herb_still_missing(ref):
    got = [r["herb"] for r in ref["herbs"] if r["status"] == "未收载"]
    assert got == EXPECTED_NOT_IN_PHARMACOPOEIA


def test_inconsistent_items_explain_themselves(ref):
    for r in ref["herbs"]:
        if r["status"] != "不一致":
            continue
        assert r["differences"], r["herb"]
        assert any(d.startswith("**") for d in r["differences"]), r["herb"]
        assert not (r["nature_match"] and r["flavors_match"] and r["meridians_match"]), r["herb"]


def test_consistent_items_have_no_substantive_difference(ref):
    """标为一致的条目不允许出现「项目多/缺」这类实质差异。"""
    for r in ref["herbs"]:
        if r["status"] != "一致":
            continue
        for d in r["differences"]:
            assert not d.startswith("**"), f"{r['herb']}：标为一致却有实质差异 {d}"


def test_match_flags_are_consistent_with_status(ref):
    for r in ref["herbs"]:
        if r["status"] == "未收载":
            assert r["nature_match"] is None
            continue
        expected = bool(r["nature_match"] and r["flavors_match"] and r["meridians_match"])
        assert expected == (r["status"] == "一致"), r["herb"]


def test_known_specific_discrepancies(ref):
    """把几个具体差异钉死，防止映射规则被改坏后静默变成「一致」。"""
    by = {r["herb"]: r for r in ref["herbs"]}
    assert by["桑椹"]["pharmacopoeia"]["nature_word"] == "寒"
    assert by["桑椹"]["project"]["nature"] == "cool"
    assert by["百合"]["pharmacopoeia"]["nature_word"] == "寒"
    assert by["淡竹叶"]["pharmacopoeia"]["nature_word"] == "寒"
    assert by["白扁豆"]["pharmacopoeia"]["nature_word"] == "微温"
    assert by["白扁豆"]["pharmacopoeia"]["nature_mapped"] == "warm"
    assert "酸" not in by["佛手"]["project"]["flavors_cn"]
    assert "酸" in by["佛手"]["pharmacopoeia"]["flavors_cn"]


def test_micro_nature_downgrade_rule(ref):
    """微寒→凉、微温→温的降档约定必须生效，否则菊花这类会全变成不一致。"""
    by = {r["herb"]: r for r in ref["herbs"]}
    assert by["菊花"]["pharmacopoeia"]["nature_word"] == "微寒"
    assert by["菊花"]["pharmacopoeia"]["nature_mapped"] == "cool"
    assert by["菊花"]["nature_match"] is True
    assert by["山楂"]["pharmacopoeia"]["nature_word"] == "微温"
    assert by["山楂"]["pharmacopoeia"]["nature_mapped"] == "warm"
    assert by["山楂"]["nature_match"] is True


# --------------------------- 快照防漂移（核心） ----------------------------


def test_project_snapshot_matches_live_data(ref, herbs):
    live = {h["name"]: h for h in herbs}
    for r in ref["herbs"]:
        h = live[r["herb"]]
        for field in ("nature", "flavors", "meridians"):
            assert r["project"][field] == h[field], f"{r['herb']}.{field} 快照已过期"


def test_validate_catches_stale_project_snapshot(mod, ref, herbs):
    import copy

    broken = copy.deepcopy(ref)
    broken["herbs"][0]["project"]["nature"] = "hot"
    problems = mod.validate(broken, herbs)
    assert any("快照已过期" in p for p in problems), problems


def test_meta_title_count_is_derived(mod, ref):
    """`_meta.title` 的味数是**派生**的，不是手写的。

    历史坑：`--refresh` 保留旧 `_meta`，靠手改 title 就会漏 —— 漏一次就是
    「文档说 35 味、数据是 38 味」。（2026-09-20，批二随批落地。）
    """
    expected = mod.TITLE_TEMPLATE.format(n=len(ref["herbs"]))
    assert ref["_meta"]["title"] == expected, (
        f"title 应为派生值 {expected!r}，实为 {ref['_meta']['title']!r} —— "
        "重跑 `python scripts/build_herb_crosscheck.py --refresh` 即可修复"
    )


def test_validate_catches_stale_meta_title(mod, ref, herbs):
    """负控制：把 title 改回旧的味数，`validate()` 必须报出来。"""
    import copy

    broken = copy.deepcopy(ref)
    broken["_meta"]["title"] = "35 味饮片性味归经核对参考数据（《中国药典》2020 年版一部）"
    problems = mod.validate(broken, herbs)
    assert any("_meta.title" in p for p in problems), problems


def test_validate_catches_missing_herb(mod, ref, herbs):
    import copy

    broken = copy.deepcopy(ref)
    broken["herbs"].pop()
    problems = mod.validate(broken, herbs)
    assert any("缺少饮片" in p for p in problems), problems


def test_validate_catches_unexplained_inconsistency(mod, ref, herbs):
    import copy

    broken = copy.deepcopy(ref)
    for r in broken["herbs"]:
        if r["status"] == "不一致":
            r["differences"] = []
            break
    problems = mod.validate(broken, herbs)
    assert any("没写差异原因" in p for p in problems), problems


# ------------------------ 只读性（不许动项目数据） -------------------------


def test_does_not_modify_project_data(mod, ref, herbs):
    before = HERBS_PATH.read_bytes()
    assert mod.main(["--check"]) == 0
    mod.validate(ref, herbs)
    mod.render(ref)
    assert HERBS_PATH.read_bytes() == before


def test_doc_says_it_does_not_change_data(doc_text):
    assert "只报告差异" in doc_text
    assert "不修改任何数据" in doc_text


# ------------------------------ 渲染产物 ----------------------------------


def test_doc_has_all_rows(doc_text, herbs):
    table = doc_text.split("## 4. 全部对照表")[1].split("### 4.1")[0]
    rows = [l for l in table.splitlines() if l.startswith("|") and "---" not in l]
    assert len(rows) == 1 + len(herbs), f"表头 1 行 + {len(herbs)} 味，实际 {len(rows)}"


def test_doc_lists_every_inconsistency(doc_text):
    section = doc_text.split("## 3. 不一致清单")[1].split("## 4.")[0]
    for name in EXPECTED_INCONSISTENT:
        assert f"### {name}" in section, name


def test_doc_documents_mapping_rules(doc_text):
    assert "微寒" in doc_text and "微温" in doc_text
    assert "我方约定" in doc_text


def test_doc_explains_why_zhonghua_bencao_is_empty(doc_text):
    assert "《中华本草》为什么没有数据" in doc_text
    assert "403" in doc_text
    assert "待确认" in doc_text


def test_doc_notes_effects_wordings_are_intentional(doc_text):
    """项目 effects 不照抄药典功能与主治是刻意的合规要求，必须写明。"""
    assert "养生类措辞" in doc_text
    assert "不是笔误" in doc_text


def test_doc_is_generated_and_lf(doc_text):
    assert "请勿手工编辑" in doc_text
    assert "build_herb_crosscheck.py" in doc_text
    assert "\r\n" not in doc_text


def test_render_is_deterministic(mod, ref):
    assert mod.render(ref) == mod.render(ref)
