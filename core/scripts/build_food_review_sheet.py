"""生成食性表（food_properties.json）的**人工审核核验单**。

用法（在 core 目录下）：

    python scripts/build_food_review_sheet.py                     # 打印摘要 + ④层矛盾
    python scripts/build_food_review_sheet.py --out ../docs/food-properties-review-sheet.md
    python scripts/build_food_review_sheet.py --check             # 校验产物是否过期（可进 CI）
    python scripts/build_food_review_sheet.py --strict            # 有矛盾则 exit 1

本脚本是**只读**的：不修改 food_properties.json，也不改任何审核状态。
它不替人做审核决定。

## 它解决什么问题

`docs/pending-items.md` 的 A1 要求 147 条逐条人工审核（`approved` 必须由具备资质的
中医师/中药师填，并同时填 `reviewed_by` / `reviewed_at`）。难点是：**食材偏性没有官方
标准**——药典只管药材（34 味有官方接口可比），GB/T 46939 只管体质分类与判定阈值。
食材四气只有「中医饮食养生通行表述」。所以这项工作的形态不是「造数据」，而是
**核验已有数据**，产物必须让审核人只聚焦有争议的格子，而不是 147 条从零判断。

## 四层分级

    ①  来源一致    找到权威/通行来源且与现值一致   → 审核人可据此 approved
    ②  来源冲突    来源之间或来源与现值不一致       → 进问题清单（按优先级排队）
    ③  无来源      找不到任何可引来源               → 标「无源可引」，凭专业判断
    ④  内部矛盾    表内自相矛盾（与外部来源无关）   → 脚本可查，属 bug 类

④ 层不依赖任何外部来源，脚本当场能跑完；①②③ 层的事实源是
`docs/food-properties-sources.json`（逐条登记来源与原文，**由人工逐条裁定映射**），
本脚本读它并把三层渲染进 §4。

⚠️ 「第一批」不再是**类别**的属性（曾按「主食/乳饮/水产」硬编码，那条理由已被证伪：
全表能沾到官方来源的只有 4 条）。现在它是 **`sources.json` 里 `batch` 字段的属性** ——
判据是「有来源可引」，与类别无关。

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
DEFAULT_SOURCES = CORE_DIR.parent / "docs" / "food-properties-sources.json"
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

# 「第一批」的定义已改：不再是**类别**的属性，而是 `docs/food-properties-sources.json`
# 里 `batch == 第一批` 的条目（判据＝**有来源可引**）。
# 旧定义（写死"主食/乳饮/水产"）的理由是"官方食养指南覆盖得到"——**已证伪**：
# 全表能沾到官方来源的只有 4 条，那三个大类恰恰是加工品最密集、最没来源的区段。
BATCH_PRIMARY = "第一批"
SOURCE_LAYERS = ("①", "②", "③", "④")

VALID_REVIEW_STATUS = ("pending", "approved", "rejected")

# §4 的「来源优先级」图例。**数据化，不写死在渲染里** ——
# B1／B2 都没新增过 `tier`，所以这块一直没露头；B3 首次新增 4 个档时才发现图例原先是
# 一串硬编码字符串、且没有任何守卫：不补则核验单 §4 的图例与 `_meta` **静默不一致**
# （审核人在 §4.1 看到「官方·审核词条」，图例里却查不到这个档）。
# 每行的 `tiers` 声明它覆盖哪些 `evidence[].tier`，由 `priority_legend_gaps()` 核对。
PRIORITY_LEGEND: tuple[dict, ...] = (
    {"priority": "①", "source": "《中国药典》2020 年版一部", "strength": "最高",
     "usage": "可直接采用（**药品**标准用作食品参考，须注明）", "tiers": ("官方·药典",)},
    {"priority": "①", "source": "食药物质目录（106 种）", "strength": "**仅合规身份**",
     "usage": "**只证明合规身份，不含四气，永不作四气基准**", "tiers": ("官方·目录(仅身份)",)},
    {"priority": "②", "source": "官方·审核词条（国家中医药管理局名词术语项目审核认证词条）",
     "strength": "高（低于药典、高于教材）",
     "usage": "可直接采用；须引词条页 URL 与原文句（**认证属国家局项目、平台承载页面**）",
     "tiers": ("官方·审核词条",)},
    {"priority": "②", "source": "《中医饮食营养学》（50 号文件 §2 A 档 / §3 B 档）", "strength": "次高",
     "usage": "可直接采用，须引原文列", "tiers": ("通行·教材", "通行·教材(有冲突)")},
    {"priority": "②", "source": "官方·卫健科普 / 通行·官媒科普 / 通行·医院科普",
     "strength": "中（**仅当药典与教材均无该条目时**可作基准）",
     "usage": "政府/官媒/医院**科普**；网页来源不随仓库归档，链接可能失效",
     "tiers": ("官方·卫健科普", "通行·官媒科普", "通行·医院科普")},
    {"priority": "②", "source": "§5.3 别名索引（含《本草纲目》《中药学》）", "strength": "核对方/溯源用",
     "usage": "取用时须写明是谁的书；**经典层不得当教材用**", "tiers": ("通行·经典",)},
    {"priority": "③", "source": "无", "strength": "—", "usage": "标「无源可引」，凭专业判断", "tiers": ()},
)


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


def load_sources(path: Path) -> dict:
    """读来源登记表（事实源）。文件不在时返回空表，脚本降级为「只有 ④ 层」。"""
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def source_entries(sources: dict) -> list[dict]:
    return list(sources.get("entries") or [])


def primary_batch_ids(sources: dict) -> set[str]:
    """「第一批」= 来源登记表里 batch 标第一批的条目。数据表里没有就是空集。"""
    return {e["id"] for e in source_entries(sources) if e.get("batch") == BATCH_PRIMARY}


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


def check_sources_consistency(entries: list[dict], sources: dict) -> list[dict]:
    """来源登记表（`sources.json`）与数据表是否**漂移**。

    只比可机器比的三项，不碰需要人判断的东西：
      1. 登记的 id 是否还在数据表里；
      2. 登记的 `project.nature` / `project.flavors` 是否等于数据现值；
      3. `layer` 是否合法。

    这三项一旦漂移，核验单就会拿着**旧的**依据给审核人看 —— 比没有依据更危险。
    （真实触发场景：改完数据忘了回头更新来源登记表。）
    """
    if not sources:
        return []
    by_id = {e["id"]: e for e in entries}
    missing, drift, bad_layer = [], [], []
    for s in source_entries(sources):
        entry = by_id.get(s.get("id"))
        if entry is None:
            missing.append(f"`{s.get('id')}`（{s.get('name')}）已不在数据表里")
            continue
        project = s.get("project") or {}
        if project.get("nature") != entry.get("nature"):
            drift.append(
                f"`{s['id']}` 四气：登记 {project.get('nature')} vs 数据 {entry.get('nature')}"
            )
        registered_flavors = project.get("flavors")
        if registered_flavors is not None and list(registered_flavors) != list(entry.get("flavors") or []):
            drift.append(
                f"`{s['id']}` 五味：登记 {registered_flavors} vs 数据 {entry.get('flavors')}"
            )
        if s.get("layer") not in SOURCE_LAYERS:
            bad_layer.append(f"`{s['id']}`：layer={s.get('layer')!r}")

    issues: list[dict] = []
    if missing:
        issues.append(
            {
                "kind": "来源登记漂移",
                "level": "矛盾",
                "headline": "来源登记表里的条目已不在数据表中",
                "rows": sorted(missing),
                "detail": "数据被删除/改名，但 `docs/food-properties-sources.json` 还记着它。",
                "action": "改文档：从来源登记表里同步删除该条。",
            }
        )
    if drift:
        issues.append(
            {
                "kind": "来源登记漂移",
                "level": "矛盾",
                "headline": "来源登记表登记的项目值与数据现值不一致",
                "rows": sorted(drift),
                "detail": (
                    "登记表是核验单的事实源。它漂了，审核人就会照旧值判断 —— "
                    "这比没有依据更危险（看起来有据可依）。"
                ),
                "action": "改文档：把 `docs/food-properties-sources.json` 的 project 字段同步到现值。",
            }
        )
    if bad_layer:
        issues.append(
            {
                "kind": "来源登记漂移",
                "level": "矛盾",
                "headline": "来源登记表里的 layer 取值不合法",
                "rows": sorted(bad_layer),
                "detail": f"合法值只有 {SOURCE_LAYERS}。",
                "action": "改文档：修正 layer。",
            }
        )
    return issues


# ---------------------------------------------------------------------------
# 映射裁定与受控词表（纯函数：渲染与测试**共用同一份逻辑**）
#
# 下面三条都是纯函数 —— 测试才能用**合成数据**做负控制。只测「真实数据上没问题」是
# 不够的：那和「这段逻辑根本没跑」长得一模一样（见 tests/test_food_review_sheet.py）。
# ---------------------------------------------------------------------------
def mapping_layer_gaps(entries: list[dict]) -> list[str]:
    """检查「映射裁定」与 `layer` 是否自洽，返回问题清单（空 = 干净）。

    两条派生规则，不依赖任何具体条目：

    1. `accepted is False`（映射被否）→ 该条**必须已降级为 ③**：非正名映射是承重的，
       映射没了来源也就没了，不能还挂在「一致」里；
    2. `accepted is None`（待确认）→ `layer` **必须是 ②**：既没采纳也没否掉，
       不能混进「一致」那一层（`jiangyou` 2026-09-18 之前就是这个形态）。

    没登记 `mapping_review` 的条目**不参与判定**，函数自己跳过。当年在测试里写成
    `(s.get("mapping_review") or {}).get("accepted") is None` 的坑正在这里：
    `{}` 的 `.get` 同样返回 None，会把几十条压根没登记的条目一起算进来。
    """
    gaps: list[str] = []
    for s in entries:
        review = s.get("mapping_review")
        if not review:
            continue
        sid, layer, accepted = s.get("id"), s.get("layer"), review.get("accepted")
        if accepted is False and layer != "③":
            gaps.append(f"`{sid}` 映射被否却没降级到 ③（仍记 {layer}）")
        if accepted is None and layer != "②":
            gaps.append(f"`{sid}` 映射待确认，layer 应为 ②（实际 {layer}）")
    return gaps


def evidence_how(reference: dict, evidence: list[dict]) -> str:
    """取 `reference` 所对齐那条 evidence 的 `how`（取不到返回「—」）。

    ⚠️ 两件都不能省，它们是这个函数存在的全部理由：

    - **不能读 `reference["how"]`** —— `reference` 里根本没有 `how` 字段
      （47 条实测 0 条有）。`reference` 只是「本次比对用了哪条依据」的摘要，
      不含这条依据「是怎么对上的」。
    - **不能取 `evidence[0]`** —— 同一条目常有多条依据（`mogu` 两条，
      `jiang`/`longyan`/`shanzha_guo` 各三条），第一条未必是 `reference` 用的那条。
      按 `(source_id, matched_name)` 对齐才对得上。
    """
    if not reference:
        return "—"
    sid, name = reference.get("source_id"), reference.get("matched_name")
    for ev in evidence or []:
        if ev.get("matched_name") != name:
            continue
        if sid and ev.get("source_id") != sid:
            continue
        return ev.get("how") or "—"
    # 退化：`reference` 没给 source_id 时只按基准名找
    for ev in evidence or []:
        if ev.get("matched_name") == name:
            return ev.get("how") or "—"
    return "—"


def out_of_vocab(values, allowed) -> list[str]:
    """返回不在**受控词表**里的取值（去重、排序）；空 = 全部合规。

    词表是「新增取值必须先登记」这个约定的执行点：取值散落在几十条 `evidence` 里，
    没有这层检查时，写错一个词（比如残留一个旧混用值「别名/等价名」）不会有任何反馈。
    """
    return sorted({str(v) for v in values if v not in allowed})


def priority_legend_gaps(sources: dict, legend=None) -> list[str]:
    """返回「在用、但 §4 图例未覆盖」的 `tier`（空 = 图例齐全）。

    §4 的图例是**写给人看**的，`evidence[].tier` 是**给机器用**的 —— 两者之间原本没有
    任何约束，于是「新增一个档、忘了补图例」不会红，只会让审核人在 §4.1 看到一个图例里
    查不到的档名（`_meta` 与产物静默不一致，正是本项目反复出现的那个形态）。
    这条纯函数把两者绑在一起：**图例漏了哪个在用档，就报出来**。

    `legend` 可传入用于负控制；缺省用模块级 `PRIORITY_LEGEND`。
    """
    rows = list(PRIORITY_LEGEND if legend is None else legend)
    covered = {t for row in rows for t in (row.get("tiers") or ())}
    used = {
        ev.get("tier")
        for s in source_entries(sources)
        for ev in (s.get("evidence") or [])
        if ev.get("tier")
    }
    return sorted(str(t) for t in used if t not in covered)


def run_checks(entries: list[dict], herb_nature: dict[str, str], sources: dict | None = None) -> list[dict]:
    issues: list[dict] = []
    issues += check_duplicate_keys(entries)
    issues += check_alias_ambiguity(entries)
    issues += check_variant_against_rules(entries)
    issues += check_temperature_siblings(entries)
    issues += check_schema_fields(entries)
    issues += check_cross_table(entries, herb_nature)
    issues += check_sources_consistency(entries, sources or {})
    return issues


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------
def category_order(entries: list[dict], primary_ids: set[str] | None = None) -> list[str]:
    """含「第一批」条目的类别优先，其余按条目数降序 —— 让审核人先做能推动验收标准的那批。"""
    primary_ids = primary_ids or set()
    counts: dict[str, int] = {}
    primary_counts: dict[str, int] = {}
    for e in entries:
        cat = e.get("category", "（无 category）")
        counts[cat] = counts.get(cat, 0) + 1
        if e["id"] in primary_ids:
            primary_counts[cat] = primary_counts.get(cat, 0) + 1

    def sort_key(cat: str) -> tuple[int, int, str]:
        return (0 if primary_counts.get(cat, 0) else 1, -counts[cat], cat)

    return sorted(counts, key=sort_key)


def render(entries: list[dict], meta: dict, issues: list[dict], source_path: Path,
           sources: dict | None = None) -> str:
    lines: list[str] = []
    add = lines.append

    sources = sources or {}
    src_entries = source_entries(sources)
    src_by_id = {s.get("id"): s for s in src_entries}
    primary_ids = primary_batch_ids(sources)

    total = len(entries)
    n_foods = sum(1 for e in entries if e["_group"] == "foods")
    n_tea = total - n_foods
    status_counts: dict[str, int] = {}
    for e in entries:
        status_counts[review_status_of(e)] = status_counts.get(review_status_of(e), 0) + 1

    contradictions = [i for i in issues if i["level"] == "矛盾"]
    doubts = [i for i in issues if i["level"] == "存疑"]
    oks = [i for i in issues if i["level"] == "正常"]

    def layer_counts(batch: str | None = None) -> dict[str, int]:
        out: dict[str, int] = {}
        for s in src_entries:
            if batch and s.get("batch") != batch:
                continue
            out[str(s.get("layer"))] = out.get(str(s.get("layer")), 0) + 1
        return out

    def ref_of(s: dict) -> dict:
        return s.get("reference") or {}

    def mapping_cell(s: dict) -> str:
        review = s.get("mapping_review")
        if not review:
            return "—"
        accepted = review.get("accepted")
        if accepted is True:
            return "✅ 采纳"
        if accepted is False:
            return "❌ **未采纳**"
        return "⏳ 待确认"

    def closed_cell(s: dict) -> str:
        """`open_question` 为空的处置栏：这条已裁定，结论不在这里重复。

        `open_question` 的用法（2026-09-18 起）：**已裁定者置 `null`**，结论见
        `mapping_review` 与数据里的 `note`；**未获权威裁定者保留原问题**
        （`baicai`/`huanggua`/`lianou` 的口径分歧即属此类）。
        """
        return "✅ 已裁定（结论见数据 `note` 与 §4.4）"

    add("# 食性表人工审核核验单（`food_properties.json`）")
    add("")
    add("> ⚠️ **本文件由脚本生成，请勿手工编辑。**")
    add(f"> 生成命令：`cd core && python scripts/build_food_review_sheet.py --out ../docs/"
        f"{DEFAULT_OUT.name}`")
    add(f"> 数据源：`core/data/{source_path.name}`（本脚本只读，不改数据、不改审核状态）")
    add(f"> 来源依据：`docs/{DEFAULT_SOURCES.name}`（逐条登记来源与原文，**人工裁定过映射**）")
    add("> 对应挂起项：`docs/pending-items.md` **A1**（食性表全部未人工审核）")
    add("")
    add("## 0. 这份单子的用法（先读）")
    add("")
    add(f"A1 不是「造数据」，是**核验已有数据**：{total} 条的 `nature` / `flavors` 早已填好，")
    add("全部是 `pending`。终局动作（`approved` + `reviewed_by` / `reviewed_at`）**只有具备资质的**")
    add("中医师/中药师能做，脚本不替你判定。")
    add("")
    add("难点在于**食材偏性没有官方标准**：药典只管药材（34 味有官方接口可比），")
    add("GB/T 46939 只管体质分类与判定阈值。食材四气只有「中医饮食养生通行表述」。")
    add(f"所以本单子把 {total} 条分四层，让审核人只看值得看的格子：")
    add("")
    add("| 层 | 含义 | 谁来做 | 现状 |")
    add("|---|---|---|---|")
    add("| ① 来源一致 | 找到权威/通行来源且与现值一致 | 审核人核对后可 `approved` | 已跑完，见 **§4** |")
    add("| ② 来源冲突 | 来源之间或来源与现值不一致 | 人工裁决（**不得直接 approved**） | 已跑完，见 **§4.2** |")
    add("| ③ 无来源 | 找不到可引来源，标「无源可引」 | 人工凭专业判断 | 已跑完，见 **§4.3** |")
    add("| ④ 内部矛盾 | 表内自相矛盾，与外部来源无关 | **脚本可查** | 见 **§2** |")
    add("")
    add("来源口径（**已定**）：**官方优先 + 多源兜底 + 无源标空**。**不把通行表述伪装成权威依据。**")
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
    if src_entries:
        lc_all = layer_counts()
        lc_primary = layer_counts(BATCH_PRIMARY)
        add(f"| 来源登记表条目数 | **{len(src_entries)}**（其中「第一批」**{len(primary_ids)}** 条） |")
        add(f"| 「第一批」分层 | " + "、".join(
            f"{k} **{lc_primary.get(k, 0)}**"
            for k in SOURCE_LAYERS if lc_primary.get(k)
        ) + " |")
        add(f"| 全部登记条目分层 | " + "、".join(
            f"{k} **{lc_all.get(k, 0)}**"
            for k in SOURCE_LAYERS if lc_all.get(k)
        ) + " |")
    add(f"| ④ 层：矛盾 | **{len(contradictions)}** 类 |")
    add(f"| ④ 层：存疑 | {len(doubts)} 类 |")
    add(f"| ④ 层：已核对正常 | {len(oks)} 类 |")
    add("")
    add("按类分布（`第一批` 列 = 该类里属第一批的条数，优先审）：")
    add("")
    add("| 类别 | 条数 | 第一批 | 审核状态 |")
    add("|---|---|---|---|")
    for cat in category_order(entries, primary_ids):
        group = [e for e in entries if e.get("category", "（无 category）") == cat]
        st: dict[str, int] = {}
        for e in group:
            st[review_status_of(e)] = st.get(review_status_of(e), 0) + 1
        n_primary = sum(1 for e in group if e["id"] in primary_ids)
        mark = f"**{n_primary}**" if n_primary else "—"
        add(f"| {cat} | {len(group)} | {mark} | "
            + "、".join(f"{k} {v}" for k, v in sorted(st.items())) + " |")
    add("")

    add("## 2. ④ 层：内部矛盾 / 存疑（机器可查）")
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

    add("## 3. 核验单（逐条）")
    add("")
    add("最后一列「判定」来自来源登记表；`○` = 属第一批（有来源可引）。")
    add("**「无源可引」也是一个合法结论**，不要为了让格子好看而硬找来源。")
    add("")
    for cat in category_order(entries, primary_ids):
        group = [e for e in entries if e.get("category", "（无 category）") == cat]
        n_primary = sum(1 for e in group if e["id"] in primary_ids)
        mark = f"　○ 第一批 {n_primary} 条" if n_primary else ""
        add(f"### {cat}（{len(group)} 条）{mark}")
        add("")
        add("| # | | id | 名称 | 四气 | 五味 | 审核状态 | 来源值 | 来源档 | 判定（层/状态） |")
        add("|---|---|---|---|---|---|---|---|---|---|")
        for i, e in enumerate(group, 1):
            natures = NATURE_CN.get(e.get("nature"), e.get("nature") or "—")
            flavors = "、".join(e.get("flavors") or []) or "—"
            status = review_status_of(e)
            flag = "⚠️ 缺字段" if "review_status" not in e else status
            s = src_by_id.get(e["id"])
            tick = "○" if e["id"] in primary_ids else ""
            if s:
                ref = ref_of(s)
                src_qi = ref.get("qi_word") or "—"
                src_tier = ref.get("tier") or "—"
                verdict = f"{s.get('layer')} {s.get('status')}"
            else:
                src_qi = src_tier = "—"
                verdict = ""
            add(f"| {i} | {tick} | `{e['id']}` | {e.get('name')} | {natures} | {flavors} | "
                f"{flag} | {src_qi} | {src_tier} | {verdict} |")
        add("")

    if src_entries:
        add("## 4. ①②③ 层：来源核对（事实源 = `docs/food-properties-sources.json`）")
        add("")
        add("| 优先级 | 来源 | 强度 | 用法 |")
        add("|---|---|---|---|")
        for _row in PRIORITY_LEGEND:
            add(f"| {_row['priority']} | {_row['source']} | {_row['strength']} | {_row['usage']} |")
        add("")
        add("> ⚠️ **① 层只表示「来源与现值一致」，不等于来源足够强**。来源档为「通行·经典」")
        add("> （《本草纲目》）者，按 50 号文件 §5.4 的规则**不得当教材用**——是否据此 `approved`")
        add("> 由审核人判断，不要只看层号。")
        add("")

        add("### 4.1 「第一批」逐条分层（判据＝有来源可引，与类别无关）")
        add("")
        add("| # | id | 名称 | 类别 | 项目四气 | 来源四气 | 来源档 | 基准条目 | 层 | 状态 | 映射裁定 |")
        add("|---|---|---|---|---|---|---|---|---|---|---|")
        primary = sorted(
            (s for s in src_entries if s.get("batch") == BATCH_PRIMARY),
            key=lambda s: (str(s.get("layer")), s.get("category") or "", s.get("id") or ""),
        )
        for i, s in enumerate(primary, 1):
            ref = ref_of(s)
            project = s.get("project") or {}
            add(f"| {i} | `{s.get('id')}` | {s.get('name')} | {s.get('category')} | "
                f"{project.get('nature_cn') or project.get('nature')} | {ref.get('qi_word') or '—'} | "
                f"{ref.get('tier') or '—'} | {ref.get('matched_name') or s.get('name')} | "
                f"{s.get('layer')} | {s.get('status')} | {mapping_cell(s)} |")
        add("")
        add(f"> ⚠️ 上表只含 `batch={BATCH_PRIMARY}` 的条目（**{len(primary)}** 条）。"
            "`batch=后续` **表示「有来源可引、但未纳入第一批」，不是「无源」** ——"
            "例如 `xianggu`（香菇）由 `mogu` 拆条新增时随拆条一并登记。")
        add("> 当时特意**没有**回头把第一批从 33 改成 34：第一批的条数是审核进度的分母，"
            "不能因为一次数据修复而漂移。")
        add("")

        conflicts = sorted(
            (s for s in src_entries if s.get("batch") == BATCH_PRIMARY and s.get("layer") == "②"),
            key=lambda s: s.get("id") or "",
        )
        add("### 4.2 层② 来源冲突（**不得直接 approved**）")
        add("")
        if conflicts:
            add("| id | 名称 | 项目值 | 来源值 | 基准条目 | 来源原文 | 处置 |")
            add("|---|---|---|---|---|---|---|")
            for s in conflicts:
                ref = ref_of(s)
                project = s.get("project") or {}
                verbatim = ""
                for ev in s.get("evidence") or []:
                    if ev.get("verbatim") and not verbatim.startswith("（§5.3"):
                        verbatim = ev["verbatim"]
                        break
                add(f"| `{s['id']}` | {s.get('name')} | {project.get('nature_cn')} | "
                    f"{ref.get('qi_word')} | {ref.get('matched_name')} | {verbatim or '—'} | "
                    f"{s.get('open_question') or closed_cell(s)} |")
        else:
            add("（第一批内无冲突项。）")
        add("")
        add("> **这些是「口径分歧」而非「数据错」**：基准是教材/经典层，强度不足以推翻现值，")
        add("> 所以一律**保留项目值**并在数据里加 `note` 留痕；`nature` 未改。")
        add("> 「处置」栏为空即「已裁定」（原问题置 `null`）—— 这一条有守卫测试：")
        add("> **第一批 ② 层条目必须在数据里有 `note`**（防「文档说了、数据没做」）。")
        add("")

        no_source = sorted(
            (s for s in src_entries if s.get("layer") == "③"), key=lambda s: s.get("id") or ""
        )
        add("### 4.3 层③ 无源可引")
        add("")
        if no_source:
            for s in no_source:
                review = s.get("mapping_review") or {}
                add(f"- `{s.get('id')}`（{s.get('name')}）：{s.get('status')}"
                    + (f"　映射裁定：{review.get('reason')}" if review.get("reason") else ""))
        else:
            add("（本批无。）")
        add("")
        add("> 三类（蔬菜/调味/水果）中另有 13 条在 50 号文件与目录里**均无条目**，")
        add("> 清单见 `docs/food-properties-batch2-plan.md` 附录，未登记进来源登记表。")
        add("")

        mapped = sorted(
            (s for s in src_entries if s.get("mapping_review")),
            key=lambda s: (str((s.get("mapping_review") or {}).get("group") or ""), s.get("id") or ""),
        )
        add("### 4.4 非正名映射的裁定结果（条目名 ≠ 语料条目名）")
        add("")
        add("| id | 条目 → 基准 | 组 | 裁定 | 限定（how） | 理由 |")
        add("|---|---|---|---|---|---|")
        for s in mapped:
            review = s.get("mapping_review") or {}
            ref = ref_of(s)
            add(f"| `{s.get('id')}` | {s.get('name')} → **{ref.get('matched_name') or '—'}** | "
                f"{review.get('group')} | {mapping_cell(s)} | "
                f"{evidence_how(ref, s.get('evidence') or [])} | {review.get('reason')} |")
        add("")
        add("> 「限定（how）」列说明**这条映射是怎么对上的**（受控词表见 `docs/"
            f"{DEFAULT_SOURCES.name}` 的 `_meta.controlled_vocab`）。")
        add("> 取值按 `reference` 的「来源 + 基准名」回到该条 `evidence[]` 里取 —— `reference`")
        add("> 本身**不含** `how`，且同一条目可能有多条依据，取第一条会取错。")
        add("")
        add("> ⚠️ 每条非正名映射都是**承重**的：这类条目通常只有 1 条证据，映射一否即落 ③ 无源。")
        add("> 最典型的是 `lianou`（莲藕→藕）——它被判为「口径分歧」的前提正是这条映射成立。")
        add("")

    add("## 5. 口径与纪律")
    add("")
    add("1. **不把通行表述伪装成权威依据**——引用时必须写清来源档，不得混入指南口径。")
    add("2. **第一批 = 有来源可引**（由 `docs/food-properties-sources.json` 的 `batch` 字段定义，")
    add("   **不是类别**）。旧的「★ 主食/乳饮/水产」定义已作废：那三个大类恰是加工品最密集、")
    add("   最没来源的区段；官方层对食材几乎零覆盖（全表能沾到官方的只有 4 条）。")
    add("3. **`approved` 只能由具备资质的中医师/中药师填**，本单子只提供依据。")
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
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES,
                        help="来源登记表路径（docs/food-properties-sources.json，①②③ 层的事实源）")
    parser.add_argument("--out", type=Path, default=None,
                        help=f"写入文件（默认只打印；约定路径 {DEFAULT_OUT}）")
    parser.add_argument("--check", action="store_true",
                        help="校验 --out 指到的产物是否与当前数据一致（可进 CI）")
    parser.add_argument("--strict", action="store_true",
                        help="存在「矛盾」（含④层与来源登记漂移）时返回 exit 1")
    args = parser.parse_args(argv)

    if not args.food.exists():
        print(f"[失败] 找不到食性表: {args.food}", file=sys.stderr)
        return 2

    meta, entries = load_foods(args.food)
    herb_nature = load_herb_nature(args.herbs)
    sources = load_sources(args.sources)
    issues = run_checks(entries, herb_nature, sources)
    text = render(entries, meta, issues, args.food, sources)

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
    if sources:
        src_entries = source_entries(sources)
        primary = [s for s in src_entries if s.get("batch") == BATCH_PRIMARY]
        layers: dict[str, int] = {}
        for s in primary:
            layers[str(s.get("layer"))] = layers.get(str(s.get("layer")), 0) + 1
        print("来源登记表：" + f"{len(src_entries)} 条（第一批 {len(primary)} 条："
              + "、".join(f"{k} {layers[k]}" for k in sorted(layers)) + "）")
    else:
        print("⚠️ 未找到来源登记表：①②③ 层无法渲染（只输出 ④ 层）")
    print()
    print(_summarize(issues))
    print()

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8", newline="\n")
        print(f"[已写入] {args.out}（{len(text.splitlines())} 行）")

    if args.strict and contradictions:
        print(f"[失败] --strict：存在 {len(contradictions)} 类「矛盾」（含④层与来源登记漂移）", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
