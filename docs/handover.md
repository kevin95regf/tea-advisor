# tea-advisor 项目交接文档

> **这份文档的用途**：让一个完全没有上下文的团队（或新平台/新会话）读完之后，能独立理解项目全貌、
> 知道哪些决定已经定了不能随便改、哪些还悬着、以及接手第一件事该做什么。
>
> **它不重复训练材料**：三层判定架构的完整设计在 `docs/three-layer-architecture.md`，
> 日常维护与排错在 `docs/maintenance.md`。本文只做**全貌 + 决策 + 边界**。
>
> 快照时间：**2026-09-17**。凡是会随代码变动的数字，本文都标了口径，可自行重测。

---

## 1. 一分钟版本

**tea-advisor 是一个中医食性的「确定性判定层」，外面套了一个本地饮食茶饮建议助手，带终端和本地 Web 两个壳。**

它解决的核心问题是：**大模型在中医食性上会一本正经地胡说**。实测过的例子——模型把性温的茉莉花茶判成「凉」。所以项目把食性判定从模型手里拿走，做成可审计的查表 + 规则运算，模型只负责它擅长的自然语言部分（理解用户吃了什么、组织推荐文案）。

三个数字概括现状：

| | |
|---|---|
| 代码 | 45 个源文件 / 10,027 行，其中 `domain` + `services`（真正的资产）2,075 行 |
| 测试 | **428 项，全离线，约 4 秒** |
| 数据 | 食性表 147 条、饮片 34 味、体质 9 型（全部就绪）、食药物质目录 106 种、药典核对 34 味、饮片来源登记 34+24 条 |

**它明确不是什么**：不是医疗器械、不做体质辨识诊断、不承诺任何疗效。所有输出都带免责声明，且禁用「治疗/根治」这类表述（有护栏强制）。

---

## 2. 核心设计原则

这一节是项目的骨架。**改动代码前先读这七条**，它们解释了绝大多数看似奇怪的实现。

### 2.1 判定必须确定性、可审计

食性判定优先走查表和规则运算，**不让模型猜**。每个判定结果都带 `Verification`（来源 + 置信度 + 判定过程），界面必须原样展示，让用户能区分：

| 来源 | 置信度 | 中文说法 |
|---|---|---|
| 表命中（已审核） | 0.9 | 查表 |
| 组合推理 / 烹饪修正 | 0.6 | 按烹饪方式推算 |
| 模型推测 | 0.3 | 模型推测 |
| 无法判定 | 0.1 | 无法判定 |

**低于 0.3 界面不显示寒热属性**（数据仍传给 Agent2）。宁可说「未判定」，也不给一个不可信的答案。

### 2.2 三层混合，顺序不可颠倒

`resolve_food()` 的判定顺序是固定的，**任何调整都会改变大量既有结果**：

```
① 温度前缀准入（纯规则，最高优先）
② 精确名查表（表里有的，直接采信，不再叠加模型的烹饪判断）
③ 食材变体层（variant_nature，查表优先）
④ 烹饪修正层（仅 ③ 未命中时兜底：冰镇 −1 / 煎炸 +1 / 烧烤 +1）
⑤ 温度前缀位移（兜底）
```

**为什么顺序不能颠倒**：表里精确的变体值会被通用规则破坏；温度语义若与模型的烹饪判断叠加，会双重扣分（历史上真出过这个 bug）。

### 2.3 四性用数值轴，`unknown` 不是 0

寒 −2 / 凉 −1 / 平 0 / 温 +1 / 热 +2。

**`unknown` → `None`，不是 0。** 这个区分很关键：0 会把「不知道」算成「平性」，在合成运算里造成静默的错误结论。

### 2.4 安全边界在结构上锁死，不靠提示词

不是「请模型不要开方」，而是：**模型能选的饮片只能来自受限候选集**（`filter_by_constitution`），且输出必经确定性护栏（`safety.py`）——白名单、剂量上限、禁忌人群、禁用表述。意图越界也写不出来。

护栏的**不变量**：被拦的内容绝不原样返回给用户；全被拦则整条作废并走规则兜底。

