"""离线路径的温度词归属（E15）。

背景
----
`analyze_offline.py` 曾写 `resolve_food(name=条目名, note=整句口述)`，
把整句口述当"备注"喂给每一样食物。备注通道会在**任意位置**找温度词
（只要备注去空格后 ≤ NOTE_MAX_LEN=10 字），于是两个后果同时发生：

  1. 温度串味：「炸鸡 冰可乐」里的「冰」被算在炸鸡头上；
  2. 条目错认：备注通道剥掉温度词后剩下的名字是「炸鸡可乐」，
     拿它去查表命中的是**可乐**条目 —— 炸鸡被按可乐算成寒。

实测「炸鸡 冰可乐」的旧结果是 `炸鸡=寒 / 可乐=寒`（表值是 热 / 凉）。
注意这是"越短的输入越错"：长句因为超过 10 字，反而不走备注通道。

修法是**温度词按位置归属**：每样食物只认领紧贴自己命中词之前的温度词
（`food_lookup.resolve_in_context`），判定层 `resolve_food` 与备注通道本身不动
（Agent1 路径还在用它们）。

本文件锁住三件事，全部走真实接口、不 mock 判定层：
  1. **派生不变式**：整句判定的每个结果，必须等于把该食物单独判定的结果；
     且判出来的四性只可能在表值上下浮动一档。
  2. **温度词不得越界**：不能从别的已识别食物名里切出来（「麻辣烫」的「烫」），
     也不能从没识别到的食物名里漏出来（「果冻」的「冻」），还不能叠两次。
  3. **负控制（变异检验，内存改副本、不落盘）**：把保护关掉或换回旧口径，
     上述断言必须变红 —— 否则这些用例可能恒真。
"""

from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.domain.enums import Nature
from app.domain.nature_math import nature_to_num, shift_nature
from app.main import app
from app.services import food_lookup
from app.services.food_lookup import _find_entry, resolve_food, resolve_in_context

client = TestClient(app)


# ============================================================
# 取数与派生工具
# ============================================================
@lru_cache(maxsize=None)
def _natures(text: str) -> dict[str, str]:
    """走真实离线接口，返回「食物名 → 四性」。同一条口述只请求一次。"""
    response = client.post(
        "/api/analyze-offline",
        json={"text": text, "constitution_override": "balanced"},
    )
    assert response.status_code == 200, response.text
    foods = response.json()["parsed"]["foods"]
    assert foods, f"{text!r} 没认出任何食物，用例会退化成空跑"
    return {food["name"]: food["nature"] for food in foods}


def _entry(name: str) -> dict:
    entry, _, _ = _find_entry(name)
    assert entry is not None, f"{name!r} 不在食性表内，用例前提不成立"
    return entry


def _table_nature(name: str) -> str:
    return _entry(name)["nature"]


def _expected(name: str, delta: int) -> str:
    """派生期望值：表值叠加该食物认领到的温度增量。"""
    shifted = shift_nature(_table_nature(name), delta)
    assert shifted is not None, f"{name!r} 的表值无法参与温度修正"
    return shifted.value


# ============================================================
# 1. 温度词归它紧挨着的那一样食物
# ============================================================
ATTRIBUTION_CASES: tuple[tuple[str, str, int], ...] = (
    ("炸鸡 冰可乐", "炸鸡", 0),
    ("炸鸡 冰可乐", "可乐", -1),
    ("火锅 冰可乐", "火锅", 0),
    ("火锅 冰可乐", "可乐", -1),
    ("炸鸡 冰啤酒", "炸鸡", 0),
    ("炸鸡 冰啤酒", "啤酒", -1),
    ("烤串 冰啤酒", "烧烤", 0),
    ("烤串 冰啤酒", "啤酒", -1),
    ("冰可乐", "可乐", -1),
    ("热牛奶", "牛奶", 1),
    ("面条配冰镇啤酒", "面条", 0),
    ("面条配冰镇啤酒", "啤酒", -1),
    ("火锅 冰镇酸梅汤", "火锅", 0),
    ("火锅 冰镇酸梅汤", "酸梅汤", -1),
    ("今天中午吃了炸鸡和冰可乐", "炸鸡", 0),
    ("今天中午吃了炸鸡和冰可乐", "可乐", -1),
    ("炸鸡冰可乐", "炸鸡", 0),
    ("炸鸡冰可乐", "可乐", -1),
    ("羊肉 苦瓜", "羊肉", 0),
    ("羊肉 苦瓜", "苦瓜", 0),
)


