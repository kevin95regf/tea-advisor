"""food_lookup 的单元测试。

这一层把"模型凭语感猜属性"变成"查表照抄"，是属性准确率的根基，
所以表能否加载、匹配是否准确、渲染是否包含关键信息，都必须有测试护着。
"""

from __future__ import annotations

from app.services.food_lookup import (
    load_food_table,
    match_foods,
    names_match,
    render_nature_change_rules,
    render_reference,
    resolve_temperature_fields,
    table_stats,
)


def find(entries: list[dict], name: str) -> list[dict]:
    """按"指同一物"的宽松规则查找条目。

    表里条目名是规范名（如「面条」），用户口述可能是更具体的说法（如「兰州拉面」），
    两者应视为命中。参见 names_match 的说明。
    """
    return [e for e in entries if names_match(name, e["name"])]


# ============================================================
# 表能否加载
# ============================================================
def test_table_loads() -> None:
    table = load_food_table()
    assert table, "food_properties.json 未加载"


def test_table_has_enough_entries() -> None:
    stats = table_stats()
    assert stats["foods"] >= 80, f"食材条数偏少：{stats['foods']}"
    assert stats["tea_drinks"] >= 10, f"茶饮条数偏少：{stats['tea_drinks']}"


def test_every_entry_has_required_fields() -> None:
    table = load_food_table()
    entries = list(table.get("foods", [])) + list(table.get("tea_drinks", {}).get("items", []))
    assert entries
    for e in entries:
        assert e.get("name"), f"{e.get('id')} 缺 name"
        assert e.get("nature"), f"{e.get('name')} 缺 nature"
        assert isinstance(e.get("flavors"), list), f"{e.get('name')} 缺 flavors"


def test_nature_values_are_valid_enum() -> None:
    from app.domain.enums import Nature

    valid = {n.value for n in Nature}
    table = load_food_table()
    entries = list(table.get("foods", [])) + list(table.get("tea_drinks", {}).get("items", []))
    bad = [e["name"] for e in entries if e.get("nature") not in valid]
    assert not bad, f"非法 nature 值: {bad}"


def test_variant_nature_values_are_valid() -> None:
    from app.domain.enums import Nature

    valid = {n.value for n in Nature}
    table = load_food_table()
    entries = list(table.get("foods", [])) + list(table.get("tea_drinks", {}).get("items", []))
    for e in entries:
        for cooking, nat in (e.get("variant_nature") or {}).items():
            assert nat in valid, f"{e['name']} 的 variant_nature[{cooking}]={nat} 非法"


def test_no_duplicate_names() -> None:
    table = load_food_table()
    names = [e["name"] for e in table.get("foods", [])]
    names += [e["name"] for e in table.get("tea_drinks", {}).get("items", [])]
    dupes = {n for n in names if names.count(n) > 1}
    assert not dupes, f"重复条目: {dupes}"


# ============================================================
# 匹配准确性（本次修复的核心场景）
# ============================================================
def test_jasmine_tea_is_matched() -> None:
    """用户实测反馈的案例：茉莉花茶此前判错属性。"""
    matched = match_foods("下午喝了杯茉莉花茶")
    hit = find(matched, "茉莉花茶")
    assert hit, f"未匹配到茉莉花茶: {[e['name'] for e in matched]}"
    assert hit[0]["nature"] == "warm", "茉莉花茶应为温性"


def test_warm_tea_drinks_not_marked_cool() -> None:
    """几种容易被误判为寒凉的温性茶饮。"""
    for text, name in [
        ("喝了杯茉莉花茶", "茉莉花茶"),
        ("喝了玫瑰花茶", "玫瑰花茶"),
        ("喝了杯红茶", "红茶"),
        ("喝了陈皮水", "陈皮茶"),
        ("喝了杯姜茶", "姜茶"),
    ]:
        matched = match_foods(text)
        hit = find(matched, name)
        assert hit, f"{text} 未匹配到 {name}，匹配结果 {[e['name'] for e in matched]}"
        assert hit[0]["nature"] == "warm", f"{name} 应为温性，实际 {hit[0]['nature']}"


