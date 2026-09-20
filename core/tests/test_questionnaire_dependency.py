"""问卷子包的依赖隔离守卫（D5 的 L3）。

D5 的口径：core 的**领域层 / 服务层 / 代理层**永不 import 可选问卷子包 `tcm_constitution`；
唯一允许碰它的是 API 端点 `app/api/questionnaire.py`（函数内 lazy import，缺失 → 501）。

这条不变量原本只是口头约定 —— 本文件把它变成可执行的不变量，与
`test_medication_reference.py` 的隔离守卫同形：禁引用清单 + 白名单 + 负控制。
"""
from __future__ import annotations

import re
from pathlib import Path

CORE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = CORE_DIR / "app"

SCAN_DIRS = ("domain", "services", "agents")
FORBIDDEN = "tcm_constitution"
# 白名单：只有端点层可以出现，且必须是函数内的 lazy import
WHITELIST = {"app/api/questionnaire.py"}
# 下限，不是写死的精确值：防「一个文件都没扫到还显示通过」这种恒真
MIN_FILES = 10


def _collect_files() -> list[Path]:
    files: list[Path] = []
    for sub in SCAN_DIRS:
        files.extend(sorted((APP_DIR / sub).rglob("*.py")))
    return files


def _forbidden_refs(files: list[Path]) -> list[str]:
    bad: list[str] = []
    for path in files:
        try:
            rel = path.relative_to(CORE_DIR).as_posix()
        except ValueError:  # 负控制样本在 CORE_DIR 之外
            rel = path.as_posix()
        if rel in WHITELIST:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(FORBIDDEN, text):
            line = text[:m.start()].count("\n") + 1
            bad.append(f"{rel}:{line} 出现了 {FORBIDDEN}")
    return bad


def test_scan_range_is_not_empty() -> None:
    files = _collect_files()
    assert len(files) >= MIN_FILES, (
        f"只扫到 {len(files)} 个文件（应 ≥{MIN_FILES}）⇒ 扫描范围可能算错了，判据会恒真"
    )


def test_core_layers_never_import_questionnaire_package() -> None:
    assert _forbidden_refs(_collect_files()) == []


def test_whitelist_target_exists() -> None:
    """白名单指向的端点必须存在；端点被移动/删除后这条会红，逼着更新白名单。"""
    target = APP_DIR / "api" / "questionnaire.py"
    assert target.is_file(), f"{target} 不存在 ⇒ 白名单条目已失效，请更新本守卫"


def test_guard_catches_forbidden_reference(tmp_path: Path) -> None:
    """负控制：合成一个含禁引用的文件，守卫必须报红（否则说明正则或扫法失效）。"""
    leak = tmp_path / "leak.py"
    leak.write_text(
        "from tcm_constitution import score_questionnaire\n",
        encoding="utf-8",
        newline="\n",
    )
    assert _forbidden_refs([leak]) != []
