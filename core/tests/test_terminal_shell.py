"""终端壳（`ui/terminal/chat.py`）的 CLI 行为测试。

补的是 SPEC §8.2 记的缺口：**终端壳零单元测试**。既有两条守卫都只钉到
`_offline_analyze` 那一层 —— `test_terminal_offline_path.py` 查的是它的 AST 结构，
`test_meal_time_paths.py` 查的是它给出的餐次；而 `cmd_resolve` / `cmd_offline` /
`main()` 的**返回码与渲染输出**此前没有任何东西守着。

本文件锁四条**用户可见**的行为，全部经 `main()`（连 argparse 的分支选择一起过）：

1. `--resolve` 打印食性，返回 0；
2. `--offline` 认不出食物时**返回码 1**；
3. `--offline` 正常出餐时打印推荐搭配，返回 0；
4. 负控制：把兜底换成"给不出推荐"，第 3 条那条输入必须从 0 **翻成 1**
   —— 否则"返回 0"可能只是因为这条链路恒返回 0，断言恒真。

设计约束
--------
- **不调模型、不需要 Key**：两条链路都不碰 `app.agents.runtime`；离线用例额外把
  `app.config.api_key_from_env` 换成"一被调用就炸"的绊线 —— 全项目只有
  `cmd_full` 会读 Key（`chat.py:385`），所以这条绊线一旦被踩到，
  就说明用例意外走到了模型链路。
- 加载方式沿用 `test_meal_time_paths.py:39-46`：按**文件路径** importlib 加载，
  不走包 import —— `core/` 不 import `ui/` 是本仓库铁律。
- 断言里的期望值（寒 / 温 / 认不出 / 出推荐）全部来自**真实数据与真实代码**，
  没有 mock 判定层；实测结果见文件末尾注释。
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import re
import sys
from pathlib import Path

import pytest

CORE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = CORE_DIR.parent
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

CHAT_PATH = PROJECT_ROOT / "ui" / "terminal" / "chat.py"


@pytest.fixture(scope="module")
def chat():
    """按文件路径加载终端壳 —— `core/` 不 import `ui/`，测试也不走包 import。"""
    # 文件缺失时报错、不跳过：skip 会造成「样本被治理偷走」式的静默失效。
    assert CHAT_PATH.is_file(), (
        f"缺少 {CHAT_PATH}（若已删除 ui/，请用 -k 'not terminal_shell' 排除本文件）"
    )
    spec = importlib.util.spec_from_file_location("_chat_for_terminal_shell", CHAT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def no_api_key(monkeypatch):
    """绊线：离线链路连 Key 都不该读。

    `cmd_full` 在**函数体内**才 `from app.config import api_key_from_env`
    （`chat.py:381-385`），所以替换模块属性就足以拦住它：一旦用例意外走到
    模型链路，这里会直接抛 AssertionError，而不是"碰巧没环境变量所以也过了"。
    """

    def _explode() -> str:
        raise AssertionError("离线链路不应读取 API Key —— 说明它走到了 cmd_full")

    monkeypatch.setattr("app.config.api_key_from_env", _explode)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)


def _run_cli(monkeypatch, chat_module, argv: list[str]) -> tuple[int, str]:
    """跑一次 `main()`，返回 (返回码, 终端输出)。

    `sys.argv` 必须替换：`main()` 里是 `parser.parse_args()`（`chat.py:565`），
    在 pytest 进程里它读到的是 pytest 自己的命令行。
    """
    monkeypatch.setattr(sys, "argv", ["chat.py", *argv])
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = chat_module.main()
    return code, out.getvalue()


# ============================================================
# 1. --resolve：查表链路
# ============================================================
def test_resolve_outputs_nature(chat, monkeypatch, capsys):
    """`--resolve 冰啤酒 茉莉花茶` ⇒ 打印食性，返回 0。

    两个期望值都是真实数据算出来的（不是 mock）：
      · 「冰啤酒」= 表内「啤酒」的凉 + 温度前缀 −1 ⇒ **寒**（`composed`，置信度 0.6）；
      · 「茉莉花茶」= 表内直取 ⇒ **温**（`rule`，置信度 0.9）——
        这条正是 README 里"模型系统性判成凉、查表纠正为温"的那个已知案例。
    """
    code, out = _run_cli(monkeypatch, chat, ["--resolve", "冰啤酒", "茉莉花茶"])

    assert code == 0, f"--resolve 应返回 0，实际 {code}\n{out}"
    # 两样东西都要被回显，否则"有输出"可能只是表头
    assert "冰啤酒" in out, out
    assert "茉莉花茶" in out, out
    # 食性必须打出来（`cmd_resolve` 的「四性：X」行，chat.py:258）
    assert re.search(r"四性：[寒凉平温热]", out), f"输出里没有食性：\n{out}"
    assert "四性：寒" in out, f"冰啤酒 的四性应为寒（凉 + 冰 −1）：\n{out}"
    assert "四性：温" in out, f"茉莉花茶 的四性应为温：\n{out}"
    # 这条链路本身不调模型，输出里也如实这么写（chat.py:252）
    assert "不调用模型" in out, out
    # 顺带确认没有把输出写到 stderr（本壳的正常输出全走 stdout）
    assert capsys.readouterr().err == ""


# ============================================================
# 2. --offline 认不出食物 ⇒ 返回码 1
# ============================================================
def test_offline_returns_1_when_no_recommendation(chat, monkeypatch, no_api_key):
    """表里一条都没认出来 ⇒ 返回码 **1**，且不打推荐段。

    这条钉的是"识别失败必须能被调用方看见"：终端壳用返回码当退出状态，
    返回 0 会让 `&&` 之类的脚本以为这次成功了。
    「今天天气不错」在食性表里零命中（实测 `match_foods()` 返回空列表），
    走的是 `_offline_analyze` 的 `if not foods` 早退分支（`chat.py:307-308`），
    再由 `cmd_offline` 翻译成返回码 1（`chat.py:356-358`）。
    """
    code, out = _run_cli(monkeypatch, chat, ["--offline", "今天天气不错"])

    assert code == 1, f"认不出食物时 --offline 应返回 1，实际 {code}\n{out}"
    assert "没能在食性表里认出任何食物" in out, out
    # 早退分支不该继续渲染推荐段
    assert "【给你的建议】" not in out, f"没认出来就不该出推荐段：\n{out}"


# ============================================================
# 3. --offline 正常出餐 ⇒ 打印推荐 + 返回码 0
# ============================================================
def test_offline_outputs_recommendation(chat, monkeypatch, no_api_key):
    """一餐正常的口述 ⇒ 打印推荐搭配并返回 **0**。

    「麻辣烫」命中场景规则 `spicy`（`core/data/diet_signals.json` 的 `scene_rules`）
    ⇒ 规则兜底给出温凉搭配（实测为「麦冬 6g + 罗汉果 3g」）并写明命中规则。
    断言盯的是**用户看得见的三件事**，不锁死具体药味（那是数据的事，由 matcher 侧测试管）：
    有推荐段、有「茶饮名 + 饮片克数」两行、有命中规则与"未调用模型"的如实说明。
    """
    code, out = _run_cli(monkeypatch, chat, ["--offline", "中午吃了碗麻辣烫"])

    assert code == 0, f"给出推荐时应返回 0，实际 {code}\n{out}"
    assert "【给你的建议】" in out, out
    assert "（本次没有推荐）" not in out, f"有推荐却打出了空推荐占位文案：\n{out}"
    # 茶饮名（`render_recommendations` 的 `1. 《…》` 行，chat.py:203）
    assert re.search(r"\d+\.\s*《.+?》", out), f"没有茶饮名：\n{out}"
    # 饮片 + 克数（`- 名字 6g  作用`，chat.py:206）
    assert re.search(r"-\s*\S+\s*\d+(?:\.\d+)?g", out), f"没有「饮片 克数」行：\n{out}"
    # 命中规则来自 matcher 的 rule_hits ⇒ 证明走的是规则兜底这条路径
    assert "命中规则" in out, out
    # 全程不调模型（chat.py:367）
    assert "本模式全程未调用模型" in out, out


# ============================================================
# 4. 负控制：让上面那条 0 变得"会变成 1"
# ============================================================
def test_negative_control_empty_recs_flips_exit_code_to_1(chat, monkeypatch, no_api_key):
    """负控制：把兜底换成"给不出推荐" ⇒ **同一条输入**必须从 0 翻成 1。

    否则第 3 条的 `code == 0` 可能只是因为"这条链路恒返回 0"，断言恒真。
    做法与既有风格一致（`test_terminal_offline_path.py` §3 的变异检验、
    `test_meal_time_paths.py::test_guard_reads_the_real_value`）：改掉被保护的东西，
    断言必须跟着变 —— 判据钉的是行为，不是常量。

    `fallback_recommend` 被替换成返回空推荐后，`cmd_offline` 末尾那条
    `return 0 if recs else 1`（`chat.py:371`）就会走到 1 这一支。
    """
    argv = ["--offline", "中午吃了碗麻辣烫"]

    # 前提：不改任何东西时，这条输入确实给得出推荐（否则下面的翻转证明不了什么）
    baseline_code, _baseline_out = _run_cli(monkeypatch, chat, argv)
    assert baseline_code == 0, "前提失效：这条输入本应给出推荐，负控制无意义"

    monkeypatch.setattr(
        chat.matcher,
        "fallback_recommend",
        lambda *args, **kwargs: ([], "（负控制：本次不给推荐）", []),
    )
    mutated_code, out = _run_cli(monkeypatch, chat, argv)

    assert mutated_code == 1, f"剔空推荐后应返回 1，实际 {mutated_code}\n{out}"
    assert "（本次没有推荐）" in out, out


# 实测（2026-09-21，core/.venv，无 API Key、无模型调用）：
#   --resolve 冰啤酒 茉莉花茶        → rc=0，四性：寒 / 四性：温
#   --offline 今天天气不错           → rc=1，"没能在食性表里认出任何食物"
#   --offline 中午吃了碗麻辣烫       → rc=0，《麦冬罗汉果润喉饮》+ 麦冬 6g/罗汉果 3g
#   同上 + 空推荐负控制              → rc=1，"（本次没有推荐）"
