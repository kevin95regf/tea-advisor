# 缺口 3 方案：饮片侧「逐味公开依据」链

> 来源：`D:\work\tea-advisor-main-assessment.md` §「本项目确认的 3 处缺口」的缺口 3；挂起项 `docs/pending-items.md` **E3**。
> 状态：**已执行（2026-09-18）—— §1–§8 是拍板前的方案与取证，§10 是执行结果（含与方案的 4 处偏差）。**
> 拍板记录（2026-09-18）：九型矩阵**只当来源层**（不吸收对方 `herbs.json`）；饮片侧来源登记表**建**；`Basis` 加 `references` 并接到终端与网页。

---

## 0　一个必须先更正的事实

评估报告（§「建议吸收」#3 与 §附问题 2）写「本项目目前**没有**对应 `food-properties-sources.json` 的饮片侧文件，需要先建」。

**这句不准确。** 本项目**已经有一张 34 味的逐味药典登记表** —— `core/data/herb_nature_reference.json`（commit `854c7ad`，**早于**本次评估），每味都带：

| 字段 | 内容（以茯苓为例） |
|---|---|
| `pharmacopoeia.xingwei_verbatim` | 药典原文「甘、淡，平。归心、肺、脾、肾经。」 |
| `pharmacopoeia.page` / `entry_id` / `url` | 页码 p.300、词条 id 374、在线链接 |
| `pharmacopoeia.nature_word` → `nature_mapped` | 药典档位 → 项目五档的降档 |
| `nature_match` / `flavors_match` / `meridians_match` / `status` | 逐项比对结果 |

覆盖：**33/34 有药典条目**，茉莉花 1 味药典未收载。

**但它不是来源登记表，它是「核对报告」** —— 三个差别：

1. `_meta.purpose` 明确写「**本文件不修改任何项目数据**」「只报告差异」，它是给复核人看的，不是给程序读的；
2. **没有 `_meta.source_registry`** —— 没有 tier / caveat / 强度排序那一套；
3. **引用的是 2020 版药典，而 2020 版已被 2025 版废止**（2025 年第 29 号公告，2025-10-01 施行），已记在 `docs/herbs-9types-draft.md` §0③。

⇒ **结论：缺口 3 的前置不是「从零建一张表」，而是「把既有的核对表提升为可被运行时读取的来源登记表，并把版本口径讲清楚」。** 这改变了工作量的量级，也改变了本次该聚焦的风险点。

---

## 1　现状取证（六条硬事实，全部已实测）

**事实 1 · `docs/*.json` 不被运行时读取。**
全仓 grep：`docs/food-properties-sources.json` 只被 `core/scripts/build_food_review_sheet.py` 读（审核脚本），**没有任何 `core/app/` 代码读它**。运行时只读 `core/data/`（`safety.py` 读 `herbs.json`、`food_lookup.py` 读 `food_properties.json`）。
⇒ 登记表若要让运行时用上，**必须落在 `core/data/`**。

**事实 2 · `matcher.build_basis` 是死代码。**
`core/app/services/matcher.py:326` 定义了它，但全仓 `grep -rn "build_basis" core/ ui/` **只有定义处一处，没有调用点**。`Basis` 的真实构造在 `core/app/services/orchestrator.py:176 / 237 / 297`。
⇒ **把 `references` 加在 `build_basis` 上等于没加。** 这正是分叉批次的形状陷阱 —— 对方把它接进了自己的链路，本项目这一份是废弃件。

**事实 3 · `Basis` 现在只有 4 个字段**（`core/app/domain/models.py:128`）：`constitution` / `constitution_label` / `rule_hits` / `guardrail_applied`。**无 `references`。**

**事实 4 · 两个壳都有现成渲染位点。**
终端 `ui/terminal/chat.py:147-163`（`render_footer`，已打印 体质 / 命中规则 / 护栏介入）；网页 `ui/web/index.html:405-410`（已打印体质 label）。

**事实 5 · 矩阵与本项目无硬冲突。**
逐格比对矩阵的 24 条「宜」claim × 本项目 `unsuitable_for`：**硬冲突 0 条**。cautions 侧的 5 处疑似全部指向**别的体质**（如生姜 宜阳虚，其 caution 说的是阴虚）—— 不矛盾。
矩阵点名的 **14 味全部在本项目白名单内**（`name` 精确匹配，0 缺失）。

**事实 6 · 矩阵列了 4 条来源，但只有 3 条真被用作依据。**

| source_id | publisher | `evidence[]` 引用次数 | 可访问性（实测） |
|---|---|---|---|
| `zibo-wjw-2021` | 淄博市卫生健康委员会 | 7 | **200** ✓ |
| `linyi-wjw-2017` | 临沂市卫生健康委员会 | 6 | **200** ✓ |
| `sac-2026` | 国家标准化管理委员会 | 2 | **200** ✓（需浏览器 UA；裸 curl 返回 403） |
| `nhc-food-medicine-2021` | 国家卫生健康委员会 | **0**（只列在 `_meta.sources`） | 412（反爬，未取得可访问确认） |