### 2.5 永远给得出东西（降级而非失败）

模型不可用、没给 Key、JSON 解析失败、推荐全被拦——以上任何一种情况都**不能变成 500**。链路末尾一定有 `matcher.fallback_recommend` 兜底，产出合法且不超剂量的搭配，并在响应里标 `meta.degraded=True`。

三条**零成本**路径从不碰模型：

| 入口 | 用途 | 成本 |
|---|---|---|
| `food_lookup.resolve_food()` | 只要属性判定 | 0 |
| `ui/terminal/chat.py --offline` | 无 Key 也给建议 | 0 |
| 高风险人群分支（孕期/慢性病/服药） | 引导就医 | 0（不调用模型） |

### 2.6 分层是硬约束

**`ui/` 单向依赖 `core/`；`core/` 永远不 import `ui/`。**

验收方式很硬核：**删掉 `ui/` 目录，`core/` 必须仍然通过 `pytest` 与 `smoke_offline.py`。**

> ⚠️ **唯一的例外**：`core/tests/test_web_shell.py` 是 `ui/web/index.html` 的静态守卫，
> 它必须读到那个文件。**删掉 `ui/` 时请用 `pytest -k "not web_shell"` 排除它** ——
> 分层约束（删掉 `ui/` 后 `core/` 仍能独立工作）依然成立，
> 只是这条守卫本身依赖它被守卫的对象。
> 该页面此前零测试覆盖，2026-09-18 补的这 6 条守卫只守「搬进弹窗时最容易丢的东西」：
> 「记住 Key」默认不勾、无 sessionStorage→localStorage 搬迁、`/healthz` 提示与默认文案仍在、
> 凭据错误会打开弹窗、Key 状态指示不回显 Key、两个按钮共用 busy 开关。

### 2.7 不内置任何人的 API Key

项目**没有服务端兜底 Key**（这不是配置开关，是代码层面的移除）。Key 只有两个来源：

- Web：前端 `Authorization: Bearer` 头（存 localStorage，可选「记住 Key」，默认不勾）
- 终端 / 脚本：环境变量 `DEEPSEEK_API_KEY`

**硬规则（有测试守着）**：`/api/analyze` 绝不记录 `Authorization` 头，绝不把 Key 写进日志或响应体。

---

## 3. 目录结构与分层规则

```
tea-advisor/
├─ core/                        ← 所有逻辑，独立可用的库
│  ├─ app/
│  │  ├─ domain/                核心判定（纯逻辑，不依赖 Web 框架）
│  │  │   enums.py              四气/五味/时段/烹饪/体质枚举 + 中文标签
│  │  │   nature_math.py        四性数值轴、温度前缀唯一入口
│  │  │   models.py             请求/响应/中间结构唯一真源
│  │  │   safety.py             白名单/剂量/禁用表述/高风险人群
│  │  ├─ services/
│  │  │   food_lookup.py        resolve_food 三层判定、match_foods
│  │  │   matcher.py            规则兜底、体质默认搭配
│  │  │   orchestrator.py       编排、凭据校验、护栏调用、降级
│  │  ├─ agents/
│  │  │   runtime.py            后端选择器（direct | dsh）
│  │  │   direct_api.py         直连官方 API 后端（默认）
│  │  │   agent1_diet.py        解析用户吃了什么 + 校准
│  │  │   agent2_recommend.py   生成推荐 + 未验证项隔离
│  │  │   json_guard.py         JSON 提取/校验/重试
│  │  │   prompts/*.md          两个 system prompt
│  │  ├─ api/                   HTTP 适配（极薄）
│  │  ├─ config.py              环境变量集中读取（Key 的唯一读取点）
│  │  └─ main.py                FastAPI 入口
│  ├─ data/                     数据层（详见 §4）
│  ├─ scripts/                  运维 / 自检 / 文档生成脚本
│  ├─ tests/                    428 项离线测试
│  └─ pyproject.toml
├─ ui/
│  ├─ terminal/chat.py          终端壳（仅标准库）
│  └─ web/index.html            网页壳（单文件，内联 JS）
├─ docs/                        文档（详见 §8）
├─ tcm-constitution-questionnaire/   nanple 贡献的国标问卷实现（独立子项目）
├─ start-web.cmd / start-terminal.cmd   Windows 双击启动
└─ .env.example / credentials.env.example
```

