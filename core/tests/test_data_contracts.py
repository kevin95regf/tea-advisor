"""数据契约守卫：`docs/data-contracts.md` 声明的**形状常量**必须与数据实际一致。

范式（与项目其它守卫一致）：**派生比对**，不写快照 ——
断言**不写死**「147」，而是**从数据现算一个串、再去文档里找它**：
数据变了文档没跟上 ⇒ 红（这是本守卫存在的理由）；文档被改坏 ⇒ 红。

⚠️ 单一入口：所有输入都经 `_doc()` / `_data()` / `_sources()` / `_field_order()` /
`_prod_py_files()` 取 —— 变异检验要能在**内存里改副本**而不落盘。
"""
from __future__ import annotations

import ast
import json
import pathlib

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
CORE_DIR = PROJECT_ROOT / "core"
DATA_DIR = CORE_DIR / "data"
DOC = PROJECT_ROOT / "docs" / "data-contracts.md"

# herbs.json 每味在 `brewing` 之后允许出现的键（E2 插的 review 字段）
REVIEW_FIELDS = ("review_status", "reviewed_by", "reviewed_at", "review_note")


def _doc() -> str:
    return DOC.read_text(encoding="utf-8")


def _data(name: str) -> dict:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def _sources() -> dict:
    return json.loads((PROJECT_ROOT / "docs" / "food-properties-sources.json").read_text(encoding="utf-8"))


def _field_order() -> tuple[str, ...]:
    """`FIELD_ORDER` 定义在脚本里（不在数据、也不在 app 代码）—— 用 AST 取字面量，不执行脚本。"""
    tree = ast.parse((CORE_DIR / "scripts" / "patch_food_table.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == "FIELD_ORDER":
            return tuple(ast.literal_eval(node.value))
    raise AssertionError("patch_food_table.py 里找不到 FIELD_ORDER 赋值")


def _prod_py_files() -> list[pathlib.Path]:
    """生产侧 Python 文件（core/app + ui），用于「production 不读 rulings」这条。"""
    files = [p for p in (CORE_DIR / "app").rglob("*.py")]
    files += [p for p in (PROJECT_ROOT / "ui").rglob("*.py")]
    return [p for p in files if ".venv" not in p.parts]


# ---------------------------------------------------------------- 文档声明 ↔ 数据实际


def test_doc_declares_actual_herbs_version():
    version = _data("herbs.json")["_meta"]["version"]
    assert f"`_meta.version` 现 **{version}**" in _doc(), (
        f"data-contracts.md 没写对 herbs.json 的 _meta.version（实际 {version!r}）"
    )


def test_doc_declares_actual_food_counts():
    d = _data("food_properties.json")
    foods, items = len(d["foods"]), len(d["tea_drinks"]["items"])
    doc = _doc()
    assert f"`food_properties.json`＝{foods + items}：" in doc, f"总数应为 {foods + items}"
    assert f"`foods` **list({foods})**" in doc, f"foods 应为 list({foods})"
    assert f"items({items})" in doc, f"tea_drinks.items 应为 {items}"


def test_doc_declares_actual_field_order_length():
    n = len(_field_order())
    doc = _doc()
    assert f"`FIELD_ORDER`（**{n}** 个" in doc, f"FIELD_ORDER 实际 {n} 个"
    assert "`core/scripts/patch_food_table.py`" in doc, "应写明 FIELD_ORDER 定义在哪"


def test_brewing_is_last_business_field_for_every_herb():
    """44 味逐条：`brewing` 之后**恰为**那 4 个 review 字段（顺序也钉住）。

    ⚠️ 逐味断言，不是「跨味并集」—— 并集对「某味少一个键」是**盲的**
    （变异检验抓到过：删掉一味里的 `review_note`，并集不变 ⇒ 守卫不红）。
    """
    herbs = _data("herbs.json")["herbs"]
    for h in herbs:
        keys = list(h.keys())
        assert "brewing" in keys, f"{h['id']} 缺少 brewing"
        tail = tuple(keys[keys.index("brewing") + 1:])
        assert tail == REVIEW_FIELDS, (
            f"{h['id']} 的 brewing 之后应为 {REVIEW_FIELDS}，实际 {tail}"
        )
    assert len(herbs) >= 40, f"只测到 {len(herbs)} 味，样本可能被治理偷走"


def test_doc_lists_the_review_fields_the_data_actually_has():
    doc = _doc()
    herbs = _data("herbs.json")["herbs"]
    tail_keys = {k for h in herbs for k in list(h.keys())[list(h.keys()).index("brewing") + 1:]}
    assert tail_keys == set(REVIEW_FIELDS), f"数据里的尾部键与预期不符：{sorted(tail_keys)}"
    for f in REVIEW_FIELDS:
        assert f in doc, f"data-contracts.md 没列出 review 字段 {f!r}"


def test_doc_declares_actual_evidence_sources_shape():
    keys = sorted(_data("herb_evidence_sources.json").keys())
    assert keys == ["_meta", "constitution_entries", "property_entries"], keys
    assert "结构＝`{_meta, property_entries, constitution_entries}`" in _doc()


def test_catalog_shape_and_batches_carry_verbatim():
    d = _data("food_medicine_catalog.json")
    assert sorted(d.keys()) == ["_meta", "batches", "items"], sorted(d.keys())
    assert d["batches"], "batches 为空，说明样本被偷走"
    no_verbatim = [b.get("name") or i for i, b in enumerate(d["batches"]) if "verbatim" not in b]
    assert not no_verbatim, f"这些 batch 没有 verbatim：{no_verbatim}"
    assert "结构＝`{_meta, batches, items}`" in _doc()


def test_sources_controlled_vocab_exists_and_is_documented():
    d = _sources()
    assert "controlled_vocab" in d["_meta"], "登记表缺 _meta.controlled_vocab"
    assert "`_meta.controlled_vocab`" in _doc(), "文档应写明受控词表的真源在哪"


def test_doc_declares_actual_constitution_extension_keys():
    ce = _data("herbs.json")["_meta"]["constitution_extension"]
    assert {"rulings", "evidence_batch"} <= set(ce), sorted(ce)
    doc = _doc()
    assert f"**共 {len(ce)} 个**" in doc, f"constitution_extension 实际有 {len(ce)} 个键"
    assert "`rulings`" in doc and "`evidence_batch`" in doc


def test_rulings_is_not_read_by_production():
    """文档声明：`rulings`／`constitution_extension` 只有测试侧读，production 零命中。

    这条守的是**一句声明本身**（曾经写错过：旧笔记把它们说成 production 读的）。
    """
    offenders = [
        str(p.relative_to(PROJECT_ROOT))
        for p in _prod_py_files()
        if "constitution_extension" in p.read_text(encoding="utf-8")
        or "rulings" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"production 代码读了 rulings/constitution_extension：{offenders}"
