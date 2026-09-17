"""把 docs/constitution-9-types.json 渲染成 docs/constitution-9-types.md。

用法（在 core 目录下）：

    python scripts/build_constitution_doc.py                      # 生成 docs/constitution-9-types.md
    python scripts/build_constitution_doc.py --out ../tmp/x.md     # 写到别处
    python scripts/build_constitution_doc.py --check               # 只校验，不写文件（有风险则 exit 1）

设计要点：
- **JSON 是单一事实源**，MD 是渲染产物，避免两份文档各说各话（本项目已经吃过文档漂移的亏）。
- C 栏（本项目调养原则）**实时读取 core/data/constitution.json**，不复制粘贴，
  因此项目数据一改，渲染出来就跟着变，不会对不上。
- A 栏（国标特征）与 B 栏（饮食方向）刻意分开渲染，并在每一条上标出来源，
  任何时候都不允许把「转引」写成「原文」、把「解读」写成「国标」。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CORE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = CORE_DIR.parent
DEFAULT_REF = PROJECT_ROOT / "docs" / "constitution-9-types.json"
DEFAULT_OUT = PROJECT_ROOT / "docs" / "constitution-9-types.md"
PROJECT_CONSTITUTIONS = CORE_DIR / "data" / "constitution.json"

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass

# 来源短标签（纯展示用，放在脚本里而不是数据文件里）
SHORT_LABELS = {
    "kjrb_wangqi": "科技日报·专访王琦院士 2026-02-10",
    "wangqi_press": "国家中医药管理局发布会·王琦院士 2026-04-29",
    "cnr_natcm": "央广网/央视新闻 2026-04-29",
    "cnr_health": "央广网 2026-02-16（受访：熊暑霖）",
    "gd_tcm": "广东省中医药局 2023-03-22",
    "openstd": "国家标准全文公开系统",
    "bucm": "北京中医药大学 2026-02-03",
    "zytcm_bao": "《中国中医药报》2026-01-26",
    "zytcm_bao_gd": "广东省中医药局 2026-01-20",
}


def load_reference(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_project_constitutions() -> dict[str, dict]:
    """项目现有体质数据，按 id 索引。文件缺失时返回空字典（不抛异常）。"""
    if not PROJECT_CONSTITUTIONS.exists():
        return {}
    raw = json.loads(PROJECT_CONSTITUTIONS.read_text(encoding="utf-8"))
    return {c["id"]: c for c in raw.get("constitutions", [])}


def validate(ref: dict, project: dict[str, dict]) -> list[str]:
    """返回问题列表。空列表表示一致。"""
    problems: list[str] = []
    cons = ref.get("constitutions", [])
    if len(cons) != 9:
        problems.append(f"体质数量应为 9，实际 {len(cons)}")

    labels = [c["label"] for c in cons]
    if len(labels) != len(set(labels)):
        problems.append("体质名称有重复")

    known_sources = {s["key"] for s in ref.get("sources", [])}
    known_sources |= {s["key"] for s in ref.get("standard", {}).get("sources", [])}

    for c in cons:
        for layer in ("features", "diet_direction"):
            if not c.get(layer):
                problems.append(f"{c['label']}：{layer} 为空")
            for item in c.get(layer, []):
                if item.get("source") not in known_sources:
                    problems.append(f"{c['label']}：{layer} 引用了未登记的来源 {item.get('source')!r}")
                if not item.get("text", "").strip():
                    problems.append(f"{c['label']}：{layer} 有空条目")

        # 项目内体质：C 栏必须能在 constitution.json 里找到，且快照要与实时数据一致
        pid = c.get("id")
        if c.get("in_project"):
            if not pid:
                problems.append(f"{c['label']}：in_project 为真但没有 id")
            elif pid not in project:
                problems.append(f"{c['label']}：id {pid!r} 在 constitution.json 里不存在")
            else:
                snap = c.get("project_principles")
                live = project[pid]
                if snap is None:
                    problems.append(f"{c['label']}：缺少 project_principles 快照")
                else:
                    for field in ("one_line", "principles", "direction", "avoid"):
                        if snap.get(field) != live.get(field):
                            problems.append(
                                f"{c['label']}：project_principles.{field} 快照与 "
                                f"constitution.json 不一致（快照已过期，请更新 JSON）"
                            )
        else:
            if not pid:
                problems.append(f"{c['label']}：缺少 id")
            elif pid in project:
                problems.append(f"{c['label']}：标为未收录，但 id {pid!r} 已在 constitution.json 里")
            if c.get("project_principles") is not None:
                problems.append(f"{c['label']}：未收录的体质不应有 project_principles")

    return problems


def cite(source_key: str, sources: dict[str, dict]) -> str:
    src = sources.get(source_key)
    if not src:
        return f"〔来源未登记：{source_key}〕"
    short = SHORT_LABELS.get(source_key, src["label"])
    return f"〔{src.get('kind', '来源')}·{short}〕"


def render(ref: dict, project: dict[str, dict]) -> str:
    std = ref["standard"]
    sources = {s["key"]: s for s in ref["sources"]}
    for s in std.get("sources", []):
        sources.setdefault(s["key"], s)
    src_by_key = {s["key"]: s for s in ref["sources"]}

    L: list[str] = []
    L.append("# GB/T 46939-2025 九种体质：特征与饮食方向")
    L.append("")
    L.append("> **本文件由 `core/scripts/build_constitution_doc.py` 从 "
             "`docs/constitution-9-types.json` 渲染生成，请勿手工编辑。** 重新生成：")
    L.append("> `cd core && python scripts/build_constitution_doc.py`")
    L.append("")
    L.append(f"> 编译日期：{ref['_meta']['compiled_at']}　版本：{ref['_meta']['version']}")
    L.append("")

    # ---------- 读之前必须知道 ----------
    must_know = ref["_meta"]["read_this_first"]
    cn_num = "零一二三四五六七八九"
    heading_n = cn_num[len(must_know)] if len(must_know) < len(cn_num) else str(len(must_know))
    L.append(f"## 0. 读这份文档前必须知道的{heading_n}件事")
    L.append("")
    for i, item in enumerate(must_know, 1):
        L.append(f"{i}. {item}")
    L.append("")
    L.append("三层结构：")
    L.append("")
    L.append("| 层 | 内容 | 性质 |")
    L.append("|---|---|---|")
    layers = ref["_meta"]["layers"]
    L.append(f"| **A** | {layers['A']} | 转引，**不是标准正文** |")
    L.append(f"| **B** | {layers['B']} | 解读/科普，**不是国标内容** |")
    L.append(f"| **C** | {layers['C']} | 项目自有数据 |")
    L.append("")

    # ---------- 标准信息 ----------
    L.append("## 1. 国家标准基本信息")
    L.append("")
    L.append("这一节是可核实的官方元数据，来源列在表格下方：")
    L.append("")
    L.append("| 项目 | 内容 |")
    L.append("|---|---|")
    rows = [
        ("标准号", std["code"]),
        ("中文名称", std["name_zh"]),
        ("英文名称", std["name_en"]),
        ("标准状态", std["status"]),
        ("发布日期", std["published_at"]),
        ("实施日期", std["effective_at"]),
        ("中国标准分类号（CCS）", std["ccs"]),
        ("国际标准分类号（ICS）", std["ics"]),
        ("提出部门", std["proposing_body"]),
        ("主管部门", std["admin_body"]),
        ("技术委员会", std["technical_committee"]),
        ("发布单位", std["publishing_bodies"]),
        ("起草牵头单位", std["drafting_lead"]),
        ("参与起草", std["drafting_participants"]),
        ("标准性质", std["nature"]),
        ("前身", std["predecessor"]),
        ("前身应用情况", std["predecessor_usage"]),
        ("辨识量表", std["questionnaire"]),
        ("判定阈值", std["threshold_note"]),
        ("证据基础", std["evidence_base"]),
    ]
    for k, v in rows:
        L.append(f"| {k} | {v} |")
    L.append("")
    L.append("**三大关键修订：**")
    L.append("")
    for i, r in enumerate(std["key_revisions"], 1):
        L.append(f"{i}. {r}")
    L.append("")
    L.append("来源：" + "；".join(
        f"[{s['label']}]({s['url']})" for s in std.get("sources", [])))
    L.append("")

    # ---------- 标准正文获取状态 ----------
    fs = std["fulltext_status"]
    L.append("### 1.1 ⚠️ 标准正文未能获取（所以 A 栏是转引）")
    L.append("")
    L.append(fs["detail"])
    L.append("")
    L.append(f"**如何补齐：** {fs['how_to_fill_layer_a']}")
    L.append("")

    # ---------- 速览 ----------
    L.append("## 2. 九型速览")
    L.append("")
    L.append("| 体质 | A 栏 · 国标特征（转引） | B 栏 · 饮食方向（解读） | C 栏 · 本项目 |")
    L.append("|---|---|---|---|")
    for c in ref["constitutions"]:
        feats = c["features"][0]["text"] if c["features"] else "—"
        diet = c["diet_direction"][0]["text"] if c["diet_direction"] else "—"
        if len(diet) > 60:
            diet = diet[:58] + "……"
        if c["in_project"]:
            proj = f"已收录（`{c['id']}`）"
        else:
            proj = f"**未收录**（id 已定：`{c['id']}`）"
        L.append(f"| **{c['label']}** | {feats} | {diet} | {proj} |")
    L.append("")
    L.append("> 九型的 id 已于 2026-09-17 全部确认，见 §4 的「四个新体质的英文 id 已确认」。")
    L.append("")
    L.append("> ⚠️ **「已收录」不等于「可对外服务」。** 上表说的是 `core/data/constitution.json` "
             "里有没有这一型的调养原则（C 栏）。一个体质能否出现在用户可选的选项里，"
             "另由 `core/data/herbs.json` 有没有为它标注饮片决定"
             "（判据见 `core/app/domain/safety.py` 的 `ready_constitutions()`）。"
             "两者是分开的，别把「C 栏有内容」读成「功能已上线」。")
    L.append("")

    # ---------- 逐型详情 ----------
    L.append("## 3. 逐型详情")
    L.append("")
    for c in ref["constitutions"]:
        title = c["label"] + f"　`{c['id']}`"
        if not c["in_project"]:
            title += "　（本项目未收录）"
        L.append(f"### {title}")
        L.append("")
        L.append("**A 栏 · 国标特征的官方转引**　⚠️ 非标准正文")
        L.append("")
        for item in c["features"]:
            L.append(f"- {item['text']} {cite(item['source'], sources)}")
        L.append("")
        L.append("**B 栏 · 饮食方向**　⚠️ 非国标内容，系解读/科普")
        L.append("")
        for item in c["diet_direction"]:
            L.append(f"- {item['text']} {cite(item['source'], sources)}")
        L.append("")
        L.append("**C 栏 · 本项目调养原则**")
        L.append("")
        if c["in_project"] and c.get("project_principles"):
            p = c["project_principles"]
            L.append(f"- 一句话：{p['one_line']}")
            L.append(f"- 调养原则：{'；'.join(p['principles'])}")
            L.append(f"- 方向：{'；'.join(p['direction'])}")
            L.append(f"- 避免：{'；'.join(p['avoid'])}")
        else:
            L.append("- **暂无（项目未收录此体质）**")
        L.append("")

    # ---------- 待确认 ----------
    L.append("## 4. 开放项与待确认")
    L.append("")
    for item in ref.get("open_items", []):
        L.append(f"### {item['title']}　`{item['status']}`")
        L.append("")
        L.append(item["detail"])
        L.append("")

    # ---------- 来源清单 ----------
    L.append("## 5. 来源清单")
    L.append("")
    L.append("| 短标签 | 完整出处 | 类型 | 日期 |")
    L.append("|---|---|---|---|")
    for s in ref["sources"]:
        short = SHORT_LABELS.get(s["key"], s["key"])
        L.append(f"| {short} | [{s['label']}]({s['url']}) | {s.get('kind', '')} | {s.get('date', '')} |")
    L.append("")
    L.append("标准元数据来源：")
    L.append("")
    for s in std.get("sources", []):
        L.append(f"- [{s['label']}]({s['url']})　{s.get('kind', '')}　{s.get('date', '')}")
    L.append("")
    L.append("---")
    L.append("")
    L.append("> 提醒：A 栏是**转引**，B 栏**不是国标内容**。GB/T 46939-2025 只规定体质分类与"
             "判定方法，不提供任何饮食或饮片建议。任何人引用本文件时都应保留这一区分。")
    L.append("")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="渲染九种体质参考文档（JSON → Markdown）")
    parser.add_argument("--ref", type=Path, default=DEFAULT_REF, help="参考数据 JSON 路径")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="输出的 Markdown 路径")
    parser.add_argument("--check", action="store_true", help="只校验一致性，不写文件")
    args = parser.parse_args(argv)

    if not args.ref.exists():
        print(f"[失败] 找不到参考数据: {args.ref}", file=sys.stderr)
        return 2

    ref = load_reference(args.ref)
    project = load_project_constitutions()
    problems = validate(ref, project)

    for p in problems:
        print(f"[问题] {p}", file=sys.stderr)

    if args.check:
        if problems:
            print(f"校验失败：{len(problems)} 项问题", file=sys.stderr)
            return 1
        print(f"校验通过：9 型齐备，来源可追溯，C 栏与 constitution.json 一致"
              f"（项目已收录 {sum(1 for c in ref['constitutions'] if c['in_project'])}/9 型）")
        return 0

    text = render(ref, project)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # 显式 newline="\n"：本仓库强制 LF
    with args.out.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print(f"已写入 {args.out}")
    if problems:
        print(f"[警告] 存在 {len(problems)} 项问题，渲染仍已完成，但请先修复", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
