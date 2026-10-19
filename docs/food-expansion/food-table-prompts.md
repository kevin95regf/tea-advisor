# tea-advisor 食材表改造：发给 WorkBuddy 的分步 prompt

用法：每一步开一个任务。先贴【通用背景】，再贴该步任务。一步做完、测试通过、你看过 diff 之后，再进行下一步。
把下面这些文件放进仓库（建议 `docs/food-expansion/`），方便它读取：
- `review_response.md`
- `split/food_properties.classification_only_147.json`
- `split/food_properties.json`
- `split/food_classification.sidecar.json`
- `split/food_tcm_evidence.sidecar.json`
- `new_foods.csv`、`pending_foods.csv`（可选）

---

## 【通用背景】（每次新对话都贴；同一对话里只贴第一次）

```
你在 tea-advisor 仓库工作。Python + FastAPI + Pydantic。食材寒热表是 core/data/food_properties.json，供 Agent1 / food_lookup 查表；药材推荐只来自 herbs.json，两者互不读取。

我们要对食材表做改造，设计与影响分析在 docs/food-expansion/review_response.md，拆分后的运行时/侧车文件在 docs/food-expansion/split/。动手前先读这些文件和相关源码（food_lookup、diet_signals、data contracts、相关测试）。

硬性规则：
1. 不要改 herbs.json 的推荐逻辑；食物表条目永远不能进入推荐候选。
2. 原有 15 个字段的含义与取值，未经明确授权不得改动（第 1 步尤其禁止改 nature / flavors）。
3. 运行时不要加载 tcm_evidence；证据放 sidecar 或并入现有 docs/food-properties-sources.json。
4. 保留字段 category（信号计算依赖它）；新增分类用 food_group_code（WS/T 464）和 dg2022_layer（膳食指南 2022 宝塔层）。
5. 分类标准：存储用 WS/T 464-2015，展示用膳食宝塔五层 +「宝塔外」；不要用 GB 2760。
6. 每步只做本步要求的事；完成后列出改动文件、跑全部测试并报告结果。
```

---

## 第 1 步：只合分类（147 条，不动寒热）

```
任务：仅做「分类-only」合并，不新增食材、不改四气五味。

1. 以 docs/food-expansion/split/food_properties.classification_only_147.json 为源，更新 core/data/food_properties.json：
   - 原有 147 条、原 15 字段的值与顺序必须与当前仓库文件逐字节一致（可用脚本校验）。
   - 每条只额外增加（若数据规范允许）：food_group_code、dg2022_layer。
2. 更新数据规范 docs（如 data-contracts / FIELD_ORDER）：
   - 二选一并在 PR 说明里写清：A) 运行时字段改为 17 个；B) 运行时仍 15 个，分类只进 sidecar，运行时不读。
   - 若选 B：用 split 里的 classification sidecar，运行时 loader 不加载它。
3. dg2022_layer 必须用 review_response 里更正后的宝塔归属（杂豆→第1层与全谷物；奶类→第4层；菌藻算蔬菜）。
4. 不要改 nature、flavors、aliases、keywords、category。
5. 跑全量测试；预期应与改前相同（除了你主动改规范/文档导致的测试）。把 46 条「归类有歧义」的列表从 review_response / README 整理进 docs，方便营养学审核。

验收：147 条未增删；寒热未变；全量测试不因寒热/条目数变化而挂。
```

---

## 第 2 步：寒热核验材料就位（不改运行时属性）

```
任务：把四气/五味核验材料整理成可交给中医师审核的包，不修改运行时 food_properties 里任何 nature/flavors。

1. 将 docs/food-expansion/split/food_tcm_evidence.sidecar.json 的内容，按仓库现有结构合并进 docs/food-properties-sources.json（或新建 docs/food-tcm-evidence.json 并在文档中说明）；运行时 loader 不得读取该文件。
2. 生成/更新一份审核清单 CSV 或 Markdown（放 docs/）：
   - 原 147：不一致 20、待核 67；五味不一致单独列出。
   - 新 79（尚未入库）：文献冲突 15、仅本草纲目 9、有毒性提示 7。
   - 每条含：id、name、当前值、文献值、来源层级、建议动作（保留/改为…/待定）。
3. 不把 79 条写入 core/data/food_properties.json。
4. 跑测试，确认运行时行为无变化。

验收：运行时表未变；证据文件不进运行时；审核清单可独立发给中医师。
```

