"""终端交互壳：本地助手的最小可用界面（仅标准库）。

设计约束
--------
- **不改核心逻辑层**：本文件只 import `app.*`，不修改 core/ 下任何文件。
- **零新依赖**：只用标准库。`rich` 属后续可选美化，不在这里引入。
- **引导方式与项目现有脚本一致**：一句 sys.path.insert 指向 core/，
  与 scripts/check_setup.py:21、scripts/smoke_offline.py:14 完全相同。

三种用法
--------
    # 1) 纯规则查表（零 LLM、零成本、秒回）—— 面向"只想用数据层"的人
    python ui/terminal/chat.py --resolve 冰啤酒

    # 2) 离线确定性推荐（不调用模型，走规则兜底）
    python ui/terminal/chat.py --offline "中午吃了碗麻辣烫，还喝了杯冰可乐"

    # 3) 默认：双 Agent 全链路（需 DEEPSEEK_API_KEY，约 12–18 秒）
    python ui/terminal/chat.py
    python ui/terminal/chat.py "晚上火锅吃撑了，都是肉" --constitution damp_heat
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# ---- 唯一的"引导"代码：定位仓库根与 core/，再挂进 sys.path ----
REPO_DIR = Path(__file__).resolve().parents[2]
CORE_DIR = REPO_DIR / "core"
sys.path.insert(0, str(CORE_DIR))

# Windows 控制台默认 GBK，中文会乱码（与核心脚本同样处理）。
# stdin 也要一起改：核心脚本不读标准输入，本壳要读，
# 而 Windows 下 stdin 被重定向/管道时用的是系统 locale 编码（cp936），
# 不显式指定 UTF-8 会把中文输入解成乱码。
for _stream in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass

from app.domain.enums import (  # noqa: E402
    CONSTITUTION_LABELS,
    FLAVOR_LABELS,
    NATURE_LABELS,
    Constitution,
    MealTime,
    Nature,
)
from app.domain.models import AnalyzeRequest, ParsedFood, ParsedMeal  # noqa: E402
from app.services import matcher  # noqa: E402
from app.services.food_lookup import (  # noqa: E402
    CONF_SHOW_THRESHOLD,
    match_foods,
    resolve_food,
)

SOURCE_LABELS = {
    "rule": "查表",
    "composed": "按烹饪方式推算",
    "llm": "模型推测",
    "unresolved": "无法判定",
}

EXAMPLES = [
    "中午吃了碗麻辣烫，还喝了杯冰可乐",
    "晚上火锅吃撑了，都是肉，还喝了啤酒",
    "早上就一杯冰美式，中午吃了份沙拉",
    "夜宵吃了炸鸡配奶茶",
]


# ============================================================
# 渲染
# ============================================================
def hr(title: str = "") -> None:
    print("\n" + "=" * 62)
    if title:
        print(title)
        print("=" * 62)


def _nature_label(value: str | None) -> str:
    return NATURE_LABELS.get(value or "unknown", "未知")


def render_parsed(parsed: ParsedMeal) -> None:
    """回显"我理解到的"。显示规则与前端一致：低于阈值不显示寒热属性。"""
    print("\n【我理解到的】")
    if not parsed.foods:
        print("  （没有识别到具体食物）")
    for food in parsed.foods:
        v = food.verification
        # 与 food_lookup.CONF_SHOW_THRESHOLD 的约定同规则：
        # 置信度低于阈值时不显示寒热属性（但数据仍保留并传给 Agent2）。
        show_nature = v.confidence >= CONF_SHOW_THRESHOLD
        nature = _nature_label(food.nature.value) if show_nature else "未判定"
        flavors = "".join(FLAVOR_LABELS.get(f.value, f.value) for f in food.flavors)
        parts = [food.name, nature]
        if flavors:
            parts.append(flavors)
        if food.amount_desc and food.amount_desc != "未指明":
            parts.append(food.amount_desc)
        line = "  · " + " · ".join(parts)
        if v.unverified:
            line += f"  [待验证：{SOURCE_LABELS.get(v.source, v.source)} {v.confidence:.1%}]"
        print(line)
        if v.detail:
            print(f"      {v.detail}")

    print(
        f"  时段：{parsed.meal_time.value} ｜ 整餐偏：{_nature_label(parsed.overall_nature.value)}"
        f" ｜ 把握度：{parsed.confidence:.0%}"
    )
    if parsed.summary:
        print(f"  复述：{parsed.summary}")
    if parsed.uncertain_items:
        print(f"  没认出来的：{'、'.join(parsed.uncertain_items)}")


def render_recommendations(recs: list) -> None:
    print("\n【给你的建议】")
    if not recs:
        print("  （本次没有推荐）")
        return
    for i, rec in enumerate(recs, 1):
        print(f"\n  {i}. 《{rec.title}》  匹配度 {rec.score:.0%}")
        for h in rec.herbs:
            role = f"  {h.role}" if h.role else ""
            print(f"     - {h.name} {h.amount_g:g}g{role}")
        b = rec.brew
        print(f"     冲泡：{b.vessel} ｜ 约 {b.water_ml}ml ｜ {b.water_temp_c}℃ ｜ 焖 {b.steep_min}min"
              f" ｜ 可续水 {b.refill_times} 次")
        for step in b.steps:
            print(f"       · {step}")
        if rec.fit_reason:
            print(f"     理由：{rec.fit_reason}")
        for c in rec.cautions:
            print(f"     ⚠ 注意：{c}")


def render_footer(resp, elapsed_s: float) -> None:
    meta = resp.meta
    print("\n" + "-" * 62)
    print(f"  体质：{resp.basis.constitution_label}", end="")
    if meta.agent1_ms is not None:
        print(f" ｜ Agent1 {meta.agent1_ms}ms", end="")
    if meta.agent2_ms is not None:
        print(f" ｜ Agent2 {meta.agent2_ms}ms", end="")
    print(f" ｜ 合计 {elapsed_s:.1f}s")
    if meta.degraded:
        print(f"  [已降级为规则匹配] {meta.degraded_reason or ''}")
    if resp.basis.rule_hits:
        print(f"  命中规则：{'、'.join(resp.basis.rule_hits)}")
    if resp.basis.guardrail_applied:
        print(f"  护栏介入：{len(resp.basis.guardrail_applied)} 项")
    print(f"\n  {resp.disclaimer.text}")
    print("-" * 62)


# ============================================================
# 三条链路
# ============================================================
def cmd_resolve(names: list[str]) -> int:
    """纯规则查表：零 LLM、零成本。这是数据层对外的最小可用接口。"""
    hr("resolve_food() 确定性判定（不调用模型）")
    for name in names:
        r = resolve_food(name=name)
        v = r.verification
        flavors = "".join(FLAVOR_LABELS.get(f, f) for f in r.flavors)
        print(f"\n  {name}")
        print(f"    四性：{_nature_label(r.nature)}   五味：{flavors or '—'}")
        print(f"    来源：{SOURCE_LABELS.get(v.source, v.source)}"
              f"   置信度：{v.confidence:.1f}"
              f"   待验证：{'是' if v.unverified else '否'}")
        if v.detail:
            print(f"    过程：{v.detail}")
        if r.entry:
            variants = r.entry.get("variant_nature") or {}
            if variants:
                v_text = "；".join(
                    f"{k}→{_nature_label(x)}" for k, x in variants.items()
                )
                print(f"    变体：{v_text}")
    return 0


def _offline_analyze(text: str, constitution: Constitution):
    """离线确定性链路：口述 → match_foods → resolve_food → 规则兜底推荐。

    全程不调用模型，无 API Key 也能出结果；代价是识别粒度取决于关键词表。
    """
    hits = match_foods(text)
    foods: list[ParsedFood] = []
    for entry in hits:
        r = resolve_food(name=entry["name"])
        try:
            nature = Nature(r.nature)
        except ValueError:
            nature = Nature.UNKNOWN
        foods.append(
            ParsedFood(name=entry["name"], nature=nature, verification=r.verification)
        )

    if not foods:
        return None, "没能在食性表里认出任何食物。离线模式只能识别表内条目，换个说法或改用完整模式。"

    conf = round(sum(f.verification.confidence for f in foods) / len(foods), 2)
    parsed = ParsedMeal(
        foods=foods,
        meal_time=MealTime.UNKNOWN,
        overall_nature=Nature.UNKNOWN,
        confidence=conf,
        summary="（离线模式：由关键词匹配 + 查表装配，未使用模型）",
    )
    recs, msg, rule_hits = matcher.fallback_recommend(parsed, constitution)
    return (parsed, recs, msg, rule_hits), None


def cmd_offline(text: str, constitution: Constitution) -> int:
    hr(f"离线确定性模式（不调用模型）：{text}")
    t0 = time.perf_counter()
    result, err = _offline_analyze(text, constitution)
    if err:
        print(f"\n  {err}")
        return 1
    parsed, recs, msg, rule_hits = result
    render_parsed(parsed)
    if msg:
        print(f"\n  {msg}")
    render_recommendations(recs)
    print("\n" + "-" * 62)
    print(f"  体质：{CONSTITUTION_LABELS.get(constitution.value, constitution.value)}"
          f" ｜ 命中规则：{'、'.join(rule_hits)} ｜ 耗时 {time.perf_counter() - t0:.2f}s")
    print("  说明：本模式全程未调用模型，属性仅覆盖食性表内条目。")
    from app.domain.models import Disclaimer
    print(f"\n  {Disclaimer().text}")
    print("-" * 62)
    return 0 if recs else 1


def cmd_full(text: str, constitution: Constitution) -> int:
    """双 Agent 全链路。需 API Key；耗时 12–18 秒。"""
    from app.services.orchestrator import AnalyzeError, analyze

    hr(f"正在解析你的饮食…（双 Agent 串行，通常 10–30 秒）")
    print(f"  {text}")
    t0 = time.perf_counter()
    try:
        resp = analyze(
            AnalyzeRequest(text=text, constitution_override=constitution)
        )
    except AnalyzeError as exc:
        print(f"\n  [解析失败] {exc.code}：{exc.message}")
        print("  提示：换个更具体的说法；若反复失败，检查 credentials.env 里的 API Key。")
        return 1
    except Exception as exc:  # pragma: no cover - 兜底
        print(f"\n  [请求失败] {type(exc).__name__}: {exc}")
        return 1

    elapsed = time.perf_counter() - t0
    if resp.user_message:
        print(f"\n【说明】\n  {resp.user_message}")
    render_parsed(resp.parsed)
    render_recommendations(resp.recommendations)
    render_footer(resp, elapsed)
    return 0


# ============================================================
# 交互循环
# ============================================================
def pick_constitution(explicit: str | None) -> Constitution:
    if explicit:
        try:
            return Constitution(explicit)
        except ValueError:
            print(f"  [警告] 未知体质 {explicit!r}，改用平和质。"
                  f"可选：{'、'.join(c.value for c in Constitution)}")
    return Constitution.BALANCED


def repl(offline: bool) -> int:
    constitution = Constitution.BALANCED
    mode = "离线确定性模式（不调用模型）" if offline else "双 Agent 全链路"
    hr("中医饮食茶饮助手 · 终端版")
    print(f"  模式：{mode}")
    print(f"  体质：{CONSTITUTION_LABELS.get(constitution.value, constitution.value)}")
    print("  直接输入你吃了什么；输入 :q 退出，:c <体质> 切换体质，:e 看示例。")
    print("  ⚠ 输出仅供日常饮食参考，不构成医疗建议。")

    while True:
        try:
            line = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见。")
            return 0

        if not line:
            continue
        if line in (":q", ":quit", ":exit"):
            print("再见。")
            return 0
        if line == ":e":
            for i, ex in enumerate(EXAMPLES, 1):
                print(f"  {i}. {ex}")
            continue
        if line.startswith(":c"):
            arg = line[2:].strip()
            if not arg:
                print("  用法：:c yang_deficiency")
                print(f"  可选：{'、'.join(c.value for c in Constitution)}")
                continue
            constitution = pick_constitution(arg)
            print(f"  体质已切换为：{CONSTITUTION_LABELS.get(constitution.value, constitution.value)}")
            continue

        if offline:
            cmd_offline(line, constitution)
        else:
            cmd_full(line, constitution)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="中医饮食茶饮助手 · 本地终端界面",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python ui/terminal/chat.py --resolve 冰啤酒 白米饭\n"
            "  python ui/terminal/chat.py --offline \"中午吃了碗麻辣烫\"\n"
            "  python ui/terminal/chat.py \"夜宵吃了炸鸡配奶茶\" --constitution damp_heat\n"
        ),
    )
    parser.add_argument("text", nargs="*", help="一句话描述你吃了什么；不传则进入交互模式")
    parser.add_argument("--resolve", nargs="+", metavar="NAME",
                        help="只做纯规则查表（零 LLM、零成本）")
    parser.add_argument("--offline", action="store_true",
                        help="离线确定性模式：不调用模型，走规则兜底")
    parser.add_argument("--constitution", default=None,
                        help=f"体质，可选：{'、'.join(c.value for c in Constitution)}")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出（便于脚本化）")
    args = parser.parse_args()

    if args.resolve:
        if args.json:
            out = []
            for name in args.resolve:
                r = resolve_food(name=name)
                out.append({
                    "name": name, "nature": r.nature, "flavors": r.flavors,
                    "source": r.verification.source,
                    "confidence": r.verification.confidence,
                    "unverified": r.verification.unverified,
                    "detail": r.verification.detail,
                })
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 0
        return cmd_resolve(args.resolve)

    text = " ".join(args.text).strip()
    if not text:
        return repl(args.offline)

    constitution = pick_constitution(args.constitution)
    if args.offline:
        return cmd_offline(text, constitution)
    return cmd_full(text, constitution)


if __name__ == "__main__":
    raise SystemExit(main())
