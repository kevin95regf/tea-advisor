# 请求全链路流程图（从用户输入到最终结果）

> 版本：commit `23d3dce`（2026-09-18，454 项测试全过）
> 覆盖：网页 `ui/web/index.html` ／ 终端 `ui/terminal/chat.py` ／ 直调脚本
> 真源标注格式：`文件 :: 函数/类`。**不贴代码，只画流程与字段。**
>
> ⚠️ 本文件是**手工维护**的流程说明，不是生成产物。代码改了要同步改这里
> （`docs/handover.md` §2 是设计原则，本文件是执行路径，两者不重复）。

---

## 0. 一图总览

```
                     ┌──────────── 三种入口 ────────────┐
                     │                                  │
   网页 index.html   │   终端 chat.py      │  脚本 / 测试
   POST /api/analyze │   cmd_full          │  orchestrator.analyze()
   + Bearer Key      │   Key 来自环境变量  │  Key 由调用方给
                     └──────────┬───────────┘
                                ▼
              ┌─────────────────────────────────────────┐
              │  HTTP 层  api/analyze.py                │
              │  extract_api_key(Authorization)         │
              └─────────────────┬───────────────────────┘
                                ▼
   ╔═══════════════════════════════════════════════════════════════╗
   ║            orchestrator.analyze()  —— 唯一编排入口              ║
   ╠═══════════════════════════════════════════════════════════════╣
   ║  闸门① 高风险人群   detect_high_risk()  命中 → 直接返回（免费）║
   ║        ↓ 未命中                                                ║
   ║  闸门② 体质就绪     ready_constitutions()  不就绪 → 422        ║
   ║        ↓ 就绪                                                  ║
   ║  闸门③ 凭据校验     无 Key / dsh 后端 → 400                    ║
   ║        ↓ 通过                                                  ║
   ║  Agent1 解析饮食 → json_guard 校验 → 三层判定校准 → ParsedMeal ║
   ║        ↓ foods 非空                                            ║
   ║  候选集收敛        filter_by_constitution()（结构性限制）      ║
   ║        ↓                                                       ║
   ║  Agent2 生成推荐   失败/空 → matcher.fallback_recommend()      ║
   ║        ↓                                                       ║
   ║  闸门④ 输出护栏    _sanitize_recommendations()                 ║
   ║        ↓                                                       ║
   ║  组装响应          _build_basis() → herb_evidence()            ║
   ╚═══════════════════════════════════════════════════════════════╝
                                ▼
                        AnalyzeResponse（JSON）
                                ▼
              网页 render*() ／ 终端 render_*() 打印
```

**四道闸门的顺序是刻意的**（`orchestrator.py` 注释明写）：
① 在 ③ 之前 —— 安全提示必须无条件可用，不该被"没填 Key"挡掉；
② 在 ③ 之前 —— 体质没数据不是填个 Key 能解决的，先报更根本的那一条。

---

## 1. 入口层

| 入口 | 输入 | 怎么传 Key | 真源 | 出口 |
|---|---|---|---|---|
| 网页 | 输入框文本 + 体质下拉 +（弹窗里的 Key） | `Authorization: Bearer`，Key 存 localStorage/sessionStorage | `ui/web/index.html :: run()` | `POST /api/analyze` |
| 终端（完整） | `--text` + `--constitution` | 环境变量（`app.config.api_key_from_env`） | `ui/terminal/chat.py :: cmd_full()` | 直接调 `analyze()` |
| 终端（离线） | 同上 `--offline` | 不需要 | `ui/terminal/chat.py :: cmd_offline()` | 见 §5.6 |
| 脚本 | 构造 `AnalyzeRequest` | 自取 | `core/scripts/smoke_agents.py` | 直接调 `analyze()` |

`AnalyzeRequest` 字段（`core/app/domain/models.py`）：
`text`(1–500) / `meal_time` / `constitution_override` / `exclude_herbs` / `session_id`

---

## 2. 主路径（联网模式）逐步

### S1 HTTP 层

- **输入**：`AnalyzeRequest` + `Authorization` 头
- **输出**：`AnalyzeResponse` 或 `HTTPException{detail:{code, message}}`
- **真源**：`core/app/api/analyze.py :: analyze_endpoint`、`core/app/api/auth.py :: extract_api_key`
- **失败时**：`AnalyzeError` → `NO_API_KEY` / `USER_KEY_UNSUPPORTED` / `API_KEY_REJECTED` 用 **400**；
  `CONSTITUTION_NOT_READY` / `AGENT1_FAILED` 用 **422**；其余异常 → **500 `INTERNAL_ERROR`**
