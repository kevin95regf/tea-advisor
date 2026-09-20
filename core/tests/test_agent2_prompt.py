"""Agent2 提示词与「须煎煮」标记的派生不变式测试。

守的是两类静默缺陷：

1. **`agent2_system.md` 的体质方向提要漏型。** 这份提要**是 `constitution.json`
   的第二份副本**（真源已由 `build_user_prompt()` 注入用户提示词）。副本漏一型，
   就会出现「用户选中阴虚质、模型只看到其余 5 型方向」——从输出表面完全看不出来。
   2026-09-18 之前它只写了 5 型，而九型早已上线。

2. **提示词文字与 `herbs.json` 标记脱钩。** 提示词是「范式」：示例用什么冲泡方式，
   模型就照着答。缺口 2 的反例正是提示词自己教的（「茯苓 + 保温杯焖 8 分钟」）。

3. **提示词教「寒热对冲」。** 第 3 条原本写着「吃了燥热的，配清凉的」，与已定口径⑨
   （不对冲、以护脾胃为准）直接矛盾。提示词是范式，模型会照着答 ⇒ 用户拿到的
   正是被否掉的方向。2026-09-20 随阶段 1 改掉，并加守卫防回退。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.agents.agent2_recommend import _candidate_lines
from app.domain.enums import Constitution
from app.domain.safety import (
    herb_requires_cooking,
    herb_whitelist_names,
    load_herb_catalog,
)

CORE_DIR = Path(__file__).resolve().parent.parent
PROMPT_PATH = CORE_DIR / "app" / "agents" / "prompts" / "agent2_system.md"
CONSTITUTION_PATH = CORE_DIR / "data" / "constitution.json"

# 「方向提要」行的形态：`   - 阴虚质：滋阴润燥方向，…`
# 只认行首的 `- X质：`，**不查全文** —— 示例段里有「体质：痰湿质」，
# 全文扫描会把「痰湿质在示例里出现过」当成「提要里有这一型」，测试就废了。
DIRECTION_LINE_RE = re.compile(r"^\s*-\s*(\S+?质)\s*：", re.M)

# 示例里的输出 JSON：整行一个对象
EXAMPLE_JSON_RE = re.compile(r'^\{"recommendations".*$', re.M)

# 提示词里点名的「后下」名单：`香气类饮片（薄荷、藿香、…）`
LATE_ADD_RE = re.compile(r"香气类饮片（([^）]+)）")


def load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def load_constitutions() -> list[dict]:
    return json.loads(CONSTITUTION_PATH.read_text(encoding="utf-8"))["constitutions"]


def _missing_constitution_labels(prompt_text: str, constitutions: list[dict]) -> list[str]:
    """提示词的方向提要里缺了哪些体质 label。

    **纯函数**：不读文件、不依赖真实数据 ——
    正向测试与负控制共用同一份判定（否则负控制只是把判定又抄了一遍，属假保证）。
    """
    listed = set(DIRECTION_LINE_RE.findall(prompt_text))
    return [c["label"] for c in constitutions if c["label"] not in listed]


def _brew_is_cook(brew: dict) -> bool:
    vessel = str(brew.get("vessel") or "")
    return (
        int(brew.get("steep_min") or 0) >= 20
        and int(brew.get("water_temp_c") or 0) >= 100
        and ("壶" in vessel or "锅" in vessel)
    )


# ============================================================
# 缺口 1：体质方向提要必须覆盖 constitution.json 的全部体质
# ============================================================
def test_agent2_prompt_covers_all_constitutions() -> None:
    """提示词的方向提要必须覆盖 `constitution.json` 的**全部** id→label。

    这是派生不变式，不写死「9」或「4」：下次加第 10 型，这条自动变红，
    强制做一次显式决定（补一行，或说明为什么不需要）。
    """
    constitutions = load_constitutions()
    assert len(constitutions) >= 9, "constitution.json 少于 9 型，样本异常"

    missing = _missing_constitution_labels(load_prompt(), constitutions)
    assert not missing, (
        f"agent2_system.md 的体质方向提要漏了这些体质：{missing}。"
        "它是 constitution.json 的第二份副本 —— 漏一型就会出现「用户选中该体质、"
        "模型只看到其余方向」的静默缺陷。补上对应的一行后再跑。"
    )


def test_coverage_check_negative_control() -> None:
    """人造第 10 型（血虚质）必须被报出来 —— 否则上一条可能根本没在检查。"""
    constitutions = load_constitutions()
    prompt = load_prompt()

    assert _missing_constitution_labels(prompt, constitutions) == []
    injected = constitutions + [{"id": "blood_deficiency", "label": "血虚质"}]
    assert _missing_constitution_labels(prompt, injected) == ["血虚质"]


def test_coverage_ignores_mentions_outside_direction_list() -> None:
    """提要之外的提及不算数 —— 防「示例里的体质名把缺口盖住」。

    示例段的输入里写着「体质：痰湿质」。若守卫图省事扫全文，
    痰湿质这一型即使从提要里被删掉也测不出来。
    """
    constitutions = [
        {"id": "balanced", "label": "平和质"},
        {"id": "qi_deficiency", "label": "气虚质"},
        {"id": "phlegm_damp", "label": "痰湿质"},
    ]
    text = "    - 平和质：随餐调整即可\n    - 气虚质：健脾益气方向\n体质：痰湿质\n"
    assert _missing_constitution_labels(text, constitutions) == ["痰湿质"]


# ============================================================
# 缺口 2：示例的冲泡方式必须与标记一致
# ============================================================
def test_prompt_examples_brew_matches_cook_requirement() -> None:
    """示例里出现须煎煮的饮片时，冲泡方式必须是煎煮；并保证两种范式都有。

    正向断言（须煎煮 ⇒ 煎煮）是硬条件；反向不写成「不必煎煮 ⇒ 不可煎煮」——
    甘草这类「可先煮 5 分钟」的饮片煮着喝并不算错，那样写会误伤。
    另外要求**至少各有一个**焖泡示例与煎煮示例：只留一种，就等于没教出区分。
    """
    examples = _prompt_examples()
    assert len(examples) >= 2, "示例不足 2 个，教不出「焖泡 / 煎煮」的区分"

    by_name = {item["name"]: item for item in load_herb_catalog().values()}
    cook_style_flags: list[bool] = []

    for ex in examples:
        for rec in ex["recommendations"]:
            cook_style_flags.append(_brew_is_cook(rec["brew"]))
            need = [
                h["name"]
                for h in rec["herbs"]
                if herb_requires_cooking(by_name.get(h["name"], {}))
            ]
            if not need:
                continue
            brew = rec["brew"]
            assert _brew_is_cook(brew), (
                f"示例「{rec['title']}」含须煎煮的 {'、'.join(need)}，"
                f"却写的是 {brew['vessel']} 焖 {brew['steep_min']} 分钟 —— "
                "提示词在教反例，模型会照抄"
            )

    assert any(cook_style_flags), "没有任何煎煮示例 —— 模型见不到正面范式"
    assert not all(cook_style_flags), "所有示例都是煎煮 —— 模型会以为焖泡不可用"


def _prompt_examples() -> list[dict]:
    out: list[dict] = []
    for m in EXAMPLE_JSON_RE.finditer(load_prompt()):
        out.append(json.loads(m.group(0)))
    return out


def test_prompt_late_add_herbs_are_not_cook_required() -> None:
    """提示词点名的「后下」饮片，必须真的都是不必煎煮的那些。

    两类标记互斥：一味饮片不可能既「须煮透才出味」又「久煮尽失」。
    这条守的是提示词文字与数据脱钩 —— 改了名单忘了改数据（或反过来）。
    """
    m = LATE_ADD_RE.search(load_prompt())
    assert m, "提示词里找不到「香气类饮片（…）」名单 —— 改了措辞请同步更新本测试"

    names = [n.strip() for n in m.group(1).split("、") if n.strip()]
    assert len(names) >= 5, f"后下名单只有 {names}，疑似漏写"

    whitelist = herb_whitelist_names()
    by_name = {item["name"]: item for item in load_herb_catalog().values()}
    for name in names:
        assert name in whitelist, f"{name} 不在饮片白名单里"
        assert not herb_requires_cooking(by_name[name]), (
            f"{name} 被提示词列为「后下、不要久煮」，却标了 requires_cooking —— 自相矛盾"
        )


# ============================================================
# 缺口 2：候选清单只给须煎煮的饮片加提示
# ============================================================
def test_candidate_lines_only_mark_cook_required() -> None:
    """候选清单里只有标了须煎煮的饮片带提示，其余渲染不变。

    按**标记**判定而不是写死名字：写死名字的话，哪天某味饮片的标记被去掉，
    测试仍会因为名字还在清单里而通过（静默失效）。
    """
    by_name = {item["name"]: item for item in load_herb_catalog().values()}
    hinted: set[str] = set()
    plain: set[str] = set()

    for constitution in Constitution:
        for line in _candidate_lines(constitution, limit=999).splitlines():
            name = line.split("（", 1)[0].removeprefix("- ").strip()
            (hinted if "⚠️ 须煎煮" in line else plain).add(name)

    assert hinted, "候选清单里一条须煎煮提示都没有 —— 标记没接到渲染上"
    overlap = hinted & plain
    assert not overlap, f"这些饮片在不同体质下提示不一致：{sorted(overlap)}"
    for name in hinted:
        assert herb_requires_cooking(by_name[name]), f"{name} 带了提示却没有标记"
    for name in plain:
        assert not herb_requires_cooking(by_name[name]), f"{name} 有标记却没带提示"


# ============================================================
# 缺口 3：第 3 条不得教「寒热对冲」（口径⑨）
# ============================================================
# 旧文案里的这两句就是被否掉的方向。它们作为**字串**出现在守卫里，
# 是为了负控制能把旧文案塞回去验证守卫会变红。
HEDGE_WORDS: tuple[str, ...] = ("配清凉的", "配温性的")

OLD_ITEM_3 = "3. **寒热要平衡**：吃了燥热的，配清凉的；吃了生冷的，配温性的。\n"


def _numbered_items(text: str, number: int) -> list[str]:
    """取出**所有**编号为 N 的条目（含续行）。

    为什么是复数：提示词里有**两组**编号列表（硬规则 1–8、搭配原则 1–6），
    取「第一个 N.」会拿到硬规则那一组，判据就守错了对象（实测踩到）。

    **只认行首的 `N. `**，不全文扫 —— 全文扫会被示例段里偶然出现的同义词蒙混
    （与缺口 1「示例里的体质名把提要缺口盖住」是同一个形状）。
    """
    out: list[str] = []
    for part in re.split(r"(?m)^(?=\s*\d+\.\s)", text):
        m = re.match(r"\s*(\d+)\.\s", part)
        if m and int(m.group(1)) == number:
            out.append(part)
    return out


def _item3_violations(prompt_text: str) -> list[str]:
    """纯函数：正向测试与负控制**共用同一份判定**。"""
    items = _numbered_items(prompt_text, 3)
    if not items:
        return ["提示词里找不到第 3 条 —— 改了编号请同步更新本测试"]

    bad: list[str] = []
    for item in items:
        bad.extend(
            f"第 3 条仍写着「{word}」——那是被口径⑨否掉的寒热对冲"
            for word in HEDGE_WORDS
            if word in item
        )
    if not any("signals.conflict" in item for item in items):
        bad.append(
            "两条编号列表的第 3 条里都没有 parsed.signals.conflict "
            "—— 模型无从知道这一餐寒热错杂"
        )
    # 正面锚点：只禁不禁不行——删成一句废话也能「不含禁用词」。
    if not any("护脾胃" in item for item in items):
        bad.append("第 3 条没有给出正面方向（护脾胃）—— 口径⑨是「不对冲 + 护脾胃」两件事")
    return bad


def test_item3_forbids_hedging_and_names_signals() -> None:
    assert _item3_violations(load_prompt()) == [], (
        "agent2_system.md 第 3 条与已定口径⑨矛盾：方向是「不对冲、以护脾胃为准」"
    )


def test_item3_guard_negative_control() -> None:
    """旧文案塞回去必须变红 —— 否则上一条是恒真断言。"""
    prompt = load_prompt()
    assert _item3_violations(prompt) == []

    # 锁定「搭配原则」里那一条（提到 signals.conflict 的），塞回旧文案。
    target = next(i for i in _numbered_items(prompt, 3) if "signals.conflict" in i)
    reverted = prompt.replace(target, OLD_ITEM_3)
    assert reverted != prompt, "替换没生效，负控制形同虚设"
    assert _item3_violations(reverted), "改回旧文案后守卫没变红 —— 判据恒真"
