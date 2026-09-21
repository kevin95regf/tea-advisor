"""README 里的事实性声明必须与仓库实际一致。

为什么单列一个文件：`test_handover_docs.py` 只守 `handover.md` 与 `pending-items.md`，
而 README 是**新接手者读的第一份文档**——它写的数字与路径没人守。实测过后果：
`scripts\\test_food_accuracy.py` 这条路径在仓库根下根本不存在（脚本全在
`core/scripts/`），静默失效了很久，2026-09-21 才发现。

三条都是**派生**断言（从仓库现算，不写死数字）：
  1. README 声明的测试项数 == 现场 `--collect-only` 收集到的条数；
  2. README 声明的测试文件数 == `core/tests/test_*.py` 的实际个数；
  3. README 反引号里引用的仓库内路径必须存在。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

CORE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = CORE_DIR.parent
README = PROJECT_ROOT / "README.md"


@pytest.fixture(scope="module")
def readme() -> str:
    return README.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def collected_count() -> int:
    """现跑一次收集数用例 —— 不断言「等于 754」，写死了下次加测试就红。"""
    proc = subprocess.run(
        [
            sys.executable, "-m", "pytest", "core/tests",
            "--collect-only", "-q", "-p", "no:cacheprovider",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, f"收集失败：{proc.stdout[-600:]}｜{proc.stderr[-600:]}"
    n = sum(1 for line in proc.stdout.splitlines() if "::" in line)
    assert n > 0, "没收集到任何用例"
    return n


def _claimed_test_counts(text: str) -> set[int]:
    """README 里所有形如「N 项 / N passed」的三位以上声明。"""
    return {int(m.group(1)) for m in re.finditer(r"(\d{3,4})\s*(?:项|passed)", text)}


def test_readme_declares_a_test_count(readme):
    assert _claimed_test_counts(readme), "README 里找不到任何测试项数声明"


def test_readme_test_count_matches_collection(readme, collected_count):
    wrong = sorted(n for n in _claimed_test_counts(readme) if n != collected_count)
    assert not wrong, f"README 写的测试项数与实收集不符（实际 {collected_count}）：{wrong}"


def test_readme_test_file_count_matches_directory(readme):
    m = re.search(r"(\d+)\s*个测试文件", readme)
    assert m, "README 没写测试文件数"
    actual = len(list((CORE_DIR / "tests").glob("test_*.py")))
    assert int(m.group(1)) == actual, f"README 写 {m.group(1)} 个测试文件，实际 {actual}"


# README 混用三种相对基：仓库根（`core/tests/...`）、`core/`（`tests/...`、`scripts/...`）、
# `core/app/`（`api/auth.py`、`agents/runtime.py`）。按根单基解析会把后两种全判成失效，
# 所以三个基都试 —— 只要它在**任一**真实基下存在，这条引用就是有效的。
BASES = [PROJECT_ROOT, CORE_DIR, CORE_DIR / "app", PROJECT_ROOT / "ui"]

# ⚠️ **不要只扫反引号**：失效最久的那条（`scripts\test_food_accuracy.py`）是在
# **代码块**里，只扫反引号的话它根本进不了视野，守卫会恒真 —— 这个坑是变异检验
# 当场抓出来的（改成一个不存在的路径，守卫仍然绿）。
_PATH_RE = re.compile(r"[\w\-./\\]+\.(?:py|md|json|html|cmd|toml|csv|exe)")


def _referenced_paths(text: str) -> set[str]:
    """README 里所有像仓库内路径的串（Windows 反斜杠归一，`..\\` 按仓库根解）。"""
    out = set()
    for raw in _PATH_RE.findall(text):
        s = raw.replace("\\", "/")
        if "://" in s:
            continue
        while s.startswith("../"):
            s = s.removeprefix("../")
        s = s.removeprefix("./")
        if not s or s.startswith(("http", "-")):
            continue
        out.add(s)
    return out


# 裸文件名（`agent1_diet.py`、`auth.py`）在文档里大量出现，它们不带目录，
# 得在源码目录里递归找；`.venv` 要跳过（遍历它会非常慢）。
_SEARCH_ROOTS = (
    CORE_DIR / "app",
    CORE_DIR / "scripts",
    CORE_DIR / "tests",
    CORE_DIR / "data",
    PROJECT_ROOT / "ui",
    PROJECT_ROOT / "docs",
)


def _path_exists(rel: str) -> bool:
    if "/" in rel:
        return any((base / rel).exists() for base in BASES)
    for root in _SEARCH_ROOTS:
        for p in root.rglob(rel):
            if ".venv" not in p.parts:
                return True
    return (PROJECT_ROOT / rel).exists()


def test_readme_referenced_paths_exist(readme):
    missing = sorted(p for p in _referenced_paths(readme) if not _path_exists(p))
    assert not missing, f"README 引用了不存在的路径：{missing}"
