# tea-advisor 系统行为规格（SPEC）

> **本文件描述的是"现在实际跑出来的行为"，不是设计意图，也不是待办清单。**
> 写法遵循一条纪律：凡是写进来的结论，都能在代码里指到具体文件与行号；
> 凡是没核实过的，一律标 `[待确认]`，不猜、不圆。

| 项 | 值 |
|---|---|
| 内容锚点 | `tea-advisor` @ git `9adbd49`（"test(数据契约): 新增 test_data_contracts.py + 修文档 4 处事实错误"）。**这是本文件所描述的那份代码**：此后没有代码提交 |
| 维护史 | 本文件于 `9a52528` 入库（该提交**纯新增本文件**，未改任何代码/数据/测试）；最近一次改动为 `de7b759`（2026-09-26，"补 7 项测试（终端壳 CLI 4 + 降级路径 3），同步计数与 SPEC"） |
| 最近复核 | **2026-09-26**：全部规模数字按仓库现状重测（见附录 A，0 处不符）；锚点与引用行逐条核验（**242 个**仓库内锚点，越界 0、无法解析 0）；原 §10「工具层验证结论」移为附录 D；口径与覆盖描述据实更正 |
| 描述范围 | `D:\work\tea-advisor\` 这一套**实际运行系统** |
| 初版生成方式 | 只读复核：通读源码 + 数据文件结构提取 + 离线测试实跑（初版生成时未修改任何既有文件）。**此后本文件按变更同步维护**，因此"只读复核"只描述初版 |
| 明确不在范围内 | `tea-advisor-fork-keep/`（未吸收素材）、`ta-recon/`（外部调研）、`core/var/`（历史痕迹区）、`dsh-home/`（DSH 会话存储）、`.venv/` |
| 行号含义 | 全部为 LF 行号（与编辑器一致）。⚠️ 本环境 `Get-Content` 会漏计空行，**不要**用它的计数复核本文件的行号 |
| 锚点写法 | 带目录的锚点一律写全路径（`core/app/...`、`ui/...`、`tcm-constitution-questionnaire/...`）。两处例外：① 裸文件名（如 `safety.py:81`）指 `core/app/` 下的同名模块；② 正文里裸写的 `tests/xxx.py` 指 `core/tests/xxx.py`。**附录 D 例外**：它的锚点基准是**仓库外**的 `D:\experiments\test_tool_calls.py`（表头已声明） |
| 标记约定 | ✅ 已实现（代码可指认）　❓ 待确认（未核实，见 §9.1）　🚫 当前不支持（明确没做）　📌 文档滞后（代码与文档不一致，以代码为准，见 §9.2）　🧪 已验证（实验内，见附录 D）　🔌 未接入主流程（见附录 D）　📎 外部来源（非本仓库可核，见附录 D） |

---

## 1. 系统定位

### 1.1 是什么

一句话：**它把"食物是寒是热"这件事从模型凭语感猜，改成查表 + 纯规则判定，再在这个确定性基础上给出日常饮食茶饮建议。**

它由两半组成，且**两半可以分开用**：

- 上半层是**判定库**：`resolve_food("冰啤酒")` → 寒。纯数据 + 纯规则，确定性、可复现、零 API 调用、零成本、毫秒级。这一层**完全不调用模型**（`README.md:24`）。
- 下半层是**本地助手**：把用户口述的饮食转成结构化结果，结合体质，推荐 1–3 条药食同源饮片的冲泡搭配。模型只在"把自由文本解析成食物列表"与"写一段人话建议"这两步参与，且**随时可以整个绕过**。

### 1.2 给谁用

| 使用者 | 他要的 | 走哪条路 |
|---|---|---|
| 想要一个本地助手的人 | 输入"中午吃了碗麻辣烫配冰可乐"，得到"该喝什么" | Web 界面 / 终端全链路（需自己的 API Key） |
| 想要一个可复用判定库的人 | `resolve_food()` 的确定性判定 | `--resolve`（终端）或直接 import（无需 Key） |
| 不想花 Key 额度的人 | 要建议但不要模型 | `--offline` 终端 / 网页"离线规则"勾选 / `/api/analyze-offline`（无需 Key） |

### 1.3 解决什么问题

**模型的系统性偏差**：实测模型在食物寒热上会成体系地判错——把性温的茉莉花茶判成"凉"，把中性食材（小笼包、兰州拉面）普遍判成"温"。加入查表后，属性准确率从 **81% 提升到 100%**（`README.md:296`）。

由此推出全项目的核心工程取舍：**"提示词里写十遍不要开方，不如让模型无方可开"**（`README.md:329`）——安全性不靠"请求模型遵守"，靠"结构上让模型做不到"（详见 §5）。

### 1.4 不是什么（简版，完整见 §8）

不是医疗建议、不做诊断、不开方剂、不承诺疗效、不做"事前提醒"、没有服务端内置 Key、没有账户体系与数据库、不是多用户服务。

### 1.5 运行形态与成本

| 维度 | 现状 ✅ |
|---|---|
| 部署 | 全部本地运行。不需要域名、备案、服务器或任何平台审核（`README.md:4`） |
| 前端 | 两个壳：`ui/web/index.html`（1057 行，由 FastAPI 同源提供）、`ui/terminal/chat.py`（606 行，仅标准库） |
| 模型 | 默认直连 DeepSeek 官方 API（`TA_BACKEND=direct`），模型 `deepseek-v4-flash`，`TA_REASONING_EFFORT=low` |
| 费用 | 记在**调用方自己的账号**上。高风险分支与离线分支**一分钱不花**（不调用模型，见 §5.2） |
| 延迟 | 全链路 13.4–18.7 s（真实模型实测，`README.md:449`）；高风险分支 ~0 s；`--offline` ~0.00 s |
| 依赖 | Python 后端：FastAPI / uvicorn / pydantic / httpx / python-dotenv；问卷子包为**可选**依赖 |

---

## 2. 当前架构

### 2.1 分层与依赖方向

**单向依赖**：`ui/` 只依赖 `core/app/`；核心逻辑层**不得**反向 import `ui/`（`README.md:405`）。`core/app/domain/` 不依赖 Web 框架。

```
ui/            （壳：终端 + 网页，各自实现渲染与显示规则）
  ↓
