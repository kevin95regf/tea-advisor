# 中医饮食茶饮推荐（Demo）

用户口述今天吃了什么 → 结合中医体质 → 推荐**药食同源饮片**的冲泡搭配。

> ⚠️ **本项目的所有输出仅供日常饮食参考，不构成医疗建议，也不能替代医师的诊断与治疗。**
> 孕期、哺乳期、经期、儿童、慢性病患者及正在服药者，请先咨询执业医师或药师。

---

## 当前进度

| 阶段 | 状态 |
|---|---|
| 数据层（20 味药食同源饮片 + 5 型体质） | ✅ 完成 |
| 安全护栏（白名单 / 剂量 / 禁用表述 / 高风险人群） | ✅ 完成，45 项测试通过 |
| JSON 解析护栏（围栏剥离 / 校验 / 失败重试） | ✅ 完成 |
| 双 Agent 提示词与实现 | ✅ 完成，**真实模型已跑通** |
| 规则兜底（模型失败时降级） | ✅ 完成 |
| FastAPI 接口 `/api/analyze` | ✅ 完成，HTTP 端到端实测通过 |
| 网页 demo | ✅ 完成 |
| 微信小程序 | ⏸ 待做 |

### 实测延迟（3 条真实语料，reasoning_effort=low）

| 环节 | 耗时 |
|---|---|
| Agent1 饮食解析 | 1.1 – 4.6 s |
| Agent2 茶饮推荐 | 11.5 – 15.0 s |
| **全链路** | **12.9 – 16.3 s** |
| 高风险人群分支 | ~0 s（不调用模型，直接引导就医） |

`TA_REASONING_EFFORT` 对延迟影响极大，实测同一任务：

| effort | Agent2 耗时 | 推荐条数 |
|---|---|---|
| max | 19.2 s | 3 |
| high | 10.1 s | 3 |
| **low（默认）** | **8.2 s** | **3** |
| off | 2.7 s | 1 |

本模型支持 `max` / `high` / `low` / `off`，`medium`、`none`、`minimal` 会导致启动失败。

> ⚠️ 注意：12 秒以上的响应时间对小程序体验偏长，`wx.request` 默认超时需显式放宽。
> 后续建议改为异步任务 + 轮询，并利用「两级返回」先把 Agent1 的解析回显给用户。

---

## 快速开始

### 1. 配置

本项目有**两个**配置文件，分工不能混：

| 文件 | 放什么 | 为什么 |
|---|---|---|
| `.env` | 应用配置：`TA_*` 模型参数、端口、超时 | 可以入库模板 |
| `credentials.env` | `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`DSH_HOME` | **不能放 `.env`** |

**为什么凭据必须单独一个文件**：`dsh` 启动时会扫描 workspace 根目录的 `.env`，
一旦发现 `DSH_HOME` / `DSH_MAX_TOKENS` 这类 `DSH_*` 变量或凭据变量就**直接拒绝启动**：

```
Error: dsh: .env sets "DSH_HOME", which only the launching environment may set
```

因为它们决定进程如何启动、从哪里加载代码与指令、如何联网，属于「启动环境专属」变量。
所以本项目约定：`.env` 里只出现 `TA_*` 与 `APP_*`，凭据与 `DSH_HOME` 放 `credentials.env`，
由 `app/config.py` 读取、`app/agents/runtime.py` 注入子进程环境。

```powershell
cd D:\work\tea-advisor
Copy-Item .env.example .env
Copy-Item credentials.env.example credentials.env
notepad credentials.env      # 填入 DEEPSEEK_API_KEY 与 DSH_HOME
```

两个真实配置文件都已被 `.gitignore` 忽略（模板文件会入库）。

### 2. 安装依赖

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

### 3. 自检（秒级，不调用模型）

```powershell
python scripts\check_setup.py
```

### 4. 离线冒烟（不调用模型，验证数据层与护栏）

```powershell
python scripts\smoke_offline.py
```

### 5. 真实模型冒烟（需要 API Key）

```powershell
python scripts\smoke_agents.py
python scripts\smoke_agents.py --only a1     # 只测解析器
python scripts\smoke_agents.py --case 1      # 只跑第 1 条语料
```

首次运行会启动 `dsh` 子进程并生成 profile，约十几秒。子进程 stderr 在 `backend/var/dsh_runtime.log`。

### 6. 启动服务

```powershell
python -m uvicorn app.main:app --reload --port 8000
```

- 网页 demo：<http://127.0.0.1:8000/demo>
- 接口文档：<http://127.0.0.1:8000/docs>
- 自检：<http://127.0.0.1:8000/healthz>

手机访问：把 `127.0.0.1` 换成电脑局域网 IP（`ipconfig` 查看），并确保防火墙放行 8000 端口。

```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 7. 跑测试