- **出口**：JSON 给前端；⚠️ Key **绝不进日志、绝不进响应体**
- **测试**：`tests/test_key_handling.py`（29 项，含日志安全 sentinel）

### S2 开单

- **输出**：`request_id = uuid4().hex[:16]`；`key_source = "user" if 有 Key else "not_used"`
- **真源**：`orchestrator.py :: analyze`

### S3 闸门① —— 高风险人群

- **输入**：`request.text` 原文
- **真源**：`core/app/domain/safety.py :: detect_high_risk`、`HIGH_RISK_KEYWORDS`（25 个：怀孕/哺乳/经期/儿童/化疗/糖尿病/高血压/服药/过敏…）
- **命中时输出**（**不调模型、不花钱**）：
  - `parsed` = 只有 `meal_time` + `summary="你提到了需要特别留意的情况"` 的空壳
  - `recommendations = []`
  - `basis.guardrail_applied = ["命中高风险关键词：…"]`
  - `meta.degraded=True` / `degraded_reason="high_risk_group"` / `key_source="not_used"`
  - `user_message` = 「…请先咨询执业医师或药师。」
- **测试**：`tests/test_safety.py`

### S4 闸门② —— 体质就绪

- **输入**：`constitution`（请求没给就默认平和质）
- **真源**：`safety.py :: ready_constitutions()` ← 从 `core/data/herbs.json` 的 `suitable_constitutions` **派生**（不是手工开关）
- **不就绪 → 输出**：`AnalyzeError("CONSTITUTION_NOT_READY")` → **422**（不是 500、也不是回落到平和质）
- **出口**：就绪才继续；`/api/constitutions` 也用同一判据，所以下拉框里不会出现不可用体质
- **测试**：`tests/test_constitution_readiness.py`（17 项，含端点测试）

### S5 闸门③ —— 凭据

- **真源**：`orchestrator.py` + `core/app/config.py`
- **无 Key →** `NO_API_KEY`（提示文案来自 `settings.missing_credentials_hint()`）→ **400**
  > ⚠️ 这条文案仍写「在页面上的「API Key」一栏填入」，2026-09-18 Key 已收进弹窗，方位描述滞后（待改，需动 Python）
- **`user_key_supported=False`（`TA_BACKEND=dsh`）→** `USER_KEY_UNSUPPORTED` → **400**
- **测试**：`tests/test_key_handling.py`

### S6 Agent1 —— 解析饮食

```
request.text
   │
   ├─① render_reference(text) ── match_foods() ──→ 命中的食性表条目 ──→ 注入 user 提示词「参考表」
   │     真源：services/food_lookup.py；数据 core/data/food_properties.json（147 条）
   │
   ├─② runtime.run(prompt, system_prompt, api_key)
   │     真源：agents/runtime.py → direct_api.py（默认）/ harness（dsh）
   │     提示词：core/app/agents/prompts/agent1_system.md
   │     输出：模型原文字符串
   │
   ├─③ json_guard.validate_with_retry(ParsedMeal, ..., max_retry=1)
   │     strip_fence → extract_json_object → parse_lenient → schema 校验
   │     失败 → 用 repair_prompt 重试 1 次 → 仍失败抛 JsonGuardError
   │     真源：core/app/agents/json_guard.py
   │
   └─④ calibrate_parsed() ── 逐项 resolve_food()（三层判定，见 §3）
         写回 verification{source, confidence, unverified, detail}
         confidence = 逐项置信度的**算术平均**（不用模型自报值）
```

- **输出**：`ParsedMeal`
  - `foods[]`：`ParsedFood{name, amount_desc, nature, flavors[], cooking, note, verification}`
  - `meal_time`、`overall_nature`（**由模型给，校准层不重算**）、`confidence`、`uncertain_items[]`、`summary`