core/app/api/       HTTP 适配层（取 Key、分档错误码、路由）
core/app/services/  编排、匹配、兜底、检索、只读资料
core/app/agents/    两个 Agent、运行时后端、JSON 护栏、提示词
core/app/domain/    枚举、数据模型、安全护栏、四性运算、信号、餐次
core/data/          规则库与数据文件（10 个 JSON）
```

### 2.2 模块规模与职责（行数为实测 LF 行数）

| 文件 | 规模 | 职责 |
|---|---|---|
| `core/app/main.py` | 205 行 | FastAPI 装配：路由注册、CORS（只放行本机来源）、lifespan 启动自检、`/healthz`、`/api/meta`、`/api/constitutions`、`/api/catalog/herbs`、`/api/disclaimer`、`/` 与 `/demo` 返回网页 |
| `core/app/config.py` | 129 行 | 环境变量集中读取（唯一入口）。**不读任何 API Key**；`.env` + `credentials.env` 两处加载 |
| `core/app/api/analyze.py` | 67 行 | `POST /api/analyze`。取 Bearer Key → `orchestrator.analyze()`；错误码分档 400/422/500 |
| `core/app/api/analyze_offline.py` | 215 行 | `POST /api/analyze-offline`。纯规则链路，不需要 Key，一次模型都不调 |
| `core/app/api/auth.py` | 47 行 | 只做一件事：把 `Authorization: Bearer <key>` 解析成裸 Key。不写日志、不入异常 |
| `core/app/api/questionnaire.py` | 126 行 | `POST /api/questionnaire`、`GET /api/questionnaire/questions`。依赖可选子包；请求/响应模型定义在本文件（见 §4） |
| `core/app/api/chat.py` | 197 行 | `POST /api/chat` + `GET /api/chat/models` + `GET /api/chat/personas`。**兼容对话入口，不是茶饮主流程**；请求/响应模型定义在本文件（见 §4） |
| `core/app/api/medication.py` | 48 行 | `GET /api/medication-reference[/{constitution}]`。只读展示，不参与推荐链路 |
| `core/app/services/orchestrator.py` | 378 行 | 编排入口 `analyze()`：三道前置闸门 → Agent1 → Agent2 → 输出护栏 → 组装；`_build_basis()` 是 `Basis` 的唯一构造点 |
| `core/app/services/matcher.py` | 595 行 | 规则兜底 `fallback_recommend()`、场景规则、体质默认搭配、冲泡常量、优先级链 L0–L4 |
| `core/app/services/food_lookup.py` | 663 行 | 三层判定入口 `resolve_food()`、匹配 `match_foods()`/`_find_entry()`、温度层准入、置信度常量、提示词参考表渲染 |
| `core/app/services/medication_reference.py` | 220 行 | 用药调理资料加载与结构校验（显式失败），与推荐链路硬隔离 |
| `core/app/agents/agent1_diet.py` | 195 行 | 饮食解析器：拼提示词（含参考表）、调运行时、`json_guard` 校验、`calibrate_parsed()` 校准 |
| `core/app/agents/agent2_recommend.py` | 257 行 | 推荐器：候选清单渲染、优先级渲染、未验证项隔离节、调运行时、`json_guard` 校验；`Agent2Output` 定义在本文件（见 §4.3） |
| `core/app/agents/runtime.py` | 251 行 | 后端选择：`direct`（默认，支持逐请求 Key）/ `dsh`（子进程，Key 绑定）；`CredentialError` |
| `core/app/agents/direct_api.py` | 235 行 | 直连官方 API：thinking 参数映射（见 §2.6）、120 s 超时、状态码→错误类型映射 |
| `core/app/agents/multi_provider.py` | 255 行 | 多供应商（deepseek/qwen/mimo/hy4），**只被 `/api/chat` 使用** |
| `core/app/agents/json_guard.py` | 166 行 | 围栏剥离 → 对象提取 → 宽松解析 → schema 校验 → 失败重试 1 次 |
| `core/app/agents/prompts/agent1_system.md` | 66 行 | Agent1 系统提示词 |
| `core/app/agents/prompts/agent2_system.md` | 99 行 | Agent2 系统提示词（含"硬性边界"8 条） |
| `core/app/domain/safety.py` | 514 行 | **确定性安全护栏**：高风险、禁用表述、白名单、剂量、体质收敛、煎煮适配、依据链 |
| `core/app/domain/models.py` | 361 行 | 请求/响应/中间结构的**主要**真源（另有 8 个模型定义在别处，见 §4 开头） |
| `core/app/domain/enums.py` | 134 行 | 四气/五味/时段/烹饪/九型体质的枚举与中文标签 |
| `core/app/domain/nature_math.py` | 462 行 | 四性数值编码、夹取、两层修正、合成 `combine()`、温度前缀唯一入口、寒热错杂 |
| `core/app/domain/diet_signals.py` | 678 行 | 饮食信号识别与计分（冲击度/湿气度/寒热错杂）、餐单派生 `derive_meal_plan()` |
| `core/app/domain/constitution_resolver.py` | 206 行 | 问卷分数 → 主导体质/兼夹体质的收敛与屏蔽集（失败类型见 §3.3） |
| `core/app/domain/meal_time.py` | 44 行 | 餐次猜测（两条离线链路共用一份） |
| `core/data/*.json` | 10 个 JSON | 规则库与数据（结构见 §4.6） |
| `core/tests/` | 45 个测试文件 | 835 项离线测试（不调模型、不需要 Key）。⚠️ 口径：**45 = `test_*.py` 的个数**；该目录下还有 `conftest.py` 与 `__init__.py`，`*.py` 合计 **47** 个（`docs/maintenance.md` §1.4 按"排除 `__init__.py`"口径记作 46，两者口径不同、都对） |
| `core/scripts/` | 12 个脚本 | 数据构建/同步/自查脚本 + 冒烟脚本 |

### 2.3 核心链路：四道闸门 + 一道结构性限制

所有入口最终汇到 `orchestrator.analyze()`（`core/app/services/orchestrator.py:192`）。HTTP、终端、脚本三条入口**全部**经它，所以手搓 API 也绕不过闸门。

| 顺序 | 闸门 | 拦什么 | 放在这个位置的**原因**（代码注释明写） |
|---|---|---|---|
| ① | 高风险人群 | 25 个人群/情境关键词（`safety.py:21-26`、判定 `:127`） | **不调模型、不花钱，所以必须无条件可用**——没填 Key 的用户说"我怀孕了"，应看到"请先咨询执业医师"而不是"缺少 API Key" |
| ② | 体质就绪 | `herbs.json` 里没有任何饮片把该体质标进 `suitable_constitutions` | 排在 ① 之后：安全提示不该被"数据没备齐"这种配置问题挡掉。排在 ③ 之前：体质不可用**不是填个 Key 能解决的**，先报更根本的那条 |
| ③ | 凭据 | 没带 Key；或 `TA_BACKEND=dsh`（不支持逐请求 Key） | 本项目无服务端兜底 Key，没 Key 就无法调用模型 |
| ④ | 输出护栏 | 白名单外 / 超 4 味 / 超剂量 / 禁用表述 / 体质不合 / 焖泡与煎煮错配 | 模型会飘，护栏不能飘；**被拦的内容绝不原样返回给用户** |

**另有一道结构性限制**（不计入闸门，但等同于第二道防线）：**候选集收敛** `safety.filter_by_constitution(constitution, limit=12, avoid=...)`（`safety.py:353`）——模型能选的饮片只有这 12 味，且方向已按体质收敛过。模型"想越界开方"也写不出来（`docs/request-flow.md:161`）。

锚点速查：① `orchestrator.py:218`　② `orchestrator.py:253` + `safety.py:415`　③ `orchestrator.py:257-265`　④ `orchestrator.py:129-189`　结构性 `safety.py:353`。

### 2.4 数据流

```
用户口述 + 体质（+ 兼夹体质屏蔽集、排除饮片）
   │
   ├─ HTTP：Authorization: Bearer <key>  ──► api/auth.extract_api_key()
   ▼
orchestrator.analyze(request, api_key)
   │  闸门① 高风险 ──命中──► 空推荐 + 引导就医（不调模型，免费）
   │  闸门② 体质就绪 ──不就绪──► 422 CONSTITUTION_NOT_READY
   │  闸门③ 凭据 ──无 Key──► 400 NO_API_KEY
   ▼
Agent1 parse_diet()：查表→渲染参考表→注入 user 提示词→模型→json_guard 校验
   ▼
calibrate_parsed()：逐项 resolve_food() 三层判定，**表命中即覆盖模型值**，把握度重算为均值
   ▼
signals = build_meal_signals(text, foods)    ← 冲击度 / 湿气度 / 寒热错杂
plan    = derive_meal_plan(signals, 体质)     ← 方向接管与推迟
   ▼
候选集 filter_by_constitution(体质, limit=12, avoid)  ← 模型只能从这里挑
   ▼
Agent2 recommend()：候选清单 + 优先级 + 未验证项隔离 → 模型 → json_guard 校验
   │  失败或返回空 ──► matcher.fallback_recommend()  （degraded=True）
   ▼
闸门④ _sanitize_recommendations()：剂量/白名单/禁词/体质/冲泡 逐条清洗
   │  全被拦 ──► 再兜底一次（degraded_reason="guardrail_removed_all"）
   ▼
_build_basis() → herb_evidence(本次实际留下的饮片, 体质)
   ▼
AnalyzeResponse（必带 disclaimer；meta 带 key_source / backend / 耗时 / degraded）
```

### 2.5 对外接口面

路由注册实测在 `core/app/main.py:110-114`（五个 router）；辅助接口在 `main.py:120-205`。

| 方法 | 路径 | 需要 Key | 用途 | 定义处 |
|---|---|---|---|---|
| POST | `/api/analyze` | **是** | 主流程：口述 → 茶饮推荐 | `core/app/api/analyze.py:35-67` |
| POST | `/api/analyze-offline` | 否 | 离线规则推荐（不调模型） | `core/app/api/analyze_offline.py:65-215` |
| POST | `/api/questionnaire` | 否 | 问卷计分 → 主导体质 + 兼夹屏蔽集 | `core/app/api/questionnaire.py:59-108` |
| GET | `/api/questionnaire/questions?sex=` | 否 | 取题目（默认 `male`） | `core/app/api/questionnaire.py:111-126` |
| POST | `/api/chat` | **是** | 兼容对话入口（多模型），**非茶饮主流程** | `core/app/api/chat.py:76-180` |
| GET | `/api/chat/models` | 否 | 6 个硬编码模型选项 | `core/app/api/chat.py:183` |
| GET | `/api/chat/personas` | 否 | 旧版兼容接口，**固定返回空数组** | `core/app/api/chat.py:195` |
| GET | `/api/medication-reference` | 否 | 用药调理资料目录（只读） | `core/app/api/medication.py:17` |
| GET | `/api/medication-reference/{constitution}` | 否 | 单个体质的资料，未收录 → 404 | `core/app/api/medication.py:34` |
| GET | `/healthz` | 否 | 自检（含 `user_key_supported`，前端据此提示后端是否支持自带 Key） | `core/app/main.py:120-137` |
| GET | `/api/meta` | 否 | 展示用中文标签 + `conf_show_threshold` + 食性表规模 | `core/app/main.py:173-195` |
| GET | `/api/constitutions` | 否 | 可对外服务的体质（按 `ready_constitutions()` 过滤） | `core/app/main.py:151-170` |
| GET | `/api/catalog/herbs` | 否 | 饮片目录：白名单全量（见 §5.3） | `core/app/main.py:140-142` |
| GET | `/api/disclaimer` | 否 | 免责声明文案（避免各壳硬编码） | `core/app/main.py:145-148` |
| GET | `/`、`/demo` | 否 | 同一个网页（`/demo` 为历史路径保留） | `core/app/main.py:198-205` |

### 2.6 配置项（全部在 `config.py` 集中读取）

| 变量 | 默认 | 作用 |
|---|---|---|
| `TA_BACKEND` | `direct` | Agent 运行时后端：`direct`（直连，支持逐请求 Key）/ `dsh`（子进程，调试用） |
| `TA_PROVIDER` / `TA_MODEL` | `deepseek-official` / `deepseek-v4-flash` | 模型选择（`config.py:54-55`） |
| `TA_REASONING_EFFORT` | `low` | 本模型支持 `max/high/low/off`；`medium`/`none`/`minimal` 会导致启动失败（`config.py:56-58`）。默认 `low` 是因为 `off` 虽快约 3 倍但推荐常只剩 1 条 |
| `TA_MAX_TOKENS` | `8192` | 上限 |
| `APP_HOST` / `APP_PORT` | `127.0.0.1` / `8000` | 服务地址（`start-web.cmd` 用 8180） |
| `AGENT1_TIMEOUT_S` / `AGENT2_TIMEOUT_S` | `45` / `60` | Agent 超时 |
| `DSH_HOME` | `<仓库根>/dsh-home` | 只在 `credentials.env` 里配（`dsh` 拒绝 `.env` 里的 `DSH_*`） |
| `DEEPSEEK_BASE_URL` | 官方地址 | 走兼容代理端点时才需要 |
| `DEEPSEEK_API_KEY` | 无 | **只从进程环境变量读，供终端/脚本用**；Web 走 `Authorization` 头。项目内**不保存、不落盘** |

**`TA_REASONING_EFFORT` → 官方 API 参数的翻译规则**（`core/app/agents/direct_api.py:55-72`，常量 `:51-52`）：

| 取值 | 实际发出的参数 |
|---|---|
| `off` / `none` / `disabled` | `{"thinking": {"type": "disabled"}}` —— 关闭思考。实测同一任务输出 token 从 135 降到 5，延迟 1165ms → 889ms（模块注释实测记录） |
| `low` / `high` / `max` | `{"thinking": {"type": "enabled"}, "reasoning_effort": <该值>}` |
| **其他非空值** | 记一条 warning，然后**按 `low` 处理**（宁可慢一点，也不要因为配置写错而静默变贵） |
| **空值** | 官方默认是"开启 + effort=high"，本项目仍**按 `low`** 处理，与项目原本的默认行为一致 |

> 官方档位是 `minimal→low, low→low, medium→high, high→high, xhigh→high, max→max, ultra→max`（`direct_api.py:49` 注释）；本项目只暴露语义明确的三个档位 + 关闭。

---

## 3. 核心用户流程

### 3.1 网页主线 ✅

1. **初始化** `loadInit()`：读已存 Key → 更新 Key 状态 → `refreshKeyHint()` 读 `/healthz`（若 `user_key_supported === false` 提示"当前后端不支持自带 Key"）→ 并发拉 `/api/meta`、`/api/constitutions`、`/api/disclaimer` → 填体质下拉 → 读已存体质 → 拉对话模型列表 → 渲染历史。
   ⚠️ **任一步失败即禁用主按钮**并提示"无法读取 /api/meta"（`ui/web/index.html:494-497`）。
2. **提交** `run()`：先 `saveKey()`；读"离线规则"勾选框；**只在"填了 Key 且非离线"时才带** `Authorization` 头；端点二选一 `/api/analyze-offline` 或 `/api/analyze`；请求体为 `text` + `constitution_override` + `avoid_constitutions`。
3. **错误处理**：`NO_API_KEY` / `USER_KEY_UNSUPPORTED` / `API_KEY_REJECTED` 归为"凭据问题"→ 自动打开设置弹窗并聚焦 Key 输入框；其余显示错误卡片。
4. **成功渲染**：`user_message` → "我理解到的"（`parsed.foods` 标签，悬停显示判定过程）→ "给你的建议"（饮片+克数、冲泡步骤、注意事项、匹配度）→ "这次推荐的公开依据"（`basis.references`）→ 免责声明 + `request_id` → 底部 meta（耗时、是否降级、体质、本次用没用 Key）。
5. **副作用**：成功即写入本地饮食记录。

**Key 存储**：勾选"记住 Key"→ `localStorage` 键 `ta_api_key`；默认不勾选 → `sessionStorage` 键 `ta_api_key_session`（只存当前标签页）。主界面只显示"已填写 / 未填写"，**不回显 Key 的任何部分**。

### 3.2 网页离线规则 ✅

勾选"离线规则"后走 `/api/analyze-offline`：不需要 Key、不调用模型。另外"饮食记录"面板里的"离线汇总近 7 天"也是固定打这个端点（把记录文本反序拼接后截取末 500 字）。

### 3.3 体质问卷 ✅（可选依赖）

| 环节 | 现状 |
|---|---|
| 题库 | 国标 30 个计分条目中，本子包含 **27 个不同问题**；因湿热质的两个性别限定题只答其一，**每位答题者实际回答 26 题**（`tcm-constitution-questionnaire/tcm_constitution/questions.py:3-5`） |
| 计分 | 转化分 = （原始分 − 条目数）/（条目数 × 4）× 100；逆向题按 6 − 取值处理 |
| 偏颇体质判定 | ≥ 40 →「是」；≥ 30 →「倾向是」；否则「否」 |
| 平和质判定 | ≥ 60 且其余 8 型均 < 30 →「是」；≥ 60 且均 < 40 →「基本是」；否则「否」 |
| 多型并存 | 国标允许多种偏颇体质同时为「是」；**按分数最高者收敛推荐方向，其余体质只做屏蔽**（把标为"不宜"的饮片排除），并在输出里写明兼了哪几型 |
| 「倾向是」 | 30–40 分**不是判定**。只有在没有任何「是」时才顶上来当主导体质，且一定提示"未达判定阈值，按倾向处理" |
| 判不出时 | **不默认平和质**，而是要求用户手动选（终端 `:c <体质>`、网页体质下拉）。理由：冒充平和质等于给一份无依据的推荐 |
| 收敛失败的两类异常 | ① **判不出** → `constitution_resolver.UndeterminedConstitutionError`（`core/app/domain/constitution_resolver.py:49`），端点转成 `requires_manual_selection=true`；② **体质 id 非法** → `UnknownConstitutionError`（`:40`）。另有 `validate_resolution()`（`:89`）对 `Resolution` 做结构校验 |
| 结果如何进入主流程 | 网页把 `dominant_constitution` 写进体质下拉、把 `avoid_constitutions` 存为当前屏蔽集，然后随 `run()` 的请求体一起提交 |
| 未装子包时 | 应用正常启动，只有问卷两个端点不可用（界面提示"问卷功能未启用…"，**不原样透出服务端安装指令**）；终端 `--questionnaire` / `:qz` 不可用 |

`--questionnaire` 与 `--constitution` 只能二选一；同时给会直接报错。

### 3.4 饮食记录 ✅

成功分析后**仅在浏览器本地**保存（`localStorage` 键 `ta_diet_history_v1`，最多 100 条）；可离线汇总近 7 天记录并回灌离线接口。不上传、不入库。

### 3.5 茶小助对话 ✅（兼容入口）

保留最近 20 条上下文（`core/app/api/chat.py:92`）；可选择 6 个模型；沿用用户自带 Key。**先跑高风险检测**——命中则直接返回固定就医话术并标 `safety_intercepted=true`，**此时不检查 Key、不调用模型**（`chat.py:94-105`）；无 Key 返回 400。模型输出经禁用表述扫描，不合规则替换为固定文案。凭据错误 → 400，运行错误 → 502。请求/响应结构见 §4.1、§4.2。
⚠️ 该项目 README 明确它"不是茶饮建议主流程"（`README.md:216-217`）。

### 3.6 调理资料 ✅（只读，隔离）

按体质展示《成年人中医体质治未病干预指南》资料摘要，**不提供剂量、不进入茶饮推荐链路、不送入模型、不参与白名单**。数据文件结构不合法时**显式报错**（`MedicationReferenceError`），不是静默空结果——这是刻意的：宁可失败，也不要看起来能用。

### 3.7 终端三链路 ✅

| 链路 | 命令 | 是否调模型 | 是否需要 Key |
|---|---|---|---|
| 纯查表 | `--resolve 冰啤酒 茉莉花茶` | 否 | 否 |
| 离线推荐 | `--offline "…"` | 否 | 否 |
| 全链路 | 位置参数 `"…"` | 是 | 是（环境变量 `DEEPSEEK_API_KEY`） |

交互命令：`:q`/`:quit`/`:exit` 退出、`:e` 列示例、`:qz` 跑问卷、`:c <体质>` 切体质（会清空兼夹屏蔽集与提示语）。
无 Key 时不是抛栈，而是打印一块"本项目不使用服务端内置 Key / 怎么设环境变量 / 申请地址 / 推荐先试 `--resolve` 与 `--offline`"的说明面板，然后返回码 1。
离线渲染与网页遵循**同一套显示规则**：置信度 ≥ `CONF_SHOW_THRESHOLD` 才显示寒热属性，否则显示"未判定"。

### 3.8 脚本与测试入口 ✅

`check_setup.py`（环境与数据自检，秒级）、`smoke_offline.py`（数据层→解析→规则兜底→护栏，不调模型）、`test_food_accuracy.py`（真实模型 23 条语料，**产生费用**）、`smoke_agents.py`（真实模型全链路，**产生费用**）、`pytest tests`（离线，见附录 A）。

---

## 4. 数据模型

> **主要真源**是 `core/app/domain/models.py`（22 个 `BaseModel`）。⚠️ **但不是全部**：另有 **8 个**请求/响应模型定义在各自的模块里，改它们同样等于改对外契约：
> `OfflineAnalyzeRequest`（`core/app/api/analyze_offline.py:33`）、`QuestionnaireRequest` / `ConstitutionResult` / `QuestionnaireResponse`（`core/app/api/questionnaire.py:37/42/49`）、`ChatMessage` / `ChatRequest` / `ChatResponse`（`core/app/api/chat.py:40/45/52`）、`Agent2Output`（`core/app/agents/agent2_recommend.py:31`）。本节把它们的字段一并列出。
>
> `models.py` 里还有 3 个**未被任何代码引用**的模型（`ErrorBody`、`ProfileResponse`、`ProfileUpdateRequest`），状态见 §9.1。

### 4.1 请求

| 对象 | 定义处 | 字段 |
|---|---|---|
| `AnalyzeRequest` | `models.py:283` | `text`(1–500，去空白后不可为空)、`meal_time`、`constitution_override`、`exclude_herbs`、`session_id`、`avoid_constitutions`。其中 `avoid_constitutions` 是**兼夹屏蔽集**：这些体质标为"不宜"的饮片一并排除，但**不改变收敛方向**（方向仍由 `constitution_override` 唯一决定） |
| `OfflineAnalyzeRequest` | `core/app/api/analyze_offline.py:33` | `text`(≤500)、`constitution`、`constitution_override`、`avoid_constitutions`、`exclude_herbs`。**没有 Key 字段** |
| `QuestionnaireRequest` | `core/app/api/questionnaire.py:37` | `sex`（正则 `^(female\|male)$`）、`answers`(dict[str, int]) |
| `ChatRequest` | `core/app/api/chat.py:45` | `messages`(1–40 条 `ChatMessage`)、`model`(默认 `deepseek-flash`)、`constitution`(默认 `balanced`)、`persona`(默认空串；**旧客户端兼容字段**，不改变系统身份) |
| `ChatMessage` | `core/app/api/chat.py:40` | `role`(`user`/`assistant`)、`content`(1–4000) |

### 4.2 响应

| 对象 | 定义处 | 字段 |
|---|---|---|
| `AnalyzeResponse` | `models.py:307` | `request_id`、`parsed`、`recommendations[]`、`basis`、`disclaimer`、`meta`、`user_message` |
| `Basis` | `models.py:241` | `constitution`、`constitution_label`、`rule_hits[]`、`guardrail_applied[]`、`references[]` |
| `EvidenceReference` | `models.py:223` | `id`、`title`、`publisher`、`url`、`supports[]`、`note`（来源自身的注意事项，**前端不得省略**） |
| `Meta` | `models.py:254` | `agent1_ms`、`agent2_ms`、`total_ms`、`model`、`degraded`、`degraded_reason`、`key_source`(`user`/`not_used`)、`backend` |
| `Disclaimer` | `models.py:25` | `version`、`text`、`is_medical_advice`(**恒为 false**) |
| `HealthResponse` | `models.py:331` | `status`、`herbs_loaded`、`data_files_ok`、`dsh_home`、`dsh_home_exists`、`model`、`disclaimer_version`、`backend`、`user_key_supported`（刻意**没有** `credentials_ok`——"服务端有没有 Key"不是有意义的状态） |
| `QuestionnaireResponse` | `core/app/api/questionnaire.py:49` | `dominant_constitution`(可为 null)、`dominant_constitution_name`(可为 null)、`avoid_constitutions[]`、`resolution_note`、`requires_manual_selection`(默认 false)、`scores[]`(`ConstitutionResult`)、`summary` |
| `ConstitutionResult` | `core/app/api/questionnaire.py:42` | `id`、`name`、`score`、`status` |
| `ChatResponse` | `core/app/api/chat.py:52` | `reply`、`model`、`usage`(可为 null)、`elapsed_ms`、`remembered_messages`、`persona`(默认 `tea_assistant`)、`references[]`(`EvidenceReference`)、`safety_intercepted`(默认 false) |

### 4.3 中间对象

| 对象 | 定义处 | 字段 | 说明 |
|---|---|---|---|
| `ParsedFood` | `models.py:67` | `name`、`amount_desc`、`nature`、`flavors[]`、`cooking`、`note`、`verification` | `note` 是**运行时字段**：温度前缀层会扫它 |
| `ParsedMeal` | `models.py:160` | `foods[]`、`meal_time`、`overall_nature`、`confidence`、`uncertain_items[]`、`summary`、`signals`、`plan` | `signals`/`plan` 为 `None` 表示未计算，既有关联方不传即保持旧行为 |
| `Verification` | `models.py:49` | `source`、`confidence`、`unverified`、`detail` | 三层架构的元数据出口 |
| `MealDimension` | `models.py:79` | `label`、`score`、`cap`、`action`、`action_label`、`signals[]`、`evidence_floor`、`basis` | 阈值与中文标签**全部来自数据文件**，代码不写死 |
| `MealConflict` | `models.py:100` | `conflict`、`heat_side[]`、`cold_side[]` | 值必须**原样**来自 `nature_math.detect_nature_conflict`，组装层不得另判一套 |
| `MealSignals` | `models.py:112` | `impact`、`dampness`、`conflict` | 三者都可能为 `None`（维度定义缺失时不臆造结论） |
| `MealPlan` | `models.py:142` | `first`、`second`、`deferred`(默认 **true**)、`note`、`second_note`、`data_missing` | `deferred=true` 时只给一条推荐——`check_blend` 是单条检查、不跨条，两组搭配同给会导致剂量叠加没人守 |
| `MealPlanStage` | `models.py:123` | `direction`、`label`、`open`、`herbs[]`、`amounts`、`title`、`reason` | `open=false` 表示**该方向本次不可用**（方向子集与候选集交集为空，或药材未定）。不是错误，也不得退化成别的方向 |
| `Agent2Output` | `core/app/agents/agent2_recommend.py:31` | `recommendations[]`、`user_message` | **Agent2 的原始输出结构**，比接口层薄一层：Agent2 的模型输出就是按它做 schema 校验的（`json_guard` 的校验目标） |

### 4.4 输出对象

| 对象 | 定义处 | 字段 |
|---|---|---|
| `Recommendation` | `models.py:212` | `title`、`herbs[]`、`brew`、`fit_reason`、`cautions[]`、`score` |
| `HerbInBlend` | `models.py:190` | `name`、`amount_g`(≥0)、`nature`、`flavors[]`、`meridians[]`、`role` |
| `BrewGuide` | `models.py:201` | `vessel`、`water_ml`(100–2000)、`water_temp_c`(40–100)、`steps[]`、`steep_min`(1–60)、`refill_times`(0–5) |
| `CatalogHerb` | `models.py:348` | `id`、`name`、`nature`、`flavors[]`、`meridians[]`、`effects[]`、`max_daily_g`、`cautions[]`、`suitable_constitutions[]`、`brewing`、`unsuitable_for[]` |

### 4.5 枚举

| 枚举 | 取值 |
|---|---|
| `Nature`（四气） | `cold`寒 / `cool`凉 / `neutral`平 / `warm`温 / `hot`热 / `unknown`未知 |
| `Flavor`（五味） | `sour`酸 / `bitter`苦 / `sweet`甘 / `pungent`辛 / `salty`咸 / `bland`淡 / `astringent`涩 |
| `MealTime` | `breakfast` / `lunch` / `dinner` / `snack` / `late_night` / `unknown` |
| `CookingMethod` | `raw` / `boiled` / `steamed` / `stir_fried` / `deep_fried` / `grilled` / `cold` / `pickled` / `unknown` |
| `Constitution`（九型） | `balanced`平和 / `qi_deficiency`气虚 / `yang_deficiency`阳虚 / `yin_deficiency`阴虚 / `phlegm_damp`痰湿 / `damp_heat`湿热 / `blood_stasis`血瘀 / `qi_stagnation`气郁 / `special_diathesis`特禀。**顺序与 GB/T 46939-2025 名录一致**，由 `tests/test_constitution_readiness.py` 断言枚举与 `constitution.json`、`docs/constitution-9-types.json` 三者一致 |
| `SOURCE_LABELS` | `rule`查表 / `composed`按烹饪方式推算 / `llm`模型推测 / `unresolved`无法判定 |

⚠️ **收录进枚举 ≠ 可以对用户开放**：能否对外服务由数据是否备齐派生，见 §5.6。

### 4.6 规则库与数据文件结构（只描述形状，数值以文件为真源）

| 文件 | 顶层结构 | 条目数 | 单条字段 |
|---|---|---|---|
| `core/data/food_properties.json` | `_meta` / `foods` / `tea_drinks` | 129 食材 + 18 茶饮 = **147** | `id, name, aliases, category, nature, flavors, keywords, reviewed, reviewed_by, reviewed_at, review_note, review_status`；另有派生字段 `variant_nature`、`nature_change_rules` 等 |
| `core/data/herbs.json` | `_meta` / `herbs` | **44 味** | `id, name, nature, flavors, meridians, effects, max_daily_g, cautions, suitable_constitutions, unsuitable_for, brewing, review_status, reviewed_by, reviewed_at, review_note` |
| `core/data/constitution.json` | `_meta` / `constitutions` | 9 型 | `id, label, one_line, signs, principles, direction, avoid` |
| `core/data/constitution_medication.json` | `_meta` / `constitutions` / `concurrent_principles` / `concurrent_constitutions` | 9 + 兼夹 | 单型：`id, label, clause, principle, common_drugs, recommended_formulas, adjustment_points, referral_note` |
| `core/data/diet_signals.json` | `_meta` / `signals` / `scene_rules` / `nature_keywords` / `dimensions` | 11 信号 + 4 场景规则 | 信号：`id, label, judge, arity, evidence, rule, note`；场景：`id, label, priority, match_natures, keywords, blend, title, reason` |
| `core/data/meal_plan_rules.json` | `_meta` / `trigger` / `order` / `directions` / `plan` | — | `trigger{impact_min, dampness_min}`；方向含 `when/unless/herbs/take/title_suffix/overrides_scene` |
| `core/data/food_medicine_catalog.json` | `_meta` / `batches` / `items` | 106 项 / 4 批次 | `name, full, paren, alternates, batch` |
| `core/data/herb_nature_reference.json` | `_meta` / `herbs` / `open_items` | 44 / 4 | `herb, project, bridge_note, pharmacopoeia, nature_match, flavors_match, meridians_match, differences, status, impact` |
| `core/data/herb_evidence_sources.json` | `_meta` / `property_entries` / `constitution_entries` | 44 / 24 | 属性：`id, name, project, evidence, status, delta, open_question`；体质：`constitution, herb_id, herb_name, source_id, matched_name, how, quote, level, review_status` |
| `docs/constitution-9-types.json` | `_meta` / `standard` / `sources` / `constitutions` / `open_items` | 国标元数据 + 5 来源 | `standard` 含 `code, name_zh, name_en, status, published_at, effective_at, questionnaire, threshold_note` 等 |

### 4.7 数据派生纪律（改数据前必读）

- ⚠️ **`docs/*.json` 不被运行时读取**；运行时真源是 `core/data/*.json` 本身（`docs/data-contracts.md:26`）。
- ⚠️ `herbs.json` 是 `indent=2` 但**数组按宽度折行**：`json.load` → `dumps` 回写会产生约 2400 行假 diff ⇒ 只能文本级精确替换。
- ⚠️ `herbs.json` 的 `_meta.constitution_extension.rulings` 的**读者是测试侧**（`core/tests/test_safety.py` 的 `load_rulings()`），**生产代码零引用**。
- ⚠️ `food_properties.json` 的 `ENTRY_FIXES` 是强制写入 ⇒ 改食物数据必须同步它，否则下次跑补丁脚本会覆盖手改内容。
- ⚠️ 批脚本会**把文案逐字写进 `herbs.json`** ⇒「文案即数据」，改脚本前先看它会写什么。
- ⚠️ 两份自查产物（`docs/catalog-compliance.md`、`docs/food-properties-review-sheet.md`）是**生成物，不要手工编辑**；`--strict` 模式在存在待办时会 exit 1。
- ⚠️ 口径陈述不写死数字（如"库内 N 味寒凉一律标阳虚不宜"）——N 每批都变，必然过期。

---

## 5. 安全约束

> 本章是 SPEC 的核心之一。总原则一句话：**模型会飘，护栏不能飘**——所有面向用户的推荐，都必须先过确定性检查，再由接口层返回（`safety.py:1-5`）。

### 5.1 硬规则总表（机器强制 vs 提示词约束）

| 约束 | 谁在强制 | 违反后果 |
|---|---|---|
| 高风险人群不给推荐 | **代码**（闸门①） | 命中即不调模型，返回就医引导 |
| 饮片必须来自白名单 | **代码**（候选集 + `check_blend`；白名单定义见 §5.3） | 候选集里挑不到；输出时该味被剔除 |
| 单味剂量上限 | **代码**（`check_blend` 自动裁剪 + 留痕） | 裁剪进 `adjusted`，写进 `guardrail_applied` |
| 总量与味数上限 | **代码**（超味数整组拒绝；超总量只警告 + 标记） | 见 §5.4 |
| 禁用表述 | **代码**（`scan_free_text`） | **整条推荐作废**，不留商量余地 |
| 体质不合（宜/不宜） | **代码**（`unsuitable_for` 硬剔除 + `suitable_constitutions` 排序） | 见 §5.6 |
| 须煎煮饮片不能用焖泡 | **代码**（`check_brew_adequacy` → 自动换 `COOK_BREW` + 留痕） | 自动改写并记进 `guardrail_applied`，不静默 |
| 不开方剂、不承诺疗效、不诊断、不虚构文献 | **提示词**（`agent2_system.md` "硬性边界"8 条） | 词面上有禁词表兜底，其余靠提示词 |
| 每味 3–10 克、只给 1–3 条、香气类后下 | **提示词** | 无代码校验（剂量上限由 §5.4 兜） |

### 5.2 高风险人群闸门 ✅

- **判据**：`HIGH_RISK_KEYWORDS` 共 **25 个**词，命中任一即触发（`safety.py:21-26`，判定函数 `safety.py:127`）。
  分组：孕产与经期（怀孕/孕妇/备孕/哺乳/喂奶/经期/月经）、儿童（小孩/孩子/儿童/婴儿/宝宝/幼儿）、重大情况（化疗/手术/糖尿病/高血压/心脏病/肾病/肝病）、用药与过敏（吃药/服药/中药/西药/过敏）。
- **行为**：不调用模型、不花一分钱；`recommendations=[]`；`basis.guardrail_applied` 写明"命中高风险关键词：…"；`meta.degraded=True` / `degraded_reason="high_risk_group"` / `key_source="not_used"`；`user_message` 引导咨询执业医师或药师（`orchestrator.py:218-248`）。
- **位置刻意**：在凭据校验**之前**——没填 Key 的用户说"我怀孕了"，应看到安全提示而不是"缺少 API Key"。
- **离线路径同样生效**：`/api/analyze-offline` 也用同一个 `detect_high_risk`，命中同样返回就医话术且不调模型（`core/app/api/analyze_offline.py:148-171`）。
- **对话入口同样生效**：`/api/chat` 先跑同一判据，命中即返回固定话术并标 `safety_intercepted=true`，此时不检查 Key、不调模型（`core/app/api/chat.py:94-105`）。
- ⚠️ **已知语义**：这是"用户自述"触发，不是"发物拦截"。README 亦说明：本项目**不做事前提醒**，不拦、不挡、不报警，所有输出都是"吃了之后怎么调"（详见 §8.1）。

### 5.3 饮片白名单与候选集收敛 ✅

- **白名单来源**：`core/data/herbs.json` 的 `herbs` 段，当前 **44 味**（实测 `len(load_herb_catalog()) == 44`）。加载于 `safety.py:81`，**文件不存在时返回空字典、不抛异常**（这是既有设计允许的降级路径）。
- **候选集收敛**：`filter_by_constitution(constitution, limit=12, avoid=())`（`safety.py:353`）：
  1. 先剔除 `unsuitable_for` 命中当前体质或屏蔽集中任一体质的饮片；
  2. 把标了 `suitable_constitutions` 的排在前面（**按 catalog 顺序**）；
  3. 其余作为中性兜底排在后面；
  4. 取前 12 味。
- **为什么这是安全措施**：模型即使想自由发挥，候选集里也只有药食同源饮片，**"无方可开"**。它与闸门④是两条独立防线，两条都做。
- **⚠️ `avoid` 只影响排除，不参与排序**——否则两份体质的契合度会混在一起，"方向唯一"这个前提就没了。
- **显式失败**：若某体质在 `suitable_constitutions` 里一条记录都没有，抛 `MissingConstitutionDataError`（`safety.py:63-74`、`:404-409`）而**不退化成未筛选清单**。理由：退化成"目录前 N 味"会让模型给出方向相反的搭配（例如阴虚质拿到温补辛温之品），而这种错误**从输出表面完全看不出来**，比直接报错危险得多。
- **白名单 vs 食药物质目录**：`docs/catalog-compliance.md` 记录了白名单与"既是食品又是中药材的物质目录（106 种）"的逐项核对与处置决定。其中一条重要口径：**目录只给合规身份、不含四气**，因此**不得作为体质适配依据**。

### 5.4 剂量与结构上限 ✅（`check_blend`，`safety.py:148-219`）

| 约束 | 阈值 | 处理方式 |
|---|---|---|
| 单次搭配味数 | `MAX_HERBS_PER_BLEND = 4`（`safety.py:42`） | **整组拒绝**（避免"君臣佐使"式处方结构） |
| 单味日用量 | `min(条目 max_daily_g, HARD_DOSE_CEILING_G = 30 g)`（`safety.py:36`、`:191-199`） | **自动裁剪到上限**并记入 `adjusted`、给出 warning（与"不静默改写"原则一致：改写必须留痕） |
| 单次搭配总量 | `TOTAL_DOSE_CEILING_G = 45 g`（`safety.py:39`、`:207-212`） | **只警告 + 标记 `adjusted`**（不裁剪） |
| 白名单外饮片 | — | 剔除该味并 blocked（`safety.py:180-182`） |
| 用户手动排除 | `exclude_herbs` | 剔除该味并 blocked（`safety.py:185-187`） |
| 饮片自身 `cautions` | — | **逐条转成 warning**（`safety.py:203-205`） |

调用方约定（`safety.py:156-158`）：**不要静默丢弃 blocked 内容**——要么剔除对应饮片后重算，要么整条推荐作废并走规则兜底；**绝不能把被拦的内容照原样返回给用户**。

### 5.5 禁用表述 ✅

- `FORBIDDEN_PHRASES` 共 **15 个**词：治疗、治愈、根治、药到病除、主治、疗效、疗程、处方、代替吃药、停药、包好、确诊、癌症、肿瘤、药方（`safety.py:29-33`）。
- 扫描对象：推荐的 `title`、`fit_reason`、`cautions` 拼成的文本（`orchestrator.py:162`；离线路径同样扫，`core/app/api/analyze_offline.py:179-190`）。
- 判定：命中即 `ok=False`，**整条推荐作废**（`orchestrator.py:163-167`）。
- 离线路径的处理略不同：命中者从结果中移除，并把 `user_message` 换成"部分推荐未通过安全检查，已从结果中移除。"（`core/app/api/analyze_offline.py:188-190`）。
- `/api/chat` 也扫模型输出，不合规则替换为固定文案。

### 5.6 体质适配 ✅

| 机制 | 判据 | 在哪生效 |
|---|---|---|
| **硬剔除**（方向收敛） | 饮片 `unsuitable_for` 命中当前体质或屏蔽集 | LLM 路径：候选集构造期（`safety.py:395-398`）；兜底路径：`matcher._herbs_unsuitable_for_any()`（`matcher.py:469-485`，在 `fallback_recommend` 里 `:511-524`） |
| **排序优先**（契合度） | 饮片 `suitable_constitutions` 命中当前体质 | 候选集排序（`safety.py:399-402`） |
| **只做提示**（不作废） | `check_constitution_fit()`：`unsuitable_for` 命中则追加一句"与你当前体质方向不完全契合，建议减量或更换" | 输出护栏（`orchestrator.py:170-176`、`safety.py:222-247`） |
| **可对外服务判据** | `ready_constitutions()`：至少 1 味饮片把该体质标进 `suitable_constitutions` | 启动/请求时闸门②（`safety.py:415-436`）、`/api/constitutions` 过滤 |

- **为什么"就绪"是派生的、不是手工开关**：这个条件恰好是 `filter_by_constitution` 不抛 `MissingConstitutionDataError` 的**充要条件**。手工 flag 会漂移——翻了开关却漏写数据，用户一点就是 500。派生则让"数据备齐"与"体质上线"成为同一件事。
- **当前实测**：`ready_constitutions()` 返回**全部 9 型**，所以网页体质下拉与终端都能选到九型；未就绪的体质会被闸门②以 422 `CONSTITUTION_NOT_READY` 明确拒绝，**刻意不回落平和质**（理由：阴虚与平和需要的是不同的饮片，降级没有有意义的答案）。
- **两条路径口径必须一致**（E4 的结论）：主导体质与兼夹体质在 LLM 路径与离线路径**都用同一份 `unsuitable_for` 判据硬剔除**。这在代码注释里被明确写成纪律，并由 `core/tests/test_constitution_integration.py` 钉死——否则同一个用户"有 Key / 没 Key"会拿到不同的安全边界，而界面只显示最终搭配，看不出差异来源。
- **兼夹体质（`avoid_constitutions`）**：只做排除，不改方向；`check_constitution_fit` 对主导体质与屏蔽集**同等看待**（输出层都是"提示"而非"剔除"，剔除发生在候选集/默认搭配阶段）。

### 5.7 冲泡方式适配（煎煮） ✅

- **数据标记**：饮片条目的 `brewing.requires_cooking`（`safety.py:261-269`）。判据读**数据标记**而不是现场猜文本——标记与其依据（`brewing.note` 原文）放在同一个对象里，改的时候看得见理由。另有派生不变式 `cook_required_without_basis()`（`safety.py:272-288`）：标记了 `requires_cooking` 却在自己的 `brewing` 文本里找不到"煮/煎/炖"依据的条目会被检查出来。
- **什么叫"算煎煮"**：`brew_is_cook_style()` 要求**三条同时满足**——水温到 100、焖煮不少于 20 分钟、器具有煮的条件（器皿名含"壶"或"锅"）（`safety.py:313-327`）。只看时长不看器具会漏判"保温杯焖 30 分钟"，那依然出不了味。
- **发现后的处理**：`check_brew_adequacy()`（`safety.py:330-350`）只负责**发现与措辞**；`orchestrator` 把 `rec.brew` 换成 `matcher.COOK_BREW`，并把"冲泡方式已调整为煎煮：…"记进 `guardrail_applied`（`orchestrator.py:181-185`）。
- **为什么 safety 不直接换**：否则 safety 要反向依赖 matcher，形成循环导入（注释明写）。
- ⚠️ **关键词刻意不含"熬"**：它会命中麦冬、桑椹的"适合熬夜后口干"，把两味明显不必煎煮的饮片误判进来（`safety.py:253-255`）。

### 5.8 审核状态与"未验证"标注 ✅

- 三态而非布尔（`reviewed: false` 无法区分"还没审"与"审了但不认可"）：

| 状态 | 效果 |
|---|---|
| `approved` | 真·硬规则库：置信度 0.9，界面**不**标注 |
| `pending` | 置信度 0.9，但界面**必须**标注"待验证" |
| `rejected` | 降为组合推理档（0.6），不再作硬规则 |

- **当前实际状态**：`food_properties.json` 全部 147 条与 `herbs.json` 均为 `pending` ⇒ 界面会**普遍**显示"待验证"标记。这是刻意的：标记密度就是审核进度的可见反馈。**不要为了界面好看而批量置为 `approved`**（`README.md:352-353`）。
- 与安全的关系：**收录 ≠ 已审核**；属性依据中医饮食养生通行表述整理（食物偏性，非药物功效），**对外提供任何形式的服务前，必须由具备资质的中医师/中药师复核**（`README.md:9-11`）。

### 5.9 凭据、日志与网络边界 ✅

| 规则 | 实现 |
|---|---|
| **不存在服务端内置 Key** | `config.py` 不读取任何 API Key（`config.py:19-27`）；"服务端兜底 Key"已从代码中彻底移除。Key 只有两个来源：网页 `Authorization` 头、终端/脚本的环境变量 `DEEPSEEK_API_KEY`（`config.py:119-129`） |
| Key 逐请求传递 | `core/app/api/auth.py:28` 解析 Bearer（大小写不敏感、内部不允许空白、长度 > 256 视为无效）；格式不对**返回 None 而不抛异常**——宁可回明确的"请填 Key"，也不要给用户一个难懂的 500 |
| **Key 绝不进日志/响应/异常** | `core/app/api/auth.py:9-14` 写成硬规则；`core/app/api/analyze.py:9-13` 声明本文件不记录 Authorization 头、异常 message 只来自 `AnalyzeError`；`core/app/api/analyze.py:56` 注释要求 detail 里不放 key。由 `tests/test_key_handling.py` 的 sentinel 串测试守着 |
| 不支持时明确报错，不静默换 Key | `TA_BACKEND=dsh` 时返回 400 `USER_KEY_UNSUPPORTED`（`orchestrator.py:259-265`）——静默复用别人的 Key 会让用户以为费用记在自己账上 |
| CORS 只放行本机 | `main.py:99-108` 只允许 `http://127.0.0.1:<port>` 与 `http://localhost:<port>`，并注明**不要改回通配**（那会让局域网内任意网页调用你本机的接口） |
| 前端 Key 默认不记住 | 默认存 `sessionStorage`（仅当前标签页）；勾选后才写 `localStorage`；主界面不回显 Key 任何部分 |
| 数据不出本地 | 饮食记录只在浏览器本地；无账户、无数据库、无上传 |

### 5.10 数据缺失时的失败策略 ✅

策略**按后果分级**，不是一刀切"都降级"或"都报错"：

| 缺失对象 | 策略 | 锚点 |
|---|---|---|
| `herbs.json` 整体缺失 | 白名单为空 → `filter_by_constitution` 返回 `[]`、`ready_constitutions()` 返回空集（既有设计允许的降级路径） | `safety.py:386-389`、`:426-430` |
| 某体质在 `suitable_constitutions` 里为空 | **显式失败** `MissingConstitutionDataError` | `safety.py:404-409` |
| `food_properties.json` 缺失 | 返回空表，判定整体落到第三层（模型推测/无法判定） | `food_lookup.py:72-77` |
| `herb_evidence_sources.json` 缺失 | 返回空字典——**依据链是增强项，缺了推荐链路必须照常工作，不能因此 500** | `safety.py:105-115` |
| `diet_signals.json` 的 `scene_rules` 缺失 | `MissingSceneRulesError`，**导入期就炸**（不是某个请求里静默降级） | `diet_signals.py:117`、`matcher.py:66` |
| `meal_plan_rules.json` 缺失 | 派生返回 `None`，调用方走老路 | `diet_signals.py:523` |
| `constitution_medication.json` 结构不合法 | **显式失败** `MedicationReferenceError`（宁可失败，也不要看起来能用） | `medication_reference.py:65-71` |

### 5.11 与推荐链路硬隔离的模块 ✅

`core/app/services/medication_reference.py`（用药调理资料）有一条明确的隔离契约：**不收录标准正文、不计算剂量、不做体质匹配推荐、不生成搭配**；`describe_profile()` 刻意不含剂量字段；`safety.py`、`food_lookup.py`、`matcher.py`、`orchestrator.py`、两个提示词文件**一律不得** import 或读取它；`constitution_medication.json` 不是 `herbs.json` 的来源、不可互相同步；免责声明必须原样展示、不得裁剪。以上由 `tests/test_medication_reference.py` 守卫。

### 5.12 安全层的不变量（写进注释的契约）

1. 被拦的内容**绝不原样返回**给用户（纪律写在 `safety.py:156-158`；落点在 `core/app/services/orchestrator.py:153-159`——拦即剔除、剔空即整条作废）。
2. 全部被拦 → 整条作废并走规则兜底，**而不是抛异常变成 500**（`orchestrator.py:338-347`）。
3. 自动改写必须**留痕**：剂量裁剪记 `adjusted`，冲泡改写记 `guardrail_applied`——项目原则是"不静默改写"，不是"不许改写"。
4. `basis.references` 由**本次真正留下的推荐**决定，**不看 Agent 原始输出**——被护栏拦掉的饮片不该出现在公开依据里（`orchestrator.py:113-117`）。
5. 护栏调用**不能因为"我们相信兜底函数"就跳过**：跳过等于把这个不变量降级成一句约定（`docs/analyze-offline-plan.md:133`）。

---

## 6. 分层可信度

> 本章回答："同一个属性，凭什么说它可信？"核心是**判定权在表和规则手里，模型只作第三层兜底，且它的推测会被标记、被隔离、不许参与计算**。

### 6.1 三层总览（置信度递减，来源可追溯）

| 层 | 来源 | 置信度 | 生效条件 |
|---|---|---|---|
| 第一层 硬规则库 | `food_properties.json` 规范名**精确命中** | **0.9** | 名称与规范名相同 ⇒ 表值即权威，**不叠加**模型给的烹饪修正 |
| 第一层附 食材变体层 | 条目自带的 `variant_nature`（如"红薯→烤红薯"） | 0.9 | 查表直取，**优先于**通用烹饪修正 |
| 第二层 组合推理（烹饪修正） | 纯规则 ±1：冰镇 −1；煎炸 +1；烧烤 +1；辛辣 +1；蒸煮/炒/生/腌 0 | **0.6** | **仅当名称未精确命中**表内规范名时生效 |
| 第二层附 温度前缀层 | 「冰啤酒」「热牛奶」里的冰/热，用**纯字符串规则**识别 | 0.6 | 剥掉前缀后必须是完整表内食物名才生效 |
| 第三层 LLM 推测 | 表里没有 → 保留模型判断但标记未验证 | **0.3** | 表未命中且模型给了非 unknown 的值 |
| 无法判定 | 表未命中且模型也没给 | **0.1** | 前端**不显示**寒热属性（数据仍返回） |

**编码细节**（`nature_math.py:30-48`）：寒 −2 / 凉 −1 / 平 0 / 温 +1 / 热 +2；溢出夹取（性热的羊肉再油炸仍是热，`clamp` 到 +2）；**`unknown` 没有值（返回 `None`），不是 0**——否则"未判定"会被当成平性参与运算。

**两层修正的顺序不可颠倒**（`nature_math.py:1-28`、`docs/three-layer-architecture.md:56-65`）：变体层在前、通用烹饪修正层在后。原因：表里精确的变体值会被通用规则破坏；而"精确命中"要比较**名称整体**而不是命中词——`炸馒头` 靠关键词、`冰啤酒` 靠包含关系识别，它们的名称与规范名不同，属于"带烹饪信息的派生名称"，应当让烹饪层生效；而 `希腊酸奶` 名称与规范名完全相同，表值即权威。

**合成算法**（`combine()`，`nature_math.py:356`）：取绝对值最大者为主导项；同向项累加、封顶 ±2；**反向项只做 50% 抵消、不翻转主导方向**；平性既不贡献方向也不稀释（加米饭不会把凉性拉平）；并列时取先出现的（保证同样输入结果稳定）；烹饪修正最后叠加。
⚠️ **实测：`combine()` 在 `core/app/` 下只有定义、没有调用点**——多层食材合成**未接入主流程**（完整边界见 §8.2）。

**寒热错杂**（`detect_nature_conflict()`，`nature_math.py:435`，阈值 `CONFLICT_THRESHOLD = 2`）只报状态、不做加法：≥ +2 入 `heat_side`，≤ −2 入 `cold_side`，两侧都非空即 `conflict=true`。它的结果**原样**进入 `MealConflict`，组装层不得另判一套。

### 6.2 温度前缀层（为什么单独做一层）

**动机**：模型给的 `cooking` 无法区分"可靠证据"与"猜测"——它会给出"希腊酸奶 = cold""火腿三明治 = grilled"这类没有依据的值；而"冰啤酒""热牛奶"里的冰/热本身就在名字里，是字符串层面的确定信号（`docs/three-layer-architecture.md:82-86`）。

| 维度 | 现状 |
|---|---|
| **唯一入口** | `nature_math.resolve_temperature(name, note)`（`nature_math.py:259`）。新增前缀只改一处（`CHILL_PREFIXES`/`HEAT_PREFIXES`，`:116`/`:122`），解析层与提示词层都通过它拿结论 |
| 前缀表 | 降温 14 项（冰镇的/冰镇/冰的/冰/加冰的/加冰/去冰的/去冰/冷冻的/冷冻/冷藏的/冷藏/冻的/冻）命中 −1；升温 12 项（热腾腾的/热腾腾/滚烫的/滚烫/烫的/烫/加热的/加热/温热的/温热/热的/热）命中 +1。均**最长优先** |
| 双通道扫描 | **食物名只认开头**（避免"冰淇淋/凉皮/热狗"被误判）；**备注在任意位置查找**（实测模型会输出 `note=去冰`）。优先级：**食物名 > 备注** |
| 备注通道长度闸 | `NOTE_MAX_LEN = 10`（`nature_math.py:256`）——备注过长则不启用该通道 |
| **准入条件（本层最关键的安全边界）** | 温度来自食物名时，**剥掉前缀后剩下的词必须是完整表内食物名**：`food_lookup.resolve_temperature_fields()`（`food_lookup.py:173`）+ `_is_full_entry_name()`（`:217`，只认恰好等于某条目的规范名或别名） |
| 实际效果举例 | 冰啤酒→寒 ✓；热牛奶→温 ✓；**冰红茶→平**（红茶本温，冰 −1）✓；冰淇淋→**不叠加**（"淇淋"不是表内条目）✓；热狗→落到表外走 LLM 层 ✓；热干面→靠关键词命中"面条"，**不升温** ✓ |
| 与表内变体协同 | 模型对同一道菜命名不稳定（`name=去冰奶茶` / `name=奶茶,note=去冰` / `name=冰奶茶`）。前两种由温度层覆盖，第三种名字不在表内会落到 LLM ⇒ 因此常见温度变体也**直接收录进表**，两层互为兜底 |
| 历史教训 | 提示词层曾自己用子串匹配（`"冰" in text`）、解析层用前缀匹配，两套逻辑漂移——"冰淇淋"在解析层被正确排除、在提示词层却被当成冰镇。现已统一到唯一入口 |

### 6.3 三层判定的执行顺序（`resolve_food`）

输入：模型给的食物名 `name` + `cooking` + `note` + `llm_nature` + `text_hint`（`food_lookup.py:310-316`）。顺序如下（**这个顺序是契约，不可随意改**）：

1. **温度前缀层最先做**（`:328-352`）：先剥前缀再查表；剥离后查不到且确有过温度信号时，用原名再查一次。
2. **未命中表**：模型给了非 unknown 的值 → `source=llm` / 0.3；否则 → `source=unresolved` / 0.1（`:363`、`:374`）。
3. **命中表 → 变体层**：该条目对当前烹饪方式有 `variant_nature` → 直取变体值（`:380-404`）。
4. **精确命中**（名称整体等于规范名，`:393`）→ 查表直取，**不叠加通用烹饪修正**（`:406-410`）。
5. **烹饪修正层**：由别名/关键词识别或名称不同的情况走 `nature_math.apply_cooking_fallback()`；但**存在温度信号时跳过该层**，避免同一个"冰"算两遍（`:412-432`）。
6. **温度层最后叠加**：`shift_nature(nature, temp_delta)`，成功则 `source=composed` 并写入"（温度前缀由…识别，纯规则判定，不经模型）"（`:434-450`）。

### 6.4 置信度与审核三态

常量（`food_lookup.py:41-45`）：`CONF_RULE=0.9`、`CONF_COMPOSED=0.6`、`CONF_LLM=0.3`、`CONF_UNRESOLVED=0.1`、`CONF_SHOW_THRESHOLD=0.3`。

最终档位由 `review_status` 三态与来源共同决定（`food_lookup.py:452-471`）：

| 审核态 | 来源 | 最终置信度 | 是否标注 |
|---|---|---|---|
| `approved` | 表命中 | 0.9 | 不标注 |
| `pending` | 表命中、未走修正层 | 0.9 | **标"待验证"** |
| `pending` | 表命中、走了修正层 | 0.6 | 标"待验证" |
| `rejected` | 表命中 | 0.6 + "（该条目审核未通过，仅供参考）" | 标"待验证" |
| — | 模型推测 | 0.3 | 标"待验证" |
| — | 无法判定 | 0.1 | 标"待验证" + **不显示寒热属性** |

**整餐把握度** = 逐项置信度的算术平均（`agent1_diet.py:119-122`），**不再采信模型自报的 `confidence`**。

**显示阈值**：`CONF_SHOW_THRESHOLD = 0.3`，低于它前端不显示寒热属性（数据仍在，只是不呈现）。

### 6.5 优先级：硬规则 > 组合规则 > 模型推测（覆盖链）

这是"分层可信度"真正落地的地方——**不是并列展示，而是谁覆盖谁**：

| # | 步骤 | 行为 | 锚点 |
|---|---|---|---|
| 1 | **参考表先注入提示词** | 命中表的条目渲染成"必须原样采用表中的值，即使你的判断不同也以表为准" | `agent1_diet.py:53-59`；提示词 `agent1_system.md:9` |
| 2 | **解析后按表覆盖模型值** | 仅当判定来源是 `rule` 或 `composed` 时才覆盖 `nature`、`flavors` | `agent1_diet.py:112-117` |
| 3 | **把握度重算** | 用逐项置信度均值覆盖模型自报值 | `agent1_diet.py:119-122` |
| 4 | **代码派生口径压过模型自由发挥** | 信号由 `build_meal_signals()` 算，优先级由 `derive_meal_plan()` 算，**不是模型自拍** | `diet_signals.py:441`、`:595`；`orchestrator.py:303-305` |
| 5 | **兜底选方的优先级链 L0–L4** | 见 §6.6 | `matcher.py:362` |
| 6 | **模型输出仍要过确定性护栏** | 白名单/剂量/禁词/体质/冲泡 | `orchestrator.py:129-189` |
| 7 | **公开依据只认登记过的来源** | 悬空来源不展示——"宁可少给一条依据，也不给用户一个没登记过的出处" | `safety.py:474-478`、`:442-514` |

**校准失败不阻断整体**：逐项 `resolve_food()` 出错时只记 error 日志并保留模型判断（`agent1_diet.py:106-109`），不让单点异常把整次解析打掉。
⚠️ 同时注意一处**刻意的"不覆盖"**：`text_hint` 只取**该食物自己**的名字与备注，绝不用整句口述——历史上传整句导致跨食材串味（"中午吃了碗兰州拉面，还喝了杯麻辣烫"里的"辣"会把兰州拉面判成温）。离线路径同理，改用按位置归属的 `resolve_in_context()`（`food_lookup.py:553`），修掉了"炸鸡 冰可乐"里炸鸡被判成寒的 bug。

### 6.6 组合规则（第二层）的完整优先级

信号层是**纯代码判定**，与模型无关：

| 信号 | 计分 | 阈值与档位 |
|---|---|---|
| **冲击度** `impact` | 信号各 +1（iced/frozen/fried/greasy/spicy/carbonated/alcohol/temp_shock），聚合方式 `sum_per_item_then_max` | `cap=3`：0–1 → `none`；2 → `protect_stomach`；3+ → `protect_stomach_plus` |
| **湿气度** `dampness` | 信号各 +1（high_sugar/greasy/fried/cold_raw/iced/dairy），聚合方式 `sum` | `cap=3`：0–1 → `none`；2 → `damp_clear`；3+ → `damp_clear_plus` |
| **寒热错杂** `conflict` | 不加分数，只报状态 | 两侧同时存在偏热与偏寒条目即为真 |

阈值与中文标签**全部从数据文件读**（`diet_signals.json` 的 `dimensions` 与 `meal_plan_rules.json` 的 `trigger`：`impact_min=2`、`dampness_min=2`），代码不写死。
⚠️ **`core/data/diet_signals.json`** 的 `_meta.unexecutable_thresholds` 如实记录了两条**当前不可执行**的口径（湿气·高糖原述"每份总糖 ≥ 15 g"、湿气·油腻原述"每 100 g 脂肪 ≥ 20 g"），因为食性表没有糖量与脂肪字段——该键只在 `diet_signals.json` 里，`meal_plan_rules.json` 的 `_meta` 没有它。这是**已知缺口，不是隐藏缺陷**。

**餐单派生** `derive_meal_plan()`（`diet_signals.py:595`）：

| 环节 | 现状 |
|---|---|
| 触发 | 三项任一：冲击度 ≥ 2、湿气度 ≥ 2、寒热错杂为真。三项全假 ⇒ 返回 `None`（本次没有方向接管，调用方走老路） |
| 方向顺序 | `["stomach_guard"（先护脾胃，可压过场景规则）, "damp_clear"（兼顾化湿，不可压过）]` |
| 可用饮片 | **方向饮片子集 ∩ 候选集**（`filter_by_constitution`）；**不足 `take`（2 味）即整方向关闭**，不退化成"取到几味算几味" |
| 空结果处理 | 方向关闭时返回**非空**的 `MealPlan`（`first=None`）并在 `note` 里如实说明；正常返回 `None` 表示未触发 |
| `stomach_guard` | 当前 `herbs=[]` ⇒ **恒关闭**（口径⑥的落法），关闭时给出照实说明 |
| 数据不齐 | 抛 `MissingConstitutionDataError` 时**不吞**：返回 `data_missing=true` 的 `MealPlan` 并给出说明 |
| 第二段 | 恒为"体质方向"且 `deferred=true` ⇒ `open=false`；**推迟话术来自数据文件**，壳与提示词都不自己写 |

**兜底选方的 L0–L4**（`matcher._choose_blend()`，`matcher.py:362`）：

| 级别 | 条件 | 结果 |
|---|---|---|
| L0 | `parsed.signals` 为 `None`（未计算） | 逐字节保持老行为：先场景规则（`_pick_rule`），否则体质默认搭配 |
| — | **方向可压过场景**（`overrides_scene=true`，当前仅"先护脾胃"） | 直接用该方向 |
| L1 | **寒热错杂为真** | **不对冲**：只在"有关键词命中且非对冲"的场景规则里选；没有可保留的 ⇒ 退体质默认（`conflict_no_counter`） |
| L2/L3 | 场景规则命中（要求有关键词命中，"夜宵"这类空关键词兜底不算场景结论） | 用规则搭配；否则方向接管 |
| L4 | 湿气触发但方向不可用 | 退体质默认（`damp_clear_closed`），**不走"夜宵和胃"那种兜底顶上** |
| 其余 | 冲击度触发而护脾胃未开放 | 走老路 + 如实说明（`stomach_guard_closed`）——**仍给搭配，不静默替换** |

**4 条场景规则的实际取值**（`core/data/diet_signals.json` 的 `scene_rules` 段，2026-09-21 实测）：

| id | priority | 关键词 | 搭配 | 茶饮名 | `match_natures` |
|---|---|---|---|---|---|
| `greasy` | 3 | 麻辣 / 炸 / 烤 / 烧烤 / 油 / 红烧 / 火锅 / 肉 / 肥 / 奶油 | 陈皮 5 + 山楂 6 | 陈皮山楂消食饮 | warm, hot |
| `cold_intake` | 2 | 冰 / 冷 / 凉 / 雪糕 / 冰淇淋 / 生鱼 / 刺身 / 沙拉 / 冷饮 | 生姜 5 + 红枣 6 | 生姜红枣温中饮 | cool, cold |
| `spicy` | 2 | 辣 / 麻辣 / 椒 / 烧烤 / 孜然 | 麦冬 6 + 罗汉果 3 | 麦冬罗汉果润喉饮 | hot |
| `late_night` | 1 | **（空元组）** | 陈皮 4 + 茯苓 6 | 陈皮茯苓和胃饮 | unknown |

⚠️ `late_night` 的 `keywords` 是**空元组**，只能靠 `match_natures={unknown}` 拿 1 分 ⇒ 所以 `_scene_rule_ids()` 额外要求"必须有关键词命中"，否则非夜宵的一餐会被它说成"夜里吃得多"（D31）。

**化湿方向的可用饮片**（`meal_plan_rules.json`，实测）：茯苓 6 / 陈皮 4 / 荷叶 5 / 薏苡仁 10 / 白扁豆 10 / 赤小豆 10 —— 实际取「这 6 味 ∩ 候选集」按方向顺序的前 `take=2` 味。

**"不对冲"的判据**（`_is_counter_rule()`，`matcher.py:297`）：搭配**整体**偏一侧、而这一餐的对侧非空 ⇒ 判为对冲。混合寒热的搭配不算。这条规则由提示词与代码**双写**：提示词要求"不要刻意对冲"，代码在 L1 直接排除对冲型规则——因为"没 Key 的用户走的还是被否掉的旧口径"会造成同一用户"有 Key / 没 Key 拿到相反的推荐方向"。

### 6.7 模型侧的隔离：未验证项不许参与计算

`agent2_recommend._build_unverified_section()`（`agent2_recommend.py:90`，在 `:184` 接入提示词）：

- 筛选出 `verification.unverified` 为真的食物；**为空则整节不出现**（不制造噪音）。
- 标题即约束：**"以下食物的食性未经验证（不得作为搭配计算依据）"**。
- 原因映射：模型推测 / 无法判定 / "表内条目尚未人工审核"；若置信度低于显示阈值，再补一句"低于阈值，不予采信"。
- 约束原文：不得据此选择饮片、计算用量或改变搭配方向；若推荐与该食物直接相关，**必须**在 `fit_reason` 或 `cautions` 注明「此项食性未经验证」。
- 这是**提示词层**的隔离；而白名单是**构造期**的硬隔离（候选集里根本没有被屏蔽项）。两者是不同强度的两道。

### 6.8 出口与显示约定

| 出口 | 内容 | 锚点 |
|---|---|---|
| `Verification` 四字段 | `source` / `confidence` / `unverified` / `detail`（判定过程，便于排查与审计） | `models.py:49` |
| 来源中文标签 | 查表 / 按烹饪方式推算 / 模型推测 / 无法判定 | `enums.py:129` |
| 阈值下发 | `/api/meta` 下发 `conf_show_threshold` 与全部标签，**各壳不要硬编码** | `main.py:173-195` |
| 网页壳 | 按阈值与来源决定是否显示寒热属性、是否标"待验证" | `ui/web/index.html:318`、`:513`、`:529` |
| 终端壳 | 与网页同一规则（`confidence >= CONF_SHOW_THRESHOLD` 才显示，否则"未判定"） | `ui/terminal/chat.py:106-108` |
| Agent2 引用阈值 | 用于判断"低于阈值，不予采信"的措辞 | `agent2_recommend.py:26`、`:111` |

**✅ 已确认**：`CONF_SHOW_THRESHOLD` 的引用点就是上表这 6 处 —— `agent2_recommend.py:26/111`、`food_lookup.py:45`、终端 `chat.py:68/106/108`、网页 `index.html:318/513/529`。**网页壳是通过 `/api/meta` 间接使用，没有硬编码该数值**，与"各壳不要各自硬编码"的设计一致。

### 6.9 当前档位实际状态（一句话总结）

判定的**权威性**不在模型手里：表命中就覆盖模型、模型只在表外作第三层、它的推测会被标注、被隔离、且**不得作为任何计算的依据**；而"表本身"当前**全部是 `pending`**，因此界面上会普遍出现"待验证"——**这不是 bug，是审核进度的可见反馈**。

---

## 7. 降级路径

### 7.0 口径、总数与总表

**"降级"的定义**（本文件统一口径）：**请求仍返回 200，系统给出结果或明确话术，只是能力/来源降了一档**（`meta.degraded=True` 或等价行为）。

按此口径，**服务端共 9 条降级出口**，全部列在下表；编号是全文件通用的（§7.1–§7.3 只展开各自那一组的细节，**不再重复计数**）。

| # | 组 | 触发条件 | 去处与标注 | 锚点 |
|---|---|---|---|---|
| **1** | 主链路 | 命中高风险关键词 | 空推荐 + 引导就医；`degraded_reason="high_risk_group"` | `orchestrator.py:218` → `:224-248` |
| **2** | 主链路 | Agent2 抛异常，或返回空推荐 | 转 `matcher.fallback_recommend`；`degraded_reason=str(exc)[:200]` | 触发 `:315-323`；兜底 `:324-330` |
| **3** | 主链路 | 输出护栏把推荐全拦掉（且此前未降级过） | 再兜底一次 → 再过一遍护栏；`degraded_reason="guardrail_removed_all"` | `orchestrator.py:338-347` |
| **4** | 兜底函数 | `exclude_herbs` 正好覆盖整组搭配 | 空推荐 + 专用话术 | `matcher.py:518-520` |
| **5** | 兜底函数 | 体质（含兼夹）硬剔除把整组剔空 | 先退平和质通用搭配并照实归因；通用也空 ⇒ 空推荐 + 专用话术 | `matcher.py:523-553`、空出口 `:537-538` |
| **6** | 兜底函数 | 搭配里的饮片全不在白名单 | 空推荐 + "候选饮片不可用，请检查 herbs.json。" | `matcher.py:557-559` |
| **7** | 离线路径 | 输入为空 | `degraded_reason="输入为空"` + "请先说说你吃了什么。" | `core/app/api/analyze_offline.py:87-103` |
| **8** | 离线路径 | 命中高风险关键词 | 200 + `"高风险拦截"` + 就医话术；不调用模型 | `core/app/api/analyze_offline.py:148-171` |
| **9** | 离线路径 | 用户主动选择的正常离线模式 | `degraded_reason="离线模式：不调用模型"`；`backend="offline"` | `core/app/api/analyze_offline.py:192-213` |

必须与这 9 条分开看待的还有四类（均在本章内展开）：**再降一级但仍有推荐**（§7.2 末）、**降级链的尽头（唯一 500 点）**（§7.4）、**刻意不降级的硬失败 5 条**（§7.5）、**看起来像降级但实际不是的 3 类**（§7.6）。

### 7.1 主链路（上表 #1–#3，`orchestrator.analyze()`）

| # | 行为与标注 | 锚点 |
|---|---|---|
| **1** | `recommendations=[]`；`parsed` 只保留 `meal_time` 与一句 summary；`basis.guardrail_applied=["命中高风险关键词：…"]`；`degraded=True` / `key_source="not_used"`；`user_message` 引导就医。语义见 §7.6 B 与 §5.2 | 判定 `orchestrator.py:218`；返回 `:224-248`；标注 `:237-238` |
| **2** | `rule_hits` 一并带出；`degraded=True` | 空推荐在 `:322-323` 转成异常；兜底 `:324-330` |
| **3** | 兜底后再**过一遍护栏**，两次的 `guardrail_applied` 合并 | `orchestrator.py:338-347` |

> 这三条出口的行为断言由 `core/tests/test_degradation_paths.py` 正面守护：高风险不调模型且无需 Key（`:86-100`）、Agent2 失败降级仍给非空搭配（`:103-122`）、护栏清空后 `degraded_reason="guardrail_removed_all"` 并留痕（`:125-150`）。

### 7.2 兜底函数内部的空出口（上表 #4–#6，`matcher.fallback_recommend()`）

兜底函数的契约是**"永远给出合法且安全的搭配"**（`matcher.py:495-509`）。但有些情况连它也給不出，于是返回**空推荐 + 专用话术**（仍 200，不是 500）：

| # | 触发条件 | 行为 | 锚点 |
|---|---|---|---|
| **4** | `exclude_herbs` 正好覆盖整组搭配 | "你排除的饮片正好是这组搭配的全部，换一组或去掉排除项再试试。" | `matcher.py:518-520` |
| **5** | 体质（含兼夹）硬剔除把整组剔空 | 先退到平和质通用搭配并**照实归因**（主导体质剔的 / 兼夹剔的 / 两者都有，分别记 `constitution_cleared_blend`、`avoid_cleared_blend`）；若通用兜底也被剔空 ⇒ "按你的体质（含兼夹体质）筛下来没有可用饮片，请换个说法或咨询医师。" | 剔除 `:523-524`；退通用并归因 `:526-553`；空出口 `:537-538` |
| **6** | 搭配里的饮片全不在白名单（`_make_herbs` 全部跳过） | "候选饮片不可用，请检查 herbs.json。" | `matcher.py:557-559`；`_make_herbs` 定义 `:208-226` |

**再降一级但仍有推荐（不属上面三条空出口）**：`_constitution_default()` 遇到未收录的体质时，**不退化成 `KeyError`**，而是退到 `GENERIC_FALLBACK_KEY="balanced"`，并在理由里写明"该体质的专属搭配尚未收录，已改用平和质的通用搭配"（`matcher.py:247-263`）。它当前收录**全部 9 型**默认搭配（`matcher.py:69-119`），所以这条分支现在是纵深防御。

**兜底路径顺带会做的两件事**（都在 `fallback_recommend` 内）：含须煎煮饮片时把冲泡换成 `COOK_BREW` 并记 `brew_cook_required`（`:571-578`）；`fit_reason` 追加"（此建议来自规则匹配）"及其它如实说明（`:580-585`）。

### 7.3 离线路径（上表 #7–#9，`/api/analyze-offline`）

| # | 标注 | 锚点 |
|---|---|---|
| **7** | `degraded=True` / `key_source="not_used"` / `backend="offline"` / `model="offline-rules"` | `core/app/api/analyze_offline.py:87-103`（标注 `:97-98`） |
| **8** | `guardrail_applied` 写明命中词 | `core/app/api/analyze_offline.py:148-171`（标注 `:165-166`） |
| **9** | 用户主动选的正常模式，语义见 §7.6 C | `core/app/api/analyze_offline.py:192-213`（标注 `:209-210`） |

离线路径另有两条**不是降级**的出口：文案安全检查不过 → 移除该条并把 message 换成"部分推荐未通过安全检查，已从结果中移除。"（`:179-190`）；体质未就绪 → **422** `CONSTITUTION_NOT_READY`（`:78-85`）。

### 7.4 降级链的尽头：唯一的 500 点

`matcher._constitution_default()` 里，若连 `GENERIC_FALLBACK_KEY="balanced"` 都缺失，会 `raise RuntimeError`（`matcher.py:253-257`，代码标注 `pragma: no cover - 数据表被改坏才会走到`）。它处在 #2 的 `except` 分支内被调用，异常会冒出 `analyze()` → `core/app/api/analyze.py:62-67` → **500 `INTERNAL_ERROR`**。

这是全链路**唯一**会因为"数据表被改坏"而变成 500 的点；其余所有"给不出搭配"的情况都被设计成上面 §7.2 的空出口话术。

### 7.5 刻意不降级的硬失败（5 条）

这五条**不降级、不兜底**，直接报错并给出可操作提示——因为降级会给出**没有意义的答案**：

| 错误码 | 触发条件 | HTTP | 锚点 |
|---|---|---|---|
| `NO_API_KEY` | 没带可用 Key（本项目无服务端兜底 Key） | 400 | `orchestrator.py:257-258`；文案 `config.py:97-111` |
| `USER_KEY_UNSUPPORTED` | `TA_BACKEND=dsh`（Key 与子进程绑定，无法逐请求换） | 400 | `orchestrator.py:259-265` |
| `API_KEY_REJECTED` | 模型服务方拒绝凭据（401/402/403） | 400 | `orchestrator.py:272-276`；映射 `direct_api.py:218-235` |
| `AGENT1_FAILED` | Agent1 其它异常，**含 JSON 解析失败** | 422 | `orchestrator.py:277-281` |
| `CONSTITUTION_NOT_READY` | 主导体质或屏蔽集里某型数据未备齐 | 422 | `orchestrator.py:62-96`、`:253`；离线侧 `core/app/api/analyze_offline.py:78-85` |

HTTP 分档规则：`{NO_API_KEY, USER_KEY_UNSUPPORTED, API_KEY_REJECTED}` → **400**（配置/凭据问题，换个说法重试没用）；其余 `AnalyzeError` → **422**；未预期异常 → **500**（`core/app/api/analyze.py:32`、`:57`、`:62-67`）。

**为什么这些不降级**（代码注释的理由，值得原样保留）：
- 体质未就绪：项目讲的"降级而非失败"针对的是**基础设施故障**（没 Key、模型挂、JSON 失败），那些情况下降级还能给出有用的东西；而阴虚与平和**需要的是不同的饮片**，降级没有有意义的答案，只能显式拒绝。回落平和质等于"用平和质的答案冒充阴虚质的答案"。
- Key 类错误：不是"没看懂你吃了什么"，必须回一个让人去改 Key 的错误码，前端据此把焦点移到 Key 输入框。

### 7.6 看起来像降级、实际不是（三类）

这三类最容易在排障时被误判，因此单列（`degraded=True` **不等于故障**，字段语义见 §7.8）：

| # | 现象 | 为什么不是降级 | 锚点 |
|---|---|---|---|
| **A** | **一个食物都没认出来**：`recommendations=[]` + "没太看明白你吃了什么…" | `degraded` **保持 `False`**——这是**正常结果**，不是降级。Agent1 正常跑完了，只是没识别到食物 | `orchestrator.py:284-299` |
| **B** | **高风险分支**：`degraded=True` / `degraded_reason="high_risk_group"` | 这是"**刻意不调用模型**"的正常分支，不是故障 | `orchestrator.py:224-248` |
| **C** | **离线模式**：`degraded=True` / `"离线模式：不调用模型"` | 它是用户**主动选的正常模式**，没有任何东西"降级"了。⚠️ 语义与主链路**相反**：同一个兜底函数在主链路里 `degraded=True` 意味着"出问题了"，在离线路径里是"本来就这样" | `core/app/api/analyze_offline.py:192-213` |

> 📌 与之相关的**文档滞后**见 §9.2 D2（`docs/analyze-offline-plan.md` 曾规划离线标 `degraded=False` 并新增 `meta.mode`，代码与此相反）。

### 7.7 壳层兜底（不属于上面 9 条，但影响用户体验）

| 场景 | 行为 | 锚点 |
|---|---|---|
| 终端·全链路无 Key | 打印凭据说明面板（怎么设环境变量、申请地址、推荐先试 `--resolve`/`--offline`），返回码 **1** | `ui/terminal/chat.py:385-398` |
| 终端·离线无推荐 | 返回码 **1** | `ui/terminal/chat.py:347-358` |
| 终端·体质 id 未知 | **不报错**，打印警告后回落 `BALANCED` | `ui/terminal/chat.py:476-483` |
| 终端·问卷不可用/判不出/被取消 | 五类分支一律返回 `None`，不抛异常（未装子包时打印安装命令） | `ui/terminal/chat.py:437-473` |
| 网页·凭据类错误 | 归为"凭据问题"，自动打开设置弹窗并聚焦 Key 输入框 | `ui/web/index.html:650-659` |
| 网页·初始化接口失败 | 禁用主按钮 + 提示"无法读取 /api/meta。请确认服务在运行，然后刷新页面。" | `ui/web/index.html:494-497` |
| 网页·问卷端点 501 | 换成"问卷功能未启用…"的人话提示，**不原样透出服务端安装指令** | `ui/web/index.html:813-829` |

### 7.8 降级相关的响应字段语义

| 字段 | 取值 | 含义 |
|---|---|---|
| `meta.degraded` | `true` / `false` | 是否走了规则兜底。⚠️ **不要单独用它判断故障**——判故障要看 `degraded_reason`（§7.6） |
| `meta.degraded_reason` | `high_risk_group` | 正常（安全分支未调模型） |
| | `guardrail_removed_all` | **异常**（生成的推荐全被护栏拦掉） |
| | `str(exc)[:200]` | Agent2 失败的真实原因（截断 200 字） |
| | `输入为空` / `高风险拦截` / `离线模式：不调用模型` | 离线路径的三种情形 |
| `meta.key_source` | `user` | 本次用了调用方提供的 Key |
| | `not_used` | 本次**未调用模型**（高风险分支、离线路径）——前端据此显示"本次未调用模型（规则分支，无费用）" |
| `meta.backend` | `direct` / `dsh` / `offline` | 本次走的运行时后端 |
| `user_message` | 各分支文案 | 需要向用户补充说明的话（降级说明、没看懂、就医引导、排除项清空说明） |

---

## 8. 已知边界

### 8.1 明确不做 🚫

| 不做 | 依据 |
|---|---|
| **不构成医疗建议、不做诊断、不承诺疗效** | 每个业务响应必带 `disclaimer`（`is_medical_advice` 恒为 false） |
| **不开方剂** | 单次搭配 ≤ 4 味、总量 ≤ 45 g 的设计意图就是"不像方剂"；提示词明写不做"君臣佐使"、不出现方剂名 |
| **不做"事前提醒"** | 本项目是**事后处理**工具：不拦、不挡、不报警，所有输出都是"吃了之后怎么调"。理由：事前提醒需要一份**可审定名单**与个体化判据，两者都不存在 |
| **不单列"发物"** | 同上：本地语料只有上位类别有据、食物表覆盖约 55%、食物侧无体质通路。推论：仲裁顺序为"冲击度 ≥ 2 → 体质 × 极端方向"，**不设硬禁忌档**；用户自述过敏走既有高风险分支（`HIGH_RISK_KEYWORDS` 已含"过敏"） |
| **不保存 API Key、无服务端兜底 Key** | "服务端兜底 Key"已从代码中彻底移除，不是配置开关 |
| **不收录标准正文、不算剂量、不做体质匹配推荐** | `medication_reference` 的隔离契约，由测试守卫 |
| **没有账户体系、数据库、多用户与云端存储** | 饮食记录只在浏览器本地；`session_id` 仅作日志串联 |

### 8.2 当前不支持 🚫

| 项 | 现状 |
|---|---|
| 多层食材合成 | `nature_math.combine()` 已实现并测试，但在 `core/app/` 下**无调用点** ⇒ **未接入主流程**（`README.md:490-492`、`docs/three-layer-architecture.md:208-210` 说的都是这件事——**此处是事实，不是文档滞后**）。`resolve_food()` 只判定单一食物；整菜名要么表里收录，要么整体落到第三层 |
| 规范名精确命中时的烹饪修正 | **不叠加模型给的烹饪修正**（无法可靠区分"可靠证据"与"猜测"）。温度类已由温度前缀层解决；煎炸/烧烤类仍受限，需要在表里为该食物单列条目并写 `variant_nature` |
| 离线路径的食物识别率 | `--offline` 依赖关键词匹配，**只能识别表内条目**，表里没有的一律认不出。它牺牲识别率换取零成本、零延迟与确定性，是刻意的取舍 |
| 未安装问卷子包 | `/api/questionnaire` 与 `/api/questionnaire/questions` 不可用；终端 `--questionnaire`/`:qz` 不可用。其余功能正常 |
| 两条离线路径的护栏等价性 | **API 离线路径**会逐条跑禁用表述扫描；**终端 `cmd_offline`** 只走 `matcher`，**不经过** `_sanitize_recommendations`。安全由"兜底配方本身来自白名单 + 固定克数"保证，但这与联网路径**不是同一条护栏** |
| 终端壳测试覆盖 | ✅ **已覆盖的部分**（5 个文件，共 37 项）：`core/tests/test_terminal_shell.py`（4 项，CLI 行为：`--resolve` 食性 / `--offline` 返回码 1 / `--offline` 出推荐 / 空推荐负控制）、`test_terminal_offline_path.py`（10 项，`_offline_analyze` 的 AST 结构守卫 + 行为不变式）、`test_meal_time_paths.py`（6 项，终端与 API 的餐次一致）、`test_shell_signals_render.py`（8 项，两个壳的信号渲染 + 跨链路一致）、`test_shell_plan_render.py`（9 项，两个壳的 plan 渲染 + 跨链路一致）。⚠️ **仍未覆盖**：`cmd_full`（需 Key 与模型）、`repl()` 交互循环、`run_questionnaire()`；另有 `core/scripts/smoke_offline.py` 冒烟 |
| Web 端"无 Key 的对话" | `/api/chat` 必须带 Key；无 Key 只能走 `/api/analyze-offline` |
| 数据目录可配置 | 数据路径固定为 `core/data/`（`config.py:78`），换位置需改代码或调工作目录 |

### 8.3 数据层面的已知局限

1. **第一层数据尚未人工审核**：`food_properties.json`（147 条）与 `herbs.json`（44 味）全部为 `pending`。属性依据中医饮食养生通行表述整理（食物偏性，非药物功效），**对外提供服务前应由具备资质的中医师/中药师复核**。
2. **关键词子串会把无关名称拉进表**：例如"辣椒"的关键词含"麻辣"，于是口述里的"麻辣烫"会把"辣椒"也命中。已知案例（"薯条"→"炸鱼薯条"、"寿司"→"生鱼片"）已通过三级匹配优先级修掉，但字符串匹配本质上无法完全消除歧义；要彻底解决需要菜品别名库或分词。
   ⚠️ 这一局限在 `--offline` 下**更容易被看到**：`match_foods()` 是"表里哪些条目在句子里出现过"，而不是"识别出你吃了什么"。所以离线模式的物品列表应理解为**表命中项**，与实际所吃并不等价。
3. **黄历式的诚实标注**：`herb_nature_reference.json` 是"饮片 vs 药典 2020 的**核对报告**"而非来源表；`_meta.known_limitations` 与 `open_items` 如实记录未决项。药典引用的是 2020 版（已被 2025 版废止）这类"必须跟着依据走"的诚实边界，由 `EvidenceReference.note` 带出且**前端不得省略**。
4. **九型体质矩阵未填满**：`docs/constitution-9-types.md:277` 记录 244 格中大量格子仍待专业判定；**空缺 ≠ 安全或不宜，空缺只表示"未判定"**。⚠️ 未标"不宜"的饮片**仍然会被推荐**（只是排序靠后），所以"应当禁忌却没标"是真实风险。
5. **数据词表存在多份分叉**：辣/寒热词表在代码与数据文件中曾并存三份，2026-09-21 已部分下沉到 `diet_signals.json` 的 `nature_keywords`（实测现存 cold **9** / hot **7** / warm **5** 个词），但**评分权重（cold/hot 各 2、warm 各 1）仍是代码里的评分参数、未下沉**（`core/app/api/analyze_offline.py:44-48` 注释明写）；库内另有"三份辣/寒热词表不合并、但登记守卫"的决定。

### 8.4 工程层面的已知缺口

| 缺口 | 说明 |
|---|---|
| `core/var/` 混入测试收集 | 在 `core/` 下直接跑裸 `pytest -q` 会把 `core/var/` 里的临时脚本一起收集（含 GBK 编码文件）而报 `UnicodeDecodeError`；必须带 `tests` 参数 |
| venv 里的 `.exe` shim 失效 | `pip.exe`/`uvicorn.exe` 会**无声失败**；一律用 `python -m pip` / `python -m uvicorn`（目录曾从 `backend` 改名为 `core`，shim 中的绝对路径失效） |
| `dsh` 后端的超时未强制 | `runtime.run()` 收 `timeout_s` 形参，但 `dsh` 后端路径**未使用**它（`direct` 后端用 `timeout_s or 120.0`）❓ 见 §9.1 |
| 200 但非 JSON 的响应 | `direct_api` 的 `resp.json()` 未包 try，会抛出未包装的解析异常（`multi_provider` 已捕获为 `RuntimeError`） |

---

## 9. 待确认、文档滞后与守卫缺口

### 9.1 待确认项 ❓

> 原则：**没核实就不写死**。以下都是只读复核中未能确证的点，正式引用前请再核一次。

| # | 事项 | 现状与边界 |
|---|---|---|
| 1 | `constitution_resolver.resolve_from_scores()` 内部的收敛规则 | 只确证异常类型与结构校验（见 §3.3）；主导/兼夹的**具体挑选算法**未逐行读 |
| 2 | `herb_evidence_sources.json` 域 II 的体质依据明细 | 结构与硬约束已确证（只返回命中本次原料的来源、域 II 需给体质才参与），计数已实测（`constitution_entries` = 24、`source_registry` = 6），但**未逐条核对内容** |
| 3 | `catalog-compliance.md` 提到的"目录级排除"能力 | 该文档记录"现有 `exclude_herbs` 是**每个请求的用户自选排除**，不是目录级开关"，并计划新增；**当前代码里是否已有该能力未确证** |
| 4 | `dsh` 后端是否真的无超时强制 | 从 `runtime.py` 看 `timeout_s` 形参未被使用；未实际构造超时场景验证 |
| 5 | 官方模型列表与 `/api/chat` 的 6 个模型在真实调用中的可用性 | 只确证接口返回 6 个硬编码 key，未实测每个 key 都能通 |
| 6 | `ErrorBody` / `ProfileResponse` / `ProfileUpdateRequest` **是否有意保留** | 定义在 `core/app/domain/models.py:40-43`、`:317-322`、`:325-328`；全仓检索**只有定义处这一处引用**，没有任何路由或模块使用它们。是预留、还是历史遗留 ⇒ 未确证。**因此本文件不把它们的字段写进 §4 的契约表**——如果它们其实是有意的对外结构，§4 需要补 |

### 9.2 文档滞后清单 📌（**一律以代码为准**）

| # | 文档说法 | 代码实测 | 位置 |
|---|---|---|---|
| **D1** | `docs/request-flow.md` §5.6：`/api/analyze-offline` **"尚未立项"** | **已实现并注册**：`core/app/api/analyze_offline.py`（215 行）、`main.py:111`；网页已有"离线规则"勾选框 | `docs/request-flow.md:330` |
| **D2** | `docs/analyze-offline-plan.md`：离线应标 `degraded=False`，并新增 `meta.mode="offline"` 区分 | 实测离线标 **`degraded=True`**（`degraded_reason="离线模式：不调用模型"`），且 `Meta` **没有** `mode` 字段 | `docs/analyze-offline-plan.md:95-96`；`core/app/api/analyze_offline.py:209-210`；`models.py:254-278` |
| **D3** | `docs/request-flow.md` §5.6：终端离线"**不过闸门④**"（并把该差异记为已知差异） | 该说法对**终端**仍成立；但**API 离线路径已跑禁用表述扫描**（`scan_free_text`），只是**没有**跑完整的 `_sanitize_recommendations`。即：现在有**两条**离线路径，护栏强度各不相同 | `docs/request-flow.md:342-343`；`core/app/api/analyze_offline.py:179-190`；`ui/terminal/chat.py:347-358` |
| **D4** | `README.md` 指明 Web 端口 **8180** | 网页里的两处错误提示写的是 `http://127.0.0.1:8000`（后端默认端口确实是 8000，`start-web.cmd` 用 8180） | `README.md:184/194/197`；`ui/web/index.html:654`、`:689` |
| **D5** | `docs/handover.md` §2.5：模型不可用、**没给 Key、JSON 解析失败**、推荐全被拦——"以上任何一种情况都**不能变成 500**" | 其中两项与代码相反：**没给 Key** 会 `raise AnalyzeError("NO_API_KEY")` → 400（`orchestrator.py:257-258`），**Agent1 的 JSON 解析失败**会 `raise AnalyzeError("AGENT1_FAILED")` → 422（`:277-281`）。SPEC §7.5 已按代码写清"刻意不降级的硬失败 5 条" | `docs/handover.md:76`；`orchestrator.py:257-258`、`:277-281`；§7.5 |
| **D6** | `core/app/agents/prompts/agent1_system.md:30` 要求份量"未提及写「未指明」" | 同文件 `:60` 的示例输出用了 `"amount_desc":"未吃完"`，与字段定义不一致（属提示词内部不一致） | `core/app/agents/prompts/agent1_system.md:30`、`:60` |

> **撤销记录（不再占用编号）**：曾列为本表 D5 的一条「`README.md:207` 写"食性表 146 条"」**不成立**——README 全文没有 "146"，`:207` 是「调理资料」那一条，`:340`/`:349` 均写 147；`git log -S"146" -- README.md` 显示该数字在更早的 `dc83af1` 就已改掉。该说法源自一次未核实的转述。

### 9.3 已确认（从待确认移入）✅

| 事项 | 确认结论 |
|---|---|
| `CONF_SHOW_THRESHOLD` 是否被壳层实际使用 | **是，但通过 `/api/meta` 间接使用**（引用点清单见 §6.8） |
| 白名单规模、就绪体质、食性表规模 | 实测：白名单 **44 味**；`ready_constitutions()` 返回**全部 9 型**；食性表 **147 条**（129 + 18） |
| 问卷子包缺失时的行为 | **确实返回 501**：`core/app/api/questionnaire.py:18-34` 的 `_require_questionnaire()` 捕获 `ModuleNotFoundError`，且**仅当** `exc.name` ∈ {`tcm_constitution`, `tcm_constitution.questions`} 时转 501（其它 ImportError 照抛）；detail 就是那段安装命令，网页壳再把它换成"问卷功能未启用…"的人话提示（`ui/web/index.html:813-829`） |
| `nature_math.PREFIX_BOUNDARY_CHARS` 的引用关系 | 定义在 `nature_math.py:211`（在 nature_math 内部**无使用**），但**被 `food_lookup.py:26` 导入、在 `food_lookup.py:548` 的 `_claims_prefix()` 里实际使用** ⇒ 它就是温度词"自成边界"三种判据之一（见 §6.2） |
| 4 条场景规则的完整取值 | 已逐条实测（id / priority / 关键词 / 搭配 / `match_natures`），见 §6.6 的表 |
| `RULES.late_night` 的关键词与搭配 | `keywords` 是**空元组**；搭配为陈皮 4 + 茯苓 6（"陈皮茯苓和胃饮"）、`match_natures` = {unknown}（见 §6.6）；其判据与文案由 `tests/test_late_night_wording.py` 守护 |
| 白名单里的数据标注分布 | 实测：`brewing.requires_cooking` 为真的 **12 味**；有 `unsuitable_for` 的 **38 味**；有 `suitable_constitutions` 的 **38 味** |
| 终端壳的测试覆盖 | 覆盖它的**是 5 个文件共 37 项**，不是"只有新增的 4 项"（清单见 §8.2） |

### 9.4 文档守卫的覆盖缺口 📌

| 缺口 | 说明 | 位置 |
|---|---|---|
| `README.md` 的**每文件项数表**不在守卫覆盖内 | `core/tests/test_doc_facts.py` 只认"测试项数"语境的 3–4 位数字与"N 个测试文件"，**不认 2 位的每文件计数** ⇒ 会静默过期。2026-09-21 实测就发现 `test_safety.py` 在 README 里写 50、实际 **54**（已修正） | `core/tests/test_doc_facts.py:41-46`、`:127-135` |

---

## 附录 A　实测基线与数据规模

| 项 | 值 | 来源 |
|---|---|---|
| 测试收集数 | **835 项**（45 个测试文件） | 实测：`python -m pytest core/tests --collect-only -q`（2026-09-26 复核；较上次 828 项 **+7**：`test_degradation_paths.py` +3、`test_terminal_shell.py` +4） |
| 实跑结果（A：临时目录可写） | **833 passed / 2 skipped / 0 failed** | 2026-09-26 复核实测（835 收集 − 2 skip） |
| 实跑结果（B：DSH 沙箱只读临时目录） | 821 passed / 2 skipped / 1 failed / 4 errors（**当时共 828 项**） | 同一套测试、同一份代码，仅环境不同 |
| B 里那 5 项失败的原因 | **全部是 `PermissionError`**：测试要往 `%TEMP%\dsh-*\pytest-of-*` 写临时目录被拒。涉及 `test_herb_evidence`、`test_catalog_check`、`test_questionnaire_dependency` | 报错原文 `[WinError 5] 拒绝访问` |
| **结论** | **不是代码缺陷**：两次结果的差异只由运行环境的临时目录写权限决定（B 的失败项在 A 下全绿） | — |
| 测试性质 | 全部离线：不调用模型、不需要 API Key（约数秒级） | — |
| 白名单 | 44 味 | `herbs.json` |
| 食性表 | 147 条（129 食材 + 18 茶饮） | `food_properties.json` |
| 体质 | 9 型，全部就绪 | `constitution.json` + 派生 |
| 信号 | 11 个，场景规则 4 条 | `diet_signals.json` |
| 食药物质目录核对 | 106 项 | `food_medicine_catalog.json` |
| 依赖模型的端到端 | `test_food_accuracy.py`（23 条语料）、`smoke_agents.py`（全链路） | **会产生调用费用** |

## 附录 B　文档地图（谁该读哪份）

| 文档 | 给谁 | 内容 |
|---|---|---|
| `README.md` | 使用者 | 这是什么、怎么装、怎么用、已知局限 |
| `CONTRIBUTING.md` | 贡献者 | 不可随手改的契约、数据表怎么改、PR 流程 |
| `docs/three-layer-architecture.md` | 改判定逻辑的人 | 三层原理、数值编码、已知局限 |
| `docs/maintenance.md` | 维护者 | 全貌、数据流、运维、验证基线、成本模型、排错手册 |
| `docs/data-contracts.md` | 改数据的人 | 数据文件的形状与派生纪律、批脚本文案陷阱 |
| `docs/request-flow.md` | 排查链路的人 | 逐步流程与字段（⚠️ 已部分滞后，见 §9.2） |
| `docs/handover.md` | 接手的人 | 设计原则、口径编号、已验证安全状态（⚠️ §2.5 有滞后，见 §9.2 D5） |
| `docs/pending-items.md` | 维护者 | 挂起项台账（D/E 编号） |
| `docs/catalog-compliance.md`、`docs/food-properties-review-sheet.md` | 合规与审核 | **生成物，勿手工编辑** |
| **本文件 `SPEC.md`** | 想一次看清"当前实际行为"的人 | 定位、架构、流程、数据模型、安全、可信度、降级、边界、待确认；附录 D 是项目外实验的结论 |

## 附录 C　测试覆盖地图（关键环节）

| 环节 | 测试文件 |
|---|---|
| 护栏（白名单/剂量/禁词/体质/煎煮） | `tests/test_safety.py`（全项目最不能松的一层） |
| HTTP / 凭据 / 日志安全 | `tests/test_key_handling.py`（含 Key 不进日志的 sentinel 测试） |
| 三层判定接线与隔离 | `tests/test_calibration.py`、`tests/test_food_lookup.py` |
| 温度前缀层 | `tests/test_temperature_layer.py` |
| 四性运算与合成 | `tests/test_nature_math.py` |
| JSON 容错与重试 | `tests/test_json_guard.py` |
| 体质就绪闸门与两路径一致性 | `tests/test_constitution_readiness.py`、`tests/test_constitution_integration.py` |
| 数据契约与派生不变式 | `tests/test_data_contracts.py`、`tests/test_herb_evidence.py`、`tests/test_catalog_check.py` |
| 信号与餐单接线 | `tests/test_meal_signals_wiring.py`、`tests/test_meal_plan_wiring.py`、`tests/test_offline_segmentation.py` |
| **降级路径三条出口（§7.1）** | `tests/test_degradation_paths.py`（3 项：高风险不调模型且无需 Key / Agent2 失败降级仍给非空搭配 / 护栏清空后 `guardrail_removed_all` 并留痕） |
| 壳层（网页） | `tests/test_web_shell.py` |
| 壳层（终端）CLI 行为 | `tests/test_terminal_shell.py`（4 项：`--resolve` 食性 / `--offline` 返回码 1 / `--offline` 出推荐 / 空推荐负控制） |
| 壳层（终端）结构与行为不变式 | `tests/test_terminal_offline_path.py`（10 项：`_offline_analyze` 的 AST 结构守卫 + 单样食物零漂移 + 温度词归属） |
| 壳层（两个壳）渲染与跨链路一致 | `tests/test_shell_signals_render.py`（8 项）、`tests/test_shell_plan_render.py`（9 项） |
| 终端与 API 的餐次一致 | `tests/test_meal_time_paths.py`（6 项） |
| `late_night` 兜底的判据与文案 | `tests/test_late_night_wording.py`（含"样本必须真的命中 late_night"的前置断言与文案变异检验） |
| **零覆盖** | 终端壳的 `cmd_full`（需 Key 与模型）、`repl()` 交互循环、`run_questionnaire()`（终端壳已覆盖的部分见 §8.2） |

---

## 附录 D　工具层验证结论（Function Calling 实验）

> **本附录口径**：素材来自**项目外**的一次实验（`D:\experiments\test_tool_calls.py`），它**不属于 tea-advisor 代码库**（因此本附录的锚点是相对该脚本的行号，见头部「锚点写法」的例外②）。
> 只写**验证了什么、意味着什么**，不写后续计划。
> ⚠️ **现状前提**：tea-advisor 目前**没有任何 tool / function-calling 代码**——对 `core/**/*.py` 与全仓 `*.md` 检索 `tool_calls` / `tool_choice` / `tools=` / `function_call` / `函数调用` **全部零命中**；两个 Agent 走的是"纯文本 → JSON"，靠提示词 + `core/app/agents/json_guard.py:134` 的 `validate_with_retry` 兜住格式。因此本附录所有条目的状态都是 **未接入主流程** 🔌。

### D.1 实验装置（可逐一核对的代码面）

| 装置 | 实验里的实际实现 | 锚点（`test_tool_calls.py`） |
|---|---|---|
| 调用方式 | 用 `openai` SDK **直连** `https://api.deepseek.com`，**不走项目运行时**；模型写的是 `deepseek-chat` | `:229-234`、`:344` |
| 工具数 | **2 个**：`screen_health_risk`、`check_blend` | `:237-277` |
| `screen_health_risk` schema | 参数 `text`（string，required）；描述写明"命中时应引导就医，不推荐茶饮" | `:241-250`、`:242`、`:248` |
| `check_blend` schema | `herbs` 为数组，每项 `name`(string) + `amount_g`(number)，二者 required；顶层 required `["herbs"]` | `:255-275`、`:266-269`、`:273` |
| `screen_health_risk` 实现 | 关键词表 **8 个**（怀孕/哺乳/化疗/手术/糖尿病/高血压/过敏/吃药），返回 `{risk, matched}` | `:281-286`、`:282` |
| `check_blend` 实现 | 自建 **6 味** `WHITELIST`（每味一个上限）+ `MAX_HERBS = 4`；超味数整组拒绝；白名单外记 `blocked`；超量裁剪并记 `adjusted[{name, from, to}]` | `:289-293`、`:300-301`、`:308-310`、`:312-315` |
| `ok` 的判据 | `ok = len(blocked)==0 and len(adjusted)==0` | `:319` |
| 分发方式 | `json.loads(tool_call.function.arguments)` → `TOOL_FUNCTIONS[name](**tool_args)`；未知工具名有兜底分支 | `:324-327`、`:365`、`:371`、`:372-373` |
| 主循环 | 上限 **5 轮**；**不传 `tool_choice`**；`for tool_call in message.tool_calls`；结果以 `role:"tool"` + `tool_call_id` 回灌 | `:335`、`:343-347`、`:363`、`:377-381` |
| 触发修正的输入 | 用户要求"金银花、菊花、薄荷**各 15 克**"，而白名单里薄荷上限 6、菊花上限 10 ⇒ **首次** `check_blend` 必然返回 `ok=false` 且带 `adjusted` | `:332`、`:290` |