def test_cool_tea_drinks_are_cool() -> None:
    for text, name in [
        ("喝了菊花茶", "菊花茶"),
        ("喝了绿茶", "绿茶"),
        ("喝了决明子茶", "决明子茶"),
        ("喝了罗汉果茶", "罗汉果茶"),
    ]:
        matched = match_foods(text)
        hit = find(matched, name)
        assert hit, f"{text} 未匹配到 {name}"
        assert hit[0]["nature"] in ("cool", "cold"), f"{name} 应为凉/寒，实际 {hit[0]['nature']}"


def test_neutral_foods_stay_neutral() -> None:
    """实测发现模型有系统性偏温倾向，这些平性食材必须查到 neutral。"""
    for text, name in [
        ("吃了小笼包", "小笼包"),
        ("吃了碗兰州拉面", "拉面"),
        ("喝了豆浆", "豆浆"),
        ("吃了碗银耳莲子羹", "银耳"),
        ("吃了清蒸鲈鱼", "鲈鱼"),
    ]:
        matched = match_foods(text)
        hit = find(matched, name)
        assert hit, f"{text} 未匹配到 {name}，匹配结果 {[e['name'] for e in matched]}"
        assert hit[0]["nature"] == "neutral", f"{name} 应为平性，实际 {hit[0]['nature']}"


def test_rice_and_porridge_are_neutral() -> None:
    for text, name in [("吃了白米饭", "米饭"), ("喝了碗白粥", "白粥"), ("吃了馒头", "馒头")]:
        hit = find(match_foods(text), name)
        assert hit, f"{text} 未匹配到 {name}"
        assert hit[0]["nature"] == "neutral", f"{name} 应为平性"


def test_names_match_tolerates_specific_wording() -> None:
    """用户口述更具体（或更简略）时的名称对齐。"""
    # 一方是另一方子串
    assert names_match("兰州拉面", "拉面")
    assert names_match("冰美式咖啡", "冰美式")
    assert names_match("清蒸鲈鱼", "鲈鱼")
    # 规范化后一方含另一方
    assert names_match("白米饭", "米饭")
    # 前两字相同的近似说法（"奶茶" vs "珍珠奶茶"由子串规则覆盖）
    assert names_match("龙眼", "龙眼肉")
    # 别名与关键词也会被认作同一物："拉面"是「面条」条目的关键词
    assert names_match("拉面", "面条")
    assert names_match("兰州拉面", "面条")
    assert names_match("大米饭", "米饭")
    # 不应误判
    assert not names_match("苹果", "香蕉")
    assert not names_match("", "米饭")
    assert not names_match("米饭", "")


def test_cold_fruits() -> None:
    hit = find(match_foods("吃了根香蕉"), "香蕉")
    assert hit and hit[0]["nature"] == "cold"


def test_longer_keyword_wins_over_shorter() -> None:
    """「麻辣香锅」比「麻辣」更具体，应排在前面。"""
    matched = match_foods("晚上吃了麻辣香锅")
    assert matched, "未匹配任何条目"
    assert matched[0]["name"] == "麻辣香锅", f"排序错误，首位是 {matched[0]['name']}"


def test_no_match_returns_empty() -> None:
    assert match_foods("今天天气不错心情很好") == []


def test_empty_input_returns_empty() -> None:
    assert match_foods("") == []


def test_match_respects_limit() -> None:
    text = "吃了米饭 面条 馒头 小笼包 饺子 包子 豆浆 牛奶 豆腐 苹果 香蕉 橘子 西瓜 葡萄 梨"
    assert len(match_foods(text, limit=5)) <= 5


# ============================================================
# 渲染
# ============================================================
def test_render_reference_includes_nature_and_note() -> None:
    out = render_reference("下午喝了杯茉莉花茶")
    assert "茉莉花茶" in out
    assert "温" in out, "渲染结果应含中文属性标签"
    assert "说明" in out, "茶饮条目应带上说明"