- **失败时**：`CredentialError` → `API_KEY_REJECTED` **400**；其余（含 JSON 解析失败）→ `AGENT1_FAILED` **422**
- **真源**：`core/app/agents/agent1_diet.py :: parse_diet / calibrate_parsed`
- **出口**：`ParsedMeal` → ① 前端「我理解到的」卡片 ② Agent2 的 user 提示词
- **测试**：`test_calibration.py`(20)、`test_food_lookup.py`(24)、`test_temperature_layer.py`(26)、`test_nature_math.py`(35)、`test_json_guard.py`(14)

### S6.5 一个食物都没认出来

- **输出**：`recommendations=[]` + `user_message="没太看明白你吃了什么…"`，`degraded=False`（这不是降级，是正常结果）

### S7 候选集收敛（在 Agent2 内部，结构性限制）

- **输入**：体质 id
- **处理**：`filter_by_constitution(cid, limit=12)` —— `unsuitable_for` 命中即剔除 → `suitable_constitutions` 命中排前 → 其余中立补后 → 取前 12
- **输出**：渲染进提示词的候选清单（`_candidate_lines`，须煎煮的带「⚠️ 须煎煮」）+ `_build_unverified_section`（未验证食物**不得作为计算依据**）
- **失败时**：`suitable` 一条都没有 → `MissingConstitutionDataError`（**显式失败，不退化成未筛选清单**）
- **真源**：`safety.py :: filter_by_constitution` ← `core/data/herbs.json`；体质文案 ← `core/data/constitution.json`
- **测试**：`test_agent2_prompt.py`(6)、`test_constitution_reference.py`(28)

> 这道不算"闸门"，但它是**结构性的**：模型能选的饮片只有这 12 味，越界也写不出来。

### S8 Agent2 —— 生成推荐

- **输入**：`ParsedMeal` 的 JSON + 体质 brief + 候选清单 + `exclude_herbs`
- **输出**：`Agent2Output{recommendations: list[Recommendation], user_message}`
  - `Recommendation{title, herbs[{name, amount_g, nature, flavors, meridians, role}], brew, fit_reason, cautions, score}`
- **失败时**（抛异常或返回空）→ **降级**：`matcher.fallback_recommend(parsed, constitution, exclude_herbs)`，
  置 `degraded=True` / `degraded_reason=str(exc)[:200]` / `rule_hits`
- **真源**：`core/app/agents/agent2_recommend.py`；提示词 `core/app/agents/prompts/agent2_system.md`
- **测试**：`test_agent2_prompt.py`（提示词不变式，含九型方向与须煎煮标记）

### S9 闸门④ —— 输出护栏

逐条推荐依次过四道检查（`orchestrator.py :: _sanitize_recommendations`）：

| 检查 | 拦什么 | 放什么 / 怎么处理 | 真源 |
|---|---|---|---|
| `check_blend` | 超出 4 味、白名单外饮片、用户已排除、单味超 `min(max_daily_g, 30g)`、总量 > 45g | blocked 的**剔除**（剔空则整条作废）；超剂量**自动裁剪**并留痕；条目 `cautions` 转成 warning | `safety.py :: check_blend` ← `herbs.json` |
| `scan_free_text` | `FORBIDDEN_PHRASES`（治疗/治愈/根治/主治/疗效/疗程/处方/停药/确诊/癌症…）出现在 `title`/`fit_reason`/`cautions` | **整条作废**，不留商量余地 | `safety.py :: scan_free_text` |
| `check_constitution_fit` | 饮片 `unsuitable_for` 命中当前体质 | 只给 warning，**追加进 `rec.cautions`**，不作废 | `safety.py :: check_constitution_fit` |
| `check_brew_adequacy` | 含须煎煮饮片却配了保温杯焖泡 | **自动换成 `matcher.COOK_BREW`**（养生壶/小锅煮 20–30 分钟）并留痕 | `safety.py :: check_brew_adequacy` + `matcher.COOK_BREW` |

- **输出**：`(cleaned: list[Recommendation], applied: list[str])` → `applied` 进 `basis.guardrail_applied`（**用户可见**）
- **全被拦时**：若此前没降级过 → 再用 `fallback_recommend` 兜底一次 + 再过一遍护栏，
  置 `degraded=True` / `degraded_reason="guardrail_removed_all"`
- **不变量**：被拦的内容**绝不原样返回给用户**
- **测试**：`tests/test_safety.py`（34 项，全项目最不能松的一层）

### S10 组装响应

