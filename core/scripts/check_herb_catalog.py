"""核对 core/data/herbs.json 的饮片白名单是否落在国家卫健委食药物质目录内。

用法（在 core 目录下）：

    python scripts/check_herb_catalog.py                       # 人读表格
    python scripts/check_herb_catalog.py --format md           # Markdown 表格
    python scripts/check_herb_catalog.py --format json         # 机器可读
    python scripts/check_herb_catalog.py --only not_in         # 只看不在目录内的
    python scripts/check_herb_catalog.py --strict              # 有「不在目录内」或「需人工判断」则 exit 1
    python scripts/check_herb_catalog.py --format md --out ../docs/catalog-compliance.md

本脚本是**只读**的：除非显式传 --out，否则不写任何文件；
永远不修改 herbs.json，也不对「该不该删」作任何决定。

判定分三类：
  in       在目录内      —— 目录里有对应条目
  not_in   不在目录内    —— 目录里找不到，需要人工决定「删掉」还是「标注仅作参考」
  review   需人工判断    —— 目录里存在相近但可能不是同一物的条目，脚本不替你做判断

外部权威数据全部来自 core/data/food_medicine_catalog.json（其中每个批次都保留了
公告原文串 verbatim，可逐字与政府网页核对）。
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
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

DEFAULT_CATALOG = CORE_DIR / "data" / "food_medicine_catalog.json"
DEFAULT_HERBS = CORE_DIR / "data" / "herbs.json"

# ---------------------------------------------------------------------------
# 我方与目录之间的名称桥接
#
# 这是「人工判断」，不是外部权威数据，所以刻意放在脚本里、和数据文件分开，
# 每条都写明理由。只有在我有把握「同物异名」时才登记；
# 把握不足的一律进 NEEDS_HUMAN_JUDGMENT，由人来定。
# ---------------------------------------------------------------------------
HERB_ALIASES: dict[str, tuple[str, str]] = {
    "陈皮": (
        "橘皮",
        "同物异名：项目沿用《中国药典》名「陈皮」，目录用「橘皮」；"
        "药典中「陈皮」与「橘红」是两个不同条目，故此处不等同于「桔红」",
    ),
    "红枣": (
        "大枣",
        "俗称：目录在「枣（大枣、酸枣、黑枣）」项下并列收录「大枣」",
    ),
    "生姜": (
        "生姜",
        "目录在「姜（生姜、干姜）」项下并列收录「生姜」",
    ),
}

# 这些饮片脚本不自动判定，只报告候选，等人决定。
NEEDS_HUMAN_JUDGMENT: dict[str, str] = {
    "橘红": (
        "目录内同时存在「橘皮」与「桔红」两条（2002 年附件 1），2024 年第 4 号又新增「化橘红」；"
        "「橘红」是否等同 2002 名单的「桔红」、还是应归到「化橘红」，需人工判断"
    ),
}

# ---------------------------------------------------------------------------
# 已作出的处置决定
#
# 这是**人作出的决定**，不是脚本的推断，所以单独登记、带日期，并可追溯。
# status 只有两个值：
#   已实施 —— herbs.json / 代码已按此决定改好
#   待实施 —— 决定已定，代码尚未改（不要把它当成已经生效）
# ---------------------------------------------------------------------------
DECISIONS: dict[str, dict[str, str]] = {
    "玫瑰花": {
        "decided_at": "2026-09-17",
        "decision": "保留，名称需明确品种。**代码先不动，等 nanple 审数据时一起处理。**",
        "action": (
            "计划：把 herbs.json 中的名称改为「玫瑰花（重瓣红玫瑰）」，明确品种；"
            "并同步加别名「玫瑰花」，否则 check_blend 会因名称不匹配把模型输出的"
            "「玫瑰花」判成白名单外饮片而拦掉。"
            "⚠️ 该品种约束是**采购/供应链要求**，代码只能表达它、无法核实原料；"
            "若无法保证原料确为重瓣红玫瑰，本条应降级为「仅作参考」。"
        ),
        "status": "待实施（等 nanple 审数据）",
        "basis": (
            "卫生部公告 2010 年第 3 号允许「玫瑰花（重瓣红玫瑰）」作为普通食品生产经营"
        ),
    },
    "茉莉花": {
        "decided_at": "2026-09-17",
        "decision": "标注「仅作参考」，推荐时排除。**代码先不动，等 nanple 审数据时一起处理。**",
        "action": (
            "计划：在 herbs.json 上标记为仅作参考，并让推荐链路（filter_by_constitution 的候选集、"
            "matcher.fallback_recommend）永不选中它。需要新增目录级排除能力——"
            "现有 exclude_herbs 是每个请求的用户自选排除，不是目录级开关。"
        ),
        "status": "待实施（等 nanple 审数据）",
        "basis": (
            "食用依据仅为广西地方标准（效力限广西），不承担全国范围的合规风险"
        ),
    },
    "橘红": {
        "decided_at": "2026-09-17",
        "decision": "归属 2002 年附件 1 的「桔红」，视为在目录内",
        "action": "无需改动代码或数据。若日后新增饮片出现「化橘红」，应作为独立条目单列。",
        "status": "已实施",
        "basis": (
            "herbs.json 中「橘红」的功效「理气宽中、燥湿化痰」与药典 2020 年版一部"
            "「橘红」原文逐字一致，而与同文件「陈皮」的「理气健脾、燥湿化痰」刻意区分"
        ),
    },
}

# 字形归一：目录与我方对同一味药存在异体/通假写法时用于匹配。
# 只做无歧义的字形替换，不改变语义。
VARIANT_CHARS = {
    "桔": "橘",  # 桔红 / 橘红
    "葚": "椹",  # 桑葚 / 桑椹
}

# ---------------------------------------------------------------------------
# 额外的合规背景（带出处）。
#
# 目的是让「删掉 / 标注仅作参考」这个决定有依据。
# 这里只陈述事实与出处，不代替你做决定。
# ---------------------------------------------------------------------------
EXTRA_CONTEXT: dict[str, list[str]] = {
    "玫瑰花": [
        "**不在食药物质目录，但存在另一条合规路径。** 卫生部公告 2010 年第 3 号"
        "《关于批准 DHA 藻油、棉籽低聚糖等 7 种物品为新资源食品及其他相关规定的公告》"
        "规定：「允许玫瑰花（重瓣红玫瑰）、凉粉草（仙草）作为普通食品生产经营」。"
        "出处：[食品伙伴网转载该公告全文](http://law.foodmate.net//show-163987.html)",
        "**该路径有适用范围限制。** 公告针对的是栽培品种**玫瑰花（重瓣红玫瑰 "
        "Rose rugosa cv. Plena）**，不是所有蔷薇属植物。herbs.json 中该条目写的是"
        "「干花蕾」，若实际原料不是重瓣红玫瑰，此路径不成立。",
        "玫瑰花另外出现在卫法监发〔2002〕51 号 **附件 2《可用于保健食品的物品名单》**"
        "（而不是附件 1），即它历史上走的是保健食品原料路径。",
    ],
    "茉莉花": [
        "**不在食药物质目录，也未查到国家级的新食品原料或普通食品批准。**",
        "已查到的食用依据是**地方级**的：广西壮族自治区食品安全地方标准《茉莉花》"
        "于 2024 年初发布。南宁市人民政府门户网站报道原文称，该标准"
        "「从源头上解决了茉莉花不能作为食品原料的问题」。"
        "出处：[南宁市人民政府门户网站](https://www.nanning.gov.cn/ywzx/xqdt/2024nxqdt/t5824867.html)",
        "**这句话反过来是一份重要证据**：在该地方标准出台之前，茉莉花在全国层面"
        "不能作为食品原料使用。地方标准的效力范围限于广西；若产品面向全国销售，"
        "茉莉花是本项目 34 味里合规依据最弱的一味。",
    ],
    "橘红": [
        "这个条目脚本不替你判定，但下面是决定所需的全部事实依据：",
        "**事实一**：卫法监发〔2002〕51 号附件 1 中，「橘皮」与「桔红」是**并列的两条**"
        "（已逐字核对原文，见 food_medicine_catalog.json 的 batches[].verbatim）。",
        "**事实二**：2024 年第 4 号公告新增的是「**化**橘红」，其基源为"
        "「芸香科植物化州柚（Citrus grandis 'Tomentosa'）或柚（Citrus grandis（L.）Osbeck）"
        "的未成熟或近成熟的干燥外层果皮」，与橘皮、橘红均不同。",
        "**事实三**：《中国药典》2020 年版一部对「陈皮」「橘红」分列条目。"
        "药典「橘红」为「辛、苦，温。归肺、脾经。理气宽中，燥湿化痰。"
        "用于咳嗽痰多，食积伤酒，呕恶痞闷」（药典 2020 年版一部 395–396 页）。",
        "**关键旁证**：herbs.json 中「橘红」条目的功效写的是「理气宽中、燥湿化痰」，"
        "与药典「橘红」原文**逐字一致**；而同文件「陈皮」条目写的是"
        "「理气健脾、燥湿化痰」，与药典「陈皮」原文一致。两者措辞被刻意区分，"
        "说明项目里的「橘红」指向的是药典「橘红」而非陈皮。",
        "需要你判断的是三种可能：(a) 指药典「橘红」→ 对应 2002 名单的「桔红」"
        "（桔/橘 异体字），**在目录内**；(b) 指「化橘红」→ 对应 2024 年第 4 号，"
        "**在目录内**；(c) 实际与「橘皮/陈皮」同物 → 应并入陈皮条目，否则构成重复收录。",
    ],
}

STATUS_LABELS = {
    "in": "在目录内",
    "not_in": "不在目录内",
    "review": "需人工判断",
}


def _norm(text: str) -> str:
    """归一化：去空白 + 异体字替换。仅用于匹配，不用于展示。"""
    out = "".join(VARIANT_CHARS.get(ch, ch) for ch in text)
    return "".join(out.split())


def split_items(verbatim: str) -> list[str]:
    """按「、」切分公告原文串，但括号内的「、」不算分隔符。

    例：「枣（大枣、酸枣、黑枣）」必须算 1 条而不是 3 条。
    这个函数同时用来校验目录文件的 count 是否和 verbatim 自洽。
    """
    out: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in verbatim.replace("。", ""):
        if ch in "（(":
            depth += 1
        elif ch in "）)":
            depth = max(0, depth - 1)
        if ch == "、" and depth == 0:
            out.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        out.append("".join(buf).strip())
    return [t for t in out if t]


def _display_width(text: str) -> int:
    """东亚全角字符按 2 列计算，用于对齐表格。"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _display_width(text))


