# 维护与交接文档

> **这份文档给维护者。** 其它三份文档的分工：
>
> | 文档 | 给谁 | 回答什么问题 |
> |---|---|---|
> | `README.md` | 使用者 | 这是什么、怎么装、怎么用 |
> | `CONTRIBUTING.md` | 贡献者 | 哪些是契约、数据怎么改、PR 要走什么流程 |
> | `docs/three-layer-architecture.md` | 想改判定逻辑的人 | 三层架构的设计原理、数值编码、**已知局限** |
> | **本文** | **维护者** | 全貌、数据流、运维、验证基线、排错手册、以及"当初为什么这么写" |
>
> 维护时的第一原则：**改任何东西之前，先看 `CONTRIBUTING.md` 第 4 节的十条契约。**
> 那十条是踩过坑之后钉下来的，不是装饰。

---

## 1. 项目是什么、现在到哪一步

### 1.1 定位

**中医食性的确定性判定层 + 本地运行的饮食茶饮建议助手。**

核心主张：**食物是寒是热，不靠模型的语感猜，而是查表 + 纯规则推导，并且每一档结论都能追溯来源。**
模型只负责两件事——把自由文本解析成食物列表、把结论写成人话——而且这两件事都可以整个绕过。

### 1.2 两种用法

| 用法 | 入口 | 是否需要 API Key |
|---|---|---|
| 当**库**用（只要判定） | `resolve_food()` / `match_foods()` / `nature_math.*` | **不需要**，零成本、零网络 |
| 当**助手**用（要建议） | `ui/terminal/chat.py`、`ui/web/`、`POST /api/analyze` | 需要（**只能由调用方提供，无兜底**） |

### 1.3 当前状态

| 能力 | 状态 |
|---|---|
| 三层判定（`resolve_food`） | ✅ 完整，含温度前缀层与准入校验 |
| 双 Agent 协作 | ✅ 真实模型跑通 |
| 安全护栏（白名单/剂量/禁用表述/高风险人群） | ✅ 机器强制 |
| JSON 护栏（围栏剥离/校验/重试） | ✅ |
| 规则兜底（模型不可用时降级） | ✅ |
| 终端壳 | ✅ `--resolve` / `--offline` / 交互三种用法 |
| 网页壳 | ✅ 含测试指引、置信度标注、API Key 输入 |
| **用户自带 API Key（逐请求）** | ✅ 默认直连后端支持 |
| 服务端内置 Key | ❌ **不存在**（曾有的"兜底 Key"已按需求移除）；Key 只由调用方传入 |
| 数据表**人工审核** | ❌ **147 条全部 `pending`**（刻意的，见 §9.3） |
| 第二层 `combine()` 接入主流程 | ❌ 已实现并测试，但未接线 |
| 食性表规模 | 147 条（129 食材 + 18 茶饮） |
| 饮片白名单 | 35 味 |
| 体质 | 9 型 |

### 1.4 规模（随代码变动，更新时请重测）

重测口径：只统计该层的源码文件（`.py`；`ui/web` 为 `.html`；`agents` 另含 `prompts/*.md`），
排除 `__pycache__`，行数按 `\n` 计。

| 层 | 文件 | 行数 | 说明 |
|---|---|---|---|
| `core/app/domain` | 5 | 973 | **核心判定，纯逻辑，不依赖 Web 框架** |
| `core/app/services` | 4 | 1,102 | 编排与规则兜底 |
| `core/app/agents` | 8 | 1,164 | LLM 层（含两个后端）+ 2 个提示词文件 |
| `core/app/api` | 3 | 115 | HTTP 适配，极薄 |
| `core/tests` | 13 | 2,919 | **335 项，全离线，约 0.9 秒** |
| `core/scripts` | 10 | 2,907 | 运维/自检脚本 |
| `ui/terminal` | 1 | 398 | 终端壳 |
| `ui/web` | 1 | 449 | 网页壳 |
| **合计** | 45 | **10,027** | |

数据：`food_properties.json` 66 KB、`herbs.json` 22 KB、`constitution.json` 2.6 KB、
`food_medicine_catalog.json` 19 KB（合规自检用）、`herb_nature_reference.json` 61 KB（药典核对用）。
后两个**不参与运行时判定**。

> ⚠️ **别用 PowerShell 的 `(Get-Content x).Count` 数行数。** 实测它会把
> `core/app/agents/prompts/*.md` 数成 32/29 行，实际是 66/64 行（差一倍）。
> 用 Python 的 `bytes.count(b"\n")` 口径重测。

> 判断架构是否还健康的快速指标：**`domain` + `services` 的行数占比**。
> 这两层是真正的资产（2,075 行），其余是壳与测试。若这两层开始膨胀，
> 说明有人在把界面逻辑或模型逻辑塞进核心层。

---

## 2. 一次请求的完整数据流

以网页端点「给我建议」为例，标注每一步的落点与**不变量**：

```
浏览器
  │  POST /api/analyze
  │  Authorization: Bearer <用户Key>   （可选）
  │  {"text": "...", "constitution_override": "..."}
  ▼
core/app/api/analyze.py::analyze_endpoint
  │  auth.extract_api_key(header)      → 裸 Key 或 None（格式不对也返回 None，不抛 500）
  │  ⚠️ 不变量：此处及之后，Key 绝不进日志/响应/异常
  ▼
core/app/services/orchestrator.py::analyze(request, *, api_key)
  │  ① 凭据前置校验（早于一切模型调用）
  │     · 有用户 Key 但后端不支持 → AnalyzeError("USER_KEY_UNSUPPORTED")
  │     · 无任何 Key           → AnalyzeError("NO_API_KEY")
  │  ② 高风险人群检查 detect_high_risk(text)
  │     └─ 命中 → 直接返回，recommendations=[]，meta.key_source="not_used"
  │        ⚠️ 不变量：此分支**不调用模型**，秒回、零成本
  ▼
core/app/agents/agent1_diet.py::parse_diet(text, meal_time, api_key=...)
  │  ③ render_reference(text)        → 先查表，把命中的条目属性作为参考注入提示词
  │  ④ runtime.run(user_prompt, system_prompt=...)   ← 后端在此分叉
  │     · TA_BACKEND=direct → DirectAPIRuntime（逐请求 Key）
  │     · TA_BACKEND=dsh    → HarnessRuntime（Key 绑子进程，不接受逐请求 Key）
  │  ⑤ json_guard.validate_with_retry(ParsedMeal, ...)  失败重试 1 次
  │  ⑥ calibrate_parsed(parsed, text)  ★ 三层架构的落地点
  │     └─ 逐项调 resolve_food，用确定性结果**覆盖**模型的属性判断
  │        ⚠️ 不变量：命中表时以表为准，模型的值只作为第三层兜底
  ▼
core/app/services/food_lookup.py::resolve_food(name, cooking, llm_nature, text_hint, note)
  │  ⑦ 判定顺序（**不可颠倒**）：
  │     温度前缀层准入校验 → 查表精确同名 → 食材变体层 → 烹饪修正层 → 温度前缀叠加
  │     产出 ResolvedFood(nature, flavors, entry, verification{source, confidence, unverified, detail})
  │  ⑧ 置信度：rule 0.9 / composed 0.6 / llm 0.3 / unresolved 0.1
  ▼
core/app/agents/agent2_recommend.py::recommend(parsed, constitution, exclude, api_key=...)
  │  ⑨ _candidate_lines(constitution) → 用 safety.filter_by_constitution 收敛候选集
  │     ⚠️ 不变量：模型只能在白名单内选，**无方可开**
  │  ⑩ _build_unverified_section(parsed) → 把未验证项单列并禁止用作搭配依据
  ▼
core/app/services/orchestrator.py::_sanitize_recommendations
  │  ⑪ safety.check_blend        → 白名单 / 剂量裁剪 / 用户排除
  │  ⑫ safety.scan_free_text     → 禁用表述（"治疗""根治"…）
  │  ⑬ safety.check_constitution_fit → 体质契合提示
  │     ⚠️ 不变量：被拦的内容绝不原样返回；全被拦则整条作废并走规则兜底
  │  ⑭ 推荐为空 → matcher.fallback_recommend（meta.degraded=True）
  ▼
AnalyzeResponse  ← 必带 disclaimer；meta 带 key_source / backend / 耗时 / degraded
```

