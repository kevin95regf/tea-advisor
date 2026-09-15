"""给 food_properties.json 补逐条审核字段（一次性迁移，可重复运行）。

为什么需要逐条审核状态
----------------------
原来只有整表的 `review_status: pending`，无法回答"这 300 条里哪几条已经让中医师看过了"。
三层架构里，硬规则库的属性会被当作高置信度（0.9）直接采信，
所以"哪几条已审核"必须是数据的一部分，而不是靠记忆。

用法（在 backend 目录下）：
    python scripts/add_review_fields.py            # 执行迁移
    python scripts/add_review_fields.py --dry-run  # 只看会改什么

幂等：已有 reviewed 字段的条目不重复写入。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass

TABLE = BACKEND_DIR / "data" / "food_properties.json"

# 分层修正的说明：写进 _meta，作为数据文件的自我描述
LAYER_NOTES = {
    "correction_layers": {
        "layer_1_food_variant": (
            "食材变体层：同一种食材因形态不同而属性不同（如 红薯 平 → 烤红薯 温）。"
            "由条目的 variant_nature 字段提供，查表优先，直接取值，不做加减。"
        ),
        "layer_2_cooking": (
            "烹饪修正层：条目没有对应变体记录时的通用兜底。"
            "蒸煮 ≈ 0，煎炸 +1，烧烤 +1，加辛辣配料 +1，冰镇 -1。"
            "仅在 layer_1 未命中时生效，否则会破坏表里精确的变体值。"
        ),
        "order": "layer_1 优先；未命中才走 layer_2；两者都不适用则属性不可判定。",
    },
    "confidence_convention": {
        "rule": 0.9,
        "composed": 0.6,
        "llm": 0.3,
        "unresolved": 0.1,
        "note": "低于 0.3 时界面不显示寒热属性；所有非 rule 来源必须标注。",
    },
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只报告，不写文件")
    args = parser.parse_args()

    if not TABLE.exists():
        print(f"[失败] 找不到 {TABLE}")
        return 1

    raw = json.loads(TABLE.read_text(encoding="utf-8"))
    meta = raw.setdefault("_meta", {})
    today = date.today().isoformat()

    # 1) _meta 补充分层说明与置信度约定
    changed_meta: list[str] = []
    for key, value in LAYER_NOTES.items():
        if key not in meta:
            meta[key] = value
            changed_meta.append(key)

    # 2) 逐条补 review 字段
    groups = [
        ("foods", raw.get("foods", [])),
        ("tea_drinks", (raw.get("tea_drinks") or {}).get("items", [])),
    ]

    added = 0
    skipped = 0
    for group_name, items in groups:
        for entry in items:
            if "reviewed" in entry:
                skipped += 1
                continue
            entry["reviewed"] = False
            entry["reviewed_by"] = None
            entry["reviewed_at"] = None
            entry["review_note"] = None
            added += 1

    print("=" * 66)
    print("food_properties.json 审核字段迁移")
    print("=" * 66)
    print(f"  表文件：{TABLE}")
    print(f"  _meta 新增字段：{changed_meta or '（无）'}")
    print(f"  条目新增 review 字段：{added} 条")
    print(f"  已有字段跳过：{skipped} 条")

    total = sum(len(items) for _, items in groups)
    print(f"  条目总数：{total}")

    if args.dry_run:
        print("\n  [dry-run] 未写入文件。")
        return 0

    TABLE.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",  # 强制 LF：仓库用 .gitattributes 统一 LF，Windows 默认 CRLF 会造成假 diff
    )
    print(f"\n  已写入。请用 git diff 复核，然后让审核人逐条把 reviewed 改为 true。")
    print(f"  建议审核完成时间记录为 reviewed_at，审核人写 reviewed_by。")
    print(f"  参考：{today}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
