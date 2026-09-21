# 新工作区入门提示词

> **用法**：把下面 `## 提示词正文` 起的全部内容复制，作为新工作区会话的第一条消息粘贴。
> 由 2026-09-18 生成、2026-09-20 更新。项目会继续变，正文里的数字请以仓库现状为准——提示词只负责
> 让你知道「去哪儿查」和「哪些坑别人踩过」。

## 提示词正文

你正在接手 **tea-advisor**（工作目录 `D:\work\tea-advisor`）。下面是我能给你的最小可用上下文。
请**先读文件再下判断**——本提示词是路标不是事实源，仓库才是。

---

### 0. 项目是什么

「饮食 + 体质 → 茶饮推荐」。

- 后端：FastAPI，代码在 `core/app/`（三层：domain / services / agents）。
- 模型调用：双后端（`TA_BACKEND=direct | dsh`），提示词在 `core/app/agents/prompts/`。
- 无 API Key 或调用失败时走**离线规则兜底**（`core/app/services/matcher.py`），不是报错。
- 三个界面入口：终端 `ui/terminal/`、网页 `ui/web/`、体检式子包 `tcm-constitution-questionnaire/`（独立 pip 包，core 不 import 它）。
- 分层铁律：**`core/` 永远不 import `ui/`**，问卷子包与 core 之间只靠 id 字符串对齐。

### 1. 开工前先做这三件事

1. 跑测试，确认环境：
   ```
   cd core && ./.venv/Scripts/python.exe -m pytest tests -q
   ```
   期望 **765 passed**。红就是环境问题，先修再说别的。
2. 读 `docs/pending-items.md` —— 挂起项**唯一真源**，概览表 + 每项详情小节。
3. 读 `docs/handover.md` —— 全貌（设计原则、目录分层、数据资产、决策表、文档地图）。

### 2. 当前状态（2026-09-21 快照）

| 项 | 值 |
|---|---|
| 本地 HEAD | `dd34d94` |
| 远程 `origin/main` | `dd34d94`（与本地一致） |
| 未推送 | 0 —— 阶段 0／1／2 共 23 个提交已于 2026-09-20 推送（快进 `88c65a3..dd34d94`） |
| 工作区 | 干净 |
| 测试 | 765 passed |
| 唯一 ⛔ 硬阻碍 | **A1**：食性表 147 条全部未人工审核 ⇒ 「对外提供服务」不能算完成 |

数据规模：食物 **129** + 茶饮 **18** = 147 条（都在 `core/data/food_properties.json`）；
饮片 **44** 味（`core/data/herbs.json`，`_meta.version` 0.8.0）；
食性来源登记 **94** 条（`docs/food-properties-sources.json`）。

### 3. 关键文件地图

**运行时数据（`core/data/`，改之前先出方案）**

- `food_properties.json` —— 食物 129 条 + `tea_drinks` 18 条，四气五味、适宜/不宜体质。
- `herbs.json` —— 饮片 44 味。**内联数组格式**，`json.load`+`dumps` 回写会炸出巨大假 diff，只能文本级精确替换。
- `herb_nature_reference.json` —— 44 味 vs 药典 2020 的对照（已废止，见 C3），是核对报告**不是**来源表。
- `herb_evidence_sources.json` —— 饮片侧依据链（E3），`core/scripts/build_herb_sources.py --write/--check` 维护。

**来源与核验（事实源在 docs/，`docs/*.json` 不被运行时读）**

- `docs/food-properties-sources.json` —— 食性来源登记，94 条，受控词表在 `_meta.controlled_vocab`。
- `docs/food-properties-review-sheet.md` —— 上面那张表的**脚本产物**（`core/scripts/build_food_review_sheet.py`），不要手编。
- `docs/pending-items.md`、`docs/handover.md`、`docs/maintenance.md`、`docs/request-flow.md`。

**修改通道**

- 数据表唯一修正通道：`core/scripts/patch_food_table.py`（⚠️ `ENTRY_FIXES` 是**强制写入**，改数据必须同步改它，否则被静默写回；改完复跑验幂等）。

### 4. 铁律（这些都是踩出来的，别重蹈）

1. **只用 `core/.venv/Scripts/python.exe`** —— 仓库根 `.venv` 是残骸（缺 pytest/fastapi/httpx/dotenv）。
2. **仓库强制 LF** —— Python 写文件显式 `newline="\n"`。
3. **不擅自改 `core/data/*.json` 与 `.env`** —— 改前先出方案给所有者。`.env` 是 `load_dotenv(override=True)`，shell 环境变量改不了 `TA_BACKEND`。
4. **`herbs.json` 只能文本级替换**；批量「多处 old→new」用**脚本**（按文件聚合、一次读完一次写完），幂等判据用「**新串**」（`new` 含 `old` 时反过来判「old 不存在」），写完必须复核实际落盘。
5. **脚本产物不手工编辑**：`catalog-compliance` / `constitution-9-types` / `herb-nature-crosscheck` / `food-properties-review-sheet` / `herb-evidence-sources` —— JSON 才是事实源。
6. **本机 Git Bash coreutils 会间歇失效**（随机 exit 127）⇒ 提交用 `git commit -F <文件>`（文件写 gitignored 的 `core/var/`，用完删）；查文件用 Read/Grep 而不是 shell 的 cat/grep。
7. **本机有 `HTTP_PROXY` 没有 `NO_PROXY`** ⇒ localhost 必须显式绕代理（curl `--noproxy '*'` / Python `ProxyHandler({})`），否则 502。代理端口每次启动都变，需现场确认。
8. **push 前先 `git fetch` + `ls-remote` 比对**（`[gone]` 不代表已推；`update-ref` 会静默失效）。发现分叉**先停手，绝不 push -f**。
9. **`_find_entry` 把 `keywords` 与 `aliases` 合并扫描** ⇒ 移除一个词必须**两处都清**；改名会改变判层（`exact_name_hit` 才走查表直取）。
10. **`note` 是运行时字段**：`resolve_temperature_fields(name, note)` 扫两个串，命中 `CHILL_PREFIXES`/`HEAT_PREFIXES`（含「温热」）就改四气 ⇒ 补 note 前确认没有这些连续子串。
11. **测试写法**：派生不变式 + 负控制，**不写数据快照断言**（改一次红一次，且分不清「数据坏了」还是「活干完了」）。改守卫后做**变异检验**确认它真会红。

