"""`docs/food-properties-sources.json` 的映射一致性守卫 —— E5。

背景
----
`how` 受控词表里有 10 个取值，但此前**只有两类**有守卫：
`制品·原料继承`（`test_product_inheritance_points_at_a_real_herb`）与
`制品·原料继承（语料原料）`（`test_corpus_inheritance_*`）。另两类
——**`同条目·品种方向描述`（2 处）**与**`等价名（通称差异）`（3 处）**——一条守卫都没有。
按「有 `how` 就该有守卫」的口径，这是 E5。

⚠️ 一条**实测纠正过的判据**（写之前先验过，见 `core/var/probe_e5_rules.py`）
----------------------------------------------------------------------------
`nature_match` 比的**不是**「条内任一条 `evidence` 的四气」，而是 **`reference` 那一条**。
反例：`fuzhu` 有 3 条 evidence，其中一条的 `qi_mapped` 恰好等于项目值，
但 `nature_match=False` —— 因为它选定的 `reference`（人民网那条，`cool`）不等。
⇒ 判据是 `nature_match == (reference.qi_mapped == project.nature)`。按「任一条」写会**误判 1 条**。

另一条坑：`reference` 是 `evidence` 的**精简写法**（`locator` 更短，如 `xianggu` 去掉
「；纲目 23455」），所以**不能**要求它逐字 ∈ evidence —— 那样会误报。

「先验实测」的结果（47 条映射获采纳）：以下五条规则**全部 0 违规**，
且各含实质样本（不一致 13 条／品种方向 1 组／通称差异 3 处）⇒ 不是恒真。
"""

from __future__ import annotations

import copy
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Sequence

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SOURCES = ROOT / "docs/food-properties-sources.json"

# `nature_match` 只对**映射获采纳**的条目有意义：未获采纳的（status 为「无源可引…」
# 或「仅身份，无四气可比」）压根没有可比的四气，字段缺失是**刻意**的。
VARIETY_HOW = "同条目·品种方向描述"
SYNONYM_HOW = "等价名（通称差异）"


def _sources() -> dict[str, Any]:
    """**单一入口**：所有断言都从这里取输入。

    变异检验要顶替的就是它 —— 若各断言各自读盘，变异改的是副本、断言读的是原文，
    结果会「显示绿」（本项目踩过的「同一份输入只能有一个入口」）。
    """
    return json.loads(SOURCES.read_text(encoding="utf-8"))


def _entries(data: dict[str, Any] | None = None) -> list[dict]:
    return list((data if data is not None else _sources()).get("entries") or [])


def _vocab(data: dict[str, Any] | None = None) -> set[str]:
    d = data if data is not None else _sources()
    how = ((d.get("_meta") or {}).get("controlled_vocab") or {}).get("how") or {}
    return {str(x) for x in (how.get("取值") or [])}


def _accepted(entries: Sequence[dict]) -> list[dict]:
    """映射获采纳的条目（`nature_match` / `delta` 只在这批上有意义）。"""
    return [e for e in entries if (e.get("mapping_review") or {}).get("accepted") is True]


def _project_nature(entry: dict) -> Any:
    return (entry.get("project") or {}).get("nature")


def _reference_qi(entry: dict) -> Any:
    return (entry.get("reference") or {}).get("qi_mapped")


# ============================================================
# 纯函数判据（正向测试与负控制共用同一份逻辑，否则负控制只是把判定又写了一遍）
# ============================================================
def _vocab_gaps(entries: Sequence[dict], vocab: set[str]) -> list[tuple[str, Any]]:
    """规则①：每条 `evidence.how` 必须 ∈ 受控词表。"""
    return [
        (e.get("id"), ev.get("how"))
        for e in entries
        for ev in (e.get("evidence") or [])
        if ev.get("how") not in vocab
    ]


def _nature_match_gaps(entries: Sequence[dict]) -> list[tuple[str, Any, Any, Any]]:
    """规则②：`nature_match == (reference.qi_mapped == project.nature)`。"""
    gaps = []
    for e in _accepted(entries):
        relation = _reference_qi(e) == _project_nature(e)
        if bool(e.get("nature_match")) != relation:
            gaps.append((e.get("id"), e.get("nature_match"), relation, _reference_qi(e)))
    return gaps