`nhc-food-medicine-2021` 是《药食同源目录管理规定》。按本项目既有铁律「**目录只给合规身份、不含四气**」，它**不得作体质适配依据**。好在矩阵也确实没拿它当 evidence，只在方法学里引用它定义白名单 —— 所以本次把它登记为**白名单来源**即可，不涉及剔除任何条目。

---

## 2　两个必须先拍板的问题

### 问题 1　登记表放哪儿？

| 选项 | 做法 | 评价 |
|---|---|---|
| **A（建议）** | 事实源放 **`core/data/herb_evidence_sources.json`**（运行时读）；人读登记表由脚本渲染成 `docs/herb-evidence-sources.md` | 与项目既有「JSON 是事实源 → md 是渲染产物」一致（`constitution-9-types.json`→`.md`、`herb_nature_reference.json`→`crosscheck.md`）；运行时读 `core/data/`，不越层 |
| B | 事实源放 `docs/herb-evidence-sources.json`，运行时读 `docs/` | **对齐了位置却没对齐理由** —— food 那张之所以在 `docs/`，恰恰因为它**不被运行时读**。B 会让 `core/app/` 依赖 `docs/`，破坏分层 |

**建议 A。** 你要求的「结构对齐 `food-properties-sources.json`」，对齐的是 `_meta.source_registry` + `entries[]` + `evidence[]` 这套**结构**，不是它的存放位置。

### 问题 2　矩阵的 24 格「只当来源层」写成什么形态？

| 选项 | 做法 | 代价 |
|---|---|---|
| **A（建议）** | 只进新登记表的 `constitution_evidence[]`：`{constitution, herb_id, source_id, quote, level:"evidence"}`，**不带 `field`、不写进 `herbs.json`** | **零。** 244 格账本不动、`filter_by_constitution` 候选顺序不动 |
| B | 同时写进 `herbs.json` 的 `_meta.constitution_extension.rulings.cells`，`field: "suitable_constitutions"` | ① 会**改变候选排序**（追加 `suitable` 会按下标插进 suitable 段，下标小的跃居首位 —— 山楂已在气郁首位）；② **语义混用**：`rulings` 块的成文职责是「软约束豁免登记」，装「来源支持」是两回事；③ 要逐格重算下标 |

**建议 A。** 依据：E3 要的是「**公开依据链**」（让人**看得到出处**），不是「新增判定」；你的拍板原话是「**只当来源层**」。B 的收益（多 24 格 `suitable_constitutions`）与代价（动账本 + 动排序 + 语义混用 + 要算下标）不成比例。

> 若日后要按矩阵**收敛候选池**，那是**另一个决定**（评估报告 §附问题 1「矩阵的定位」），应单独立项、单独算下标，不在本次范围内。

---

## 3　设计：两条来源域 + 一个汇合点

**核心判断：拆成两个来源域，各自独立登记、独立测试，最后在 `Basis.references` 汇合。**
理由：两者的触发条件、覆盖范围、诚实边界完全不同；混在一张表里必然漂移（一方补了数据、另一方忘了同步）。

```
推荐结果 cleaned
   └─ 本次实际用到的饮片名集合 {茯苓, 陈皮, ...}
        ├─[域 I]  属性依据：这味的四气五味归经从哪来   ← 药典 2020 一部（33/34）
        └─[域 II] 体质依据：为什么这味适合你的体质     ← 政府科普（14/34）
                      ↓  safety.herb_evidence(herb_names, constitution)
                  Basis.references: list[EvidenceReference]
                      ↓
              终端 render_footer  ／  网页 index.html
```

### 3.1　域 I · 属性依据

- **来源**：药典 2020 一部。**复用食物侧 `source_registry` 里已登记的 `chp2020` 同一个 id**，不新造。
- **登记表条目**（每条 = 一味）：

```json
{
  "id": "fuling",
  "name": "茯苓",
  "project": {"nature": "neutral", "nature_cn": "平",
              "flavors": ["sweet", "bland"], "meridians": ["心", "肺", "脾", "肾"]},
  "evidence": [{
    "source_id": "chp2020",
    "tier": "官方·药典",
    "matched_name": "茯苓",
    "how": "正名（药典收载名）",
    "locator": "《中国药典》2020 年版一部 p.300「茯苓」",
    "verbatim": "甘、淡，平。归心、肺、脾、肾经。",
    "url": "https://ydz.chp.org.cn/#/item?bookId=1&entryId=374"
  }],
  "status": "一致",
  "delta": null,
  "open_question": null
}
```

- **派生而非手抄**：由 `core/scripts/build_herb_sources.py` 从 `herb_nature_reference.json` **派生**（verbatim / page / entry_id / url / 降档全部来自它），保证两份不会漂移。
- **茉莉花**：药典未收载 → `evidence: []`、`status: "无源可引"`，`open_question` 写明「药典一部未收载；食用依据仅广西地方标准」。
- **7 处药典与项目不一致**（红枣归经缺「心」／荷叶多「淡」／桑椹·百合·淡竹叶 四气「凉」vs药典「寒」／白扁豆「平」vs「微温」／佛手缺「酸」「胃」）：**照 `open_items.discrepancies_keep_project_values` 的既有裁定保留项目值**。登记表**如实记 `verbatim` 与 `delta`，不借登记表偷偷改数据**。