### D.2 已验证的能力（实验内 🧪）

| # | 结论 | 代码依据 | 本次的边界 |
|---|---|---|---|
| 1 | **模型能正确选工具** | 两个工具都塞进 `tools`，按 `function.name` 分发；脚本会打印被选中的名字 | `:237-277`、`:364`、`:370-371` | 候选只有 **2 个**，且只有 **1 条**用户输入（`:332`） |
| 2 | **模型能正确传参数（结构 / 类型）** | 分发是 `TOOL_FUNCTIONS[name](**tool_args)`：参数名必须精确为 `text` / `herbs`，`herbs` 每项必须含 `name`+`amount_g`，结构或类型不符会直接抛错 | `:365`、`:371`、`:266-269` | **枚举值**这一条 ❓ 待确认：实测版两个 schema **都没有枚举参数**（`constitution` 的 `enum` 只出现在被注释掉的旧稿 `:90-94`） |
| 3 | **模型能自我修正** | 工具描述本身就写明"若返回 `ok=false`，需根据 `adjusted` 修改后再次调用，直到 `ok=true`"；返回值含**机器可读**的 `adjusted`；工具结果回灌进对话供下一轮使用 | `:256`、`:314`、`:319`、`:377-381` | 修正后的具体数值与 `adjusted.to` 是否逐字一致，由实验结论给出；脚本内**没有断言**可复核 |
| 4 | **模型能一次调多个工具** | 单轮内 `for tool_call in message.tool_calls` 逐个执行，并给每个结果带各自的 `tool_call_id` | `:363`、`:377-381` | 未验证 3 个以上、或同一工具被并行调多次时的顺序依赖 |
| 5 | **模型能自己决定什么时候停** | 停止条件是**代码侧**判断"这一轮没有 `tool_calls`"即 break 并输出最终回答 | `:352-355` | 未验证"模型会不会无限调下去"；安全网是硬编码的 5 轮上限（`:335`） |

