"""生成食性表（food_properties.json）的**人工审核核验单**。

用法（在 core 目录下）：

    python scripts/build_food_review_sheet.py                     # 打印摘要 + ④层矛盾
    python scripts/build_food_review_sheet.py --out ../docs/food-properties-review-sheet.md
    python scripts/build_food_review_sheet.py --check             # 校验产物是否过期（可进 CI）
    python scripts/build_food_review_sheet.py --strict            # 有④层矛盾则 exit 1

本脚本是**只读**的：不修改 food_properties.json，也不改任何审核状态。
它不替人做审核决定。

## 它解决什么问题

`docs/pending-items.md` 的 A1 要求 146 条逐条人工审核（`approved` 必须由具备资质的
中医师/中药师填，并同时填 `reviewed_by` / `reviewed_at`）。难点是：**食材偏性没有官方
标准**——药典只管药材（34 味有官方接口可比），GB/T 46939 只管体质分类与判定阈值。
食材四气只有「中医饮食养生通行表述」。所以这项工作的形态不是「造数据」，而是
**核验已有数据**，产物必须让审核人只聚焦有争议的格子，而不是 146 条从零判断。

## 四层分级

    ①  来源一致    找到权威/通行来源且与现值一致   → 审核人可直接 approved
    ②  来源冲突    来源之间或来源与现值不一致       → 进问题清单（按优先级排队）
    ③  无来源      找不到任何可引来源               → 标「无源可引」，凭专业判断
    ④  内部矛盾    表内自相矛盾（与外部来源无关）   → **本阶段脚本可查，属 bug 类**

④ 层不依赖任何外部来源，所以脚本当场就能全部跑出来；①②③ 层需要外部来源，
属阶段二（口径甲：官方食养指南优先 → 多源交叉兜底 → 无来源标空）。
本脚本先产出**骨架 + ④层清单**，①②③ 层的列留空待填。

⚠️ 产物里 `approved` 永远是 0，直到真的有人审核。**不要为了让界面好看批量置 approved**
——标记密度就是审核进度的可见反馈（`docs/maintenance.md` §9.3）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CORE_DIR = Path(__file__).resolve().parent.parent
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

# Windows 控制台默认 GBK，中文会乱码
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass

# 温度前缀刻意复用领域层那一套常量，不在这里另写一份 ——
# 新增前缀只改 nature_math 一处（那里有完整注释说明「热干面」这类误伤为何被排除）。
from app.domain.nature_math import CHILL_PREFIXES, HEAT_PREFIXES  # noqa: E402

DEFAULT_FOOD = CORE_DIR / "data" / "food_properties.json"
DEFAULT_HERBS = CORE_DIR / "data" / "herbs.json"
DEFAULT_OUT = CORE_DIR.parent / "docs" / "food-properties-review-sheet.md"

NATURE_ORDER = ("cold", "cool", "neutral", "warm", "hot")
NATURE_CN = {"cold": "寒", "cool": "凉", "neutral": "平", "warm": "温", "hot": "热"}
NATURE_RANK = {n: i - 2 for i, n in enumerate(NATURE_ORDER)}

# 处理方式 → 通用兜底增量。与数据文件 _meta.nature_change_rules / correction_layers
# 的 layer_2 一致；layer_1（条目 variant_nature）优先，命中时不走这里。
LAYER2_DELTA = {
    "cold": -1,
    "deep_fried": 1,
    "grilled": 1,
    "stir_fried": 1,
    "boiled": 0,
    "steamed": 0,
    "raw": 0,
}

# 第一批：优先挑官方食养指南/膳食指南覆盖得到的大类，先让 A1 的验收标准动起来
# （验收要求 approved > 0）。菜肴/饮料/冷饮/甜点这类最易错，放后面。
FIRST_BATCH_CATEGORIES = ("主食", "乳饮", "水产")

VALID_REVIEW_STATUS = ("pending", "approved", "rejected")


# ---------------------------------------------------------------------------
# 载入
# ---------------------------------------------------------------------------
def load_foods(path: Path) -> tuple[dict, list[dict]]:
    """返回 (文件级 _meta, 全部条目)。茶饮在 tea_drinks.items 里，不是平铺列表。"""
    raw = json.loads(path.read_text(encoding="utf-8"))
    entries: list[dict] = []
    for item in raw.get("foods", []):
        entries.append({**item, "_group": "foods"})
    for item in (raw.get("tea_drinks") or {}).get("items", []):
        entries.append({**item, "_group": "tea_drinks"})
    return raw.get("_meta", {}), entries


def load_herb_nature(path: Path) -> dict[str, str]:
    """饮片名 → 项目四气。用于跨表一致性核对。"""
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {item["name"]: item.get("nature") for item in raw.get("herbs", [])}


def review_status_of(entry: dict) -> str:
    """读审核状态，带兼容回退。

    回退规则与 `food_lookup.py` 一致（那边是 `status = "approved" if entry.get("reviewed")
    else "pending"`）：缺 review_status 的条目按旧布尔字段判。三态迁移之后新加的条目
    漏走迁移时就是靠这条回退才不会行为异常（见 pending-items E1）。
    """
    status = entry.get("review_status")
    if status is None:
        return "approved" if entry.get("reviewed") else "pending"
    return str(status)


# ---------------------------------------------------------------------------
# ④ 层：内部矛盾 / 存疑（不依赖任何外部来源）
# ---------------------------------------------------------------------------
def check_duplicate_keys(entries: list[dict]) -> list[dict]:
    issues: list[dict] = []
    for field in ("id", "name"):
        seen: dict[str, list[str]] = {}
        for e in entries:
            seen.setdefault(str(e.get(field, "")), []).append(e["id"])
        dup = {k: v for k, v in seen.items() if len(v) > 1}
        if dup:
            issues.append(
                {
                    "kind": "重复",
                    "level": "矛盾",
                    "headline": f"{field} 重复",
                    "rows": [f"`{k}` 出现在 {len(v)} 条：{'、'.join(v)}" for k, v in dup.items()],
                    "detail": "查表按 name/id 定位，重复会让匹配结果取决于遍历顺序。",
                    "action": "改数据：给重复项区分命名或合并。",
                }
            )
    return issues


def check_alias_ambiguity(entries: list[dict]) -> list[dict]:
    """同一个别名指向多条不同条目。

    只有**四气不同**时才算真矛盾：指向两条但属性一致，顶多是重复登记，
    不会让判定结果随遍历顺序漂移。
    """
    index: dict[str, list[dict]] = {}
    for e in entries:
        for key in [e.get("name", "")] + list(e.get("aliases", [])):
            if key:
                index.setdefault(key, []).append(e)

    rows, same_rows = [], []
    for key, group in index.items():
        ids = {e["id"] for e in group}
        if len(ids) < 2:
            continue
        natures = {e.get("nature") for e in group}
        line = f"`{key}` → " + "、".join(f"{e['id']}（{NATURE_CN.get(e.get('nature'), '?')}）" for e in group)
        (rows if len(natures) > 1 else same_rows).append(line)

    issues: list[dict] = []
    if rows:
        issues.append(
            {
                "kind": "别名歧义",
                "level": "矛盾",
                "headline": "同一别名指向多条**属性不同**的条目",
                "rows": sorted(rows),
                "detail": (
                    "用户说这个词时，命中哪一条取决于遍历顺序；两条四气不同，"
                    "判定结果会不稳定（`maintenance.md` §10.11 记录过同类现象）。"
                ),
                "action": "改数据：让别名只留在最贴切的那一条上，或干脆拆分/合并条目。",
            }
        )
    if same_rows:
        issues.append(
            {
                "kind": "别名重复登记",
                "level": "存疑",
                "headline": "同一别名指向多条条目（属性一致）",
                "rows": sorted(same_rows),
                "detail": "属性一致，不影响判定结果；但会让 diff 与维护更难读。",
                "action": "可不改，或顺手清理。",
            }
        )
    return issues


def check_variant_against_rules(entries: list[dict]) -> list[dict]:
    """条目自带的 variant_nature（layer_1）与通用兜底规则（layer_2）是否打架。

    layer_1 是精确值、优先级更高，所以**不算错**；但两者差得越多，
    越值得人看一眼——因为一旦哪天删掉 variant_nature，兜底会给出另一个答案。
    """
    issues: list[dict] = []
    for e in entries:
        variants = e.get("variant_nature") or {}
        if not variants:
            continue
        base = e.get("nature")
        if base not in NATURE_RANK:
            continue
        for method, declared in variants.items():
            if method not in LAYER2_DELTA:
                issues.append(
                    {
                        "kind": "变体无法校验",
                        "level": "存疑",
                        "headline": f"`{e['id']}` 的 variant_nature 用了规则表里没有的处理方式",
                        "rows": [f"`{method}` → {declared}（`nature_change_rules` 无 `{method}`）"],
                        "detail": "没有兜底规则可比，无法判断该值是否合理。",
                        "action": "人工确认该处理方式与取值，必要时补进 nature_change_rules。",
                    }
                )
                continue
            expect = NATURE_ORDER[max(0, min(4, NATURE_RANK[base] + LAYER2_DELTA[method] + 2))]
            if declared != expect:
                issues.append(
                    {
                        "kind": "变体与规则不一致",
                        "level": "矛盾",
                        "headline": f"`{e['id']}`（{e.get('name')}）的变体属性与兜底规则不一致",
                        "rows": [
                            f"本味四气 {NATURE_CN[base]}，处理方式 `{method}` 按规则应得 "
                            f"**{NATURE_CN[expect]}**，但 variant_nature 记的是 **{NATURE_CN.get(declared, declared)}**"
                        ],
                        "detail": (
                            "layer_1 优先，所以当前判定用的是记录值，**不是 bug**；"
                            "但删掉 variant_nature 就会漂到另一个答案，说明两者必有一个要改。"
                        ),
                        "action": "人工定：改 variant_nature，还是把该味的 base nature 改对。",
                    }
                )
    return issues


def _strip_temperature_prefix(name: str) -> tuple[int, str] | None:
    """名字带温度前缀时返回 (增量, 去掉前缀的净名字)。"""
    text = (name or "").replace(" ", "").strip()
    for delta, prefixes in ((-1, CHILL_PREFIXES), (1, HEAT_PREFIXES)):
        for prefix in sorted(prefixes, key=len, reverse=True):
            if text.startswith(prefix) and len(text) > len(prefix):
                return delta, text[len(prefix):]
    return None


def check_temperature_siblings(entries: list[dict]) -> list[dict]:
    """「冰奶茶 / 热奶茶」这类独立条目，与基条目（奶茶）的差值是否符合温度规则。

    这是把**代码里的规则**（`nature_math`：冰镇 -1、加热 +1）反过来对数据做体检：
    同一种饮品被拆成多条独立条目时，很容易各写各的，与规则脱节。
    与 `variant_nature` 那条不同，这里检查的是**条目之间**的关系。
    """
    by_name = {e.get("name"): e for e in entries}
    rows, notes = [], []
    for e in entries:
        parsed = _strip_temperature_prefix(e.get("name", ""))
        if not parsed:
            continue
        delta, base = parsed
        parent = by_name.get(base)
        if not parent:
            continue
        if e.get("nature") not in NATURE_RANK or parent.get("nature") not in NATURE_RANK:
            continue
        actual = NATURE_RANK[e["nature"]] - NATURE_RANK[parent["nature"]]
        line = (
            f"`{e['id']}`（{NATURE_CN[e['nature']]}）vs 基条目 `{parent['id']}`"
            f"（{NATURE_CN[parent['nature']]}）：实际差 {actual:+d}，规则要求 {delta:+d}"
        )
        (rows if actual != delta else notes).append({**e, "_line": line})

    issues: list[dict] = []
    if rows:
        issues.append(
            {
                "kind": "温度变体不一致",
                "level": "矛盾",
                "headline": "独立条目的温度差值与代码规则不符",
                "rows": [r["_line"] for r in rows],
                "detail": "规则在 `nature_math`（冰镇 -1 / 加热 +1），数据侧必须跟着走。",
                "action": "改数据：对齐基条目四气或调整该条目。",
            }
        )
    if notes:
        issues.append(
            {
                "kind": "温度变体（已核对）",
                "level": "正常",
                "headline": "温度变体与规则一致（列出备查）",
                "rows": [r["_line"] for r in notes],
                "detail": "与 `nature_math` 的单档温度增减一致。",
                "action": "无需处理。",
            }
        )
    return issues


def check_schema_fields(entries: list[dict]) -> list[dict]:
    """字段齐备性：审核字段、category。

    这类问题不改判定结果，但会让「只读某一字段的脚本」静默漏条目
    （pending-items E1 就是这个形态）。
    """
    issues: list[dict] = []
    base_fields = [e for e in entries if e["_group"] == "foods"]

    missing_status = [e for e in entries if "review_status" not in e]
    if missing_status:
        issues.append(
            {
                "kind": "缺 review_status",
                "level": "矛盾",
                "headline": "条目缺合法三态 `review_status`",
                "rows": [
                    f"`{e['id']}`（{e['name']}）只有旧布尔 `reviewed={e.get('reviewed')}`"
                    for e in missing_status
                ],
                "detail": (
                    "运行时靠 `food_lookup.py` 的兼容回退照常当 pending 处理，**行为已正确**；"
                    "风险是以后有人写脚本只读 `review_status` 就会漏掉这几条（pending-items E1）。"
                ),
                "action": "改数据：跑一次 `python scripts/patch_food_table.py`（先 --dry-run）。",
            }
        )

    illegal = [e for e in entries if review_status_of(e) not in VALID_REVIEW_STATUS]
    if illegal:
        issues.append(
            {
                "kind": "非法状态值",
                "level": "矛盾",
                "headline": "`review_status` 取值不在三态之内",
                "rows": [f"`{e['id']}` → {e.get('review_status')!r}" for e in illegal],
                "detail": "三态之外的取值会让「按状态筛选」静默落空。",
                "action": "改数据：改为 pending/approved/rejected 之一。",
            }
        )

    no_category = [e for e in base_fields if "category" not in e]
    tea_no_category = [e for e in entries if e["_group"] == "tea_drinks" and "category" not in e]
    if no_category or tea_no_category:
        rows = [f"`{e['id']}`（{e['name']}）" for e in no_category + tea_no_category]
        issues.append(
            {
                "kind": "缺 category",
                "level": "存疑",
                "headline": "条目没有 `category`，按类兜底对它们失效",
                "rows": rows,
                "detail": (
                    "`_meta.field_notes.category` 写着「便于按类兜底判断」。"
                    "茶饮整体不带 category（结构不对称），不是判定错误，但兜底路径覆盖不到它们。"
                ),
                "action": "人工定：是否给茶饮补 category，或改用 tea_drinks 这一层做兜底。",
            }
        )
    return issues


def check_cross_table(entries: list[dict], herb_nature: dict[str, str]) -> list[dict]:
    """跨表一致性：茶饮条目 vs `herbs.json` 里的同名饮片。

    同一味东西在两个文件里出现（茉莉花茶 vs 茉莉花饮片），四气必须一致，
    否则同一个人在两处会拿到相反的方向。这是**可机器校验**的，不需要外部来源。
    """
    rows, mismatched = [], []
    for e in entries:
        name = e.get("name", "")
        base = name[:-1] if name.endswith("茶") else name
        if base not in herb_nature:
            continue
        herb = herb_nature[base]
        line = f"`{e['id']}`（{name}）{NATURE_CN.get(e.get('nature'), '?')} vs 饮片 `{base}` {NATURE_CN.get(herb, herb)}"
        (mismatched if e.get("nature") != herb else rows).append(line)

    issues: list[dict] = []
    if mismatched:
        issues.append(
            {
                "kind": "跨表不一致",
                "level": "矛盾",
                "headline": "茶饮条目与同名饮片的四气不一致",
                "rows": mismatched,
                "detail": "同一物在两个文件里属性不同，用户在两处会拿到相反方向。",
                "action": "改数据：以饮片（有药典可核）为准对齐。",
            }
        )
    if rows:
        issues.append(
            {
                "kind": "跨表一致性（已核对）",
                "level": "正常",
                "headline": "茶饮条目与同名饮片四气一致（列出备查）",
                "rows": rows,
                "detail": "这是本表与 `herbs.json` 之间可用机器守住的唯一硬关系。",
                "action": "无需处理。",
            }
        )
    return issues


def run_checks(entries: list[dict], herb_nature: dict[str, str]) -> list[dict]:
    issues: list[dict] = []
    issues += check_duplicate_keys(entries)
    issues += check_alias_ambiguity(entries)
    issues += check_variant_against_rules(entries)
    issues += check_temperature_siblings(entries)
    issues += check_schema_fields(entries)
    issues += check_cross_table(entries, herb_nature)
    return issues


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------
def category_order(entries: list[dict]) -> list[str]:
    """第一批优先，其余按条目数降序 —— 让审核人先做能推动验收标准的那批。"""
    counts: dict[str, int] = {}
    for e in entries:
        counts[e.get("category", "（无 category）")] = counts.get(e.get("category", "（无 category）"), 0) + 1

    def sort_key(cat: str) -> tuple[int, int, str]:
        return (0 if cat in FIRST_BATCH_CATEGORIES else 1, -counts[cat], cat)

    return sorted(counts, key=sort_key)


def render(entries: list[dict], meta: dict, issues: list[dict], source_path: Path) -> str:
    lines: list[str] = []
    add = lines.append

    total = len(entries)
    n_foods = sum(1 for e in entries if e["_group"] == "foods")
    n_tea = total - n_foods
    status_counts: dict[str, int] = {}
    for e in entries:
        status_counts[review_status_of(e)] = status_counts.get(review_status_of(e), 0) + 1

    contradictions = [i for i in issues if i["level"] == "矛盾"]
    doubts = [i for i in issues if i["level"] == "存疑"]
    oks = [i for i in issues if i["level"] == "正常"]

    add("# 食性表人工审核核验单（`food_properties.json`）")
    add("")
    add("> ⚠️ **本文件由脚本生成，请勿手工编辑。**")
    add(f"> 生成命令：`cd core && python scripts/build_food_review_sheet.py --out ../docs/"
        f"{DEFAULT_OUT.name}`")
    add(f"> 数据源：`core/data/{source_path.name}`（本脚本只读，不改数据、不改审核状态）")
    add("> 对应挂起项：`docs/pending-items.md` **A1**（食性表 146 条全部未人工审核）")
    add("")
    add("## 0. 这份单子的用法（先读）")
    add("")
    add("A1 不是「造数据」，是**核验已有数据**：146 条的 `nature` / `flavors` 早已填好，")
    add("全部是 `pending`。终局动作（`approved` + `reviewed_by` / `reviewed_at`）**只有具备资质的**")
    add("中医师/中药师能做，脚本不替你判定。")
    add("")
    add("难点在于**食材偏性没有官方标准**：药典只管药材（34 味有官方接口可比），")
    add("GB/T 46939 只管体质分类与判定阈值。食材四气只有「中医饮食养生通行表述」。")
    add("所以本单子把 146 条分四层，让审核人只看值得看的格子：")
    add("")
    add("| 层 | 含义 | 谁来做 | 现状 |")
    add("|---|---|---|---|")
    add("| ① 来源一致 | 找到权威/通行来源且与现值一致 | 脚本抓取 + 人工确认 | 阶段二 |")
    add("| ② 来源冲突 | 来源之间或来源与现值不一致 | 人工裁决 | 阶段二 |")
    add("| ③ 无来源 | 找不到可引来源，标「无源可引」 | 人工凭专业判断 | 阶段二 |")
    add("| ④ 内部矛盾 | 表内自相矛盾，与外部来源无关 | **本脚本已跑完**（§2） | ✅ 见 §2 |")
    add("")
    add("来源口径（**已定**）：**官方优先 + 多源兜底 + 无源标空**——优先引国家卫健委 /")
    add("中国营养学会的食养指南与膳食指南；其次 2–3 个通行来源交叉一致；都找不到就明确标")
    add("「无源可引」。**不把通行表述伪装成权威依据。**")
    add("")
    add("⚠️ 产物里 `approved` 永远是 0，直到真的有人审核。**不要为了让界面好看批量置 approved**")
    add("——标记密度就是审核进度的可见反馈（`docs/maintenance.md` §9.3）。")
    add("")

    add("## 1. 现状")
    add("")
    add("| 项 | 值 |")
    add("|---|---|")
    add(f"| 总条数 | **{total}**（`foods` {n_foods} + `tea_drinks.items` {n_tea}） |")
    add(f"| 审核状态 | " + "、".join(f"{k} **{v}**" for k, v in sorted(status_counts.items())) + " |")
    missing_status = [e for e in entries if "review_status" not in e]
    add(f"| 其中实际缺 `review_status` 字段 | **{len(missing_status)}** 条（上表按兼容回退计为 pending，"
        f"见 §2） |")
    add(f"| 文件级 `_meta.review_status` | `{meta.get('review_status')}` |")
    add(f"| ④ 层：矛盾 | **{len(contradictions)}** 类 |")
    add(f"| ④ 层：存疑 | {len(doubts)} 类 |")
    add(f"| ④ 层：已核对正常 | {len(oks)} 类 |")
    add("")
    add("按类分布（★ = 第一批，优先审）：")
    add("")
    add("| 类别 | 条数 | 审核状态 |")
    add("|---|---|---|")
    for cat in category_order(entries):
        group = [e for e in entries if e.get("category", "（无 category）") == cat]
        st: dict[str, int] = {}
        for e in group:
            st[review_status_of(e)] = st.get(review_status_of(e), 0) + 1
        mark = "★ " if cat in FIRST_BATCH_CATEGORIES else ""
        add(f"| {mark}{cat} | {len(group)} | " + "、".join(f"{k} {v}" for k, v in sorted(st.items())) + " |")
    add("")

    add("## 2. ④ 层：内部矛盾 / 存疑（机器可查，已跑完）")
    add("")
    add("这一层不依赖任何外部来源，所以脚本当场就能跑完。**矛盾类必须先处理**——")
    add("它们与审核无关，是数据自身或数据与代码的关系出了问题。")
    add("")
    if not contradictions and not doubts:
        add("未发现问题。")
        add("")
    for issue in contradictions + doubts:
        icon = "🔴" if issue["level"] == "矛盾" else "🟡"
        add(f"### {icon} {issue['headline']}")
        add("")
        add(f"- **类型**：`{issue['kind']}`　**级别**：{issue['level']}")
        for row in issue["rows"]:
            add(f"  - {row}")
        add(f"- **为什么算问题**：{issue['detail']}")
        add(f"- **该怎么处理**：{issue['action']}")
        add("")

    add("### ✅ 已核对正常（备查）")
    add("")
    for issue in oks:
        add(f"- **{issue['headline']}**（`{issue['kind']}`）")
        for row in issue["rows"]:
            add(f"  - {row}")
    add("")
    add("> 附带一个**规则层面**的观察（不在 A1 范围内，只记录）：温度前缀表把「去冰」也当成")
    add("> 降温前缀（`nature_math.CHILL_PREFIXES`，-1），所以 `去冰奶茶` 记「凉」与代码是自洽的。")
    add("> 但「去掉冰」按直觉应接近常温，这里规则与直觉有出入——属于规则讨论，要改就改")
    add("> `nature_math` 那一处前缀表，与本次数据审核无关。")
    add("")

    add("## 3. 核验单骨架（146 条）")
    add("")
    add("阶段二的来源核对结果填进最后两列。**「无源可引」也是一个合法结论**，")
    add("不要为了让格子好看而硬找来源。")
    add("")
    for cat in category_order(entries):
        group = [e for e in entries if e.get("category", "（无 category）") == cat]
        mark = "★ 第一批" if cat in FIRST_BATCH_CATEGORIES else ""
        add(f"### {cat}（{len(group)} 条）{mark}")
        add("")
        add("| # | id | 名称 | 四气 | 五味 | 审核状态 | 来源核对（阶段二） | 判定（阶段二） |")
        add("|---|---|---|---|---|---|---|---|")
        for i, e in enumerate(group, 1):
            natures = NATURE_CN.get(e.get("nature"), e.get("nature") or "—")
            flavors = "、".join(e.get("flavors") or []) or "—"
            status = review_status_of(e)
            flag = "⚠️ 缺字段" if "review_status" not in e else status
            add(f"| {i} | `{e['id']}` | {e.get('name')} | {natures} | {flavors} | {flag} | | |")
        add("")

    add("## 4. 阶段二作业口径（已定：官方优先 + 多源兜底 + 无源标空）")
    add("")
    add("| 优先级 | 来源 | 说明 |")
    add("|---|---|---|")
    add("| 1 | 国家卫健委 / 中国营养学会的**食养指南与膳食指南** | 半官方、可引用性最高；但按疾病/人群编写，**不按食材列四气**，覆盖不全 |")
    add("| 2 | 中医饮食养生**通行表述**的多源交叉 | 2–3 源一致才记「来源一致」；结论只能是「来源一致」，**不能**写成「正确」 |")
    add("| 3 | 找不到任何来源 | 标**「无源可引」**，留给审核人凭专业判断 |")
    add("")
    add("两条纪律：")
    add("")
    add("1. **不把通行表述伪装成权威依据**——引用时必须写清是第 2 档来源，不得混入指南口径。")
    add("2. **第一批只做 ★ 主食 / 乳饮 / 水产**：这些大类在指南里覆盖最好，最可能先产出 `approved`，")
    add("   让 A1 的验收标准（`approved > 0`）先动起来。菜肴 / 饮料 / 冷饮 / 甜点最易错，放后面。")
    add("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _summarize(issues: list[dict]) -> str:
    out = []
    for level, icon in (("矛盾", "🔴"), ("存疑", "🟡"), ("正常", "✅")):
        for issue in issues:
            if issue["level"] == level:
                out.append(f"  {icon} [{issue['kind']}] {issue['headline']}（{len(issue['rows'])} 条）")
                for row in issue["rows"][:6]:
                    out.append(f"      - {row}")
                if len(issue["rows"]) > 6:
                    out.append(f"      … 另有 {len(issue['rows']) - 6} 条")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="生成食性表人工审核核验单（只读，不修改任何数据）"
    )
    parser.add_argument("--food", type=Path, default=DEFAULT_FOOD, help="food_properties.json 路径")
    parser.add_argument("--herbs", type=Path, default=DEFAULT_HERBS, help="herbs.json 路径（跨表核对用）")
    parser.add_argument("--out", type=Path, default=None,
                        help=f"写入文件（默认只打印；约定路径 {DEFAULT_OUT}）")
    parser.add_argument("--check", action="store_true",
                        help="校验 --out 指到的产物是否与当前数据一致（可进 CI）")
    parser.add_argument("--strict", action="store_true",
                        help="存在④层「矛盾」时返回 exit 1")
    args = parser.parse_args(argv)

    if not args.food.exists():
        print(f"[失败] 找不到食性表: {args.food}", file=sys.stderr)
        return 2

    meta, entries = load_foods(args.food)
    herb_nature = load_herb_nature(args.herbs)
    issues = run_checks(entries, herb_nature)
    text = render(entries, meta, issues, args.food)

    contradictions = [i for i in issues if i["level"] == "矛盾"]

    if args.check:
        target = args.out or DEFAULT_OUT
        if not target.exists():
            print(f"[失败] 产物不存在: {target}（先跑一次 --out 生成）", file=sys.stderr)
            return 1
        on_disk = target.read_text(encoding="utf-8")
        if on_disk != text:
            print(f"[失败] 产物已过期: {target}", file=sys.stderr)
            print("        数据变了但核验单没重新生成，请重跑一次 --out", file=sys.stderr)
            return 1
        print(f"[通过] 产物与当前数据一致: {target}")
        return 0

    print(f"食性表：{len(entries)} 条（foods "
          f"{sum(1 for e in entries if e['_group'] == 'foods')} + tea_drinks "
          f"{sum(1 for e in entries if e['_group'] == 'tea_drinks')}）")
    print(f"审核状态：", end="")
    st: dict[str, int] = {}
    for e in entries:
        st[review_status_of(e)] = st.get(review_status_of(e), 0) + 1
    print("、".join(f"{k} {v}" for k, v in sorted(st.items())))
    print(f"④ 层：矛盾 {len(contradictions)} 类 / 存疑 {len([i for i in issues if i['level'] == '存疑'])} 类")
    print()
    print(_summarize(issues))
    print()

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8", newline="\n")
        print(f"[已写入] {args.out}（{len(text.splitlines())} 行）")

    if args.strict and contradictions:
        print(f"[失败] --strict：存在 {len(contradictions)} 类④层矛盾", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
