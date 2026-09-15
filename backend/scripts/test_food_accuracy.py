"""Agent1 属性判定准确率测试。

这是本次改动的核心验证：把"模型凭语感猜属性"变成"查表后照抄"，
到底提升了多少，用固定语料量出来。

用法（在 backend 目录下）：
    python scripts/test_food_accuracy.py

注意：每条语料都要调用一次模型，约 1–3 秒，默认 12 条语料。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass

# 语料 + 期望属性。期望值来自 data/food_properties.json（人工核对过的通行表述）。
# 只断言"至少有一个食物命中期望属性"，避免因拆分粒度不同而误判。
CASES: list[dict] = [
    {"text": "下午喝了杯茉莉花茶", "expect": {"茉莉花茶": "warm"}},
    {"text": "中午吃了个小笼包配豆浆", "expect": {"小笼包": "neutral", "豆浆": "neutral"}},
    {"text": "晚上吃了烧烤配啤酒", "expect": {"啤酒": "cool"}},
    # 冰饮：凉/寒都属于可接受判定（程度差异有主观性），
    # 关键是不能再判成温或平——本项用于确认冰镇信息被采纳
    {"text": "喝了两瓶冰啤酒", "expect": {"啤酒": ("cool", "cold")}},
    {"text": "中午吃了碗兰州拉面", "expect": {"兰州拉面": "neutral"}},
    {"text": "晚上火锅吃撑了，都是肉", "expect": {"火锅": "hot"}},
    {"text": "吃了关东煮和烤红薯", "expect": {"关东煮": "warm", "烤红薯": "warm"}},
    {"text": "中午吃了个三明治配冰美式", "expect": {"三明治": "neutral", "冰美式": ("cool", "cold")}},
    {"text": "喝了杯菊花茶", "expect": {"菊花茶": "cool"}},
    {"text": "晚上喝了碗银耳莲子羹", "expect": {"银耳": "neutral"}},
    {"text": "吃了根香蕉和一个苹果", "expect": {"香蕉": "cold", "苹果": "cool"}},
    {"text": "中午吃了清蒸鲈鱼配白米饭", "expect": {"白米饭": "neutral"}},
    # 补充：温性茶饮与平性主食的易错项
    {"text": "喝了杯玫瑰花茶，吃了碗白粥", "expect": {"玫瑰花茶": "warm", "白粥": "neutral"}},
    {"text": "早上吃了馒头配牛奶", "expect": {"馒头": "neutral", "牛奶": "neutral"}},
    # 外国/新式食物：实测发现这类词会被误配到相近的中式通用条目
    {"text": "下午吃了杯希腊酸奶", "expect": {"希腊酸奶": "cool"}},
    {"text": "点了份韩式炸鸡配可乐", "expect": {"韩式炸鸡": "hot"}},
    {"text": "中午吃了份意大利面", "expect": {"意大利面": "neutral"}},
    {"text": "晚上吃了寿司配味增汤", "expect": {"寿司": "cool"}},
    {"text": "中午吃了个牛肉汉堡和薯条", "expect": {"牛肉汉堡": "warm"}},
    {"text": "吃了咖喱鸡饭", "expect": {"咖喱": "hot"}},
    # 温度前缀层（纯规则）：冰镇 -1、加热 +1
    # 注意：本层依赖温度字出现在**食物名**里。
    # 若模型把"去冰"放进 note 而不是 name（实测会发生），本层看不到，
    # 那时会退回表值——这是已知局限，见 docs/three-layer-architecture.md
    {"text": "喝了瓶冰镇啤酒", "expect": {"啤酒": "cold"}},
    {"text": "睡前喝了杯热牛奶", "expect": {"牛奶": "warm"}},
]


def norm(name: str) -> str:
    """名称归一化，容忍模型加前后缀（如「冰美式咖啡」「白米饭」）。"""
    return name.replace(" ", "").strip()


def match(expected_name: str, actual_name: str) -> bool:
    a, e = norm(actual_name), norm(expected_name)
    return e in a or a in e or (len(e) >= 2 and e[:2] == a[:2])


def main() -> int:
    from app.agents.agent1_diet import parse_diet
    from app.services.food_lookup import table_stats

    stats = table_stats()
    print("=" * 78)
    print("Agent1 属性判定准确率测试")
    print(f"参考表规模：食材 {stats['foods']} 条 + 茶饮 {stats['tea_drinks']} 条 = {stats['total']} 条")
    print("=" * 78)

    total_checks = 0
    passed_checks = 0
    parsed_ok = 0
    unknown_count = 0
    all_foods = 0
    failures: list[str] = []

    for i, case in enumerate(CASES, 1):
        text = case["text"]
        expect = case["expect"]
        try:
            parsed, ms, _ = parse_diet(text)
        except Exception as exc:
            print(f"\n{i:2d}. [解析失败] {text}\n    {str(exc)[:90]}")
            failures.append(f"{text} → 解析失败")
            total_checks += len(expect)
            continue

        parsed_ok += 1
        got = {f.name: f.nature.value for f in parsed.foods}
        all_foods += len(parsed.foods)
        unknown_count += sum(1 for v in got.values() if v == "unknown")

        line_ok = True
        detail: list[str] = []
        for name, want in expect.items():
            total_checks += 1
            accepted = want if isinstance(want, tuple) else (want,)
            hit = None
            for actual_name, actual_nature in got.items():
                if match(name, actual_name):
                    hit = actual_nature
                    break
            if hit in accepted:
                passed_checks += 1
                detail.append(f"{name}={hit} ✓")
            else:
                line_ok = False
                want_text = "/".join(accepted)
                detail.append(f"{name} 期望{want_text} 实际{hit or '未识别'} ✗")
                failures.append(f"{text} → {name} 期望 {want_text}，实际 {hit or '未识别'}")

        mark = "OK " if line_ok else "BAD"
        print(f"\n{i:2d}. [{mark}] {text}（{ms}ms）")
        print(f"    识别：{'、'.join(f'{k}({v})' for k, v in got.items()) or '（空）'}")
        print(f"    判定：{'；'.join(detail)}")

    print("\n" + "=" * 78)
    print("汇总")
    print(f"  语料解析成功：{parsed_ok}/{len(CASES)}")
    print(f"  属性判定正确：{passed_checks}/{total_checks}"
          f"（{passed_checks / max(total_checks, 1) * 100:.0f}%）")
    print(f"  属性 unknown 数：{unknown_count}/{all_foods}"
          f"（占比 {unknown_count / max(all_foods, 1) * 100:.0f}%）")
    if failures:
        print(f"\n  未达标项（{len(failures)}）：")
        for f in failures:
            print(f"    - {f}")
    else:
        print("\n  全部达到期望值。")

    # 判定门槛：属性准确率 90% 以上，且 unknown 占比压到 10% 以内
    acc = passed_checks / max(total_checks, 1)
    unk = unknown_count / max(all_foods, 1)
    print()
    if acc >= 0.9 and unk <= 0.10:
        print("  结论：通过（准确率 ≥90%，unknown ≤10%）")
        return 0
    print("  结论：未通过。准确率需 ≥90% 且 unknown ≤10%，请继续调表或调提示词。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
