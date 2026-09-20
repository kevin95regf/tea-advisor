"""核对饮片的性味归经：国家药典委员会官方数据 vs 项目 herbs.json。

用法（在 core 目录下）：

    python scripts/build_herb_crosscheck.py --refresh   # 联网，从官方药典接口重建参考数据
    python scripts/build_herb_crosscheck.py             # 离线，从参考数据渲染 Markdown
    python scripts/build_herb_crosscheck.py --check     # 离线，只校验一致性（可进 CI）

数据来源（国家药典委员会「中国药典在线版」，公开只读接口）：
    POST https://ydz.chp.org.cn/front-api/search   {"keyword": "...", "bookId": 1}
    GET  https://ydz.chp.org.cn/front-api/entry/{id}

**本脚本只读取 herbs.json，绝不修改它。** 一致与否只作报告，由人判断以哪个为准。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

CORE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = CORE_DIR.parent
HERBS_PATH = CORE_DIR / "data" / "herbs.json"
REF_PATH = CORE_DIR / "data" / "herb_nature_reference.json"
DOC_PATH = PROJECT_ROOT / "docs" / "herb-nature-crosscheck.md"

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass

API = "https://ydz.chp.org.cn/front-api"
API_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Referer": "https://ydz.chp.org.cn/",
    "Content-Type": "application/json",
}

# 项目名 -> 药典词条候选名（人工桥接，逐条有理由）
NAME_BRIDGE: dict[str, tuple[list[str], str]] = {
    "红枣": (["大枣"], "项目用俗称「红枣」，药典词条为「大枣」"),
    "藿香": (["广藿香"], "项目用「藿香」，药典词条为「广藿香」"),
    "紫苏": (["紫苏叶"], "药典无单列「紫苏」，分列紫苏叶/紫苏子/紫苏梗；此处取「紫苏叶」"),
}

# ---- 映射规则：药典档位 -> 项目档位。这是**我方约定**，不是药典的说法 ----
NATURE_MAP = {
    "大寒": "cold", "寒": "cold",
    "微寒": "cool", "凉": "cool",
    "平": "neutral",
    "微温": "warm", "温": "warm",
    "热": "hot", "大热": "hot",
}
EXACT_NATURE_WORDS = {"寒", "凉", "平", "温", "热"}  # 药典用词正好落在项目档位上

FLAVOR_MAP = {
    "酸": "sour", "苦": "bitter", "甘": "sweet", "辛": "pungent",
    "咸": "salty", "淡": "bland", "涩": "astringent",
}
FLAVOR_CN = {v: k for k, v in FLAVOR_MAP.items()}
NATURE_CN = {"cold": "寒", "cool": "凉", "neutral": "平", "warm": "温", "hot": "热"}

SECTIONS_OF_INTEREST = ["性味与归经", "功能与主治", "用法与用量", "贮藏"]

# ---- 四性数值轴。这是 core/app/domain/nature_math.py 的编码，此处是副本，
#      tests/test_herb_crosscheck.py 有断言卡住两者一致 ----
NATURE_AXIS = {"cold": -2, "cool": -1, "neutral": 0, "warm": 1, "hot": 2}

# ---- 饮片的 nature / flavors / meridians 在代码里到底被谁用 ----
# 2026-09 逐条实测（用 ripgrep 把所有 .nature 读取点列出来核对过）。
# 这个结论决定了「差异影响」怎么写，所以连同证据一起登记在这里。
FIELD_CONSUMERS = {
    "nature": [
        "`core/app/agents/agent2_recommend.py:62-66`：把每味候选饮片拼成"
        "「- 茯苓（平，甘/淡，归心/肺/脾/肾）」交给 Agent2 —— **这是唯一的实质消费者**。",
        "`core/app/services/matcher.py:156`：规则兜底时把 `nature` 原样拷进 `HerbInBlend` 输出对象。",
    ],
    "flavors": [
        "`core/app/agents/agent2_recommend.py:63-66`：同上，拼进 Agent2 的候选描述。",
        "`core/app/services/matcher.py:157`：拷进输出对象。",
    ],
    "meridians": [
        "`core/app/agents/agent2_recommend.py:66`：同上，拼进 Agent2 的候选描述。",
        "`core/app/services/matcher.py:158`：拷进输出对象。",
    ],
}
# 「没人用」的部分同样重要，所以显式写出来，避免以后有人想当然。
FIELD_NON_CONSUMERS = [
    "`core/app/domain/safety.py` **完全不读这三个字段**：`check_blend` 只用 "
    "`name` / `max_daily_g` / `cautions` / `unsuitable_for`；`check_constitution_fit` 只用 "
    "`unsuitable_for`；`filter_by_constitution` 只用 `suitable_constitutions`。",
    "`core/app/services/matcher.py:134` 的 `match_natures` 匹配的是 **`parsed.overall_nature`"
    "（整餐四气，来自 Agent1）**，不是饮片四气。",
    "**没有任何地方把饮片四气加总成茶饮的四气**，四性数值轴（`nature_math.py`）只作用于食材。",
    "两个壳渲染推荐的饮片时都只打印名字/用量/作用：`ui/terminal/chat.py:133-135` 打 "
    "`h.name / h.amount_g / h.role`；`ui/web/index.html` 的 `renderRecs` 同理。"
    "前端出现的 `f.nature` 是**食材**的四性，不是饮片的。",
]

# ---- 人作出的处置决定（与 task 1 的 DECISIONS 同构） ----
DECISION = {
    "decided_at": "2026-09-17",
    "decision": "7 处不一致**先保留项目值**，在文档里标注药典值与差异影响；等 nanple 复核数据后再决定是否改。",
    "status": "待 nanple 复核",
    "action": (
        "1) 不修改 herbs.json 任何字段；2) 本文档为每处不一致给出「差异影响」；"
        "3) 待 nanple 复核后，若要改，用 `--refresh` 重建参考数据并同步更新测试里的"
        " EXPECTED_INCONSISTENT 清单。"
    ),
    "basis": "这些差异均不影响任何确定性判定（见 §3.1 的代码取证），因此不阻塞；而是否改动应听数据审核人的判断。",
}



# ============================== 抓取 ======================================

def _strip_tags(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s or "")
    return s.replace("&nbsp;", " ").replace("&amp;", "&").strip()


def _search(keyword: str) -> list[dict]:
    import httpx

    r = httpx.post(f"{API}/search", headers=API_HEADERS,
                   json={"keyword": keyword, "bookId": 1}, timeout=30, verify=False)
    return (r.json().get("data") or {}).get("list") or []


def _entry(entry_id: int) -> dict:
    import httpx

    r = httpx.get(f"{API}/entry/{entry_id}", headers=API_HEADERS, timeout=30, verify=False)
    return r.json().get("data") or {}


def _parse_sections(html: str) -> dict[str, str]:
    text = re.sub(r"</p>|<br\s*/?>", "\n", html or "")
    text = re.sub(r"<[^>]+>", "", text).replace("&nbsp;", " ")
    out: dict[str, str] = {}
    for field in SECTIONS_OF_INTEREST:
        m = re.search(r"【" + re.escape(field) + r"】(.*?)(?=【|$)", text, re.S)
        if m:
            out[field] = " ".join(m.group(1).split())
    return out


def fetch_pharmacopoeia(herb_names: list[str]) -> list[dict]:
    records: list[dict] = []
    for name in herb_names:
        candidates, _ = NAME_BRIDGE.get(name, ([name], ""))
        hit = None
        for cand in candidates:
            lst = _search(cand)
            exact = [x for x in lst
                     if _strip_tags(x.get("title", "")) == cand
                     and "2020" in (x.get("bookName") or "")
                     and "一部" in (x.get("bookName") or "")]
            if exact:
                hit = exact[0]
                break
        if not hit:
            print(f"[未收载] {name}（候选：{candidates}）", file=sys.stderr)
            records.append({"herb": name, "found": False})
            continue
        det = _entry(hit["id"])
        records.append({
            "herb": name,
            "found": True,
            "matched_title": _strip_tags(hit.get("title", "")),
            "entry_id": hit["id"],
            "book": hit.get("bookName"),
            "page": hit.get("pageNum"),
            "pinyin": det.get("pinyinTitle"),
            "latin": det.get("eTitle"),
            "sections": _parse_sections(det.get("htmlContent", "")),
            "url": f"https://ydz.chp.org.cn/#/item?bookId=1&entryId={hit['id']}",
        })
        time.sleep(0.3)
    return records


# ============================== 比对 ======================================

def _parse_nature(xingwei: str) -> tuple[str, str | None, str]:
    body = xingwei.split("归")[0].replace("。", "").strip()
    if "，" not in body:
        return body, None, ""
    flavor_part, nature_part = body.rsplit("，", 1)
    nature_part = nature_part.strip()
    for key in sorted(NATURE_MAP, key=len, reverse=True):
        if nature_part.startswith(key):
            return nature_part, key, flavor_part
    return nature_part, None, flavor_part


def _parse_flavors(flavor_part: str) -> list[str]:
    out = []
    for it in re.split(r"[、,，]", flavor_part):
        it = it.strip()
        if not it:
            continue
        base = it[1:] if it.startswith("微") else it
        if base in FLAVOR_MAP:
            out.append(FLAVOR_MAP[base])
    return out


def _parse_meridians(xingwei: str) -> list[str]:
    m = re.search(r"归(.+?)经", xingwei)
    if not m:
        return []
    return [x.strip() for x in re.split(r"[、,，]", m.group(1)) if x.strip()]


def _impact(item: dict) -> list[str]:
    """给出一致性差异的**下游影响**。全部基于代码实测，不猜。"""
    if item["status"] != "不一致":
        return []
    herb = item["herb"]
    proj = item["project"]
    ph = item["pharmacopoeia"]
    out: list[str] = []

    if not item["nature_match"]:
        a = NATURE_AXIS.get(proj["nature"])
        b = NATURE_AXIS.get(ph["nature_mapped"])
        if a is not None and b is not None:
            out.append(
                f"**四性数值轴**：项目 `{proj['nature']}`({a:+d}) → 药典降档后 "
                f"`{ph['nature_mapped']}`({b:+d})，相差 **{abs(b - a)} 档**"
                f"（编码见 `core/app/domain/nature_math.py`）。"
                f"注意：这条轴**不作用于饮片**，只作用于食材。"
            )
        out.append(
            f"**对确定性逻辑无影响**：没有任何护栏或规则读饮片四气，"
            f"所以改与不改都不会改变 `filter_by_constitution`、`check_blend`、"
            f"`_pick_rule` 的结果。"
        )
        delta = "更偏寒凉" if (b is not None and a is not None and b < a) else "更偏温热"
        out.append(
            f"**对 Agent2 有软性影响**：候选描述里 {herb} 的四性会从"
            f"「{proj['nature_cn']}」变成「{ph['nature_mapped_cn'] or ph['nature_word']}」"
            f"（{delta}），模型据此做寒热搭配推理时可能略微改变选料倾向。"
            f"这不是硬约束，无法用测试断言。"
        )
        out.append(
            f"**展示影响**：两个壳目前都不打印饮片四性，所以用户看不到这个差别。"
        )

    if not item["flavors_match"]:
        extra = [x for x in proj["flavors_cn"] if x not in ph["flavors_cn"]]
        miss = [x for x in ph["flavors_cn"] if x not in proj["flavors_cn"]]
        bits = []
        if extra:
            bits.append(f"项目多「{'、'.join(extra)}」")
        if miss:
            bits.append(f"项目缺「{'、'.join(miss)}」")
        out.append(
            f"**五味不参与任何运算**：五味没有数值编码，既不进护栏也不进规则兜底的选取条件，"
            f"只出现在 Agent2 的候选描述文字里。{'；'.join(bits)}，"
            f"因此**确定性逻辑零影响**，仅候选描述的文字不同。"
        )

    if not item["meridians_match"]:
        extra = [x for x in proj["meridians"] if x not in ph["meridians"]]
        miss = [x for x in ph["meridians"] if x not in proj["meridians"]]
        bits = []
        if extra:
            bits.append(f"项目多「{'、'.join(extra)}」")
        if miss:
            bits.append(f"项目缺「{'、'.join(miss)}」")
        out.append(
            f"**归经不参与任何运算**：`herbs.json` 的 `_meta.field_notes` 就写明归经是"
            f"「中文展示用」。{'；'.join(bits)}，"
            f"**确定性逻辑零影响**；唯一后果是 Agent2 看到的脏腑信息少了一味，"
            f"可能轻微影响它写 `role` 时的用词。"
        )

    if out:
        out.append(
            "**结论**：本处差异**不会改变任何确定性判定结果**，"
            "因此「先保留项目值」不会引入功能风险；改动与否取决于中药专业判断。"
        )
    return out



def raw_from_reference(ref: dict) -> list[dict]:
    """从已存的参考数据还原出 build_records 需要的 raw 形状（不联网）。

    这样改 NATURE_MAP 或 _impact 之后，用 --recompute 就能重算派生字段，
    不必重新抓一遍药典。
    """
    out: list[dict] = []
    for r in ref.get("herbs", []):
        ph = r.get("pharmacopoeia")
        if not ph:
            out.append({"herb": r["herb"], "found": False})
            continue
        out.append({
            "herb": r["herb"],
            "found": True,
            "matched_title": ph["matched_title"],
            "entry_id": ph["entry_id"],
            "book": ph.get("book"),
            "page": ph["page"],
            "pinyin": ph.get("pinyin"),
            "latin": ph.get("latin"),
            "sections": {
                "性味与归经": ph["xingwei_verbatim"],
                "功能与主治": ph.get("effects_verbatim", ""),
                "用法与用量": ph.get("dosage_verbatim", ""),
            },
            "url": ph["url"],
        })
    return out


def build_records(raw: list[dict], herbs: list[dict]) -> list[dict]:
    by_name = {h["name"]: h for h in herbs}
    out: list[dict] = []
    for rec in raw:
        name = rec["herb"]
        herb = by_name.get(name)
        if not herb:
            continue
        item: dict = {
            "herb": name,
            "project": {
                "nature": herb["nature"],
                "nature_cn": NATURE_CN.get(herb["nature"], herb["nature"]),
                "flavors": herb["flavors"],
                "flavors_cn": [FLAVOR_CN.get(f, f) for f in herb["flavors"]],
                "meridians": herb["meridians"],
                "effects": herb["effects"],
                "max_daily_g": herb["max_daily_g"],
            },
        }
        bridge = NAME_BRIDGE.get(name)
        item["bridge_note"] = bridge[1] if bridge else None

        if not rec.get("found"):
            item.update({"pharmacopoeia": None, "status": "未收载", "differences": [],
                         "impact": [], "nature_match": None, "flavors_match": None,
                         "meridians_match": None})
            out.append(item)
            continue

        xw = rec["sections"].get("性味与归经", "")
        nature_word, nature_key, flavor_part = _parse_nature(xw)
        mapped = NATURE_MAP.get(nature_key) if nature_key else None
        flavors = _parse_flavors(flavor_part)
        meridians = _parse_meridians(xw)

        n_match = mapped == herb["nature"]
        f_match = set(flavors) == set(herb["flavors"])
        m_match = set(meridians) == set(herb["meridians"])

        diffs: list[str] = []
        if not n_match:
            diffs.append(
                f"**四气**：项目「{NATURE_CN.get(herb['nature'], herb['nature'])}」，"
                f"药典「{nature_word}」"
                + (f"（按降档约定应为「{NATURE_CN.get(mapped)}」）" if mapped else "（降档不到）")
            )
        elif nature_key not in EXACT_NATURE_WORDS:
            diffs.append(f"四气：降档后一致，但药典原文用的是更细的档「{nature_word}」")
        if not f_match:
            extra = [FLAVOR_CN.get(x, x) for x in herb["flavors"] if x not in flavors]
            miss = [FLAVOR_CN.get(x, x) for x in flavors if x not in herb["flavors"]]
            bits = []
            if extra:
                bits.append("项目多「" + "、".join(extra) + "」")
            if miss:
                bits.append("项目缺「" + "、".join(miss) + "」")
            diffs.append("**五味**：" + "；".join(bits))
        if not m_match:
            extra = [x for x in herb["meridians"] if x not in meridians]
            miss = [x for x in meridians if x not in herb["meridians"]]
            bits = []
            if extra:
                bits.append("项目多「" + "、".join(extra) + "」")
            if miss:
                bits.append("项目缺「" + "、".join(miss) + "」")
            diffs.append("**归经**：" + "；".join(bits))

        item.update({
            "pharmacopoeia": {
                "matched_title": rec["matched_title"],
                "page": rec["page"],
                "pinyin": rec.get("pinyin"),
                "latin": rec.get("latin"),
                "xingwei_verbatim": xw,
                "nature_word": nature_word,
                "nature_mapped": mapped,
                "nature_mapped_cn": NATURE_CN.get(mapped) if mapped else None,
                "flavors": flavors,
                "flavors_cn": [FLAVOR_CN.get(f, f) for f in flavors],
                "meridians": meridians,
                "effects_verbatim": rec["sections"].get("功能与主治", ""),
                "dosage_verbatim": rec["sections"].get("用法与用量", ""),
                "entry_id": rec["entry_id"],
                "url": rec["url"],
            },
            "nature_match": n_match,
            "flavors_match": f_match,
            "meridians_match": m_match,
            "differences": diffs,
            "status": "一致" if (n_match and f_match and m_match) else "不一致",
        })
        item["impact"] = _impact(item)
        out.append(item)
    return out


# ============================== 校验 ======================================

def validate(ref: dict, herbs: list[dict]) -> list[str]:
    problems: list[str] = []
    recs = ref.get("herbs", [])
    names = [r["herb"] for r in recs]
    if len(names) != len(set(names)):
        problems.append("饮片名有重复")
    if set(names) != {h["name"] for h in herbs}:
        missing = {h["name"] for h in herbs} - set(names)
        extra = set(names) - {h["name"] for h in herbs}
        if missing:
            problems.append(f"参考数据缺少饮片：{sorted(missing)}")
        if extra:
            problems.append(f"参考数据含未知饮片：{sorted(extra)}")

    by_name = {h["name"]: h for h in herbs}
    for r in recs:
        h = by_name.get(r["herb"])
        if not h:
            continue
        p = r["project"]
        # 项目侧快照必须与 herbs.json 实时一致，防止文档漂移
        for field in ("nature", "flavors", "meridians"):
            if p[field] != h[field]:
                problems.append(
                    f"{r['herb']}：project.{field} 快照已过期"
                    f"（快照 {p[field]!r} != herbs.json {h[field]!r}）"
                )
        if r["status"] == "未收载" and r["pharmacopoeia"] is not None:
            problems.append(f"{r['herb']}：状态为未收载但带了药典数据")
        if r["status"] != "未收载":
            ph = r["pharmacopoeia"]
            if not ph or not ph.get("xingwei_verbatim"):
                problems.append(f"{r['herb']}：缺少药典性味归经原文")
            elif "性味与归经" not in ph["xingwei_verbatim"] and "归" not in ph["xingwei_verbatim"]:
                problems.append(f"{r['herb']}：药典原文疑似没抓到归经部分")
        if r["status"] == "不一致" and not r["differences"]:
            problems.append(f"{r['herb']}：标为不一致但没写差异原因")
        if r["status"] == "不一致" and not r.get("impact"):
            problems.append(f"{r['herb']}：标为不一致但没写差异影响（第 1 条决定要求必须有）")
        if r["status"] != "不一致" and r.get("impact"):
            problems.append(f"{r['herb']}：一致的条目不应有差异影响")
        if r["status"] == "一致" and r["differences"]:
            # 允许「降档后一致但原文更细」这类说明
            if any(d.startswith("**") for d in r["differences"]):
                problems.append(f"{r['herb']}：标为一致但存在实质性差异")
    return problems


# ============================== 渲染 ======================================

def render(ref: dict) -> str:
    meta = ref["_meta"]
    recs = ref["herbs"]
    ok = [r for r in recs if r["status"] == "一致"]
    bad = [r for r in recs if r["status"] == "不一致"]
    miss = [r for r in recs if r["status"] == "未收载"]

    L: list[str] = []
    L.append(f"# {len(recs)} 味饮片性味归经核对：《中国药典》2020 年版一部 vs 项目")
    L.append("")
    L.append("> **本文件由 `core/scripts/build_herb_crosscheck.py` 从 "
             "`core/data/herb_nature_reference.json` 渲染生成，请勿手工编辑。** 重新生成：")
    L.append("> `cd core && python scripts/build_herb_crosscheck.py`")
    L.append("")
    L.append(f"> 生成日期：{meta['compiled_at']}　版本：{meta['version']}")
    L.append("")
    L.append("## 1. 结论摘要")
    L.append("")
    L.append(f"**合计 {len(recs)} 味：一致 {len(ok)} 味，不一致 {len(bad)} 味，"
             f"药典未收载 {len(miss)} 味。**")
    L.append("")
    L.append("> **本文件只报告差异，不修改任何数据。** 以哪个为准由人判断。")
    L.append("")
    L.append("> ### ⚠️ 两条必须先读的声明")
    L.append(">")
    L.append("> **① 「微寒→凉、微温→温」是项目约定，不是药典的说法。**")
    L.append("> 药典的四气分档比项目细，项目只有 5 档，必须降档才能比较。"
             "表格里凡是用了降档的行都标了 `†`，"
             "而**药典原文值一律保留在「药典四气」列和参考数据的 "
             "`pharmacopoeia.xingwei_verbatim` 字段里**，约定随时可推翻重算。")
    L.append(">")
    L.append("> **② 下面所有差异都不影响任何确定性判定。**")
    L.append("> 饮片的四气/五味/归经**不参与任何护栏或规则计算**"
             "（代码取证见 §3.1），唯一实质消费者是把候选描述交给 Agent2 的提示词。"
             "所以「先保留项目值」不引入功能风险。")
    L.append("")
    L.append("## 2. 数据来源与方法")
    L.append("")
    L.append(meta["method"])
    L.append("")
    L.append("主源：**国家药典委员会「中国药典在线版」公开接口**（《中华人民共和国药典》"
             "2020 年版一部），每条都保留了逐字原文与页码。")
    L.append("")
    L.append("### 2.1 档位映射（⚠️ 项目约定，非药典原文）")
    L.append("")
    L.append("药典的四气分档比项目细（有「微寒」「微温」），项目只有 5 档，必须降档。"
             "**降档规则是我方约定**，所以药典原文一律保留，方便推翻：")
    L.append("")
    L.append("| 药典原文 | 项目档位 | 说明 |")
    L.append("|---|---|---|")
    for k, v in NATURE_MAP.items():
        note = "原样对应" if k in EXACT_NATURE_WORDS else "**降档（项目约定）**"
        L.append(f"| {k} | `{v}`（{NATURE_CN.get(v, v)}）| {note} |")
    L.append("")
    L.append("五味按字面对应：酸/苦/甘/辛/咸/淡/涩；药典写「微苦」时按「苦」计。")
    L.append("")

    L.append("## 3. 不一致清单（需要你判断以哪个为准）")
    L.append("")
    L.append("### 3.1 先看代码：这些字段到底被谁用")
    L.append("")
    L.append("判读下面每一条差异的影响之前，先把取证摆出来"
             "（用 ripgrep 把所有 `.nature` 读取点列出来核对过）：")
    L.append("")
    L.append("**唯一的实质消费者：**")
    L.append("")
    for f in ("nature", "flavors", "meridians"):
        for line in FIELD_CONSUMERS[f]:
            L.append(f"- `{f}` → {line}")
    L.append("")
    L.append("**明确没人用的地方（同样重要）：**")
    L.append("")
    for line in FIELD_NON_CONSUMERS:
        L.append(f"- {line}")
    L.append("")
    L.append("### 3.2 逐条差异与影响")
    L.append("")
    if not bad:
        L.append("（无）")
        L.append("")
    for r in bad:
        ph = r["pharmacopoeia"]
        L.append(f"#### {r['herb']}")
        L.append("")
        L.append(f"- 药典词条：**{ph['matched_title']}**（2020 年版一部 p.{ph['page']}）"
                 f"　[在线查看]({ph['url']})")
        if r["bridge_note"]:
            L.append(f"- 名称桥接：{r['bridge_note']}")
        L.append(f"- **药典原文**：{ph['xingwei_verbatim']}")
        L.append(f"- **项目当前**（按决定保留，未改动）：{r['project']['nature_cn']}／"
                 f"{'、'.join(r['project']['flavors_cn'])}／"
                 f"{'、'.join(r['project']['meridians'])}")
        L.append("- **差异**：")
        for d in r["differences"]:
            L.append(f"  - {d}")
        L.append("- **差异影响**：")
        for line in r.get("impact", []):
            L.append(f"  - {line}")
        L.append(f"- 药典【功能与主治】（仅供参照）：{ph['effects_verbatim']}")
        L.append("")

    L.append("## 4. 全部对照表")
    L.append("")
    L.append("「药典四气」列保留原文用词；标 `†` 表示该行用到了降档约定"
             "（见 §2.1），括号内是降档后的项目档位。")
    L.append("")
    L.append("| 饮片 | 项目四气 | 药典四气（原文） | 项目五味 | 药典五味 | 项目归经 | 药典归经 | 是否一致 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for r in recs:
        p = r["project"]
        if r["status"] == "未收载":
            L.append(f"| {r['herb']} | {p['nature_cn']} | — | "
                     f"{'、'.join(p['flavors_cn'])} | — | {'、'.join(p['meridians'])} | — | "
                     f"**药典未收载** |")
            continue
        ph = r["pharmacopoeia"]
        n_cell = ph["nature_word"]
        if ph["nature_word"] not in EXACT_NATURE_WORDS:
            n_cell += f" †（→{ph['nature_mapped_cn']}）"
        if not r["nature_match"]:
            n_cell += " ⚠️"
        f_cell = "、".join(ph["flavors_cn"])
        if not r["flavors_match"]:
            f_cell += " ⚠️"
        m_cell = "、".join(ph["meridians"])
        if not r["meridians_match"]:
            m_cell += " ⚠️"
        mark = "✅" if r["status"] == "一致" else "❌"
        L.append(f"| {r['herb']} | {p['nature_cn']} | {n_cell} | "
                 f"{'、'.join(p['flavors_cn'])} | {f_cell} | "
                 f"{'、'.join(p['meridians'])} | {m_cell} | {mark} |")
    L.append("")
    L.append("`†` = 该行用到了「微寒→凉、微温→温」的**项目约定**（非药典原文）；"
             "药典原文用词已保留在本列。⚠️ = 该维度与药典不一致，详见 §3.2。")
    L.append("")

    if miss:
        L.append("### 4.1 药典未收载")
        L.append("")
        for r in miss:
            L.append(f"- **{r['herb']}**：在《中国药典》2020 年版一部中检索不到该词条。"
                     f"这独立佐证了它在合规上的特殊地位（见 `docs/catalog-compliance.md`）。")
        L.append("")

    L.append("## 5. 处置决定（已登记）")
    L.append("")
    L.append("这是**人作出的决定**，与机械比对结果分开记录。")
    L.append("")
    L.append(f"- **决定日期**：{DECISION['decided_at']}")
    L.append(f"- **决定**：{DECISION['decision']}")
    L.append(f"- **实施状态**：`{DECISION['status']}`")
    L.append(f"- **决定依据**：{DECISION['basis']}")
    L.append(f"- **要做的事**：{DECISION['action']}")
    L.append("")
    L.append("> 补充：**四气降档约定（微寒→凉、微温→温）已于 2026-09-17 认可**，"
             "但仍属项目约定、非药典原文 —— 原文值始终保留，见 §1 的声明与 §2.1。")
    L.append("")

    L.append("## 6. 《中华本草》为什么没有数据")
    L.append("")
    for line in meta["zhonghua_bencao_status"]:
        L.append(f"- {line}")
    L.append("")

    L.append("## 7. 开放项")
    L.append("")
    for item in ref.get("open_items", []):
        L.append(f"### {item['title']}　`{item['status']}`")
        L.append("")
        L.append(item["detail"])
        L.append("")
    L.append("---")
    L.append("")
    L.append("> 提醒：药典记载的是**药品**标准；项目把它用作**食品/茶饮**方向的属性参考。"
             "两者用途不同。另外项目 `effects` 字段刻意使用养生类措辞、不照抄药典"
             "【功能与主治】，这是合规要求（见 `herbs.json` 的 `_meta.field_notes`），"
             "不是笔误。")
    L.append("")
    return "\n".join(L)


# ============================== 入口 ======================================

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="核对饮片性味归经（只读 herbs.json）")
    parser.add_argument("--refresh", action="store_true",
                        help="联网从官方药典接口重建参考数据（需要网络）")
    parser.add_argument("--recompute", action="store_true",
                        help="不联网，从已存的药典原文重算派生字段（改了映射规则或影响逻辑后用）")
    parser.add_argument("--check", action="store_true", help="只校验一致性，不写文件")
    parser.add_argument("--out", type=Path, default=DOC_PATH)
    parser.add_argument("--ref", type=Path, default=REF_PATH)
    args = parser.parse_args(argv)

    herbs = json.loads(HERBS_PATH.read_text(encoding="utf-8"))["herbs"]

    if args.refresh or args.recompute:
        if not args.ref.exists():
            print(f"[失败] 找不到参考数据: {args.ref}（--recompute 需要先 --refresh 一次）",
                  file=sys.stderr)
            return 2
        loaded = json.loads(args.ref.read_text(encoding="utf-8"))
        raw = (fetch_pharmacopoeia([h["name"] for h in herbs]) if args.refresh
               else raw_from_reference(loaded))
        loaded["herbs"] = build_records(raw, herbs)
        args.ref.write_text(json.dumps(loaded, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8", newline="\n")
        print(f"已{'刷新' if args.refresh else '重算'} {args.ref}")

    if not args.ref.exists():
        print(f"[失败] 找不到参考数据: {args.ref}", file=sys.stderr)
        return 2

    ref = json.loads(args.ref.read_text(encoding="utf-8"))
    problems = validate(ref, herbs)
    for p in problems:
        print(f"[问题] {p}", file=sys.stderr)

    if args.check:
        if problems:
            print(f"校验失败：{len(problems)} 项问题", file=sys.stderr)
            return 1
        recs = ref["herbs"]
        print(f"校验通过：{len(recs)} 味齐备；一致 "
              f"{sum(1 for r in recs if r['status'] == '一致')}，"
              f"不一致 {sum(1 for r in recs if r['status'] == '不一致')}，"
              f"未收载 {sum(1 for r in recs if r['status'] == '未收载')}")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(render(ref))
    print(f"已写入 {args.out}")
    if problems:
        print(f"[警告] 存在 {len(problems)} 项问题，渲染仍已完成，但请先修复", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
