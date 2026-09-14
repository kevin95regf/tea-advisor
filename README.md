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
| 双 Agent 提示词与实现 | ✅ 完成，**待真实模型验证** |
| 规则兜底（模型失败时降级） | ✅ 完成 |
| FastAPI 接口 `/api/analyze` | ✅ 完成，HTTP 实测通过 |
| 网页 demo | ✅ 完成 |
| 真实模型冒烟 | ⏳ 需要你的 API Key |
| 微信小程序 | ⏸ demo 验证后再做 |

---

## 快速开始

### 1. 配置环境变量

```powershell
cd D:\work\tea-advisor
Copy-Item .env.example .env
notepad .env      # 填入 DEEPSEEK_API_KEY
```

`.env` 已被 `.gitignore` 忽略，不会提交到仓库。

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

## 待验证事项（重要）

以下三点我无法在当前环境验证，需要你在真实环境确认：

1. **`DeepSeekHarness` 的构造参数与凭据传递方式**。代码按官方文档写了
   `dsh_home` / `cwd` / `provider` / `model` / `max_tokens` / `api_key` / `base_url`，
   首次跑 `smoke_agents.py` 时如报参数错误，对照
   [Python SDK 文档](https://deepseek-harness.github.io/deepseek-harness/guide/python-sdk) 调整 `app/agents/runtime.py`。
2. **系统提示词注入方式**。当前把系统提示词拼在 user 消息前（`runtime.run` 的 `system_prompt` 参数），
   并在 `smoke_agents.py` 里通过 `DSH_SYSTEM_PROMPT` 影响子进程。若发现模型不守格式，
   更稳的做法是给每个 agent 单独一个 profile + patch 文件。
3. **`herbs.json` 的医学准确性**。文件里 `_meta.review_status` 标的是 `pending`：

   > 属性、剂量上限、禁忌均为保守整理的通行表述，**上线前必须由具备资质的中医师/中药师复核**，
   > 并以国家卫健委发布的最新「既是食品又是中药材的物质目录」为准。

另外：主力模型只用于生成结构化 JSON，**不建议开启联网/工具能力**。

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
