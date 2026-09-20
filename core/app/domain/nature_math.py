"""四性（寒热）的数值编码与修正运算。

为什么需要数值轴
----------------
「煎炸 +1、冰镇 -1」这类修正规则，以及第二层「多样食材合成」，
都需要把定性枚举（寒/凉/平/温/热）映射到数值上才能运算。
本模块是这个运算的唯一真源，任何涉及四性加减的地方都必须走这里。

编码
----
寒 = -2   凉 = -1   平 = 0   温 = +1   热 = +2

两层修正（顺序不可颠倒）
------------------------
1. **食材变体层**：同一种食材因形态不同而属性不同，如「红薯」平 → 「烤红薯」温。
   由数据表条目的 `variant_nature` 提供，**查表优先**，直接取表里的值。
2. **烹饪修正层**：表里没有变体记录时，按通用规则做 ±1 兜底。
   蒸煮 0、煎炸 +1、加辛辣配料 +1、冰镇 -1。

第 2 层只在第 1 层没有命中时生效——否则表里精确的变体值会被通用规则破坏。
"""

from __future__ import annotations

from typing import NamedTuple

from app.domain.enums import Nature

# 编码值边界
NATURE_MIN = -2
NATURE_MAX = 2

# 数值 → 四性。索引即偏移量，避免用 dict 查表时漏键
_NUM_TO_NATURE: dict[int, Nature] = {
    -2: Nature.COLD,
    -1: Nature.COOL,
    0: Nature.NEUTRAL,
    1: Nature.WARM,
    2: Nature.HOT,
}

_NATURE_TO_NUM: dict[str, int] = {
    Nature.COLD.value: -2,
    Nature.COOL.value: -1,
    Nature.NEUTRAL.value: 0,
    Nature.WARM.value: 1,
    Nature.HOT.value: 2,
}

# 烹饪方式的通用修正（仅在第 1 层食材变体未命中时使用）
COOKING_DELTA: dict[str, int] = {
    "cold": -1,        # 冰镇/加冰
    "deep_fried": 1,   # 煎炸
    "grilled": 1,      # 烧烤
    "stir_fried": 0,   # 炒
    "steamed": 0,      # 蒸
    "boiled": 0,       # 煮
    "raw": 0,          # 生
    "pickled": 0,      # 腌
    "unknown": 0,
}

# 「加辛辣配料 +1」的识别关键词（看 note 与 name）
SPICY_KEYWORDS: tuple[str, ...] = (
    "辣", "麻辣", "重辣", "加辣", "辣椒", "花椒", "芥末", "咖喱", "胡椒", "孜然",
)

# 数值结果 → 四性的取整门限。
# value 落在 [-0.5, 0.5) 记为平；±0.5 归到主导方向（由调用方给出 dominant），
# 以避免"反向抵消后恰好为 0"把偏性抹平成平性。
ROUND_THRESHOLD = 0.5


def nature_to_num(nature: Nature | str | None) -> int | None:
    """四性 → 数值。unknown 或无法识别返回 None（表示"没有值"，不是 0）。"""
    if nature is None:
        return None
    key = nature.value if isinstance(nature, Nature) else str(nature)
    return _NATURE_TO_NUM.get(key)


def num_to_nature(value: float | int) -> Nature:
    """数值 → 四性。四舍五入到最近的整数档，并夹在 [-2, 2]。"""
    rounded = int(round(float(value)))
    clamped = max(NATURE_MIN, min(NATURE_MAX, rounded))
    return _NUM_TO_NATURE[clamped]


def num_to_nature_with_dominant(value: float, dominant_sign: int) -> Nature:
    """数值 → 四性，±0.5 的边界值归到主导方向。

    dominant_sign: +1 表示主导项偏温/热，-1 表示偏寒/凉，0 表示无主导。
    """
    if abs(value) == ROUND_THRESHOLD and dominant_sign != 0:
        return _NUM_TO_NATURE[dominant_sign]
    return num_to_nature(value)


def clamp(value: int) -> int:
    """把数值夹到 [-2, 2]。例如"性热的羊肉再油炸"仍是热，不能变成"超热"。"""
    return max(NATURE_MIN, min(NATURE_MAX, value))


