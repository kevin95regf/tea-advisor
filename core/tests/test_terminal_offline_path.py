"""终端离线链路（链路 C）的结构守卫 —— E15 的漏网。

背景
----
E15 修的是「离线路径把整句口述当 note 喂进 `resolve_food`」。当时只修了
`core/app/api/analyze_offline.py`（链路 B），**漏了 `ui/terminal/chat.py`
自己实现的那份离线解析**（链路 C）。实测同一批口述里 14 条有 7 条四性不同，
其中 5 条差在**极端档（±2）** ⇒ 阶段 1 的寒热冲突判定在终端路径下恒为 False。

既有守卫为什么看不见 C
----------------------
`test_offline_segmentation.test_offline_path_no_longer_feeds_the_sentence_as_note`
只做两件事：① 硬编码只读 `analyze_offline.py` 一个文件；② 只拦
`resolve_food(..., note=...)`「传了整句」这个形状。而 **C 的病灶是「什么都没
传」，方向正好相反** ⇒ 就算把 `chat.py` 加进那份守卫的文件列表也依然拦不住。

本文件锁三件事
--------------
1. `_offline_analyze` 必须调用 `resolve_in_context`，且**不得**再出现
   `resolve_food` 调用（AST 级：注释与字符串里的同名不算）。
2. 同函数里构造 `ParsedFood` 必须带 `flavors=` —— 否则阶段 1 接上后
   `diet_signals.spicy` 在终端路径恒判不出，与 `conflict` 恒假同一形状。
3. **负控制（内存改副本、不落盘）**：把上面任一条改回旧写法，守卫必须变红；
   并保证守卫不会被注释/字符串里的同名骗过。

⚠️ 判据必须**按函数体**而不是整个文件：`cmd_resolve`（`resolve` 子命令）里的
`resolve_food` 是**故意**不带上下文的（用户输「牛奶」就是要查牛奶本身什么性），
改了反而错。文件级扫描会把它误判成违规 —— `test_file_level_scan_would_false_positive`
把这一点钉住。
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.domain.nature_math import nature_to_num
from app.services.food_lookup import (
    load_food_table,
    resolve_food,
    resolve_in_context,
)

CORE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = CORE_DIR.parent
CHAT = PROJECT_ROOT / "ui" / "terminal" / "chat.py"
API_OFFLINE = CORE_DIR / "app" / "api" / "analyze_offline.py"

FN_NAME = "_offline_analyze"

# 现实口述（前 4 条取自 chat.py 的 EXAMPLES）
CORPUS: tuple[str, ...] = (
    "中午吃了碗麻辣烫，还喝了杯冰可乐",
    "晚上火锅吃撑了，都是肉，还喝了啤酒",
    "早上就一杯冰美式，中午吃了份沙拉",
    "夜宵吃了炸鸡配奶茶",
    "中午吃了麻辣火锅，还喝了杯冰可乐",
    "晚上吃了火锅配冰啤酒",
    "吃了羊肉火锅和冰淇淋",
    "炸鸡配冰可乐",
    "面条配冰镇啤酒",
    "下午吃了蛋糕喝了冰奶茶",
    "早上吃了油条豆浆",
    "喝了一杯热牛奶",
    "吃了份三文鱼刺身和一碗热汤面",
    "夏天吃了西瓜又吃了顿烧烤",
)


# ============================================================
# 0. 取源码与 AST 作用域
# ============================================================
def _chat_source() -> str:
    # 文件缺失时报错、不跳过：skip 会造成「样本被治理偷走」式的静默失效。
    assert CHAT.is_file(), (
        f"缺少 {CHAT}（若已删除 ui/，请用 -k 'not terminal_offline_path' 排除本组）"
    )
    return CHAT.read_text(encoding="utf-8")


def _function(source: str, name: str) -> ast.FunctionDef:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"源码里找不到函数 {name}：多半是重命名了，守卫要跟着改")


def _calls_in(fn: ast.FunctionDef) -> list[tuple[str, int]]:
    """函数体内所有`<名字>(...)`调用 —— 只看调用，不看注释与字符串。"""
    out: list[tuple[str, int]] = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name:
            out.append((str(name), node.lineno))
    return out


# ============================================================
# 1. 守卫（纯函数：真实文件与合成坏样本共用同一份判据）
# ============================================================
def _guard_entrypoint(source: str) -> list[str]:
    fn = _function(source, FN_NAME)
    calls = _calls_in(fn)
    errors: list[str] = []
    if not any(n == "resolve_in_context" for n, _ in calls):
        errors.append(f"{FN_NAME} 未调用 resolve_in_context")
    for name, lineno in calls:
        if name == "resolve_food":
            errors.append(f"第 {lineno} 行出现 resolve_food 调用（应改用 resolve_in_context）")
    return errors


def _guard_flavors(source: str) -> list[str]:
    fn = _function(source, FN_NAME)
    errors: list[str] = []
    built = 0
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", None) != "ParsedFood":
            continue
        built += 1
        if not any(k.arg == "flavors" for k in node.keywords):
            errors.append(f"第 {node.lineno} 行的 ParsedFood(...) 缺 flavors=")
    if not built:
        errors.append(f"{FN_NAME} 里没有构造 ParsedFood")
    return errors


# ============================================================
# 2. 正控：真实文件必须过
# ============================================================
def test_terminal_offline_uses_context_aware_entrypoint():
    assert not _guard_entrypoint(_chat_source())


def test_terminal_offline_fills_flavors():
    assert not _guard_flavors(_chat_source())


def test_both_offline_paths_share_the_same_entrypoint():
    """链路 B 与链路 C 必须用同一个入口 —— 否则又会分叉出第三套口径。"""
    api = API_OFFLINE.read_text(encoding="utf-8")
    assert "resolve_in_context" in api
    assert not _guard_entrypoint(_chat_source())


# ============================================================
# 3. 负控制：关掉保护，断言必须变红
# ============================================================
def test_guard_catches_the_old_call_shape():
    """改回 `resolve_food(name=...)` ⇒ 守卫必须报错。"""
    source = _chat_source()
    old = 'r = resolve_food(name=entry["name"])'
    assert source.count("r = resolve_in_context(text, entry)") == 1
    mutated = source.replace("r = resolve_in_context(text, entry)", old)
    assert mutated != source
    errors = _guard_entrypoint(mutated)
    assert errors, "旧调用形状没被抓出 ⇒ 这条守卫恒真"
    assert any("resolve_food" in e for e in errors)


def test_guard_catches_missing_flavors():
    """去掉 `flavors=` ⇒ 守卫必须报错。"""
    source = _chat_source()
    assert source.count("flavors=r.flavors,") == 1
    mutated = source.replace("flavors=r.flavors,\n", "")
    assert mutated != source
    errors = _guard_flavors(mutated)
    assert errors, "缺 flavors 没被抓出 ⇒ 这条守卫恒真"


def test_guard_is_not_fooled_by_mentions_in_comments():
    """注释/字符串里提到 `resolve_food` 不算违规 —— 证明判据钉的是结构不是文本。"""
    source = _chat_source()
    decoy = source.replace(
        "    hits = match_foods(text)",
        "    # 注意：resolve_food(name=...) 在这里是错的，见上。\n"
        '    _ = "resolve_food(name=x)"\n'
        "    hits = match_foods(text)",
    )
    assert decoy.count("resolve_food(name=") > source.count("resolve_food(name=")
    assert not _guard_entrypoint(decoy), "守卫被注释/字符串骗过 ⇒ 不是结构级判据"


def test_file_level_scan_would_false_positive():
    """为什么不按整个文件判：`cmd_resolve` 里的 `resolve_food` 是**故意**保留的。"""
    source = _chat_source()
    file_calls = [
        (getattr(n.func, "id", None), n.lineno)
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.Call)
    ]
    resolve_food_lines = [ln for name, ln in file_calls if name == "resolve_food"]
    assert resolve_food_lines, "文件里已无 resolve_food 调用 ⇒ 本条前提失效，应改写"
    # 它们都在 cmd_resolve 里，不在 _offline_analyze 里
    assert not _guard_entrypoint(source)


# ============================================================
# 4. 行为不变式（走真实接口，不 mock 判定层）
# ============================================================
def _table_entries() -> list[dict]:
    table = load_food_table()
    rows = list(table.get("foods") or [])
    rows += list((table.get("tea_drinks") or {}).get("items") or [])
    return [e for e in rows if str(e.get("name") or "").strip()]


def test_single_food_names_do_not_drift():
    """单样食物零漂移：只输一个条目名时，带语境的入口必须等于不带语境的结果。

    这条证明 S0 改的是「温度词归属」，没碰判定层本身。
    """
    entries = _table_entries()
    assert len(entries) >= 100, f"样本被偷走：只取到 {len(entries)} 条"
    drift = []
    for entry in entries:
        name = str(entry["name"]).strip()
        a = resolve_food(name=name).nature
        b = resolve_in_context(name, entry).nature
        if a != b:
            drift.append((name, a, b))
    assert not drift, f"单样食物出现漂移：{drift[:5]}"


def test_context_moves_the_chilled_food_into_the_extreme_band():
    """终端漏前缀的后果：「冰可乐」只到 cool(−1) 而非 cold(−2) ⇒ 进不了冲突侧。"""
    text = "中午吃了碗麻辣烫，还喝了杯冰可乐"
    entry = next(e for e in _table_entries() if str(e["name"]) == "可乐")

    with_context = resolve_in_context(text, entry).nature
    without = resolve_food(name="可乐").nature

    assert nature_to_num(with_context) == -2, f"带语境应到寒：{with_context}"
    assert nature_to_num(without) == -1, f"不带语境只到凉：{without}"
    assert with_context != without


def test_the_fix_matters_on_a_realistic_corpus():
    """现实口述里必须真的有一批出现极端档差异 —— 否则这条修复只是纸面改动。"""
    hits = 0
    for text in CORPUS:
        before: dict[str, int] = {}
        after: dict[str, int] = {}
        for entry in _table_entries():
            name = str(entry["name"])
            if name not in text:
                continue
            before[name] = nature_to_num(resolve_food(name=name).nature)
            after[name] = nature_to_num(resolve_in_context(text, entry).nature)
        if any(
            abs(before[k]) < 2 and abs(after[k]) >= 2
            for k in set(before) | set(after)
            if k in before and k in after
        ):
            hits += 1
    assert hits >= 3, f"只有 {hits} 条口述出现极端档差异 ⇒ 修复影响面存疑"
