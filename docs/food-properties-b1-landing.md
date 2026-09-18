# B1 · 茶饮 11 条落盘方案（待确认后动代码/数据）

> 日期：2026-09-18　上游：
> `docs/food-properties-b1-tea.md`（核实记录）、`docs/food-properties-remaining-plan.md`（100 条分层）
> **拍板已定**：① 认继承（甲），但**显式留痕推翻语料定性**；② 茉莉花茶降 ③、值不动；
> ③ 菊花／大枣纲目分歧按 `layer ① + open_question` 记、不动值。
> 状态：**已执行**（2026-09-18，4 个提交）。执行中相对本方案的两处偏离
> （留痕日期写法、`matched_name` 取 herbs.json 饮片名）记在
> `docs/food-properties-b1-tea.md` §5 第 8 条与 §8。

---

## 0. 结论先行

| 问题 | 结论 |
|---|---|
| 动数据吗 | **不动** `core/data/food_properties.json`（值、note、flavors 一律不动） |
| 动什么 | `docs/food-properties-sources.json`：**+11 条 entries** + 词表登记 + 2 处元信息计数 |
| 会连带重生成 | `docs/food-properties-review-sheet.md`（脚本产物，**禁止手工编辑**） |
| 新增文件 | 落盘脚本（一次性，放 `core/var/`）、新增守卫测试 1 组 |
| 11 条怎么分 | **10 条 layer ①**（A 档 4 + B 档 6）、**茉莉花茶 layer ③** |
| 全部标 | `batch = 后续`（**不标「第一批」**，理由见 §6.1） |

---

## 1. 落盘范围（动 / 不动）

### 动（4 处）

| 文件 | 改动 |
|---|---|
| `docs/food-properties-sources.json` | 新增 11 条 entries；`_meta.controlled_vocab.how` 加取值；`_meta.counts` 更新；`_meta.mapping_review.outcome` 更新 |
| `docs/food-properties-review-sheet.md` | **脚本重新生成**（不由我手编） |
| `core/tests/test_food_review_sheet.py` | 新增 2 条守卫（§7） |
| `docs/food-properties-b1-tea.md` | §6「两项待拍板」改为已拍板，并指向本文 |

### 不动（明确边界）

1. `core/data/food_properties.json` —— 值 / note / flavors 一律不改（本批次「动数据？否」）
2. `core/data/herbs.json`、`herb_nature_reference.json` —— 只读，作为**依据来源**被引用
3. `core/data/*.json` 其余文件
4. 茶饮的 `review_status` 仍为 `pending` —— **登记来源 ≠ 已审核**，`approved` 只能由人给

---

## 2. 逐条取值（11 条完整，可直接照抄）

`category` 一律 **`茶饮`**（新增取值；现有 47 条是蔬菜/水果/肉类…，无茶饮）。
`nature_cn` 按现有惯例取项目四气对应中文：`cool→凉`、`warm→温`、`neutral→平`。
`project.flavors` **必须等于数据现值**（否则触发「来源登记漂移·矛盾」）。

### A 档 4 条（S1 有原料条目 + 药典一致）→ `layer ①`

| id | name | nature | flavors | 基准（药典正条名） | 药典 locator | 药典原文 | 辅证 S1 |
|---|---|---|---|---|---|---|---|
| `juhua_cha` | 菊花茶 | cool 凉 | sweet,bitter | 菊花 | p.372（entryId 490） | 甘、苦，微寒。归肺、肝经。 | 行 400「辛、甘、苦，微寒。归肺、肝经。」 |
| `jiangcha` | 姜茶 | warm 温 | pungent | 生姜 | p.153（entryId 148） | 辛，微温。归肺、脾、胃经。 | 行 336「辛，温。入脾、胃、肺经。」 |
| `hongzao_cha` | 红枣茶 | warm 温 | sweet | **大枣**（药典正条名；herbs.json 作「红枣」） | p.72（entryId 30） | 甘，温。归脾、胃、心经。 | 行 1187「甘，温。入脾、胃经。」 |
| `luohanguo_cha` | 罗汉果茶 | cool 凉 | sweet | 罗汉果 | p.270（entryId 328） | 甘，凉。归肺、大肠经。 | 行 1013「甘，凉，无毒。入肺、脾经。」 |

