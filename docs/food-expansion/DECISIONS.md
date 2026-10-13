# 食材表改造决策记录

## 第 1 步（2026-10-12）

### 数据契约：选 A —— 运行时字段扩为 17 个

- **决定**：在 `core/scripts/patch_food_table.py` 的 `FIELD_ORDER` 末尾追加 `food_group_code`、`dg2022_layer`，由 15 → **17**。
- **不选 B 的原因**：分类要进运行时 JSON 便于以后膳食结构分析与导出；`normalize_key_order` 本就会把未登记字段排到后面，登记进 `FIELD_ORDER` 可避免键序漂移。当前 `core/app` **不读**这两个字段（见 `_meta.food_group.runtime_use`）。
- **文档**：`docs/data-contracts.md` 已改为声明 17 个字段。
- **未改**：原 15 字段取值（含全部 `nature` / `flavors` / `category` / `aliases` / `keywords`）；未入库 79 条新食材；未加载 `tcm_evidence`。

### 分类标准

- 存储：`food_group_code` = WS/T 464-2015 类-亚类-小类码（含非标准 `X-n` 复合菜组）。
- 展示：`dg2022_layer` = 膳食宝塔 2022（1–5 / 0=宝塔外 / X=复合）。
- 宝塔更正已体现在本批数据：菌藻→第 2 层；奶类→第 4 层（杂豆更正仅影响尚未入库的新增条目）。

### 审核材料

- 46 条归类歧义：`docs/food-expansion/classification_ambiguous.md`
- 设计说明：`docs/food-expansion/review_response.md`

## 第 2 步（2026-10-12）

### 证据存放：新建 `docs/food-tcm-evidence.json`（不合并进 sources 登记表）

- **原因**：既有 `docs/food-properties-sources.json` 是 94 条「登记表」list 结构（`id/project/evidence/reference/...`）；sidecar 是按 id 索引的 226 条核验结果（`tcm_check/tcm_evidence/...`），结构不同，强行合并易破坏既有契约与脚本。
- **约定**：审核读 `food-tcm-evidence.json` + `tcm_review_checklist.md`；登记表继续服务其原有用途。
- **运行时**：`core/app` / `ui` **零引用**本文件（已 grep 确认）。
- **运行时表**：`food_properties.json` 的 `nature`/`flavors` 与第 1 步结束时 SHA256 一致；79 条未入库。

## 第 3 步（2026-10-12）

### 匹配启发式：词界约束（未入库 79）

- **问题**：影子加载新食材后，菜名被子串原料抢走（黑胡椒牛排→胡椒等）。
- **方案**：在 `match_foods` / `_find_entry` 落地 CJK token 词界、饮品后缀保护、前缀孤儿抑制、规范名嵌套剔除、主食/茶排序加权、中心语在后。
- **验证**：`tests/test_match_hijack_regression.py` 用影子表（不写盘）；报告见 `matching_before_after.md`。
- **未做**：79 条仍不写入 `core/data/food_properties.json`。

## 第 4 步（2026-10-12）

### 安全批次入库 65 条；hold-back 14 条

- **入库**：79 − 14 = **65** → 运行时总计 **212**（194 食材 + 18 茶饮）。
- **Hold-back（第二批）**：9 调味（花椒/胡椒/八角/桂皮/孜然/芝麻/猪油/大豆油/蜂蜜）+ 柚子/菠萝/桑葚/梅子 + 白果。清单：`batch2_pending.md`。
- **字段**：仅 `FIELD_ORDER` 17 字段；`review_status=pending`。
- **未改**：原 147 条 nature/flavors；未加载 tcm_evidence。

## 第 5 步（2026-10-12）

### 食药对照与桑葚寒热

- **对照表**：`docs/food-expansion/food-herb-crosswalk.json`（并复制 `docs/food-herb-crosswalk.json`），扫描精确词交集，共 13 对；运行时不读。
- **策略**：维持 E8-β —— 食物表与 `herbs.json` 并存；推荐候选只来自 `filter_by_constitution`（herbs.json）。
- **桑葚 / 桑椹**（唯一寒热不一致）：
  - 食物侧（第二批 hold-back，**未入库**）按药典取 **寒**；
  - 饮片 `sangshen` 现为 **凉**（`herb_nature_reference` 已登记与药典分歧）；
  - **不静默改 `herbs.json`**；是否改凉→寒交所有者 + 中医师裁定后再动。
