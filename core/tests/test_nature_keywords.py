"""三份寒热／辣词表的关系守卫 —— 「辣词对齐」的**乙方案**。

三份词表（**刻意不合并**）
-------------------------
① `core/data/diet_signals.json` 的 `nature_keywords`（`cold` / `hot` / `warm`）
   —— 离线路径猜整餐四性用（`_match_nature_from_text`）；
② 同文件 `scene_rules.spicy.keywords` —— 「这餐算辛辣场景吗」用（选搭配）；
③ `core/app/domain/nature_math.SPICY_KEYWORDS`（**代码常量**）—— 「文本里有没有辛辣信号」
   的判据，喂 `has_spicy_marker()`（四性 +1 修正 ＋ `diet_signals._is_spicy` 计分）。

2026-09-21 裁定：**不合并**。合并要给 `nature_math` 引入数据依赖，而它是本项目少见的
**零 IO 纯模块** —— 为 10 个词破它不划算。⇒ 承认三者不同，但**把「不同」登记在案**：
下面三个差额集合就是登记项，任何一处词表被改（增／删／改名）都会让差额变化 ⇒ **变红**，
逼着改的人显式说明「这次分叉是有意的」。

⚠️ 这不属于「两份名单必然漂移」那类反模式：漂移危险是因为**无声**；这里的分叉是**有声**的
—— 登记项就是那条声。所以本文件**不**断言三表相等（那是假目标），只断言「关系没变」。
"""

from __future__ import annotations

import sys

import pytest

from app.domain.diet_signals import load_nature_keywords, load_scene_rules
from app.domain.nature_math import SPICY_KEYWORDS

# ============================================================
# 登记：三表之间的**当前**关系（改动必须显式更新这里）
# ============================================================
# 关系①：`nature_keywords.cold`（四性判定）与 `scene_rules.cold_intake.keywords`（选搭配）
# 目前**逐字相同**。两者是不同判据，将来要分叉是允许的 —— 但必须改这条登记并写明理由。
COLD_LISTS_ARE_EQUIVALENT = True

# 关系②：场景辣词表必须是四性热词表的**子集**（凡场景认作辛辣的词，四性判定也该认）。
SCENE_SPICY_MUST_SUBSET_HOT = True

# 关系③：三表共有的「核心辣词」—— 一个都不能少（少了说明某表被改名/删词而没同步）
CORE_SPICY_WORDS = frozenset({"辣", "麻辣", "孜然"})

# 关系④：**已知的、有意的**差额（登记项）。任何一处变动都会改这些集合 ⇒ 红。
SPICY_MINUS_HOT = frozenset({"重辣", "加辣", "辣椒", "花椒", "芥末", "咖喱", "胡椒"})
HOT_MINUS_SPICY = frozenset({"椒", "烧烤", "火锅", "炸"})
SCENE_SPICY_MINUS_SPICY = frozenset({"椒", "烧烤"})
# 关系⑤：`hot` 里借自 `scene_rules.greasy` 的词（离线四性表当年从场景规则抄了这几个）
HOT_BORROWED_FROM_GREASY = frozenset({"烧烤", "火锅", "炸", "麻辣"})


# ---- 单一入口（变异检验要顶替的就是它们）----
def _nature_keywords() -> dict[str, tuple[str, ...]]:
    return load_nature_keywords()


def _scene_rules() -> dict[str, dict]:
    return {str(r["id"]): r for r in load_scene_rules()}


def _spicy_keywords() -> frozenset[str]:
    return frozenset(SPICY_KEYWORDS)


def _cold() -> set[str]:
    return set(_nature_keywords()["cold"])


def _hot() -> set[str]:
    return set(_nature_keywords()["hot"])


def _scene_spicy() -> set[str]:
    return set(_scene_rules()["spicy"].get("keywords") or [])


# ============================================================
# 关系①：cold 两表逐字相同
# ============================================================
def test_cold_lists_are_equivalent():
    if not COLD_LISTS_ARE_EQUIVALENT:
        pytest.skip("登记为「允许分叉」，见文件头")
    cold = _cold()
    scene_cold = set(_scene_rules()["cold_intake"].get("keywords") or [])
    assert cold, "nature_keywords.cold 为空 —— 判据失去覆盖面"
    assert cold == scene_cold, (
        f"两份 cold 词表已分叉：只在四性表 {sorted(cold - scene_cold)}／只在场景表 "
        f"{sorted(scene_cold - cold)}。⚠️ 分叉可以，但要改本文件的登记并写明理由"
    )


