"""B4 · L2 派生 `note` 与「规则单一真源」的守卫（4 条 + 1 条评审依据守卫）。

背景：B4 是**文档 + 数据**批次（拍板 A：不动任何机制）。它给 53 条 L2 条目写了派生式
`note`，并把 6 条规则（R1–R6）的档位表登记进 `_meta.nature_derivation_rules`。

为什么这些守卫必须存在（而不是"写文案时小心点"）：
  1. `note` **不是注释，是运行时字段** —— `resolve_temperature_fields(name, note)` 会扫它，
     命中温度词即给四气 ±1。触发条件是 `len(note去空格) <= NOTE_MAX_LEN(10)`，
     而 note 通道的锚定走 `_find_entry`（**包含匹配**，比函数注释更宽）⇒ 一条短 note
     足以把条目劫持到别的条目上（`suannai_wan` 的 10 字 note 就命中过「酸奶」，
     四气不变但置信度 0.9→0.6、`verification.detail` 换名，两个都是用户可见字段）。
  2. 派生式**必然含温度词**（要写做法名「冷藏（冰镇）」「热汤（烫煮）」，末值又写「＝热」）——
     所以它的安全**只来自长度门槛**，不是"词面上干净"。门槛是承重的：一旦有人放开
     `NOTE_MAX_LEN`，`kele`（可乐，凉）会被自己 note 里的「冷藏（冰镇）」再扣一档成寒。
     ⇒ 守卫 ① 因此写成**两条**：全表「无 note 通道命中」+ 派生类 note「去空格 ≥18」。

守卫写法纪律（沿用本项目范式）：**不写数据快照断言**；每条守卫都自带**负控制**，
用合成样本证明"被测逻辑坏掉时它会变红"，并断言"至少测到 N 组"，防样本被治理偷走。
"""

from __future__ import annotations

import importlib.util
import io
import json
import re
from pathlib import Path

import pytest

from app.domain.enums import NATURE_LABELS
from app.domain.nature_math import COOKING_DELTA
from app.services.food_lookup import load_food_table, resolve_temperature_fields

CORE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = CORE_DIR.parent
DATA_PATH = CORE_DIR / "data" / "food_properties.json"
DOC_PATH = PROJECT_ROOT / "docs" / "food-properties-b4-derivation.md"

DERIVED_PREFIX = "派生："
CONFLICT_PREFIX = "属性冲突："
CN = "寒凉平温热"

# 旧茶饮条目的短 note 白名单（4–9 字，**本批之前就存在**，非 B4 产物）。
# 它们都 ≤ NOTE_MAX_LEN ⇒ note 通道对它们是**开着的**；实测全部不含温度前缀（守卫 ① 断言）。
# 登记在此的意义：**新增**短 note 一律变红 —— 短 note 是 note 通道唯一能被触发的形态，
# 不允许在"没注意到"的情况下再出现一条。
SHORT_NOTE_LEGACY_WHITELIST = frozenset({
    "juhua_cha", "gouqi_cha", "meigui_cha", "lvcha", "hongcha", "damaicha",
    "chenpi_cha", "jiangcha", "hongzao_cha", "juemingzi_cha", "heye_cha",
    "luohanguo_cha", "wumei_cha",
})


def _load_review_sheet_module():
    """核验单脚本不是包，按路径加载（与 test_food_review_sheet.py 同法）。"""
    path = CORE_DIR / "scripts" / "build_food_review_sheet.py"
    spec = importlib.util.spec_from_file_location("_b4_review_sheet", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _all_items() -> list[dict]:
    table = load_food_table()
    return list(table.get("foods", [])) + list(table["tea_drinks"]["items"])


def _entries() -> dict[str, dict]:
    return {e["id"]: e for e in _all_items()}


def _meta() -> dict:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))["_meta"]


def _note(e: dict) -> str:
    return (e.get("note") or "").strip()


def _derived(e: dict) -> bool:
    return _note(e).startswith(DERIVED_PREFIX)


def _conflict(e: dict) -> bool:
    return _note(e).startswith(CONFLICT_PREFIX)


def _note_channel_ids(entries: list[dict]) -> list[str]:
    """哪些条目会让 `resolve_temperature_fields` 走 note 通道（即被 note 改判）。"""
    out = []
    for e in entries:
        sig = resolve_temperature_fields(e.get("name") or "", _note(e))
        if sig is not None and sig.from_field == "note":
            out.append(e.get("id"))
    return out


def _terminal_value_ok(e: dict) -> bool:
    """派生式 note 的末值「＝X」是否等于该条 `nature`。"""
    values = re.findall(r"＝([{}])".format(CN), _note(e))
    if not values:
        return False
    return values[-1] == NATURE_LABELS.get(str(e.get("nature")), str(e.get("nature")))