def load_catalog(path: Path) -> tuple[dict, list[dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("items") or []
    return data, items


def load_herbs(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("herbs") or []


def build_index(items: list[dict]) -> dict[str, tuple[dict, str]]:
    """归一化名称 -> (目录条目, 匹配来源说明)。"""
    index: dict[str, tuple[dict, str]] = {}
    for item in items:
        index.setdefault(_norm(item["name"]), (item, "目录主名"))
        for alt in item.get("alternates") or []:
            index.setdefault(_norm(alt), (item, "目录括号内并列名"))
    return index


def check(herbs: list[dict], items: list[dict]) -> list[dict]:
    index = build_index(items)
    results: list[dict] = []
    for herb in herbs:
        name = herb.get("name", "")
        note_parts: list[str] = []
        bridge = HERB_ALIASES.get(name)

        if bridge:
            lookup, bridge_reason = bridge
            note_parts.append(bridge_reason)
        else:
            lookup, bridge_reason = name, None

        hit = index.get(_norm(lookup))
        entry, match_kind = hit if hit else (None, None)

        if name in NEEDS_HUMAN_JUDGMENT:
            status = "review"
            note_parts.append(NEEDS_HUMAN_JUDGMENT[name])
        elif entry is not None:
            status = "in"
            if match_kind:
                note_parts.append(f"匹配方式：{match_kind}")
        else:
            status = "not_in"
            note_parts.append("目录四批公告中均未收录此名称")

        results.append(
            {
                "herb": name,
                "status": status,
                "status_label": STATUS_LABELS[status],
                "catalog_name": entry["full"] if entry else None,
                "catalog_batch": entry["batch"] if entry else None,
                "match_kind": match_kind,
                "note": "；".join(note_parts),
            }
        )
    return results


def summarise(results: list[dict]) -> dict:
    summary = {"in": 0, "not_in": 0, "review": 0, "total": len(results)}
    for r in results:
        summary[r["status"]] += 1
    return summary


# ------------------------------- 渲染 -------------------------------------

HEADERS = ["饮片名", "是否在目录内", "目录里的对应名称", "备注"]


def _row_cells(r: dict) -> list[str]:
    return [
        r["herb"],
        r["status_label"],
        r["catalog_name"] or "—",
        r["note"],
    ]


def render_table(results: list[dict], summary: dict) -> str:
    groups = [
        ("清单 A · 在目录内（合规，无需处理）", [r for r in results if r["status"] == "in"]),
        ("清单 B · 不在目录内（需你决定「删掉」还是「标注仅作参考」）",
         [r for r in results if r["status"] == "not_in"]),
        ("清单 C · 需人工判断（脚本不替你选）", [r for r in results if r["status"] == "review"]),
    ]
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append("饮片白名单 × 食药物质目录 核对结果")
    lines.append("=" * 78)
    lines.append(
        f"合计 {summary['total']} 味：在目录内 {summary['in']}，"
        f"不在目录内 {summary['not_in']}，需人工判断 {summary['review']}"
    )
    for title, rows in groups:
        lines.append("")
        lines.append(f"── {title}（{len(rows)} 味）")
        if not rows:
            lines.append("   （无）")
            continue
        cells = [_row_cells(r) for r in rows]
        widths = [max(_display_width(h), *(_display_width(c[i]) for c in cells))
                  for i, h in enumerate(HEADERS)]
        lines.append("   " + "  ".join(_pad(h, widths[i]) for i, h in enumerate(HEADERS)))
        lines.append("   " + "  ".join("-" * w for w in widths))
        for c in cells:
            lines.append("   " + "  ".join(_pad(v, widths[i]) for i, v in enumerate(c)))
    relevant = [r for r in results if r["herb"] in EXTRA_CONTEXT]
    if relevant:
        lines.append("")
        lines.append("── 合规背景补充（只陈述事实与出处，不代替你决定）")
        for r in relevant:
            lines.append("")
            lines.append(f"   [{r['herb']}]")
            for item in EXTRA_CONTEXT[r["herb"]]:
                lines.append(f"     · {item}")
    decided = [r for r in results if r["herb"] in DECISIONS]
    if decided:
        lines.append("")
        lines.append("── 已登记的处置决定（人作出的，非脚本推断）")
        for r in decided:
            d = DECISIONS[r["herb"]]
            lines.append("")
            lines.append(f"   [{r['herb']}] {d['decision']}   状态={d['status']}"
                         f"（{d['decided_at']}）")
            lines.append(f"     · 依据：{d['basis']}")
            lines.append(f"     · 要做的事：{d['action']}")
    lines.append("")
    return "\n".join(lines)


def render_markdown(results: list[dict], summary: dict, catalog: dict) -> str:
    meta = catalog.get("_meta", {})
    lines: list[str] = []
    lines.append("# 饮片白名单 × 食药物质目录 合规核对")
    lines.append("")
    lines.append(
        f"本文件由 `core/scripts/check_herb_catalog.py` 生成，核对对象是 "
        f"`core/data/herbs.json` 的饮片白名单与 `core/data/food_medicine_catalog.json`"
        f"（{meta.get('title', '食药物质目录')}，共 {meta.get('total', '?')} 种）。"
    )
    lines.append("")
    lines.append(
        f"**合计 {summary['total']} 味：在目录内 {summary['in']} 味，"
        f"不在目录内 {summary['not_in']} 味，需人工判断 {summary['review']} 味。**"
    )
    lines.append("")
    lines.append("> 本文件是合规自检记录，不构成法律意见。判断食品生产经营合规性请以"
                 "国家卫健委发布的最新目录原文为准。")
    lines.append("")
    lines.append("> **本文件是脚本生成的，请勿手工编辑。** 重新生成：")
    lines.append("> `cd core && python scripts/check_herb_catalog.py --format md"
                 " --out ../docs/catalog-compliance.md`")
    lines.append("")

    groups = [
        ("清单 A · 在目录内（合规，无需处理）", [r for r in results if r["status"] == "in"]),
        ("清单 B · 不在目录内（需决定「删掉」还是「标注仅作参考」）",
         [r for r in results if r["status"] == "not_in"]),
        ("清单 C · 需人工判断（脚本不替你选）", [r for r in results if r["status"] == "review"]),
    ]
    for title, rows in groups:
        lines.append(f"## {title}")
        lines.append("")
        if not rows:
            lines.append("（无）")
            lines.append("")
            continue
        lines.append("| " + " | ".join(HEADERS) + " |")
        lines.append("|" + "---|" * len(HEADERS))
        for r in rows:
            note = r["note"].replace("|", "\\|")
            lines.append(
                f"| {r['herb']} | {r['status_label']} | {r['catalog_name'] or '—'} | {note} |"
            )
        lines.append("")

    lines.append("## 处置决定（已登记）")
    lines.append("")
    lines.append(
        "以下是**人作出的处置决定**，带决定日期与依据，与上面的机械核对结果分开记录。"
        "`待实施` 表示决定已定但代码/数据尚未改，**不要当成已经生效**。"
    )
    lines.append("")
    decided = [r for r in results if r["herb"] in DECISIONS]
    if not decided:
        lines.append("（暂无已登记的决定）")
        lines.append("")
    for r in decided:
        d = DECISIONS[r["herb"]]
        lines.append(f"### {r['herb']} —— {d['decision']}")
        lines.append("")
        lines.append(f"- **决定日期**：{d['decided_at']}")
        lines.append(f"- **实施状态**：`{d['status']}`")
        lines.append(f"- **决定依据**：{d['basis']}")
        lines.append(f"- **要做的事**：{d['action']}")
        lines.append("")

    lines.append("## 待决策项与合规背景")
    lines.append("")
    lines.append(
        "以下只陈述事实与出处，**不代替你做决定**。清单 B 与清单 C 里的每一味都在这里"
        "给出做判断所需的依据。"
    )
    lines.append("")
    relevant = [r for r in results if r["herb"] in EXTRA_CONTEXT]
    if not relevant:
        lines.append("（无需人工决策的条目）")
        lines.append("")
    for r in relevant:
        lines.append(f"### {r['herb']} —— {r['status_label']}")
        lines.append("")
        for item in EXTRA_CONTEXT[r["herb"]]:
            lines.append(f"- {item}")
        lines.append("")

    lines.append("## 数据来源")
    lines.append("")
    for batch in catalog.get("batches", []):
        lines.append(
            f"- **{batch['label']}**（{batch['date']}，{batch['issuer']}，{batch['count']} 种）"
            f"—— [原文]({batch['url']})"
        )
    lines.append("")
    lines.append(
        "每个批次的公告原文串都保存在 `core/data/food_medicine_catalog.json` 的 "
        "`batches[].verbatim` 字段里，可与上述网页逐字对照。"
    )
    lines.append("")
    return "\n".join(lines)


def render_json(results: list[dict], summary: dict, catalog: dict) -> str:
    payload = {
        "catalog": {
            "title": catalog.get("_meta", {}).get("title"),
            "version": catalog.get("_meta", {}).get("version"),
            "total": catalog.get("_meta", {}).get("total"),
            "compiled_at": catalog.get("_meta", {}).get("compiled_at"),
        },
        "summary": summary,
        "results": results,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


# ------------------------------- 入口 -------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="核对饮片白名单是否在食药物质目录内（只读，不修改任何数据）"
    )
    parser.add_argument("--herbs", type=Path, default=DEFAULT_HERBS, help="herbs.json 路径")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG,
                        help="food_medicine_catalog.json 路径")
    parser.add_argument("--format", choices=("table", "md", "json"), default="table")
    parser.add_argument("--only", choices=("all", "in", "not_in", "review"), default="all",
                        help="只输出某一类（不影响 --strict 的判定）")
    parser.add_argument("--out", type=Path, default=None, help="写入文件（默认只打印）")
    parser.add_argument("--strict", action="store_true",
                        help="存在「不在目录内」或「需人工判断」时返回 exit 1")
    args = parser.parse_args(argv)

    if not args.catalog.exists():
        print(f"[失败] 找不到目录文件: {args.catalog}", file=sys.stderr)
        return 2
    if not args.herbs.exists():
        print(f"[失败] 找不到饮片文件: {args.herbs}", file=sys.stderr)
        return 2

    catalog, items = load_catalog(args.catalog)
    herbs = load_herbs(args.herbs)
    expected = catalog.get("_meta", {}).get("total")
    if expected is not None and expected != len(items):
        print(
            f"[警告] 目录文件声明 {expected} 种，实际 {len(items)} 条，请检查数据文件",
            file=sys.stderr,
        )
    # 自洽性：每个批次的 verbatim 数出来的条数必须等于声明的 count
    for batch in catalog.get("batches", []):
        actual = len(split_items(batch.get("verbatim", "")))
        if actual != batch.get("count"):
            print(
                f"[警告] 批次 {batch.get('id')} 声明 {batch.get('count')} 种，"
                f"但 verbatim 里数出 {actual} 条",
                file=sys.stderr,
            )

    results = check(herbs, items)
    summary = summarise(results)
    shown = results if args.only == "all" else [r for r in results if r["status"] == args.only]

    if args.format == "table":
        text = render_table(shown, summary)
    elif args.format == "md":
        text = render_markdown(results, summary, catalog)
    else:
        text = render_json(shown, summary, catalog)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        # 显式 newline="\n"：本仓库强制 LF（.gitattributes 的 * text=auto eol=lf），
        # 用默认写法则在 Windows 上会产生 CRLF，每次重新生成都会带来一次全文件 diff。
        with args.out.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(text + "\n")
        print(f"已写入 {args.out}")
    else:
        print(text)

    if summary["not_in"] or summary["review"]:
        print(
            f"\n需人工处理：不在目录内 {summary['not_in']} 味，需人工判断 {summary['review']} 味。",
            file=sys.stderr,
        )
    if args.strict and (summary["not_in"] or summary["review"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