# ============================================================
# 关系②：场景辣词 ⊆ 四性热词
# ============================================================
def test_scene_spicy_is_a_subset_of_hot():
    hot = _hot()
    scene_spicy = _scene_spicy()
    assert scene_spicy, "scene_rules.spicy.keywords 为空 —— 判据失去覆盖面"
    if SCENE_SPICY_MUST_SUBSET_HOT:
        extra = scene_spicy - hot
        assert not extra, (
            f"场景辣词不在四性热词表里：{sorted(extra)} —— "
            "这些词会被「选搭配」认作辛辣、却不影响整餐四性判定"
        )


# ============================================================
# 关系③：核心辣词三表共有
# ============================================================
def test_core_spicy_words_are_shared():
    hot, scene_spicy, spicy = _hot(), _scene_spicy(), _spicy_keywords()
    for word in sorted(CORE_SPICY_WORDS):
        assert word in hot, f"核心辣词 {word!r} 已不在 nature_keywords.hot"
        assert word in scene_spicy, f"核心辣词 {word!r} 已不在 scene_rules.spicy"
        assert word in spicy, f"核心辣词 {word!r} 已不在 SPICY_KEYWORDS"


# ============================================================
# 关系④：登记的三组差额必须原样
# ============================================================
def test_registered_divergences_are_unchanged():
    hot, scene_spicy, spicy = _hot(), _scene_spicy(), _spicy_keywords()
    checks = [
        ("SPICY_KEYWORDS − hot", spicy - hot, SPICY_MINUS_HOT),
        ("hot − SPICY_KEYWORDS", hot - spicy, HOT_MINUS_SPICY),
        ("scene_rules.spicy − SPICY_KEYWORDS", scene_spicy - spicy, SCENE_SPICY_MINUS_SPICY),
    ]
    for label, actual, registered in checks:
        assert actual == registered, (
            f"{label} 变了：现在 {sorted(actual)}，登记的是 {sorted(registered)}。"
            "⚠️ 三表分叉是**有意**的，但任何变动都要同步更新本文件的登记（并说明理由）"
        )


def test_hot_words_borrowed_from_greasy_are_registered():
    """`hot` 里有几个词是当年从 `RULES.greasy.keywords` 抄来的（本次搬迁**未改值**）。

    这条把「借来的那部分」也登记住 —— 否则将来有人清理 `hot`（比如去掉「炸」），
    会静默改掉离线四性判定。
    """
    borrowed = _hot() & set(_scene_rules()["greasy"].get("keywords") or [])
    assert borrowed == HOT_BORROWED_FROM_GREASY, (
        f"`hot` 与 `greasy` 的重叠变了：现在 {sorted(borrowed)}，"
        f"登记的是 {sorted(HOT_BORROWED_FROM_GREASY)}"
    )


# ============================================================
# 变异检验：从单一入口改一份词表 ⇒ 对应关系必须红
# ============================================================
def test_negative_control_and_mutation(monkeypatch):
    # 基线：全部关系成立
    test_cold_lists_are_equivalent()
    test_scene_spicy_is_a_subset_of_hot()
    test_core_spicy_words_are_shared()
    test_registered_divergences_are_unchanged()

    MOD = sys.modules[__name__]
    real_nk = _nature_keywords()
    real_spicy = _spicy_keywords()

    # 变异：从四性表里删掉一个核心辣词 ⇒ 关系③ 与 ④ 都必须红
    broken_nk = {**real_nk, "hot": tuple(w for w in real_nk["hot"] if w != "麻辣")}
    monkeypatch.setattr(MOD, "_nature_keywords", lambda: broken_nk)
    with pytest.raises(AssertionError):
        test_core_spicy_words_are_shared()
    with pytest.raises(AssertionError):
        test_registered_divergences_are_unchanged()
    monkeypatch.undo()

    # 变异：给代码常量表加一个词 ⇒ 差额必须红（说明它与数据表脱钩了）
    monkeypatch.setattr(MOD, "_spicy_keywords", lambda: real_spicy | {"新词"})
    with pytest.raises(AssertionError):
        test_registered_divergences_are_unchanged()
    monkeypatch.undo()

    # 变异：让 cold 两表分叉 ⇒ 关系① 必须红
    monkeypatch.setattr(MOD, "_cold", lambda: set(real_nk["cold"]) - {"凉"})
    with pytest.raises(AssertionError):
        test_cold_lists_are_equivalent()
    monkeypatch.undo()

    # 负控制：改一个与本组关系无关的（warm 表增删）⇒ 五条关系仍全绿
    monkeypatch.setattr(
        MOD, "_nature_keywords",
        lambda: {**real_nk, "warm": tuple(real_nk["warm"]) + ("不相关的词",)},
    )
    test_cold_lists_are_equivalent()
    test_scene_spicy_is_a_subset_of_hot()
    test_core_spicy_words_are_shared()
    test_registered_divergences_are_unchanged()
    test_hot_words_borrowed_from_greasy_are_registered()
    monkeypatch.undo()