### 3.2　域 II · 体质适配依据

- **来源**：3 条政府科普（`zibo-wjw-2021` / `linyi-wjw-2017` / `sac-2026`，**全部实测可达**）+ 项目既有的《粤中医》（广东省中医药局，`docs/herbs-9types-draft.md` §1 已登记，本次分配 id）。
- **条目数**：**24 条**（14 味 × 9 型的 evidence 映射）。
- **每条**：

```json
{
  "constitution": "yin_deficiency",
  "herb_id": "gouqizi",
  "herb_name": "枸杞子",
  "source_id": "zibo-wjw-2021",
  "matched_name": "枸杞",
  "how": "简称对应",
  "quote": "原文明确列举……",
  "level": "evidence",
  "review_status": "pending"
}
```

- **`nhc-food-medicine-2021` 只登记为白名单来源**，`tier: "官方·仅合规身份"`，并写明「**不作体质适配依据**」—— 与食物侧 `fm_catalog` 同一条铁律。
- **映射须逐条留痕**：矩阵用「红枣/枸杞」，项目用「大枣/枸杞子」，`matched_name` + `how` 照食物侧 `mapping_review` 的做法记。食物侧 A1 的教训是**映射是承重的** —— 否掉一条，该条目就落到「无源」。

### 3.3　汇合点 · `Basis.references`

- **新增 `models.EvidenceReference`**，形状借分叉批次：
  `id` / `title` / `publisher` / `url` / `supports: list[str]` / `note: str`
- **文档字符串必须逐字写清边界**（分叉批次这一点做得对，照抄）：
  > `supports` 只表示该来源明确提到了这些原料与当前方向，**不代表来源支持本程序生成的具体搭配、克数**。
- **新增 `safety.herb_evidence(herb_names, constitution) -> list[dict]`**：
  - 域 I：本次用到的味 → 药典条目（**一个来源支持多味时合并 `supports`**）
  - 域 II：本次用到的味 × 当前体质 → 命中的政府来源
  - 只返回**命中本次原料**的来源 —— 这是分叉批次最关键的设计：**不把体质级概述当成单味依据**。
- **`Basis` 加** `references: list[EvidenceReference] = Field(default_factory=list)`。
- **接线：改 `orchestrator.py` 三处构造点**（176 / 237 / 297），
  `herb_names = {h.name for rec in cleaned for h in rec.herbs}`。
- **`matcher.build_basis` 死代码**：建议**删除**，references 构造抽成 helper（如 `_build_references()`）。理由见 §8 待确认项 3。

### 3.4　壳展示

| 壳 | 位点 | 呈现 |
|---|---|---|
| 终端 | `ui/terminal/chat.py` → `render_footer` | 新增段 `公开依据（仅支持原料与调养方向）：`，逐条 `· 来源名《标题》｜支持：A、B｜URL` |
| 网页 | `ui/web/index.html` | 新增 `renderReferences(data.basis.references)` 卡片；**外链带 `rel="noopener noreferrer" target="_blank"`，所有文案一律走 `esc()`** |

### 3.5　护栏（**已拍板：加，独立提交**）

分叉批次在它的 `chat.py` 里有一句护栏：「程序会在回复下方结构化展示来源，**你不得虚构其他文献或链接**」。
本项目把这句话加进 `core/app/agents/prompts/agent2_system.md`（模型不该编文献）—— 它**会改提示词**，而 `agent2_system.md` 刚在缺口 1/2 里改过，故**独立一次提交**，回滚不影响主体（见 §9.5）。

---

## 4　文件清单

**新增（4）**

| 路径 | 说明 |
|---|---|
| `core/data/herb_evidence_sources.json` | 登记表事实源（域 I 34 条 + 域 II 24 条 + `_meta.source_registry`） |
| `core/scripts/build_herb_sources.py` | 只读工具：从 `herb_nature_reference.json` 派生域 I；默认只打印、`--out` 才落盘、`--check` 进 CI、渲染确定性 |
| `docs/herb-evidence-sources.md` | 人读登记表（由脚本渲染，**请勿手工编辑**） |
| `core/tests/test_herb_evidence.py` | 派生不变式 + 负控制 |

**改动（6）**

| 路径 | 改动 |
|---|---|
| `core/app/domain/models.py` | 新增 `EvidenceReference`；`Basis` 加 `references` |
| `core/app/domain/safety.py` | 新增 `load_herb_evidence_sources()` / `herb_evidence()` |
| `core/app/services/orchestrator.py` | 三处构造点接 `references` |
| `core/app/services/matcher.py` | 删掉死的 `build_basis`（references 构造抽 helper） |
| `ui/terminal/chat.py` | `render_footer` 打印公开依据 |
| `ui/web/index.html` | 新增 references 卡片 |