- **测试**：`core/tests/test_food_herb_boundary.py` 锁定候选边界与证据不进运行时。

## 第 6 步（2026-10-13）

### 桑椹饮片四气：按药典凉→寒（所有者批准）

- **决定**：`core/data/herbs.json` 中 id=`sangshen`（名「桑椹」）的 `nature` 由 `cool`（凉）改为 `cold`（寒）。
- **依据**：《中国药典》2020 年版一部 p.362「桑椹」【性味与归经】原文「甘、酸，寒。归心、肝、肾经。」（在线：https://ydz.chp.org.cn/#/item?bookId=1&entryId=475）。
- **对照表**：`docs/food-expansion/food-herb-crosswalk.json`（及 `docs/food-herb-crosswalk.json`）桑葚↔桑椹 `nature_agree=true`；`_meta.counts.nature_mismatch` 1→0。
- **未改**：百合、淡竹叶仍为凉（本次只批桑椹）；食物侧桑葚仍第二批 hold-back（`food_in_runtime=false`），未写入 `food_properties.json`。
- **测试**：`test_food_herb_boundary.py` 改为断言寒热一致且食物未入库；`test_herb_crosscheck.py` 的 `EXPECTED_INCONSISTENT` 去掉桑椹，并重建 `herb_nature_reference.json`（`--recompute`）。


## 第 7 步（2026-10-13）

### Batch H1：饮片 P0×7 入库 + 食疗模板（数据层）

- **决定**：向 `herbs.json` 追加 7 味（`huangqi` 黄芪、`dangshen` 党参、`danggui` 当归、`sharen` 砂仁、`maiya` 麦芽、`mugua` 木瓜、`pangdahai` 胖大海），44→**51**；`_meta.version` 0.8.0→**0.9.0**。
- **依据**：药食目录（2002-51 / 2019-08 / 2023-09）+ 《中国药典》2020 一部（本地 `chp2020_entries.json`）；体质 suitable/unsuitable **留空**（宁缺毋滥）；公告特殊人群与麦芽回乳、当归香辛料限定写入 `cautions`。
- **须煎煮**：黄芪/党参/当归/砂仁/麦芽/木瓜标 `requires_cooking`；胖大海沸水泡服（2–3 枚）。木瓜 brewing 标明宣木瓜≠番木瓜。
- **食疗模板**：新建 `core/data/soup_templates.json`（`sishen_tang`、`jiangzao_cha`，`kind=food_therapy`，pending）；只读加载器 + 契约测试；**不**改 Agent2 提示词、**不**接推荐 API。
- **未做**：git push / commit；门诊经方整方；清补凉/银耳莲子等下一批评审入库。
- **旁路**：`docs/food-expansion/soup_templates_landing.md`；文献候选见 `food-therapy-literature-candidates.md`。

## 第 8 步（2026-10-13）

### 五条食疗模板入库 + Agent 思考路径最小接线

- **决定**：在已有 `sishen_tang` / `jiangzao_cha` 之外，向 `soup_templates.json` 追加 5 条（`yiner_lianzi_baihe`、`qizao_jitang`、`shenqi_dazao`、`qingbuliang_wl`、`shanzha_maiya`）；模板总数 **7**；`_meta.version` → **0.2.0**。
- **Schema**：`components[]` 每项必须且只能含 `herb_id` **或** `food_id`；加载时校验分别 ∈ `herbs.json` / `food_properties.json`（foods + tea_drinks）。
- **边界**：全部 `kind=food_therapy`、`review_status=pending`；厨房约量文案；芪枣禁「补中益气」；清补凉钉死五味白名单；山楂麦芽强制哺乳回乳 + 孕慎 caution。
- **Agent 路径（最小）**：`list_soup_templates` / `get_soup_template` 只读工具函数；`tool_registry_stub.py` 注册点；`docs/agent-path-soup-templates.md`；`agent2_system.md` 硬边界第 9 条；可选 `GET /api/soup-templates`（reference 隔离，不进 recommend）。
- **未做**：完整 tool-calling 主循环；pending → Agent2 自动推荐；git push/commit。

