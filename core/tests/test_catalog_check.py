"""食药物质目录数据与核对脚本的回归测试。

这些测试守的是「目录数据被改坏」和「脚本静默失配」两类风险：
目录文件里少一条、批次数量写错、或者某味饮片突然匹配不上，都应当立刻失败，
而不是安静地输出一份看起来正常的清单。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

CORE_DIR = Path(__file__).resolve().parent.parent
SCRIPT_PATH = CORE_DIR / "scripts" / "check_herb_catalog.py"
CATALOG_PATH = CORE_DIR / "data" / "food_medicine_catalog.json"
HERBS_PATH = CORE_DIR / "data" / "herbs.json"

# 批次数量是公告本身的事实，改动即意味着目录内容变了，必须显式确认
EXPECTED_BATCH_COUNTS = {"2002-51": 87, "2019-08": 6, "2023-09": 9, "2024-04": 4}
EXPECTED_TOTAL = 106


def _load_module():
    spec = importlib.util.spec_from_file_location("check_herb_catalog", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_herb_catalog"] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


@pytest.fixture(scope="module")
def mod():
    return _load_module()


@pytest.fixture(scope="module")
def catalog():
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def herbs():
    return json.loads(HERBS_PATH.read_text(encoding="utf-8"))["herbs"]


# --------------------------- 目录数据完整性 --------------------------------


def test_catalog_total_is_106(catalog):
    assert catalog["_meta"]["total"] == EXPECTED_TOTAL
    assert len(catalog["items"]) == EXPECTED_TOTAL


def test_catalog_batch_counts(catalog):
    counts = {b["id"]: b["count"] for b in catalog["batches"]}
    assert counts == EXPECTED_BATCH_COUNTS
    assert sum(counts.values()) == EXPECTED_TOTAL


def test_every_batch_keeps_verbatim_source(catalog):
    """每个批次都要保留公告原文串，否则无法与政府网页逐字核对。"""
    for batch in catalog["batches"]:
        assert batch["verbatim"].strip(), batch["id"]
        assert batch["url"].startswith("http"), batch["id"]


def test_batch_counts_match_verbatim(catalog, mod):
    """verbatim 里实际能数出来的条数必须等于声明的 count。"""
    for batch in catalog["batches"]:
        assert len(mod.split_items(batch["verbatim"])) == batch["count"], batch["id"]


def test_verbatim_parsing_keeps_parenthetical_items_intact(mod):
    """括号内的顿号不是分隔符 —— 这是本数据最容易出错的地方。"""
    items = mod.split_items("枣（大枣、酸枣、黑枣）、姜（生姜、干姜）、茯苓")
    assert items == ["枣（大枣、酸枣、黑枣）", "姜（生姜、干姜）", "茯苓"]


def test_no_duplicate_catalog_names(catalog):
    names = [i["name"] for i in catalog["items"]]
    assert len(names) == len(set(names))


def test_every_item_has_valid_batch(catalog):
    valid = {b["id"] for b in catalog["batches"]}
    for item in catalog["items"]:
        assert item["batch"] in valid, item


def test_qualifier_notes_present_for_qualifiers(catalog):
    """括号内容被判定为限定词时，必须写明理由，不能默默丢掉。"""
    by_full = {i["full"]: i for i in catalog["items"]}
    assert by_full["杏仁（甜、苦）"].get("qualifier_note")
    assert by_full["肉苁蓉（荒漠）"].get("qualifier_note")


def test_parenthetical_alternates_are_registered(catalog):
    by_full = {i["full"]: i for i in catalog["items"]}
    assert by_full["龙眼肉（桂圆）"]["alternates"] == ["桂圆"]
    assert set(by_full["枣（大枣、酸枣、黑枣）"]["alternates"]) == {"大枣", "酸枣", "黑枣"}
    assert set(by_full["姜（生姜、干姜）"]["alternates"]) == {"生姜", "干姜"}


# ------------------------- 已知的四味特殊情况 ------------------------------

# 这四味是清单 A/B/C 的边界样本，行为一旦漂移必须显式确认
KNOWN_STATUS = {
    "陈皮": "in",      # 同物异名 陈皮 -> 橘皮
    "红枣": "in",      # 俗称     红枣 -> 大枣（目录括号内并列名）
    "生姜": "in",      # 目录括号内并列名
    "玫瑰花": "not_in",
    "茉莉花": "not_in",
    "橘红": "review",  # 目录有「桔红」「橘皮」「化橘红」三条，脚本不替人判定
}


def test_known_edge_cases_status(mod, herbs, catalog):
    results = {r["herb"]: r["status"] for r in mod.check(herbs, catalog["items"])}
    for herb, expected in KNOWN_STATUS.items():
        assert results.get(herb) == expected, f"{herb} 状态漂移: {results.get(herb)} != {expected}"


def test_review_items_report_a_candidate(mod, herbs, catalog):
    """需人工判断的条目要把候选条目报出来，不能让人两手空空。"""
    results = {r["herb"]: r for r in mod.check(herbs, catalog["items"])}
    assert results["橘红"]["catalog_name"] == "桔红"


# ------------------------------ 脚本行为 ----------------------------------


def test_every_herb_gets_a_definite_status(mod, herbs, catalog):
    """34 味每一味都必须落到 in/not_in/review 之一，不允许「未知」。"""
    results = mod.check(herbs, catalog["items"])
    assert len(results) == len(herbs)
    for r in results:
        assert r["status"] in mod.STATUS_LABELS, r
        assert r["status_label"]
        assert r["note"]


def test_summary_matches_results(mod, herbs, catalog):
    results = mod.check(herbs, catalog["items"])
    summary = mod.summarise(results)
    assert summary["total"] == len(herbs)
    assert summary["in"] + summary["not_in"] + summary["review"] == len(herbs)


def test_checker_does_not_modify_data_files(mod, herbs, catalog):
    """脚本必须是只读的：跑完前后两个数据文件的字节数不变。"""
    before_catalog = CATALOG_PATH.read_bytes()
    before_herbs = HERBS_PATH.read_bytes()
    mod.check(herbs, catalog["items"])
    assert CATALOG_PATH.read_bytes() == before_catalog
    assert HERBS_PATH.read_bytes() == before_herbs


def test_status_beats_hit(mod, catalog):
    """「需人工判断」的条目即使能匹配上，也不能被降级成 in。"""
    herbs = [{"name": "橘红"}]
    assert mod.check(herbs, catalog["items"])[0]["status"] == "review"


def test_strict_mode_returns_1_when_work_remains(tmp_path, capsys):
    """--strict 在有「不在目录内」或「需人工判断」时必须返回 1，供 CI 使用。"""
    script_main = _load_module().main
    assert script_main(["--strict", "--only", "not_in"]) == 1


def test_missing_catalog_returns_2(tmp_path, capsys):
    script_main = _load_module().main
    assert script_main(["--catalog", str(tmp_path / "nope.json")]) == 2


def test_json_output_is_parseable(capsys, tmp_path):
    mod = _load_module()
    out = tmp_path / "r.json"
    assert mod.main(["--format", "json", "--out", str(out)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["summary"]["total"] == len(payload["results"])
    assert payload["catalog"]["total"] == EXPECTED_TOTAL