### 2.1 三个"绕过模型"的入口（维护时别把它们弄丢）

| 入口 | 何时用 | 成本 |
|---|---|---|
| `food_lookup.resolve_food()` | 只要属性判定 | 0 |
| `ui/terminal/chat.py --offline` | 无 Key 也要给建议（`match_foods` + `resolve_food` + `matcher`） | 0 |
| 高风险人群分支 | 命中孕期/慢性病/服药等 | 0（不调用模型） |

---

## 3. 模块地图与改动风险

| 文件 | 行数 | 职责 | 改动风险 |
|---|---|---|---|
| `domain/enums.py` | 117 | 四气/五味/时段/烹饪/体质枚举 + 中文标签（含 `SOURCE_LABELS`） | 低（加取值安全，改取值名=改契约） |
| `domain/nature_math.py` | 355 | 四性数值轴、`shift_nature`、`combine`、**温度前缀唯一入口** | **高** |
| `domain/models.py` | 236 | 请求/响应/中间结构**唯一真源** | **高**（改字段名=改对外契约） |
| `domain/safety.py` | 264 | 白名单/剂量/禁用表述/高风险人群/体质收敛 | **高**（安全层） |
| `services/food_lookup.py` | 561 | `resolve_food` 三层判定、`match_foods`、`render_reference` | **高** |
| `services/matcher.py` | 268 | 规则兜底、体质默认搭配 | 中 |
| `services/orchestrator.py` | 272 | 编排、凭据前置校验、护栏调用、降级 | **高** |
| `agents/runtime.py` | 251 | 后端选择器、dsh 后端、`AgentRun`、`CredentialError` | 中 |
| `agents/direct_api.py` | 224 | 直连官方 API 后端、思考参数映射、错误文案 | 中 |
| `agents/agent1_diet.py` | 195 | 解析器 + `calibrate_parsed` | **高** |
| `agents/agent2_recommend.py` | 197 | 推荐器 + 未验证项隔离 | 中 |
| `agents/json_guard.py` | 166 | JSON 提取/校验/重试 | 中（最容易被低估） |
| `agents/prompts/*.md` | 130 | 两个 system prompt | 中（改完必须跑真实回归） |
| `api/auth.py` | 47 | Bearer 头 → 裸 Key | 低 |
| `api/analyze.py` | 67 | 路由 + 凭据错误码映射 | 低 |
| `config.py` | 129 | 环境变量集中读取（**Key 的唯一读取点**） | 低 |
| `main.py` | 177 | FastAPI 入口、`/`、`/healthz`、`/api/meta` | 低 |
| `ui/terminal/chat.py` | 398 | 终端壳（仅标准库） | 低 |
| `ui/web/index.html` | 449 | 网页壳（单文件，内联 JS） | 低 |

> 行数口径同 §1.4（Python `bytes.count(b"\n")`，不含 `__pycache__`）。
> 别用 PowerShell `(Get-Content x).Count` —— 它还会把 UTF-8 当 GBK 解，中文注释会乱码。

---

## 4. 三层判定：常量与不变量

完整设计见 `docs/three-layer-architecture.md`。这里只列**改代码时必须记住的常量**：

| 常量 | 值 | 位置 | 含义 |
|---|---|---|---|
| `CONF_RULE` | 0.9 | `food_lookup` | 表命中（已审核不标注） |
| `CONF_COMPOSED` | 0.6 | `food_lookup` | 组合推理 / 烹饪修正 |
| `CONF_LLM` | 0.3 | `food_lookup` | 模型推测 |
| `CONF_UNRESOLVED` | 0.1 | `food_lookup` | 无法判定 |
| `CONF_SHOW_THRESHOLD` | **0.3** | `food_lookup` | **低于此值界面不显示寒热属性**（数据仍传 Agent2） |
| `COOKING_DELTA` | 冰镇 −1 / 煎炸 +1 / 烧烤 +1 | `nature_math` | 仅在第 1 层未命中时生效 |
| `SPICY_KEYWORDS` | 辣/麻辣/花椒/孜然… | `nature_math` | 命中即 +1（**注意它会受模型 note 措辞影响**，见 §10.11） |
| `CHILL_PREFIXES` / `HEAT_PREFIXES` | 冰/去冰/加热… | `nature_math` | **新增前缀只改这一处** |
| 四性编码 | 寒 −2 / 凉 −1 / 平 0 / 温 +1 / 热 +2 | `nature_math` | `unknown` **没有数值**（`None`），不是 0 |
| `review_status` | approved / pending / rejected | 数据 | 三态，不是布尔 |

### 4.1 四条不可颠倒 / 不可分散的不变量

1. **温度判定只有一个入口** `nature_math.resolve_temperature(name, note)`。
   历史上解析层用前缀匹配、提示词层用子串匹配，两套逻辑漂移过（「冰淇淋」在解析层被正确排除，
   在提示词层却被当成冰镇）。
2. **`resolve_food` 的层序**：温度前缀准入 → 精确同名 → 食材变体层 → 烹饪修正层 → 温度叠加。
   表里精确的变体值会被通用规则破坏，所以变体层必须优先于通用修正。
3. **规范名精确命中时不叠加模型给的烹饪修正**（无法区分"可靠证据"与"猜测"）。
4. **中文标签与显示阈值只从 `/api/meta` 取**（终端壳则直接 `import app.domain.enums`）。
   两个壳都不得各自硬编码映射表——这条已有回归测试（变异测试）钉住。

---

## 5. 凭据与后端：完整矩阵

### 5.1 两个后端

| | `direct`（默认） | `dsh` |
|---|---|---|
| 实现 | `agents/direct_api.py` | `agents/runtime.py::HarnessRuntime` |
| 传输 | httpx 直连官方 OpenAI 兼容端点 | DeepSeekHarness 子进程（stdio） |
| 启动成本 | 无 | 首次约 1.4–2.2 秒 |
| **逐请求 Key** | ✅ 支持 | ❌ **不支持**（Key 写进子进程环境，`run()` 无凭据参数） |
| 运行时目录 | 不需要 | 需要 `DSH_HOME`，会写 profile |
| 输入 token | 只有本项目提示词 | 额外带 ~9,000 token 的 harness 上下文（走缓存价） |
| 无状态 | ✅ 每次调用独立 | 复用 `session_id` 会延续同一段持久对话 |
| 用途 | **生产默认** | 调试 / 对照 |

### 5.2 行为矩阵（维护时最常查的表）

**前提：本项目不使用服务端内置 Key。** Key 只有一个来源——调用方显式传入
（网页走 `Authorization` 头，终端与脚本走环境变量 `DEEPSEEK_API_KEY`）。
没有任何"配置文件里的兜底"可以退。