```powershell
python -m pytest -q
```

---

## 架构

```
用户口述
   │
   ▼
[Agent 1 饮食解析器]  ──►  ParsedMeal（结构化 JSON）
   │                        食物 / 寒热属性 / 五味 / 烹饪方式 / 时段 / 把握度
   ▼
[Agent 2 中医推荐器]  ──►  Recommendation[]（1–3 条）
   │  ↑ 输入：Agent1 的 JSON + 体质 + 白名单候选饮片
   ▼
[安全护栏 safety.py]  ──►  白名单 / 剂量裁剪 / 禁用表述 / 体质契合
   │
   ▼
 接口响应（必带 disclaimer）
```

**两个 Agent 通过一个 JSON 通信，谁都不越界。**

- Agent1 管「你吃了什么」，不做推荐、不判断体质。
- Agent2 管「配什么泡」，只能在白名单候选集内选，不开方剂、不超剂量。

### 为什么要有白名单和规则兜底

提示词里写十遍「不要开方」，不如**让模型无方可开**：
Agent2 只能从 `herbs.json` 的 20 味里挑，候选集由 `safety.py` 按体质预先收敛。
即使模型完全不可用，`matcher.py` 的规则兜底仍会给出合法、安全、不超剂量的搭配
（响应里 `meta.degraded = true`）。

---

## 目录结构

```
tea-advisor/
├─ .env.example                  应用配置模板（TA_* / APP_*）
├─ credentials.env.example       凭据模板（API Key / DSH_HOME，不能放 .env）
├─ backend/
│  ├─ app/
│  │  ├─ main.py                  FastAPI 入口、/healthz、/demo、目录与免责声明接口
│  │  ├─ config.py                环境变量集中读取
│  │  ├─ api/analyze.py           POST /api/analyze
│  │  ├─ agents/
│  │  │  ├─ runtime.py            DeepSeekHarness 子进程生命周期
│  │  │  ├─ agent1_diet.py        饮食解析器
│  │  │  ├─ agent2_recommend.py   中医推荐器
│  │  │  ├─ json_guard.py         JSON 提取 / 校验 / 重试
│  │  │  └─ prompts/              两个 agent 的系统提示词
│  │  ├─ domain/
│  │  │  ├─ enums.py              四气 / 五味 / 时段 / 体质枚举
│  │  │  ├─ models.py             请求 / 响应 / 中间结构（唯一真源）
│  │  │  └─ safety.py             ★ 确定性安全护栏
│  │  └─ services/
│  │     ├─ orchestrator.py       双 Agent 串行编排 + 降级
│  │     └─ matcher.py            规则兜底与候选收敛
│  ├─ data/
│  │  ├─ herbs.json               ★ 20 味药食同源饮片库
│  │  └─ constitution.json        5 型体质速查
│  ├─ scripts/                    自检与冒烟脚本
│  ├─ tests/                      45 项测试
│  └─ static/demo.html            网页 demo
└─ miniprogram/                   （待建）
```

---

## 核心接口

### `POST /api/analyze`

请求：

```json
{
  "text": "中午吃了碗麻辣烫，还喝了杯冰可乐",
  "constitution_override": "phlegm_damp",
  "exclude_herbs": []
}
```

响应要点：