def test_render_reference_includes_variant_hint() -> None:
    """带 variant_nature 的条目应渲染出处理方式带来的变化。

    样本用规范名「鸡肉」，**故意不用「炸鸡」**：表里已有独立的 `zhaji` 条目
    （炸鸡，热，咸/辛）。「炸鸡」原是 `jirou` 上的别名——属 ④-1 别名污染
    （把不属于自己的名字挂在条目上），2026-09-17 已删除。若继续拿「炸鸡」当样本，
    命中的会是 `zhaji`，而它没有 `variant_nature`，这条测试就会静默失效。
    """
    out = render_reference("吃了鸡肉")
    assert "鸡肉" in out
    assert "油炸" in out, f"应提示油炸后的属性变化，实际：{out}"


def test_fried_chicken_resolves_to_its_own_entry() -> None:
    """④-1 别名污染已修的守卫：`炸鸡` 取自身条目的值，不再借 `鸡肉`。

    删别名之前，「炸鸡」会被 `jirou` 的 aliases+keywords 命中，渲染成
    「鸡肉：温，甘」+「（油炸→热）」。删掉之后必须命中 `zhaji`（热，咸/辛），
    且**不能**再带出 `jirou` 的处理方式提示 —— 否则说明别名又被挂回去了。
    """
    out = render_reference("吃了炸鸡")
    assert "炸鸡" in out
    assert "热" in out, f"炸鸡应取自身条目（热，咸/辛），实际：{out}"
    assert "油炸" not in out, f"炸鸡不应再渲染「鸡肉」的变体提示（别名污染回归）：{out}"


def test_render_reference_empty_when_no_match() -> None:
    assert render_reference("今天心情不错") == ""


def test_render_nature_change_rules() -> None:
    rules = render_nature_change_rules()
    assert "冰镇" in rules
    assert "油炸" in rules
    assert "清蒸" in rules


def test_reference_text_is_compact() -> None:
    """参考表只注入命中的条目，不应该把整表塞进提示词。"""
    one = render_reference("喝了茉莉花茶")
    many = render_reference("喝了茉莉花茶 菊花茶 绿茶 红茶 普洱 姜茶 红枣茶 陈皮茶 荷叶茶 罗汉果茶 决明子茶 乌梅茶")
    assert len(one) < 400, f"单条参考表过长：{len(one)}"
    assert len(many) < 3000, f"多条参考表过长：{len(many)}"


# ============================================================
# 5. `note` 是运行时字段：写文案不能踩到温度前缀
# ============================================================
def test_jiangyou_note_has_no_temperature_side_effect() -> None:
    """给 `note` 写文案时必须避开温度前缀 —— 它不是注释，是**运行时字段**。

    `resolve_temperature_fields(name, note)` 会**同时扫 name 与 note**，命中
    `CHILL_PREFIXES`（冰 / 加冰 / 冷藏 / 冷冻 / 冻…）或 `HEAT_PREFIXES`
    （热 / 烫 / 加热 / 温热…）就给四气 **±1**。全表实测有 4 条命中，其中
    `suannai_wan`（酸奶碗）正是**从 note 命中**的（note 写了「冷藏」）。

    A2 ① 给 `jiangyou` 补的 note 写「…《本草纲目》9948 记辛、温。…」—— 「辛、温」不含
    「温热」「热」，所以**不该产生任何温度信号**。这条防的是哪天有人把文案改成
    「古籍记其性温热」之类，把「平」悄悄推到「温」（数据会显示成有依据的改动）。

    注意：它守的是「**没有副作用**」，不是「note 写了某句特定的话」—— 后者是快照断言，
    改一次文案就红一次。
    """
    table = load_food_table()
    entries = list(table.get("foods", [])) + list(table.get("tea_drinks", {}).get("items", []))
    entry = next((e for e in entries if e.get("id") == "jiangyou"), None)
    assert entry is not None, "表里找不到酱油条目（jiangyou）"
    note = (entry.get("note") or "").strip()
    assert note, "A2 ① 要求酱油有 note 留痕（否则核验单 §4.2 的「一律加 note」是假陈述）"
    assert resolve_temperature_fields(entry.get("name") or "", note) is None, (
        f"酱油的 note 踩到温度前缀，会悄悄改它的四气：{note!r}"
    )