### 5. 已完成的两大块（2026-09-18）

**B2 —— 问卷接入推荐链路**（6 提交 `3d84ff8`…`65956e6`，已推送）

- 新增 `core/app/domain/constitution_resolver.py`：`resolve_from_scores(scores) → (primary, avoid, note)`。
- 体质是**四处独立消费**：① 就绪闸门 ② `filter_by_constitution`（LLM）③ matcher 场景规则/默认搭配（离线）④ `check_constitution_fit` 护栏。四处都透传了 `avoid`；离线路径对 `avoid` **硬剔除**。
- 终端入口 `ui/terminal/chat.py` 的 `--questionnaire` / `:qz`。
- 关键测试：`core/tests/test_constitution_integration.py`（跨路径一致性，从数据反推屏蔽体质，做过变异检验）。
- 方案与执行记录在 `docs/b2-questionnaire-integration-plan.md`、`docs/b2-integration-execution-plan.md`。

**B1 —— 茶饮 11 条食性来源登记**（4 提交 `4b1cca5`…`8308c38`，**已于 2026-09-18 推送**）

- `4b1cca5` 登记表 +11 条 + 新词表「制品·原料继承」　`291c69c` 重生成核验单
- `388f316` 新增守卫：`how="制品·原料继承"` 的 `matched_name` 必须在 `herbs.json` 有**同名饮片且四气相等**（含负控制，两个分支都做了变异检验）
- `8308c38` 核实记录改「已拍板」并归档落盘方案
- 记录：`docs/food-properties-b1-tea.md`（核实）、`docs/food-properties-b1-landing.md`（落盘方案）。
- **`core/data/` 一字未改** —— 登记的是来源，不是数据。

### 6. 待确认 / 下一步

- ⛔ **A1**：147 条全未人工审核 —— 唯一硬阻碍，没有它别谈对外服务。
- **A3**（`口蘑` 凭项目判断挂别名）、**C1/C2/C3**（中华本草空列 / 国标转引 / 药典 2020 已废止）、**D1**（玫瑰·茉莉代码改动）、**D3**（7 味须预处理）：都待外部资料或所有者拍板。
- **E4**：LLM 路径对主导体质的 `unsuitable_for` 是硬排除，离线路径只给 caution —— 同一体质有无 Key 拿到的安全边界不同，**口径未定，先别改**。
- **茶饮剩 7 条**（普洱/绿茶/红茶/乌龙/大麦茶/水果茶/奶盖茶）：三处基准语料确无依据，按 L3 留在剩余 100 条里，B1 只覆盖 11/18。
- 剩余 100 条食性分层见 `docs/food-properties-remaining-plan.md`（L1 35 / L2 32 / L3 33，**未动数据**）。

### 7. 跟所有者协作的方式

- **先给方案，确认后再动代码。** 所有者明确要求这个节奏。
- **每步跑 pytest**，交付时报 hash、改了哪些文件、测试结果、留作待确认的项。
- **判断在表，不在模型** —— 来源登记表是事实源，不要问模型某食物什么性味。
- 浏览器验收不装 agent-browser：用 Edge + venv `websockets` 直连 CDP（样例 `core/var/browser_check*.py`，可能被清过）。

### 8. 已知文档滞后（读到时别当真）

- 后端 `NO_API_KEY` 文案仍写「API Key 一栏」（前端已改，后端没跟）。
- `docs/request-flow.md` 标注了三处文档/代码不一致（Agent1 JSON 失败实为 422 硬失败等）。
- 快照日期写死在 `handover.md` / `pending-items.md` 里（守卫要求），不代表内容是最新的。
- 另有若干「单据性」文档滞后仍挂在 `docs/pending-items.md` 里（如 **E6** 路线图数字失真），本节的通用提醒不再重复列举。

### 9. 别动的东西

- `D:\work\tea-advisor-fork-keep` —— 27 个分叉保留文件（含 2075 行 `index.html` 参考版，清单见其 `MANIFEST.md`）。🟡 四项前端改造做完前**不要删**。
- 分支 `remote-backup-nanple` —— 覆盖远程前的备份（远程已用本地覆盖，快进非强推）。
- `core/.venv` —— 唯一可用的环境。

### 10. 一个 bisect 陷阱

`4b1cca5`（B1 提交 1）**单独 checkout 是红的**：它改了来源登记表但核验单还没重生成，
`build_food_review_sheet.py --check` 会失败。从 `291c69c` 起全绿。
这是四步切分的代价，不是 bug，别去「修」它。

---

**正文结束。** 读完请先用 §1 的三件事确认环境，再决定做什么。