**依赖方向**：`ui/` → `core/app/main.py` 或直接 import `core/app/services`。反向的 import 一律视为架构破坏。

**中文标签的单一真源**：Web 壳走 `GET /api/meta`，终端壳直接 import `app.domain.enums`。**不要把标签硬编码到壳里。**

**技术栈**：Python ≥3.10、pydantic v2、FastAPI/uvicorn（可选 `[web]` extra）、httpx、python-dotenv、deepseek-harness-sdk。`core/` 的核心依赖装完就能 `from app.services.food_lookup import resolve_food`，不需要 Web 框架。

---

## 4. 数据资产

| 文件 | 内容 | 规模 | 参与运行时判定？ |
|---|---|---|---|
| `core/data/food_properties.json` | 食材 + 茶饮食性表，逐条审核状态 | 147 条（129 食材 + 18 茶饮） | ✅ 是 |
| `core/data/herbs.json` | 饮片白名单（剂量上限、禁忌、归经、宜忌体质） | 34 味 | ✅ 是 |
| `core/data/constitution.json` | 体质定义 + 调养原则 | 9 型（全部就绪） | ✅ 是 |
| `core/data/food_medicine_catalog.json` | 国家卫健委食药物质目录（4 批公告汇编） | 106 种 | ❌ 只用于合规自检 |
| `core/data/herb_nature_reference.json` | 药典 2020 一部记载 + 与项目的比对结果 | 34 味 | ❌ 只用于核对 |
| `core/data/herb_evidence_sources.json` | 饮片侧来源登记表：属性依据 + 体质适配依据 + 来源注册表 | 34 味 + 24 条 | ✅ 是（只生成 `basis.references`，不参与判定） |

**审核三态**（`review_status`）：`approved` = 真·硬规则库，界面不标注；`pending` = 0.9 但界面必须标「待验证」；`rejected` = 降为 0.6，不作硬规则。

> ⚠️ **当前 147 条全部是 `pending`，没有一条经人工审核。** 这是「对外提供服务」的唯一硬阻碍，且只有具备资质的中医师/中药师能解。详见 §7 挂起事项。

字段含义写在各自的 `_meta.field_notes` 里，**改结构时同步改它**。

> ⚠️ **「收录」与「可对外服务」是两件事，判据由数据派生。** `constitution.json` 与 `enums.py` 含国标九型，
> 但某个体质能否对外服务，取决于 `herbs.json` 里是否至少有 1 味把它标进 `suitable_constitutions`
> （判据函数 `safety.ready_constitutions()`）。2026-09-17 写入四型的配伍标注后，**九型已全部就绪**，
> `GET /api/constitutions` 返回 9 项。这条闸门不会消失：将来任何新增体质，数据没备齐就不会被暴露
> ——下拉框里不出现，手搓请求指定则得到 422 而非 500。详见 `docs/pending-items.md` B3。

---

## 5. 当前状态

### 5.1 规模（口径：Python `bytes.count(b"\n")`，排除 `__pycache__`）

| 层 | 文件 | 行数 |
|---|---|---|
| `core/app/domain` | 5 | 973 |
| `core/app/services` | 4 | 1,102 |
| `core/app/agents` | 8 | 1,164 |
| `core/app/api` | 3 | 115 |
| `core/tests` | 13 | 2,919 |
| `core/scripts` | 10 | 2,907 |
| `ui/terminal` | 1 | 398 |
| `ui/web` | 1 | 449 |
| **合计** | **45** | **10,027** |

> 判断架构是否健康的快速指标：**`domain` + `services` 的行数占比**。这两层是真正的资产（2,075 行）。
> 若开始膨胀，说明有人在把界面逻辑或模型逻辑塞进核心层。