| 后端 | 带了 Key | 结果 |
|---|---|---|
| direct | ✅ | 正常调用，`meta.key_source="user"` |
| direct | ❌ | `400 NO_API_KEY`，提示去界面填或设环境变量；**不发任何模型调用** |
| direct | ✅ 但被服务方拒绝（401/402/403） | `400 API_KEY_REJECTED` |
| dsh | ✅ | `400 USER_KEY_UNSUPPORTED` —— dsh 无法按请求换 Key，**绝不静默复用** |
| dsh | ❌ | `400 NO_API_KEY`（同上） |
| 任意 | 命中高风险人群 | **先于凭据校验**返回：不调用模型、`key_source="not_used"`、引导就医 |

> **安全分支为什么排在凭据校验之前**：它不花一分钱，所以必须无条件可用。
> 一个还没填 Key 的用户输入"我怀孕了"，应该看到"请先咨询执业医师"，
> 而不是"缺少 API Key"。这个顺序有测试钉住
> （`test_high_risk_branch_works_without_any_key`）。

> **为什么 dsh + Key 要报错而不是回退**：dsh 的 Key 与子进程绑定，一个进程只能有一个；
> 静默复用旧 Key 会让用户以为自己填的 Key 生效了、以为费用记在自己账上。

### 5.3 Key 的流向与安全规则

```
浏览器 localStorage/sessionStorage
  → Authorization: Bearer <key>
  → api/auth.py::extract_api_key()
  → orchestrator.analyze(api_key=...)
  → parse_diet / recommend(api_key=...)
  → runtime.run(api_key=...)
  → httpx headers={"Authorization": f"Bearer {key}"}
```

**硬规则（`CONTRIBUTING.md` 契约 9，配套测试 `tests/test_key_handling.py`）：**

* 不得记录 `Authorization` 头或 Key（连掩码也不要加进请求路径）
* 不得把 Key 放进响应体、`HTTPException(detail=...)` 或异常信息
* 上游报错时**不回显响应体**（官方 401 响应体自带掩码 Key，但一律不回显更好守）
* 允许记录的只有：模型名、接口主机名、耗时、token 用量、`session_id`

---

## 6. 运维手册

### 6.1 四种起法

```powershell
# ① 最省事：双击（Windows）
start-web.cmd          # 起服务 + 4 秒后自动开浏览器；TA_NO_BROWSER=1 可跳过
start-terminal.cmd     # 终端版

# ② 网页版（手打）
cd core
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000

# ③ 终端版
core\.venv\Scripts\python.exe ui\terminal\chat.py              # 交互（走模型）
core\.venv\Scripts\python.exe ui\terminal\chat.py --offline "..."  # 离线（0 成本）
core\.venv\Scripts\python.exe ui\terminal\chat.py --resolve 冰啤酒   # 纯查表（0 成本）

# ④ 只想用判定层（无需服务、无需 Key）
core\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'core'); from app.services.food_lookup import resolve_food; print(resolve_food(name='冰啤酒').nature)"
```

> ⚠️ **不要用裸 `pip` / `uvicorn`**：`core/.venv` 的目录名被改过（`backend` → `core`），
> Windows 的控制台脚本 shim 把绝对路径写死在 exe 里，已失效。一律用 `python -m`。
> 想修就重建 venv（见 §10.5）。

### 6.2 端口 / 绑定 / CORS 约束

| 项 | 值 | 说明 |
|---|---|---|
| 默认端口 | 8000（`APP_PORT`） | |
| 默认绑定 | `127.0.0.1` | **只本机可访问**。要让局域网访问必须显式 `--host 0.0.0.0` |
| CORS | 只放行 `http://127.0.0.1:<port>` 与 `http://localhost:<port>` | 界面与接口同源，本来不需要 CORS；**绝不要改回 `["*"]`** |

> ⚠️ 若用 `--host 0.0.0.0` 暴露到局域网：CORS 只能挡浏览器 JS，**挡不住直连**。
> 好消息是这不再涉及额度风险——本服务不持有任何 Key，每个请求必须自带。
> 要担心的变成"任何人都能拿它当模型代理用"，必要时在前面加一层访问控制。

### 6.3 日志

| 位置 | 内容 |
|---|---|
| 进程 stdout/stderr | uvicorn 访问日志 + `app.*` 的 INFO（直连后端会打印 model/host/耗时/token 用量） |
| `core/var/dsh_runtime.log` | **仅 dsh 后端**的子进程 stderr（排查 dsh 启动问题看它） |
| `dsh-home/` | **仅 dsh 后端**的 profile 与会话记录（含完整对话，已被 gitignore） |

**日志里不会出现 Key** —— 这是有测试保证的（§7.3）。

### 6.4 关闭与清理

```powershell
# 停服务：Ctrl+C；或按端口找进程
Get-NetTCPConnection -LocalPort 8000 -State Listen | ForEach-Object { Get-Process -Id $_.OwningProcess }
Get-Process | Where-Object { $_.ProcessName -match 'python' } | Stop-Process -Force
```

> ⚠️ **改完代码记得重启服务**：uvicorn 不加 `--reload` 不会热加载。
> 曾因此出现"改了代码但请求打到旧进程、报出莫名错误"（见 §10.1）。

---

## 7. 验证与回归

### 7.1 四道验证（成本从低到高）

| # | 命令 | 耗时 | 需要 Key | 费用 |
|---|---|---|---|---|
| ① | `python scripts\check_setup.py` | 秒级 | 否 | 0 |
| ② | `python scripts\smoke_offline.py` | 秒级 | 否 | 0 |
| ③ | `python -m pytest -q` | 约 0.7 秒 | 否 | 0 |
| ④ | `python scripts\smoke_agents.py` | 60–90 秒 | **是** | 约 3.5 分 |
| ⑤ | `python scripts\test_food_accuracy.py` | 60–120 秒 | **是** | 约 3.7 分 |

（均在 `core/` 目录下执行）

### 7.2 基线（2026-09，direct 后端启用前后实测）

| 指标 | dsh + low | direct + low | direct + off |
|---|---|---|---|
| 属性准确率（23 语料 / 29 断言） | 29/29 (100%) | 28/29 (97%) | **29/29 (100%)** |
| unknown 占比 | 0/35 (0%) | 0/34 (0%) | 0/34 (0%) |
| Agent1 耗时 | 1.9–4.3 s | 1.4–2.0 s | 1.0–1.1 s |
| Agent2 耗时 | 8.2–21.8 s | 11.9–13.6 s | **4.1–4.6 s** |
| 全链路 | 11.3–24.9 s | 12.6–15.6 s | **5.1–5.7 s** |
| 推荐条数 | 2–3 | 2–3 | **1–3（3 例实测 3/1/1）** ⚠️ |
| 单元测试（当时的口径，现在是 §7.3 的 335） | 183 | 230 | 230 |

**`direct + low` 那 1 项失败已定位，不是回归**：Agent1 偶然把"配辣椒油"写进 `note`，
合法触发了 `SPICY_KEYWORDS` 的 +1 规则（「面条」平 → 温）。见 §10.11。

#### `off` 的取舍（2026-09-17 实测定案：默认保持 `low`）

`off` 不是白送的加速，它有代价。**一句话：要省时省钱就设 `TA_REASONING_EFFORT=off`，
代价是推荐通常从 2–3 条降到 1 条。**

| 维度 | `low` | `off` |
|---|---|---|
| 全链路耗时 | 12.6–15.6 s | **3.0–6.3 s**（约快 2–4 倍） |
| 成本 | 基准 | **降一个量级**（输出占 92.2%，关思考后 Agent2 输出从 2,028 token 降到数百级） |
| 属性准确率 | 28/29 | 29/29（无损失） |
| 文案质量 | 基准 | **未退化**：方名、剂量、匹配度、理由、注意事项均完整 |
| **推荐条数** | 2–3 | ⚠️ **1–3，实测 3 例为 3 / 1 / 1** |

