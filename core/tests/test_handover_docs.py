"""交接文档与挂起清单的结构完整性测试。

交接文档是最容易腐烂的一类文档：它引用一堆文件路径、承诺一堆决策、列一堆待办，
而这些东西随时会变。这些测试只守**结构**（不守具体措辞），目的是让它烂掉时会失败，
而不是安静地把接手的人带偏。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

CORE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = CORE_DIR.parent
DOCS = PROJECT_ROOT / "docs"
HANDOVER = DOCS / "handover.md"
PENDING = DOCS / "pending-items.md"

# handover.md 必须覆盖的章节（用户明确要求的全貌要素）
REQUIRED_HANDOVER_SECTIONS = [
    "一分钟版本",
    "核心设计原则",
    "目录结构与分层规则",
    "数据资产",
    "当前状态",
    "所有已定决策",
    "未决事项",
    "文档地图",
    "工作区状态",
    "新接手者的前 30 分钟",
]

# pending-items.md 必须覆盖的挂起类目
REQUIRED_PENDING_SECTIONS = ["A 类", "B 类", "C 类", "D 类", "E 类"]

# 用户点名要求进清单的事项，各自至少有一个 ID 覆盖
REQUIRED_PENDING_TOPICS = {
    "中华本草": "《中华本草》列全空",
    "国标 A 栏": "A 栏转引待替换",
    "药典不一致": "7 处不一致待 nanple 复核",
    "phlegm_dampness": "问卷拼写不一致",
    "244": "244 个配伍判定",
}


@pytest.fixture(scope="module")
def handover() -> str:
    return HANDOVER.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def pending() -> str:
    return PENDING.read_text(encoding="utf-8")


# ------------------------------ 存在性与章节 ------------------------------


def test_both_docs_exist():
    assert HANDOVER.is_file(), HANDOVER
    assert PENDING.is_file(), PENDING


def test_handover_covers_required_sections(handover):
    for section in REQUIRED_HANDOVER_SECTIONS:
        assert section in handover, f"handover.md 缺少章节：{section}"


def test_pending_covers_required_categories(pending):
    for section in REQUIRED_PENDING_SECTIONS:
        assert section in pending, f"pending-items.md 缺少类目：{section}"


def test_pending_covers_user_requested_topics(pending):
    for needle, label in REQUIRED_PENDING_TOPICS.items():
        assert needle in pending, f"挂起清单缺少事项：{label}"


def test_handover_points_to_pending_as_source_of_truth(handover):
    assert "pending-items.md" in handover
    assert "唯一真源" in handover


def test_pending_declares_itself_the_source_of_truth(pending):
    assert "唯一真源" in pending


# -------------------------------- 决策编号 --------------------------------


def test_handover_decision_numbers_are_contiguous(handover):
    """§6 的决策表从 1 编号到最后一条，不允许跳号（跳号=有人删了决定没说明）。"""
    section = handover.split("## 6. 所有已定决策")[1].split("## 7. 未决事项")[0]
    nums = []
    for line in section.splitlines():
        m = re.match(r"\|\s*(\d+)\s*\|", line)
        if m:
            nums.append(int(m.group(1)))
    assert nums, "没解析到任何决策编号"
    assert nums == list(range(1, len(nums) + 1)), f"决策编号不连续：{nums}"


def test_handover_decision_count_matches_last_number(handover):
    section = handover.split("## 6. 所有已定决策")[1].split("## 7. 未决事项")[0]
    nums = [int(m.group(1)) for m in re.finditer(r"\|\s*(\d+)\s*\|", section)]
    assert max(nums) == len(nums)


# ------------------------------ 挂起项的结构 ------------------------------


def _overview_block(text: str) -> str:
    """取「## 概览」到下一个真正的水平分隔线之间的内容。

    注意不能用 text.split("---")：markdown 表格的分隔行 `|---|---|` 里也含 `---`。
    """
    tail = text.split("## 概览", 1)[1]
    return re.split(r"\n---\s*\n", tail, maxsplit=1)[0]


def _pending_ids(text: str) -> list[str]:
    """从概览表第一列抓 ID（形如 **A1**）。"""
    return re.findall(r"\*\*([A-E]\d+)\*\*", _overview_block(text))


def test_pending_ids_unique(pending):
    ids = _pending_ids(pending)
    assert ids, "没解析到挂起项 ID"
    assert len(ids) == len(set(ids)), f"ID 重复：{ids}"


def test_every_overview_id_has_a_detail_section(pending):
    ids = _pending_ids(pending)
    for pid in ids:
        assert f"## {pid}" in pending, f"{pid} 在概览里但缺少详情小节"


def test_every_detail_section_is_in_overview(pending):
    details = set(re.findall(r"^## ([A-E]\d+)　", pending, re.M))
    overview = set(_pending_ids(pending))
    missing = details - overview
    assert not missing, f"有详情但不在概览里：{sorted(missing)}"


def test_every_pending_item_has_owner_and_status(pending):
    """每个挂起项都必须写清谁负责、什么状态 —— 否则清单等于没写。"""
    overview = _overview_block(pending)
    rows = [l for l in overview.splitlines()
            if l.startswith("|") and "---" not in l and "ID" not in l]
    assert rows, "概览表为空"
    for row in rows:
        cells = [c.strip() for c in row.strip("|").split("|")]
        assert len(cells) >= 4, row
        owner, status_raw = cells[-3], cells[-1]
        assert owner and owner != "—", f"缺责任人：{row}"
        # 状态列允许带 ✅/⛔ 等装饰，先剥掉再判断
        status = status_raw.strip("✅⛔* `")
        assert status.startswith(("待", "已")), f"状态可疑：{status_raw!r}"


def test_pending_marks_hard_blockers(pending):
    """硬阻碍必须有显式标记，不能和普通事项混在一起。"""
    assert "⛔" in pending
    overview = _overview_block(pending)
    assert overview.count("⛔") >= 2, "至少 A1 与 B3 应标为硬阻碍"


def test_pending_uses_relative_commands_not_machine_paths(pending):
    """命令要能在任何机器上跑，不能写死 D:\\work\\...。"""
    assert "D:\\work\\tea-advisor" not in pending


# ------------------------------ 引用的文件存在 ----------------------------


def _referenced_repo_paths(text: str) -> set[str]:
    """抓反引号里看起来像仓库内路径的串。"""
    out = set()
    for raw in re.findall(r"`([^`\n]+)`", text):
        s = raw.strip()
        if "/" not in s:
            continue
        if s.startswith(("http", "POST", "GET", "-")):
            continue
        if not re.match(r"^[\w\-./]+$", s):
            continue
        if not (s.startswith(("core/", "docs/", "ui/", "tcm-constitution-questionnaire/"))
                or s.endswith((".py", ".md", ".json", ".html", ".cmd", ".toml", ".csv"))):
            continue
        out.add(s)
    return out


@pytest.mark.parametrize("doc_name", ["handover.md", "pending-items.md"])
def test_referenced_paths_exist(doc_name):
    """文档里提到的仓库内路径必须真实存在 —— 这条最能在重构后立刻报错。"""
    text = (DOCS / doc_name).read_text(encoding="utf-8")
    missing = []
    for rel in sorted(_referenced_repo_paths(text)):
        # 允许目录（末尾带 /）与通配（如 agents/prompts/*.md）
        if "*" in rel:
            parent = PROJECT_ROOT / Path(rel).parent
            if not parent.is_dir():
                missing.append(rel)
            continue
        if not (PROJECT_ROOT / rel).exists():
            missing.append(rel)
    assert not missing, f"{doc_name} 引用了不存在的路径：{missing}"


# ------------------------------ 安全与格式 --------------------------------


@pytest.mark.parametrize("doc_name", ["handover.md", "pending-items.md"])
def test_docs_contain_no_key_material(doc_name):
    """交接文档绝不能出现真实的 Key。

    注意三件事：
    - `sk-` 本身可以出现（文档要描述这个模式、要写 `sk-...` 占位符）
    - 测试哨兵常量 `sk-SENTINEL-...` 是**已知的、刻意造的**常量，它本来就在
      `tests/test_key_handling.py` 里，文档引用它来说明扫描结果也是合理的
    - 除此之外，任何 `sk-` 后跟一串像 Key 的字符都不允许
    """
    text = (DOCS / doc_name).read_text(encoding="utf-8")
    hits = [h for h in re.findall(r"sk-[A-Za-z0-9_-]{8,}", text)
            if not h.upper().startswith("SK-SENTINEL")]
    assert not hits, f"{doc_name} 里出现疑似真 Key：{hits}"


@pytest.mark.parametrize("doc_name", ["handover.md", "pending-items.md"])
def test_docs_are_lf_only(doc_name):
    text = (DOCS / doc_name).read_text(encoding="utf-8")
    assert "\r\n" not in text, f"{doc_name} 含 CRLF（本仓库强制 LF）"


def test_handover_states_its_snapshot_date(handover):
    assert "2026-09-17" in handover


def test_pending_states_its_snapshot_date(pending):
    assert "2026-09-17" in pending


# --------------------------- 与代码现状的一致性 ---------------------------


def test_handover_venv_guidance_matches_reality():
    """交接文档说 core/.venv 才是可用的那个 —— 这条断言它没写反。"""
    text = HANDOVER.read_text(encoding="utf-8")
    assert "core/.venv" in text
    # core/.venv 必须真的存在且带 pytest
    assert (PROJECT_ROOT / "core" / ".venv" / "Scripts" / "python.exe").is_file()


def test_handover_documents_the_two_backends(handover):
    assert "TA_BACKEND" in handover
    assert "direct" in handover and "dsh" in handover


def test_handover_documents_the_layering_rule(handover):
    assert "ui/" in handover and "core/" in handover
    assert "不 import ui" in handover or "永远不 import" in handover


def test_pending_e1_matches_actual_data_state():
    """E1 说只有 3 条缺 review_status —— 断言这个数字仍然准确。"""
    import json

    d = json.loads((CORE_DIR / "data" / "food_properties.json").read_text(encoding="utf-8"))
    recs = d["foods"] + d["tea_drinks"]["items"]
    missing = [r["name"] for r in recs if not r.get("review_status")]
    assert len(missing) == 3, f"缺 review_status 的条数变了：{missing}"
    text = PENDING.read_text(encoding="utf-8")
    for name in missing:
        assert name in text, f"E1 没列出 {name}"