**文档同步**：`docs/pending-items.md` E3 状态改「已实施」+ 补「解决于」；`docs/maintenance.md` 数据文件表加一行；`docs/three-layer-architecture.md` 若涉 `Basis` 字段需同步。

> **`core/data/herbs.json` 本次不动** —— 这正是选项 A 的要点。`_meta.version` 保持 0.5.0。

---

## 5　测试方案（派生不变式 + 负控制）

**域 I 不变式**

1. 登记表 `id` 集合 **== `herbs.json` 的 `id` 集合**（34 味全覆盖、不多不少）
2. 每条 `project.{nature, flavors, meridians}` **== `herbs.json` 现值**（挡住手写漂移）
3. 每条 `evidence[0].verbatim` **能在 `herb_nature_reference.json` 里找到同串**（挡住编造）

**域 II 不变式**

4. 每条 `herb_id` ∈ `herbs.json` 的 id 集合（挡住挂在白名单外的味）
5. 每条 `source_id` ∈ `_meta.source_registry`（挡住悬空来源）
6. `(constitution, herb_id)` 不重复
7. `nhc-food-medicine-2021` **不得**出现在任何域 II 条目里（铁律守卫）

**端到端不变式**

8. **推荐里出现的每一味，`references` 里必须有对应条目** —— 这是分叉批次那条「逐位映射必须精确相等」的移植，**它挡的正是最难发现的错：「推荐了某味但引文里没有它」**。

**负控制（每条关键不变式配一个）**

- 造一条 `verbatim` 与参照文件不符的假条目 → 断言不变式 3 报错
- 造一条 `herb_id` 不在白名单的假条目 → 断言不变式 4 报错
- 造一条 `source_id` 悬空的假条目 → 断言不变式 5 报错
- 造一条推荐结果里带「甘草」、但登记表对应条目被删掉 → 断言不变式 8 报错

> 按项目成文纪律：**不写数据快照式断言**（`assert len(missing) == 3` 之类 —— 数据补齐后必红，且分不清「数据坏了」还是「活儿干完了」）；**只用派生不变式 + 负控制**，每条不变式都要有人造数据的负控制。

---

## 6　已知代价与覆盖缺口（如实）

| # | 事实 | 处理 |
|---|---|---|
| 1 | **体质依据只有 14/34 味** | 其余 20 味**只有属性依据**。界面必须如实，不能给用户「每味都有体质依据」的错觉 |
| 2 | **属性依据 33/34**（茉莉花无源） | 茉莉花 `status: 无源可引`；界面要么不展示依据、要么注明「药典未收载」 |
| 3 | **药典引用的是 2020 版，现行是 2025 版** | 必须写进 `note`；并**新登记一条挂起项**（等取得 2025 版在线全文再换）。跨版性味归经变动概率不高，但**这是未经核实的假设** |
| 4 | **7 处药典与项目不一致仍保留项目值** | 登记表如实记 `delta`，**不借登记表改数据**；等 nanple 复核（沿用既有 `open_items` 裁定） |
| 5 | 展示的是「来源支持原料与方向」，**不是**「来源支持本程序的搭配与克数」 | 这句必须进 `EvidenceReference` 文档字符串 **+ 界面脚注** |
| 6 | 登记项 `review_status: pending`（未人工审核） | 与 A1 食性表 147 条全 pending 的口径一致 —— **「收录」≠「已审核」** |

---

## 7　执行顺序（拍板后）

1. `build_herb_sources.py`：从 `herb_nature_reference.json` 派生域 I → `core/data/herb_evidence_sources.json`
2. 录入域 II 24 条（逐条带 `matched_name` / `how`）+ `_meta.source_registry`
3. 渲染 `docs/herb-evidence-sources.md`（确定性：无生成时间戳、`set` 排序输出）
4. `models.EvidenceReference` + `Basis.references`
5. `safety.herb_evidence()`
6. `orchestrator` 三处接线 + 删 `matcher.build_basis` 死代码
7. 两个壳渲染
8. `core/tests/test_herb_evidence.py`（8 条不变式 + 4 条负控制）
9. 全量 `pytest` + `scripts/smoke_offline.py` + `--check` 幂等复跑 → commit → push
10. 同步 `docs/pending-items.md` / `docs/maintenance.md`

---

## 8　逐条拍板结果（2026-09-18）

| # | 问题 | 拍板 |
|---|---|---|
| 1 | 登记表存放 | **`core/data/herb_evidence_sources.json` 当事实源 + `docs/herb-evidence-sources.md` 渲染产物**。对齐 food 的**结构**，不对齐位置 |
| 2 | 矩阵 24 格形态 | **只进登记表，不写 `herbs.json`**（三重代价不冒） |
| 3 | `matcher.build_basis` 死代码 | **删掉**；references 在 `orchestrator.py` 的**真实构造点**接（176/237/297）—— 强化做法见 §9.2-C |
| 4 | `agent2_system.md` 护栏 | **加，独立一次提交**（便于回滚） |
| 5 | 药典 2020 版口径 | **如实标版本 + 新登记一条挂起项**（等 2025 版在线全文） |
| 6 | 界面是否呈现「未审核」 | 建议见 §9.6，**待你点头**（与 §9.7 第 2 项并列） |

