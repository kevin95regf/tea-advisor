"""三份「入口文档」里的事实性声明必须与仓库实际一致。

守的是 `README.md`（新接手者第一份）、`docs/handover.md`（全貌）、
`docs/new-workspace-onboarding.md`（当前状态）—— 它们的数字与路径**跨三份
重复出现**，只守一份等于没守：改了 README 忘 handover，数字就开始腐烂。

由来：2026-09-21 做文档同步时实测发现，`scripts\\test_food_accuracy.py` 这条
路径在仓库根下根本不存在（脚本全在 `core/scripts/`），静默失效了很久没人报；
`test_handover_docs.py` 只守 handover 的**结构**（章节、ID、决策编号），不守这类事实。

三条都是**派生**断言（从仓库现算，不写死数字）：
  1. 声明的测试项数 == 现场 `--collect-only` 收集到的条数；
  2. 声明的测试文件数 == `core/tests/test_*.py` 的实际个数（没写就不查）；
  3. 引用的仓库内路径必须存在。

豁免（EXEMPT_*）一律**显式 + 带理由**，并由下面两条元守卫盯着：文档里已经没有
那个数字/路径了，就说明豁免过期了，测试会红 —— 免得豁免自己变成新的静默角落。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

CORE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = CORE_DIR.parent
DOCS = PROJECT_ROOT / "docs"

GUARDED_DOCS = (
    "README.md",
    "docs/handover.md",
    "docs/new-workspace-onboarding.md",
)

# 只认「测试项数」语境里的数字，避免把「244 个配伍判定」这类无关数字抓进来。
# 每条都能追溯到一句真正在说测试规模的话。
_TEST_COUNT_PATTERNS = (
    r"pytest[^\n]{0,60}?(\d{3,4})\s*(?:项|passed)",  # 命令行语境
    r"(\d{3,4})\s*项(?:离线测试|，全离线)",  # 「758 项离线测试」
    r"\|\s*测试\s*\|\s*\**(\d{3,4})",  # 状态表里的「测试」行
    r"期望\s*\**(\d{3,4})\s*passed",  # onboarding 的期望值
)

# 历史留痕：这些数字在文档里**不是**本项目的声明。
EXEMPT_COUNTS: dict[str, dict[int, str]] = {
    "docs/handover.md": {
        230: "§9 在讲别处文档曾写「pytest 230 项」，是历史留痕，不是本项目的声明",
    },
}

# 指别的仓库 / 不是路径的串。
EXEMPT_PATHS: dict[str, dict[str, str]] = {
    "docs/new-workspace-onboarding.md": {
        "MANIFEST.md": "指 `tea-advisor-fork-keep` 那个**别的仓库**的清单，不在本仓库内",
    },
}

# 文档混用四种相对基：仓库根（`core/tests/...`）、`core/`（`tests/...`、`scripts/...`）、
# `core/app/`（`api/auth.py`）、`ui/`（`terminal/chat.py`）。按根单基解析会把后三种
# 全判成失效，所以四个基都试 —— 只要它在**任一**真实基下存在，这条引用就是有效的。
BASES = [PROJECT_ROOT, CORE_DIR, CORE_DIR / "app", PROJECT_ROOT / "ui"]

# ⚠️ **不要只扫反引号**：失效最久的那条（`scripts\test_food_accuracy.py`）是在
# **代码块**里，只扫反引号的话它根本进不了视野，守卫会恒真 —— 这个坑是变异检验
# 当场抓出来的（改成一个不存在的路径，守卫仍然绿）。
# ⚠️ 也不收 `.exe`：那会把 `pip.exe` / `uvicorn.exe` 这类**命令名**当成仓库路径。
_PATH_RE = re.compile(r"[\w\-./\\]+\.(?:py|md|json|html|cmd|toml|csv)")

# 裸文件名（`agent1_diet.py`、`auth.py`）在文档里大量出现，它们不带目录，得在源码
# 目录里递归找；`.venv` 要跳过（遍历它会非常慢）。
_SEARCH_ROOTS = (
    CORE_DIR / "app",
    CORE_DIR / "scripts",
    CORE_DIR / "tests",
    CORE_DIR / "data",
    PROJECT_ROOT / "ui",
    DOCS,
)


def _text(rel: str) -> str:
    """读被守的文档。抽成一层是为了**变异检验**：改副本时只需顶替这个函数，
    不用真的往磁盘上写（写磁盘再改回来那条路，失手就是真改动）。"""
    return (PROJECT_ROOT / rel).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def collected_count() -> int:
    """现跑一次收集数用例 —— 不断言「等于 758」，写死了下次加测试就红。"""
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


def _declared_test_counts(text: str) -> set[int]:
    out: set[int] = set()
    for pat in _TEST_COUNT_PATTERNS:
        out.update(int(m) for m in re.findall(pat, text))
    return out


@pytest.mark.parametrize("rel", GUARDED_DOCS)
def test_declared_test_count_matches_collection(rel, collected_count):
    text = _text(rel)
    declared = _declared_test_counts(text) - set(EXEMPT_COUNTS.get(rel, {}))
    assert declared, f"{rel} 里找不到任何测试项数声明（正则该改了，别让它静默失效）"
    wrong = sorted(n for n in declared if n != collected_count)
    assert not wrong, f"{rel} 写的测试项数与实收集不符（实际 {collected_count}）：{wrong}"


@pytest.mark.parametrize("rel", GUARDED_DOCS)
def test_declared_test_file_count_matches_directory(rel):
    """写了「N 个测试文件」的才查；没写的文档不要求它写。"""
    text = _text(rel)
    m = re.search(r"(\d+)\s*个测试文件", text)
    if not m:
        pytest.skip(f"{rel} 没写测试文件数")
    actual = len(list((CORE_DIR / "tests").glob("test_*.py")))
    assert int(m.group(1)) == actual, f"{rel} 写 {m.group(1)} 个测试文件，实际 {actual}"


def _referenced_paths(text: str) -> set[str]:
    """文档里所有像仓库内路径的串（Windows 反斜杠归一，`..\\` 按仓库根解）。"""
    out = set()
    for raw in _PATH_RE.findall(text):
        s = raw.replace("\\", "/")
        if "://" in s:
            continue
        while s.startswith("../"):
            s = s.removeprefix("../")
        s = s.removeprefix("./")
        if not s or s.startswith(("http", "-", "*", ".")):
            continue  # `*`：gitignore 的通配模式（`*.local.md`）；`.`：dotfile 模式
        out.add(s)
    return out


def _path_exists(rel: str) -> bool:
    if "/" in rel:
        return any((base / rel).exists() for base in BASES)
    if (PROJECT_ROOT / rel).exists() or (CORE_DIR / rel).exists():
        return True
    for root in _SEARCH_ROOTS:
        for p in root.rglob(rel):
            if ".venv" not in p.parts:
                return True
    return False


@pytest.mark.parametrize("rel", GUARDED_DOCS)
def test_referenced_paths_exist(rel):
    text = _text(rel)
    exempt = set(EXEMPT_PATHS.get(rel, {}))
    missing = sorted(p for p in _referenced_paths(text) - exempt if not _path_exists(p))
    assert not missing, f"{rel} 引用了不存在的路径：{missing}"


# ------------------------- 盯着豁免自己别腐烂 -------------------------


@pytest.mark.parametrize("rel", sorted(EXEMPT_COUNTS))
def test_count_exemptions_are_still_present(rel):
    """豁免的数字必须在文档里还找得到 —— 找不到说明豁免过期了（文档改了，豁免没清）。"""
    text = _text(rel)
    for num, reason in EXEMPT_COUNTS[rel].items():
        assert str(num) in text, f"{rel} 的豁免 {num}（{reason}）已经不在文档里了，删掉它"


@pytest.mark.parametrize("rel", sorted(EXEMPT_PATHS))
def test_path_exemptions_are_still_present(rel):
    text = _text(rel)
    for name, reason in EXEMPT_PATHS[rel].items():
        assert name in text, f"{rel} 的豁免 {name}（{reason}）已经不在文档里了，删掉它"