### 5.2 已验证的功能

- ✅ 三层判定 + 置信度体系（428 项离线测试覆盖）
- ✅ 双 Agent 链路（Agent1 解析 → Agent2 推荐）
- ✅ 确定性护栏（白名单/剂量/禁忌/禁用表述/高风险人群）
- ✅ 规则兜底（模型不可用时仍给出合法搭配）
- ✅ 逐味公开依据链（属性依据 33/34 味 + 体质依据 24 条，随推荐返回 `basis.references`，两个壳都呈现）
- ✅ 两个后端：`direct`（直连官方 API，默认）与 `dsh`（DeepSeekHarness 子进程）
- ✅ 用户自带 Key，逐请求传递，无服务端兜底
- ✅ 终端壳 + 本地 Web 壳
- ✅ 三条零成本路径

### 5.3 质量基线（2026-09 实测）

| 指标 | dsh + low | direct + low | direct + off |
|---|---|---|---|
| 属性准确率（23 语料 / 29 断言） | 29/29 | 28/29 | **29/29** |
| unknown 占比 | 0/35 | 0/34 | 0/34 |
| 全链路耗时 | 11.3–24.9 s | 12.6–15.6 s | **5.1–5.7 s**（本项 2026-09-17 复测为 3.0–6.3 s） |
| 推荐条数 | 2–3 | 2–3 | ⚠️ **1–3（3 例实测 3/1/1）** |

`direct + low` 的那 1 项失败**已定位，不是回归**：Agent1 偶然把「配辣椒油」写进 `note`，合法触发了辛辣 +1 规则。

> ⚠️ `off` 会让**推荐条数常从 2–3 掉到 1 条**，所以默认值仍是 `low`（决策 #11）。
> 要省时省钱（耗时降 2–4 倍、成本降一个量级）可自行设 `TA_REASONING_EFFORT=off`，代价就是上面这一行。

> ⚠️ `test_food_accuracy.py` **只测 Agent1 的属性判定**，完全不碰 Agent2。改 Agent2 或提示词时，
> 必须人工读一遍 `smoke_agents.py` 的输出——推荐质量没有自动化断言。

### 5.4 成本

一次完整查询：**空闲约 1.02 分，高峰约 2.03 分**（高峰 = 周一至周五 9:00–12:00、14:00–18:00 北京时间）。

**输出占成本 92.2%，其中 Agent2 占 84%。** 省钱的唯一杠杆是缩短输出，最有效的旋钮是思考强度（`off` 让 Agent2 输出从 2,028 token 降到数百级）。Agent1 几乎免费（0.163 分/次）。

⚠️ 但 `off` 不是免费的午餐：它会让**推荐条数常从 2–3 条降到 1 条**（§5.3 末行），因此默认不启用，详见决策 #11。

### 5.5 验证命令

```bash
cd core
python -m pytest -q                    # 335 项，全离线，约 0.9 秒
python scripts/smoke_offline.py        # 数据层→解析→规则兜底→护栏，不调模型
python scripts/check_setup.py          # 环境与数据自检
# 以下需要 API Key：
python scripts/smoke_agents.py         # 真实模型冒烟，约 60–90 秒，产生费用
python scripts/test_food_accuracy.py   # 属性准确率，只测 Agent1
```

---

## 6. 所有已定决策

以下决策**已经定案**。改动其中任何一条都意味着推翻决定，请显式确认。

### 6.1 定位与架构

| # | 决策 | 理由 |
|---|---|---|
| 1 | **定位为本地桌面助手 / 开源 CLI+Web 库，不做微信小程序** | 个人主体过不了「深度合成-AI 问答」类目审核，医疗健康类目对个人关闭 |
| 2 | **保留核心资产、只换壳，不重写** | `resolve_food` 确定性判定、三层架构、双 Agent、34 味食性表、测试体系全部保留 |
| 3 | **原地改造，保留 Git 历史，不迁移** | 仓库留在 `D:\work\tea-advisor` |
| 4 | **LICENSE = MIT** | 开源友好 |
| 5 | **`ui/` 单向依赖 `core/`** | 验收：删掉 `ui/` 后 `core/` 仍过 pytest + smoke_offline |
| 6 | **不改写 Git 历史** | 避免对公开仓库 force-push、避免变更协作者 nanple 的 commit hash |