---

## 第 3 步：匹配修复（79 条入库前必修）

```
任务：修复「菜名被单个新食材关键词抢走」的问题，为分批入库做准备。先不要合并 79 条。

背景（必须复现并写测试）：黑胡椒牛排→胡椒、桑葚酒→桑葚、菠萝咕咾肉→菠萝、柚子茶→柚子、「枣」从红枣茶变成鲜枣；以及 马齿苋包子、芝麻酱拌面、百香果茶 等。

1. 阅读 food_lookup 的匹配与排序逻辑，提出并实现修复，优先考虑：
   - 更长关键词优先；
   - 避免单字/过短 token 误伤；
   - 已有完整菜名/茶饮条目时优先于原料；
   - 不要破坏现有 147 条的既有匹配（用仓库里原有匹配相关测试 + 新增回归用例）。
2. 新增回归测试，覆盖上面列出的错误样例，以及至少 5 个「应仍匹配原条目」的对照。
3. 用脚本对一批菜名做 before/after 报告，附在 PR 说明。
4. 仍不写入 79 条新食材。

验收：新回归测试全绿；原有匹配测试全绿；报告里上述误匹配已消失。
```

---

## 第 4 步：分批加入新食材（跳过高风险词）

```
任务：在第 1、3 步已合并的前提下，把「安全批次」新食材写入 food_properties.json。

1. 数据源：docs/food-expansion/split/food_properties.json 与 new_foods.csv。
2. 本批不要加入：
   - 9 种调料：花椒、胡椒、八角、桂皮、孜然等（以 new_foods / review_response 名单为准）；
   - 柚子、菠萝、桑葚、梅子；
   - 白果（药典有毒，除非产品明确接受并加安全标记）。
3. 其余新条目：只写入运行时需要的字段（15 或 17，与第 1 步决策一致）+ 必要的 food_group_code / dg2022_layer；review_status=pending。
4. 更新所有写死「147」的测试与文档数字（约 5 处，见 review_response），改为实际新总数。
5. 跑全量测试 + 第 3 步回归；用 offline 路径抽测若干含新食材的餐例，确认不会再出现「整菜被调料/水果单字劫持」。
6. 被跳过的条目列在 docs 的「第二批待入库」清单，附原因。

验收：高风险词未入库；计数类测试已更新且通过；无新增误匹配。
```

---

## 第 5 步：食物表与药材表重叠 + 体积收尾

```
任务：处理与 herbs.json 的重叠，并确认体积/加载方式符合约定。

1. 重叠（至少）：薏米↔薏苡仁、红豆↔赤小豆、山药↔山药、桑葚↔桑椹；并扫描是否还有同名/别名重叠，写入 docs/food-herb-crosswalk.json（或 sidecar）：food_id、herb_id、关系说明、寒热是否一致。
2. 桑葚：以药典为准统一为寒；若改 herbs 或 food，必须在文档记录决策，并加测试锁定。
3. 加测试：从食物表解析出的任何 id/name，不得出现在推荐候选药材列表中（候选只来自 herbs.json 过滤结果）。
4. 确认运行时未加载 tcm_evidence；大段出处只在 docs。若第 1 步选了 sidecar 分类，确认 loader 行为与文档一致。
5. 跑全量测试。

验收：对照表落地；推荐候选不含食物表条目；运行时 JSON 体积可控；测试全绿。
```

---

## 给审核同学的一句话分工

| 步骤 | 谁审 | 审什么 |
|---|---|---|
| 1 | 营养学 | WS/T 464 编码、宝塔层、46 条歧义 |
| 2 | 中医师 | 四气五味与出处，不改代码 |
| 3–4 | 工程 | 匹配与分批入库 |
| 5 | 工程 + 产品 | 食药重叠策略、桑葚寒热 |

第二批（调料 + 柚子/菠萝/桑葚/梅子等）等第 3 步匹配方案稳定、中医师点头后再开新任务，不要塞进第 4 步。
