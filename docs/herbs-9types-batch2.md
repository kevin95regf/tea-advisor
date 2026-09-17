# 批次二记录：5 格「待确认」配伍判定（**已写入 `herbs.json`**）+ 豁免登记出口

> 状态：**2026-09-17 已执行**。
> 方案留档：`docs/herbs-9types-batch2-confirm.md`（**已执行**）
> 上游：`docs/pending-items.md` B3 原「需要什么」栏单列的 5 处
> 判定来源：项目所有者转达的**外部专业意见**，`level` 沿用 `docs/herbs-9types-draft.md` §2 的口径
> 影响面：`core/data/herbs.json` 34 味中的 **4 味**（香薷、荷叶、山楂、槐花）；`version` `0.3.0` → `0.4.0`

## 执行结果（2026-09-17，**先读这一节**）

**5 格已写入**，其中 4 格改变了条目数据、1 格只登记：

| # | 格子 | 判定 | `level` | 落到哪个字段 |
|---|---|---|---|---|
| 1 | 香薷 `xiangru` × 阴虚 | **忌** | `evidence` | `unsuitable_for` += `yin_deficiency`（**硬屏蔽**）；另补 `cautions`「阴虚有热者禁用」 |
| 2 | 荷叶 `heye` × 阴虚 | 慎用 | `inference` | `cautions` 追加（软通道，**登记豁免**） |
| 3 | 山楂 `shanzha` × 阴虚 | 慎用 | `inference` | `cautions` 追加（软通道，**登记豁免**） |
| 4 | 山楂 `shanzha` × 气郁 | 宜（倾向） | `inference` | `suitable_constitutions` += `qi_stagnation`（**升位**，见下） |
| 5 | 槐花 `huaihua` × 血瘀 | 慎用（低置信） | `inference` | `cautions` 追加（**不触发**既有守卫，无需登记） |

新条款一律**追加在 `cautions` 末尾**，不挤掉原有的硬安全提示（荷叶的「气血偏虚」、山楂的「胃酸过多」仍在首位）。

**运行时影响（实测，不是推断）**：

| | 改动前 | 改动后 |
|---|---|---|
| 阴虚候选**池** | 24 味 | **23 味**（香薷移出） |
| 阴虚默认返回（`limit=12`） | — | **前 12 条不变**（香薷 catalog 下标 32，本就在截断线外） |
| 气郁 `suitable` | 红枣、薄荷 | **山楂**、红枣、薄荷 |
| 气郁候选池 | 33 味 | 33 味（不变） |
| 血瘀 | 山楂/红枣/生姜 | 不变 |
| `ready_constitutions()` / `GET /api/constitutions` | 9 型 | 9 型（不变） |

⚠️ **阴虚只看 top12 看不出这次改动**（香薷排在第 32 位）—— 与 cautions 批次同样的陷阱，
验收必须用大 `limit` 取全池。这也正是配套测试用 `limit=999` 的原因。

`pytest` **382 → 384 passed**（改写 1 条守卫 + 新增 2 条）。`food_properties.json` 未改动。

---

## 0. 这批是什么、不是什么

**是什么**：把**外部专业意见**给出的 5 格判定落到数据上。3 格是「慎用」类软提示（写 `cautions`），
1 格是「明确忌」（写 `unsuitable_for`，硬屏蔽），1 格是「宜（倾向）」（写 `suitable_constitutions`）。

**不是什么**：**写入 ≠ 审核通过**。5 格全部 `review_status: pending`，界面照旧标「待验证」，
与其余数据同等对待。**不新增任何 `review_*` 字段**（那是挂起项 E2 的决定）。

**与 cautions 批次（`docs/herbs-cautions-yinxu-batch.md`）的区别**：

| | cautions 批次 | 本批（批次二） |
|---|---|---|
| 依据来源 | 项目**自有** `cautions` 措辞 | **外部专业意见** |
| 等级 | `inference`（项目数据推导） | 1 格 `evidence` + 4 格 `inference` |
| 写哪 | 一律 `unsuitable_for`（硬屏蔽） | 依据等级决定：`evidence` → 硬屏蔽；`inference` → 允许软通道 |
| 格数 | 10 | 5 |

---

## 1. 豁免登记出口（**本次新落地的机制**）

### 1.1 它解决什么问题

既有守卫 `test_cautions_naming_yinxu_must_be_blocked` 是一条**派生不变式**：
凡 `cautions` 命中阴虚方向 5 词（`阴虚`/`津液`/`口干`/`上火`/`内热`）的饮片，
**必须**在 `yin_deficiency` 的 `unsuitable_for` 里。