**为什么仍然默认 `low`**：首屏只给 1 条推荐，观感上像"没想出更多"，是明显的体验降级；
demo 阶段不值得为此省这点钱和几秒。等并发量上来、需要压成本或压延迟时再切 `off`，
那时 1 条推荐可以被接受。

**怎么切**（任选其一）：

1. 改 `core/app/config.py` 里 `TA_REASONING_EFFORT` 的默认值 `low` → `off`（改完需重启）；
2. 在环境变量里覆盖 —— ⚠️ 注意 `.env` 是 `override=True`，**会反向覆盖命令行设的值**，
   直接 `$env:TA_REASONING_EFFORT="off"` 不生效，见 §10.6。

> 样本说明：本节条数结论来自 3 个用例的实测，**不足以推翻上面 23 语料的准确率数据**；
> 但足以证明旧结论「`off` 下推荐条数不变（2–3）」是错的，上表已据此修正。

存档位置（本机，不入库）：`D:\work\tea-advisor-baselines\`。

### 7.3 各脚本能测到什么、**测不到**什么（重要）

| 脚本 | 测到的 | **测不到的** |
|---|---|---|
| `pytest` | 判定逻辑、护栏、JSON 护栏、凭据与日志安全、食药物质目录合规、体质参考与药典核对文档一致性、交接文档结构（335 项，全离线） | 真实模型行为；HTTP 层在缺 `[web]` extra 时会自动跳过 |
| `test_food_accuracy.py` | **只有 Agent1 的属性判定** | **推荐质量、Agent2 的任何东西、文案措辞、注意事项是否到位** |
| `smoke_agents.py` | 运行时启动、原始往返、Agent1 解析、全链路格式与条数 | 属性准确率（无断言，只打印）；安全性 |
| `smoke_offline.py` | 数据层→解析→规则兜底→护栏，**不调模型** | 模型相关的任何事 |
| `build_food_review_sheet.py` | 食性表**内部**一致性：别名歧义、变体与温度规则是否打架、跨表（茶饮 vs 饮片）四气、字段齐备性。生成人工审核核验单 | 食材偏性的**外部依据**（有没有可引来源、与来源是否一致）——那要靠人 + 阶段二的来源抓取 |

> **改动 Agent2 或提示词时，别只看 `test_food_accuracy.py` 通过就收工** ——
> 它根本不碰 Agent2。必须人工读一遍 `smoke_agents.py` 的输出。

### 7.4 已知的"期望脆弱点"

`test_food_accuracy.py` 的语料里有几条期望值对**模型措辞**敏感，不是判定逻辑不稳：

| 语料 | 期望 | 为何会飘 |
|---|---|---|
| 中午吃了碗兰州拉面 | `neutral` | Agent1 若在 `note` 写"配辣椒油/加辣"，会合法触发辛辣 +1 → `warm` |
| 早上…蔬菜沙拉 | `cool` | 实测出现过 `cold`（凉/寒的程度差异有主观性，脚本对冰饮类已放宽为元组） |

改语料前请先确认是"判定错了"还是"模型这次这么说的"。

---

## 8. 成本模型

### 8.1 定价（`deepseek-flash`，元/百万 token）

| | 空闲时段 | 高峰时段 |
|---|---|---|
| 输入（缓存命中） | 0.02 | 0.04 |
| 输入（缓存未命中） | 1 | 2 |
| 输出 | 4 | 8 |

高峰 = 北京时间**周一至周五 9:00–12:00、14:00–18:00**，其余为空闲。
官方定价页：<https://api-docs.deepseek.com/zh-cn/quick_start/pricing/>

### 8.2 实测单次用量与成本

| | 缓存命中输入 | 未命中输入 | 输出（含思考） |
|---|---|---|---|
| Agent1 | 8,960 | 193 | 314（思考 161） |
| Agent2 | 9,728 | 230 | 2,028（思考 1,213） |

| 时段 | 一次完整查询 | 1 元可跑 | 1000 次 |
|---|---|---|---|
| 空闲 | **1.02 分** | 98 次 | 10.16 元 |
| 高峰 | 2.03 分 | 49 次 | 20.33 元 |

**成本结构：输出占 92.2%，输入仅 7.8%；其中 Agent2 占 84%。**

三个推论：

1. **省钱的杠杆只有一个：缩短输出。** 输入便宜到可忽略（9,728 token 的缓存输入只值 0.0002 元）。
2. **Agent1 几乎免费**（0.163 分/次）—— 只跑属性判定的脚本可以随便跑。
3. **思考强度是最大旋钮**：`off` 让 Agent2 输出从 2,028 降到数百 token 级，
   全链路从 12.6–15.6 s 降到 5.1–5.7 s（见 §7.2 的 off 列）。

### 8.3 怎么自己复核（不信任上面的数字时）

官方返回的 `usage` 里有分项，直接用 httpx 调一次即可（`DirectAPIRuntime` 已把它记进日志）：

```python
# 关键字段
usage["prompt_tokens"]                    # 未命中输入
usage["prompt_cache_hit_tokens"]          # 命中输入
usage["completion_tokens"]                # 输出
usage["completion_tokens_details"]["reasoning_tokens"]   # 其中思考
```

> ⚠️ **不要用 `total_tokens` 算钱**：它是 `输入 + 输出 + 缓存命中输入` 的合计，
> 三个部分的单价差 200 倍，混在一起算会严重高估。

---

## 9. 数据维护

### 9.1 六个数据文件

| 文件 | 内容 | 规模 |
|---|---|---|
| `food_properties.json` | `foods[]` + `tea_drinks.items[]` + `_meta` | 147 条 |
| `herbs.json` | `_meta` + `herbs[]`（含剂量上限、禁忌、归经） | 35 味 |
| `constitution.json` | 9 型体质 + `one_line` / `principles` / `avoid` | 9 型 |
| `food_medicine_catalog.json` | 国家卫健委食药物质目录（4 批公告）汇编，**只用于合规自检，不参与判定** | 106 种 |
| `herb_nature_reference.json` | 《中国药典》2020 年版一部的性味归经记载 + 与项目的比对结果，**只用于核对，不参与判定** | 35 味 |
| `herb_evidence_sources.json` | 饮片侧来源登记表：属性依据（域 I）+ 体质适配依据（域 II）+ 来源注册表，**运行时读**，只用来生成 `basis.references` | 35 味 + 24 条 |

字段含义写在各自的 `_meta.field_notes` 里，**改结构时同步改它**。

### 9.2 加条目的正确姿势

**直接编辑 JSON**，按 `indent=2` 的现有风格插入，并补齐 `review_*` 字段。理由：diff 干净、可评审。

**若新条目「必须煎煮」**（质地坚实、保温杯焖不出味），在它的 `brewing` 里加
`"requires_cooking": true` —— 候选清单会据此标「⚠️ 须煎煮」，兜底与护栏会自动改用煎煮方式
（机制见 `docs/agent2-9types-brew-plan.md`）。前提是 `brewing.note` / `prep` 里**真的写着**
「煮/煎/炖」依据：`tests/test_safety.py::test_cook_required_flag_has_textual_basis` 会检查这一点，
标记不能凭空出现。反过来，写「久煮尽失」的后下类饮片**不要**加这个标记。

### 9.3 审核三态（**不要为了界面好看而批量置 approved**）

| 状态 | 效果 |
|---|---|
| `approved` | 真·硬规则库，0.9，界面**不**标注 |
| `pending` | 0.9，但界面必须标「待验证」（**当前 147 条全部是这个**） |
| `rejected` | 降为组合推理档 0.6，不再作硬规则 |

`approved` 只应由具备资质的中医师/中药师填写，并同时填 `reviewed_by` / `reviewed_at`。
标记密度就是审核进度的可见反馈。

### 9.4 ⚠️ `scripts/` 下三个脚本都是**冻结的一次性批次脚本**

| 脚本 | 真相 |
|---|---|
| `add_food_entries.py` | `NEW_ENTRIES` 是**源码里硬编码的 16 条历史批次**，**不是通用加条目工具**。会全量重写整个文件（大 diff）。幂等靠 id+name 双重去重；但去重集合在循环外算一次，往列表里追加时要自己保证 id 唯一 |
| `add_review_fields.py` | 加布尔 `reviewed`。**现在跑是空操作**（147 条都已有该字段） |
| `patch_food_table.py` | `reviewed` → `review_status` 三态迁移 + 4 条写死的条目修正 |

**历史执行顺序不可颠倒**：

```
add_review_fields.py   →   patch_food_table.py
  （先补 reviewed 布尔）      （再把 reviewed 迁移为 review_status）