### 6.2 凭据与后端

| # | 决策 | 理由 |
|---|---|---|
| 7 | **用户自带 Key；服务端兜底 Key 已从代码中彻底移除** | 不消耗任何人的额度；不设「默认用服务端 Key」的隐患 |
| 8 | **前端 Key 存 localStorage，「记住 Key」默认不勾选（仅本次会话）** | 共享电脑场景下的默认安全 |
| 9 | **`TA_BACKEND=direct`（默认）\| `dsh`** | dsh 一个实例 = 一个子进程，Key 绑在子进程环境上，**无法按请求切换 Key**，所以逐请求 Key 只能用 direct |
| 10 | **日志安全硬规则**：`/api/analyze` 绝不记录 Authorization 头、绝不把 Key 写进日志或响应体 | 有 sentinel 串测试守着 |
| 11 | **思考强度保持 `low`** | 2026-09-17 实测定案：`off` 更快（全链路 12.6–15.6 s → 3.0–6.3 s）、更省（成本降一个量级）、准确率无损失，但**推荐条数常从 2–3 掉到 1 条**（3 例实测 3/1/1）。demo 阶段不接受这个体验降级，故保持 `low`；需要压成本/延迟时可自行设 `TA_REASONING_EFFORT=off`。数据见 §5.3 / §5.4 |

### 6.3 判定层

| # | 决策 | 理由 |
|---|---|---|
| 12 | **三层判定顺序不可颠倒** | 见 §2.2；颠倒会破坏表内精确值与通用规则的优先级 |
| 13 | **置信度 0.9/0.6/0.3/0.1，低于 0.3 界面不显示四性** | 宁可说「未判定」也不给不可信答案 |
| 14 | **四性数值轴 寒−2/凉−1/平0/温+1/热+2；`unknown` 是 `None` 不是 0** | 0 会把「不知道」算成平性 |
| 15 | **温度语义走纯规则层，不与模型的烹饪判断叠加** | 历史上出过双重扣分 bug |
| 16 | **体质数据缺失时抛错而非静默退化** | 静默退到「目录前 N 味」会让阴虚质拿到温补辛温之品，**方向相反且从输出表面看不出来** |
| 17 | **规则兜底层的契约是「永远给出合法且安全的搭配」** | 不能抛异常变成 500 |

### 6.4 数据与合规（2026-09-17 新增）

| # | 决策 | 状态 |
|---|---|---|
| 18 | **导入国家卫健委食药物质目录 106 种**（4 批公告：87+6+9+4），逐条保留公告原文串以便逐字核对 | ✅ 已实施 |
| 19 | **玫瑰花：保留，但名称需明确品种为「玫瑰花（重瓣红玫瑰）」** | ⏳ 待实施（等 nanple 审数据） |
| 20 | **茉莉花：标注「仅作参考」，推荐时排除** | ⏳ 待实施（等 nanple 审数据） |
| 21 | **橘红：归属 2002 年附件 1 的「桔红」，视为在目录内** | ✅ 已实施（无需改代码） |
| 22 | **药典与项目不一致的 7 处：先保留项目值**，文档标注药典值与差异影响，等 nanple 复核 | ⏳ 待 nanple 复核 |
| 23 | **四气降档约定：微寒→凉、微温→温**。**这是项目约定，不是药典原文**；药典原文用词一律保留 | ✅ 已认可 |
| 24 | **九型体质 id 全部确认**：`balanced` / `qi_deficiency` / `yang_deficiency` / `yin_deficiency` / `phlegm_damp` / `damp_heat` / `blood_stasis` / `qi_stagnation` / `special_diathesis` | ✅ **已实施（Step 1 + Step 2，2026-09-17）**：枚举 / `constitution.json` / 就绪闸门已扩到 9 型，`herbs.json` 补入 10 格来源点名的配伍标注，九型全部就绪且对外可见；同日第二批又由外部专业意见写入 5 格（见 `docs/herbs-9types-batch2.md`）。244 格里余 239 格的完整判定仍待 nanple，见 B3 |
| 25 | **国标 A 栏（九型特征）用官方解读/起草人访谈的转引，逐条标注「非标准正文」** | ✅ 已实施 |
| 26 | **《中华本草》列统一标「待确认」，不猜** | ✅ 已实施（取不到数据，见挂起事项） |

