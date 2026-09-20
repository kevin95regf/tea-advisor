"""阶段 2 ③：提示词的两段结构 / 只给一条，与 plan 的装配接线。

范式＝**钉结构 + 变异检验**。

⚠️ 已踩 3 次的坑：**关键词型判据会被文案蒙混**。所以这里
- 按**行首编号**切条目（`_numbered_items`），不全文扫；
- 断言的是**字段路径**（`parsed.plan` / `plan.deferred` / `plan.second_note`），不是中文措辞；
- 每条判据都配**负控制**：把改动撤回去，守卫必须变红。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from app.agents.agent2_recommend import build_user_prompt
from app.domain.diet_signals import build_meal_signals, derive_meal_plan
from app.domain.enums import Constitution
from app.domain.models import ParsedFood, ParsedMeal
from app.services.food_lookup import match_foods, resolve_in_context

# tests/ 的 parents[1] 是 core/，parents[2] 是仓库根（接线路径里带着 core/ 前缀）
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROMPT_PATH = PROJECT_ROOT / "core" / "app" / "agents" / "prompts" / "agent2_system.md"

PLAN_SECTION_HEADING = "## 本次优先级（代码已判定，须遵守）"

# 样本：湿气餐（damp=3、无场景关键词）⇒ 会被方向接管；
# 冲突餐（conflict=True）⇒ 方向关闭、note 是冲突说明。
DAMP_CASE = "下午茶一块蛋糕和一杯奶茶"
CONFLICT_CASE = "中午吃了麻辣烫配冰可乐"


def load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _numbered_items(text: str, number: int) -> list[str]:
    """取出**所有**编号为 N 的条目（含续行）。

    提示词里有**两组**编号列表（硬规则 1–8、推荐逻辑 1–7），
    取「第一个 N.」会拿到硬规则那一组，判据就守错了对象（实测踩到过）。
    """
    out: list[str] = []
    for part in re.split(r"(?m)^(?=\s*\d+\.\s)", text):
        m = re.match(r"\s*(\d+)\.\s", part)
        if m and int(m.group(1)) == number:
            out.append(part)
    return out


def _parsed(text: str, constitution: Constitution = Constitution.BALANCED) -> ParsedMeal:
    foods: list[ParsedFood] = []
    for entry in match_foods(text):
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        resolved = resolve_in_context(text, entry)
        foods.append(ParsedFood(name=name, nature=resolved.nature, flavors=resolved.flavors))
    parsed = ParsedMeal(foods=foods, summary=text)
    parsed.signals = build_meal_signals(text, foods)
    parsed.plan = derive_meal_plan(parsed.signals, constitution.value)
    return parsed


# ---------------------------------------------------------------
# 1. 第 1 条必须指向代码派生的 plan（不只是「自己看 signals」）
# ---------------------------------------------------------------
def _item1_violations(prompt_text: str) -> list[str]:
    items = _numbered_items(prompt_text, 1)
    if not items:
        return ["提示词里找不到第 1 条 —— 改了编号请同步更新本测试"]
    bad: list[str] = []
    if not any("parsed.plan" in item for item in items):
        bad.append("第 1 条没有指向 parsed.plan —— 模型会自己另判一套优先级")
    if not any("plan.first" in item for item in items):
        bad.append("第 1 条没说 plan.first（本餐先做的方向）")
    if not any("plan.note" in item for item in items):
        bad.append("第 1 条没说 plan.note（如实写进说明）")
    return bad


def test_item1_names_code_derived_plan() -> None:
    assert _item1_violations(load_prompt()) == []


def test_item1_guard_negative_control() -> None:
    prompt = load_prompt()
    assert _item1_violations(prompt) == []

    target = next(i for i in _numbered_items(prompt, 1) if "parsed.plan" in i)
    # 退回阶段 1 的写法：只说「看这一餐的问题在哪」，不提 plan
    reverted = prompt.replace(
        target, "1. **先看这一餐的问题在哪**：油腻 → 消食化积方向；生冷 → 温中散寒方向。\n"
    )
    assert reverted != prompt, "替换没生效，负控制形同虚设"
    assert _item1_violations(reverted), "退回旧写法后守卫没变红 —— 判据恒真"


# ---------------------------------------------------------------
# 2. 第 7 条：只给一条 + 推迟话术照写
# ---------------------------------------------------------------
def _item7_violations(prompt_text: str) -> list[str]:
    items = _numbered_items(prompt_text, 7)
    if not items:
        return ["提示词里找不到第 7 条 —— 「只给一条推荐」这条纪律没有落点"]
    bad: list[str] = []
    # 硬规则那一组也有第 7 条 ⇒ 只认提到 plan 的那一组
    plan_items = [i for i in items if "plan." in i]
    if not plan_items:
        bad.append("第 7 条里没有一条指向 parsed.plan —— 守错了对象（硬规则也有第 7 条）")
        return bad
    for item in plan_items:
        if "plan.deferred" not in item:
            bad.append("第 7 条没说 plan.deferred —— 模型不知道第二段要推迟")
        if "plan.second_note" not in item:
            bad.append("第 7 条没说 plan.second_note —— 推迟话术会被模型自己编")
        if not ("只给" in item or "1 条" in item or "只输出 1 条" in item):
            bad.append("第 7 条没写死「只给一条」—— 两组搭配的剂量叠加没人守")
    return bad


def test_item7_forbids_two_blends() -> None:
    assert _item7_violations(load_prompt()) == []


def test_item7_guard_negative_control() -> None:
    prompt = load_prompt()
    assert _item7_violations(prompt) == []

    target = next(i for i in _numbered_items(prompt, 7) if "plan." in i)
    assert _item7_violations(prompt.replace(target, "")), "删掉第 7 条后守卫没变红"


# ---------------------------------------------------------------
# 3. build_user_prompt 的「本次优先级」节
# ---------------------------------------------------------------
def test_prompt_has_priority_section_when_plan_present() -> None:
    parsed = _parsed(DAMP_CASE)
    assert parsed.plan is not None and parsed.plan.first is not None
    prompt = build_user_prompt(parsed, Constitution.BALANCED)

    assert PLAN_SECTION_HEADING in prompt, "提示词里没有「本次优先级」节"
    section = prompt.split(PLAN_SECTION_HEADING, 1)[1]
    # 可用饮片与克数必须明写出来，不能指望模型自己从 parsed JSON 里翻
    for name in parsed.plan.first.herbs:
        assert name in section, f"优先级节里没写可用饮片 {name}"
    assert parsed.plan.second_note in section


def test_priority_section_tells_when_direction_closed() -> None:
    """方向关闭（冲突餐）时也得有节，且必须带上如实说明。"""
    parsed = _parsed(CONFLICT_CASE)
    assert parsed.plan is not None and parsed.plan.note
    section = build_user_prompt(parsed, Constitution.BALANCED).split(
        PLAN_SECTION_HEADING, 1
    )[1]
    assert parsed.plan.note in section, "关闭/冲突说明没写进提示词 —— 只留痕在数据里等于没说"


def test_priority_section_degrades_explicitly_without_plan() -> None:
    """plan 为 None 时给一句明确的放行说明，不静默留空。"""
    parsed = _parsed(DAMP_CASE)
    parsed.plan = None
    section = build_user_prompt(parsed, Constitution.BALANCED).split(
        PLAN_SECTION_HEADING, 1
    )[1]
    assert "没有方向接管" in section
    assert section.strip(), "plan 缺失时该节不能是空的"


def test_priority_section_negative_control() -> None:
    """变异检验：把这节拿掉 ⇒ 断言必须变红（证明不是在别处蒙混）。"""
    import app.agents.agent2_recommend as mod

    parsed = _parsed(DAMP_CASE)
    assert parsed.plan is not None and parsed.plan.first is not None
    original = mod._plan_lines
    try:
        mod._plan_lines = lambda parsed: ""  # type: ignore[assignment]
        prompt = build_user_prompt(parsed, Constitution.BALANCED)
        assert PLAN_SECTION_HEADING in prompt, "节标题还在（那是常量，不算判据）"
        body = prompt.split(PLAN_SECTION_HEADING, 1)[1]
        # 节被清空后，本来该写在这里的可用饮片与推迟话术都必须消失
        for name in parsed.plan.first.herbs:
            assert name not in body, f"节被清空后仍能读到 {name} —— 判据恒真"
        assert parsed.plan.second_note not in body
    finally:
        mod._plan_lines = original  # type: ignore[assignment]


# ---------------------------------------------------------------
# 4. 装配接线（core 两条链路）+ 变异检验
# ---------------------------------------------------------------
def _plan_wired(source: str, func_name: str) -> bool:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != func_name:
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Assign):
                continue
            func = sub.value.func if isinstance(sub.value, ast.Call) else None
            if not isinstance(func, ast.Name) or func.id != "derive_meal_plan":
                continue
            for target in sub.targets:
                if (
                    isinstance(target, ast.Attribute)
                    and target.attr == "plan"
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "parsed"
                ):
                    return True
    return False


@pytest.mark.parametrize(
    "rel_path,func_name",
    [
        ("core/app/services/orchestrator.py", "analyze"),
        ("core/app/api/analyze_offline.py", "analyze_offline_endpoint"),
    ],
)
def test_core_paths_are_wired(rel_path: str, func_name: str) -> None:
    path = PROJECT_ROOT / rel_path
    assert path.is_file(), f"接线目标文件不存在：{rel_path}"
    source = path.read_text(encoding="utf-8")
    assert _plan_wired(source, func_name), f"{rel_path}::{func_name} 未装配 parsed.plan"

    # 变异检验：把函数改个名字（语法仍合法，但判据认不出来）。
    # ⚠️ 不能用「注释掉赋值开头」的写法：装配是多行调用，注释掉首行会让续行
    #   变成 IndentationError，ast.parse 直接抛异常——那不是「判据变红」，是测试自己炸了。
    mutated = source.replace("derive_meal_plan", "derive_meal_plan_disabled")
    assert mutated != source, "替换没生效，变异检验形同虚设"
    assert not _plan_wired(mutated, func_name)


# ---------------------------------------------------------------
# 5. 跨路径一致：提示词写出的 plan == 纯函数派生的 plan
# ---------------------------------------------------------------
@pytest.mark.parametrize("constitution", list(Constitution))
def test_prompt_plan_matches_derived_plan(constitution: Constitution) -> None:
    parsed = _parsed(DAMP_CASE, constitution)
    direct = derive_meal_plan(parsed.signals, constitution.value)
    assert parsed.plan == direct, "装配进 parsed 的 plan 与直接派生的不一致 ⇒ 两处实现"

    if parsed.plan is not None and parsed.plan.first is not None:
        section = build_user_prompt(parsed, constitution).split(PLAN_SECTION_HEADING, 1)[1]
        assert [n for n in parsed.plan.first.herbs if n in section] == parsed.plan.first.herbs