@pytest.mark.parametrize("text, food, delta", ATTRIBUTION_CASES)
def test_temperature_belongs_to_the_food_it_sits_next_to(text, food, delta):
    assert len(ATTRIBUTION_CASES) >= 20, "样本太少，断言可能恒真"
    assert _natures(text)[food] == _expected(food, delta)


def test_short_and_long_wording_agree():
    """口述长短不该改变判定。

    旧口径下这是**错的**：短句走备注通道 ⇒ 串味；长句超过 10 字不走 ⇒ 正常。
    同一餐"说长说短"给出不同四性，是这个 bug 最直接的指纹。
    """
    short = _natures("炸鸡 冰可乐")
    long_ = _natures("今天中午吃了炸鸡和冰可乐")
    for name in ("炸鸡", "可乐"):
        assert short[name] == long_[name]


def test_whole_sentence_equals_judging_each_food_alone():
    """派生不变式：整句判定的结果 == 把每样食物拆开单独判定。

    两条路径（整句 / 单词）走的是同一套判定层，只是语境不同；
    如果温度词越界，两边必然对不上。
    """
    cases = (
        ("炸鸡 冰可乐", ("炸鸡", "冰可乐")),
        ("面条配冰镇啤酒", ("面条", "冰镇啤酒")),
        ("火锅 冰镇酸梅汤", ("火锅", "冰镇酸梅汤")),
    )
    checked = 0
    for whole, parts in cases:
        whole_map = _natures(whole)
        for part in parts:
            for name, nature in _natures(part).items():
                assert name in whole_map, f"{name!r} 单判有、整句判却没有"
                assert whole_map[name] == nature, (
                    f"{whole!r} 里 {name} 判成 {whole_map[name]}，"
                    f"单独判却是 {nature}"
                )
                checked += 1
    assert checked >= 6, "样本太少，断言可能恒真"


# ============================================================
# 2. 温度词不得越界
# ============================================================
NO_LEAK_CASES: tuple[tuple[str, str, int], ...] = (
    # 「烫」是麻辣烫的末字，不是给可乐升温的指令
    ("麻辣烫 可乐", "可乐", 0),
    ("麻辣烫冰可乐", "可乐", -1),
    # 没识别到的食物，其名字尾部的温度字同样不许外溢
    ("果冻 可乐", "可乐", 0),
    ("刨冰 可乐", "可乐", 0),
    ("冰淇淋 可乐", "可乐", 0),
    ("甜点 冰可乐", "可乐", -1),
)


@pytest.mark.parametrize("text, food, delta", NO_LEAK_CASES)
def test_temperature_never_leaks_from_another_food(text, food, delta):
    assert len(NO_LEAK_CASES) >= 6, "样本太少，断言可能恒真"
    assert _natures(text)[food] == _expected(food, delta)


def test_ice_ends_up_on_the_iced_entry_not_on_its_base_entry():
    """「冰奶茶」同时命中「冰奶茶」与「奶茶」两个条目（既有重复命中问题）。

    温度词归**名字里带冰**的那一条；基础条目报它自己的表值，不继承。
    这是归属规则的直接后果，不是回归——餐里的寒凉信号由「冰奶茶」承担。
    """
    meal = _natures("冰奶茶")
    assert meal["冰奶茶"] == _table_nature("冰奶茶")
    assert meal["奶茶"] == _table_nature("奶茶")


def test_prefix_already_inside_the_entry_name_is_not_counted_twice():
    """「冰奶茶」的「冰」已在规范名里；再叠一次会变成寒（多算一档）。"""
    assert _natures("冰 冰奶茶")["冰奶茶"] == _table_nature("冰奶茶")
    assert resolve_food(name="冰冰奶茶").nature == Nature.COLD.value
    assert _table_nature("冰奶茶") != Nature.COLD.value