# ============================================================
# 温度前缀（纯规则识别，不经过模型）
# ============================================================
# 为什么用纯规则而不是让模型判断烹饪方式：
#   模型给的 cooking 无法区分"可靠证据"与"猜测"——它会给出「希腊酸奶=cold」、
#   「火腿三明治=grilled」这类没有依据的值，照单全收会污染表值。
#   而「冰啤酒」「热牛奶」里的"冰/热"是字符串层面的确定信号，无需模型参与。
#
# 只在"去掉温度前缀后剩下的名字能在表里查到"时才叠加（由调用方保证），
# 这天然排除了「热狗」「热干面」「凉皮」这类温度字属于菜名的误伤。

# 降温前缀：命中即 -1
CHILL_PREFIXES: tuple[str, ...] = (
    "冰镇的", "冰镇", "冰的", "冰", "加冰的", "加冰", "去冰的", "去冰",
    "冷冻的", "冷冻", "冷藏的", "冷藏", "冻的", "冻",
)

# 升温前缀：命中即 +1
HEAT_PREFIXES: tuple[str, ...] = (
    "热腾腾的", "热腾腾", "滚烫的", "滚烫", "烫的", "烫",
    "加热的", "加热", "温热的", "温热", "热的", "热",
)


class TemperatureSignal(NamedTuple):
    """温度前缀的判定结果。

    这是**唯一**的温度语义载体：字段是结构化数据（增量/前缀/来源），
    不是中文文案，所以解析层与提示词层都能直接用，无需各写一套判断。
    """

    delta: int          # -1 降温 / +1 升温
    prefix: str         # 命中的前缀，如"冰镇"
    stripped: str       # 去掉前缀后的净名字，如"啤酒"
    from_field: str     # 命中来自哪个字段："name" 或 "note"


def _match_prefix(text: str, prefixes: tuple[str, ...]) -> str | None:
    """按长度降序匹配前缀，返回命中的前缀（长前缀优先，避免"冰"抢走"冰镇"）。"""
    for prefix in sorted(prefixes, key=len, reverse=True):
        if text.startswith(prefix):
            return prefix
    return None


def detect_temperature_prefix(name: str) -> tuple[int, str, str] | None:
    """识别单个字符串开头的温度前缀。

    返回 (增量, 前缀, 去掉前缀后的名字)，未识别到返回 None。
    只做前缀匹配，不做全文匹配。
    """
    if not name:
        return None
    text = name.replace(" ", "").strip()
    if not text:
        return None

    chill = _match_prefix(text, CHILL_PREFIXES)
    if chill:
        rest = text[len(chill) :].strip()
        if rest:
            return -1, chill, rest

    heat = _match_prefix(text, HEAT_PREFIXES)
    if heat:
        rest = text[len(heat) :].strip()
        if rest:
            return 1, heat, rest

    return None


def find_temperature_in_text(text: str) -> tuple[int, str, str] | None:
    """在任意文本里**查找**温度词（不限开头位置）。

    与 detect_temperature_prefix 的区别：
      - detect_temperature_prefix 只认**开头**的，用于食物名
        （避免「冰淇淋」「凉皮」这类温度字属于菜名的词被误判）
      - 本函数在任意位置查找，用于**备注**字段——备注通常就是"去冰""冰镇""热的"
        这类简短描述，温度词可能出现在任何位置（实测模型输出「note=去冰」）

    同样按最长匹配优先，避免"冰"抢走"冰镇"。
    """
    if not text:
        return None
    t = text.replace(" ", "").strip()
    if not t:
        return None

    for delta, prefixes in ((-1, CHILL_PREFIXES), (1, HEAT_PREFIXES)):
        for prefix in sorted(prefixes, key=len, reverse=True):
            idx = t.find(prefix)
            if idx < 0:
                continue
            rest = (t[:idx] + t[idx + len(prefix) :]).strip()
            return delta, prefix, rest

    return None


