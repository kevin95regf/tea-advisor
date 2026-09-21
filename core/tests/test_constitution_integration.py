"""跨路径一致性守卫（B2 接入 · 提交 4）。

**这个文件存在的全部理由**：体质在链路里有两条彼此独立的消费路径 ——

* LLM 路径：`safety.filter_by_constitution` 构造 Agent2 的候选集
* 离线路径：`matcher.fallback_recommend` 从场景规则 / 体质默认搭配取搭配

两条路径**不共用代码**。所以只改其中一处，结果是：
同一个兼体质用户，**有 Key 和没 Key 会拿到不同的安全边界**，而表面完全看不出来
（界面只显示最终搭配，不显示它是怎么被筛出来的）。

判据不用任何一方的实现，而是**直接从 catalog 读 `unsuitable_for` 的第三方 oracle** ——
否则两边一起改错也测不出来。

⚠️ **别把屏蔽体质写死**，这是本文件第一版踩到的坑
------------------------------------------------
第一版对每个主导体质固定挑「第一个不是它的体质」当屏蔽集。结果默认搭配里
根本没有对它不宜的饮片 ⇒ 断言**恒真**：把离线路径的屏蔽整个删掉，测试照样绿。
变异检验抓到了这一点（见 git log 提交 4）。

所以现在屏蔽体质是**从数据反推**的：先算出「不给屏蔽集时，这组搭配/候选集里
有哪些体质被标了不宜」，再拿这些体质去测屏蔽是否真的生效。
并且显式断言「至少真的测到了 N 组」，防止以后数据一变又退化成恒真。
"""

from __future__ import annotations

import pytest

from app.domain.enums import Constitution, Nature
from app.domain.models import ParsedFood, ParsedMeal
from app.domain.safety import (
    MissingConstitutionDataError,
    filter_by_constitution,
    herb_by_name,
)
from app.services import matcher

ALL_NINE = [c.value for c in Constitution]


def _unsafe_for(names: set[str], avoid: set[str]) -> set[str]:
    """第三方 oracle：这些饮片里，有哪些对 `avoid` 中任一体质标了「不宜」。

    刻意**独立实现**（直接读 catalog），不复用 `filter_by_constitution`，
    也不复用 `matcher._herbs_unsuitable_for_any` —— 复用任意一方，
    就等于让被测代码给自己判卷。
    """
    catalog = herb_by_name()
    unsafe: set[str] = set()
    for name in names:
        entry = catalog.get(name)
        if not entry:
            continue
        unsuitable = {str(x) for x in (entry.get("unsuitable_for") or [])}
        if unsuitable & avoid:
            unsafe.add(name)
    return unsafe


def _meal(nature: Nature) -> ParsedMeal:
    return ParsedMeal(
        foods=[ParsedFood(name="米饭", amount_desc="一碗")],
        overall_nature=nature,
    )


def _llm_names(primary: str, avoid: tuple[str, ...]) -> set[str]:
    catalog_size = len(herb_by_name()) + 1
    return {
        str(e.get("name"))
        for e in filter_by_constitution(primary, limit=catalog_size, avoid=avoid)
    }


def _llm_names_or_none(primary: str, avoid: tuple[str, ...]) -> set[str] | None:
    """`avoid` 把候选集整个清空时，LLM 路径会抛 `MissingConstitutionDataError`。

    这不是 bug：编排层会捕获它并降级到离线路径，离线路径有通用兜底。
    （温阳方向的饮片往往同时对阴虚质不宜，所以这种组合真实存在。）
    这类组合没有「候选集」可断言，跳过。
    """
    try:
        return _llm_names(primary, avoid)
    except MissingConstitutionDataError:
        return None


def _blockable_constitutions(base: set[str], primary: str) -> list[str]:
    """反推：这组饮片对哪些「别的」体质标了不宜 —— 这些才是值得测的屏蔽集。"""

    return [cid for cid in ALL_NINE if cid != primary and _unsafe_for(base, {cid})]


def test_both_paths_block_avoid_consistently() -> None:
    """同一个 (primary, avoid) 下，两条路径都**不许**留下对 avoid 不宜的饮片。

    覆盖离线路径的两个分支（场景规则 / 体质默认搭配）—— §0.1 的教训：
    场景规则分支原本完全不经过体质，只测默认搭配会漏掉整个 rule 分支。
    """
    tested: list[str] = []

    def offline_names(primary: str, avoid: tuple[str, ...], use_rule: bool) -> set[str]:
        """离线路径给出的饮片名。`use_rule=False` 时强制走体质默认搭配分支。"""
        original = matcher._pick_rule
        try:
            if not use_rule:
                matcher._pick_rule = lambda parsed: None  # type: ignore[assignment]
            recs, _, _ = matcher.fallback_recommend(
                _meal(Nature.WARM), Constitution(primary), avoid=avoid
            )
        finally:
            matcher._pick_rule = original
        return {h.name for rec in recs for h in rec.herbs}

    for primary in ALL_NINE:
        for use_rule in (True, False):
            base = offline_names(primary, (), use_rule)
            for cid in _blockable_constitutions(base, primary):
                kept = offline_names(primary, (cid,), use_rule)
                assert _unsafe_for(kept, {cid}) == set(), (
                    f"离线路径（{'rule' if use_rule else 'default'} 分支）"
                    f"给 {primary} 留下了屏蔽集 {cid} 不宜的饮片：{_unsafe_for(kept, {cid})}"
                )
                tested.append(f"offline:{primary}/{cid}")

        llm_base = _llm_names(primary, ())
        for cid in _blockable_constitutions(llm_base, primary):
            kept = _llm_names_or_none(primary, (cid,))
            if kept is None:
                continue
            assert _unsafe_for(kept, {cid}) == set(), (
                f"LLM 路径给 {primary} 留下了屏蔽集 {cid} 不宜的饮片：{_unsafe_for(kept, {cid})}"
            )
            tested.append(f"llm:{primary}/{cid}")

    # ---- 负控制：判据非真空 ----
    # 至少要有若干组真的被屏蔽过，否则上面的循环可能一组都没进（恒真）
    assert len(tested) >= 10, f"实际只测到 {len(tested)} 组，判据可能已退化：{tested}"
    assert any(t.startswith("offline:") for t in tested), "离线路径一次都没被真正测到"
    assert any(t.startswith("llm:") for t in tested), "LLM 路径一次都没被真正测到"


