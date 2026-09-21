"""`scene_rules`（场景 → 首选搭配）：结构守卫 · 分层守卫 · **真源守卫** —— D24。

背景
----
2026-09-21 之前，四条场景规则的 `keywords`／`blend`／`title`／`reason` 都是
`core/app/services/matcher.py` 里的**代码常量**。`signals` 侧虽已数据化，但它只认
条目／类目，并由 `test_diet_signals.py::test_no_bare_substring_scanning` 钉住
「不裸扫原文」——两套判据机制不同，不能合并；但**词表该只有一个真源**。

D24 把这四条整条迁进 `core/data/diet_signals.json` 的顶层 `scene_rules` 段，
`matcher.RULES` 改为**从数据派生**（`matcher._scene_rules()`）。

本文件守三件事
--------------
1. **结构**：字段齐备、id 唯一、`match_natures` 值合法、`blend` 的饮片必须在白名单里。
2. **分层**：`signals` 段不得出现 `keywords` —— 那会把「只认条目」的计分层变成
   子串扫描层，与 `test_no_bare_substring_scanning` 的纪律正面冲突。
3. **真源**：改数据 ⇒ `_scene_rule_ids`／`RULES` 必须随变。⚠️ 没有这一条，
   「迁移」完全可能只是**留了一份常量副本**（代码仍读代码），而前两条守卫照样全绿。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.domain.diet_signals import (
    MissingSceneRulesError,
    load_diet_signals,
    load_scene_rules,
)
from app.domain.enums import Nature
from app.domain.models import ParsedFood, ParsedMeal
from app.domain.safety import herb_whitelist_names
from app.services import matcher

CORE_DIR = Path(__file__).resolve().parent.parent

REQUIRED_FIELDS = ("id", "label", "priority", "match_natures", "keywords",
                   "blend", "title", "reason")


# ============================================================
# 1. 结构
# ============================================================
def test_scene_rules_have_required_fields():
    rules = load_scene_rules()
    assert rules, "scene_rules 段为空 —— 要么没迁移，要么被误删"
    for rule in rules:
        for field in REQUIRED_FIELDS:
            assert field in rule, f"{rule.get('id')} 缺字段 {field}"
        assert str(rule["id"]).strip(), "id 不能为空"
        assert str(rule.get("label") or "").strip(), f"{rule['id']} 的 label 为空"
        assert int(rule["priority"]) > 0, f"{rule['id']} 的 priority 应为正数"


def test_scene_rule_ids_are_unique():
    ids = [str(r["id"]) for r in load_scene_rules()]
    assert len(ids) == len(set(ids)), f"scene_rules id 重复：{ids}"


def test_scene_rule_natures_are_valid():
    valid = {n.value for n in Nature}
    for rule in load_scene_rules():
        bad = [n for n in rule["match_natures"] if n not in valid]
        assert not bad, f"{rule['id']} 的 match_natures 有非法值：{bad}（合法：{sorted(valid)}）"


def test_scene_rule_blend_herbs_are_whitelisted():
    """搭配里只能出现白名单饮片 —— 写错一个字会静默变成「少一味」。"""
    allowed = herb_whitelist_names()
    for rule in load_scene_rules():
        for herb in rule["blend"]:
            assert herb.get("name") in allowed, (
                f"{rule['id']} 的搭配引用了不在白名单的饮片：{herb.get('name')!r}"
            )
            assert float(herb.get("amount_g") or 0) > 0, (
                f"{rule['id']} 的 {herb.get('name')} 克数应为正数"
            )


def test_late_night_copy_never_names_a_time_of_day():
    """`late_night` 不是夜宵规则（见该条的 `note`）⇒ 对外文案不许提「夜里／夜宵」。

    D31 的结论原先是代码注释，迁移时随规则一起进了数据；这条把它钉在数据上，
    因为文案现在也在数据里了。
    """
    rule = next(r for r in load_scene_rules() if r["id"] == "late_night")
    shown = f"{rule['label']}{rule['title']}{rule['reason']}"
    for bad in ("夜里", "夜宵", "宵夜"):
        assert bad not in shown, f"late_night 的对外文案出现了「{bad}」：{shown}"


# ============================================================
# 2. 分层：计分层不得出现子串词表
# ============================================================
def test_scoring_layer_has_no_keyword_lists():
    """`signals` 是计分层，判据只能是条目／类目；出现 `keywords` 就是纪律被破了。"""
    offenders = [
        s.get("id")
        for s in (load_diet_signals().get("signals") or [])
        if "keywords" in (s.get("rule") or {})
    ]
    assert not offenders, (
        f"signals 里出现了 keywords：{offenders}。子串词表属于 scene_rules —— "
        "混进计分层会让「不裸扫原文」的纪律失效（见 test_diet_signals.py 的同名守卫）"
    )


# ============================================================
# 3. 真源：改数据必须改行为
# ============================================================
def _scene_rule_ids(meal: ParsedMeal) -> set[str]:
    return matcher._scene_rule_ids(meal, None)


def _meal(name: str, nature: Nature) -> ParsedMeal:
    return ParsedMeal(foods=[ParsedFood(name=name)], overall_nature=nature)


def _mutated_rules(drop: tuple[str, str]) -> tuple[dict, ...]:
    """内存里改副本：把 `drop[0]` 号规则的关键词 `drop[1]` 删掉。"""
    rules = [dict(r) for r in load_scene_rules()]
    for r in rules:
        if r["id"] == drop[0]:
            r["keywords"] = [k for k in r["keywords"] if k != drop[1]]
    return tuple(rules)


def test_scene_rule_ids_react_to_data_edits(monkeypatch):
    """删掉数据里的一个关键词 ⇒ 命中集必须随之变化。

    「炸鱼薯条」只靠关键词「炸」命中 greasy（它的四性是 hot，但 `_scene_rule_ids`
    只认关键词）⇒ 删「炸」必须让它掉出去。
    """
    meal = _meal("炸鱼薯条", Nature.HOT)
    assert "greasy" in _scene_rule_ids(meal), "样本前提失效：炸鱼薯条本应命中 greasy"

    monkeypatch.setattr(matcher, "load_scene_rules", lambda: _mutated_rules(("greasy", "炸")))
    monkeypatch.setattr(matcher, "RULES", matcher._scene_rules())
    assert "greasy" not in _scene_rule_ids(meal), (
        "删掉数据里的「炸」后仍命中 greasy ⇒ RULES 不是从数据派生的（留了常量副本）"
    )


def test_unrelated_data_edits_do_not_change_scene_rule_ids(monkeypatch):
    """负控制：改**别的**规则不该误伤（否则上一条可能只是「什么都变红」）。"""
    meal = _meal("炸鱼薯条", Nature.HOT)
    monkeypatch.setattr(matcher, "load_scene_rules", lambda: _mutated_rules(("spicy", "孜然")))
    monkeypatch.setattr(matcher, "RULES", matcher._scene_rules())
    assert "greasy" in _scene_rule_ids(meal)


def test_rules_copy_comes_from_data(monkeypatch):
    """改数据里的文案 ⇒ `RULES` 里的文案跟着变（证明没有第二份文案副本）。"""
    rules = [dict(r) for r in load_scene_rules()]
    for r in rules:
        if r["id"] == "greasy":
            r["title"] = "改过的标题"
    monkeypatch.setattr(matcher, "load_scene_rules", lambda: tuple(rules))
    rebuilt = matcher._scene_rules()
    assert next(r for r in rebuilt if r["id"] == "greasy")["title"] == "改过的标题"


def test_edit_at_the_file_reader_reaches_rebuilt_rules(monkeypatch):
    """把修改打在**最外层文件读取**（`load_diet_signals`）上，链条必须一路走通：

        diet_signals.json  → load_diet_signals → load_scene_rules → _scene_rules → RULES

    上面那条只证明「`matcher` 调了 loader」；这条把起点接到文件入口，闭合整条链。
    ⚠️ 顺带把语义钉住：`RULES` 是 **import 期快照**（`RULES = _scene_rules()`），
    所以改数据文件需要重启进程才生效 —— 不是每个请求都读盘。有人要改成每请求读盘，
    应当是有意识的决定，而不是顺手改掉。
    """
    from app.domain import diet_signals

    data = load_diet_signals()
    mutated = {
        **data,
        "scene_rules": [
            {**r, "keywords": [k for k in r["keywords"] if k != "炸"]}
            if r["id"] == "greasy" else r
            for r in data["scene_rules"]
        ],
    }
    monkeypatch.setattr(diet_signals, "load_diet_signals", lambda: mutated)
    diet_signals.load_scene_rules.cache_clear()
    try:
        greasy = next(r for r in matcher._scene_rules() if r["id"] == "greasy")
        assert "炸" not in greasy["keywords"], "改文件读取层后重建不出新词表 ⇒ 链条断了"
        assert matcher.RULES is not None and "炸" in next(
            r for r in matcher.RULES if r["id"] == "greasy"
        )["keywords"], "RULES 应是 import 期快照，不该跟着数据实时变"
    finally:
        diet_signals.load_scene_rules.cache_clear()


def _matcher_source() -> str:
    """`matcher.py` 的源码文本。

    ⚠️ 抽成函数是**为了变异检验能顶替它**：守卫如果直接读盘，变异检验改的是内存副本、
    守卫读的是原文，结果会「显示绿」—— 这正是本项目踩过的「同一份输入只能有一个入口」。
    """
    return (CORE_DIR / "app/services/matcher.py").read_text(encoding="utf-8")


def test_RULES_is_built_from_the_loader_not_inlined():
    """结构守卫：`matcher.py` 里 `RULES` 必须恰有一处赋值，且值是 `_scene_rules()` 调用。

    内联字面量会让数据表变成**第二份副本** —— 而「两份名单必然漂移」是项目记过的坑。
    """
    tree = ast.parse(_matcher_source())
    assigns = [
        node for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and getattr(node.target, "id", None) == "RULES"
    ]
    assert len(assigns) == 1, f"matcher.py 里 RULES 应恰有一处赋值，实际 {len(assigns)} 处"
    value = assigns[0].value
    assert isinstance(value, ast.Call) and getattr(value.func, "id", "") == "_scene_rules", (
        "RULES 必须由 `_scene_rules()` 派生；直接内联字面量等于又造了一份真源"
    )


# ============================================================
# 4. 缺数据要响亮地失败
# ============================================================
@pytest.mark.parametrize(
    "fake_signals",
    [{}, {"signals": [], "dimensions": {}}],
    ids=["整份文件缺失", "只有 scene_rules 段缺失"],
)
def test_missing_scene_rules_raises(monkeypatch, fake_signals):
    """缺段 ⇒ 抛异常。静默返回空表等于「所有场景规则悄悄失效」，那是行为降级。"""
    from app.domain import diet_signals

    monkeypatch.setattr(diet_signals, "load_diet_signals", lambda: fake_signals)
    diet_signals.load_scene_rules.cache_clear()
    try:
        with pytest.raises(MissingSceneRulesError):
            diet_signals.load_scene_rules()
    finally:
        diet_signals.load_scene_rules.cache_clear()