# 温度词要能被"认领"，它在文本里必须有明确边界：要么在串首，要么紧跟在
# 这些分隔符／连接用语之后。否则它是**前一个词的一部分**——「麻辣烫」的「烫」、
# 「果冻」的「冻」、「刨冰」的「冰」都不是温度指令。
#
# 这个表只求"够用"，不求完备：漏掉某个连接字，后果是温度词**不被认领**
# （判定退回食物自身的表值，保守且诚实），不会造成误判。反过来多加一个字
# 才会放开认领，所以新增时要想清楚。
PREFIX_BOUNDARY_CHARS: tuple[str, ...] = (
    " ", "\t", "\n",
    "，", "。", "、", "；", "：", "！", "？", "“", "”", "（", "）",
    ",", ".", ";", ":", "!", "?", '"', "'", "(", ")",
    "+", "＋", "-", "－", "~", "/", "|", "&",
    "和", "与", "跟", "及", "配", "加", "再", "又", "还", "有",
    "了", "的", "是", "在", "吃", "喝", "点", "买", "带",
    "个", "份", "杯", "瓶", "罐", "碗", "盘", "两", "几",
)


def trailing_temperature_prefix(text: str) -> str | None:
    """识别**紧贴文本末尾**的温度前缀（纯规则，复用上面两张前缀表）。

    为什么不让 `find_temperature_in_text` 兼任：那个函数服务的是"备注"——
    整段备注都是这一餐的描述，所以它在**任意位置**找温度词，找到的就是这餐的温度。
    本函数服务的是另一个问题：一段话里有多样食物时，温度词该判给**谁**。
    这时只能靠**位置**——「炸鸡 冰可乐」里的「冰」紧贴「可乐」之前，属于可乐；
    它离「炸鸡」隔着别的东西，不该算在炸鸡头上（这正是 E15）。

    因此调用方送入的是"某个命中词**之前**的那一段"，本函数只回答
    "这一段末尾是不是温度词"。末尾空格忽略（「冰 可乐」也算）。
    注意只做**末尾**匹配而不是全文查找：温度词若出现在段中别处，
    说明它属于前面那样食物，不能算在后面这样食物头上。

    刻意不做两件事：
      - 不做"剥掉前缀后须为完整表内食物名"的准入——那是 `resolve_food` 的职责；
        本函数只识别、不判定，避免两处各写一套准入而漂移。
      - 判不出返回 None 而不是空串（沿用 unknown ≠ 0 的纪律）。
    """
    if not text:
        return None
    tail = text.rstrip()
    if not tail:
        return None
    for prefixes in (CHILL_PREFIXES, HEAT_PREFIXES):
        for prefix in sorted(prefixes, key=len, reverse=True):
            if tail.endswith(prefix):
                return prefix
    return None


# 备注通道最大长度。超过这个长度就不再认为是"纯温度描述"——
# 模型的 note 常常是复述菜名（如 note="麻辣烫 麻辣烫"），
# 里面的"烫"会被误当成升温词。要求备注足够短，能挡住这类噪声。
NOTE_MAX_LEN = 10


def resolve_temperature(name: str = "", note: str = "") -> TemperatureSignal | None:
    """**温度前缀判定的唯一入口。** 同时扫描食物名与备注，返回结构化信号。

    为什么要有这个入口：温度判定原本散落在两处——
    解析层用前缀匹配、提示词层用子串判断，两套逻辑会各自漂移
    （例如「冰淇淋」在解析层被正确排除，在提示词层却会被当成冰镇）。
    现在两层共用本函数，新增前缀只需改 CHILL_PREFIXES / HEAT_PREFIXES 一处。

    扫描方式按字段区分，这是刻意的：

    - **食物名**：只认**开头**的温度词，避免「冰淇淋」「凉皮」「热狗」被误判。
    - **备注**：只在**任意位置**查找，且备注本身要短（NOTE_MAX_LEN 以内）。
      备注里通常写的是"去冰""冰镇""热的"这类简短描述，位置不定（实测模型会
      输出 note=去冰，也会输出 note=麻辣烫 麻辣烫 这种复述），
      所以用长度上限挡掉复述型备注，避免把菜名里的"烫"当成升温词。

    优先级：食物名 > 备注。名字里的温度字是用户最直接的表达，
    备注只在名字没给出温度信息时才采信。
    """
    detected = detect_temperature_prefix(name or "")
    if detected:
        delta, prefix, stripped = detected
        return TemperatureSignal(
            delta=delta, prefix=prefix, stripped=stripped, from_field="name"
        )

    note_text = (note or "").replace(" ", "").strip()
    if not note_text or len(note_text) > NOTE_MAX_LEN:
        return None

    found = find_temperature_in_text(note_text)
    if found:
        delta, prefix, stripped = found
        return TemperatureSignal(
            delta=delta, prefix=prefix, stripped=stripped, from_field="note"
        )

    return None