**另外接受两条**：第 8 条派生不变式（「推荐里的每一味在 references 里必须有对应」）守住可追溯；`nhc-food-medicine-2021` 只登记为白名单来源、永不作体质依据。

---

## 9　最终执行稿

### 9.1　数据文件：`core/data/herb_evidence_sources.json`（新增）

顶层三键：`_meta` / `property_entries[34]` / `constitution_entries[24]`。

**`_meta`**：

```json
{
  "title": "饮片侧来源登记表（属性依据 + 体质适配依据）",
  "version": "0.1.0",
  "compiled_at": "2026-09-18",
  "purpose": "登记 core/data/herbs.json 每味饮片的（一）四气五味归经依据、（二）体质适配依据，供 safety.herb_evidence() 生成 Basis.references。**本文件不修改 herbs.json。**",
  "why_this_file": "食物侧的对应物是 docs/food-properties-sources.json；那张之所以放 docs/ 是因为它不被运行时读。本表要被 safety.py 运行时读，故落 core/data/ —— 对齐结构，不对齐位置。",
  "scope": "只登记「来源明确点名」的组合，不做药典功效外推。",
  "hard_rules": [
    "域 I 只能引 chp2020；域 II 只能引 source_registry 里的政府来源。",
    "nhc-food-medicine-2021 只证明合规身份、不含四气与体质适配 —— 永不作体质依据。",
    "supports 只表示来源提到这些原料与方向，不代表来源支持本程序生成的具体搭配、克数。",
    "域 I 的 nature/flavors/meridians 必须与 herbs.json 现值一致；不一致处按既有裁定保留项目值，只记 delta。"
  ],
  "source_registry": { "...": "见下表" },
  "counts": {"property_total": 34, "property_with_source": 33, "constitution_total": 24, "distinct_herbs": 14}
}
```

**`source_registry`（6 条）**：

| id | label | tier | 用途 |
|---|---|---|---|
| `chp2020` | 《中华人民共和国药典》2020 年版一部 | 官方·药典 | **域 I 唯一来源** |
| `zibo-wjw-2021` | 淄博市卫生健康委员会《不同体质适合不同药膳》 | 政府网站科普 | 域 II |
| `linyi-wjw-2017` | 临沂市卫生健康委员会《解读〈中国公民中医养生保健素养〉⑩》 | 政府网站科普 | 域 II |
| `sac-2026` | 国家标准化管理委员会《中医体质分类国家标准四月一日起实施》 | 官方·政策解读 | 域 II |
| `gd-gov-2023` | 广东省中医药局《如何辨识自己的体质？九种体质调理方》2023-03-22 | 政府网站科普 | **暂未使用**（见 §9.7 第 2 项） |
| `nhc-food-medicine-2021` | 国家卫生健康委员会《按照传统既是食品又是中药材的物质目录管理规定》 | 官方·**仅合规身份** | **只作白名单来源，永不作体质依据** |

`chp2020` 的 `caveat` 必须含版本事实：「**版本为 2020 版，已被 2025 版废止（2025-10-01 施行）；2025 版在线全文尚未取得，跨版性味归经是否变动未经核实。**」

**`property_entries` 每条（34 条，脚本派生、不手写）**：

```json
{
  "id": "fuling",
  "name": "茯苓",
  "project": {"nature": "neutral", "nature_cn": "平",
              "flavors": ["sweet", "bland"], "flavors_cn": ["甘", "淡"],
              "meridians": ["心", "肺", "脾", "肾"]},
  "evidence": [{
    "source_id": "chp2020",
    "tier": "官方·药典",
    "matched_name": "茯苓",
    "how": "正名（药典收载名）",
    "locator": "《中国药典》2020 年版一部 p.300「茯苓」",
    "verbatim": "甘、淡，平。归心、肺、脾、肾经。",
    "url": "https://ydz.chp.org.cn/#/item?bookId=1&entryId=374"
  }],
  "status": "一致",
  "delta": null,
  "open_question": null
}
```

| 情形 | 条数 | 写法 |
|---|---|---|
| 一致 | 26 | `status: "一致"`、`delta: null` |
| 降档后一致但药典用更细档（山楂/菊花/麦冬/生姜/决明子/槐花/藿香/香薷/鱼腥草） | — | `status: "一致"`，`delta` 记「药典原文用更细档『微温』」 |
| **不一致**（红枣缺「心」/荷叶多「淡」/桑椹·百合·淡竹叶 凉vs寒/白扁豆 平vs微温/佛手缺「酸」「胃」） | 7 | `status: "不一致"`、`delta` 写清、`project` **照 herbs.json 现值**、`open_question` 指向既有裁定（保留项目值、等 nanple 复核） |
| 药典未收载（茉莉花） | 1 | `evidence: []`、`status: "无源可引"`、`open_question: "《中国药典》2020 年版一部未收载；食用依据仅广西地方标准。"` |