### D.3 已验证的限制（含外部来源 📎）

| # | 限制 | 状况与锚点 |
|---|---|---|
| 1 | **脚本不传 `tool_choice`** | 发起请求时只传 `model` / `messages` / `tools`（`:343-347`）⇒ 走的是**默认 auto**；因此"思考模式下不能用 `required`"这条**在脚本内无法证实**，属**外部来源**（DeepSeek 官方 issue #1376）❓ |
| 2 | **模型可能不调工具，约 40% 概率** | **外部来源**（同上）。⚠️ 本实验只跑了**1 条**输入，脚本内没有任何重复次数或统计代码 ⇒ 这 40% **不是**本实验测出来的数 |
| 3 | **模型名与思考模式的对应关系** | 脚本写死 `model="deepseek-chat"`（`:344`），且完全没有 `reasoning_effort` 之类参数 ⇒ 它与项目 `TA_MODEL=deepseek-v4-flash` / `TA_REASONING_EFFORT=low`（`core/app/config.py:54-58`）的**对应关系未核实** ❓ |
| 4 | **证据强度：无断言、无留痕** | 全脚本只有 `print`（`:340`、`:367-375`、`:353-354`），**没有 `assert`、没有落盘记录**；本版 `while` 循环**也没有** max-turn 的 `else` 分支（被注释的旧稿有一个 `:148-149`）⇒ 达到 5 轮上限时**静默退出**，不留任何标记 |
| 5 | **脚本内含一处硬编码凭据** | `:232`（以及注释稿 `:1`、`:7`）把 API Key 直接写进了源码。⚠️ 该文件**不在本仓库内**，所以 §9.3「全仓库无残留 API Key」的结论不受影响；**本附录不记录该凭据的任何内容** |