def test_offline_path_no_longer_feeds_the_sentence_as_note():
    """钉结构：离线路径不许退回"整句当备注"的写法。

    用 AST 查调用点而不是查字符串——注释里出现 `note=text` 只是说明，
    真正要拦的是 `resolve_food(..., note=...)` 这个调用形状。
    """
    source = (
        Path(__file__).resolve().parents[1] / "app" / "api" / "analyze_offline.py"
    ).read_text(encoding="utf-8")
    assert "resolve_in_context" in source

    offenders: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", None) != "resolve_food":
            continue
        # 关键字形式 note=… 与位置形式（第 5 个位置参数就是 note）都算
        passed_note = any(keyword.arg == "note" for keyword in node.keywords)
        passed_note = passed_note or len(node.args) >= 5
        if passed_note:
            offenders.append(node.lineno)
    assert not offenders, f"离线路径又用 resolve_food(note=…) 了：第 {offenders} 行"


# ============================================================
# 3. 负控制：关掉保护，断言必须变红
# ============================================================
def test_old_call_shape_reproduces_the_bug():
    """负控制之一：旧的调用形状真的会把炸鸡判成寒。

    这条证明上面那些断言不是恒真——旧口径确实会错，且错法就是"炸鸡按可乐算"。
    """
    resolved = resolve_food(name="炸鸡", note="炸鸡 冰可乐")
    assert resolved.nature == Nature.COLD.value
    assert resolved.nature != _table_nature("炸鸡")
    assert "可乐" in (resolved.verification.detail or "")


def test_without_position_rule_the_temperature_is_lost(monkeypatch):
    """负控制之二：把"位置归属"关掉，可乐立刻认领不到紧贴它的「冰」。"""
    cola = _entry("可乐")
    text = "炸鸡 冰可乐"
    assert resolve_in_context(text, cola).nature == _expected("可乐", -1)

    monkeypatch.setattr(food_lookup, "trailing_temperature_prefix", lambda text: None)
    leaked = resolve_in_context(text, cola).nature
    assert leaked == _table_nature("可乐")
    assert leaked != _expected("可乐", -1)


def test_without_overlap_guard_a_food_can_borrow_a_neighbours_temperature(monkeypatch):
    """负控制之三：去掉交叉校验后，可乐会去认领麻辣烫的「烫」，凉被抬成平。"""
    cola = _entry("可乐")
    text = "麻辣烫 可乐"
    assert resolve_in_context(text, cola).nature == _table_nature("可乐")

    monkeypatch.setattr(food_lookup, "_overlaps", lambda span, spans: False)
    borrowed = resolve_in_context(text, cola).nature
    assert borrowed == _expected("可乐", 1)
    assert borrowed != _table_nature("可乐")


# ============================================================
# 4. 全局不变量：判出来的四性只能在表值上下浮动一档
# ============================================================
CORPUS: tuple[str, ...] = (
    "炸鸡 冰可乐",
    "火锅 冰可乐",
    "炸鸡 冰啤酒",
    "烤串 冰啤酒",
    "麻辣烫 冰可乐",
    "麻辣烫 可乐",
    "麻辣烫冰可乐",
    "麻辣烫",
    "冰可乐",
    "热牛奶",
    "去冰奶茶",
    "冰奶茶",
    "热奶茶",
    "冰 冰奶茶",
    "冰淇淋",
    "冰淇淋 可乐",
    "羊肉 苦瓜",
    "西瓜 苦瓜",
    "面条配冰镇啤酒",
    "火锅 冰镇酸梅汤",
    "果冻 可乐",
    "刨冰 可乐",
    "今天中午吃了炸鸡和冰可乐",
    "温热的黄酒",
    "凉皮",
    "加冰可乐",
    "去冰可乐",
    "甜点 冰可乐",
    "炸鸡冰可乐",
    "火锅冰可乐",
)


def test_reported_nature_never_becomes_another_food():
    """任何一样食物判出来的四性，只允许是它**自己**表值 ±1。

    "变成另一个食物的属性"就是 E15 的病灶：炸鸡（热）被按可乐算成寒，
    偏移 4 档。这个不变量不需要知道正确答案，就能抓住那类错误。
    """
    checked = 0
    for text in CORPUS:
        for name, nature in _natures(text).items():
            table = nature_to_num(_table_nature(name))
            if table is None:
                continue
            got = nature_to_num(nature)
            assert got is not None, f"{text!r} 里 {name} 判成 {nature}（判不出）"
            assert abs(got - table) <= 1, (
                f"{text!r} 里 {name} 判成 {nature}，"
                f"而它自己的表值是 {_table_nature(name)}，偏移超过一档"
            )
            checked += 1
    assert checked >= 40, f"只覆盖到 {checked} 组，断言可能恒真"
