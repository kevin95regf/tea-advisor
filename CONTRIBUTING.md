# 贡献指南

感谢你有兴趣参与。本项目是**本地运行的桌面助手**，同时它的数据层与判定逻辑
也可以被当作一个独立的 Python 库使用。下面分「跑起来」「改哪里」「别改坏什么」三段。

> ⚠️ **红线（先读这一段）**：本项目输出仅供日常饮食参考，**不构成医疗建议**。
> 任何 PR 都不得引入疗效承诺、诊断结论或可替代就医的表述。
> 提示词、文案、数据条目的改动都受此约束，`core/app/domain/safety.py` 里有机器强制的词表。

---

## 1. 跑起来

### 1.1 环境

* Python **>= 3.10**（CI 与开发者实测环境为 3.13）
* 建议用虚拟环境：

```powershell
cd core
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,web]"
```

> `web` extra 提供本地 Web 界面所需的 `fastapi` / `uvicorn`。
> 只用终端界面（`ui/terminal/chat.py`）的话可以省掉它：
> `pip install -e ".[dev]"`。

### 1.2 配置文件与 API Key

| 文件 | 放什么 | 为什么 |
|---|---|---|
| `.env` | 应用配置：`TA_*` 模型参数、`APP_*` 端口、超时 | 可选（都有默认值），可以入库模板 |
| `credentials.env` | `DSH_HOME`、可选的 `DEEPSEEK_BASE_URL` | **不能放 `.env`**；**不存 API Key** |

**API Key 不放在任何文件里。** 本项目不使用服务端内置 Key（曾有的"兜底 Key"已移除），
Key 只有一个来源——调用方显式传入：

* 网页：`Authorization: Bearer <key>` 头，逐请求
* 终端与脚本：环境变量 `DEEPSEEK_API_KEY`（`config.api_key_from_env()` 读取）

**为什么 `DSH_HOME` 必须单独一个文件**：`dsh` 启动时会扫描 workspace 根目录的 `.env`，
一旦发现 `DSH_HOME` 这类 `DSH_*` 变量就**直接拒绝启动**：

```
Error: dsh: .env sets "DSH_HOME", which only the launching environment may set
```

因为它们决定进程如何启动、从哪里加载代码与指令、如何联网，属于「启动环境专属」变量。
所以约定：`.env` 里只出现 `TA_*` 与 `APP_*`，`DSH_HOME` 放 `credentials.env`，
由 `app/config.py` 读取、`app/agents/runtime.py` 注入子进程环境。

> 只有 `TA_BACKEND=dsh`（调试用）才需要 `credentials.env`；默认的 direct 后端不用它。

两个真实配置文件都已被 `.gitignore` 忽略，模板文件会入库。**提交前请确认你没有把
自己的 Key 提交上去**（`git diff --cached` 看一眼）。

### 1.3 四道验证，按成本从低到高

```powershell
# ① 环境与数据自检（秒级，不调模型）
python scripts\check_setup.py

# ② 离线冒烟：数据层 → 解析 → 规则兜底 → 护栏 全链路（不调模型）
python scripts\smoke_offline.py

# ③ 单元测试（离线，约 0.7 秒，278 项）
python -m pytest -q

# ④ 真实模型冒烟（需要 API Key，约 60–90 秒，会产生调用费用）
python scripts\smoke_agents.py
```

**提交 PR 前 ①②③ 必须全绿。** ④ 无法在无凭据的 CI 里跑，请在你本地跑一次并在
PR 描述里贴结果。

终端界面也可以用来手工验证：

```powershell
python ui\terminal\chat.py --resolve 冰啤酒 白米饭     # 纯规则查表，零成本
python ui\terminal\chat.py --offline "中午吃了碗麻辣烫"  # 离线推荐，零成本
python ui\terminal\chat.py                            # 交互模式（默认走真实模型）
```

---

## 2. 想改什么，改哪里