def _delta_gaps(entries: Sequence[dict]) -> list[str]:
    """规则③：`delta` 非空 ⟺ 不一致（一致却写 delta 会让人以为有分歧）。"""
    gaps = []
    for e in _accepted(entries):
        relation = _reference_qi(e) == _project_nature(e)
        if relation and e.get("delta") is not None:
            gaps.append(f"{e.get('id')}（一致却写了 delta）")
        if not relation and not e.get("delta"):
            gaps.append(f"{e.get('id')}（不一致却没写 delta）")
    return gaps


def _mismatch_trace_gaps(entries: Sequence[dict]) -> list[str]:
    """规则④：与来源不一致时必须**留下可读的痕迹**，而不是只有 `nature_match=False`。

    痕迹可以是 `open_question`，也可以是 `mapping_review.reason`（`jiangyou` 就是后者：
    它的理由写在 reason 里 —— 映射采纳、值不改）。此外状态**不得**写「一致」。
    """
    gaps = []
    for e in _accepted(entries):
        if _reference_qi(e) == _project_nature(e):
            continue
        trace = bool(e.get("open_question")) or bool((e.get("mapping_review") or {}).get("reason"))
        if not trace:
            gaps.append(f"{e.get('id')}（不一致但无留痕）")
        if e.get("status") == "一致":
            gaps.append(f"{e.get('id')}（不一致却标了「一致」）")
    return gaps


