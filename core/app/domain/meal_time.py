"""餐次猜测（两条离线链路共用一份）。

2026-09-21 由 `core/app/api/analyze_offline.py` 下沉而来（**D28**）：原先只有 API
离线路径在猜，终端 `ui/terminal/chat.py` 直接写死 `MealTime.UNKNOWN` ⇒ 同一个用户
在网页与终端拿到不同的餐次，而任何依赖餐次的判据（如夜宵场景）在终端链路**永远
命不中**。放在 `domain/` 是因为两端都要用，而 `core/` 不 import `ui/`。

判据两段：先按口述里的**时间词**，没有再退回**当前钟点**。
⚠️ 兜底那一段用的是"现在几点"，不是"这餐几点吃" —— 同一句口述在不同时刻跑会
得到不同结果。这是既有行为（搬过来时未改），接判据时必须知道这一点。
"""

from __future__ import annotations

import time

from app.domain.enums import MealTime

_KEYWORD_MAP: tuple[tuple[tuple[str, ...], MealTime], ...] = (
    (("早餐", "早上", "早饭"), MealTime.BREAKFAST),
    (("午餐", "中午", "午饭"), MealTime.LUNCH),
    (("晚餐", "晚上", "晚饭"), MealTime.DINNER),
    # ⚠️ 「宵夜」与「夜宵」是同一个词的两种写法，两个都要写：实测「宵夜吃了烧烤」
    # 在只写「夜宵」时会漏过关键词、退到当前钟点（凌晨跑测试 ⇒ 判成 breakfast）。
    (("夜宵", "宵夜", "半夜"), MealTime.LATE_NIGHT),
    (("下午茶", "加餐"), MealTime.SNACK),
)


def guess_meal_time(text: str) -> MealTime:
    """从口述里猜餐次；猜不出就按当前钟点退一个。"""
    for words, value in _KEYWORD_MAP:
        if any(word in text for word in words):
            return value
    hour = time.localtime().tm_hour
    if 5 <= hour < 10:
        return MealTime.BREAKFAST
    if 10 <= hour < 14:
        return MealTime.LUNCH
    if 14 <= hour < 17:
        return MealTime.SNACK
    if 17 <= hour < 21:
        return MealTime.DINNER
    return MealTime.LATE_NIGHT
