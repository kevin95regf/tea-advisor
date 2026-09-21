"""餐次猜测：两条离线链路必须用**同一份**实现（**D28**）。

原先只有 API 离线路径（`analyze_offline`）在猜餐次，终端 `ui/terminal/chat.py`
直接写死 `MealTime.UNKNOWN` ⇒ 同一个用户在网页与终端拿到不同的餐次，而任何
依赖餐次的判据在终端链路**永远命不中**（与 E4 同形：两条路径边界不同）。

函数已下沉到 `core/app/domain/meal_time.py`，两端共用。

⚠️ 终端侧用 `importlib` 按**文件路径**加载 `chat.py`，不走包 import ——
`core/` 不 import `ui/` 是本仓库铁律，测试也守它。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

CORE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = CORE_DIR.parent
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from app.domain.enums import MealTime  # noqa: E402
from app.domain.meal_time import guess_meal_time  # noqa: E402
from app.domain.models import Constitution  # noqa: E402

SAMPLES = (
    "中午吃了米饭和炒青菜",
    "早餐吃了面包和牛奶",
    "宵夜吃了烧烤",
    "晚上吃了火锅喝了冰可乐",
    "下午茶一块蛋糕和一杯奶茶",
)


@pytest.fixture(scope="module")
def chat():
    spec = importlib.util.spec_from_file_location(
        "_chat_for_meal_time", PROJECT_ROOT / "ui" / "terminal" / "chat.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _terminal_meal_time(chat, text: str) -> MealTime:
    (parsed, _recs, _msg, _hits), _err = chat._offline_analyze(text, Constitution.BALANCED)
    return parsed.meal_time


def test_both_offline_paths_agree(chat):
    """跨链路一致：终端与 API 对同一句口述必须给出同一个餐次。"""
    for text in SAMPLES:
        assert _terminal_meal_time(chat, text) == guess_meal_time(text), text


def test_terminal_is_no_longer_always_unknown(chat):
    assert _terminal_meal_time(chat, "中午吃了米饭和炒青菜") is not MealTime.UNKNOWN


@pytest.mark.parametrize("text", ["夜宵吃了烧烤", "宵夜吃了烧烤", "半夜起来吃了泡面"])
def test_late_night_wordings_all_resolve(text):
    """「宵夜」与「夜宵」是同一个词的两种写法 —— 只写一个会让另一个漏到兜底。"""
    assert guess_meal_time(text) is MealTime.LATE_NIGHT


def test_guard_reads_the_real_value(chat, monkeypatch):
    """变异检验：把终端用的函数换成恒 UNKNOWN，断言必须跟着变。

    否则说明断言钉的是常量（`is not MealTime.UNKNOWN` 永远成立），守卫恒真。
    """
    monkeypatch.setattr(chat, "guess_meal_time", lambda _text: MealTime.UNKNOWN)
    assert _terminal_meal_time(chat, "中午吃了米饭和炒青菜") is MealTime.UNKNOWN