def _variety_gaps(entries: Sequence[dict]) -> dict[str, list]:
    """规则⑤：`同条目·品种方向描述` 必须是**成对**的。

    这个 how 的语义是「同一条语料条目内按品种／方向给出不同四气」（茶叶 → 绿茶凉／红茶温）。
    所以逐条看是没有意义的，必须按 `matched_name` 分组校验：
    ① 每组 ≥2 条；② 组内 `qi_mapped` 至少两种（否则「方向描述」名不副实）；
    ③ 每条的 `qi_mapped` 必须等于它自己的项目四气（否则项目值与依据对不上）。
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        for ev in (e.get("evidence") or []):
            if ev.get("how") == VARIETY_HOW:
                groups[str(ev.get("matched_name"))].append(e)
    gaps: dict[str, list] = {}
    for matched, members in groups.items():
        problems: list[str] = []
        if len(members) < 2:
            problems.append("只有 1 条，不成对")
        if len({_reference_qi(m) for m in members}) < 2:
            problems.append("组内四气只有一种，称不上「方向描述」")
        for m in members:
            if _reference_qi(m) != _project_nature(m):
                problems.append(f"{m.get('id')} 的 qi 与项目四气不符")
        if problems:
            gaps[matched] = problems
    return gaps


def _synonym_gaps(entries: Sequence[dict]) -> list[str]:
    """规则⑥：`等价名（通称差异）` 的 `matched_name` 必须是**另一个名字**。

    它表达「同一物的通称差异」（蒜→大蒜）。若 `matched_name` 等于项目条目名，
    那这条映射等于什么都没说 ⇒ 变红。
    """
    return [
        f"{e.get('id')}：matched_name 与条目名相同（{e.get('name')}）"
        for e in entries
        for ev in (e.get("evidence") or [])
        if ev.get("how") == SYNONYM_HOW and ev.get("matched_name") == e.get("name")
    ]


# ============================================================
# 正向断言（真实数据）
# ============================================================
def test_every_how_value_is_in_the_controlled_vocab():
    gaps = _vocab_gaps(_entries(), _vocab())
    assert not gaps, f"evidence.how 用了受控词表外的取值：{gaps}"


def test_nature_match_agrees_with_the_reference_entry():
    accepted = _accepted(_entries())
    assert len(accepted) >= 40, f"映射获采纳的条目骤降到 {len(accepted)}，判据可能已失去覆盖面"
    gaps = _nature_match_gaps(_entries())
    assert not gaps, (
        f"这些条目的 nature_match 与「reference 那条的四气 vs 项目四气」不符：{gaps}。"
        "⚠️ 判据比的是 **reference**，不是「条内任一条 evidence」"
    )


def test_delta_present_exactly_when_mismatched():
    gaps = _delta_gaps(_entries())
    assert not gaps, f"delta 与一致性不符：{gaps}"


def test_mismatch_always_leaves_a_readable_trace():
    entries = _entries()
    mismatched = [
        e for e in _accepted(entries)
        if _reference_qi(e) != _project_nature(e)
    ]
    # 非真空：这份数据里确实存在不一致（实测 13 条），否则本条等于没测
    assert len(mismatched) >= 5, f"不一致的条目只剩 {len(mismatched)} 条，负控制失去意义"
    gaps = _mismatch_trace_gaps(entries)
    assert not gaps, f"与来源不一致却没留下痕迹：{gaps}"


def test_variety_direction_descriptions_are_paired():
    gaps = _variety_gaps(_entries())
    assert not gaps, f"{VARIETY_HOW} 的成对性不成立：{gaps}"
    # 非真空：这个 how 至少得真的被用过
    used = sum(
        1 for e in _entries() for ev in (e.get("evidence") or [])
        if ev.get("how") == VARIETY_HOW
    )
    assert used >= 2, f"{VARIETY_HOW} 只被用了 {used} 次，本条已失去覆盖面"


def test_synonym_how_maps_to_a_different_name():
    entries = _entries()
    used = [ev for e in entries for ev in (e.get("evidence") or [])
            if ev.get("how") == SYNONYM_HOW]
    assert len(used) >= 2, f"{SYNONYM_HOW} 只被用了 {len(used)} 次，本条已失去覆盖面"
    gaps = _synonym_gaps(entries)
    assert not gaps, f"{SYNONYM_HOW} 的 matched_name 等于条目名，等于没说：{gaps}"


# ============================================================
# 负控制：人造数据必须让每条规则各自报出来
# ============================================================
def _entry(**over) -> dict:
    base = {
        "id": "x",
        "name": "甲",
        "project": {"nature": "neutral"},
        "evidence": [{"how": "正名", "matched_name": "甲", "qi_mapped": "neutral"}],
        "reference": {"how": "正名", "matched_name": "甲", "qi_mapped": "neutral"},
        "nature_match": True,
        "delta": None,
        "status": "一致",
        "mapping_review": {"accepted": True, "reason": "样例"},
    }
    base.update(over)
    return base


def test_negative_controls_each_rule_bites():
    good = [_entry()]
    assert not _nature_match_gaps(good)
    assert not _delta_gaps(good)
    assert not _mismatch_trace_gaps(good)
    assert not _vocab_gaps(good, _vocab())

    # ② nature_match 说谎
    assert _nature_match_gaps([_entry(nature_match=False)]) == [("x", False, True, "neutral")]
    # ③ 一致却写 delta ／ 不一致却没写
    assert _delta_gaps([_entry(delta="项目「平」 vs 来源「温」")])
    assert _delta_gaps([_entry(
        reference={"qi_mapped": "warm"}, nature_match=False)])
    # ④ 不一致且无留痕（这个合成条目同时踩两条：无留痕 + status 还写着「一致」）
    bad = _entry(reference={"qi_mapped": "warm"}, nature_match=False, delta="d")
    bad["mapping_review"] = {"accepted": True}
    assert _mismatch_trace_gaps([bad]) == [
        "x（不一致但无留痕）",
        "x（不一致却标了「一致」）",
    ]
    # 只把 status 改对、留痕仍缺 ⇒ 只剩第一条
    bad["status"] = "冲突"
    assert _mismatch_trace_gaps([bad]) == ["x（不一致但无留痕）"]
    # ⑤ 品种方向只有 1 条
    one = _entry(evidence=[{"how": VARIETY_HOW, "matched_name": "茶", "qi_mapped": "cool"}])
    assert "茶" in _variety_gaps([one])
    # ⑥ 通称差异写成同名
    same = _entry(evidence=[{"how": SYNONYM_HOW, "matched_name": "甲", "qi_mapped": "warm"}])
    assert _synonym_gaps([same])
    # ① how 不在词表里
    off = _entry(evidence=[{"how": "编的取值"}])
    assert _vocab_gaps([off], _vocab())


def test_negative_control_mutation_via_single_entry(monkeypatch):
    """把「改数据」打在**唯一入口** `_sources()` 上 ⇒ 断言必须变红。

    这条防的是「守卫看着在跑、其实读的是另一份输入」：从入口改，才证明它真在读数据。
    """
    real = _sources()

    mutated = copy.deepcopy(real)
    for e in mutated["entries"]:
        if e.get("id") == "lvcha":
            e["reference"]["qi_mapped"] = "warm"     # 凉 → 温，制造 mismatch
    monkeypatch.setattr(sys.modules[__name__], "_sources", lambda: mutated, raising=True)

    assert _nature_match_gaps(_entries()), "从入口改数据后仍报绿 ⇒ 守卫读的不是这份输入"
    assert _delta_gaps(_entries()), "delta 校验没跟着数据走"
    # 负控制：改完之后，与 lvcha 无关的规则不受影响
    assert not _vocab_gaps(_entries(), _vocab())