### D.4 本次实验**没有**验证的东西（防误读清单 🚫）

被包成工具的是**等价 stub**，不是项目真函数——下列能力**一概未验证**：

| 未验证项 | 与项目真实现的差距 |
|---|---|
| 真实饮片白名单 | 实验用**自建 6 味**（`:289-292`）；项目是 `core/data/herbs.json` 的全量白名单（44 味，§5.3） |
| 真实 `safety.check_blend` | 项目版还有**总量 45 g** 上限、`cautions` → warning、用户 `exclude_herbs`（`core/app/domain/safety.py:148-219`；§5.4），实验版**一项都没有** |
| 体质适配 | 实测版两个 tool 的 schema **没有 `constitution` 参数**（`:255-275`）⇒ `filter_by_constitution` 的候选集收敛（`safety.py:353`；§5.3、§5.6）**未参与** |
| 高风险判据的规模 | 实验用 **8** 个关键词（`:282`）；项目是 **25** 个（`safety.py:21-26`；§5.2） |
| 禁用表述 / 煎煮适配 / 依据链 | `scan_free_text`（§5.5）、`check_brew_adequacy`（§5.7）、`herb_evidence`（§5.12）**均未出现在实验里** |
| 模型对"被拒"的反应 | 未验证模型拿到 `blocked`（白名单外）时会怎么处理——实验输入（`:332`）里的三味**都在**白名单内，只会触发 `adjusted` |
| 异常与边界 | 未验证错误工具名、参数缺字段、参数类型错误时模型的表现（脚本只有"未知工具"的兜底分支 `:372-373`） |
| 并发 / 超时 / 重试 | 脚本是单线程串行、无超时、无重试 |
| 真实入口 | `/api/analyze`、终端、离线路径**都不是**本实验的对象；实验绕过 `orchestrator` 直接调 SDK |