```

三者都支持 `--dry-run`。**改任何数据文件前先跑 `--dry-run`。**

### 9.5 食药物质目录与合规自检（`check_herb_catalog.py`）

**与 §9.4 那三个脚本不同，`scripts/check_herb_catalog.py` 是长期可重复运行的只读工具，不是一次性批次脚本。**

它把 `herbs.json` 的饮片白名单逐条对照 `food_medicine_catalog.json`
（国家卫健委"按照传统既是食品又是中药材的物质目录"，4 批公告共 106 种），输出三类清单：

| 状态 | 含义 | 该做什么 |
|---|---|---|
| 在目录内 | 目录里有对应条目 | 无需处理 |
| 不在目录内 | 四批公告均未收录 | 人工决定「删掉」还是「标注仅作参考」 |
| 需人工判断 | 目录里有相近但可能不是同一物的条目 | 人工判断，脚本不替你选 |

```bash
cd core
python scripts/check_herb_catalog.py                        # 人读表格
python scripts/check_herb_catalog.py --format md --out ../docs/catalog-compliance.md
python scripts/check_herb_catalog.py --strict               # 有遗留项则 exit 1，可进 CI
```

`docs/catalog-compliance.md` 是**脚本生成的，不要手工编辑**。

维护时要知道的三件事：

1. **目录数据自证。** 每个批次在 `batches[].verbatim` 里保留了公告原文串，
   任何人都能拿它和政府网页逐字对照。脚本启动时会用 `split_items()` 校验
   「verbatim 数出来的条数 == 声明的 count」，不一致就打警告。
   ⚠️ 解析陷阱：括号内的顿号不是分隔符 —— `枣（大枣、酸枣、黑枣）` 是 **1** 条不是 3 条。
2. **名称桥接是人工判断，刻意放在脚本里而不是数据文件里**（`HERB_ALIASES` /
   `NEEDS_HUMAN_JUDGMENT` 两个常量，每条都写明理由），这样"外部权威数据"和
   "我方的映射判断"不会混在一起。当前登记：陈皮→橘皮、红枣→大枣、生姜→生姜（目录括号内并列名）；
   橘红走 `NEEDS_HUMAN_JUDGMENT`。
3. **「不在食药物质目录」≠「不能当食品用」。** 例如玫瑰花走的是卫生部公告
   2010 年第 3 号（允许重瓣红玫瑰作为普通食品生产经营）这条路。所以脚本只做目录比对，
   不会输出"违规"结论。各味的具体背景见 `docs/catalog-compliance.md` 的「待决策项与合规背景」。
4. **人工处置决定登记在脚本的 `DECISIONS` 常量里**（带决定日期、依据、要做的事、实施状态），
   渲染进 `docs/catalog-compliance.md` 的「处置决定（已登记）」小节。
   ⚠️ `status` 为 `待实施` 的决定**尚未生效**，别把它当成已经改好。
   登记位置刻意选在脚本里：这样决定与机械核对结果在同一份可重生成的产物里，
   不会出现"文档说改了、代码没改"的漂移。

改动 `herbs.json` 的饮片名单后，**重新跑一次这个脚本并重新生成文档**。

### 9.6 性味归经核对（`build_herb_crosscheck.py`）

把饮片的四气/五味/归经与**《中国药典》2020 年版一部**逐条对照。
主源是国家药典委员会「中国药典在线版」的公开只读接口，不是第三方镜像：

```bash
cd core
python scripts/build_herb_crosscheck.py --refresh   # 联网，从官方接口重建参考数据
python scripts/build_herb_crosscheck.py             # 离线，从参考数据渲染 Markdown
python scripts/build_herb_crosscheck.py --check     # 离线，只校验一致性（可进 CI）
```

```python
POST https://ydz.chp.org.cn/front-api/search   {"keyword": "...", "bookId": 1}
GET  https://ydz.chp.org.cn/front-api/entry/{id}   # 返回 htmlContent，含【性味与归经】
```

当前结果：**35 味中一致 27、不一致 7、药典未收载 1**。不一致项见
`docs/herb-nature-crosscheck.md` 第 3 节，**脚本只报告，不改数据**，以哪个为准由人定。

**2026-09-17 已决定：7 处不一致先保留项目值，等 nanple 复核后再定。** 决定与每处的
「差异影响」都写进了 `docs/herb-nature-crosscheck.md` 与参考数据的 `open_items`。

> ⚠️ 关于影响面，有一处**必须记住的反直觉结论**：饮片的 nature / flavors / meridians
> **不参与任何确定性判定**。`safety.py` 只读 `name`/`max_daily_g`/`cautions`/
> `unsuitable_for`/`suitable_constitutions`；`matcher` 的 `match_natures` 匹配的是
> **整餐四气**（`parsed.overall_nature`，来自 Agent1），不是饮片四气；两个壳渲染推荐饮片时
> 只打印 `name`/`amount_g`/`role`。唯一实质消费者是 `agent2_recommend.py:62-66` 把候选
> 描述交给 Agent2 的提示词，属**软性影响**。所以这 7 处差异改了也不会改变任何判定结果，
> 「先保留」不引入功能风险。（文档 §3.1 有完整取证；先前有一处文档写反了，已更正。）

维护时要知道的五件事：

1. **不要用 PowerShell 数行数**（见 §1.4 的警告），也别用第三方药典镜像当主源 ——
   官方接口能直接拿到 `htmlContent` 原文，还带页码和在线链接。
2. **四气降档是项目约定，不是药典原文**：药典有「微寒/微温」，项目只有 5 档，脚本按
   `微寒→凉、微温→温` 降档（2026-09-17 已认可）。**药典原文一律保留**在
   `pharmacopoeia.nature_word` 与 `xingwei_verbatim`，文档表格也单列「药典四气（原文）」
   并用 `†` 标出用了降档的行。改约定后跑 `--recompute` 即可**离线**重算派生字段，无需重抓。
3. **`project` 字段是快照**，有测试卡住它与 `herbs.json` 实时一致。改了 `herbs.json`
   的 nature/flavors/meridians 就必须 `--refresh` 重建，否则 `pytest` 会失败。
4. **《中华本草》那一列本次没有数据**，原因是公开渠道取不到（药智网需登录、
   tcmdoc.cn 403、中医世家拒连），而 yao86.com 虽引用《中华本草》但展示的是药典值。
   完整实测记录在参考数据的 `_meta.zhonghua_bencao_status`。**该列空缺 = 未核实，
   不等于与药典相同。**
5. **项目 `effects` 不照抄药典【功能与主治】是刻意的**：`herbs.json` 的
   `_meta.field_notes` 要求"必须使用养生类措辞，禁止疗效承诺"。所以别把
   「把 effects 换成药典原文」当成修 bug。

### 9.7 交接文档与挂起清单

| 文档 | 用途 |
|---|---|
| `docs/handover.md` | **项目全貌交接文档**：项目是什么、七条核心设计原则、目录与分层、当前状态、31 条已定决策、工作区状态、接手前 30 分钟 |
| `docs/pending-items.md` | **挂起事项的唯一真源**：A 类对外服务硬阻碍 / B 类等 nanple / C 类等外部资料 / D 类等决定 / E 类技术债 |

**约定**：`maintenance.md` 与 `handover.md` 只放摘要 + 指向 `pending-items.md` 的链接，
**不要把挂起明细复制过来**，否则两处会不一致。挂起项解决后只更新 `pending-items.md`。

这两个文档有 26 项结构测试（`tests/test_handover_docs.py`）守着：章节齐备、
挂起项 ID 唯一且都有责任人与状态、**引用的仓库路径真实存在**、文档里没有 Key 材料。
所以重构后如果文档引用了已改名的文件，`pytest` 会直接报错。

### 9.8 饮片侧来源登记表（`build_herb_sources.py`）

**与 §9.5 / §9.6 同类：长期可重复运行的只读工具，不是一次性批次脚本。**

它维护 `core/data/herb_evidence_sources.json`（挂起项 E3 的落地物）。事实源与产物：

| 角色 | 路径 | 谁生成 |
|---|---|---|
| 事实源 | `core/data/herb_evidence_sources.json` | 域 I 由脚本派生；域 II 与 `_meta` 人工录入 |
| 人读登记表 | `docs/herb-evidence-sources.md` | 脚本渲染，**请勿手工编辑** |

```bash
cd core
python scripts/build_herb_sources.py            # 只打印摘要，不写文件
python scripts/build_herb_sources.py --write    # 落盘 JSON + 渲染 Markdown
python scripts/build_herb_sources.py --check    # 只校验不写盘（可进 CI）
```

**分工必须记住**：域 I（逐味）**从 `herb_nature_reference.json` 派生**，
一个字都不手写，所以两份表格不可能漂移；域 II（24 条）与 `_meta` 是**人工录入**的，
本脚本只重算 `_meta.counts`、原样保留其余内容。`tests/test_herb_evidence.py` 里有
一条等价于 `--check` 的测试，**手工改 JSON 或改那份 Markdown 都会让 `pytest` 变红**。

它把结果交给 `safety.herb_evidence(herb_names, constitution)`，再由
`orchestrator._build_basis()` 装进 `Basis.references`，最后两个壳各自渲染。

维护时要知道的五件事：

1. **`_build_basis()` 是 `Basis` 的唯一构造点**，三处返回路径全走它。测试用 AST
   （不是 grep）数 `Basis(...)` 的调用点数，并用同一条守卫确认 `core/app/` 全文
   不再有 `def build_basis` —— 那个函数曾是一份**没有任何调用点**的同名实现，
   改它等于没改，而输出表面完全看不出来。
2. **域 II 条目不得带 `field` / `verdict` 这类键。** 带了它就成了 `herbs.json` 的
   `rulings`（软约束豁免登记）的第二本账。域 II 回答的是「**为什么推荐**」，
   `rulings` 回答的是「忌/慎用该怎么落地」，两件事。有测试守着。
3. **`nhc-food-medicine-2021` 永不作体质依据**（只证明合规身份）。它在注册表里
   登记在册是为了说明「为什么不能用」，`constitution_entries` 引用次数必须为 0。
4. **`herb_evidence()` 只返回命中本次原料的来源**，且域 II 只在传了 `constitution`
   时参与。把体质级的概述当成某一味的依据，是这条链最容易犯的错。
5. **覆盖是不完整的，且必须如实呈现**：属性依据 34/35 味（茉莉花药典未收载），
   体质依据只有 14/35 味。界面脚注与 `EvidenceReference` 的文档字符串都写着同一句边界：
   来源支持的是**原料与调养方向**，不是本程序生成的**具体搭配与克数**。
   `review_status: pending` 一律**不进界面** —— 那是审核流程的状态，不是来源可信度的状态。

---

## 10. 排错手册

### 10.1 改了代码但行为没变 / 报出莫名其妙的错

**症状**：请求返回旧结构；或旧进程报 `KeyError: 'xxx'`。
**原因**：**端口被旧服务占用**。新启动的 uvicorn 绑不上端口直接退出（Windows 上表现为 exit 1、无输出），
而请求打到了那个跑旧代码的进程上。
**处置**：

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen | ForEach-Object { Get-Process -Id $_.OwningProcess | Select-Object Id, ProcessName, StartTime }
Get-Process | Where-Object { $_.ProcessName -match 'python' } | Stop-Process -Force
```
**预防**：uvicorn 加 `--reload`；或每次测完就把服务关掉。