**`constitution_entries` 每条（24 条，人工录入）**：

```json
{
  "constitution": "yin_deficiency",
  "herb_id": "gouqizi",
  "herb_name": "枸杞子",
  "source_id": "zibo-wjw-2021",
  "matched_name": "枸杞",
  "how": "简称对应",
  "quote": "原文明确列举……",
  "level": "evidence",
  "review_status": "pending"
}
```

⚠️ **不带 `field` 键** —— 带了就成了判定登记，会与 `rulings` 语义混用（§2 问题 2）。

### 9.2　代码改动

**A · `core/app/domain/models.py`** —— 新增 `EvidenceReference`（置于 `Basis` 之前）+ `Basis.references`：

```python
class EvidenceReference(BaseModel):
    """公开依据。

    ``supports`` 只表示该来源明确提到了这些原料与当前方向，
    **不代表来源支持本程序生成的具体搭配、克数或个体化使用**。
    """

    id: str
    title: str
    publisher: str
    url: str
    supports: list[str] = Field(default_factory=list)
    note: str = ""


class Basis(BaseModel):
    ...
    references: list[EvidenceReference] = Field(
        default_factory=list,
        description="本次实际推荐原料对应的公开依据",
    )
```

> **已实测确认无碰撞**：`grep -rn "basis" core/tests/` 的命中全是表格列名 / 函数名（`cook_required_without_basis`、`basis` 列），**没有任何测试断言 `Basis` 的字段集或响应键的精确集合** → 加字段不会撞现有断言。

**B · `core/app/domain/safety.py`** —— 新增两函数，复用 `load_herb_catalog` 那套 `@lru_cache(maxsize=1)` + 「文件不存在返回空、不抛异常」的写法：

```python
@lru_cache(maxsize=1)
def load_herb_evidence_sources() -> dict: ...


def herb_evidence(herb_names: set[str], constitution: str | None = None) -> list[dict]:
    """本次实际用到的饮片 → 公开依据，按 source_id 聚合。

    只返回**命中本次原料**的来源；体质的概述性来源不算作单味的依据。
    """
```

聚合规则照分叉批次：同一 `source_id` 命中多味时**合并成一条**，`supports` 去重累加；条目自己的 `note` 用 `；` 拼接。

**C · `core/app/services/orchestrator.py`** —— **抽一个「活的」统一入口，三处都走它**：

```python
def _build_basis(
    constitution: Constitution,
    label: str,
    *,
    recs: list[Recommendation] | None = None,
    rule_hits: list[str] | None = None,
    guardrail_applied: list[str] | None = None,
) -> Basis:
    """Basis 的唯一构造点。

    统一入口让「新增一处 Basis(...) 却忘了 references」在结构上不可能发生 ——
    matcher.build_basis 之所以危险，正因为它是一份**没人调用**的同名实现。
    """
    names = {h.name for rec in (recs or []) for h in rec.herbs}
    return Basis(
        constitution=constitution,
        constitution_label=label,
        rule_hits=rule_hits or [],
        guardrail_applied=guardrail_applied or [],
        references=herb_evidence(names, constitution.value) if names else [],
    )
```

| 原构造点 | 改成 | references |
|---|---|---|
| `:176` 高风险分支 | `_build_basis(constitution, label, guardrail_applied=[...])` | 天然为空（无推荐） |
| `:237` 未识别出食物 | `_build_basis(constitution, label)` | 天然为空 |
| `:297` 正常路径 | `_build_basis(constitution, label, recs=cleaned, rule_hits=rule_hits, guardrail_applied=applied)` | **真正携带依据** |

> 为什么不是「只在 297 加一行」：三处各写一遍 `references=` 的话，将来多出第四处构造点就会静默漏掉。走统一入口后**「真实构造点」与「唯一构造点」合一**，并由 §9.4 的源码守卫钉住。
> 注意 176/237 **不需要**写 `references=[]` —— 传了也是空，反而制造「这里也要管」的错觉。

**D · `core/app/services/matcher.py`** —— 删掉 `build_basis`（`:326-337`，12 行死代码）。

**E · 两条源码守卫**（落在新测试文件里，挡住复发）：
1. `orchestrator.py` 里 `Basis(` 只出现 **1** 次（必须落在 `_build_basis` 内）
2. `core/app/` 全文不再出现 `def build_basis`

### 9.3　壳展示

