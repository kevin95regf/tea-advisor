"""数据表结构升级与条目修正（幂等，可重复运行）。

本脚本做三件事：
  1. 把二值 `reviewed` 升级为三态 `review_status`：
     approved（已审核通过）/ pending（待审核）/ rejected（审核不通过）
     为什么需要三态：`reviewed: false` 无法区分"还没审"和"审了但不认可"。
     后者绝不能被当作高置信度硬规则使用。
  2. 修正内容重叠的条目（这类重叠会让短名条目抢走具体菜名的匹配）。
  3. 记录修正原因到 review_note，便于日后追溯。

用法（在 backend 目录下）：
    python scripts/patch_food_table.py --dry-run
    python scripts/patch_food_table.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass

TABLE = BACKEND_DIR / "data" / "food_properties.json"

VALID_STATUS = ("approved", "pending", "rejected")

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