### 10.2 命令报 `exit code: 1` 但输出完全正常

**原因**：管道被下游提前关闭。`... | Select-Object -First 5` 取够就关管道，
上游进程收到断管，Windows 上结算为 exit 1。
**处置**：忽略；要确认就重跑一次不接管道，取 `$LASTEXITCODE`。

### 10.3 存档的中文输出变成乱码，或被判为二进制文件

**原因**：PowerShell 重定向原生命令输出时的编码不一致。
实测同一批脚本，`Tee-Object` 写出了 **UTF-16**（带 FF FE BOM），而 `Out-File -Encoding utf8` 正常；
且 PowerShell 会用 cp936 解码原生命令的 UTF-8 输出，写入时再次变形。
**处置**：脚本自己已经 `reconfigure(encoding="utf-8")`；在 PowerShell 侧统一用
`| Out-File -FilePath x.txt -Encoding utf8`。若已拿到 UTF-16 文件，转码即可。

### 10.4 终端里中文乱码

**原因**：Windows 控制台默认 GBK。
**处置**：`scripts/` 与 `ui/terminal/chat.py` 都在入口 `reconfigure(encoding="utf-8")`，
终端壳还额外处理了 **stdin**（重定向时 stdin 用 locale 编码，不指定会把中文输入解成乱码）。

### 10.5 `pip.exe` / `uvicorn.exe` 报错或无声失败

**原因**：`core/.venv` 是在目录还叫 `backend` 时创建的，Windows 的控制台脚本 shim 把绝对路径写死在 exe 里。
**处置**：一律用 `python -m`。或重建：

```powershell
cd core
Remove-Item .venv -Recurse -Force
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,web]"
```

### 10.6 设了环境变量却不生效

**原因**：`config.py` 用 `load_dotenv(..., override=True)` 加载 `.env` 与 `credentials.env`，
**文件里定义过的键会覆盖进程环境变量**；文件里没有的键则不受影响。
**处置**：`TA_*` / `APP_*` 这类应用配置改文件（刻意的——为了让项目配置压过 DSH 自己设的 `DSH_HOME`）。
但 **`DEEPSEEK_API_KEY` 不受此影响**：配置文件里不再定义它，
所以 `$env:DEEPSEEK_API_KEY` 能正常生效（这也是终端与脚本给 Key 的方式）。

### 10.7 `dsh: .env sets "DSH_HOME", which only the launching environment may set`

**原因**：`.env`（**含注释里**）出现了任何 `DSH_*` 变量。
**处置**：把 `DSH_HOME` 移到 `credentials.env`（dsh 不扫描该文件名）。
（API Key 不在文件里，所以与这条无关。）