| 你的意图 | 该改的文件 | 说明 |
|---|---|---|
| 增减食材 / 改属性 | `core/data/food_properties.json` | 见第 3 节，**别用脚本批量灌** |
| 增减饮片 / 改剂量上限 | `core/data/herbs.json` | 改完必须让 `check_setup.py` 与 `pytest` 通过 |
| 改体质说明 | `core/data/constitution.json` | 5 型，与 `app/domain/enums.py` 的枚举必须一致 |
| 改四性运算（±1 修正、合成算法） | `app/domain/nature_math.py` | **唯一真源**，改前先读 `docs/three-layer-architecture.md` |
| 改温度前缀识别（冰/热…） | `app/domain/nature_math.py` 的 `CHILL_PREFIXES` / `HEAT_PREFIXES` | **只改这一处**，两个上层入口自动跟随 |
| 改判定顺序 / 置信度 | `app/services/food_lookup.py` | `resolve_food()` 是三层架构的入口 |
| 改安全护栏（词表、剂量、高风险人群） | `app/domain/safety.py` | 改词表要同步补测试 |
| 改 Agent 行为 | `app/agents/prompts/*.md` | 提示词改动影响面大，PR 请附 ④ 的前后对比 |
| 改接口字段 | `app/domain/models.py` | **改了就是改了对外契约**，必须同步前端与提示词 |
| 改交互界面 | `ui/` 下的对应子目录 | 不要为此修改 `core/app/` 下的核心逻辑 |

---

## 3. 数据表贡献指南（重点）

### 3.1 条目结构

`food_properties.json` 顶层是 `foods` 数组 + `tea_drinks.items` 数组 + `_meta`。
一条典型条目：

```json
{
  "id": "mifan",
  "name": "米饭",
  "aliases": ["白饭", "白米饭", "大米饭"],
  "category": "主食",
  "nature": "neutral",
  "flavors": ["sweet"],
  "keywords": ["米饭", "白饭", "大米饭"],
  "variant_nature": { "cold": "cold" },
  "note": "……",
  "reviewed": false,
  "reviewed_by": null,
  "reviewed_at": null,
  "review_note": null,
  "review_status": "pending"
}
```

字段含义见文件自身的 `_meta.field_notes`。取值必须来自 `app/domain/enums.py`：

* `nature`：`cold` 寒 / `cool` 凉 / `neutral` 平 / `warm` 温 / `hot` 热
* `flavors`：`sour` 酸 / `bitter` 苦 / `sweet` 甘 / `pungent` 辛 / `salty` 咸 / `bland` 淡 / `astringent` 涩

### 3.2 怎么加条目：**直接编辑 JSON**

新条目请**直接编辑 `food_properties.json`**，按 `indent=2` 的现有风格插入，
并补齐上面 `review_*` 系列字段（默认 `reviewed: false` / `review_status: "pending"`）。

这样做的理由：diff 干净、可评审、不依赖脚本的内部状态。

### 3.3 ⚠️ 关于 `scripts/` 下的三个数据维护脚本

**这三个脚本都是「冻结的一次性批次脚本」，不是通用工具。**
它们记录的是历史上特定几次数据变更，脚本里的数据是**写死在源码里的**。

#### `scripts/add_food_entries.py` —— **不要把它当作「加条目工具」**

* 它的新增内容来自源码里硬编码的 `NEW_ENTRIES` 列表（16 条，针对「希腊酸奶」
  「韩式炸鸡」这类曾被误配的外国/新式食物），**不是从命令行读入的**。
* 所以它对「加一种你自己想加的食物」这件事**没有帮助**——除非你去改源码里的
  `NEW_ENTRIES`，而那样改动应该直接落到 JSON 里（见 3.2）。
* 幂等性：按 `id` **和** `name` 双重去重，已存在则跳过，重复运行不会产生重复条目。
* **注意**：它会把整个 `food_properties.json` 用 `json.dumps(indent=2)` **全量重写**，
  可能产生大范围 diff。提交前务必 `git diff` 复核。
* **已知隐患**：去重集合在循环**之前**一次性算好，循环中不更新。所以如果
  `NEW_ENTRIES` 自身出现两条同 `id`/同 `name` 的条目，两条都会被写入。
  往这个列表追加内容时请自行确认 id 唯一。

