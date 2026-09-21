# 数据契约 —— `core/data/*.json` 与 `docs/food-properties-sources.json`

> 本文件回答的问题是：**这些数据文件长什么样、有哪些派生纪律、改的时候会踩什么坑。**
> 它跟着数据同仓演进 —— **改了数据就顺手改它**；描述失真比没有描述更危险。
>
> ⚠️ 运行时真正的**真源是 JSON 本身**。本文件只描述**形状与纪律**，不复制具体数值；
> 数值以文件为准（需要计数请现算，别抄这里）。

## `core/data/food_properties.json`

- `food_properties.json`＝147：`foods` **list(129)**、`tea_drinks` **{_note, items(18)}** ——
  **嵌套≠同构**，查重必须先 flatten，否则会漏掉整个茶饮段。
- ⚠️ **`ENTRY_FIXES` 是强制写入** ⇒ 改食物数据必须同步它（否则下次跑补丁脚本会把手改的内容覆盖回去）。
- 字段集合＝`FIELD_ORDER`（14 个）；`nature` 只 5 值存英文。

## `core/data/herbs.json`

- **内联数组**格式 ⇒ 只能**文本级精确替换**（`json.load` → `dumps` 回写会把格式炸开、产生数千字符假 diff）。
  精确替换的 old 串必须带**唯一上下文锚定**（同一段 JSON 片段常出现多次）。
- `_meta.version` 现 **0.8.0**。
- **`brewing` 是每味最后一个业务字段**；E2 之后插入 4 个 review 字段（**无 `reviewed` 布尔**）。
  `CatalogHerb(**item)` 会**忽略多余字段**。
- **收录≠已审核**；**`docs/*.json` 不被运行时读**。

## `core/data/herb_evidence_sources.json`

- 结构＝`{_meta, property_entries, constitution_entries}`。
- **域 I 自动派生、域 II 与 `_meta` 人工**（脚本只重算 `counts`）⇒
  **域 II 只收「政府来源点名」组合，教材级不进** ⇒ **写 `suitable_constitutions` 不动域 II**。
- ⚠️ 手改 `_meta` 后**必须再跑 `--write`**（改前一次、改后一次，再 `--check`）。

## `core/data/herb_nature_reference.json`

- 性质＝**饮片 vs 药典 2020 的核对报告非来源表**。
- `_meta.title` **派生**（`TITLE_TEMPLATE` ＋ `validate()` 守护）；`compiled_at` **一派生一手改**
  （crosscheck `--refresh` 改、sources 手改）。
- ⚠️ 改完脚本**先 `--refresh` 再 pytest**。
- md 里 **`†` ＝走降档约定**（`NATURE_MAP`：微寒→凉、微温→温）。

## `core/data/food_medicine_catalog.json`

- 结构＝`{_meta, batches, items}`。
- **`batches[].verbatim` 只存名单串、不存「使用限定」句**（限定句另有出处，见 `pending-items.md` 相关项）。

## `_meta.constitution_extension`（在 `herbs.json` 内）

- ＝ `rulings`（软约束豁免，`load_rulings()` 读）＋ `evidence_batch`（批次留痕，**不被读**）。
- 配套只读工具的行为：默认不写、`--out` 落盘、`--strict` exit 1。

## `docs/food-properties-sources.json`（登记表）

- 往 `docs/food-properties-sources.json` 加条目有 7 条「会静默出错」纪律 ⇒ **照既有条目抄格式**
  （`project.*` 等数据现值、日期写中文、`locator` 含 URL）。

## 两条通用纪律

- ⚠️ **批脚本会往数据里写文案**：`core/var/stage3_apply.py` 的 `vis_tail`／`open_questions`／`scope`／
  `CATALOG_ANNOUNCEMENT` 会被**逐字写进 `herbs.json`** ⇒ 「文案即数据」，改脚本前先看它会写什么。
- ⚠️ **口径陈述不写死数字**（如「库内 N 味寒凉一律标阳虚不宜」）—— N 每批都变 ⇒ 必过期。