| 壳 | 确切插入点 | 呈现 |
|---|---|---|
| 终端 | `ui/terminal/chat.py` → `render_footer`，在 `:160` 的 `guardrail_applied` 之后、`:162` 的 disclaimer 之前 | 段标题 `公开依据（仅支持原料与调养方向）：`；逐条 `  · {publisher}《{title}》｜支持：{supports}｜{url}`；`note` 非空时缩进一行 |
| 网页 | `ui/web/index.html` → `:404` 的 `renderRecs(...)` 之后插 `html += renderReferences(data.basis && data.basis.references);`；函数定义放 `renderKeySource`（`:425`）之后 | 卡片标题「这次推荐的公开依据」；`supports` 与 `note` 一律走 `esc()`；外链 `rel="noopener noreferrer" target="_blank"`；卡片底部脚注「来源支持原料与调养方向，不代表支持具体搭配、克数」 |

### 9.4　测试清单（`core/tests/test_herb_evidence.py`，新增）

> 本节是 §5 的**最终版**（补了源码守卫 14 与负控制 19），编号即测试。

**登记表结构 / 派生不变式**

1. `property_entries` 的 `id` 集合 **==** `herbs.json` 的 `id` 集合（34 味全覆盖、不多不少）
2. 每条 `property_entries[i].project.{nature, flavors, meridians}` **==** `herbs.json` 现值
3. 每条有来源的 `evidence[0].verbatim` **能在** `herb_nature_reference.json` 里找到同串
4. 每条 `constitution_entries[i].herb_id` ∈ `herbs.json` 的 `id` 集合
5. 每条 `constitution_entries[i].source_id` ∈ `_meta.source_registry`
6. `(constitution, herb_id)` 不重复
7. `nhc-food-medicine-2021` **不出现**在任何 `constitution_entries` 里
8. `constitution_entries` 里**没有任何 `field` 键**（来源与判定分离的守卫）

**行为**

9. `herb_evidence({"茯苓"}, "balanced")` → 含 `chp2020` 那条，`supports == ["茯苓"]`
10. `herb_evidence({"茯苓"}, "balanced")` → **不含**任何域 II 条目（茯苓不在矩阵 14 味里）
11. 多味同源**按 `source_id` 合并**：`herb_evidence({"山药", "红枣"}, "qi_deficiency")` 里 `sac-2026` / `linyi-wjw-2017` 各只出现 1 条，`supports` 含两味
12. 空输入 → `[]`
13. **端到端**：照 `test_key_handling.stub_agents` 的形状（`monkeypatch.setattr(orchestrator, "parse_diet" / "agent2_recommend", ...)` + `orchestrator.analyze(...)`），桩返回含矩阵内饮片的推荐 → `resp.basis.references` 必须覆盖到本次推荐的**每一味**
14. 源码守卫：`orchestrator.py` 的 `Basis(` 计数 == 1；`core/app/` 无 `def build_basis`

**负控制（人造数据，断言检查真的会报）**

15. 造 `verbatim` 与参照文件不符的假条目 → 断言不变式 3 报错
16. 造 `herb_id` 不在白名单的假条目 → 断言不变式 4 报错
17. 造 `source_id` 悬空的假条目 → 断言不变式 5 报错
18. 造「推荐结果带甘草、但把甘草的 references 删掉」 → 断言不变式 13 报错
19. 造一条带 `field` 键的假条目 → 断言不变式 8 报错

### 9.5　提交切分（两次）

| 提交 | 内容 | 为什么分开 |
|---|---|---|
| **① 主体** | 登记表 + `build_herb_sources.py` + `docs/herb-evidence-sources.md` + `models.py` + `safety.py` + `orchestrator.py` + `matcher.py` + 两个壳 + `test_herb_evidence.py` + `pending-items.md` / `maintenance.md` | 一个可独立回滚的功能单元 |
| **② 护栏** | `core/app/agents/prompts/agent2_system.md` 加「你不得虚构其他文献或链接」 | 按拍板独立提交，回滚不影响主体 |

**顺序：① 在前、② 在后。** 理由：护栏文案说的是「程序会在回复下方结构化展示来源」—— **这句话在 ① 落地前并不成立**（程序还不展示来源）。先①后②，每个 commit 各自自洽。

（这细化了 §7 的第 9 步。）

### 9.6　第 6 项（界面是否呈现未审核状态）—— 最终建议

**建议：`review_status` 不进界面，但脚注必须写。**

- `review_status: "pending"` 是**审核流程**的状态，不是**来源可信度**的状态 —— 药典那条是官方标准，标「未审核」会让用户误以为依据不可靠。
- 数据侧照旧记 `"pending"`（与 A1 食性表 147 条全 pending 的口径一致），只是不渲染到界面。
- 两个壳都写脚注：「来源支持原料与调养方向，**不代表支持具体搭配、克数**」。
- 界面**不出现**任何古籍引文（来源里没有），也不出现 `url` 以外的链接。

### 9.7　两项待点头（**均已拍板接受，2026-09-18**）

1. **§9.6** 的取舍（`review_status` 不进界面 + 脚注文案）→ **接受**。
2. **域 II 的范围**：第一版**只登记矩阵的 24 条**。项目自有的 10 格（`herbs.json` 的 `constitution_extension`，来源 = 广东省中医药局）**暂不纳入** —— 其中 9 格是「忌 / 慎用」（负面 claim；而 references 回答的是「为什么**推荐**」，不是「为什么避开」），只有 **山楂 × 气郁 1 格**是正向。
   登记表**结构已预留**，日后要补只需加条目、不改代码。→ **接受**。