- `evidence`：**两条**（`chp2020` + `s1_dietetics`），`reference` 对齐 **`chp2020`**
  （沿用 `jiang`／`longyan`／`shanzha_guo` 的既有做法：官方优先）
- `reference.qi_word` = 药典词（`微寒`／`微温`／`温`／`凉`），映射值与项目值**全等**

### B 档 6 条（S1 无原料条目，唯一依据＝药典）→ `layer ①`

| id | name | nature | flavors | 基准 | 药典 locator | 药典原文 | 味差异 |
|---|---|---|---|---|---|---|---|
| `gouqi_cha` | 枸杞茶 | neutral 平 | sweet | 枸杞子 | p.309（390） | 甘，平。归肝、肾经。 | — |
| `meigui_cha` | 玫瑰花茶 | warm 温 | sweet,bitter | 玫瑰花 | p.258（308） | 甘、微苦，温。归肝、脾经。 | — |
| `chenpi_cha` | 陈皮茶 | warm 温 | pungent,bitter | 陈皮 | p.248（293） | 苦、辛，温。归肺、脾经。 | — |
| `juemingzi_cha` | 决明子茶 | cool 凉 | sweet,bitter | 决明子 | p.200（223） | 甘、苦、咸，微寒。归肝、大肠经。 | **缺咸** |
| `heye_cha` | 荷叶茶 | neutral 平 | bitter,bland | 荷叶 | p.336（434） | 苦，平。归肝、脾、胃经。 | **多淡** |
| `wumei_cha` | 乌梅茶 | neutral 平 | sour,astringent | 乌梅 | p.130（114） | 酸、涩，平。归肝、脾、肺、大肠经。 | — |

- `evidence`：**一条**（`chp2020`），`reference` = 该条
- ⚠️ 味差异**不否定**映射（冲泡制品的辛散/咸味不显性变化属正常），但写进 `open_question` 留痕

### 茉莉花茶 1 条 → `layer ③`

| id | name | nature | flavors | evidence | reference | status |
|---|---|---|---|---|---|---|
| `molihua_cha` | 茉莉花茶 | warm 温 | sweet,pungent | `[]`（无源可引） | `null` | **无源可引（基准三处无据）** |

- `nature_match: null`、`delta: null`（与 `qingcai` 同型）
- `mapping_review.accepted: false` ⇒ 必须 `layer=③`（`mapping_layer_gaps` 硬规则，§6.6）

### 11 条共用字段

| 字段 | 取值 |
|---|---|
| `batch` | `后续` |
| `how` | **制品·原料继承**（新取值，须先登记词表） |
| `tier` | A/B 档的 `chp2020` → `官方·药典`；A 档的 `s1_dietetics` → `通行·教材` |
| `alias_from` | `null` |
| `reviewed_by` / `reviewed_at` | `null`（未审核） |
| `mapping_review.by` / `.at` | `项目所有者` / `2026-09-18` |
| `mapping_review.group` | **E 组·制品·原料继承**（A/B/C/D 组已用） |

---

## 3. 三条留痕文案（这是本批次的核心，不是套话）

### 3.1　推翻语料定性的留痕（A/B 档 10 条共用开头）

> ⚠️ **本条显式推翻 50 号文件的既有定性**：
> 该文件 §5.2（行 478）明令「凡『茶』『糖』『汁』『粉』类后缀…**不可默认继承原料的四气**」，
> 行 396 更把「菊花茶」直接判为 **C 档（无据）**。
> 本项目选择**认继承**，依据是：18 条茶饮里的这 11 条，其值与 `herbs.json` 同名原料
> **11/11 完全相等**（脚本逐条比对，非目测），不可能是巧合。
> **推翻动作按项目所有者 2026-09-18 裁定在此留痕**，不是「没看到那条规则」。

### 3.2　A 档补一句（有 S1 原文）

> 原料在《中医饮食营养学》有独立条目（行 N，原文已引），故本条**不只是药典孤证**。

### 3.3　B 档补一句（只有药典）

> 原料在《中医饮食营养学》**无独立条目**，唯一依据是药典（**药品**标准）。
> `_meta.source_registry.chp2020.caveat` 自述「用途不同」⇒ **不得写成来源确凿**，
> 是否 `approved` 由审核人判断。

### 3.4　茉莉花茶 reason（映射成立但基准无据）