- `_build_basis()`（`Basis` 的**唯一构造点**）：
  - `references = herb_evidence(本次实际留下的饮片名, constitution)`
    —— 只给**命中本次原料**的公开依据，被护栏剔除的饮片不出现
  - 真源：`core/data/herb_evidence_sources.json`（域 I 属性 34 条 + 域 II 体质 24 条）
- **输出** `AnalyzeResponse`：

| 字段 | 内容 |
|---|---|
| `request_id` | 16 位十六进制，按它定位日志 |
| `parsed` | S6 的 `ParsedMeal` |
| `recommendations[]` | S9 清洗后的推荐（1–3 条） |
| `basis` | `constitution` / `constitution_label` / `rule_hits[]` / `guardrail_applied[]` / `references[]` |
| `disclaimer` | 固定免责声明（`is_medical_advice=False`） |
| `meta` | `agent1_ms` / `agent2_ms` / `total_ms` / `model` / `degraded` / `degraded_reason` / `key_source` / `backend` |
| `user_message` | 需要补充说明的话（降级说明、没看懂、高风险引导） |

- **测试**：`tests/test_herb_evidence.py`（31 项，依据链的派生不变式 + 负控制）

---

## 3. 三层判定（`resolve_food` 内部）

这是「判断权在表和规则手里」的落地点。真源：`core/app/services/food_lookup.py :: resolve_food`。

```
        输入：模型给的食物名 name + cooking(处理方式的模型判断) + note + llm_nature
                              │
   ┌──────────────────────────▼───────────────────────────┐
   │ 温度前缀层（纯规则，最先做）                          │
   │ nature_math.resolve_temperature 同时扫 name 与 note   │
   │ 前缀：冰镇/冰/加冰/去冰/冷冻/冷藏/冻 → -1            │
   │       热/烫/滚烫/加热/温热            → +1           │
   │ 准入：剥掉前缀后须是完整表内食物名（「冰淇淋」不通过）│
   └──────────────────────────┬───────────────────────────┘
                              ▼
   ┌──────────────────────────────────────────────────────┐
   │ ① 查表层  _find_entry（三级，顺序不可颠倒）           │
   │   0 级 规范名完全相同 → 1 级 包含关系(gap 最小)       │
   │   → 2 级 keywords ∪ aliases                          │
   └──────────────────────────┬───────────────────────────┘
              ┌───────────────┴───────────────┐
        命中表                            未命中表
              ▼                                ▼
   ┌────────────────────┐        ┌──────────────────────────────┐
   │ ② 食材变体层        │        │ 保留模型的判断：              │
   │ variant_nature[cook]│        │ llm_nature 有值 → source=llm  │
   │ 有就直接用          │        │   confidence 0.3 unverified   │
   ├────────────────────┤        │ 否则 → source=unresolved      │
   │ ③ 烹饪修正层        │        │   confidence 0.1              │
   │ apply_cooking_      │        └──────────────────────────────┘
   │ fallback（±1 通用   │
   │ 规则）              │
   │ ⚠️ exact_name_hit  │
   │ （名字==规范名）时  │
   │ 不叠加，表里就是权威│
   └────────┬───────────┘
            ▼
   ④ 温度前缀在以上结果上再叠加 ±1（shift_nature 自动夹取）
            ▼
   置信度与「待验证」由 review_status 决定：
     approved → 0.9，unverified=False
     pending  → 0.9（走了修正层则 0.6），unverified=True  ← 当前 147 条全是这个
     rejected → 0.6，unverified=True
```

- **输出**：`ResolvedFood{name, nature, flavors, entry, verification}`
- **出口**：写回 `ParsedFood.verification` → 前端标签悬停显示（来源 + 置信度 + 判定过程）
- **显示阈值**：`CONF_SHOW_THRESHOLD = 0.3`，低于它前端**不显示寒热属性**（数据仍在，只是不呈现）
- **测试**：`test_food_lookup.py`、`test_temperature_layer.py`、`test_nature_math.py`、`test_calibration.py`

---

## 4. 四道闸门一览

