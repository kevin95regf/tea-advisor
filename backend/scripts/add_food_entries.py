"""把新增食性条目合并进 food_properties.json。

为什么用脚本而不是手改 JSON
--------------------------
表的字段较多（nature/flavors/keywords/variant_nature/review 系列），
手工在多行 JSON 里插条目极易漏字段或破坏语法。这里按数据结构插入，
并自动为 review 字段补默认值，保证幂等（同 id 不重复添加）。

用法（在 backend 目录下）：
    python scripts/add_food_entries.py --dry-run
    python scripts/add_food_entries.py
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

# 本次新增：主要针对"外国/新式食物"，实测发现这类词会被误配到相近的中式通用条目
# （例如「希腊酸奶」被当成普通「酸奶」、「韩式炸鸡」被当成普通「炸鸡」）。
NEW_ENTRIES: list[dict] = [
    {
        "id": "xila_suannai",
        "name": "希腊酸奶",
        "aliases": ["希腊式酸奶", "greek yogurt"],
        "category": "乳饮",
        "nature": "cool",
        "flavors": ["sweet", "sour"],
        "keywords": ["希腊酸奶", "希腊式酸奶", "greek"],
        "note": "脱乳清后质地厚、味偏酸，较普通酸奶更偏凉；多为冷藏食用",
        "variant_nature": {"cold": "cold"},
    },
    {
        "id": "hanshi_zhaji",
        "name": "韩式炸鸡",
        "aliases": ["韩式炸鸡块", "korean fried chicken"],
        "category": "菜肴",
        "nature": "hot",
        "flavors": ["salty", "pungent", "sweet"],
        "keywords": ["韩式炸鸡", "韩式炸鸡块", "korean"],
        "note": "油炸 + 甜辣酱，偏燥热",
    },
    {
        "id": "yidali_mian",
        "name": "意大利面",
        "aliases": ["意面", "pasta", "spaghetti"],
        "category": "主食",
        "nature": "neutral",
        "flavors": ["sweet"],
        "keywords": ["意大利面", "意面", "pasta", "spaghetti"],
        "note": "本质为小麦制品，属性近面条；配奶油白酱偏滋腻，配番茄酱偏凉",
    },
    {
        "id": "shousi",
        "name": "寿司",
        "aliases": ["寿司卷", "sushi"],
        "category": "主食",
        "nature": "cool",
        "flavors": ["sweet", "sour", "salty"],
        "keywords": ["寿司", "寿司卷", "sushi"],
        "note": "米饭平，但常配生鱼与醋，整体偏凉；生食款更偏寒",
        "variant_nature": {"raw": "cold"},
    },
    {
        "id": "niurou_hanbao",
        "name": "牛肉汉堡",
        "aliases": ["芝士汉堡", "cheeseburger"],
        "category": "主食",
        "nature": "warm",
        "flavors": ["salty", "sweet"],
        "keywords": ["牛肉汉堡", "芝士汉堡", "cheeseburger"],
        "note": "牛肉温 + 煎烤，整体偏温",
    },
    {
        "id": "zhayu_shutiao",
        "name": "炸鱼薯条",
        "aliases": ["fish and chips"],
        "category": "菜肴",
        "nature": "hot",
        "flavors": ["salty"],
        "keywords": ["炸鱼薯条", "fish and chips", "炸鱼"],
        "note": "双重油炸，偏燥热",
    },
    {
        "id": "niuyouguo_shala",
        "name": "牛油果沙拉",
        "aliases": ["avocado salad"],
        "category": "菜肴",
        "nature": "cool",
        "flavors": ["sweet", "sour"],
        "keywords": ["牛油果沙拉", "avocado"],
        "note": "生食蔬菜水果为主，偏凉",
    },
    {
        "id": "hanshi_banfan",
        "name": "韩式拌饭",
        "aliases": ["石锅拌饭", "bibimbap"],
        "category": "菜肴",
        "nature": "warm",
        "flavors": ["pungent", "salty", "sweet"],
        "keywords": ["韩式拌饭", "石锅拌饭", "bibimbap", "拌饭"],
        "note": "多配辣酱，石锅款偏温热",
    },
    {
        "id": "rishi_lamian",
        "name": "日式拉面",
        "aliases": ["豚骨拉面", "ramen"],
        "category": "菜肴",
        "nature": "warm",
        "flavors": ["salty", "sweet"],
        "keywords": ["日式拉面", "豚骨拉面", "ramen"],
        "note": "热汤浓汤底，偏温",
    },
    {
        "id": "gali",
        "name": "咖喱",
        "aliases": ["咖喱饭", "curry"],
        "category": "菜肴",
        "nature": "hot",
        "flavors": ["pungent", "salty"],
        "keywords": ["咖喱", "curry"],
        "note": "姜黄、辣椒、香料为主，偏温热",
    },
    {
        "id": "tusi",
        "name": "吐司",
        "aliases": ["全麦吐司", "toast"],
        "category": "主食",
        "nature": "neutral",
        "flavors": ["sweet"],
        "keywords": ["吐司", "toast"],
        "note": "小麦制品，属性近馒头；烤过略偏温",
        "variant_nature": {"grilled": "warm"},
    },
    {
        "id": "sanmingzhi_huotui",
        "name": "火腿三明治",
        "aliases": ["ham sandwich"],
        "category": "主食",
        "nature": "neutral",
        "flavors": ["salty"],
        "keywords": ["火腿三明治", "ham sandwich"],
        "note": "面包平，火腿偏温，整体近平",
    },
    {
        "id": "suannai_wan",
        "name": "酸奶碗",
        "aliases": ["酸奶水果碗", "yogurt bowl"],
        "category": "甜点",
        "nature": "cool",
        "flavors": ["sweet", "sour"],
        "keywords": ["酸奶碗", "yogurt bowl"],
        "note": "冷藏酸奶加水果，偏凉",
    },
]

REVIEW_DEFAULTS = {
    "reviewed": False,
    "reviewed_by": None,
    "reviewed_at": None,
    "review_note": None,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    raw = json.loads(TABLE.read_text(encoding="utf-8"))
    foods = raw.setdefault("foods", [])
    existing_ids = {e.get("id") for e in foods}
    existing_names = {e.get("name") for e in foods}

    to_add: list[dict] = []
    conflicts: list[str] = []
    for entry in NEW_ENTRIES:
        if entry["id"] in existing_ids or entry["name"] in existing_names:
            conflicts.append(f"{entry['name']}（已存在，跳过）")
            continue
        merged = dict(entry)
        for key, value in REVIEW_DEFAULTS.items():
            merged.setdefault(key, value)
        to_add.append(merged)

    print("=" * 60)
    print("合并新增食性条目")
    print("=" * 60)
    print(f"  待新增：{len(to_add)} 条")
    for e in to_add:
        print(f"    + {e['name']}（{e['nature']}）")
    if conflicts:
        print(f"  跳过：{len(conflicts)} 条")
        for c in conflicts:
            print(f"    - {c}")

    if args.dry_run:
        print("\n  [dry-run] 未写入。")
        return 0

    foods.extend(to_add)
    TABLE.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",  # 强制 LF，避免 Windows 默认 CRLF 在 git 里造成假 diff
    )
    print(f"\n  已写入，表内食材共 {len(foods)} 条。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
