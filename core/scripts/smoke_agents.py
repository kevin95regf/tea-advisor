"""真实模型冒烟：验证 dsh Python SDK 能跑通，并单测 Agent1 / Agent2 / 串联。

用法（在 core 目录下，需先配好 .env 里的 DEEPSEEK_API_KEY）：

    python scripts/smoke_agents.py            # 跑默认 3 条语料，全链路
    python scripts/smoke_agents.py --only a1  # 只测 Agent1
    python scripts/smoke_agents.py --case 1   # 只跑第 1 条语料

第一次运行会启动 dsh 子进程并生成 profile，约需十几秒。
子进程的 stderr 会写到 var/dsh_runtime.log，排查启动问题先看它。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

CORE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CORE_DIR))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass

CASES: list[dict] = [
    {
        "text": "中午吃了碗麻辣烫，还喝了杯冰可乐，米饭没吃完",
        "constitution": "phlegm_damp",
        "expect_rule": "spicy",
    },
    {
        "text": "晚上跟朋友吃火锅，全是肉，还喝了两瓶啤酒，撑得不行",
        "constitution": "damp_heat",
        "expect_rule": "greasy",
    },
    {
        "text": "早上就一杯冰美式，中午吃了份蔬菜沙拉",
        "constitution": "yang_deficiency",
        "expect_rule": "cold_intake",
    },
]


def hr(title: str) -> None:
    print("\n" + "=" * 62)
    print(title)
    print("=" * 62)


def main() -> int:
    parser = argparse.ArgumentParser(description="真实模型冒烟测试")
    parser.add_argument("--only", choices=["a1", "a2", "full"], default="full")
    parser.add_argument("--case", type=int, default=None, help="只跑指定序号（从 1 开始）")
    args = parser.parse_args()

    from app.config import get_settings

    settings = get_settings()

    hr("0. 前置检查")
    if not settings.has_credentials:
        print("  [失败] " + settings.missing_credentials_hint())
        return 1
    print(f"  [通过] API Key 已配置：{settings.deepseek_api_key[:6]}...")
    print(f"  [通过] 模型：{settings.model} / {settings.provider}")
    print(f"  [通过] DSH_HOME：{settings.dsh_home}")

    # 让子进程把 agent 的 persona 换成我们的系统提示词。
    # 注意：必须在启动进程之前设置，且只影响本脚本（不进入 .env，避免污染主环境）。
    prompts_dir = settings.prompts_dir
    os.environ.setdefault(
        "DSH_SYSTEM_PROMPT",
        (prompts_dir / "agent1_system.md").read_text(encoding="utf-8")[:4000],
    )
    # 运行时诊断日志
    var_dir = CORE_DIR / "var"
    var_dir.mkdir(exist_ok=True)
    log_file = open(var_dir / "dsh_runtime.log", "a", encoding="utf-8")  # noqa: SIM115
    print(f"  [通过] 运行时日志：{log_file.name}")

    from app.agents.runtime import get_runtime

    runtime = get_runtime()

    hr("1. 启动 DSH 运行时")
    t0 = time.perf_counter()
    try:
        runtime.ensure_started()
    except Exception as exc:
        print(f"  [失败] 启动失败：{exc}")
        print("\n排查建议：")
        print("  1) 确认 .env 里的 DEEPSEEK_API_KEY 正确")
        print("  2) 确认 DSH_HOME 是纯英文绝对路径且可写")
        print(f"  3) 查看日志：{log_file}")
        return 1
    print(f"  [通过] 运行时就绪，耗时 {time.perf_counter() - t0:.1f}s")

    hr("2. 原始往返测试（验证 SDK 基本可用）")
    try:
        # session id 必须唯一：复用同一个 id 会延续同一段持久对话，
        # 重复跑本脚本时会直接报 "session already exists"。
        run = runtime.run("只回复两个字：收到", session_id=f"ta-smoke-ping-{time.time_ns()}")
        print(f"  [通过] 模型回复：{run.text.strip()[:60]!r}（{run.elapsed_ms}ms）")
    except Exception as exc:
        print(f"  [失败] 往返失败：{exc}")
        return 1

    indices = [args.case - 1] if args.case else list(range(len(CASES)))
    failures: list[str] = []

    # ---------- Agent 1 ----------
    if args.only in ("a1", "full"):
        hr("3. Agent1 饮食解析（真实模型）")
        from app.agents.agent1_diet import parse_diet

        for i in indices:
            case = CASES[i]
            label = f"用例{i + 1}"
            try:
                parsed, ms, _ = parse_diet(case["text"])
                foods = "、".join(
                    f"{f.name}({f.nature.value})" for f in parsed.foods
                )
                print(f"\n  {label}：{case['text']}")
                print(f"    → {len(parsed.foods)} 项：{foods or '（空）'}")
                print(
                    f"    → 时段={parsed.meal_time.value} 整餐={parsed.overall_nature.value} "
                    f"把握度={parsed.confidence:.2f}（{ms}ms）"
                )
                if parsed.summary:
                    print(f"    → 复述：{parsed.summary}")
                if parsed.uncertain_items:
                    print(f"    → 未识别：{'、'.join(parsed.uncertain_items)}")
                if not parsed.foods:
                    failures.append(f"{label} 未解析出食物")
                if parsed.confidence < 0.3:
                    failures.append(f"{label} 把握度过低（{parsed.confidence:.2f}）")
            except Exception as exc:
                print(f"\n  {label} [失败]：{exc}")
                failures.append(f"{label} 解析失败")

    # ---------- 全链路 ----------
    if args.only in ("a2", "full"):
        hr("4. 全链路（Agent1 → Agent2 → 护栏）")
        from app.domain.enums import Constitution
        from app.services.orchestrator import AnalyzeError, analyze
        from app.domain.models import AnalyzeRequest

        for i in indices:
            case = CASES[i]
            label = f"用例{i + 1}"
            try:
                resp = analyze(
                    AnalyzeRequest(
                        text=case["text"],
                        constitution_override=Constitution(case["constitution"]),
                    )
                )
                print(f"\n  {label}：{case['text']}")
                print(f"    → 体质：{resp.basis.constitution_label}")
                print(
                    f"    → 耗时：A1 {resp.meta.agent1_ms}ms / "
                    f"A2 {resp.meta.agent2_ms}ms / 合计 {resp.meta.total_ms}ms"
                )
                if resp.meta.degraded:
                    print(f"    → [已降级] {resp.meta.degraded_reason}")
                if resp.user_message:
                    print(f"    → 说明：{resp.user_message}")
                if not resp.recommendations:
                    print("    → 无推荐")
                    failures.append(f"{label} 无推荐")
                for rec in resp.recommendations:
                    blend = " + ".join(
                        f"{h.name}{h.amount_g:g}g" for h in rec.herbs
                    )
                    print(f"    → 《{rec.title}》{blend}（匹配度 {rec.score:.2f}）")
                    print(f"       理由：{rec.fit_reason}")
                    for c in rec.cautions:
                        print(f"       注意：{c}")
                if resp.basis.guardrail_applied:
                    print(f"    → 护栏介入 {len(resp.basis.guardrail_applied)} 项")
                print(f"    → 免责声明版本：{resp.disclaimer.version}")
            except AnalyzeError as exc:
                print(f"\n  {label} [失败] {exc.code}：{exc.message}")
                failures.append(f"{label} 编排失败")
            except Exception as exc:
                print(f"\n  {label} [失败]：{exc}")
                failures.append(f"{label} 异常")

    hr("结果")
    runtime.close()
    log_file.close()
    if failures:
        print(f"  {len(failures)} 项失败：")
        for f in failures:
            print(f"    - {f}")
        print(f"\n  提示：模型输出有随机性，偶发失败可先重跑一次；稳定失败请调提示词。")
        return 1
    print("  全部通过。可以进入下一步：启动服务 + 打开网页 demo。")
    print("    uvicorn app.main:app --reload --port 8000")
    print("    http://127.0.0.1:8000/demo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