### 10.7b 界面填了 Key 却报 `NO_API_KEY`

**原因**：`Authorization` 头格式不对（缺 `Bearer` 前缀、含空白、超长）→
`extract_api_key()` 返回 `None` → 当作"没给 Key"。
**处置**：这是**刻意**的（宁可回 400 也不要 500）。检查前端拼头的方式。
注意 HTTP 头只能是 ASCII，Key 里混入中文会导致请求在客户端就发不出去。

### 10.7c 用户没填 Key 时连"请咨询医师"都看不到

**原因**：凭据校验写在了高风险分支**之前**。
**处置**：安全分支必须排在前面——它不调用模型、不花钱，理应无条件可用。
见 `test_high_risk_branch_works_without_any_key`。

### 10.8 模型返回空正文（`content` 为空串）

**原因**：思考模式下 `max_tokens` 太小，被思考吃光。
实测 `max_tokens=64` 时 64 个 token 全进 reasoning，正文为空。
**处置**：调大 `TA_MAX_TOKENS`（默认 8192 足够），或设 `TA_REASONING_EFFORT=off`。
`DirectAPIRuntime` 已对这个情况给出明确报错。

### 10.9 在界面填了 Key 却报 `NO_API_KEY`

**原因**：`Authorization` 头格式不对（缺 `Bearer` 前缀、含空格、超长）→
`extract_api_key()` 返回 `None` → 当作"没给 Key"。
**处置**：这是**刻意**的（宁可回 400 也不要 500）。检查前端拼头的方式。
另外注意 HTTP 头只能是 ASCII —— Key 里混入中文会让请求在客户端就发不出去。

> 历史提醒：本项在 v0.1 时表现为"静默回退到服务端兜底 Key"，靠 `meta.key_source="server"`
> 才能察觉。v0.2 移除了兜底，所以现在会直接报 `NO_API_KEY` —— 更吵，但不会有人在你不知情时花钱。

### 10.10 关键词子串把无关条目拉进表

**症状**：说「麻辣烫」把「辣椒」也识别出来（因为辣椒的关键词含"麻辣"）。
**原因**：字符串子串匹配的固有歧义，已记录在 `docs/three-layer-architecture.md` 的「已知局限」。
**处置**：**不要当 bug 修**。彻底解决需要菜品别名库或分词。
在 `--offline` 模式下更容易看到，因为 `match_foods` 是"表里哪些条目在句子里出现过"，
而不是"识别出你吃了什么"。

### 10.11 同一句话两次判定结果不同

**原因**：模型层有运行间波动，会传导到判定。最常见的是 Agent1 在 `note` 里补了
"配辣椒油/加辣"之类的措辞，**合法**触发 `SPICY_KEYWORDS` 的 +1。
另有 `蔬菜沙拉` 在 `cool`/`cold` 之间摆动（程度差异有主观性）。
**处置**：先看 `verification.detail` 里的判定过程，确认是"规则被合法触发"还是"真错了"。
`detail` 就是为这种排查设计的。

### 10.12 `pytest` 报 `ModuleNotFoundError: fastapi`

**原因**：`fastapi` 在 `[web]` extra 里，只装了 `.[dev]`。
**处置**：`pip install -e ".[dev,web]"`；或只跑核心测试（HTTP 层测试会自动 skip）。

---

## 11. 已知局限与开放决策

### 11.1 已知局限（完整版见 `docs/three-layer-architecture.md`）

1. 规范名精确命中时不叠加模型给的烹饪修正（需要时在表里单列 `variant_nature`）
2. 关键词子串会拉进无关条目
3. **第二层 `combine()` 未接入主流程**（已实现并测试，`resolve_food` 目前只做单食材）
4. 数据未人工审核（147 条全 `pending`）
5. `--offline` 只能识别表内条目
6. 中文标签虽已收敛到 `/api/meta`，但 `cooking` 标签的展示仍只在前端用到（终端壳未展示）

### 11.2 开放决策（留给后续）

| # | 决策点 | 现状与建议 |
|---|---|---|
| 1 | ~~**默认思考强度** `low` vs `off`~~ → **2026-09-17 已定：维持 `low`** | 实测结论：`off` 更快（12.6–15.6 s → 3.0–6.3 s）更省（降一个量级）、准确率无损失，**但推荐条数常从 2–3 掉到 1 条**（3 例实测 3/1/1）。demo 阶段不接受这个降级。取舍与切法见 §7.2 末尾 |
| 2 | 数据人工审核 | 需要资质人员；审核完逐条改 `review_status` + `reviewed_by` |
| 3 | `combine()` 接入 | 属改核心，需单独立项与回归 |
| 4 | `ui/web` 展示判定过程 | 现在只有悬停 tooltip；可考虑铺开成终端那种逐项列表 |
| 5 | Web 壳支持 `--offline` | 需要把离线装配逻辑暴露成接口或前端实现（注意别越过 `ui/`→`core/` 的分层线） |
| 6 | 异步任务 + 进度反馈 | 全链路 5–25 秒是主要体验瓶颈 |
| 7 | **体质模型 5 型 → 9 型**（补阴虚/血瘀/气郁/特禀，对齐 GB/T 46939-2025） | **卡在数据，不在代码。** 代码约 100 行（枚举、`constitution.json` 4 条、提示词 9 行（2026-09-18 已补齐 9 型方向提要）、测试 +6 项）；数据才是大头：`herbs.json` 里 34 味 × `suitable_constitutions` + 27 味 × `unsuitable_for`，针对 4 个新体质共约 **244 个配伍判定**（2026-09-17 已落地 15 格，余 239 格）。而 **GB/T 46939-2025 只规定体质分类、问卷、计分与判定阈值，不提供任何饮食或饮片建议** —— 这 244 条无标准可依，必须由懂中医的人判定。防错已就位（见下），所以"只加枚举忘了补数据"现在是**安全的失败**，可以分次推进 |

> **第 7 项的前期资料已备好（2026-09-17 加）：`docs/constitution-9-types.md`**
>
> 九型的特征与饮食方向已整理成带出处的汇编，JSON 是事实源、MD 由脚本渲染：
>
> ```bash
> cd core
> python scripts/build_constitution_doc.py            # 从 JSON 重新渲染 MD
> python scripts/build_constitution_doc.py --check    # 只校验一致性（可进 CI）
> ```
>
> 用这份资料时必须清楚三件事：
>
> 1. **文档里的 A 栏（国标特征）是转引，不是标准正文。** 标准正文取不到：
>    openstd 的在线预览在非浏览器环境只返回回退页，中国标准出版社的正版 PDF 需积分。
>    要升级成逐字原文，得先用浏览器打开 openstd 在线预览或取得正版 PDF。
> 2. **B 栏（饮食方向）不是国标内容**，来源是起草人访谈与官方科普；而且其中较完整的一份
>    是广东省中医药局 2023 年的文章，分类框架源自 **2009 年学会标准**，早于新国标。
> 3. **C 栏实时取自 `core/data/constitution.json`**，并有测试卡住快照与实时数据的一致性 ——
>    改了项目数据而没更新 JSON 快照，`pytest` 会直接失败，不会静默渲染一份错文档。
> 4. **九型的 id 已于 2026-09-17 全部确认**（阴虚质 `yin_deficiency`、血瘀质 `blood_stasis`、
>    气郁质 `qi_stagnation`、特禀质 `special_diathesis`），扩到 9 型时直接用。
>    ~~注意 nanple 的问卷项目用 `phlegm_dampness`，和本项目的 `phlegm_damp` 拼写不同，接入要适配。~~
>    **2026-09-18 已对齐**：仓库内 `tcm-constitution-questionnaire/` 已按方案①改为 `phlegm_damp`
>    （3 文件 8 处），接入**不再需要适配层**。防回潮由 `core/tests/test_questionnaire_id_alignment.py` 守住；
>    方案与改动清单见 `docs/b2-constitution-id-alignment.md`。