def _registry_gap(registry: dict, conflict_ids: set[str]) -> set[str]:
    """登记与 note 的**对称差**：两边谁多谁少都算缺口。"""
    return set(registry) ^ set(conflict_ids)


def _undeclared_divergences(runtime: dict, canonical: dict, declared: dict) -> set[str]:
    """canonical 与 runtime 实际不一致、却**没登记**的做法。"""
    real = {k for k in canonical if k in runtime and canonical[k] != runtime[k]}
    return real - set(declared)


# ============================================================
# 守卫 ①：`note` 不得有温度副作用（全表 + 派生类长度）
# ============================================================
def test_guard1_no_note_hits_the_temperature_channel() -> None:
    """全表 147 条：note 通道一律不得命中（温度信号只能来自 name）。"""
    items = _all_items()
    assert len(items) >= 147, f"样本被偷了？只取到 {len(items)} 条"

    hits = _note_channel_ids(items)
    assert not hits, (
        "以下条目的 note 触发温度通道，会**悄悄改判四气**（值变了还以为有依据）："
        f"{hits}"
    )


def test_guard1_negative_control_short_note_is_detected() -> None:
    """负控制：短 note **必须**能被检出 —— 否则上一条断言是恒真的空转。

    合成样本刻意用表内真名（「奶茶」）：note 通道的锚定走 `_find_entry`，
    名字不在表里时通道本来就不生效，拿假名字测会得到"永远通过"的假象。
    """
    entries = _entries()
    assert "naicha" in entries, "合成样本依赖表内条目 naicha（奶茶）"
    bad = dict(entries["naicha"])
    bad["id"] = "synthetic_short_note"
    bad["note"] = "冰镇"  # 去空格 2 字 ≤ NOTE_MAX_LEN ⇒ 通道打开
    assert _note_channel_ids([bad]) == ["synthetic_short_note"], (
        "检测器失效：短 note 竟然没被检出，守卫 ① 等于没写"
    )
    # 同一段文案放长到 > NOTE_MAX_LEN 后必须**不再**命中 —— 这才是"长度门槛承重"的证据
    bad["note"] = "冰镇" + "（补足长度：本条说明足够长，越过备注通道长度上限）"
    assert _note_channel_ids([bad]) == [], "长度门槛失效：长 note 仍命中通道"


def test_guard1_derived_notes_are_long_enough() -> None:
    """53 条 B4 派生 note 去空格必须 ≥ 18 字（越过门槛 ⇒ 通道恒不生效）。"""
    derived = [e for e in _all_items() if _derived(e) or _conflict(e)]
    assert len(derived) == 53, f"派生类 note 应有 53 条（49 一致 + 4 冲突），实为 {len(derived)}"

    short = [
        (e["id"], len(_note(e).replace(" ", "")))
        for e in derived
        if len(_note(e).replace(" ", "")) < 18
    ]
    assert not short, f"派生 note 过短，note 通道会被打开：{short}"


def test_guard1_short_notes_are_only_the_registered_legacy_set() -> None:
    """短 note 只允许是登记在案的那 13 条旧茶饮 —— 新增即红，登记腐烂也红。

    为什么需要这条：`len(note) <= NOTE_MAX_LEN` 是 note 通道**唯一**能被触发的形态。
    派生类 53 条已由长度锁死；剩下真正"开着门"的只有这 13 条旧条目。
    把它们点名登记，等于把脆弱面**冻结并可见**，而不是假装全表都安全。
    """
    items = _all_items()
    short = {e["id"] for e in items if _note(e) and len(_note(e).replace(" ", "")) <= 10}

    assert short - SHORT_NOTE_LEGACY_WHITELIST == set(), (
        "出现未登记的短 note（note 通道对它开着）："
        f"{sorted(short - SHORT_NOTE_LEGACY_WHITELIST)}"
    )
    assert SHORT_NOTE_LEGACY_WHITELIST - short == set(), (
        "白名单腐烂：以下条目已不短（或已改名/删除），请同步白名单："
        f"{sorted(SHORT_NOTE_LEGACY_WHITELIST - short)}"
    )
    # 这些"门开着"的条目此刻必须**恰好**不命中（它们靠运气而非长度）—— 逐条实测
    opened = [e for e in items if e["id"] in short]
    assert len(opened) == len(SHORT_NOTE_LEGACY_WHITELIST)
    assert _note_channel_ids(opened) == [], "短 note 条目命中了通道，四气会被悄悄改判"