### D.5 对后续改动意味着什么

> ### **原则：代码护栏是底线，模型自查是增强。**
> 模型自查是**概率性**的（外部来源：约 40% 的情况下模型根本不调工具，见 D.3）。因此**不能因为"模型会自查"就取消、放宽或绕过 `safety.py` 的任何检查**。工具层最多是"同一份护栏的第二次机会"，**不是**护栏的替代品——在本项目现有链路里，护栏的执行点始终在**代码侧**（`core/app/services/orchestrator.py:129-189` 的 `_sanitize_recommendations`）。

| # | 含义 | 依据 |
|---|---|---|
| 1 | **护栏的返回值必须机器可读、且可据以修正。** 自我修正在本次实验里能发生，前提是返回值同时给出"通过与否"与"差多少"：`ok` + `adjusted[{name, from, to}]`。项目现有 `GuardrailResult` 已经是这个形状（`ok` / `blocked` / `warnings` / `adjusted`，`core/app/domain/safety.py:48-60`）——即"可被模型读懂并据以改正"这一点，项目侧的返回结构**天然满足** | 实验 `:314`、`:319`；`safety.py:48-60` |
| 2 | **判据必须同源，不能另写一套。** 项目已经踩过同形风险：LLM 路径与离线路径必须用**同一份** `unsuitable_for` 判据，否则同一用户"有 Key / 没 Key"会拿到不同安全边界，而界面只显示最终搭配、看不出差异来源（§5.6，E4；由 `core/tests/test_constitution_integration.py` 钉死）。工具层若自带一份判据，就是同一个失效形状 | §5.6；同源判据的既有做法见 `core/app/services/matcher.py:469-485`（`_herbs_unsuitable_for_any`）与 `safety.py:395-398`（候选集侧的同一判据） |
| 3 | **终止权不能完全交给模型。** 本次实验里"模型自己停"（`:352-355`）与"硬上限 5 轮"（`:335`）**同时存在**；含义是：模型自主停止是一次**行为观察**，不是**保证**。链路必须自己持有轮数/重试上限 | 实验 `:335`、`:352-355` |
| 4 | **本实验支持的范围是"暴露已有的确定性函数"，不是"让模型承担判定"。** 已验的是"能选中工具、按 schema 传参、读结果、改正、停止"；它**不改变** §5 里那些靠结构锁死的结论——候选集收敛、白名单、剂量上限、禁词、体质硬剔除仍然是底线，与模型是否配合无关 | §5.1–§5.12；全仓零 tool 代码 |