| # | 闸门 | 在哪一步 | 拦什么 | 放什么 | 真源 | 测试 |
|---|---|---|---|---|---|---|
| ① | 高风险人群 | 最前（先于凭据） | 25 个人群/情境关键词 | 只给引导就医，不给推荐、不调模型、免费 | `safety.py :: detect_high_risk` | `test_safety.py` |
| ② | 体质就绪 | 安全之后、凭据之前 | `herbs.json` 没标 `suitable_constitutions` 的体质 | 9 型（当前全部就绪）；未就绪 → 422 | `safety.py :: ready_constitutions` | `test_constitution_readiness.py` |
| ③ | 凭据 | 体质之后、Agent1 之前 | 没带 Key；`TA_BACKEND=dsh` | 带了 Key 且 direct → 放行 | `orchestrator.py` + `config.py` | `test_key_handling.py` |
| ④ | 输出护栏 | Agent2 之后、返回之前 | 白名单外 / 超味数 / 超剂量 / 禁用表述 / 体质不合 / 焖泡煎煮错配 | 清洗后的推荐；全拦则走规则兜底 | `orchestrator.py :: _sanitize_recommendations` + `safety.py` | `test_safety.py` |

**外加一道结构性限制**：`filter_by_constitution`（S7）—— 模型只能从 12 味候选里挑，
这是把「越界开方」锁死的地方，与 ④ 是两条独立的防线（handover §2.4 称「两条都做」）。

---

## 5. 降级路径

```
                    哪里出问题？
                          │
   ┌──────────┬───────────┼────────────┬──────────────┐
   ▼          ▼           ▼            ▼              ▼
 没 Key    模型失败    JSON 解析失败  高风险分支     离线模式
   │          │           │            │              │
   ▼          ▼           ▼            ▼              ▼
 400        见下       见下        直接返回       见 §5.6
NO_API_KEY
```

### 5.1 没 Key

- **走什么**：闸门③ 直接报错 **400 `NO_API_KEY`**，**不降级、不调模型**
- **例外**：若文本先命中闸门①，则**根本走不到凭据校验**，直接返回高风险引导（免费）
- **网页出口**：`isKeyIssue` → 自动打开 `<dialog id="cfg">` 并把焦点放进 Key 输入框
- **测试**：`test_key_handling.py`

### 5.2 模型失败（超时 / 网络 / 被拒）

- **Agent1 侧**：`CredentialError` → 400 `API_KEY_REJECTED`；其它异常 → 422 `AGENT1_FAILED`
  —— **Agent1 失败不降级**，直接报错
- **Agent2 侧**：任何异常 → **降级** `matcher.fallback_recommend`，`degraded=True`
  （理由：Agent1 是解析，错了就是"没听懂"；Agent2 是推荐，错了还能用规则给个安全的）

### 5.3 JSON 解析失败

- **走什么**：`json_guard` 剥围栏 → 提取 → 宽松解析 → schema 校验 → **失败重试 1 次**（`repair_prompt`）
- **仍失败**：`JsonGuardError` → Agent1/Agent2 抛出 → **Agent1 侧是 422 硬失败，Agent2 侧才降级**
- **真源**：`core/app/agents/json_guard.py`
- **测试**：`test_json_guard.py`（14 项）

> ⚠️ **文档与代码不一致（发现，未改）**：`handover.md` §2.5 写「JSON 解析失败…不能变成 500，
> 链路末尾一定有 `matcher.fallback_recommend` 兜底」。实测代码里 **Agent1 的 JSON 解析失败是 422 硬失败**，
> 只有 Agent2 失败才走兜底。建议二选一：改文档措辞，或让 Agent1 也能降级（后者要出方案）。

### 5.4 高风险分支

- **走什么**：闸门① 直接返回，见 S3。`degraded=True` 但**不是故障**（`degraded_reason="high_risk_group"`）
- **出口**：网页「说明」卡片 + 免责声明；`meta.key_source="not_used"` ⇒ 前端显示「本次未调用模型」

### 5.5 护栏全拦 / Agent2 返回空

- **走什么**：`fallback_recommend` 兜底 → 再过一遍护栏 → `degraded_reason="guardrail_removed_all"`
- **若兜底也被排除干净**：`fallback_recommend` 返回 `user_message="你排除的饮片正好是这组搭配的全部…"`，
  `recommendations=[]`（**仍不是 500**）

### 5.6 离线模式

- **网页**：**没有**离线路径（必须填 Key）。`/api/analyze-offline` **尚未立项**，方案见 `docs/analyze-offline-plan.md`
- **终端 `--offline`**（`chat.py :: cmd_offline`）：

