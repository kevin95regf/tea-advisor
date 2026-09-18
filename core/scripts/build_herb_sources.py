"""派生 / 校验饮片侧来源登记表的**域 I（属性依据）**。

用法（在 core 目录下）：

    python scripts/build_herb_sources.py            # 只打印摘要，不写任何文件（默认）
    python scripts/build_herb_sources.py --write    # 落盘 JSON + 渲染人读 Markdown
    python scripts/build_herb_sources.py --check    # 校验磁盘内容与派生结果一致（可进 CI）

分工（重要）：

- **域 I `property_entries`（34 味）由本脚本从 `herb_nature_reference.json` 派生**，
  一个字都不手写 —— 两份表格因此不可能漂移。`project` 块取自 `herbs.json` 的**现值**，
  不是参照表里的历史快照，所以不存在「改了 herbs.json 而登记表没跟上」。
- **域 II `constitution_entries`（24 条）与 `_meta` 是人工录入的，本脚本原样保留**。
  它们的事实源就是 `core/data/herb_evidence_sources.json` 自身，脚本只重算 `_meta.counts`。

本脚本是**只读**的：除非显式传 `--write`，否则不写任何文件；**永远不修改 herbs.json**。

CLI 与 `check_herb_catalog.py` / `build_herb_crosscheck.py` 保持一致：
默认只打印、`--out` 覆盖路径、`--check` 进 CI、渲染确定性（无生成时间戳、无 set 遍历顺序）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CORE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = CORE_DIR.parent
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from app.domain.enums import FLAVOR_LABELS, NATURE_LABELS  # noqa: E402

# Windows 控制台默认 GBK，中文会乱码
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass

HERBS_PATH = CORE_DIR / "data" / "herbs.json"
REF_PATH = CORE_DIR / "data" / "herb_nature_reference.json"
JSON_PATH = CORE_DIR / "data" / "herb_evidence_sources.json"
MD_PATH = PROJECT_ROOT / "docs" / "herb-evidence-sources.md"

# 参照表的 status -> 登记表的 status。两者语义相同，用词不同：
# 参照表是「与药典的比对结果」，登记表要回答「这味有没有来源可引」。
STATUS_MAP = {"一致": "一致", "不一致": "不一致", "未收载": "无源可引"}

KEEP_PROJECT_VALUES_REF = (
    "按 2026-09-17 既有裁定保留项目值、不改 herbs.json，等 nanple 复核"
    "（见 core/data/herb_nature_reference.json 的 "
    "open_items.discrepancies_keep_project_values）"
)
NO_SOURCE_QUESTION = "《中国药典》2020 年版一部未收载；食用依据仅广西地方标准。"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _strip_md_bold(text: str) -> str:
    """参照表的 differences 带文档用的 `**` 粗体标记，数据里不留排版标记。"""
    return text.replace("**", "")


def build_property_entries(ref: dict, herbs: list[dict]) -> list[dict]:
    """从药典参照表 + herbs.json 现值派生域 I 的 34 条。"""
    rc_by_name = {h["herb"]: h for h in ref["herbs"]}
    entries: list[dict] = []

    for herb in herbs:
        name = herb["name"]
        rc = rc_by_name.get(name)
        if rc is None:
            raise KeyError(
                f"herbs.json 的「{name}」在 herb_nature_reference.json 里没有对应记录 —— "
                "两表覆盖不一致，请先 --refresh 重建参照表"
            )
        ph = rc.get("pharmacopoeia") or {}

        evidence: list[dict] = []
        if ph.get("entry_id"):
            matched = ph["matched_title"]
            evidence.append(
                {
                    "source_id": "chp2020",
                    "tier": "官方·药典",
                    "matched_name": matched,
                    # 非正名映射的桥接理由取自参照表（人工写过、逐条有据），不在这里重编
                    "how": rc.get("bridge_note") or "正名（药典收载名）",
                    "locator": f"《中国药典》2020 年版一部 p.{ph['page']}「{matched}」",
                    "verbatim": ph["xingwei_verbatim"],
                    "url": ph["url"],
                }
            )

        status = STATUS_MAP[rc["status"]]
        diffs = [_strip_md_bold(d) for d in rc.get("differences") or []]
        if status == "不一致":
            open_question: str | None = KEEP_PROJECT_VALUES_REF
        elif status == "无源可引":
            open_question = NO_SOURCE_QUESTION
        else:
            open_question = None

        entries.append(
            {
                "id": herb["id"],
                "name": name,
                "project": {
                    "nature": herb["nature"],
                    "nature_cn": NATURE_LABELS[herb["nature"]],
                    "flavors": list(herb["flavors"]),
                    "flavors_cn": [FLAVOR_LABELS[f] for f in herb["flavors"]],
                    "meridians": list(herb["meridians"]),
                },
                "evidence": evidence,
                "status": status,
                "delta": "；".join(diffs) if diffs else None,
                "open_question": open_question,
            }
        )
    return entries


def rebuild(payload: dict, ref: dict, herbs: list[dict]) -> dict:
    """把派生结果并回整份登记表：域 I 重算，`_meta` 与域 II 原样保留。"""
    if "constitution_entries" not in payload:
        raise KeyError(
            "登记表缺少 constitution_entries —— 域 II 是人工录入的，本脚本不会替你生成。"
            "请先恢复该字段（它的事实源就是这份文件，git 里有）"
        )
    prop = build_property_entries(ref, herbs)
    cons = payload["constitution_entries"]

    meta = dict(payload.get("_meta") or {})
    meta["counts"] = {
        "property_total": len(prop),
        "property_with_source": sum(1 for e in prop if e["evidence"]),
        "constitution_total": len(cons),
        "distinct_herbs": len({e["herb_id"] for e in cons}),
    }
    return {"_meta": meta, "property_entries": prop, "constitution_entries": cons}


# ------------------------------- 渲染 -------------------------------------


def _cell(text: object) -> str:
    """Markdown 表格单元格：转义竖线与换行。"""
    s = "" if text is None else str(text)
    return s.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def _src_name(src: dict, source_id: str) -> str:
    """来源的展示名：`发布方《标题》`。与两个壳的渲染格式保持一致。"""
    publisher, title = src.get("publisher"), src.get("title")
    if publisher and title:
        return f"{publisher}《{title}》"
    return publisher or title or source_id


def render_md(payload: dict) -> str:
    meta = payload["_meta"]
    prop = payload["property_entries"]
    cons = payload["constitution_entries"]
    counts = meta["counts"]
    labels = {c["id"]: c["label"] for c in load_json(CORE_DIR / "data" / "constitution.json")["constitutions"]}

    lines: list[str] = []
    lines.append("# 饮片侧来源登记表（属性依据 + 体质适配依据）")
    lines.append("")
    lines.append(
        "本文件由 `core/scripts/build_herb_sources.py` 从事实源 "
        "`core/data/herb_evidence_sources.json` 渲染生成。"
    )
    lines.append("")
    lines.append("> **本文件是脚本生成的，请勿手工编辑。** 重新生成：")
    lines.append("> `cd core && python scripts/build_herb_sources.py --write`")
    lines.append("> （只校验不写盘：`python scripts/build_herb_sources.py --check`）")
    lines.append("")
    lines.append(
        f"**覆盖**：属性依据（域 I）**{counts['property_total']} 味**，其中有来源 "
        f"{counts['property_with_source']} 味；体质适配依据（域 II）**{counts['constitution_total']} 条**，"
        f"涉 **{counts['distinct_herbs']} 味**饮片 × 政府来源。"
    )
    lines.append("")
    lines.append(f"> 目的：{meta['purpose']}")
    lines.append(">")
    lines.append(f"> 为什么落 `core/data/`：{meta['why_this_file']}")
    lines.append(">")
    lines.append(f"> 范围：{meta['scope']}")
    lines.append("")
    lines.append("**硬规则**")
    lines.append("")
    for rule in meta["hard_rules"]:
        lines.append(f"- {rule}")
    lines.append("")

    # ---------------- 域 I ----------------
    lines.append("## 1　属性依据（域 I）· 四气五味归经从哪来")
    lines.append("")
    lines.append(
        f"唯一来源是《中华人民共和国药典》2020 年版一部（`chp2020`）。"
        f"{counts['property_total']} 味里 **{counts['property_with_source']} 味**有药典条目。"
        "`project` 列是 `herbs.json` 的**现值**，`delta` 列写它与药典原文的差异 —— "
        "**7 处差异按既有裁定保留项目值，本表只记录、不改数据**。"
    )
    lines.append("")
    lines.append("| 饮片 | 项目四气 | 项目五味 | 项目归经 | 与药典 | 药典原文 | 差异 | 出处 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for e in prop:
        p = e["project"]
        ev = e["evidence"][0] if e["evidence"] else None
        verbatim = ev["verbatim"] if ev else "—（药典未收载）"
        locator = ev["locator"] if ev else "—"
        if ev and ev.get("url"):
            locator = f"[{locator}]({ev['url']})"
        lines.append(
            "| {name} | {nature} | {flavors} | {meridians} | {status} | {verbatim} | {delta} | {locator} |".format(
                name=_cell(e["name"]),
                nature=_cell(p["nature_cn"]),
                flavors=_cell("、".join(p["flavors_cn"])),
                meridians=_cell("、".join(p["meridians"])),
                status=_cell(e["status"]),
                verbatim=_cell(verbatim),
                delta=_cell(e["delta"] or "—"),
                locator=locator,
            )
        )
    lines.append("")
    inconsistent = [e for e in prop if e["status"] == "无源可引"]
    if inconsistent:
        lines.append(
            "**没有属性来源的饮片**：" + "、".join(f"`{e['id']}`（{e['name']}）" for e in inconsistent)
            + " —— 见各条的 `open_question`。"
        )
        lines.append("")

    # ---------------- 域 II ----------------
    lines.append("## 2　体质适配依据（域 II）· 为什么这味适合你的体质")
    lines.append("")
    lines.append(
        "**只登记「政府来源明确点名」的 (体质 × 饮片) 组合**，不做药典功效外推。"
        "这一域回答的是「为什么**推荐**」，**不回答「为什么避开」** —— 来源里写的忌/慎用不在此表。"
    )
    lines.append("")
    lines.append("| 体质 | 饮片 | 来源 | 来源用名 | 对应方式 | 依据原文 | 等级 | 审核 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    registry = meta["source_registry"]
    for e in cons:
        src = registry.get(e["source_id"], {})
        lines.append(
            "| {c} | {h} | {s} | {m} | {how} | {q} | {lv} | {rs} |".format(
                c=_cell(labels.get(e["constitution"], e["constitution"])),
                h=_cell(e["herb_name"]),
                s=_cell(_src_name(src, e["source_id"])),
                m=_cell(e["matched_name"]),
                how=_cell(e["how"]),
                q=_cell(e["quote"]),
                lv=_cell(e["level"]),
                rs=_cell(e["review_status"]),
            )
        )
    lines.append("")

    # ---------------- 来源注册表 ----------------
    lines.append("## 3　来源注册表")
    lines.append("")
    for sid in registry:  # 保持文件里的登记顺序
        s = registry[sid]
        lines.append(f"### `{sid}`")
        lines.append("")
        lines.append(f"- **发布方**：{s['publisher']}")
        lines.append(f"- **标题**：{s['title']}")
        lines.append(f"- **层级**：{s['tier']}")
        lines.append(f"- **强度**：{s['strength']}")
        lines.append(f"- **取得方式**：{s['how']}")
        lines.append(f"- **链接**：{s['url']}")
        if s.get("caveat"):
            lines.append(f"- **注意**：{s['caveat']}")
        lines.append("")

    # ---------------- 已知局限 ----------------
    lines.append("## 4　已知局限（如实）")
    lines.append("")
    for item in meta["known_limitations"]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append(
        f"> 来源优先级：{meta['reference_priority']}"
    )
    lines.append("")
    return "\n".join(lines)


# ------------------------------- 入口 -------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="派生 / 校验饮片侧来源登记表的域 I（只读 herbs.json 与参照表）"
    )
    parser.add_argument("--write", action="store_true",
                        help="落盘 JSON 并渲染 Markdown（默认只打印摘要）")
    parser.add_argument("--check", action="store_true",
                        help="校验磁盘上的 JSON / Markdown 与派生结果一致，不一致则 exit 1")
    parser.add_argument("--json", type=Path, default=JSON_PATH, help="登记表 JSON 路径")
    parser.add_argument("--md", type=Path, default=MD_PATH, help="人读 Markdown 路径")
    parser.add_argument("--herbs", type=Path, default=HERBS_PATH, help="herbs.json 路径")
    parser.add_argument("--ref", type=Path, default=REF_PATH, help="药典参照表路径")
    args = parser.parse_args(argv)

    for path, label in ((args.herbs, "herbs.json"), (args.ref, "药典参照表")):
        if not path.exists():
            print(f"[失败] 找不到{label}: {path}", file=sys.stderr)
            return 2

    herbs = load_json(args.herbs)["herbs"]
    ref = load_json(args.ref)

    if not args.json.exists():
        print(f"[失败] 找不到登记表: {args.json}"
              "（它的事实源，域 II 靠它自己保存；请先从 git 恢复）", file=sys.stderr)
        return 2

    payload = rebuild(load_json(args.json), ref, herbs)
    md_text = render_md(payload)
    json_text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    if args.check:
        problems: list[str] = []
        on_disk = load_json(args.json)
        if on_disk.get("property_entries") != payload["property_entries"]:
            problems.append("property_entries 与派生结果不一致（跑了 --refresh 却没 --write？）")
        if (on_disk.get("_meta") or {}).get("counts") != payload["_meta"]["counts"]:
            problems.append("_meta.counts 与实际内容不一致")
        if not args.md.exists():
            problems.append(f"缺少渲染产物 {args.md}")
        elif args.md.read_text(encoding="utf-8") != md_text:
            problems.append(f"{args.md.name} 与渲染结果不一致（勿手工编辑，请 --write）")
        for p in problems:
            print(f"[问题] {p}", file=sys.stderr)
        if problems:
            print(f"校验失败：{len(problems)} 项问题", file=sys.stderr)
            return 1
        counts = payload["_meta"]["counts"]
        print(
            f"校验通过：属性依据 {counts['property_total']} 味"
            f"（有来源 {counts['property_with_source']}），"
            f"体质依据 {counts['constitution_total']} 条（涉 {counts['distinct_herbs']} 味）"
        )
        return 0

    if args.write:
        args.json.write_text(json_text, encoding="utf-8", newline="\n")
        args.md.parent.mkdir(parents=True, exist_ok=True)
        args.md.write_text(md_text, encoding="utf-8", newline="\n")
        print(f"已写入 {args.json}")
        print(f"已写入 {args.md}")
        return 0

    counts = payload["_meta"]["counts"]
    print("（未写任何文件；加 --write 落盘，加 --check 校验）")
    print(f"属性依据（域 I）：{counts['property_total']} 味")
    for status in ("一致", "不一致", "无源可引"):
        n = sum(1 for e in payload["property_entries"] if e["status"] == status)
        print(f"  {status}：{n}")
    print(f"体质适配依据（域 II）：{counts['constitution_total']} 条，"
          f"涉 {counts['distinct_herbs']} 味饮片")
    print(f"来源注册表：{len(payload['_meta']['source_registry'])} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