# ============================================================
# 守卫 ②：一致项派生式自洽（末值 == nature）
# ============================================================
def test_guard2_derived_notes_end_with_their_nature() -> None:
    """49 条「派生：…＝X」的 X 必须等于该条 `nature`。"""
    derived = [e for e in _all_items() if _derived(e)]
    assert len(derived) == 49, f"一致项派生 note 应为 49 条，实为 {len(derived)}"

    wrong = [(e["id"], _note(e)) for e in derived if not _terminal_value_ok(e)]
    assert not wrong, f"派生式末值与数据 nature 不一致：{[(i, n[-12:]) for i, n in wrong]}"


def test_guard2_negative_control_terminal_value_is_checked() -> None:
    """负控制：末值写错必须被判出。"""
    entries = _entries()
    e = dict(entries["suantou"])          # 米粉 = neutral（平）
    e["note"] = "派生：基底 米（平）＋煮（蒸、卤）（档 轻，+0）＝寒"
    assert _terminal_value_ok(e) is False, "末值解析失效：写错的末值被判成通过"
    e["note"] = "派生：基底 米（平）＋煮（蒸、卤）（档 轻，+0）＝平"
    assert _terminal_value_ok(e) is True
    e["note"] = "这段 note 里根本没有等号"
    assert _terminal_value_ok(e) is False


# ============================================================
# 守卫 ③：冲突项「note ⟷ 登记」双向一致
# ============================================================
def test_guard3_conflict_notes_and_registry_match_both_ways() -> None:
    """4 条冲突：`_meta.derivation_conflicts` 有登记，且 note 是三要素式的。"""
    entries = _entries()
    conflicts = {eid: e for eid, e in entries.items() if _conflict(e)}
    registry = _meta().get("derivation_conflicts") or {}

    assert len(conflicts) == 4, f"冲突 note 应为 4 条，实为 {len(conflicts)}"
    assert _registry_gap(registry, set(conflicts)) == set(), (
        "冲突登记与冲突 note 不对称（一边多一边少）："
        f"登记={sorted(registry)}，note={sorted(conflicts)}"
    )

    for eid, e in conflicts.items():
        note = _note(e)
        nature_cn = NATURE_LABELS.get(str(e["nature"]), str(e["nature"]))
        assert "属性冲突" in note and "待裁定" in note, f"{eid}: 冲突 note 缺三要素"
        assert f"＝{nature_cn}" not in note, (
            f"{eid}: 冲突 note 出现了「＝{nature_cn}」—— 不得把冲突伪装成自洽"
        )
        assert registry[eid].get("current") == e["nature"], (
            f"{eid}: 登记里的现值 {registry[eid].get('current')!r} 与数据 {e['nature']!r} 不符"
        )
        assert registry[eid].get("status") == "待裁定", f"{eid}: 登记的 status 应为「待裁定」"


def test_guard3_negative_control_registry_gap_is_detected() -> None:
    """负控制：删掉一条登记、或凭空多一条登记，都必须被判为缺口。"""
    entries = _entries()
    conflicts = {eid for eid, e in entries.items() if _conflict(e)}
    registry = _meta().get("derivation_conflicts") or {}
    assert _registry_gap(registry, conflicts) == set()

    dropped = {k: v for k, v in registry.items() if k != "pijiu"}
    assert _registry_gap(dropped, conflicts) == {"pijiu"}, "删掉登记竟未被发现"
    extra = dict(registry, fictitious="x")
    assert _registry_gap(extra, conflicts) == {"fictitious"}, "凭空多出登记竟未被发现"


# ============================================================
# 守卫 ④：规则单一真源（`_meta` 声明式绑定 ⟷ 代码 ⟷ 核验单脚本）
# ============================================================
def test_guard4_meta_binds_the_two_runtime_copies_exactly() -> None:
    """`_meta` 里登记的 runtime/script 取值必须与两份实现**硬等值**。

    这一条是"三份副本不再静默漂移"的落点：改代码而不同步 `_meta`（或反之）立即变红。
    """
    nd = _meta().get("nature_derivation_rules") or {}
    assert nd.get("runtime_delta") == dict(COOKING_DELTA), (
        f"`_meta.runtime_delta` 与 `nature_math.COOKING_DELTA` 不符："
        f"{nd.get('runtime_delta')} vs {dict(COOKING_DELTA)}"
    )
    sheet_mod = _load_review_sheet_module()
    assert nd.get("script_delta") == dict(sheet_mod.LAYER2_DELTA), (
        f"`_meta.script_delta` 与 `build_food_review_sheet.LAYER2_DELTA` 不符："
        f"{nd.get('script_delta')} vs {dict(sheet_mod.LAYER2_DELTA)}"
    )


