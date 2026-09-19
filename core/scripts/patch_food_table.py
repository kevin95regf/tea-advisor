"""数据表结构升级与条目修正（幂等，可重复运行）。

本脚本做四件事：
  1. 把二值 `reviewed` 升级为三态 `review_status`：
     approved（已审核通过）/ pending（待审核）/ rejected（审核不通过）
     为什么需要三态：`reviewed: false` 无法区分"还没审"和"审了但不认可"。
     后者绝不能被当作高置信度硬规则使用。
  2. 修正内容重叠的条目（这类重叠会让短名条目抢走具体菜名的匹配）。
  3. 记录修正原因到 review_note，便于日后追溯。
  4. 新增条目（`NEW_ENTRIES`）——用于**条目粒度错误**的拆分，例如
     「蘑菇」一条代表蘑菰/香蕈两个四气不同的物种，只能拆成两条。
     拆分不是"补缺口"而是"修矛盾"：两个物种必须各自成条，删别名解决不了。
  5. B4 · L2 派生 `note`（`LAYER2_NOTES`）——逐条写入派生式说明，**只动 `note`**。
  6. B4 · `_meta` 规则登记（`META_PATCH`）——`nature_derivation_rules`（机器可读档位表，
     不渲染进提示词）与 `derivation_conflicts`（R6 冲突登记，值不动）。

**它是数据修正的唯一正规通道**：幂等（重复跑结果不变）、每条修正都留 `review_note`、
强制 LF（避免 Windows CRLF 在 git 里造成假 diff）。不要手工改 `food_properties.json`。

用法（在 core 目录下）：
    python scripts/patch_food_table.py --dry-run
    python scripts/patch_food_table.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CORE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CORE_DIR))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass

TABLE = CORE_DIR / "data" / "food_properties.json"

VALID_STATUS = ("approved", "pending", "rejected")

# 条目字段的**规范顺序**。新字段要插到这个位置，不能一律 append 到末尾——
# 否则同一张表里会同时存在两种键序（`note` 在 `keywords` 后 vs 在 `review_status` 后），
# diff 和人工阅读都会变难。表里既有 34 条带 `note` 的条目都在 `keywords` 之后。
FIELD_ORDER = (
    "id", "name", "aliases", "category", "nature", "flavors", "keywords",
    "variant_nature", "note", "base_form",
    "reviewed", "reviewed_by", "reviewed_at", "review_note", "review_status",
)


def normalize_key_order(entry: dict) -> dict:
    """按 `FIELD_ORDER` 重排键；未登记的字段保持相对顺序、排在其后。"""
    ordered = {k: entry[k] for k in FIELD_ORDER if k in entry}
    for key, value in entry.items():
        if key not in ordered:
            ordered[key] = value
    return ordered

# 条目修正：id -> 要改的字段
ENTRY_FIXES: dict[str, dict] = {
    # 「寿司」与「生鱼片」关键词重叠（生鱼片的关键词含"寿司"），
    # 会让寿司被判定成生鱼片的属性。移除重叠关键词，让两者各归各。
    "shengyu": {
        "keywords": ["生鱼片", "刺身", "三文鱼"],
        "review_note": "移除与「寿司」重叠的关键词，避免寿司被误配为生鱼片属性",
    },
    # 寿司：同希腊酸奶的理由——"生食"是常见吃法而非加工方式，
    # 不应把「凉」再降一档成「寒」。生鱼片另有一条目，各自归位。
    "shousi": {
        "variant_nature": {},
        "review_note": "去掉 raw 变体：生食为常见吃法，属性维持凉，不与生鱼片同档",
    },
    # 希腊酸奶：去掉 cold 变体——冷藏只是食用方式，
    # 不应把「凉」再降一档成「寒」，否则与冰镇饮料混为一谈。
    "xila_suannai": {
        "variant_nature": {},
        "review_note": "去掉 cold 变体：冷藏为常见食用方式，属性维持凉，不与冰镇饮料同档",
    },
    # 薯条：表里曾把「薯条」写成「炸鱼薯条」的关键词，导致匹配歧义。
    # 现已按规范名精确匹配，这里确保薯条自身条目存在且关键词干净。
    "shujiaotiao": {
        "keywords": ["薯条", "薯片"],
        "review_note": "关键词归一，避免与「炸鱼薯条」相互抢占匹配",
    },
    # ---------- ④ 层：内部矛盾（属数据错，与外部来源无关） ----------
    # ④-1 别名污染：把不属于自己的名字挂在条目上。
    # 「炸鸡」是独立条目 zhaji（热，菜肴），同时挂在 jirou 的 aliases 与 keywords 里，
    # 导致 names_match("炸鸡","鸡肉") 为真（且反向为假，不对称），炸鸡会被判成鸡肉属性。
    # 删别名即解——注意 jirou 的 aliases 与 keywords **两处都要清**。
    "jirou": {
        "aliases": ["鸡腿", "鸡胸"],
        "keywords": ["鸡肉", "鸡腿", "鸡胸"],
        "review_note": "移除「炸鸡」别名与关键词：它属于独立条目 zhaji（热），留着会让炸鸡被判成鸡肉（温）属性",
    },
    # ④-2 变体与兜底规则差一档：base 温 + 冰镇 -1 = 平，原值记「凉」。
    # 可乐/红薯/鸡肉/吐司的冰镇/加热变体都符合规则，咖啡是唯一离群条目。
    "kafei": {
        "variant_nature": {"cold": "neutral"},
        "review_note": "冰镇变体由 cool 改 neutral：温 + 冰镇 -1 = 平，与其余变体条目同规则",
    },
    # ---------- D4a 口径分歧：保留项目值，只在数据里留痕 ----------
    # 这 4 条不是「数据错」而是「来源口径之争」（基准是教材/经典层，
    # 强度不足以推翻现值）。无权威裁定前不改 nature，只把双方值写进 note。
    "baicai": {
        "note": "口径分歧：项目值凉；《中医饮食营养学》行2541 记平。未获权威裁定前保留项目值。",
        "review_note": "加 note 留痕（口径分歧），nature 未改",
    },
    "huanggua": {
        "note": "口径分歧：项目值凉；《中医饮食营养学》行786 记寒。未获权威裁定前保留项目值。",
        "review_note": "加 note 留痕（口径分歧），nature 未改",
    },
    "lianou": {
        "note": (
            "口径分歧：项目值凉；《中医饮食营养学》行609 记寒、"
            "《本草纲目》26315 正条记平（同条引《大明》作温）。未获权威裁定前保留项目值。"
        ),
        "review_note": "加 note 留痕（口径分歧，三值并列），nature 未改",
    },
    # D4a 的第 4 条（A2 ①，2026-09-18 落定）：映射（酱油→酱）**采纳**，但基准是
    # 《本草纲目》——50 号文件 §5.4 自定「经典层不得当教材用」，强度不足以把项目值
    # 「平」改「温」。⇒ 值不改，补 note 留痕。
    # ⚠️ `note` 是**运行时字段**，不是注释：food_lookup.resolve_temperature_fields 会同时
    # 扫 name 与 note，命中 CHILL_PREFIXES / HEAT_PREFIXES（冰/加冰/冷藏/冷冻、热/烫/加热/温热…）
    # 就给四气 **±1**。所以这段文案**刻意避开**这些连续子串——「辛、温」不含「温热」「热」，
    # 实测 resolve_temperature_fields("酱油", note) 返回 None。
    # 守卫：tests/test_food_lookup.py::test_jiangyou_note_has_no_temperature_side_effect
    "jiangyou": {
        "note": "口径分歧：项目值平；《本草纲目》9948 记辛、温。未获权威裁定前保留项目值。",
        "review_note": "加 note 留痕（口径分歧）；映射（酱油→酱）已采纳、值不改",
    },
    # ④-4 别名跨物种：条目名「蘑菇」→ 蘑菰（寒），别名「香菇」→ 香蕈（平），
    # 一个条目代表两个四气不同的物种。香菇已拆出为独立条目 xianggu（见 NEW_ENTRIES），
    # 这里把 mogu 收窄为蘑菰。
    #
    # A2 ②（2026-09-18 落定，走 (C)）：金针菇/杏鲍菇/平菇 是**另外 3 个物种**、50 号文件
    # 无条目，从 `aliases` + `keywords` **两处**移出 —— 只删 `keywords` 无效，因为
    # `_find_entry` 的第 2 级匹配把两处**合并成一处扫描**（food_lookup.py:286）。
    # 移出后这 3 个词走「表未覆盖」的模型推测分支（置信度 0.9 → 0.3，界面标「食性未经验证」）：
    # 以 0.9 呈现一个无来源的四气，比以 0.3 诚实标注「未经验证」更危险。
    #
    # `口蘑` 与那 3 个词**不同批次处理**：它在通行语境下就是「蘑菇」的口语同义语，
    # 留在别名上有匹配价值；但**依据是项目专业判断，不是来源行**（50 号文件不在仓库，
    # §5.3 有无「口蘑」行无法本地核实，不编行号）。挂起项 docs/pending-items.md A3。
    "mogu": {
        "aliases": ["蘑菰", "口蘑"],
        "keywords": ["蘑菇", "蘑菰", "口蘑"],
        "nature": "cold",
        "review_note": (
            "拆条后收窄为「蘑菰」（寒，纲目 23487）：香菇已移至 xianggu；四气由 neutral 改 cold。"
            "**条目代表的物种＝蘑菰；显示名保留「蘑菇」不改名**，以维持 exact_name_hit 直取"
            "（改名会让用户说「蘑菇」落到别名匹配，并可能启用烹饪修正层）。"
            "金针菇/杏鲍菇/平菇 是另外 3 个物种、50 号文件无条目，已从 aliases + keywords 两处移出"
            "（走「表未覆盖」分支，界面标「食性未经验证」）；「口蘑」保留在别名上，"
            "但**依据是项目专业判断、非来源行**（见挂起项 A3）。"
        ),
    },
}

# 新增条目：id -> 字段字典（`_after` 指定插到哪个条目之后）
# 只用于「修矛盾」类拆分，不用于补缺口——无来源的新食材不在这里加。
NEW_ENTRIES: dict[str, dict] = {
    "xianggu": {
        "id": "xianggu",
        "name": "香菇",
        "aliases": ["香蕈", "冬菇", "花菇"],
        "category": "蔬菜",
        "nature": "neutral",
        "flavors": ["sweet"],
        "keywords": ["香菇", "香蕈", "冬菇", "花菇"],
        "reviewed": False,
        "reviewed_by": None,
        "reviewed_at": None,
        "review_note": "由 mogu 拆出（④层矛盾：一个条目代表两个四气不同的物种）",
        "review_status": "pending",
        "_after": "mogu",
    },
}


# ============================================================
# B4 · L2 派生规则（R1–R6）的机器可读登记
# ============================================================
# 规则成文、逐条推导、逐条 `note` 文案：`docs/food-properties-b4-derivation.md`。
#
# 为什么**不写进 `_meta.nature_change_rules`**（这是对原方案 §9 第 2 步的一处偏离）：
#   那个键是**散文**，且经 `render_nature_change_rules()` **渲染进 Agent1 提示词**
#   （agent1_diet.py）。B4 的档位值与当前代码 `COOKING_DELTA` 并不一致
#   （油炸 深+2 / 生食 -1 / 炒 +1 三处，见 `alignment_pending`）。把 B4 口径写进提示词，
#   等于把「文档口径」当「运行时行为」讲给模型 —— 那正是拍板 A（本批不动机制）要避免的。
#   故新开本键：机器可读、**不渲染进提示词**，供守卫 ④ 与 B4b 收口使用。
#
# `runtime_delta` / `script_delta` 是**声明式绑定**：守卫 ④ 断言它们分别与
# `nature_math.COOKING_DELTA` / `build_food_review_sheet.LAYER2_DELTA` **硬等值**，
# 任一侧漂移即变红 —— 这样「三份副本」的差异是**被声明的**，不是静默的。
META_PATCH: dict = {
    "nature_derivation_rules": {
        "_doc": (
            "B4 第 2 步（文档 + 数据批次）。canonical_delta = B4 口径（真源）；"
            "runtime_delta / script_delta = 代码与核验单脚本的**现值**（守卫 ④ 硬等值绑定）；"
            "alignment_pending = canonical 与 runtime 的差集，B4b 收口。"
        ),
        "tiers": [
            {"tier": "轻", "delta": 0, "methods": ["boiled", "steamed", "bake_form"],
             "desc": "煮（蒸、卤、焯）；定型烘焙（吐司、蛋糕，含水高）"},
            {"tier": "中", "delta": 1,
             "methods": ["stir_fried", "grilled", "high_temp_bake", "heavy_braise", "hot_soup", "spicy"],
             "desc": "炒；明火烧烤；高温/脱水烘烤；油糖酱焖烧、久煮焖烧、卤汁浓酱；热汤（烫煮）"},
            {"tier": "深", "delta": 2, "methods": ["deep_fried"],
             "desc": "油炸（单次与双重同判：表内 5 条油炸成品 5/5 相对基底跨两档）"},
            {"tier": "轻·冷向", "delta": -1, "methods": ["cold"], "desc": "冷藏、冰镇"},
            {"tier": "深·冷向", "delta": -2, "methods": ["deep_freeze"], "desc": "深度冷冻（冰淇淋）"},
            {"tier": "方向性", "delta": None, "methods": ["raw", "pickled"],
             "desc": "生食 -1（与冰镇同现时只计一次，取生食）；腌制方向不定 ⇒ 记 0 并在 note 标「方向不定」"},
            {"tier": "发酵", "delta": None, "methods": ["ferment_alcohol", "ferment_dairy", "semi_ferment"],
             "desc": "酒/曲类 +1；乳发酵 0；半发酵 0"},
        ],
        "canonical_delta": {
            "raw": -1, "cold": -1, "deep_freeze": -2,
            "boiled": 0, "steamed": 0, "bake_form": 0, "pickled": 0,
            "grilled": 1, "stir_fried": 1, "spicy": 1, "hot_soup": 1,
            "high_temp_bake": 1, "heavy_braise": 1,
            "deep_fried": 2,
            "ferment_alcohol": 1, "ferment_dairy": 0, "semi_ferment": 0,
            "unknown": 0,
        },
        "runtime_delta": {
            "cold": -1, "deep_fried": 1, "grilled": 1, "stir_fried": 0,
            "steamed": 0, "boiled": 0, "raw": 0, "pickled": 0, "unknown": 0,
        },
        "script_delta": {
            "cold": -1, "deep_fried": 1, "grilled": 1, "stir_fried": 1,
            "boiled": 0, "steamed": 0, "raw": 0,
        },
        "alignment_pending": {
            "deep_fried": {
                "canonical": 2, "runtime": 1,
                "note": "油炸整档记深；代码仍 +1 ⇒ 本批只落文档口径。",
            },
            "raw": {
                "canonical": -1, "runtime": 0,
                "note": "生食 -1（拍板 D 甲案）；代码仍 0 ⇒ 寿司/生鱼片的生食扣档只在文档口径成立。",
            },
            "stir_fried": {
                "canonical": 1, "runtime": 0,
                "note": "三份副本不一致的原始形态：代码 0 / 本表 1 / 核验单脚本 1（拍板 E 要求守卫覆盖）。",
            },
        },
    },
    # R6：判为「属性冲突」的条目必须登记在此（值一律不动，待裁定）。
    # 守卫 ③ 双向断言：登记里有 ⇒ note 里必须有「属性冲突」「待裁定」；
    # note 里写了「属性冲突」⇒ 登记里必须有。
    "derivation_conflicts": {
        "qubing_naicha": {
            "name": "去冰奶茶", "current": "cool", "derived": "neutral",
            "reason": "基底 茶（平）（无加工修正）＝平；项目保留了「去冰仍比热饮偏凉」的既有裁定。",
            "status": "待裁定",
        },
        "liangcha": {
            "name": "凉茶", "current": "cold", "derived": "cool",
            "reason": "草本基底（凉茶草药方）在表内无条目，现值按草本药性记寒。",
            "status": "待裁定",
        },
        "pijiu": {
            "name": "啤酒", "current": "cool", "derived": "neutral",
            "reason": "酒曲发酵（+1）与冰镇（-1）方向相反 —— 正是 R6 要标记的「不抵消」场景。",
            "status": "待裁定",
        },
        "shengyu": {
            "name": "生鱼片", "current": "cold", "derived": "cool",
            "reason": "生食只到 -1（档位不足），现值按「生鱼偏寒」记寒；拍板 D 取甲的代价。",
            "status": "待裁定",
        },
    },
}

# L2 派生的逐条 `note`（**只写 `note`，`nature` / `variant_nature` / `review_note` 一律不动**）。
# 内容区自动生成自 `docs/food-properties-b4-derivation.md` §4（评审依据），
# 由 `core/tests/test_b4_derivation_notes.py` 断言「数据 == 文档 §4」逐字一致。
# 写作纪律：去空格 ≥18 字（越过 NOTE_MAX_LEN ⇒ note 温度通道恒不生效）。
LAYER2_NOTES: dict[str, str] = {
    # --- B4 自动生成区：起 ---
    "suantou": "派生：基底 米（平）＋煮（蒸、卤）（档 轻，+0）＝平",
    "youtiao": "派生：基底 面（平）＋油炸（档 深，+2）＝热",
    "hanbao": "派生：基底 面（平）＋明火烧烤（档 中，+1）＝温；配料 牛肉（不跨档）",
    "sanmingzhi": "派生：基底 面（平）（无加工修正）＝平；配料 火腿（不跨档）",
    "yidali_mian": "派生：基底 面（平）＋煮（蒸、卤）（档 轻，+0）＝平",
    "shousi": "派生：基底 米（平）＋生食（-1）＝凉；配料 醋（调味，不抵消）",
    "niurou_hanbao": "派生：基底 面（平）＋明火烧烤（档 中，+1）＝温；配料 牛肉（不跨档）",
    "tusi": "派生：基底 面（平）＋定型烘焙（档 轻，+0）＝平",
    "sanmingzhi_huotui": "派生：基底 面（平）（无加工修正）＝平；配料 火腿（不跨档）",
    "mahuoguo": "派生：基底 复合（平起算）＋辛辣（+1）＋久煮焖烧（档 中，+1）＝热",
    "malatang": "派生：基底 复合（平起算）＋辛辣（+1）＋热汤（烫煮）（+1）＝热",
    "malahuoguo": "派生：基底 复合（平起算）＋辛辣（+1）＋久煮焖烧（档 中，+1）＝热",
    "shaokao": "派生：基底 牛（温）＋明火烧烤（档 中，+1）＋辛辣（+1）＝热",
    "hongshao": "派生：基底 猪（平）＋油糖酱焖烧（档 中，+1）＝温",
    "lajiao_chao": "派生：基底 复合（平起算）＋炒（档 中，+1）＋辛辣（+1）＝热",
    "zhajiang": "派生：基底 面（平）＋炒（档 中，+1）＝温",
    "guanzhudong": "派生：基底 复合（平起算）＋热汤（烫煮）（+1）＝温",
    "shala": "派生：基底 复合（平起算）＋生食（-1）＝凉",
    "pisa": "派生：基底 面（平）＋高温烘烤（档 中，+1）＝温；配料 奶酪（不跨档）",
    "zhaji": "派生：基底 鸡（温）＋油炸（档 深，+2）＝热",
    "shuijiao_rou": "派生：基底 米（平）＋辛辣（+1）＋热汤（烫煮）（+1）＝热",
    "huntun": "派生：基底 面（平）＋煮（蒸、卤）（档 轻，+0）＝平",
    "hanshi_zhaji": "派生：基底 鸡（温）＋油炸（档 深，+2）＋辛辣（+1）＝热",
    "zhayu_shutiao": "派生：基底 鱼（平）＋油炸（档 深，+2）＝热",
    "niuyouguo_shala": "派生：基底 复合（平起算）＋生食（-1）＝凉；配料 牛油果（平）",
    "hanshi_banfan": "派生：基底 米（平）＋辛辣（+1）＝温",
    "rishi_lamian": "派生：基底 面（平）＋热汤（烫煮）（+1）＝温",
    "gali": "派生：基底 复合（平起算）＋辛辣（+1）＋久煮焖烧（档 中，+1）＝热",
    "kele": "派生：基底 糖（平）＋冷藏（冰镇）（档 轻，-1）＝凉",
    "naicha": "派生：基底 茶（平）＋乳发酵（+0）＝平；配料 奶（不跨档）",
    "suanmeitang": "派生：基底 糖（平）（无加工修正）＝平；配料 乌梅（表值平）",
    "guozhi": "派生：基底 复合（平起算）＋生食（-1）＝凉",
    "bing_naicha": "派生：基底 茶（平）＋冷藏（冰镇）（档 轻，-1）＝凉",
    "re_naicha": "派生：基底 茶（平）＋热汤（烫煮）（+1）＝温",
    "dangao": "派生：基底 面（平）＋定型烘焙（档 轻，+0）＝平；配料 蛋、糖（不跨档）",
    "lvdougao": "派生：基底 绿豆（凉）＋煮（蒸、卤）（档 轻，+0）＝凉",
    "binggan": "派生：基底 面（平）＋高温烘烤（档 中，+1）＝温",
    "suannai_wan": "派生：基底 酸奶（平）＋冷藏（冰镇）（档 轻，-1）＝凉；配料 水果（不跨档）",
    "xila_suannai": "派生：基底 酸奶（平）＋冷藏（冰镇）（档 轻，-1）＝凉",
    "bingqilin": "派生：基底 牛奶（平）＋深度冷冻（档 深，-2）＝寒；配料 糖（不跨档）",
    "shujiaotiao": "派生：基底 土豆（平）＋油炸（档 深，+2）＝热",
    "chadan": "派生：基底 蛋（平）＋煮（蒸、卤）（档 轻，+0）＋配料茶叶（红茶温）（+1）＝温",
    "lourou": "派生：基底 猪（平）＋卤汁浓酱（档 中，+1）＝温",
    "huotui": "派生：基底 猪（平）＋腌制（档 方向不定，+0）＋明火烧烤（档 中，+1）＝温",
    "xiangchang": "派生：基底 猪（平）＋腌制（档 方向不定，+0）＋明火烧烤（档 中，+1）＝温",
    "puerg": "派生：基底 茶（平）＋酒曲发酵（+1）＝温",
    "wulong": "派生：基底 茶（平）＋半发酵（+0）＝平",
    "putaoyou_cha": "派生：基底 茶（平）＋冷藏（冰镇）（档 轻，-1）＝凉；配料 水果（不跨档）",
    "naixicha": "派生：基底 茶（平）＋乳发酵（+0）＝平；配料 奶盖（不跨档）",
    # ---- R6 冲突式（值不动，登记于 _meta.derivation_conflicts）----
    "qubing_naicha": "属性冲突：基底 茶（平）（无加工修正）＝平，项目值记凉。去冰后按规则应回平，但项目保留了「去冰仍比热饮偏凉」的既有裁定 ⇒ 按 R6 标记为属性冲突、保留项目值，待裁定。",
    "liangcha": "属性冲突：基底 复合（平起算）＋冷藏（冰镇）（档 轻，-1）＝凉，项目值记寒。草本基底（凉茶草药方）在表内无条目，现值按草本药性记寒 ⇒ 按 R6 标记为属性冲突、保留项目值，待裁定。",
    "pijiu": "属性冲突：基底 大麦（平）＋酒曲发酵（+1）＋冷藏（冰镇）（档 轻，-1）＝平，项目值记凉。酒曲发酵（+1）与冰镇（-1）方向相反 —— 正是 R6 要标记的「不抵消」场景 ⇒ 按 R6 标记为属性冲突、保留项目值，待裁定。",
    "shengyu": "属性冲突：基底 鱼（平）＋生食（-1）＝凉，项目值记寒。生食只到 -1（档位不足），现值按「生鱼偏寒」记寒；此为拍板 D 取甲的代价 ⇒ 按 R6 标记为属性冲突、保留项目值，待裁定。",
    # --- B4 自动生成区：止 ---
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    raw = json.loads(TABLE.read_text(encoding="utf-8"))
    groups = [
        ("foods", raw.get("foods", [])),
        ("tea_drinks", (raw.get("tea_drinks") or {}).get("items", [])),
    ]

    # ---------- 1. reviewed → review_status ----------
    migrated = 0
    already = 0
    for _, items in groups:
        for entry in items:
            if "review_status" in entry:
                already += 1
                continue
            # reviewed: true → approved；否则 pending
            entry["review_status"] = "approved" if entry.get("reviewed") else "pending"
            migrated += 1

    # ---------- 2. 条目修正 ----------
    fixes_applied: list[str] = []
    by_id = {}
    for group_name, items in groups:
        for entry in items:
            by_id[entry.get("id")] = entry

    for entry_id, patch in ENTRY_FIXES.items():
        entry = by_id.get(entry_id)
        if not entry:
            continue
        for key, value in patch.items():
            if entry.get(key) == value:
                continue
            entry[key] = value
            fixes_applied.append(f"{entry.get('name')}.{key}")

    # ---------- 2a. B4 · L2 派生 note ----------
    # 只写 `note`。若 `ENTRY_FIXES` 与本表命中同一 id，`ENTRY_FIXES` 先写、这里后写 ⇒
    # 二者必须**互不重叠**（当前无重叠：B4 的 53 条里，shengyu/shousi/shujiaotiao/kafei
    # 虽在 ENTRY_FIXES 中，但被改的是 keywords / review_note，不是 note）。
    # 引用了不存在的 id 直接报错 —— 不给静默通过的机会（拼错 id 会变成"这条没写"）。
    missing = [i for i in LAYER2_NOTES if i not in by_id]
    if missing:
        raise SystemExit(f"LAYER2_NOTES 引用了不在数据表的 id：{missing}")
    notes_applied: list[str] = []
    for entry_id, note in LAYER2_NOTES.items():
        entry = by_id[entry_id]
        if entry.get("note") == note:
            continue
        entry["note"] = note
        notes_applied.append(entry.get("name") or entry_id)

    # ---------- 2b. B4 · `_meta` 规则登记 ----------
    meta = raw.setdefault("_meta", {})
    meta_applied: list[str] = []
    for meta_key, meta_value in META_PATCH.items():
        if meta.get(meta_key) == meta_value:
            continue
        meta[meta_key] = meta_value
        meta_applied.append(meta_key)

    # ---------- 2c. 新增条目（拆条） ----------
    # 注意：foods 与 groups 里的是**同一个列表对象**，insert 之后后面的统计与校验
    # 会自动带上新条目，不需要再手动同步。
    foods = raw.get("foods", [])
    added: list[str] = []
    for entry_id, spec in NEW_ENTRIES.items():
        if entry_id in by_id:
            continue
        new_entry = {k: v for k, v in spec.items() if not k.startswith("_")}
        anchor = spec.get("_after")
        index = next((i for i, e in enumerate(foods) if e.get("id") == anchor), len(foods) - 1)
        foods.insert(index + 1, new_entry)
        by_id[entry_id] = new_entry
        added.append(f"{new_entry['name']}（{entry_id}，插在 {anchor} 之后）")

    # ---------- 2c. 统一字段顺序 ----------
    reordered = 0
    for _, items in groups:
        for i, entry in enumerate(items):
            normalized = normalize_key_order(entry)
            if list(normalized) != list(entry):
                items[i] = normalized
                reordered += 1

    # ---------- 3. 校验 ----------
    problems: list[str] = []
    for _, items in groups:
        for entry in items:
            status = entry.get("review_status")
            if status not in VALID_STATUS:
                problems.append(f"{entry.get('name')}: review_status={status!r} 非法")
    print("=" * 66)
    print("数据表结构升级与条目修正")
    print("=" * 66)
    print(f"  review_status 迁移：{migrated} 条（已有 {already} 条）")
    print(f"  条目修正：{len(fixes_applied)} 处")
    for f in fixes_applied:
        print(f"    - {f}")
    print(f"  B4 派生 note：写入 {len(notes_applied)} 条（共 {len(LAYER2_NOTES)} 条登记）")
    for name in notes_applied:
        print(f"    ~ {name}")
    print(f"  B4 `_meta` 登记：{len(meta_applied)} 块"
          + (f"（{', '.join(meta_applied)}）" if meta_applied else "（已是最新）"))
    print(f"  新增条目：{len(added)} 条")
    for a in added:
        print(f"    + {a}")
    print(f"  字段顺序归一：{reordered} 条")
    if problems:
        print(f"  校验问题：{len(problems)} 处")
        for p in problems:
            print(f"    ! {p}")

    counts = {"approved": 0, "pending": 0, "rejected": 0}
    for _, items in groups:
        for entry in items:
            counts[entry.get("review_status", "pending")] = counts.get(entry.get("review_status", "pending"), 0) + 1

    print(f"\n  审核状态分布：已通过 {counts.get('approved', 0)} / "
          f"待审核 {counts.get('pending', 0)} / 不通过 {counts.get('rejected', 0)}")

    if args.dry_run:
        print("\n  [dry-run] 未写入。")
        return 0

    TABLE.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",  # 强制 LF，避免 Windows 默认 CRLF 在 git 里造成假 diff
    )
    print("\n  已写入。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
