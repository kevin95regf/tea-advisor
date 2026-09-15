"""离线冒烟：不调用模型，验证数据层 → 解析 → 规则兜底 → 护栏 全链路可跑。

用法（在 core 目录下）：
    python scripts/smoke_offline.py

它证明的是"除模型外的所有环节都是通的"，这样一旦接上 API Key 只剩模型本身的不确定性。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows 控制台默认 GBK，中文会乱码
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass

from app.agents.agent1_diet import build_user_prompt as a1_prompt
from app.agents.agent2_recommend import build_user_prompt as a2_prompt
from app.agents.json_guard import JsonGuardError, parse_lenient, validate
from app.domain.enums import Constitution, CookingMethod, MealTime, Nature
from app.domain.models import AnalyzeRequest, ParsedFood, ParsedMeal
from app.domain.safety import check_blend, detect_high_risk
from app.services import matcher
from app.services.orchestrator import _sanitize_recommendations

PASS = "  [通过]"
FAIL = "  [失败]"
failures: list[str] = []


def check(desc: str, cond: bool, extra: str = "") -> None:
    if cond:
        print(f"{PASS} {desc}")
    else:
        print(f"{FAIL} {desc} {extra}")
        failures.append(desc)


def main() -> int:
    print("=" * 62)
    print("离线冒烟测试（不调用模型）")
    print("=" * 62)

    # ---------- 1. json_guard ----------
    print("\n[1/5] JSON 解析护栏")
    messy = '好的，这是结果：\n```json\n{"foods":[{"name":"麻辣烫","amount_desc":"一碗"}],"confidence":0.8}\n```\n希望有帮助！'
    try:
        obj = parse_lenient(messy)
        check("能从围栏+闲聊文本中提取 JSON", obj.get("foods")[0]["name"] == "麻辣烫")
    except JsonGuardError as exc:
        check("能从围栏+闲聊文本中提取 JSON", False, str(exc))

    try:
        validate(ParsedMeal, messy)
        check("能直接校验成 ParsedMeal", True)
    except JsonGuardError as exc:
        check("能直接校验成 ParsedMeal", False, str(exc))

    try:
        validate(ParsedMeal, '{"foods": [{"name": "饭", "nature": "超级热"}]}')
        check("非法枚举值应被拒绝", False, "竟然通过了")
    except JsonGuardError:
        check("非法枚举值应被拒绝", True)

    try:
        validate(ParsedMeal, '{"foods": [{"name": "饭"')
        check("截断的 JSON 应被拒绝", False, "竟然通过了")
    except JsonGuardError:
        check("截断的 JSON 应被拒绝", True)

    # ---------- 2. 提示词构造 ----------
    print("\n[2/5] 提示词构造")
    p1 = a1_prompt("中午吃了麻辣烫", MealTime.LUNCH)
    check("Agent1 提示词含用户原话", "麻辣烫" in p1)
    check("Agent1 提示词含时段", "lunch" in p1)

    fake_meal = ParsedMeal(
        foods=[ParsedFood(name="麻辣烫", amount_desc="一碗", nature=Nature.HOT, note="麻辣汤底")],
        meal_time=MealTime.LUNCH,
        overall_nature=Nature.HOT,
        confidence=0.85,
        summary="午餐吃了麻辣烫",
    )
    p2 = a2_prompt(fake_meal, Constitution.PHLEGM_DAMP)
    check("Agent2 提示词注入了解析结果", "麻辣烫" in p2)
    check("Agent2 提示词注入了体质", "痰湿" in p2)
    check("Agent2 提示词含候选白名单", "陈皮" in p2 and "茯苓" in p2)
    check("Agent2 提示词未泄露原始口述之外的自由文本", "用户口述" not in p2)

    # ---------- 3. 规则兜底 ----------
    print("\n[3/5] 规则兜底推荐")
    recs, msg, hits = matcher.fallback_recommend(fake_meal, Constitution.PHLEGM_DAMP)
    check("能产出推荐", len(recs) >= 1)
    check("推荐有饮片", bool(recs and recs[0].herbs))
    check("推荐有冲泡步骤", bool(recs and recs[0].brew.steps))
    check("麻辣烫命中辛辣场景（优先润燥）", "spicy" in hits, f"hits={hits}")
    check("有用户可读说明", bool(msg))

    # 纯油腻场景应走消食
    greasy_meal = ParsedMeal(
        foods=[ParsedFood(name="红烧肉", nature=Nature.WARM, cooking=CookingMethod.BOILED, note="很油")],
        meal_time=MealTime.DINNER,
        overall_nature=Nature.WARM,
        confidence=0.85,
    )
    greasy_recs, _, greasy_hits = matcher.fallback_recommend(
        greasy_meal, Constitution.PHLEGM_DAMP
    )
    check("油腻场景命中消食规则", "greasy" in greasy_hits, f"hits={greasy_hits}")
    check("消食推荐含山楂或陈皮", any(
        h.name in ("山楂", "陈皮") for h in greasy_recs[0].herbs
    ) if greasy_recs else False)

    cold_meal = ParsedMeal(
        foods=[ParsedFood(name="冰可乐", nature=Nature.COLD, note="冰镇")],
        overall_nature=Nature.COLD,
        confidence=0.9,
    )
    cold_recs, _, cold_hits = matcher.fallback_recommend(cold_meal, Constitution.YANG_DEFICIENCY)
    check("生冷场景命中温中规则", "cold_intake" in cold_hits, f"hits={cold_hits}")

    # ---------- 4. 护栏 ----------
    print("\n[4/5] 护栏与清洗")
    res = check_blend([{"name": "甘草", "amount_g": 50}, {"name": "附子", "amount_g": 3}])
    check("超剂量产生警告", any("甘草" in w for w in res.warnings))
    check("白名单外饮片被拦", any("附子" in b for b in res.blocked))
    check("整体标记为不通过", res.ok is False)

    cleaned, applied = _sanitize_recommendations(
        matcher.fallback_recommend(fake_meal, Constitution.PHLEGM_DAMP)[0],
        Constitution.PHLEGM_DAMP,
        exclude_herbs=[],
    )
    check("正常推荐能通过清洗", len(cleaned) == 1)
    check("清洗结果保留饮片", bool(cleaned and cleaned[0].herbs))

    excluded, _ = _sanitize_recommendations(
        matcher.fallback_recommend(fake_meal, Constitution.PHLEGM_DAMP)[0],
        Constitution.PHLEGM_DAMP,
        exclude_herbs=["陈皮", "山楂"],
    )
    check("用户排除全部饮片时推荐被作废或换料", len(excluded) == 0 or all(
        h.name not in ("陈皮", "山楂") for h in excluded[0].herbs
    ))

    # ---------- 5. 编排入口 ----------
    print("\n[5/5] 编排入口（高风险分支）")
    req = AnalyzeRequest(text="我怀孕了，今天吃了火锅，能喝什么茶", constitution_override=Constitution.BALANCED)
    check("高风险关键词被识别", len(detect_high_risk(req.text)) > 0)

    # 高风险分支不调用模型，可以安全地直接跑
    from app.services.orchestrator import analyze as run_analyze

    resp = run_analyze(req)
    check("高风险请求返回空推荐", len(resp.recommendations) == 0)
    check("高风险请求标记降级", resp.meta.degraded is True)
    check("高风险请求带免责声明", resp.disclaimer.is_medical_advice is False)
    check("高风险请求引导就医", "医师" in resp.user_message or "药师" in resp.user_message)

    # ---------- 汇总 ----------
    print("\n" + "=" * 62)
    if failures:
        print(f"冒烟结果：{len(failures)} 项失败")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("冒烟结果：全部通过。数据层、护栏、规则兜底均已就绪。")
    print("下一步：配好凭据后运行 python scripts/smoke_agents.py 验证真实模型调用。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