#### `scripts/add_review_fields.py` —— 历史上的一次性迁移，**现在跑是空操作**

* 它给每个条目补上布尔字段 `reviewed`（以及 `reviewed_by` / `reviewed_at` / `review_note`）。
* 当前表内 **146 条已全部含有 `reviewed`**，所以现在运行它不会改动任何条目。
* 保留它只是为了记录迁移历史与可复现性。

#### `scripts/patch_food_table.py` —— 结构升级 + 定向修正

* 把二值 `reviewed` 升级为三态 `review_status`（`approved` / `pending` / `rejected`）。
* 附带 4 处写死的条目修正（`ENTRY_FIXES`，如移除「生鱼片」与「寿司」重叠的关键词）。
* 幂等：已有 `review_status` 的条目跳过；`ENTRY_FIXES` 里值已等于目标值时跳过。

#### 📌 三者的历史执行顺序**不可颠倒**

```
add_review_fields.py   →   patch_food_table.py
   （先补 reviewed 布尔）      （再把 reviewed 迁移为 review_status 三态）
```

`patch_food_table.py` 的迁移逻辑是「`reviewed: true` → `approved`，否则 `pending`」。
如果先跑它、再跑 `add_review_fields.py`，迁移依据就不存在了。

#### 三者都支持 `--dry-run`

**改动任何数据文件之前，先跑一次 `--dry-run` 看清楚会动什么：**

```powershell
python scripts\add_food_entries.py --dry-run
python scripts\add_review_fields.py --dry-run
python scripts\patch_food_table.py --dry-run
```

### 3.4 审核状态（三态）与贡献者的关系

| 状态 | 含义 | 效果 |
|---|---|---|
| `approved` | 已由具备资质的人员审核通过 | 真·硬规则库，置信度 0.9，界面**不**标注 |
| `pending` | 待审核（**当前 146 条全部是这个**） | 置信度 0.9，但界面必须标注「待验证」 |
| `rejected` | 审核不通过 | 降为组合推理档（0.6），不再作硬规则 |

**普通贡献者请一律填 `pending`**，不要自行标 `approved`——那等于声称属性已被专业审核。
`approved` 只应由具备资质的中医师 / 中药师填写，并同时填写 `reviewed_by` / `reviewed_at`。

> 当前表内全部为 `pending`，所以界面会普遍显示「待验证」标记。
> 这是**刻意**的：标记密度就是审核进度的可见反馈，不要为了"界面好看"去批量置为 `approved`。

---

## 4. 别改坏这些契约

以下都是有意为之的设计，改动前请先读 `docs/three-layer-architecture.md`，
并在 PR 里说明为什么原设计不成立：

1. **`app/domain/models.py` 是请求 / 响应 / 中间结构的唯一真源。**
   改这里的字段名等于改对外契约，必须同步 `ui/` 下的所有壳与两个 Agent 的提示词。

2. **`app/domain/nature_math.py` 是四性运算的唯一真源。**
   任何涉及寒热加减的地方都必须走它，不要在别处另写一套 ±1 逻辑。
   注意 `unknown` 没有数值（返回 `None`），不是 `0`。

3. **温度判定只有一个入口：`nature_math.resolve_temperature(name, note)`。**
   历史上解析层用前缀匹配、提示词层用子串匹配，两套逻辑漂移过
   （「冰淇淋」在解析层被正确排除，在提示词层却被当成冰镇）。
   新增前缀**只改 `CHILL_PREFIXES` / `HEAT_PREFIXES` 一处**。

4. **`resolve_food()` 的判定顺序不可颠倒**：未命中表 → 食材变体层 → 烹饪修正层 → 温度前缀层。
   表里精确的变体值会被通用烹饪规则破坏，所以变体层必须优先。

5. **置信度约定**：`rule` 0.9 / `composed` 0.6 / `llm` 0.3 / `unresolved` 0.1；
   **低于 0.3 时界面不显示寒热属性**（但数据仍传给 Agent2）。
   所有非 `rule` 来源必须标注「待验证」。