```
text → match_foods(关键词命中，长词优先)
     → resolve_food(三层判定，无 llm_nature → 未命中即 unresolved)
     → ParsedMeal(meal_time=UNKNOWN, overall_nature=UNKNOWN, summary="（离线模式…）")
     → matcher.fallback_recommend（规则选方）
     → terminal render_*
```

  - **不调模型、不需要 Key、零成本**
  - ⚠️ **不过闸门④**（`_sanitize_recommendations` 没被调用）：兜底配方本身就是从 `herbs.json`
    取的白名单条目 + 固定克数，安全由数据保证；但这与联网路径**不是同一条护栏**，是已知差异
  - ⚠️ `overall_nature` 恒为 `UNKNOWN` ⇒ `RULES.late_night`（只匹配 UNKNOWN）才可能命中
  - **测试覆盖**：CLI 行为层已由 `core/tests/test_terminal_shell.py` 覆盖（4 项：`--resolve` 食性 / `--offline` 返回码 / `--offline` 出推荐 / 空推荐负控制）；`cmd_full`（需 Key）与 `repl()` 交互循环仍无测试，另有 `core/scripts/smoke_offline.py` 冒烟
- **测试**：CLI 行为层已覆盖（见上）；`cmd_full` 与交互循环仍无测试（这是「离线链路住在壳层里」这个待办的根因）

---

## 6. 出口一览（结果去哪了）

| 出口 | 渲染什么 | 真源 |
|---|---|---|
| 网页「我理解到的」 | `parsed.foods[]` 标签（悬停显示 `verification.detail`）、时段、整餐偏、把握度、待验证计数 | `index.html :: renderParsed` |
| 网页「给你的建议」 | `recommendations[]`：饮片+克数、冲泡步骤、`cautions`、匹配度 | `index.html :: renderRecs` |
| 网页「这次推荐的公开依据」 | `basis.references[]`（只含命中本次原料的来源） | `index.html :: renderReferences` |
| 网页 底部 meta | 耗时 + `degraded` + 体质 + `request_id` + `renderKeySource`（用了谁的 Key） | `index.html :: run` |
| 终端 | `render_parsed` / `render_recommendations` + 规则命中 + 免责声明 | `chat.py` |
| 日志 | `logger.info("analyze 完成 request_id=… degraded=…")`，**不含 Key** | `orchestrator.py` |

---

## 7. 测试覆盖地图

| 环节 | 测试文件 | 项数 |
|---|---|---|
| HTTP / 凭据 / 日志安全 | `test_key_handling.py` | 50 |
| 护栏（白名单/剂量/禁用表述/体质/煎煮） | `test_safety.py` | 54 |
| 体质就绪闸门 | `test_constitution_readiness.py` | 18 |
| 三层判定接线与隔离 | `test_calibration.py` | 20 |
| 查表与匹配 | `test_food_lookup.py` | 24 |
| 温度前缀层 | `test_temperature_layer.py` | 48 |
| 四性运算 | `test_nature_math.py` | 48 |
| JSON 容错 | `test_json_guard.py` | 14 |
| Agent2 提示词不变式 | `test_agent2_prompt.py` | 8 |
| 依据链 | `test_herb_evidence.py` | 31 |
| 网页壳静态守卫 | `test_web_shell.py` | 19 |
| `late_night` 兜底的判据与文案 | `test_late_night_wording.py`（6 项） |
| **零覆盖** | 终端壳的 `cmd_full`（需 Key）与 `repl()` 交互循环 | **0** |

---

## 8. 已知的坑（看图时容易误判）

1. **「没填 Key 就该报 400」不成立** —— 高风险分支在凭据校验之前，没 Key 也返回 200。
2. **`degraded=True` 不等于故障** —— 高风险分支与「没识别出食物」都可能是正常结果，
   判故障要看 `degraded_reason`（`high_risk_group` 是正常的，`guardrail_removed_all` 才是异常）。
3. **`cautions` 的约束力很弱** —— 主路径上它只是文案，真正的硬约束在 `check_blend` 的
   `blocked`（剔除/作废）与 `guardrail_applied`（留痕）。
4. **`overall_nature` 不做重算** —— 由 Agent1 给，校准层只重算 `confidence`；
   离线路径恒为 `UNKNOWN`。
5. **离线路径与联网路径不同护栏** —— 见 §5.6。
