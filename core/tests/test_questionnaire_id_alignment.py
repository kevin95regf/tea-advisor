"""问卷子包与 `core/` 体质标识的一致性守卫（pending-items B2 · 方案①）。

B2 的问题只有一句话：问卷子包用 `phlegm_dampness`，`core/` 用 `phlegm_damp`，
两边对同一个痰湿质给出不同的标识串。方案①是**问卷侧改名**（本仓已执行，
见 `docs/b2-constitution-id-alignment.md`），`core/` 一个字未动。

改名本身是 8 处字符串替换，但它有一个特点：**改完了不会有任何既有测试变红** ——
`core/` 根本不 import 这个子包（它要靠 `sys.path` 塞路径才能引），
所以「改回旧拼写」和「新增一个拼错的 scale」都是**静默**的。本文件补的就是这个洞。

写法沿用本项目的「**派生不变式 + 负控制**」范式：
每条检查都是纯函数（入参 `str`），判据**从 `Constitution` 枚举派生**而不是抄一份快照
—— 这样将来扩到十型时，测试会自动指出问卷侧没跟上，而不是静默放行。
用 AST 而不是 `import`，理由见 `docs/b2-constitution-id-alignment.md` §5.2。
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.domain.enums import Constitution

CORE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = CORE_DIR.parent
PKG = PROJECT_ROOT / "tcm-constitution-questionnaire"
QUESTIONS_PY = PKG / "tcm_constitution" / "questions.py"
CSV_PATH = PKG / "questionnaire.csv"
TEST_SCORING_PY = PKG / "tests" / "test_scoring.py"

# 方案① 要消灭的旧拼写。它必须**只**出现在历史叙述里，不出现在任何代码/数据中。
LEGACY = "phlegm_dampness"

# 判据来自枚举本身，不是快照
VALID: list[str] = [c.value for c in Constitution]
VALID_SET: set[str] = set(VALID)


def _read(path: Path) -> str:
    # 文件缺失时报错、不跳过：skip 会造成「样本被治理偷走」式的静默失效
    # （路径一旦算错就永远跳过，还显示通过）。
    assert path.is_file(), f"缺少 {path}"
    return path.read_text(encoding="utf-8")


def _bad_keys(keys: list[str]) -> list[str]:
    """派生不变式：每个键都必须是 `Constitution` 的合法值。"""
    return [k for k in dict.fromkeys(keys) if k not in VALID_SET]


def _missing_keys(keys: list[str]) -> list[str]:
    """反向不变式：枚举里有的体质，问卷侧一个都不能少。"""
    return [k for k in VALID if k not in set(keys)]


# ---------------------------------------------------------------- 守卫 1


def _csv_scale_keys(csv_text: str) -> list[str]:
    """`questionnaire.csv` 第一列（分量表键），跳过表头。"""
    rows = [ln for ln in csv_text.splitlines() if ln.strip()]
    if len(rows) < 2:
        raise AssertionError("questionnaire.csv 连表头带数据都不足两行")
    return [ln.split(",")[0].strip() for ln in rows[1:]]


def test_g1_csv_scale_keys_are_valid_and_complete():
    keys = _csv_scale_keys(_read(CSV_PATH))
    assert _bad_keys(keys) == [], f"问卷 CSV 出现非法体质键：{_bad_keys(keys)}"
    assert _missing_keys(keys) == [], f"问卷 CSV 缺少体质：{_missing_keys(keys)}"


def test_g1_negative_control_legacy_spelling_is_caught():
    """负控：把旧拼写塞回 CSV，检查必须报出来（否则 G1 根本没在判）。"""
    bad_csv = (
        "scale,scale_zh,item_no,question_id,question,reverse_scored,sex\n"
        f"{LEGACY},痰湿质,1,q12,您感到身体沉重不轻松或不爽快吗？,false,all\n"
        "damp_heat,湿热质,1,q15,您面部或鼻部有油腻感吗？,false,all\n"
    )
    keys = _csv_scale_keys(bad_csv)
    assert _bad_keys(keys) == [LEGACY]
    assert _missing_keys(keys) == [k for k in VALID if k != "damp_heat"]


# ---------------------------------------------------------------- 守卫 2


def _const_names_keys(src: str) -> list[str]:
    """AST 解析 `CONSTITUTION_NAMES` 字典字面量的键（保留顺序）。"""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id != "CONSTITUTION_NAMES":
                continue
            value = node.value
            if isinstance(value, ast.Dict):
                return [
                    k.value
                    for k in value.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)
                ]
    raise AssertionError("questions.py 里找不到 CONSTITUTION_NAMES 字典字面量")


def test_g2_const_names_match_enum_exactly():
    src = _read(QUESTIONS_PY)
    assert _const_names_keys(src) == VALID, (
        f"CONSTITUTION_NAMES 与 Constitution 枚举不一致："
        f"{_const_names_keys(src)} vs {VALID}"
    )


def test_g2_negative_control_legacy_spelling_is_caught():
    """负控：键改回旧拼写后，必须既判不等、也被 _bad_keys 抓出。"""
    src = _read(QUESTIONS_PY).replace('"phlegm_damp"', f'"{LEGACY}"', 1)
    keys = _const_names_keys(src)
    assert keys != VALID, "负控失效：旧拼写竟然仍被判为与枚举一致"
    assert _bad_keys(keys) == [LEGACY], _bad_keys(keys)


# ---------------------------------------------------------------- 守卫 3


def _scale_use_scales(src: str) -> list[str]:
    """AST 解析所有 `ScaleUse("...")` 的第一个实参。"""
    tree = ast.parse(src)
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id != "ScaleUse" or not node.args:
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                out.append(arg.value)
    return out


def test_g3_scale_uses_are_valid():
    src = _read(QUESTIONS_PY)
    uses = _scale_use_scales(src)
    assert uses, "没解析到任何 ScaleUse(...) —— 多半是 questions.py 结构变了"
    assert _bad_keys(uses) == [], f"ScaleUse 出现非法体质键：{_bad_keys(uses)}"


def test_g3_negative_control_legacy_spelling_is_caught():
    """负控：合成一段含旧拼写 ScaleUse 的源码，必须被判非法。"""
    bad_src = 'ScaleUse("' + LEGACY + '")\n'
    assert _scale_use_scales(bad_src) == [LEGACY]
    assert _bad_keys(_scale_use_scales(bad_src)) == [LEGACY]


# ---------------------------------------------------------------- 守卫 4


def _legacy_hits(text: str) -> list[str]:
    return [LEGACY] if LEGACY in text else []


def test_g4_no_legacy_spelling_in_package():
    for path in (QUESTIONS_PY, CSV_PATH, TEST_SCORING_PY):
        assert _legacy_hits(_read(path)) == [], (
            f"{path.name} 里仍有旧拼写 {LEGACY}（B2 方案① 已改名）"
        )


def test_g4_negative_control_legacy_spelling_is_caught():
    """负控：检查函数对含旧拼写的文本必须报命中。"""
    assert _legacy_hits(f'    "{LEGACY}": "痰湿质",') == [LEGACY]
    assert _legacy_hits('    "phlegm_damp": "痰湿质",') == []
