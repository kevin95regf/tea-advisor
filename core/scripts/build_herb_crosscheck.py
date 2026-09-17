"""核对 34 味饮片的性味归经：国家药典委员会官方数据 vs 项目 herbs.json。

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
                         "nature_match": None, "flavors_match": None,
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
    L.append("# 34 味饮片性味归经核对：《中国药典》2020 年版一部 vs 项目")
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
    L.append("## 2. 数据来源与方法")
    L.append("")
    L.append(meta["method"])
    L.append("")
    L.append("主源：**国家药典委员会「中国药典在线版」公开接口**（《中华人民共和国药典》"
             "2020 年版一部），每条都保留了逐字原文与页码。")
    L.append("")
    L.append("### 2.1 档位映射（我方约定，非药典说法）")
    L.append("")
    L.append("药典的四气分档比项目细（有「微寒」「微温」），项目只有 5 档，必须降档。"
             "**降档规则是我方约定**，所以原文一律保留，方便推翻：")
    L.append("")
    L.append("| 药典原文 | 项目档位 |")
    L.append("|---|---|")
    for k, v in NATURE_MAP.items():
        L.append(f"| {k} | `{v}`（{NATURE_CN.get(v, v)}）|")
    L.append("")
    L.append("五味按字面对应：酸/苦/甘/辛/咸/淡/涩；药典写「微苦」时按「苦」计。")
    L.append("")

    L.append("## 3. 不一致清单（需要你判断以哪个为准）")
    L.append("")
    if not bad:
        L.append("（无）")
        L.append("")
    for r in bad:
        ph = r["pharmacopoeia"]
        L.append(f"### {r['herb']}")
        L.append("")
        L.append(f"- 药典词条：**{ph['matched_title']}**（2020 年版一部 p.{ph['page']}）"
                 f"　[在线查看]({ph['url']})")
        if r["bridge_note"]:
            L.append(f"- 名称桥接：{r['bridge_note']}")
        L.append(f"- **药典原文**：{ph['xingwei_verbatim']}")
        L.append(f"- **项目当前**：{r['project']['nature_cn']}／"
                 f"{'、'.join(r['project']['flavors_cn'])}／"
                 f"{'、'.join(r['project']['meridians'])}")
        L.append("- 差异：")
        for d in r["differences"]:
            L.append(f"  - {d}")
        L.append(f"- 药典【功能与主治】：{ph['effects_verbatim']}")
        L.append("")

    L.append("## 4. 全部对照表")
    L.append("")
    L.append("| 饮片 | 项目四气 | 药典四气 | 项目五味 | 药典五味 | 项目归经 | 药典归经 | 是否一致 |")
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
    L.append("⚠️ = 该维度与药典不一致，详见第 3 节。")
    L.append("")

    if miss:
        L.append("### 4.1 药典未收载")
        L.append("")
        for r in miss:
            L.append(f"- **{r['herb']}**：在《中国药典》2020 年版一部中检索不到该词条。"
                     f"这独立佐证了它在合规上的特殊地位（见 `docs/catalog-compliance.md`）。")
        L.append("")

    L.append("## 5. 《中华本草》为什么没有数据")
    L.append("")
    for line in meta["zhonghua_bencao_status"]:
        L.append(f"- {line}")
    L.append("")

    L.append("## 6. 开放项")
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
    parser.add_argument("--check", action="store_true", help="只校验一致性，不写文件")
    parser.add_argument("--out", type=Path, default=DOC_PATH)
    parser.add_argument("--ref", type=Path, default=REF_PATH)
    args = parser.parse_args(argv)

    herbs = json.loads(HERBS_PATH.read_text(encoding="utf-8"))["herbs"]

    if args.refresh:
        raw = fetch_pharmacopoeia([h["name"] for h in herbs])
        ref = json.loads(args.ref.read_text(encoding="utf-8")) if args.ref.exists() else {}
        ref["herbs"] = build_records(raw, herbs)
        args.ref.write_text(json.dumps(ref, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8", newline="\n")
        print(f"已刷新 {args.ref}")

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