| 字段 | 说明 |
|---|---|
| `parsed` | Agent1 产物原样回显，前端展示「我理解到的」 |
| `parsed.confidence` | 低于 0.5 时前端应提示用户补充描述 |
| `recommendations[]` | 1–3 条，含 `herbs[]`（用量/属性/作用）、`brew`（冲泡步骤）、`fit_reason`、`cautions`、`score` |
| `basis` | 体质、命中的规则、护栏介入记录 |
| `meta.degraded` | `true` 表示走了规则兜底 |
| `disclaimer` | **所有响应必带**，前端统一渲染，禁止各自硬编码 |

错误码：`AGENT1_FAILED`（422，解析失败）、`INTERNAL_ERROR`（500）。

---

## 已验证事项与踩过的坑

以下三点已在真实环境验证通过，记录在此避免重复踩坑：

### 1. `dsh` 拒绝从工作区 `.env` 读取 `DSH_*` 变量 ✅ 已解决

报错形态：

```
Error: dsh: .env sets "DSH_HOME", which only the launching environment may set
  (it decides how this process starts, where its code and instructions load from,
   or how it reaches the network); export DSH_HOME instead of putting it in a .env file
```

**触发条件**：`dsh` 启动时扫描 workspace 根目录（即传给 SDK 的 `cwd`）的 `.env`。
本项目 `cwd` = 项目根，所以任何 `DSH_HOME` / `DSH_MAX_TOKENS` / `DEEPSEEK_API_KEY`
都不能出现在 `.env` 里，**注释里出现这些字符串也可能被扫描到**。

**解决**：`DSH_*` 与凭据放 `credentials.env`（dsh 不扫描该文件名），
由 `app/agents/runtime.py` 注入子进程 `os.environ`；`.env` 只留 `TA_*` / `APP_*`。

### 2. `DeepSeekHarness` 构造参数 ✅ 已验证可用

```python
DeepSeekHarness(
    dsh_home="...", cwd="...",
    provider="deepseek-official", model="deepseek-v4-flash",
    reasoning_effort="low", max_tokens=8192,
    api_key="sk-...",          # 同时注入 os.environ 更稳
)
with harness: result = harness.run(prompt, session_id=...)
result.final_response        # 取文本
```

- 启动约 1.7–4.5 s，进程复用，后续轮次 1–15 s。
- **`session_id` 必须每次唯一**：复用同一个 id 会延续同一段持久对话，
  重复执行同一请求会直接报 `session "xxx" already exists`，
  且按内容 hash 生成 id 会让重复输入累积上文、污染结果。代码里已改用 `time.time_ns()`。

### 3. 系统提示词注入方式 ✅ 已验证可用

当前把系统提示词拼在 user 消息前（`runtime.run(..., system_prompt=...)`），
实测模型能稳定遵守 JSON 格式与安全边界，**暂不需要给每个 agent 单独建 profile**。
若后续发现格式遵守度下降，再考虑 profile + patch 方案。

### 4. 仍需人工复核的事项 ⏳

**`herbs.json` 的医学准确性**。文件里 `_meta.review_status` 标的是 `pending`：

> 属性、剂量上限、禁忌均为保守整理的通行表述，**上线前必须由具备资质的中医师/中药师复核**，
> 并以国家卫健委发布的最新「既是食品又是中药材的物质目录」为准。

---

## 隐私提醒

`DSH_HOME` 默认指向项目内的 `dsh-home/`（已被 gitignore），与你主 DSH 环境隔离。
**不要把主 DSH 的 `~/.dsh` 或任何 `sessions/*.jsonl` 放进仓库或网盘**——里面有完整对话记录。

---

## 下一步

1. 配好 `.env` → 跑 `python scripts\smoke_agents.py`
2. 打开 `http://127.0.0.1:8000/demo` 试几条真实口述
3. 根据实际输出调 `backend/app/agents/prompts/` 里的提示词（改前先提交，方便回滚）
4. demo 满意后再做小程序：`miniprogram/` 只做「输入页 + 结果页」两个页面