### 6.5 协作与文档

| # | 决策 | 理由 |
|---|---|---|
| 27 | **244 个配伍判定提给 nanple**（34 味 × `suitable_constitutions` + 27 味 × `unsuitable_for`，针对 4 个新体质） | 无标准可依，必须由懂中医的人判定 |
| 28 | **nanple 问卷项目的 `phlegm_dampness` vs 本项目 `phlegm_damp` 拼写不一致，作为第一个 Issue** | 接入前必须解决 |
| 29 | **区分「冻结的一次性批次脚本」与「可重跑的只读工具」** | `scripts/` 下 `add_food_entries.py` / `add_review_fields.py` / `patch_food_table.py` 是**冻结的历史批次脚本**，改数据前必须 `--dry-run`；`check_herb_catalog.py` / `build_*.py` 是**可反复运行的只读工具** |
| 30 | **生成的文档不手工编辑** | `catalog-compliance.md`、`constitution-9-types.md`、`herb-nature-crosscheck.md` 三份都由脚本从 JSON 渲染，JSON 是事实源 |
| 31 | **仓库强制 LF**（`* text=auto eol=lf`，`*.cmd`/`*.bat` 例外） | 避免 Windows 上的假 diff；Python 写文件要显式 `newline="\n"` |

---

## 7. 未决事项

**完整的挂起清单、责任人、阻塞关系见 `docs/pending-items.md`。** 这里只给摘要：

| 类别 | 事项 | 谁来解 |
|---|---|---|
| **对外服务前的硬阻碍** | 147 条食性数据全部未人工审核（全 `pending`） | 具备资质的中医师/中药师 |
| **只等 nanple** | 7 处药典不一致复核；244 个配伍判定（已落地 15 格，余 239 格）；问卷拼写不一致 | nanple |
| **只等你决定** | 玫瑰花/茉莉花的代码改动时机 | 项目所有者 |
| **受外部资源阻塞** | 《中华本草》列全空（取不到公开数据）；国标 A 栏是转引（正文有付费墙） | 取得资料后可解 |
| **技术债** | 3 条食性表缺 `review_status`；`herbs.json` 缺逐条审核字段 | 开发 |

---

## 8. 文档地图

| 文档 | 用途 | 何时读 |
|---|---|---|
| `README.md` | 面向使用者：装什么、怎么跑、`--resolve` 什么输出 | 第一次接触 |
| `CONTRIBUTING.md` | 面向贡献者：契约、验证流程、改动规范 | 准备提 PR |
| `docs/three-layer-architecture.md` | **三层判定架构的完整设计** | 改判定逻辑前 |
| `docs/maintenance.md` | 日常维护、运维手册、排错手册、成本模型 | 出问题时 |
| `docs/pending-items.md` | **挂起事项清单（唯一真源）** | 接力/排期时 |
| `docs/catalog-compliance.md` | 饮片白名单 × 食药物质目录核对 + 处置决定 | 涉合规时 |
| `docs/constitution-9-types.md` | 国标九型特征与饮食方向（A/B/C 三层，带出处） | 做 5→9 时 |
| `docs/herb-nature-crosscheck.md` | 34 味药典对照表 + 差异影响分析 | 涉药典数据时 |

**三份生成型文档不要手工编辑**（重新生成命令写在各自开头的引用块里）：

```bash
cd core
python scripts/check_herb_catalog.py --format md --out ../docs/catalog-compliance.md
python scripts/build_constitution_doc.py
python scripts/build_herb_crosscheck.py
python scripts/build_herb_sources.py --write
```