> 映射「茉莉花茶 → 茉莉花」**本身成立**（确为茉莉花所制），问题在**基准三处无据**：
> ① 药典 2020 **未收载**（已登记为 `herb_nature_reference.json` 的
> `open_items.jasmine_not_in_pharmacopoeia`）；②《中医饮食营养学》**零命中**；
> ③《本草纲目》行 10187「茉莉」只有【释名】【主治】、**无【气味】**
> （行 10194「热，有毒」是**根**不是花）。
> ⇒ 映射不能承重，落 ③。**值 `warm` 保留**：③ 层不是数据错，只是**不宣称有来源**。

### 3.5　`open_question`（菊花／大枣记纲目分歧，B 档记强度）

- **菊花茶**：「纲目行 10732 记『苦，平，无毒』，与 S1:400／药典（微寒）**方向相反**。
  纲目属通行·经典档，低于教材与药典 ⇒ `layer` 仍记 ①、**值不动**（沿用第一批「冲突不动值」口径）。」
- **红枣茶**：「纲目行 24156 记『甘，平，无毒』，与 S1:1187／药典（温）**方向相反**。处置同菊花茶。」
- **B 档 6 条**：「唯一依据是药典（**药品**标准）；原料在《中医饮食营养学》无独立条目。
  **不得据此宣称来源确凿**。」
- **决明子茶** 追加：「味不全等：项目 [sweet, bitter]，药典『甘、苦、咸』（缺咸）。」
- **荷叶茶** 追加：「味不全等：项目 [bitter, bland]，药典『苦』（多淡）。」

---

## 4. 词表与元信息的同步（3 处，缺一即红）

### 4.1　`_meta.controlled_vocab.how`

新增取值 **`制品·原料继承`**，并在 `语义` 里写明：

> 「项目条目是**制品**（冲泡/加工品），依据条目是它的**原料**；四气沿用原料。
> ⚠️ 这是**继承关系，不是同名**——50 号文件 §5.2 明令『不可默认继承』，
> 故每条都必须显式留痕（推翻理由见该条 `mapping_review.reason`）。」

同时在 `history` 追加一行：2026-09-18 新增，用于 B1 茶饮 11 条。

### 4.2　`_meta.mapping_review.outcome`（**有守卫**）

`test_outcome_counts_match_actual` 要求三态计数**等于实算**。11 条全部登记 `mapping_review`：

| 键 | 现值 | 新值 | 变化 |
|---|---|---|---|
| `accepted` | 17 | **27** | +10（A 档 4 + B 档 6） |
| `rejected` | 1 | **2** | +1（茉莉花茶） |
| `pending` | 0 | 0 | — |

并在 `scope` 追加：B1 茶饮 11 条（2026-09-18 登记，E 组·制品·原料继承）。

### 4.3　`_meta.counts`（无守卫，但文件须自洽）

| 键 | 现值 | 新值 |
|---|---|---|
| `后续\|一致` | 8 | **18**（+10） |
| `后续\|无源可引（基准三处无据）` | — | **1**（新增键） |
| `total` | 47 | **58** |

---

## 5. 落盘方式（脚本生成，不手抄）

已实测：`json.dumps(d, ensure_ascii=False, indent=2)` 与磁盘内容**只差末尾一个 `\n`**
⇒ 可以安全脚本回写（补 `+"\n"` 即可），不会像 `herbs.json` 那样炸成假 diff。

一次性脚本放 `core/var/`，步骤：

1. 读 `sources.json` → 加词表取值 → 追加 11 条 entries → 重算 `outcome` 与 `counts`
2. `json.dump(..., indent=2, ensure_ascii=False)` + 末尾 `\n`，`newline="\n"` 写盘
3. **复用 `core/var/` 的幂等纪律**：判据用「新串」——`ids 已含 11 条则跳过`
4. 跑 `build_food_review_sheet.py --out ../docs/food-properties-review-sheet.md` 重生成核验单
5. 跑全量 pytest

---

## 6. 技术约束（上一版 7 条 + 本轮新核出 4 条）

