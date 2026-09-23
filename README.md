# 中医食性判定层 + 本地饮食茶饮助手

把「食物是寒是热」这件事从**模型凭语感猜**，变成**查表 + 纯规则判定**，
再在此基础上给出日常饮食茶饮建议。全部在本地运行，不需要域名、备案、服务器或任何平台审核。

> ⚠️ **本项目的所有输出仅供日常饮食参考，不构成医疗建议，也不能替代医师的诊断与治疗。**
> 孕期、哺乳期、经期、儿童、慢性病患者及正在服药者，请先咨询执业医师或药师。
>
> 数据文件 `_meta.review_status` 目前为 `pending`：属性依据中医饮食养生通行表述整理，
> **对外提供任何形式的服务前，必须由具备资质的中医师 / 中药师复核**，
> 并以国家卫健委发布的最新「既是食品又是中药材的物质目录」为准。

---

## 这是什么：两种用法

这个仓库同时服务两类人，请挑你需要的那一半读：

| 你是 | 你要的 | 去哪 |
|---|---|---|
| **想要一个本地助手** | 输入「中午吃了碗麻辣烫配冰可乐」，得到一碗该喝什么的建议 | [快速开始](#快速开始) |
| **想要一个可复用的判定库** | `resolve_food("冰啤酒") → 寒`，确定性、可复现、零成本、零 API 调用 | [当库用](#当库用三行拿到确定性判定) |

**分界线**：`resolve_food()` 及它下面的整层（第 1、2 节所述的三层架构）**不调用任何模型**，
是纯数据 + 纯规则，可以直接嵌进你自己的项目。模型只在「把自由文本解析成食物列表」
和「写一段人话建议」这两步参与，且**随时可以整个绕过**。

---

## 快速开始

### 30 秒体验：不需要 API Key，不花一分钱

```powershell
cd core
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"        # 只想跑终端壳就够；要 Web 界面见下一节

# ① 纯规则查表：零 LLM、零成本、毫秒级
python ..\ui\terminal\chat.py --resolve 冰啤酒 茉莉花茶 冰淇淋

# ② 离线推荐：不调用模型，走规则兜底，仍然给出合规且不超剂量的搭配
python ..\ui\terminal\chat.py --offline "中午吃了碗麻辣烫，还喝了杯冰可乐"

# ③ 验证一切正常
python -m pytest -q
```

### 使用网页版问卷：安装国标问卷子包

网页版先做体质问卷，因此使用网页版时需要安装问卷子包。没有安装时 Web 服务仍能启动，
但 `/api/questionnaire` 与 `/api/questionnaire/questions` 返回 501，无法完成网页的开始流程；
终端的 `--questionnaire` / `:qz` 也不可用。应用不会在 import 阶段修改 `sys.path`。
请把两个项目装进同一个虚拟环境：

```powershell
cd ..                                   # 回到仓库根
core\.venv\Scripts\python.exe -m pip install -e tcm-constitution-questionnaire
core\.venv\Scripts\python.exe -m pip install -e ".\core[dev,web]"
```

之后（`--offline` 也能用，问卷本身不调模型）：

```powershell
python ..\ui\terminal\chat.py --questionnaire "中午吃了碗麻辣烫"
python ..\ui\terminal\chat.py --questionnaire --offline "中午吃了碗麻辣烫"
```

交互模式里输入 `:qz` 可以随时跑一次；装上后 `python scripts/check_setup.py` 的第 6 节会报「可用」。

⚠️ 三点要说清：

- 问卷判定的是**倾向性体质，不是诊断**。国标允许多种偏颇体质同时判为「是」；
  此时按**分数最高者**收敛推荐方向，其余体质**只做屏蔽**（把标为不宜的饮片排除），
  并在输出里写明兼了哪几型。
- 转化分 30–40 的「**倾向是**」**不是判定**。只有在没有任何「是」时它才顶上来当主导体质，
  且一定会提示「问卷未达判定阈值，按倾向处理」。
- 判不出时**不会**默认平和质，而是请你手动选（`:c <体质>`）——冒充平和质等于给一份无依据的推荐。

`--questionnaire` 与 `--constitution` 只能二选一。

`--resolve` 的实际输出（`detail` 会告诉你**每一档是怎么来的**）：

```
  冰啤酒
    四性：寒   五味：苦甘
    来源：按烹饪方式推算   置信度：0.6   待验证：是
    过程：「啤酒」原形态下属性为凉；冰修正 -1：凉 → 寒
          （温度前缀由食物名识别，纯规则判定，不经模型）（该条目尚未通过人工审核）

  茉莉花茶
    四性：温   五味：甘辛
    来源：查表   置信度：0.9   待验证：是
```

### 用完整助手：需要你自己的 API Key

**本项目不在服务端保存任何 API Key，也没有内置的兜底 Key。**
要用完整助手（让模型解析饮食、写建议），你必须提供自己的 Key，有两种给法：

| 界面 | 怎么给 | 费用 |
|---|---|---|
| **网页版** | 在页面上的「API Key」一栏填入 | 记在你自己的账号 |
| **终端 / 脚本** | 先设环境变量再运行：`$env:DEEPSEEK_API_KEY = "sk-..."` | 同上 |

**不填就一定失败**：网页不填会返回 `400 NO_API_KEY`，终端会打印怎么设置环境变量。
这样做是刻意的——不会有人在你不知情时消耗你的额度。

Key 是**逐请求生效**的：通过 `Authorization: Bearer <key>` 头发给本机后端，
再由后端转给模型服务，**不写入日志、不落盘、不入库**。
网页里默认**不勾选**「记住 Key」，Key 只存在当前标签页；勾选后才写入浏览器 `localStorage`。

每次响应都会标注本次有没有调用模型（`meta.key_source`）：网页上显示
「本次使用你填的 Key」或「本次未调用模型（规则分支，无费用）」。

> **申请 Key**：<https://platform.deepseek.com/api_keys>
>
> **不想填 Key 也想试**：`--resolve`（纯查表）与 `--offline`（规则推荐）
> 两条路完全不调用模型，见上面的「30 秒体验」。它们也是本项目真正的核心。

#### 后端选型：`TA_BACKEND`

| 值 | 行为 |
|---|---|
| `direct`（默认） | 直连 DeepSeek 官方 API。Key 逐请求传入，**支持界面/环境变量给 Key** |
| `dsh` | 走 DeepSeekHarness 子进程。Key 与子进程绑定（一个进程一个 Key），**无法按请求换 Key**；保留用于调试 |

> ⚠️ `dsh` 后端下在界面填 Key 会直接返回 `USER_KEY_UNSUPPORTED`，**不会静默换用别的 Key** ——
> 静默复用会让你以为费用记在自己账上。原因见 [踩过的坑](#2-dsh-的-key-粒度是一个-harness-实例)。

#### 配置文件

| 文件 | 放什么 | 说明 |
|---|---|---|
| `.env` | `TA_BACKEND`、`TA_*` 模型参数、`APP_*` 端口、超时 | 可选，全部有默认值；模板入库 |
| `credentials.env` | `DSH_HOME`、可选的 `DEEPSEEK_BASE_URL` | 可选；**不存 API Key** |

**为什么 `DSH_HOME` 要单独一个文件**：`dsh` 启动时会扫描 workspace 根目录的 `.env`，
一旦发现 `DSH_HOME` 这类 `DSH_*` 变量就**直接拒绝启动**：

```
Error: dsh: .env sets "DSH_HOME", which only the launching environment may set
```

因为它们决定进程如何启动、从哪里加载代码与指令、如何联网，属于「启动环境专属」变量。
所以约定：`.env` 里只出现 `TA_*` 与 `APP_*`，`DSH_HOME` 放 `credentials.env`。

```powershell
cd <仓库根>
Copy-Item .env.example .env                          # 可选：不配也能跑，全部参数都有默认值
Copy-Item credentials.env.example credentials.env    # 可选：只有用 dsh 后端才需要
```

两份配置都是**可选**的：

* **不配 `.env`** → 用内置默认值（`TA_BACKEND=direct`、`deepseek-v4-flash`、`TA_REASONING_EFFORT=low`）。
* **不配 `credentials.env`** → 完全不影响：它不含 Key，而 `DSH_HOME` 有默认值（`<仓库根>/dsh-home`）。

两个真实配置文件都已被 `.gitignore` 忽略（模板文件会入库）。
**实测：全新 clone 不配任何配置文件也能跑通 `pytest`（841 项）与 `--resolve` 纯规则链路。**

```powershell
# 环境与数据自检（秒级，不调模型）
cd core
python scripts\check_setup.py

# 离线冒烟：数据层 → 解析 → 规则兜底 → 护栏 全链路
python scripts\smoke_offline.py

# 真实模型冒烟（约 60–90 秒，会产生调用费用）
python scripts\smoke_agents.py

# 终端助手（交互模式，走真实模型）
python ..\ui\terminal\chat.py
```

### 图省事：双击启动（Windows）

不想敲命令就双击仓库根目录下的两个脚本：

| 脚本 | 作用 |
|---|---|
| **`start-web.cmd`** | 起本地服务，约 4 秒后自动打开浏览器到 <http://127.0.0.1:8000>。设 `TA_NO_BROWSER=1` 可跳过自动开浏览器 |
| **`start-terminal.cmd`** | 打开终端版助手 |

两个脚本都会先检查 `core\.venv` 是否存在，缺了就打印安装命令而不是报一堆错。
它们只是便利入口，等价于下面手打的命令。

### 本地 Web 界面

```powershell
cd core
python -m uvicorn app.main:app --reload --port 8000
```

* 本地界面：<http://127.0.0.1:8000>
* 接口文档：<http://127.0.0.1:8000/docs>
* 自检：<http://127.0.0.1:8000/healthz>

网页版先展示食性判定说明；点击「开始」完成分男女的体质问卷后，进入茶饮建议页面。
主页面提供三种方式，并保留饮食记录与调理资料面板：

* **规则速览**：调用 `/api/analyze-offline` 给出饮食与茶饮建议，不需要 Key、不调用模型。
* **联网对话**：通过本机 Web 服务调用同一个离线规则接口，使用项目内的数据与规则，不调用外部模型 API。
* **API 对话**：使用右上角「API 设置」中选择的模型和用户提供的 Key；Key 输入框可切换显示或隐藏。
* **体质问卷**：按性别加载九种体质问卷；主导体质用于后续建议，兼夹体质只作为屏蔽集。无法确定时需重新测评。
* **饮食记录**：成功分析后仅在浏览器本地保存记录，并可离线汇总近 7 天内容。
* **调理资料**：只读展示指南资料摘要，不提供剂量，也不进入茶饮推荐链路。

界面与接口由同一个服务同源提供，因此**不需要**、也不应该打开 CORS 通配。
`app/main.py` 只放行本机来源；请勿改回 `["*"]`——那会让局域网内任意网页都能调用你本机的接口。

#### 两条模型执行路径的定位

* `/api/analyze` 是茶饮建议的主流程，由 `agents/runtime.py` 与
  `services/orchestrator.py` 统一编排，并执行确定性安全护栏。
* `/api/chat` 是为旧版网页多模型选择保留的兼容对话入口，当前仍通过
  `multi_provider.py` 调用 OpenAI 兼容接口；它不是茶饮建议主流程。
* 两个入口共用 `api/auth.py` 的 Bearer Key 解析与相同的隐私边界。后续若要合并模型实现，
  应先抽出统一的逐请求运行时接口，不再在路由内新增第三套鉴权或供应商判断。

> 只用终端界面时**不必**启动这个服务，也不必安装 `web` extra。

---

## 当库用：三行拿到确定性判定

```python
from app.services.food_lookup import resolve_food

r = resolve_food(name="冰啤酒")
print(r.nature)                    # cold（寒）
print(r.flavors)                   # ['bitter', 'sweet']
print(r.verification.source)       # composed —— 表值 + 纯规则温度修正
print(r.verification.confidence)   # 0.6
print(r.verification.detail)       # 完整判定过程，可追溯
```

`ResolvedFood.verification` 是这套库最核心的对外契约：

| 字段 | 含义 |
|---|---|
| `source` | `rule` 命中表 / `composed` 组合推理 / `llm` 模型推测 / `unresolved` 无法判定 |
| `confidence` | 0.9 / 0.6 / 0.3 / 0.1（约定见下） |
| `unverified` | `true` 表示未经中医食性验证，**界面必须标注** |
| `detail` | 判定过程说明，便于排查与审计 |

**调用方应当按 `confidence` 决定是否展示**：约定是**低于 0.3 时不显示寒热属性**
（数据仍然保留，但不要呈现给用户）。

### 边界与注意事项

* 数据层经由 `app.config` 依赖 `python-dotenv`，并且从 `core/data/` 读 JSON。
  想把数据放到别处，目前需要自行设置工作目录或改 `config.py`（计划中会加 `TA_DATA_DIR`）。
* `resolve_food()` **只判定单一食物**。整菜名（如「番茄炒蛋」）要么表里收录，要么整体落到 LLM 层。
  多层食材的合成算法 `nature_math.combine()` 已实现并测试，但**尚未接入主流程**。
* `unknown` 没有数值（返回 `None`），**不是 0**——否则「未判定」会被当成平性参与运算。

---

## 核心：三层混合判断架构

食物寒热属性的判定分三层，置信度递减，来源可追溯。完整设计见
**[docs/three-layer-architecture.md](docs/three-layer-architecture.md)**。

```
用户口述
   ↓
┌─────────────────────────────────────────────┐
│ 第一层 硬规则库          confidence 0.9      │
│   food_properties.json 规范名精确命中         │
│   直接查表，表值即权威，不叠加模型猜测         │
├─────────────────────────────────────────────┤
│ 第一层附 食材变体层       confidence 0.9      │
│   条目自带 variant_nature（如 红薯→烤红薯 温）│
├─────────────────────────────────────────────┤
│ 第二层 组合推理（烹饪修正） confidence 0.6    │
│   蒸煮 0 / 煎炸 +1 / 烧烤 +1 / 辛辣 +1 / 冰镇 -1│
├─────────────────────────────────────────────┤
│ 第二层附 温度前缀层       confidence 0.6      │
│   「冰啤酒」「热牛奶」的冰/热用**纯字符串规则**识别 │
│   剥掉前缀后须是完整表内食物名才生效            │
├─────────────────────────────────────────────┤
│ 第三层 LLM 推测          confidence 0.3      │
│   表里没有 → 保留模型判断但标记未验证          │
│   完全判不出 → unresolved / 0.1              │
└─────────────────────────────────────────────┘
   ↓
逐项写入 verification{source, confidence, unverified, detail}
   ↓
界面按阈值决定是否显示、是否标注
```

### 为什么必须查表：模型的系统性偏差

实测发现模型在食物寒热上有**成体系的错误**——把性温的茉莉花茶判成「凉」，
把中性食材（小笼包、兰州拉面）普遍判成「温」。加查表后准确率 81% → 100%。

参考表放在 user 消息而不是 system 提示词里，是为了保持 system 前缀稳定、
让 KV 缓存继续命中；同时只注入命中的条目，单条参考表 < 400 字符。

回归测试：

```powershell
python core\scripts\test_food_accuracy.py        # 真实模型 23 条语料
python -m pytest core\tests\test_food_lookup.py -q   # 表本身与匹配逻辑的单测
```

### 双 Agent 协作：通过一个 JSON 通信，谁都不越界

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

* Agent1 管「你吃了什么」，不做推荐、不判断体质。
* Agent2 管「配什么泡」，只能在白名单候选集内选，不开方剂、不超剂量。

**为什么要有白名单和规则兜底**：提示词里写十遍「不要开方」，不如**让模型无方可开**。
Agent2 只能从 `herbs.json` 的 44 味里挑，候选集由 `safety.py` 按体质预先收敛。
即使模型完全不可用，`matcher.py` 的规则兜底仍会给出合法、安全、不超剂量的搭配
（响应里 `meta.degraded = true`）。

---

## 数据

| 文件 | 内容 | 规模 |
|---|---|---|
| `core/data/food_properties.json` | 食材 + 茶饮食性表，逐条审核状态 | **147 条**（129 食材 + 18 茶饮） |
| `core/data/herbs.json` | 药食同源饮片白名单（含剂量上限与禁忌） | **44 味** |
| `core/data/constitution.json` | 体质速查 | **9 型** |

**审核状态是三态**，不是布尔值——`reviewed: false` 无法区分「还没审」和「审了但不认可」：

| 状态 | 效果 |
|---|---|
| `approved` | 真·硬规则库，置信度 0.9，界面**不**标注 |
| `pending` | 置信度 0.9，但界面必须标注「待验证」（**当前 147 条全部是这个**） |
| `rejected` | 降为组合推理档（0.6），不再作硬规则 |

> 全部为 `pending` 是**刻意**的：界面普遍显示「待验证」标记，
> 标记密度就是审核进度的可见反馈。**请勿为了界面好看而批量置为 `approved`。**

想加条目 / 参与审核，请读 **[CONTRIBUTING.md](CONTRIBUTING.md)**——
特别是第 3 节，它说明了 `scripts/` 下那三个数据维护脚本**都是冻结的一次性批次脚本**，
不是通用加条目工具。

---

## 目录结构

```
tea-advisor/
├─ README.md                       本文件
├─ CONTRIBUTING.md                 贡献指南（数据表怎么改、哪些是契约）
├─ LICENSE                         MIT
├─ .env.example                    应用配置模板（TA_* / APP_*）
├─ credentials.env.example         运行配置模板（DSH_HOME / 自定义接口地址；不含 Key）
├─ ui/                             ★ 前端交互层：所有"壳"都在这里
│  ├─ terminal/chat.py             终端壳（仅标准库）：--resolve / --offline / 交互
│  └─ web/index.html               本地 Web 界面（由 FastAPI 同源提供）
├─ core/                        ★ 核心逻辑层（与 ui/ 解耦，不 import ui）
│  ├─ app/
│  │  ├─ main.py                   FastAPI 入口（Web 适配层）、/ 、/docs、/healthz
│  │  ├─ config.py                 环境变量集中读取
│  │  ├─ api/analyze.py            POST /api/analyze
│  │  ├─ api/
│  │  │  ├─ analyze.py             POST /api/analyze（读 Authorization 头）
│  │  │  └─ auth.py                从 Bearer 头提取用户自带的 API Key
│  │  ├─ agents/
│  │  │  ├─ runtime.py             后端选择 + dsh 子进程后端 + CredentialError
│  │  │  ├─ direct_api.py          直连官方 API 的后端（默认，支持逐请求 Key）
│  │  │  ├─ agent1_diet.py         饮食解析器
│  │  │  ├─ agent2_recommend.py    中医推荐器
│  │  │  ├─ json_guard.py          JSON 提取 / 校验 / 重试
│  │  │  └─ prompts/               两个 agent 的系统提示词
│  │  ├─ domain/                   ★ 纯逻辑，不依赖 Web 框架
│  │  │  ├─ enums.py               四气 / 五味 / 时段 / 体质枚举 + 中文标签
│  │  │  ├─ nature_math.py         四性数值运算 + 温度前缀唯一入口
│  │  │  ├─ models.py              请求 / 响应 / 中间结构（唯一真源）
│  │  │  └─ safety.py              ★ 确定性安全护栏
│  │  └─ services/
│  │     ├─ food_lookup.py         ★ resolve_food() 三层判定入口
│  │     ├─ matcher.py             规则兜底与候选收敛
│  │     └─ orchestrator.py        双 Agent 串行编排 + 降级
│  ├─ data/                        数据层（上表三个 JSON）
│  ├─ scripts/                     自检与冒烟脚本
│  └─ tests/                       841 项离线测试
├─ start-web.cmd                   ★ Windows 双击启动网页版（自动开浏览器）
├─ start-terminal.cmd              ★ Windows 双击启动终端版
└─ docs/three-layer-architecture.md
```

**分层规则**：`ui/` 只单向依赖 `core/app/`，核心逻辑层**不得**反向 import `ui/`。
新增界面请放进 `ui/` 并复用核心，不要为此改动 `app/domain/`、`app/services/`、`app/agents/`。

---

## 测试

```powershell
cd core
python -m pytest tests -q    # 841 passed，不调用模型、不需要 API Key
```

> ⚠️ 别在 `core/` 下直接跑裸 `pytest -q`：它会把 `core/var/` 下的临时脚本一起收集（其中有 GBK 编码文件，会报 `UnicodeDecodeError`）。带上 `tests` 就不会。

| 文件 | 覆盖内容 | 项数 |
|---|---|---|
| `tests/test_nature_math.py` | 编码、夹取、边界取整、两层修正、合成算法 | 48 |
| `tests/test_temperature_layer.py` | 温度前缀、双通道扫描、准入校验、与表内变体优先级 | 48 |
| `tests/test_safety.py` | 白名单、剂量裁剪、禁用表述、高风险人群、体质筛选 | 50 |
| `tests/test_food_lookup.py` | 表完整性、匹配准确性、渲染、名称对齐 | 24 |
| `tests/test_calibration.py` | 校准接线、来源标记、Agent2 隔离、已知局限固化 | 20 |
| `tests/test_json_guard.py` | 围栏剥离、对象提取、schema 校验、失败重试 | 14 |
| `tests/test_key_handling.py` | Authorization 解析、思考模式映射、**Key 不进日志/响应/异常**、凭据错误码、无 Key 即拒绝 | 50 |

> 本表只列核心 7 个文件；`core/tests/` 现共 **45 个测试文件 / 841 项**，完整清单跑 `pytest --collect-only -q`（在 `core/` 目录下）。

需要 API Key 的端到端（**不在 pytest 内**，会产生调用费用）：

```powershell
python core\scripts\test_food_accuracy.py    # 属性准确率：23 条语料
python core\scripts\smoke_agents.py      # 运行时启动 → 原始往返 → Agent1 → 全链路
```

---

## 实测延迟

`reasoning_effort=low`、3 条真实语料的实测（含 `scripts/smoke_agents.py` 全链路）：

| 环节 | 耗时 |
|---|---|
| DSH 运行时首次启动 | ~2.2 s（进程复用，后续不再付这个成本） |
| Agent1 饮食解析 | 1.3 – 4.7 s |
| Agent2 茶饮推荐 | 11.7 – 16.5 s |
| **全链路** | **13.4 – 18.7 s** |
| 高风险人群分支 | ~0 s（**不调用模型**，直接引导就医） |
| `--offline` 确定性链路 | ~0.00 s（**不调用模型**） |

`TA_REASONING_EFFORT` 对延迟影响极大，实测同一任务：

| effort | Agent2 耗时 | 推荐条数 |
|---|---|---|
| max | 19.2 s | 3 |
| high | 10.1 s | 3 |
| **low（默认）** | **8.2 s** | **3** |
| off | 2.7 s | 1 |

**这就是默认取 `low` 而不是 `off` 的原因**：`off` 快约 3 倍、成本降一个量级，但推荐常只剩 1 条
（2026-09-17 复测：3 个用例给出 3 / 1 / 1 条）。需要压延迟或压成本时可自行设
`TA_REASONING_EFFORT=off`，代价就是上面这一行。取舍详解见 `docs/maintenance.md` §7.2。

本模型支持 `max` / `high` / `low` / `off`；`medium`、`none`、`minimal` 会导致启动失败。

> ⚠️ 13 秒以上的等待对交互体验偏长。若在意响应速度，优先用 `--resolve`（毫秒级）
> 或 `--offline`（毫秒级）；要改成异步任务 + 轮询需自行扩展 `ui/`。

---

## 已知局限（重要，不要误当 bug 修）

1. **规范名精确命中时，不叠加模型给的烹饪修正。**
   因为无法从模型输出可靠区分「可靠证据」与「猜测」——模型可能给「希腊酸奶」一个
   `cold`、给「火腿三明治」一个 `grilled`，照单全收会把表值污染成错误档位。
   这一局限已由**温度前缀层**部分解决；剩下的煎炸/烧烤类修正需要在表里为该食物
   单列条目并写 `variant_nature`。

2. **关键词子串会把无关名称拉进表。**
   例如 `辣椒` 的关键词含「麻辣」，于是口述里的「麻辣烫」会把 `辣椒` 也命中。
   已知案例（「薯条」被匹配到「炸鱼薯条」、「寿司」被匹配到「生鱼片」）已通过三级匹配优先级
   （精确同名 > 包含关系按 gap 最小 > 关键词）修掉，但字符串匹配本质上无法完全消除歧义。
   要彻底解决需要菜品别名库或分词。

   > 这一局限在 `--offline` 模式下**更容易被看到**：`match_foods()` 是「表里哪些条目在句子里出现过」，
   > 而不是「识别出你吃了什么」。所以离线模式的物品列表应理解为**表命中项**，与实际所吃并不等价。

3. **第二层组合推理尚未接入主流程。**
   `combine()` 已实现并测试，但 `resolve_food` 目前只做单食材判定。
   「番茄炒蛋」这类整菜名要么表里收录，要么整体落到第三层。

4. **第一层数据尚未人工审核。**
   `food_properties.json` 与 `herbs.json` 全部为 `pending`。属性依据中医饮食养生通行表述整理
   （食物偏性，非药物功效），**对外提供任何服务前应由具备资质的中医师/中药师复核**。

5. **离线模式只能识别表内条目。**
   `--offline` 依赖 `match_foods()` 的关键词匹配，表里没有的食物一律认不出。
   它牺牲识别率换取零成本、零延迟与完全确定性，是刻意的取舍。

---

## 开发与贡献

**五份文档的分工**（想深入哪一块就读哪一份）：

| 文档 | 给谁 | 内容 |
|---|---|---|
| 本文件 | 使用者 | 这是什么、怎么装、怎么用 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 贡献者 | 十条不可随手改的契约、数据表怎么改、PR 流程 |
| [docs/three-layer-architecture.md](docs/three-layer-architecture.md) | 想改判定逻辑的人 | 三层架构的原理、数值编码、**已知局限** |
| [docs/maintenance.md](docs/maintenance.md) | **维护者** | 全貌、数据流、运维、验证基线、成本模型、排错手册 |
| [docs/data-contracts.md](docs/data-contracts.md) | **改数据的人** | `core/data/*.json` 与食性登记表的**形状与派生纪律**、批脚本文案陷阱 |

```powershell
python core\scripts\check_setup.py   # 环境与数据自检
python core\scripts\smoke_offline.py # 离线全链路冒烟
python -m pytest core\tests -q       # 841 项
```

提交 PR 前请读 **[CONTRIBUTING.md](CONTRIBUTING.md)**，其中写明了：

* 哪些是**不可随意改的契约**（`models.py` 唯一真源、`nature_math` 是四性运算唯一真源、
  温度判定只有 `resolve_temperature()` 一个入口、`resolve_food()` 的层序、置信度约定）
* 数据表怎么加条目，以及 `scripts/` 下三个维护脚本**都是冻结的一次性批次脚本**、
  都支持 `--dry-run`、历史执行顺序是 `add_review_fields.py` → `patch_food_table.py`
* `ui/` 与 `core/` 的分层规则

---

## 踩过的坑（已验证，避免重复踩）

### 1. `dsh` 拒绝从工作区 `.env` 读取 `DSH_*` 变量 ✅ 已解决

**触发条件**：`dsh` 启动时扫描 workspace 根目录（即传给 SDK 的 `cwd`）的 `.env`。
本项目 `cwd` = 项目根，所以任何 `DSH_HOME` / `DSH_MAX_TOKENS` / `DEEPSEEK_API_KEY`
都不能出现在 `.env` 里，**注释里出现这些字符串也可能被扫描到**。

**解决**：`DSH_HOME` 放 `credentials.env`（`dsh` 不扫描该文件名），
由 `app/agents/runtime.py` 注入子进程 `os.environ`；`.env` 只留 `TA_*` / `APP_*`。

> 补充：从 v0.2 起本项目**不再保存 API Key**（`DEEPSEEK_API_KEY` 由调用方逐请求传入）。
> 但这条 `dsh` 约束依然成立——只要 `TA_BACKEND=dsh`，`DSH_HOME` 就不能进 `.env`。

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

* 启动约 1.7–4.5 s，进程复用，后续轮次 1–15 s。
* **`session_id` 必须每次唯一**：复用同一个 id 会延续同一段持久对话，
  重复执行同一请求会直接报 `session "xxx" already exists`，
  且按内容 hash 生成 id 会让重复输入累积上文、污染结果。代码里已改用 `time.time_ns()`。

### 3. 系统提示词注入方式 ✅ 已验证可用

当前把系统提示词拼在 user 消息前（`runtime.run(..., system_prompt=...)`），
实测模型能稳定遵守 JSON 格式与安全边界，**暂不需要给每个 agent 单独建 profile**。
若后续发现格式遵守度下降，再考虑 profile + patch 方案。

### 4. Windows 控制台的编码 ✅ 已解决

Python 脚本在 Windows 控制台默认用 GBK 输出，中文会乱码。
`scripts/` 下的脚本与 `ui/terminal/chat.py` 都在入口处显式 `reconfigure(encoding="utf-8")`；
终端壳还额外处理了 **stdin**——Windows 下标准输入被重定向时用系统 locale 编码（cp936），
不显式指定 UTF-8 会把中文输入解成乱码。

### 5. 仍需人工复核的事项 ⏳

**`herbs.json` 与 `food_properties.json` 的医学准确性**。两个文件的 `_meta.review_status`
都是 `pending`，**对外提供服务前必须由具备资质的中医师/中药师复核**。

---

## 隐私提醒

`DSH_HOME` 默认指向仓库内的 `dsh-home/`（已被 gitignore），与你主 DSH 环境隔离。
**不要把主 DSH 的 `~/.dsh` 或任何 `sessions/*.jsonl` 放进仓库或网盘**——里面有完整对话记录。
同理，`dsh-home/` 目录虽然不入库，也建议放在仓库目录**之外**，避免误打包。

提交前自查：

```powershell
git status --short          # 确认没有 .env / credentials.env / dsh-home/
git diff --cached           # 逐行看一次暂存内容
```

---

## 许可

[MIT](LICENSE)。另请一并阅读 LICENSE 文件末尾的**附加声明**：
它说明了本项目的非医疗建议属性，以及对外提供服务的复核义务。
