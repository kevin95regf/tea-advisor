"""食物表 vs 饮片表边界（第 5 步）。

硬约束：
1. 推荐候选只来自 herbs.json（经 filter_by_constitution）；
2. 仅存在于食物表、不在饮片表的名字，不得出现在候选里；
3. docs 里的四气证据文件不被运行时加载。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.enums import Constitution
from app.domain.safety import MissingConstitutionDataError, filter_by_constitution, ready_constitutions

CORE = Path(__file__).resolve().parent.parent
ROOT = CORE.parent


def _foods() -> list[dict]:
    d = json.loads((CORE / "data" / "food_properties.json").read_text(encoding="utf-8"))
    return list(d["foods"]) + list(d["tea_drinks"]["items"])


def _herbs() -> list[dict]:
    return json.loads((CORE / "data" / "herbs.json").read_text(encoding="utf-8"))["herbs"]


def _herb_names_and_aliases() -> set[str]:
    out: set[str] = set()
    for h in _herbs():
        if h.get("name"):
            out.add(h["name"])
        for a in h.get("aliases") or []:
            if a:
                out.add(str(a))
        for k in h.get("keywords") or []:
            if k:
                out.add(str(k))
    return out


def _all_candidates() -> list[dict]:
    ready = set(ready_constitutions())
    items: list[dict] = []
    for c in Constitution:
        if c.value not in ready:
            continue
        try:
            items.extend(filter_by_constitution(c.value, limit=50))
        except MissingConstitutionDataError:
            continue
    assert items, "没有任何体质产出候选 —— 样本被偷走了"
    return items


def test_every_candidate_id_exists_in_herbs_json():
    herb_ids = {h["id"] for h in _herbs()}
    bad = [c for c in _all_candidates() if c.get("id") not in herb_ids]
    assert not bad, f"候选里出现了非 herbs.json 的 id：{bad[:5]}"


def test_food_only_names_never_appear_as_candidate_names():
    """仅食物侧有的名字（如薏米、红豆、菊花茶）不得作为候选饮片名。

    同名并存（山药）允许：那是饮片正名，不是「食物条目进了候选」。
    """
    herb_vocab = _herb_names_and_aliases()
    food_only = set()
    for f in _foods():
        name = f.get("name") or ""
        if name and name not in herb_vocab:
            food_only.add(name)
    assert food_only, "食物专用名集合为空 —— 判据失效"
    cand_names = {c.get("name") for c in _all_candidates()}
    leaked = sorted(food_only & cand_names)
    assert not leaked, f"食物专用名出现在推荐候选中：{leaked}"


def test_crosswalk_lists_required_pairs():
    path = ROOT / "docs" / "food-expansion" / "food-herb-crosswalk.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    pairs = {(e["food_id"], e["herb_id"]) for e in data["entries"]}
    required = {
        ("yimi", "yiyiren"),
        ("hongdou", "chixiaodou"),
        ("shanyao", "shanyao"),
        ("sangshen", "sangshen"),  # hold-back 食物 ↔ 饮片桑椹
    }
    missing = required - pairs
    assert not missing, f"对照表缺少必选重叠对：{missing}"
    sang = next(e for e in data["entries"] if e["food_id"] == "sangshen")
    assert sang["nature_agree"] is True
    assert sang["food_nature"] == "cold" and sang["herb_nature"] == "cold"
    assert sang["food_in_runtime"] is False


def test_runtime_loader_does_not_read_tcm_evidence():
    """抽查：core/app 与 ui 源码不得引用证据侧车文件名。"""
    needles = (
        "food-tcm-evidence",
        "food_tcm_evidence",
        "tcm_evidence",
        "food-herb-crosswalk",
    )
    roots = [CORE / "app", ROOT / "ui"]
    offenders: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for n in needles:
                if n in text:
                    offenders.append(f"{path.relative_to(ROOT)}:{n}")
    assert not offenders, f"运行时读了 docs 证据/对照：{offenders}"


def test_runtime_food_entries_have_at_most_17_field_order_keys():
    """运行时条目不得塞回 tcm_* / expansion_* 大字段。"""
    allowed_prefix_ok = {"id", "name", "aliases", "category", "nature", "flavors", "keywords",
                         "variant_nature", "note", "base_form",
                         "reviewed", "reviewed_by", "reviewed_at", "review_note", "review_status",
                         "food_group_code", "dg2022_layer"}
    forbidden_sub = ("tcm_", "expansion_", "classification_", "tcm_evidence")
    for e in _foods():
        keys = set(e)
        extra = keys - allowed_prefix_ok
        assert not extra, f"{e.get('id')} 多出字段 {extra}"
        blob = json.dumps(e, ensure_ascii=False)
        for bad in forbidden_sub:
            assert bad not in blob, f"{e.get('id')} 含禁止内容 {bad}"