6. **规范名精确命中时，不叠加模型给的烹饪修正。**
   因为无法从模型输出可靠区分"可靠证据"与"猜测"——模型会给「希腊酸奶」一个 `cold`、
   给「火腿三明治」一个 `grilled`。需要修正时应在表里为该食物单列条目并写 `variant_nature`，
   而不是放宽这一层。

7. **`.gitattributes` 强制 LF，写数据文件的脚本显式用 `newline="\n"`。**
   请不要让编辑器引入 CRLF，否则会产生大量假 diff。

8. **`ui/` 单向依赖 `core/`——反向依赖绝对不允许。**

   ```
   ui/terminal/  ui/web/        ← 前端交互层（所有"壳"）
        │  只允许向下 import
        ▼
   core/app/                    ← 核心逻辑层（domain / services / agents / api）
   ```

   * `ui/` 可以 `import app.*`，**可以**改自己的展示逻辑，**不可以**改 `core/app/domain/`、
     `core/app/services/`、`core/app/agents/`。
   * `core/` **不得** import `ui/` 下的任何东西，也不得假设自己正被某个特定界面调用。
     界面差异（终端 / Web / 未来的 GUI）只体现在 `ui/` 里，核心层对它们一无所知。
   * 新增一个界面 → 在 `ui/` 下加一个子目录并复用核心；**不要**为此在核心层加分支、
     加参数、加 `if 是终端` 之类的判断。
   * 唯一的接缝是 `core/app/domain/models.py` 定义的请求 / 响应结构（契约 1）。
     界面需要新数据时，先改 `models.py` 并同步所有壳，而不是让核心层去适配某个壳。
   * `core/app/main.py`（FastAPI 入口）与 `core/app/config.py` 属于**适配 / 基础设施层**，
     不是核心判定逻辑：为 Web 壳加路由或路径配置是允许的，
     但 `domain/`、`services/`、`agents/` 不应因界面变化而改动。

   > 判断标准很简单：**如果删掉 `ui/` 整个目录，`core/` 应当仍然能跑通
   > `pytest`、`smoke_offline.py` 和 `--resolve` 那条纯规则链路。**
   > 这是每次评审都要确认的事。

9. **API Key 绝不进日志、响应体或异常信息。这是硬规则，退化成"把 Key 打进日志"就是事故。**

   本项目支持**用户自带 Key**：Key 通过 `Authorization: Bearer <key>` 头逐请求传入
   （见 `core/app/api/auth.py`），因此它会在进程内存里流动。必须守住：

   * **不得**记录 `Authorization` 头，不得记录 Key 本身，也不得记录它的任何片段。
     连"前 6 位 + 后 4 位"这种掩码也**不要**加进请求路径 —— 已有的
     `check_setup.py` / `smoke_agents.py` 掩码打印的是**服务端配置文件里的** Key，
     那属于本地自检，可以保留。
   * **不得**把 Key 放进响应体、错误详情或 `HTTPException(detail=...)`。
   * 上游报错时**不要回显响应体**：官方 401 的响应体自带掩码后的 Key，
     但"绝不回显任何与凭据相关的内容"这条更容易守。参见
     `DirectAPIRuntime._describe_error()`。
   * 允许记录的只有：模型名、接口主机名、耗时、token 用量、`session_id`。
   * **不得**添加会打印请求头的中间件或日志配置。

   配套测试在 `core/tests/test_key_handling.py`，用哨兵 Key 断言它
   不出现在日志、响应体与异常信息里。改任何与凭据相关的代码后必须跑它：

   ```powershell
   python -m pytest tests\test_key_handling.py -q
   ```