1. **`how` 新取值必须先登记词表** —— 否则 `test_how_values_are_in_controlled_vocab` 红。
2. **`tier` 必须用词表现有值**，且能映射到 `source_registry`（`官方·药典`→chp2020、`通行·教材`→s1_dietetics ✓）。
3. **`layer` ∈ ①②③④**（`test_sources_layers_are_known`）。
4. **`project.nature`/`project.flavors` 必须等于数据现值** —— 否则报「来源登记漂移」等级**矛盾**。
5. **`id` 必须存在于数据表** —— 茶饮 id 已被 `load_foods()` 纳入（`_group=tea_drinks`）✓。
6. **落盘后必须重生成核验单** —— 否则 `test_sheet_is_up_to_date` 红；产物不得含时间戳。
7. **不动 `food_properties.json`** —— 本批次只登记来源。
8. 🆕 **`batch` 标「后续」不标「第一批」** —— 标「第一批」会进 §4.1 与 §4.2 清单，
   并触发 `test_first_batch_conflicts_have_note`（第一批 ② 层必须有 note）。
   ⇒ 11 条只在 **§4.4** 出现（茉莉花茶另进 **§4.3**）。
9. 🆕 **`mapping_layer_gaps` 硬规则**：`accepted=false` ⇒ `layer` 必须是 ③。
   茉莉花茶 `accepted=false` + `layer=③` ✓。（若写成 `accepted=true` + `layer=③` 不违规，
   但 §4.4 会显示「✅ 采纳」而 §4.3 显示「无源可引」，自相矛盾 ⇒ **不选**。）
10. 🆕 **`outcome` 三态计数必须等于实算**（§4.2）—— 登记 11 条就得同步，否则红。
11. 🆕 **`ref_of()` 对 `reference=null` 返回 `{}`**，§4.4 渲染 `matched_name` 会显示「—」、
    `evidence_how` 返回「—」⇒ 茉莉花茶 `evidence=[]` / `reference=null` **不会崩渲染**（已读码确认）。

---

## 7. 新增守卫测试（2 条，把「继承链」钉死）

加在 `core/tests/test_food_review_sheet.py`：

**① `test_product_inheritance_points_at_a_real_herb`**（派生不变式）
凡 `how == "制品·原料继承"` 的依据，其 `matched_name` 必须在 `herbs.json` 中有同名饮片，
**且该饮片四气 == 条目 `project.nature`**。
⇒ 防「标了继承、继承的却是不存在的原料」或「继承值与原料不符」。
这是**真正缺的一条**：将来有人把「水果茶」「奶盖茶」也标成制品·原料继承，会被立刻拦下。

**② 负控制**：合成一条 `matched_name="no_such_herb"` 的依据，必须被①抓出；
再合成一条四气不等的（如原料 warm、项目 cool），也必须被抓出。

（layer/映射自洽已有 `mapping_layer_gaps` 覆盖，不重复造。）

---

## 8. 提交切分（每步跑 pytest）

| # | 内容 | 文件 |
|---|---|---|
| 1 | 词表登记 + 11 条 entries + 2 处元信息计数 | `docs/food-properties-sources.json` |
| 2 | 重生成核验单 | `docs/food-properties-review-sheet.md` |
| 3 | 新增守卫 2 条 | `core/tests/test_food_review_sheet.py` |
| 4 | 文档（核实记录改「已拍板」+ 指向本文） | `docs/food-properties-b1-tea.md` |

---

## 9. 验收判据

1. **既有 476 条一条都不改期望**（新增 2 条 ⇒ 478 passed）
2. `pytest -q` 全绿；`build_food_review_sheet.py --check` 返回 0
3. `git diff --stat core/data/` **为空**（数据表一字未动）
4. 核验单 §4.3 出现 `molihua_cha`；§4.4 多出 11 行；§1 的「来源登记表条目数」变 **58**、
   「全部登记条目分层」变 ①**47** ②**9** ③**2**
5. 变异检验：把某条茶饮 `matched_name` 改成不存在的原料 ⇒ 新守卫必须红

---

## 10. 落盘后仍挂着的问题（不属本批次）

1. **B1 只覆盖 11 条**。茶饮共 18 条，余 7 条（普洱/绿茶/红茶/乌龙/大麦茶/水果茶/奶盖茶）
   语料里**确实无据**（50 号文件行 396 把它们与菊花茶并列判 C 档）⇒ 不在本批次，
   按 L3「纯粹无据」留在剩余 100 条里。
2. **A1 仍是唯一硬阻碍**：147 条全部 `pending`，本批次不动 `review_status`。
3. **`E4`**（LLM 硬排除 vs 离线 caution）挂起未动——与本批次无关，记在此处避免遗忘。