> **关于第 7 项的防错（2026-09-17 加）**
>
> * `filter_by_constitution` 在"该体质在 `herbs.json` 里一条数据都没有"时抛
>   `MissingConstitutionDataError`，**不再静默退化成"目录前 N 味"**。
>   实测后果：静默退化会让模型拿未经筛选的候选集去配 —— 阴虚质会拿到
>   龙眼肉、红枣、生姜等在温补辛温之品，**方向相反，而且从输出表面看不出来**。
> * `matcher._constitution_default` 在缺数据时退到平和质通用搭配，并在 `fit_reason`
>   里写明"该体质的专属搭配尚未收录"。规则兜底层的契约是"永远给出合法且安全的搭配"，
>   不能抛异常变成 500。
> * 整个 `herbs.json` 缺失时仍返回空列表（`load_herb_catalog` 的既有契约），不误报。
>
> ⚠️ 顺带查清：`matcher.CONSTITUTION_DEFAULT` 目前实测是**死代码** ——
> 五条规则的 `match_natures` 并集覆盖了 `Nature` 的全部六个取值，
> 所以 `_pick_rule` 永不返回 `None`，那条分支正常流程走不到。
> `fallback_recommend` 对体质参数的实际使用只有 `unsuitable_for` 那句注意事项。
> 若将来要按体质分发兜底搭配，得先让 `_pick_rule` 有返回 `None` 的路径。

---

## 12. 本次转型变更史

从"微信小程序 demo"转成"本地桌面助手 + 开源库"的完整过程，按提交顺序：

| 提交 | 做了什么 | 为什么 |
|---|---|---|
| `fb4c51a` | 删除 `miniprogram/`（17 文件），新增 `ui/terminal/chat.py`、`ui/web/index.html`；CORS 收紧；`pyproject` 拆分 `[web]` extra；新增 LICENSE/CONTRIBUTING；重写 README | 个人主体无法通过相关类目审核，放弃小程序；核心逻辑一行未动 |
| `46d67ed` | `backend/` → `core/`，统一 `BACKEND_DIR` → `CORE_DIR`；CONTRIBUTING 新增契约 8（`ui/` 单向依赖 `core/`） | 没有前后端之分了，`backend` 名不副实 |
| `3b9f8f5` | 网页壳补齐置信度与「待验证」标注 | 文档声称两个壳显示规则一致，实际网页壳完全没读 `verification`，会把 `llm` 档推测当确定结论展示 |
| `e74acb3` | 新增 `GET /api/meta`；两个壳不再各自硬编码中文标签与 0.3 阈值 | 标签散在三处，改一处忘一处就会让安全边界漂移 |
| `26b57d3` | 网页壳新增「测试指引」面板 | 外部测试人员面对满屏「待验证」会当缺陷上报 |
| `63ac5c3` | **支持用户自带 API Key**：新增 `direct_api.py` 直连后端（默认）、`api/auth.py`、`meta.key_source`、网页 Key 输入框；`tests/test_key_handling.py`（47 项，含日志安全）；`start-*.cmd` | dsh 的 Key 绑子进程，做不到逐请求 Key |
| `3c63c7f` `9ffa5ea` | 文档与实测数字对齐（230 项）；澄清两份 `.env` 都是可选的 | 避免文档把人带偏 |

### 12.1 转型中修掉的历史 bug（都是"文档写了但代码没做到"）

| 问题 | 位置 |
|---|---|
| 提示文案教用户把 `DEEPSEEK_API_KEY` 写进 `.env`，而 dsh 会因此拒绝启动 | `config.py::missing_credentials_hint`（同名错误曾在 `check_setup.py` 里也有一处） |
| 提示跑一个不存在的脚本 `scripts/smoke_agent1.py` | `check_setup.py` |
| 硬编码 `D:\work\tea-advisor\dsh-home`（换台机器就没用） | `check_setup.py`、`runtime.py` 注释 |
| 网页壳忽略 `verification`，把低置信度属性当确定结论 | `ui/web/index.html` |
| 4 处文档数字漂移：130/143/20/45 项 → 实际 146/34/183 | README、docs |
| dsh 后端下用无效 Key 被包装成"饮食解析失败" | `orchestrator`（已改为 `API_KEY_REJECTED`） |

---

## 13. 后续路线建议（按性价比排序）

1. **人工审核 147 条食性数据** —— 唯一阻碍"对外提供服务"的事项，且只有人能解。
   核验单已就绪：`docs/food-properties-review-sheet.md`（由 `scripts/build_food_review_sheet.py`
   生成，**只读**、可重跑、`--check` 可进 CI）。④层内部矛盾（不依赖外部来源）已经跑完，
   可先清；①②③ 层需外部来源，按「官方优先 + 多源兜底 + 无源标空」推进，
   第一批从 ★ 主食/乳饮/水产 开始（指南覆盖最好，最可能先产出 `approved`）。
2. **异步任务 + 两级返回** —— 先回显「我理解到的」，再出推荐。当前 5–25 秒是最大体验瓶颈。
3. **`combine()` 接入主流程** —— 让「番茄炒蛋」这类整菜名能走第二层，而不是整体落到 LLM。
4. **决定默认思考强度** —— 攒够样本（比如各跑 5 次准确率 + 盲评 20 条推荐文案）再定。
5. **Web 壳支持离线模式** —— 让测试人员能零成本自由探索。
6. **菜品别名库 / 分词** —— 根治关键词子串歧义。
7. **打包分发**（PyInstaller / 便携 zip）—— 让非技术用户不必先装 Python。

---

## 附录 A：常用命令速查

```powershell
$R = 'D:\work\tea-advisor'; $PY = "$R\core\.venv\Scripts\python.exe"

# 使用
& $PY "$R\ui\terminal\chat.py" --resolve 冰啤酒          # 0 成本
& $PY "$R\ui\terminal\chat.py" --offline "中午吃了麻辣烫"   # 0 成本
& $PY "$R\ui\terminal\chat.py"                           # 走模型

# 验证
Set-Location "$R\core"
& $PY -m pytest -q                                       # 335 项
& $PY scripts\smoke_offline.py
& $PY scripts\check_setup.py
& $PY scripts\test_food_accuracy.py                      # 真实模型，约 3.7 分
& $PY scripts\smoke_agents.py                            # 真实模型，约 3.5 分

# 服务
Set-Location "$R\core"; & $PY -m uvicorn app.main:app --port 8000

# 排查
Get-NetTCPConnection -LocalPort 8000 -State Listen
git -C $R status --short
git -C $R log --oneline -10
```

## 附录 B：新增一个界面时要做什么

1. 在 `ui/` 下新建子目录（`ui/gui/`、`ui/tui/`…）
2. 只 `import app.*`，**不得**改 `core/app/domain`、`services`、`agents`
3. 需要标签/阈值 → 用 `/api/meta`（或直接 `import app.domain.enums`）
4. 需要新字段 → 先改 `core/app/domain/models.py` 并同步**所有已有壳**
5. 不要在新壳里再抄一份中文映射表 —— 用 `/api/meta`（见 §4.1 第 4 条）
6. 完成后跑一次契约 8 的验证：**临时把 `ui/` 改名移走，`core/` 下 `pytest` 与 `smoke_offline.py` 仍应全绿**
