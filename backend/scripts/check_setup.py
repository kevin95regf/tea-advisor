"""环境与数据自检脚本（不调用模型，秒级完成）。

用法（在 backend 目录下）：
    python scripts/check_setup.py

它会检查：
  1. .env 是否存在、DEEPSEEK_API_KEY 是否已填
  2. DSH_HOME 路径是否合法（纯英文）
  3. deepseek-harness-sdk 是否安装
  4. herbs.json / constitution.json 是否能通过 Pydantic 校验
  5. 安全护栏的若干基本行为
"""

from __future__ import annotations

import sys
from pathlib import Path

# 允许从项目根直接运行本脚本
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows 控制台默认 GBK，中文会乱码
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass

OK = "  [OK]  "
WARN = "  [警告]"
FAIL = "  [失败]"

problems: list[str] = []


def line(symbol: str, text: str) -> None:
    print(f"{symbol} {text}")


def main() -> int:
    print("=" * 62)
    print("茶饮推荐后端 · 环境自检")
    print("=" * 62)

    # ---------- 1. 配置 ----------
    print("\n[1/5] 配置与环境变量")
    from app.config import BACKEND_DIR, PROJECT_ROOT, get_settings

    settings = get_settings()
    line(OK, f"项目根目录: {PROJECT_ROOT}")
    line(OK, f"后端目录:   {BACKEND_DIR}")

    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        line(OK, f".env 已存在: {env_file}")
    else:
        line(WARN, ".env 不存在，请复制 .env.example 为 .env 并填入 API Key")
        problems.append("缺少 .env")

    if settings.has_credentials:
        key = settings.deepseek_api_key or ""
        line(OK, f"DEEPSEEK_API_KEY 已设置（{key[:6]}...{key[-4:] if len(key) > 10 else ''}）")
    else:
        line(FAIL, "DEEPSEEK_API_KEY 未设置 —— 无法调用模型")
        problems.append("缺少 DEEPSEEK_API_KEY")

    line(OK, f"模型: {settings.model}（provider={settings.provider}）")

    # ---------- 2. DSH_HOME ----------
    print("\n[2/5] DSH 运行时目录")
    dsh_home = Path(settings.dsh_home)
    if any("\u4e00" <= ch <= "\u9fff" for ch in str(dsh_home)):
        line(FAIL, f"DSH_HOME 含中文，子进程链路可能出问题: {dsh_home}")
        problems.append("DSH_HOME 含中文")
    else:
        line(OK, f"DSH_HOME 为纯英文路径: {dsh_home}")
    if dsh_home.exists():
        line(OK, "DSH_HOME 目录已存在")
    else:
        line(WARN, "DSH_HOME 目录不存在，首次启动时会自动创建")

    try:
        import deepseek_harness  # noqa: F401

        line(OK, "deepseek-harness-sdk 已安装")
    except Exception as exc:
        line(FAIL, f"deepseek-harness-sdk 未安装或无法导入: {exc}")
        line(WARN, "执行：pip install deepseek-harness-sdk")
        problems.append("SDK 未安装")

    # ---------- 3. 数据文件 ----------
    print("\n[3/5] 数据文件")
    import json

    from app.domain.models import CatalogHerb

    herbs_path = settings.data_dir / "herbs.json"
    if not herbs_path.exists():
        line(FAIL, f"缺少 {herbs_path}")
        problems.append("缺少 herbs.json")
        herbs: list[dict] = []
    else:
        raw = json.loads(herbs_path.read_text(encoding="utf-8"))
        herbs = raw.get("herbs", [])
        line(OK, f"herbs.json 加载成功，共 {len(herbs)} 味饮片")

    bad: list[str] = []
    for item in herbs:
        try:
            CatalogHerb(**item)
        except Exception as exc:
            bad.append(f"{item.get('name', '?')}: {str(exc)[:80]}")
    if bad:
        line(FAIL, f"{len(bad)} 味饮片字段不合法")
        for b in bad[:5]:
            print(f"         - {b}")
        problems.append("herbs.json 字段问题")
    elif herbs:
        line(OK, "全部饮片字段校验通过（四气/五味/归经/上限/禁忌齐备）")

    names = [h["name"] for h in herbs]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        line(FAIL, f"存在重复饮片名: {dupes}")
    elif herbs:
        line(OK, "无重复饮片名")

    cons_path = settings.data_dir / "constitution.json"
    if cons_path.exists():
        cons = json.loads(cons_path.read_text(encoding="utf-8")).get("constitutions", [])
        line(OK, f"constitution.json 加载成功，共 {len(cons)} 型体质")
    else:
        line(FAIL, "缺少 constitution.json")
        problems.append("缺少 constitution.json")

    # ---------- 4. 提示词 ----------
    print("\n[4/5] 提示词文件")
    for name in ("agent1_system.md", "agent2_system.md"):
        path = settings.prompts_dir / name
        if path.exists():
            size = len(path.read_text(encoding="utf-8"))
            line(OK, f"{name}（{size} 字）")
        else:
            line(FAIL, f"缺少 {name}")
            problems.append(f"缺少 {name}")

    # ---------- 5. 护栏行为 ----------
    print("\n[5/5] 安全护栏行为抽查")
    from app.domain.safety import (
        check_blend,
        detect_high_risk,
        filter_by_constitution,
        scan_free_text,
    )

    checks = [
        ("剂量超限被裁剪", lambda: bool(check_blend([{"name": "甘草", "amount_g": 50}]).warnings)),
        ("白名单外饮片被拦", lambda: bool(check_blend([{"name": "附子", "amount_g": 3}]).blocked)),
        ("禁用表述被检出", lambda: bool(scan_free_text("这个可以治疗失眠").blocked)),
        ("高风险人群被识别", lambda: bool(detect_high_risk("我怀孕了能喝吗"))),
        ("体质筛选可用", lambda: len(filter_by_constitution("yang_deficiency")) > 0),
    ]
    for desc, fn in checks:
        try:
            if fn():
                line(OK, desc)
            else:
                line(FAIL, f"{desc} —— 未按预期触发")
                problems.append(desc)
        except Exception as exc:
            line(FAIL, f"{desc} —— 抛异常: {exc}")
            problems.append(desc)

    # ---------- 汇总 ----------
    print("\n" + "=" * 62)
    if problems:
        print(f"自检完成：{len(problems)} 项待处理")
        for p in problems:
            print(f"  - {p}")
        print("\n提示：模型相关的问题不影响数据层，可先跑通启动流程。")
        return 1
    print("自检完成：全部通过，可以进入下一步（跑 agent 冒烟）。")
    print("下一步：python scripts/smoke_agent1.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