def test_offline_path_excludes_primary_constitution_unsuitable() -> None:
    """E4(α)：离线路径对**主导体质**也要硬排除，与 LLM 路径取齐。

    缺这条时，同一味药对主导体质标了 `unsuitable_for`：LLM 路径 `continue`（硬排除），
    离线路径只追加一句 caution（软提示）⇒ 同一个用户「有 Key / 没 Key」拿到不同的安全
    边界，而界面只显示最终搭配、看不出差异来源。判据用第三方 oracle（直接读 catalog 的
    `unsuitable_for`），不照抄任一方的实现。覆盖 rule 与 default 两个分支。
    """
    def offline_names(primary: str, use_rule: bool) -> set[str]:
        original = matcher._pick_rule
        try:
            if not use_rule:
                matcher._pick_rule = lambda parsed: None  # type: ignore[assignment]
            recs, _, _ = matcher.fallback_recommend(_meal(Nature.WARM), Constitution(primary))
        finally:
            matcher._pick_rule = original
        return {h.name for rec in recs for h in rec.herbs}

    for primary in ALL_NINE:
        for use_rule in (True, False):
            leftover = _unsafe_for(offline_names(primary, use_rule), {primary})
            assert leftover == set(), (
                f"离线路径（{'rule' if use_rule else 'default'} 分支）给 {primary} "
                f"留下了对**主导体质**不宜的饮片：{leftover}"
            )

    # ---- 负控制：把硬剔除整个关掉（模拟 E4 之前），必须有组合会违规 ----
    # 否则这条判据可能一组都没真正约束到（恒真）。这也顺带证明「E4 之前确实违规」。
    original_block = matcher._herbs_unsuitable_for_any
    violations: list[str] = []
    try:
        matcher._herbs_unsuitable_for_any = lambda consts: set()  # type: ignore[assignment]
        for primary in ALL_NINE:
            for use_rule in (True, False):
                if _unsafe_for(offline_names(primary, use_rule), {primary}):
                    violations.append(f"{primary}/{'rule' if use_rule else 'default'}")
    finally:
        matcher._herbs_unsuitable_for_any = original_block
    assert violations, (
        "把硬剔除关掉后一组违规都没有 ⇒ 本测试的判据是真空的（数据已不覆盖 E4）"
    )


def test_avoid_empty_keeps_offline_path_unchanged(monkeypatch) -> None:
    """收口判据：`avoid` **不传与传空等价**（默认不额外引入屏蔽）。

    LLM 路径的同一条等价性在 `test_safety.py` 里守，这里守离线这一侧 ——
    两处分开写，是因为它们不共用代码，不能互相代表。

    ⚠️ 本测试原写作「离线路径必须与**改动前**完全一致」—— **E4(α) 之后这句不再成立**：
    主导体质现在也硬剔除，是**刻意的行为变更**（另见
    `test_offline_path_excludes_primary_constitution_unsuitable`）。保留的是
    「默认 `avoid` 不额外动手」这半件：不传 vs 传空必须逐字相同。
    """
    meal = _meal(Nature.WARM)
    for cid in ALL_NINE:
        constitution = Constitution(cid)
        plain = matcher.fallback_recommend(meal, constitution)
        empty = matcher.fallback_recommend(meal, constitution, avoid=())
        assert [r.model_dump() for r in plain[0]] == [
            r.model_dump() for r in empty[0]
        ], cid
        assert plain[1] == empty[1], cid
        assert plain[2] == empty[2], cid

    # ---- 负控制：判据非真空 ----
    # 屏蔽集挑到「确实有饮片不宜」的那几型（从数据反推，不写死）：
    # 非空 avoid 确实会改变离线结果，否则上面那条等式可能只是两次都返回同一个东西。
    base = {h.name for r in matcher.fallback_recommend(meal, Constitution.BALANCED)[0]
            for h in r.herbs}
    blockable = _blockable_constitutions(base, "balanced")
    assert blockable, f"这份默认搭配对任何体质都没有不宜，负控制无法成立：{base}"

    changed = matcher.fallback_recommend(
        meal, Constitution.BALANCED, avoid=tuple(blockable)
    )
    assert [r.model_dump() for r in changed[0]] != [
        r.model_dump() for r in matcher.fallback_recommend(meal, Constitution.BALANCED)[0]
    ]