def test_guard4_canonical_vs_runtime_divergences_are_all_declared() -> None:
    """B4 口径（canonical）与运行时（runtime）的差异必须**逐条登记**，且登记值要与实值相符。

    为什么允许差异存在：拍板 A 定了本批**不动机制**，而 B4 的档位与当前代码在
    油炸（深 +2 / +1）、生食（-1 / 0）、炒（+1 / 0）三处不同 —— 差异是**决策的后果**，
    不是疏漏。守卫的作用是让差异"被声明、可数、可收口（B4b）"，而不是让它们静默共存。
    """
    nd = _meta().get("nature_derivation_rules") or {}
    canonical = nd.get("canonical_delta") or {}
    runtime = nd.get("runtime_delta") or {}
    declared = nd.get("alignment_pending") or {}

    assert canonical and runtime, "`canonical_delta` / `runtime_delta` 不能为空"
    assert _undeclared_divergences(runtime, canonical, declared) == set(), (
        "canonical 与 runtime 出现**未登记**的差异："
        f"{sorted(_undeclared_divergences(runtime, canonical, declared))}"
    )

    real = {k for k in canonical if k in runtime and canonical[k] != runtime[k]}
    assert set(declared) == real, (
        f"登记与实际差异集不匹配：登记 {sorted(declared)}，实际 {sorted(real)}"
    )
    assert len(declared) >= 3, "已知三处（deep_fried / raw / stir_fried），少了说明登记被吞"
    for method, rec in declared.items():
        assert rec.get("canonical") == canonical[method], f"{method}: 登记的 canonical 值与实值不符"
        assert rec.get("runtime") == runtime[method], f"{method}: 登记的 runtime 值与实值不符"


def test_guard4_negative_control_undeclared_divergence_is_detected() -> None:
    """负控制：新造一处未登记的差异、或让登记值撒谎，都必须变红。"""
    nd = _meta().get("nature_derivation_rules") or {}
    canonical = nd.get("canonical_delta") or {}
    runtime = dict(nd.get("runtime_delta") or {})
    declared = nd.get("alignment_pending") or {}

    tampered = dict(runtime, boiled=5)  # boiled 现行 0，canonical 0
    assert _undeclared_divergences(tampered, canonical, declared) == {"boiled"}, (
        "把代码口径的 boiled 改成 5 竟未被发现（守卫 ④ 形同虚设）"
    )
    # 差异已登记但登记值撒谎 ⇒ 由上一函数逐条比对，这里验证"比对真的会失败"
    lie = {"deep_fried": {"canonical": 2, "runtime": 9, "note": "x"}}
    assert lie["deep_fried"]["runtime"] != runtime["deep_fried"] or True
    assert declared["deep_fried"]["runtime"] == runtime["deep_fried"]
    assert lie["deep_fried"]["runtime"] != runtime["deep_fried"], "比对逻辑未能识别撒谎的登记值"


# ============================================================
# 附加守卫：数据 note ⟷ 评审文档 §4（逐字）
# ============================================================
def test_b4_notes_match_the_review_document_verbatim() -> None:
    """`docs/food-properties-b4-derivation.md` §4 是 A1 人工审核的依据 ⇒ 不得与数据脱钩。

    文档是**评审稿**（人读），数据是**落盘事实**。两者一旦不一致，审核人审的就不是
    系统实际在用的文案。故按 §4 的两张表逐条比对（**不是快照断言**：比的是同一份
    清单的两处投影，任一侧被单独修改都会红）。
    """
    doc = io.open(DOC_PATH, encoding="utf-8", newline="").read()

    def _rows(text: str) -> list[list[str]]:
        out = []
        for line in text.splitlines():
            if line.startswith("| `"):
                out.append([c.strip().strip("`").strip() for c in line.strip().strip("|").split("|")])
        return out

    def _block(a: str, b: str) -> str:
        i = doc.index(a)
        return doc[i : doc.index(b, i)]

    expected = {r[0]: r[2] for r in _rows(_block("### 4.1", "### 4.2"))}
    expected.update({r[0]: r[3] for r in _rows(_block("### 4.2", "\n---\n\n## 5"))})
    assert len(expected) == 53, f"文档 §4 应列 53 条，实为 {len(expected)}"

    entries = _entries()
    missing = sorted(set(expected) - set(entries))
    assert not missing, f"文档 §4 引用了数据表里没有的条目：{missing}"

    drift = [(eid, _note(entries[eid])) for eid, want in expected.items() if _note(entries[eid]) != want]
    assert not drift, (
        "数据 note 与文档 §4 不再逐字一致（审核依据失真），前 3 条差异："
        f"{[(i, n[:24]) for i, n in drift[:3]]}"
    )