---

## 10　执行结果（2026-09-18）

**两次提交**：① 主体（登记表 + 脚本 + `models`/`safety`/`orchestrator`/`matcher` + 两个壳 + 测试 + 文档同步）
→ ② 护栏（`agent2_system.md` 加「不得虚构文献」）。顺序不可反：护栏文案说的是「程序会在回复下方结构化展示来源」，
**这句话在 ① 落地前并不成立**。

**结果**：`pytest` **428 passed**（新增 31 项）；`smoke_offline` 全通过；
`build_herb_sources.py --check` 幂等通过；`git status` 干净、无敏感文件。

### 10.1　落地物

| 角色 | 路径 | 事实源？ |
|---|---|---|
| 登记表事实源 | `core/data/herb_evidence_sources.json` | **是**（域 I 派生 / 域 II 人工录入）|
| 人读登记表 | `docs/herb-evidence-sources.md` | 否（脚本渲染，勿手改）|
| 派生 / 校验工具 | `core/scripts/build_herb_sources.py` | —（只读，`--write` 才落盘）|
| 测试 | `core/tests/test_herb_evidence.py` | —（31 项：不变式 + 负控制）|

`source_registry` 6 条：`chp2020`（域 I 唯一来源）、`zibo-wjw-2021`、`linyi-wjw-2017`、
`sac-2026`（域 II 实际使用）、`gd-gov-2023`（登记在册、**暂未使用**）、
`nhc-food-medicine-2021`（**只证明合规身份，永不作体质依据**）。

### 10.2　与方案的 4 处偏差（都在执行中被证据推翻，逐条说明）

1. **不变式 6 的判据从「二元组」改成「三元组」。**
   方案 §5/§9.4 原写「`(constitution, herb_id)` 不重复」。真实数据**不成立**：
   矩阵本身就让同一 (体质, 饮片) 挂在**两条不同来源**下（气虚质 × 山药／红枣 同时有
   国家标准委与临沂卫健委两条），而**同一来源在同一格**只出现一次。
   按原判据写测试会在第一次运行就红，且它把「两条独立来源互证」这个**优点**当成缺陷。
   已改为 `(体质, 饮片, 来源)` 唯一，并另加一条测试把「多来源互证」钉成正向行为。
2. **`source_registry` 的 `label` 拆成 `publisher` + `title`。**
   `EvidenceReference` 需要 `publisher` 与 `title` 两个独立字段（终端与网页都按
   `{publisher}《{title}》` 渲染）。保留 `label` 会与它们重复，两处必然漂移，故删掉 `label`。
3. **源码守卫用 AST 而不是 grep。**
   方案只说「`orchestrator.py` 里 `Basis(` 只出现 1 次」。但 `_build_basis` 的文档字符串里
   为了解释这个坑，自身就写了 `Basis(...)` 这个例子 —— 朴素计数会数成 2。
   改用 `ast` 数**真实调用点**（并另配负控制：合成一份含 2 处调用的源码，断言数出 2）。
   同一个道理，「`core/app/` 不许再有 `def build_basis`」也走 AST。
4. **新增 `--check` 的等价测试。**
   方案把幂等列在「执行顺序」第 9 步（手动跑一次）。已提升为测试
   （`test_disk_content_equals_fresh_derivation`）：手工改 JSON **或**改那份 Markdown
   都会让 `pytest` 变红，等于把 `--check` 接进 CI。

### 10.3　如实代价（与 §6 一致，落地后无变化）

- **属性依据 33/34 味**：茉莉花药典一部未收载，`status = 无源可引`，`evidence: []`。
- **体质依据 14/34 味**：其余 20 味只有属性依据。
- **引用的是药典 2020 版**（已被 2025 版废止）→ 已登记挂起项 **C3**，并在
  `chp2020.caveat` 与 `EvidenceReference.note` 里如实标注。
- **7 处药典与项目不一致仍保留项目值**：只记 `delta`，**不借登记表改数据**（等 nanple，B1）。
- **`review_status: pending` 不进界面**；两个壳都写脚注「来源支持原料与调养方向，
  不代表支持具体搭配、克数」。

### 10.4　执行中新发现、**本次不改数据**的一条

逐字抓取政府来源时发现：临沂页把**白扁豆**列入特禀质「应少食」
（原文「应少食辛辣食物、腥膻发物以及含致敏物质的食物，如荞麦、蚕豆、白扁豆、牛肉、咖啡等」），
而 `herbs.json` 里白扁豆的 `unsuitable_for` 为空、`cautions` 也没提这条。
同一页把**乌梅**列入血瘀质忌食，这一条项目数据**已经**对上了（`unsuitable_for` 含 `blood_stasis`）。

前一条属「数据该不该改」的决定，按项目纪律**不在本项范围内**，已写进登记表的
`_meta.known_limitations`，留待所有者判断。