它们的内容都渲染自数据文件（`core/data/food_medicine_catalog.json`、
`docs/constitution-9-types.json`、`core/data/herb_nature_reference.json`、
`core/data/herb_evidence_sources.json`），
**那些 JSON 才是事实源**；`--check` 模式可只校验不写文件，适合进 CI。

---

## 9. 工作区状态

**快照时间 2026-09-17。**

### 9.1 Git

| 项 | 值 |
|---|---|
| 分支 | `main`，**与 `origin/main` 已同步**（2026-09-17 推送达 `010db2f..7ed495a`，6 个提交） |
| 准确状态 | 跑 `git log --oneline origin/main..HEAD`（输出为空即已同步） |
| 提交总数 | 31（截至 2026-09-17 推送时；取当前值跑 `git rev-list --count HEAD`） |
| 远程 | `https://github.com/kevin95regf/tea-advisor.git`（公开） |
| 标签 | `demo-1-backend`、`v1-llm-only` |
| 工作区 | **干净**（无未提交改动、无未跟踪文件） |
| 跟踪文件数 | 84（截至本次推送；取当前值跑 `git ls-files \| Measure-Object`） |

**2026-09-17 这批工作的产出**（按时间顺序，本文档自身的提交在其后）：

```
2be4e64 feat: 导入食药物质目录并核对饮片白名单
c60565a docs: 登记饮片合规的三个处置决定
470e6b3 docs: 整理国标九种体质的特征与饮食方向（带出处）
854c7ad feat: 用《中国药典》2020 版一部核对 34 味饮片的性味归经
f3b7b6f docs: 落实四条数据决定，并为药典差异补上代码取证的影响分析
```

> ⚠️ 推送由项目所有者决定，不属于开发默认动作。

### 9.2 本地文件（不入库，需要就地重建）

| 文件/目录 | 作用 | 是否必需 |
|---|---|---|
| **`core/.venv/`** | **真正装了依赖的虚拟环境**。所有命令都用它 | **是** |
| `.venv/`（仓库根） | ⚠️ **残留的半成品环境（已装发行版数约为 `core/.venv` 的 1/5，缺 pytest/fastapi/httpx/dotenv）**，来自目录改名前的时期 | 否，建议删掉 |
| `.env` | 本地运行参数（`TA_BACKEND`/`TA_MODEL` 等，**不含 Key**） | 可选，有默认值 |
| `credentials.env` | 只有 `DSH_HOME`（仅 dsh 后端需要） | dsh 后端必需 |
| `dsh-home/` | DSH 运行时目录，含完整对话日志，**绝不入库** | dsh 后端必需 |
| `.idea/` | 编辑器配置 | 否 |
| `NOTES.local.md` | 维护者本地备忘（含本机路径与待办），被 `*.local.md` 忽略 | 否（见下方提醒） |

> ⚠️ **`NOTES.local.md` 仅供参考，且已部分过期——一切以 `docs/` 下的文档为准。**
> 实测它与现状不符的地方：写「尚无远程」（实际已有 GitHub 远程）、写「`miniprogram/` 空目录待删」（已删除）、
> 写「全部提交都是占位符身份」（实际有 3 个作者）、写「pytest 230 项」（实际 335 项）。
> 它不在版本控制里，不会随文档同步更新，读到与本文冲突时**一律以本文和 `docs/pending-items.md` 为准**。

### 9.3 已验证的安全状态

- ✅ **全仓库无任何残留 API Key**（扫描 `sk-` 长串，排除 `.git`/`.venv`/`.dsh-home`，无命中）
- ✅ `.gitignore` 覆盖 `.env`、`credentials.env`、`dsh-home/`、`*.local.md`、`var/`、`logs/`
- ✅ 两份 `.env.example` / `credentials.env.example` 模板已入库
- ✅ `miniprogram/` 目录已删除

### 9.4 已知的环境陷阱（会浪费你时间）