而本次裁决是「荷叶/山楂 × 阴虚 = **慎用**，只写 `cautions`」——两者正面冲突。
该守卫的 docstring 里其实早就写了第二条出口（「或在 docs 里说明为何不写」），但**代码里没实现**。
本次把它落成代码。

### 1.2 登记表放在哪

`herbs.json` 的 `_meta.constitution_extension.rulings.cells`，与 `cautions_batch` 同级。
**不新造条目字段**（把空间留给挂起项 E2）。

命名刻意用中性的 `rulings`（而非 `nanple_batch`）：它记的是「**人对格子的裁定**」，
可累积多批、也可能来自另一位审阅者，不必把测试的读取路径钉死在一个人名上。

`cells` 是**唯一事实源**：测试的豁免名单就是从它里面筛出来的（`field != "unsuitable_for"`），
不另存第二份名单 —— 两处名单必然漂移，而漂移的方向总是「测试放过、数据漏了」。

### 1.3 三条强制规则（都在代码里）

判定逻辑抽成纯函数 `_cautions_soft_gap(catalog, cells)`（`core/tests/test_safety.py`），
**正向测试与负控制共用同一份逻辑** —— 否则负控制只是把判定又写了一遍，属假保证。

| 规则 | 内容 | 挡住的场景 |
|---|---|---|
| ① | 豁免项必须 ∈ 命中集（`stray`） | 登记表被当成绕过检查的**后门** |
| ② | 命中集里**未登记**的仍必须硬屏蔽（`escaped`） | 防线被放松 |
| ③ | **走软通道的登记项，等级不得为 `evidence`**（`soft_evidence`） | 「明确忌」被写成软提示 |

规则③ 的准确含义是「**依据等级决定写哪个字段**」：`evidence`（明确忌）只能落 `unsuitable_for`。
香薷就是这条的活例 —— 它是 `evidence`，所以它落在硬屏蔽上，**想改走软通道会被挡回来**。

配套测试：

| 测试 | 守什么 |
|---|---|
| `test_cautions_naming_yinxu_must_be_blocked` | 改写版：三类缺口（`stray`/`soft_evidence`/`escaped`）必须同时为零；首条断言防测试静默失效 |
| `test_cautions_soft_gap_negative_controls` | **负控制**：三例人造数据必须让三类缺口各自报出来 |
| `test_rulings_cells_are_well_formed` | 规则③ 推广到**所有格子**；顺带把「登记表必须非空」并入 |

⚠️ **一处与确认稿伪码的偏差（落地时发现并修正）**：确认稿 §2.2 的 `soft_evidence` 写成
「所有 `yin_deficiency` 格子中 `level == evidence` 的」，直接算会把**香薷**（`evidence` 但正确落在
`unsuitable_for` 上）判成违规，**必然误报**。落地时收窄为「**只算走软通道的**登记项」

（`field != "unsuitable_for"`）—— 否则本条测试在真实数据上永远是红的。

⚠️ 「登记表非空」**不写成「恰好 2 条」**：那会随批次失效，属数据快照。

### 1.4 红线没有放松

| 担心的场景 | 结果 |
|---|---|
| 想把某味饮片偷偷从这个体质候选集里放出来 | 得先写一条 `rulings` 记录；填 `evidence` 被规则③挡，填 `inference` 必须在 `verdict`/`basis` 里留理由 —— **留痕**，且与 `priority_review` 同级可见 |
| 往 `cautions` 里加词来试探 | 规则② 会报出未登记项，**强制**做一次显式决定 |
| 把登记表当垃圾桶（反正写进去就不报错） | 规则① 挡住：只有真命中关键词的格子才允许登记 |

---

## 2. `cautions` 出口的更正（**顺带修掉的事实错误**）

`docs/herbs-cautions-yinxu-batch.md` §0 与 `herbs.json` 的 `_meta...cautions_batch.why` 都写着
**「`cautions` 只进 Agent2 的提示词」**。**代码里不是这样**，真实出口有两处：

1. `matcher.py` 兜底路径的 `Recommendation.cautions` —— **只取每味第 1 条**；
2. `safety.check_blend` 把每条 caution 转成 warning → `Basis.guardrail_applied`（**进 API 响应**）。

两处都比 `unsuitable_for` 软，**方向性结论不变**，但影响面比原文描述的大 ——
原文会让后来者低估 `cautions` 的影响面。两处已一并更正。

连带一个**已知代价**（可接受）：按「追加末尾」的裁决，新条款在兜底路径下**看不到**
（那里只取第 1 条）；且「（推断，未经人工审核）」这类内部审核语汇会出现在 `guardrail_applied` 里
→ **用户可见**。这与 A1「界面标待验证」的口径一致。