10. **本项目不使用服务端内置 Key。任何"偷偷用某个 Key"的降级都不允许。**

   这是产品底线，不是实现细节：Key 由调用方提供，**没有 Key 就必须明确失败**，
   绝不能回退到"服务端配的那个"。用户看不到自己的钱是怎么被花掉的，是最坏的情况。

   * 没有 Key → `NO_API_KEY`（400），信息里说清去哪儿给：
     网页的「API Key」一栏，或终端/脚本的环境变量 `DEEPSEEK_API_KEY`。
     **不得**再指引用户把 Key 写进任何配置文件——本项目不从文件读 Key。
     这条文案历史上错过两次（先教用户写 `.env`，后教用户写 `credentials.env`），
     已有回归测试钉住。
   * Key 被模型服务方拒绝 → `API_KEY_REJECTED`（400），提示去改 Key，
     而不是 `AGENT1_FAILED`（那会把人引向"我描述得不对"）。
   * `TA_BACKEND=dsh` 且带了 Key → `USER_KEY_UNSUPPORTED`（400）并说明怎么解决。
     dsh 的 Key 与子进程绑定，**不能**静默复用旧 Key。
   * **安全分支必须无条件可用**：高风险人群检查放在凭据校验**之前**，
     因为那个分支不调用模型、不花钱 —— 没填 Key 的用户输入"我怀孕了"，
     应该看到"请先咨询执业医师"，而不是"缺少 API Key"。
   * 凭据类错误的 HTTP 状态码用 **400**（配置问题，换个说法重试没用），
     而不是 422（解析失败）。

   > 相关背景：`dsh` 的 Key 生效粒度是「一个 harness 实例 = 一个 dsh 子进程」，
   > `DeepSeekHarness.__init__` 把 `api_key` 写进子进程环境，`run()` 没有凭据参数。
   > 所以 `dsh` 后端天然做不到逐请求换 Key —— 这也是默认后端是 `direct` 的原因。

---

## 5. 提交与 PR

### Commit message

沿用仓库现有风格（Conventional Commits 前缀 + 中文描述）：

```
fix: 温度语义不再与模型 cooking 叠加，避免双重扣分
feat: 温度判定收拢为单一入口，同时扫描 name 与 note
```

* 一类改动一个 commit，别把「改数据」和「改提示词」混在一起。
* 数据表的改动请在正文里列清楚**改了哪几条**、依据是什么（可引用通行表述，但不要编造来源）。

### PR 检查清单

以下命令除注明外，都在 `core/` 目录下执行。

- [ ] `python scripts\check_setup.py` 通过
- [ ] `python scripts\smoke_offline.py` 通过
- [ ] `python -m pytest -q` 全绿（当前基线 **228 passed**）
- [ ] **碰了凭据 / 日志的：`python -m pytest tests\test_key_handling.py -q` 全绿**（契约 9、10）
- [ ] 改了提示词 / 判定逻辑的，附 `python scripts\smoke_agents.py` 的**前后对比**
- [ ] 改了数据表的，先跑过对应脚本的 `--dry-run`，且 `git diff` 已人工复核
- [ ] **动了 `ui/` 的：确认 `core/` 没被反向污染**——临时把 `ui/` 改名移走，
      `core/` 下 `pytest` / `smoke_offline.py` 仍应全绿（契约 8）
- [ ] 没有提交任何凭据（`.env` / `credentials.env` / `dsh-home/` 均不得入库）
- [ ] 新增的判定分支都补了测试；新增的已知局限写进
      `docs/three-layer-architecture.md` 的「已知局限」一节

> 改了 Agent 运行时（`core/app/agents/runtime.py` 或 `direct_api.py`）的，
> 除了 pytest 之外**必须**跑一次真实模型回归，因为线上行为只在那里体现：
>
> ```powershell
> python scripts\test_food_accuracy.py   # 属性准确率（基线 29/29，unknown 0）
> python scripts\smoke_agents.py         # 全链路格式与推荐条数
> ```
>
> 注意 `test_food_accuracy.py` **只测 Agent1 的属性判定**，测不出推荐质量；
> 涉及 Agent2 的改动请人工读一遍 `smoke_agents.py` 的输出。

### 关于「已知局限」

`docs/three-layer-architecture.md` 末尾单列了一节已知局限（关键词子串会拉进无关条目、
组合推理 `combine()` 尚未接入主流程、数据尚未人工审核等）。
**那不是待修的 bug 清单，而是有意的取舍记录。** 修掉其中一条时请同步更新那一节，
而不是删掉它——把局限写清楚比假装完美更有价值。