| 陷阱 | 现象 | 正解 |
|---|---|---|
| **仓库根有两个 `.venv`，别用错** | 用 `..\.venv\Scripts\python.exe -m pytest` 报 `No module named pytest` | **只用 `core\.venv\Scripts\python.exe`**（它的已装发行版数约为根 `.venv` 的 5 倍）。根 `.venv` 是目录改名前的残骸 |
| **venv 里的 `.exe` shim 已失效** | `pip.exe` / `uvicorn.exe` 无声失败 | 一律用 `python -m pip` / `python -m uvicorn`（目录曾从 `backend` 改名为 `core`，shim 里的绝对路径失效） |
| **PowerShell `Get-Content` 解码错误** | 中文注释乱码；行数数错（实测把 66 行的文件数成 32） | 用 `read` 工具或 Python；数行数用 `bytes.count(b"\n")` |
| **PowerShell 管道把原生 UTF-8 输出当 GBK** | 中文输出乱码 | 设 `PYTHONIOENCODING=utf-8`；`Out-File -Encoding utf8` |
| **改了代码但行为没变** | 报出莫名其妙的错 | 多半是旧服务还占着端口，先按端口找进程 |
| **`pip install -e .` 后目录改名** | shim 失效 | 重新安装 |
| **`exit code: 1` 但输出完全正常** | 看似失败 | 可能是 `Select-Object -First N` 的断管假象，或本 shell 被中断 |

---

## 10. 新接手者的前 30 分钟

```powershell
# 1. 环境（约 2 分钟）
cd D:\work\tea-advisor\core
..\core\.venv\Scripts\python.exe scripts\check_setup.py       # 环境与数据自检
# 若 core\.venv 不存在才需要重建（注意：别用仓库根那个 .venv，它是残骸）
# python -m venv .venv ; .\.venv\Scripts\python.exe -m pip install -e ".[dev,web]"

# 2. 验证一切正常（约 1 分钟，不花钱）
..\core\.venv\Scripts\python.exe -m pytest -q                 # 期望 335 passed
..\core\.venv\Scripts\python.exe scripts\smoke_offline.py     # 期望全部通过

# 3. 零成本看它怎么工作（不花钱，不需要 Key）
..\core\.venv\Scripts\python.exe ..\ui\terminal\chat.py --resolve 冰啤酒 茉莉花茶
..\core\.venv\Scripts\python.exe ..\ui\terminal\chat.py --offline "中午吃了碗麻辣烫，还喝了杯冰可乐"

# 4. 再看文档（按这个顺序）
#    README.md → docs/handover.md（本文）→ docs/three-layer-architecture.md
#    → docs/pending-items.md
```

> 在 `core/` 目录下也可以直接用 `.venv\Scripts\python.exe`（相对路径短一点，指向同一个环境）。

**第 3 步的 `--resolve` 输出是理解项目的最快入口**：`detail` 字段会告诉你每一档判定是怎么来的、置信度多少、为什么显示或不显示四性。

**要跑真实模型**才需要 Key：

```powershell
$env:DEEPSEEK_API_KEY = "sk-..."      # 或改用 Web 界面在界面上填
python scripts\smoke_agents.py
```

---

## 11. 接手时的五个「不要」

1. **不要**为了让界面好看而批量把 `review_status` 置为 `approved`。那需要具备资质的人逐条审。
2. **不要**把项目 `effects` 字段改成药典【功能与主治】原文。`herbs.json` 的 `field_notes` 明确要求养生类措辞、禁止疗效承诺——这是合规要求，不是笔误。
3. **不要**在 `core/` 里 import `ui/`，也不要在 `domain`/`services` 里塞界面或模型逻辑。
4. **不要**把《中华本草》列的空缺当成「与药典相同」。空缺 = **未核实**。
5. **不要**在 `docs/` 里手工编辑三份生成型文档；改数据文件后重新跑生成脚本。

---

> **交接完成判定**：一个新团队能跑通 §10 的四步、能说清 §2 的七条原则、知道 §7 有哪些事悬着、
> 并且不会犯 §11 的五个错误——这份文档就履行了职责。