---

## 3. 山楂 × 气郁：升位过强（**请优先复核**）

按裁决**先按现状写入**，但把疑虑写进了数据：`_meta.constitution_extension.rulings.priority_review`。

- **现象**：`filter_by_constitution` 的排序是「`suitable`（按 catalog 顺序）+ 中性兜底」。
  山楂的 catalog 下标是 **2**，早于红枣（6）、薄荷（12），因此写入后**跃居气郁候选第 1 位**，
  直接进 Agent2 提示词首行。
- **问题**：本格是 `inference` 级的「**倾向**」判定，不宜带有「升位」这种强效果。
- **备选**（已记在数据里）：改走 `cautions`（降为注意项，不升位）／撤回该格／维持现状。
- **方向张力（不是冲突）**：`constitution.json` 的 `qi_stagnation` 写「少食**酸涩收敛**」、
  `avoid` 列「石榴、乌梅、柿子」，`direction` 点名的宜用是「橙子、白萝卜、薄荷」——**未点名山楂**。
  附带决定 B 的备注正是解释这处偏离：**「酸涩收敛忌气郁」的说法缺乏文献依据，暂不采纳**。

---

## 4. 写入方式

- **文本级精确替换**（按 id 定位块 + 只重写目标行），不用 `json.load` + `json.dumps` 整体回写 ——
  `herbs.json` 是**内联数组**风格，整体序列化会炸出上千行假 diff（前几轮踩过）。
- 验收：`git diff --numstat core/data/herbs.json` = **36 增 / 10 删**（4 条条目 + `_meta`），无其它行被动。
  其中数据行 6 增 6 删，其余为 `_meta`（新增 `rulings` 块）。
- 逐条替换前断言**每个锚点在全文中恰好出现 1 次**；替换后**先 `json.load` 校验再落盘**
  （上一批踩过「替换 `note` 行时把闭合大括号一起替掉」的坑）。
- 未动 `review_*`、未改 `nature/flavors/meridians`、未碰 `food_properties.json`。

---

## 5. 连带同步的既有记录

| 文件 | 改了什么 |
|---|---|
| `herbs.json` | `version` `0.3.0`→`0.4.0`；新增 `rulings`；`cautions_batch` 的 `excluded`/`excluded_reason` 两条过期字段作废，改为一行 `excluded_resolved` 指针（保住审计线索，不抹历史）；`why` 的出口表述更正 |
| `docs/herbs-cautions-yinxu-batch.md` | §0 出口表述更正；执行结果段补「后来了」；§2 标题与「已登记」段改为「已裁决」；§3.2 补第二条出口已落成代码；「非空洞」一节的命中数与负控制描述更新 |
| `docs/herbs-9types-draft.md` | 表头「草稿，未入库」→「草稿 → 已部分落地」（原文已过期）；宜/忌表补香薷/山楂；「没写入的部分」段改写；§4 主表 4 格符号与依据；汇总表 4 行；§6.2/§6.4 补「已裁定」；文末 |
| `docs/pending-items.md` | B3 概览行、现状、需要什么、附注四处；快照行与 B3 标题的格数（244 → 已落地 15 / 余 239） |
| `docs/constitution-9-types.md` | §四型「仍未完成」段（3 处待确认 → 5 处已裁定） |
| `docs/handover.md` | 决策 24 与「只等 nanple」两处的格数 |
| `docs/maintenance.md` | 第 7 项未决事项的格数 |
| `docs/herbs-9types-batch2-confirm.md` | 标题与状态改为「已执行」；§8 四项从「待点头」改为「已执行/已采纳」 |

> 其中 `constitution-9-types.md` / `handover.md` / `maintenance.md` 三处**超出确认稿 §5 的清单**
> —— 它们都写着「244 格仍待 nanple」「另有 3 处待确认已单列」，本批落地后会变成**过期描述**，
> 故一并同步。若希望这三处回退，改回即可（改动只在格数与「已裁定」的一句）。

---

## 6. 本文件未做的事

- **未**把余下 239 格填上 —— 那需要懂中医的人逐条判定。
- **未**新增任何 `review_*` 字段（属挂起项 E2）。
- **未**改 `food_properties.json`、`constitution.json`、`constitution-9-types.json`、
  `herb_nature_reference.json`（四气/五味/归经均未动 → `build_herb_crosscheck.py` 无需 refresh），
  `catalog-compliance.md` 也无需重跑（饮片名未动）。
- **未**调整「界面标待验证」的口径 —— 5 格与其余数据同等对待。