### D.6 状态标注（本附录收口）

| 项 | 状态 |
|---|---|
| 工具选择 / 参数结构类型 / 一次多工具 / 自主停止 | **已验证（实验内，stub 规模）** 🧪 |
| 自我修正闭环（`ok=false` → 按 `adjusted` 改 → `ok=true`） | **已验证（实验内）** 🧪 |
| 参数**枚举值**正确 | **❓ 待确认**（实测 schema 无枚举参数，见 D.2 第 2 条） |
| 模型名与项目思考模式的对应关系 | **❓ 待确认**（脚本写 `deepseek-chat`，见 D.3 第 3 条） |
| 思考模式下 `tool_choice` 不能用 `required` / 约 40% 不调 | **外部来源**（DeepSeek issue #1376），**非**本实验测得 📎 |
| 真实 `safety.py` 各护栏在工具层下的行为 | **未验证** 🚫（见 D.4） |
| 接入 tea-advisor 主流程 | **未接入** 🔌（全仓零 tool 代码，见本附录开篇） |

---

> **本文件的维护纪律**：它描述的是**行为**，行为改了就要改它。
> 新增/修改安全规则、降级分支、置信度档位、接口字段时，请同步本文件对应小节；
> 描述失真比没有描述更危险（沿用 `docs/data-contracts.md` 开头的同一句话）。