def shift_nature(nature: Nature | str | None, delta: int) -> Nature | None:
    """在四性上叠加增量并夹取。unknown 参与修正仍返回 None。"""
    base = nature_to_num(nature)
    if base is None:
        return None
    return _NUM_TO_NATURE[clamp(base + delta)]


def has_spicy_marker(text: str) -> bool:
    """文本里是否出现"辛辣"信号（用于 +1 修正）。"""
    if not text:
        return False
    return any(kw in text for kw in SPICY_KEYWORDS)


def apply_cooking_fallback(
    nature: Nature | str | None,
    cooking: str | None,
    text_hint: str = "",
) -> tuple[Nature | None, list[str]]:
    """烹饪修正层（第 2 层兜底）。返回 (修正后的四性, 修正说明列表)。

    规则：蒸煮 0、煎炸 +1、烧烤 +1、冰镇 -1、加辛辣配料 +1。
    辛辣与烹饪方式的增量会累加，再一并夹取。
    """
    base = nature_to_num(nature)
    if base is None:
        return None, []

    notes: list[str] = []
    delta = 0

    # cooking 可能是 CookingMethod 枚举或纯字符串，统一取字符串值
    cooking_key = ""
    if cooking is not None:
        cooking_key = cooking.value if hasattr(cooking, "value") else str(cooking)

    cooking_delta = COOKING_DELTA.get(cooking_key, 0)
    if cooking_delta:
        delta += cooking_delta
        label = {
            "cold": "冰镇",
            "deep_fried": "煎炸",
            "grilled": "烧烤",
        }.get(cooking_key, cooking_key)
        notes.append(f"按{label}处理：{cooking_delta:+d}")

    if has_spicy_marker(text_hint):
        delta += 1
        notes.append("含辛辣配料：+1")

    if delta == 0:
        return num_to_nature(base), notes

    return _NUM_TO_NATURE[clamp(base + delta)], notes


def combine(values: list[float], dominant_sign: int | None = None) -> tuple[float, int]:
    """第二层合成：多样食材 → 一个数值。

    规则（由使用者确认）：
      1. **取绝对值最大者为主导项**；同向的其余项累加，封顶 ±2；
      2. **反向项只做 50% 抵消，不翻转主导方向**；
      3. 全部为 0（或空）时结果为 0（平）。

    返回 (合成值, 主导方向符号)。主导方向符号用于 ±0.5 边界取整。

    注意：本函数不处理烹饪修正——烹饪增量应在合成之后由调用方叠加。
    """
    if not values:
        return 0.0, 0

    if dominant_sign is None:
        # 主导项 = 绝对值最大者。并列时（如 羊肉+2 与 苦瓜-2）
        # 取**先出现的**那个，也就是在菜品描述里更靠前的食材，
        # 通常对应主料。这一点很关键：否则并列时会因顺序不同给出不同结果。
        best_idx = 0
        for i, v in enumerate(values):
            if abs(v) > abs(values[best_idx]):
                best_idx = i
        dominant_sign = 1 if values[best_idx] > 0 else (-1 if values[best_idx] < 0 else 0)

    if dominant_sign == 0:
        return 0.0, 0

    same_dir = [v for v in values if v * dominant_sign > 0]
    opposite = [v for v in values if v * dominant_sign < 0]

    same_total = sum(same_dir)
    # 同向累加封顶 ±2
    same_total = max(-2.0, min(2.0, same_total))
    if dominant_sign < 0:
        same_total = max(-2.0, min(0.0, same_total))
    else:
        same_total = max(0.0, min(2.0, same_total))

    # 反向 50% 抵消：反向值符号与主导相反，直接相加即自动起到抵消作用
    result = same_total + 0.5 * sum(opposite)

    # 不翻转主导方向：反向抵消最多把结果拉到 0，不能越过 0
    if dominant_sign > 0:
        result = max(0.0, result)
    else:
        result = min(0.0, result)

    return result, dominant_sign
