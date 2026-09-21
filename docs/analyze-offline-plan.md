# `/api/analyze-offline` 立项方案

> **状态：待所有者拍板，尚未动代码。** 本文只给方案，不含实现。
> 背景：`docs/frontend-fork-assessment.md` §6/§7 把「`/api/analyze-offline` 立不立项」列为
> 吸收 ⑤（饮食清单推荐）⑥（7 天记录）的前提。本文回答「它是什么、怎么做、代价多大」。
> 快照：对照基线 `1eb3d0b`，测试 **442 passed**。

---

## 0. 先给四条结论

1. **离线链路已经存在，只是住错了地方。** `ui/terminal/chat.py:203-232` 的 `_offline_analyze()`
   就是完整的离线链路（`match_foods` → `resolve_food` → `matcher.fallback_recommend`）。
   本项**不是新建一条链路**，而是把它从**壳层**提到 `core/`，再加一层极薄的 HTTP 适配。
   理由不是审美：`ui/` 单向依赖 `core/`（决策 #5），端点住在 `core/`，它**无法** import `ui/`；
   若照抄同学的实现，就会在 `core/` 里**再写一份**，从此两份实现各自漂移。

2. **它是「免 Key 可用」的缺口补丁，不是 ⑤⑥ 的完整地基。** 它天生是**单餐语义**
   （一段口述 → 一次推荐）。而 ⑤⑥ 要的是**多餐聚合**（7 天 N 顿 → 一次推荐）。
   这两件事不能混：同学版本正是混了才出问题（把 7 天拼成一段、截断 1200 字、交给单餐端点，
   见评估报告 §4.2）。**本方案只做单餐；多餐另立项（见 §7 拍板点 4）。**

3. **难点不是"再写个端点"，而是"不许绕过闸门"。** 主路径 `/api/analyze` 的护栏链条是
   高风险分支 → 体质就绪闸门 → Agent → `_sanitize_recommendations` → `_build_basis`。
   同学的 `/api/analyze-offline` **四道全绕**（不调 `detect_high_risk`、不查就绪、
   不过护栏、还调了本项目**已删除**的 `matcher.build_basis`）。照抄等于给项目开
   第二个"绕过护栏的入口"——与 `/api/chat` 的问题同族。

4. **建议：做。** 收益明确且是结构性的（Web 壳从"必须先填 Key"变成"不填也能用"），
   成本小（核心 ≈ 半天，新增约 15–20 项测试），且**不动任何现有判定逻辑**。
   但必须按 §5 的形态做，不能按同学那份改。

---

## 1. 它是什么、解决什么问题

| | 主路径 `/api/analyze` | `/api/analyze-offline` |
|---|---|---|
| 需要 API Key | **必须**（没有服务端兜底 Key，缺失直接 400 `NO_API_KEY`） | **不需要** |
| 是否调用模型 | 是（Agent1 + Agent2，串行） | **否**，一次都不调 |
| 典型耗时 | 12–18 秒（`low`）；3–6 秒（`off`） | 毫秒级 |
| 成本 | 约 1.02–2.03 分/次 | 0 |
| 识别粒度 | 模型能听懂没写进表里的说法 | **仅限 `food_properties.json` 的关键词表**，表外词认不出 |
| 属性来源 | 三层判定（查表优先，表外标 0.3 推测） | **只有查表命中那一种**（表外即认不出） |
| 文案 | 模型写的 `fit_reason`、`role` | 规则里的固定句式 |
| 推荐来源 | Agent2 自由选料（受候选集约束）+ 护栏 | `matcher.fallback_recommend()`，即主路径的兜底函数 |

**它解决的问题**：当前 Web 壳**没有 Key 就完全不可用**。对一个"饮食参考"性质的本地工具，
这是最刺眼的门槛——用户想试一下，得先去申请一个 API Key。离线端点把这一步去掉。

**它不解决的问题（必须写清，否则会被误用）**：
- 它**不会**让识别率变好。表里没有的说法照样认不出，而且**没有一个字段**像主路径那样
  告诉用户"我没认出 XX"（主路径有 `parsed.uncertain_items`，那是模型给的；离线路径拿不到）。
- 它的推荐是**同一条兜底结果**，即"安全、合法、不超剂量，但措辞简略"（§2.5 的降级契约）。
  界面**必须**把它呈现为"简化匹配"，不能让用户以为这是完整体验。

---

## 2. 接口设计

### 2.1 端点

```
POST /api/analyze-offline
```

- **不带 `Authorization` 头**：这个端点压根不接受 Key。前端不必（也不该）在这里传凭据。
- 单独成端点，**不用 `/api/analyze?mode=offline`**：后者会让"没 Key 时自动走离线"变成
  `/api/analyze` 的隐式行为，而"不带 Key → 400 `NO_API_KEY`"**是有测试守着的既有契约**
  （`core/tests/test_key_handling.py:433-450`）。改它属于推翻决定 #7 的边界，不顺手做。

### 2.2 请求

复用 `AnalyzeRequest` 的**字段名**，但单独定义 `OfflineAnalyzeRequest`：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `text` | str，1–500 | ✅ | 一段口述。**上限 500 与主路径一致，且刻意不放宽**（见下） |
| `meal_time` | `MealTime \| None` | ❌ | 用户显式给的时段。**不做任何推测** |
| `constitution_override` | `Constitution \| None` | ❌ | 缺省平和质（与主路径同） |
| `exclude_herbs` | `list[str]` | ❌ | 与主路径同，**必须透传**到 `fallback_recommend` |

**为什么 `text` 上限必须是 500、且不接受数组**：
同学的前端把 7 天记录「取最近 12 条 → 拼接 → 截断 1200 字」后 POST 进来。
**只要这个端点的 `text` 没有上限，前端就一定会这么用**——这是被验证过的行为，不是猜测。
用 500 上限 + Pydantic 的 422 把这个用法挡在门口，属于「结构上锁死」（§2.4 的思路），
比在文档里叮嘱可靠。

### 2.3 响应

**复用 `AnalyzeResponse`**（前端一套渲染逻辑，不新增响应形状）。但四处字段的取值要定死：

| 字段 | 离线路径取值 | 为什么 |
|---|---|---|
| `meta.degraded` | **`False`** | ⚠️ **与同学版本相反**。他把离线标成 `degraded=True`。但 `degraded` 在本项目的语义是**「走了兜底」= 异常信号**（§2.5）；离线是用户**主动选的正常模式**，没有任何东西"降级"了。标成 `True` 会让监控和前端把正常路径误报成故障 |
| `meta.mode` | **`"offline"`**（新增字段，默认 `"llm"`） | 让前端能区分"本次没调模型"。**不改 `degraded` 的语义**来兼职表达这件事 |
| `meta.backend` | **保持 `settings.backend`（`direct`/`dsh`）** | ⚠️ **与同学版本相反**。他写 `backend="offline"`，但该字段的取值域是 `direct`/`dsh`，塞第三个值会让 `/healthz` 与前端分支逻辑分叉。用 `mode` 表达离线，`backend` 如实表示"若调模型会走哪个后端" |
| `meta.key_source` | **`"not_used"`** | 既有枚举够用，无需改。如实告知"本次没用 Key"（高风险分支也是这个值，语义一致） |
| `meta.model` | `None`（或 `"offline-rules"`） | 见拍板点 2；建议 `None`——本次没有模型，"用的哪个模型"这个问题不成立 |
| `parsed.summary` | `"（离线模式：关键词匹配 + 查表装配，未使用模型）"` | 沿用终端现有措辞，界面照常回显 |
| `parsed.verification` | `source="rule"`、`unverified=True` | 与主路径查表命中时完全一致，界面照常标「待验证」（147 条全 `pending`，这是刻意的） |
| `basis.references` | **必须装配**（`herb_evidence`） | E3 的端到端不变式在这里同样适用：**推荐里出现的每一味，都要能在依据里找到对应** |
| `disclaimer` | 与主路径同一份 | 禁止各自硬编码文案 |

**新增字段只有 `Meta.mode` 一个**（`Literal["llm","offline"]`，默认 `"llm"`）。
它是**对外契约变化**，需要显式确认（拍板点 2）。

---

## 3. 和现有 `/api/analyze` 的关系

**共用同一套下游，只换中间那两步。**

```
                    /api/analyze                 /api/analyze-offline
                    ─────────────                ────────────────────
  高风险分支        detect_high_risk  ✅共用      同左
  体质就绪闸门      _ensure_constitution_ready ✅  同左
  ──────────────────────────────────────────────────────────────────
  解析              Agent1（模型）                match_foods + resolve_food（查表）
  推荐              Agent2（模型）                matcher.fallback_recommend（规则）
  ──────────────────────────────────────────────────────────────────
  护栏              _sanitize_recommendations ✅ 同左
  依据              _build_basis ✅               同左
```

**四道闸门一道都不能省**，理由逐条：

| 闸门 | 离线路径为什么也要有 |
|---|---|
| `detect_high_risk` | 这是**无条件可用**的分支（决策与 §2.5：不调模型、零成本）。离线路径成本更低，更没理由不做。一个没填 Key 的孕妇输入"我怀孕了"，必须看到"请先咨询执业医师"，而不是拿到一份茶饮搭配 |
| `_ensure_constitution_ready` | 挡住"数据未备齐"的体质。放到前端 localStorage 上（同学的做法）会让"是否可对外服务"这个判据离开后端，将来任何一型被清空就是 500 |
| `_sanitize_recommendations` | 白名单 / 剂量上限 / 禁用表述 / 体质契合 / 冲泡方式。兜底函数**已经**在产出合法搭配，但护栏是**契约的一部分**（"输出必经确定性护栏"），不能因为"我们相信兜底函数"就跳过——跳过等于把不变式变成约定 |
| `_build_basis` | `Basis` 的**唯一构造点**（AST 守卫盯着）。另起一处构造 = 复活 `matcher.build_basis` 那种"改了等于没改"的坑 |

**终点契约相同**：`analyze-offline` 也满足 §2.5「永远给得出东西」——
连食性表里一个词都没认出时，返回 `recommendations=[]` + `user_message`（说明"离线模式只能识别表内条目"），
**不是 500**。

---

## 4. 和 `matcher.py` 兜底路径的关系

这是本方案最容易做错的一处。

### 4.1 现状：`fallback_recommend` 一个函数、两个身份

```python
# 主路径（orchestrator.py:293-299）：Agent2 挂了才走
except Exception as exc:
    degraded = True
    recs, user_message, rule_hits = matcher.fallback_recommend(parsed, constitution, exclude)

# 离线路径（ui/terminal/chat.py:231）：它就是这个模式的本体
recs, msg, rule_hits = matcher.fallback_recommend(parsed, constitution)
```

同一个函数，**进入方式不同、`degraded` 的语义正好相反**（主路径 `True`、离线应为 `False`）。

**结论：不要把"离线"这个概念塞进 `matcher.py`。** 它一塞进去，主路径就会开始出现
只对离线成立的字段/分支。`matcher.py` 保持"纯规则匹配"，**离线的差异全部在调用方体现**。

`matcher.py` 本次**不需要改任何一行**（这是本方案风险低的主要来源）。

### 4.2 离线路径的 `ParsedMeal` 由谁装配

`fallback_recommend` 的输入是 `ParsedMeal`，它的两个关键字段在离线路径下**没有模型来给**：

| 字段 | 同学的做法 | 本方案建议 |
|---|---|---|
| `meal_time` | `_guess_meal_time()` **按系统时钟猜** | **不猜。** 请求里给了就用，否则 `UNKNOWN`。按时钟猜意味着"你什么时候打开页面"会影响结果——多餐场景下更是灾难（7 天记录会全变成同一个时段） |
| `overall_nature` | `_match_nature_from_text()` **第三份关键词表** | **不新造词表。** 见下方拍板点 1 |

**⚠️ `overall_nature` 的口径必须显式选，不能顺手定**（两案都会改变现有行为）：

| | (甲) 留 `UNKNOWN` | (乙) 用 `nature_math.combine` 按逐味四气推算 |
|---|---|---|
| 依据 | 与终端 `--offline` **现状完全一致** | 项目的四性数值轴（决策 #14），可解释、可审计 |
| `_pick_rule` 影响 | `overall_nature` 恒为 `UNKNOWN` ⇒ 少一个 +1 打分信号 | 多一个正确方向的 +1 信号 |
| `RULES.late_night` | **仍可能命中**（它是 `match_natures={UNKNOWN}`） | **基本变成死规则**（`foods` 非空 ⇒ `overall_nature` 不会是 `UNKNOWN`） |
| 现有输出 | 不变 | **终端 `--offline` 的输出会变**（默认搭配可能从 late_night 换到别的规则） |

关于 `late_night` 的真相：它现在能命中，靠的是"`overall_nature` 恰好未知"这个**巧合**，
而不是设计（它 `keywords` 为空、`match_natures={UNKNOWN}`、`priority=1`，只有别的规则都不中时才轮到它）。
选 (乙) 会把这个巧合暴露出来——这是**好事**（暴露出"夜宵"其实没有实现），
但**必须显式处置**：要么保留这条规则，要么承认它失效并单列一条挂起项。

**建议：(乙) + 手动比对一次输出 + 把 `late_night` 的处置写进文档。** 倾向理由：
(甲) 是"为了不改动一个本来就没设计好的规则而放弃更诚实的判定"，方向反了。

### 4.3 识别食物：只有一份词表

离线识别统一走 `food_lookup.match_foods()`，它的匹配词来自 `food_properties.json` 的
`keywords`/`aliases`——**事实源**。
**不新造第二份关键词表**：同学的 `_match_nature_from_text` 就是第二份（寒/热/温三组词），
它与 `matcher.RULES` 的 `keywords` 高度重复，改一处不改另一处就会静默漂移。
`RULES` 里的 `keywords` 保留原样（那是**规则命中**用的，与**食物识别**是两件事）。

> ⚠️ **2026-09-21 注记（历史记录未改写）**：这条**结论不变**，但**位置变了** ——
> `RULES` 整表（含 `keywords`）已迁进 `core/data/diet_signals.json` 的 `scene_rules` 段
> （**D24**），`matcher.RULES` 改为从数据派生。⇒ 上面「它与 `RULES` 的 `keywords` 高度重复」
> 仍成立，只是要找词表现在该去 `diet_signals.json`。另：`_match_nature_from_text` 与
> `RULES.keywords` 这两份词表的**静默漂移风险仍在**（本次未消除）。

---

## 5. 改动清单与工作量

| # | 文件 | 动作 | 规模 |
|---|---|---|---|
| 1 | `core/app/services/offline.py` | **新增**：`analyze_offline(request) -> AnalyzeResponse`；内含 `_build_parsed_meal()` | ≈ 100–130 行 |
| 2 | `core/app/api/analyze_offline.py` | **新增**：薄适配（形状照 `api/analyze.py`，但**无 `Authorization` 头**） | ≈ 45–60 行 |
| 3 | `core/app/main.py` | `include_router(analyze_offline_api.router, prefix="/api", ...)` | +2 行 |
| 4 | `core/app/domain/models.py` | `Meta` 加 `mode` 字段；加 `OfflineAnalyzeRequest` | +12 行 |
| 5 | `ui/terminal/chat.py` | `_offline_analyze()` 改为调用 `core` 版（**删掉重复实现**） | −30 / +8 行 |
| 6 | `core/tests/test_offline_analyze.py` | **新增**测试 | ≈ 300–380 行 |
| 7 | `docs/handover.md` §5.5 | 补一条验证命令（离线端点怎么手工试） | +5 行 |

**估算：核心 + 测试 ≈ 半天。** 不含前端（模式切换 UI 属 🟢/🟡 吸收项，**建议单独一次提交**，
理由见评估报告 §6"执行顺序"：骨架改动不与逻辑改动混在一起）。

**分层检查（§2.6 的硬验收）**：本次改动全在 `core/` 内 + 一处壳层调用。
删掉 `ui/` 后 `core/` 仍须过 `pytest` + `smoke_offline.py` —— 第 5 项（改终端壳）
必须放在 `core/` 可用之后，不能反过来。

### 明确不做（照抄同学版本会踩的五个坑）

| 坑 | 后果 |
|---|---|
| 调 `matcher.build_basis` | **本项目已删除该函数**（E3），照抄直接 `AttributeError`；且复活它会被源码守卫挡住 |
| `backend="offline"` | `backend` 的取值域是 `direct`/`dsh`，污染 `/healthz` 与前端分支 |
| `degraded=True` | 正常路径被上报成故障 |
| `meal_time` 按系统时钟猜 | 结果取决于"什么时候打开的页面" |
| `_match_nature_from_text` | 第三份关键词表，与 `RULES` 静默漂移 |

---

## 6. 测试影响

### 6.1 对现有 442 项的影响：**预期为零**

前提：不碰 `matcher.py` / `safety.py` / `food_lookup.py` 的既有行为（本方案确实不碰）。

⚠️ **但"不红"不等于"没变"**：选 (乙) 会改变终端 `--offline` 的输出，
而 **`late_night` 与 `ui/terminal/chat.py` 都没有任何测试覆盖**（实测 grep：`tests/` 里
既无 `late_night` 也无 `chat.py` 的引用）⇒ 行为变了**不会有任何断言报错**。
这正是项目最警惕的形状（"没报错"与"检查没跑"长得一样）。
**处置：人工跑一次 `chat.py --offline "夜宵吃了炸鸡配奶茶"`，改动前后各一次，人工比对。**

### 6.2 新增测试（建议清单）

**A. 不变式类（`core/tests/test_offline_analyze.py`）**

| # | 测什么 | 为什么是这一条 |
|---|---|---|
| 1 | **离线路径一次模型都不调**：把 `runtime.run` monkeypatch 成 `raise AssertionError`，全链路仍跑通 | 挡的正是"离线路径偷偷调模型"这类静默失败。这是本项**最该有的那条守卫** |
| 2 | **高风险分支优先于一切**：`"我怀孕了，今天吃了火锅"` ⇒ `recommendations == []` 且 `guardrail_applied` 含"命中高风险关键词" | 与主路径同一契约，且离线路径**零成本**，没有理由放宽 |
| 3 | **就绪闸门仍然生效**：`monkeypatch` 把 `ready_constitutions()` 改成不含某体质 ⇒ 该体质报 `CONSTITUTION_NOT_READY`（422） | **负控制**：另选一个就绪体质必须正常返回。只测"报错了"无法区分"闸门在跑"与"整体都坏了" |
| 4 | **护栏仍然生效**：用 `exclude_herbs` 把整组搭配排掉 ⇒ `recommendations == []`，`user_message` 是兜底那句 | 证明第 4.1 节的"共用下游"不是文档上的说法 |
| 5 | **Basis 端到端不变式**：推荐里每一味都出现在 `basis.references[*].supports` | 复用 E3 那条不变式，防止离线路径成为"推荐了某味但依据里没有它"的新入口 |
| 6 | **`meta` 三件套**：`degraded is False` ∧ `mode == "offline"` ∧ `key_source == "not_used"` ∧ `backend in {direct, dsh}` | 第 6 条的后半段（`backend != "offline"`）挡的正是同学那个坑 |
| 7 | **认不出任何食物时不抛异常**：`"今天天气不错"` ⇒ 200 + `recommendations == []` + 说明文案 | §2.5 的"降级而非失败"在离线路径同样成立 |

**B. HTTP 层（同一文件，照 `test_key_handling.py` 的 `TestClient` 写法）**

| # | 测什么 |
|---|---|
| 8 | **不带 `Authorization` 也 200** —— 与 `/api/analyze` 不带 Key 得 400 `NO_API_KEY` 形成**正反两条**。只测后者说明不了"免 Key"是真的 |
| 9 | `text` 超 500 → **422**（挡住"7 天记录整段塞进来"这个已被验证会发生的用法） |
| 10 | 响应体与日志里**不出现任何 Key 材料**（复用 `test_key_handling.py` 的 sentinel 思路） |

> 规模：约 **15–20 项**，全离线、不花钱。跑完期望 **442 + 15~20 passed**。

### 6.3 无自动化断言、必须人工过目的

- **推荐质量**：离线路径没有模型润色，`fit_reason` 是规则里的固定句式。
  参照 `handover.md` §5.3 的告诫——推荐质量**没有自动化断言**，改完要人工读一遍输出。
- **终端行为是否变化**：见 §6.1 的 ⚠️。

---

## 7. 待你拍板

| # | 问题 | 选项 | 建议 |
|---|---|---|---|
| 1 | `overall_nature` 口径 | (甲) 留 `UNKNOWN`（终端行为不变，但少一个打分信号、保留 `late_night` 的巧合）／(乙) 用 `nature_math.combine` 推算（更诚实，但**会改终端输出**且让 `RULES.late_night` 变死规则） | **(乙)**，并**人工比对一次**终端前后输出；`late_night` 的处置单列一条挂起项 |
| 2 | 是否加 `Meta.mode` 字段 | 加（对外契约变化，+1 个 `Literal`）／不加（用 `model="offline-rules"` + `key_source="not_used"` 间接表达） | **加**。间接表达那两个字段各有自己的语义，兼职表达会让前端分支靠"猜" |
| 3 | 端点形态 | 独立 `POST /api/analyze-offline`／`POST /api/analyze?mode=offline` | **独立端点**（后者会静默改掉"无 Key → 400"这条有测试守着的契约） |
| 4 | **多餐聚合（⑤⑥ 的真地基）是否现在立项** | 现在一起做／先只做单餐、多餐单独出方案 | **先只做单餐。** 多餐要定"跨 N 顿怎么合成一个整餐寒热""跨天怎么算"——这是**判定口径**，按项目纪律要先出方案给你确认，不能顺手塞进"加个端点"里 |
| 5 | 是否让离线端点接受 `meals` 数组 | 接受／不接受 | **不接受**（见 §2.2：一旦留口子，前端必然塞 7 天记录） |
| 6 | 前端模式切换 UI 的提交时机 | 与核心改动同一次／单独一次 | **单独一次**（评估报告 §6 的执行顺序建议） |

**另需注意（不在本项范围，但阻塞关系要清楚）**：

- **⑦（体质候选改读 `/api/constitutions`）与本项无关**，是独立的小改动，不必等本项。
- **`/api/chat` 不因本项而解禁**：它是另一个端点、另一套风险（四道护栏全缺）。
  若将来要接，**护栏是前置条件而非后续补**。
- 本项做完后，Web 壳的"没 Key 也能用"才真正成立。但**它仍不是"可对外服务"**——
  A1（147 条食性数据全部未人工审核）仍是唯一的硬阻碍，与端点数量无关。

---

## 8. 若确认，实施顺序

1. `core/app/services/offline.py` + `Meta.mode` + `OfflineAnalyzeRequest`（不含 HTTP）
2. `core/tests/test_offline_analyze.py` 的 A 组不变式（7 条）——**先让 core 层自己站住**
3. `core/app/api/analyze_offline.py` + `main.py` 挂路由 + B 组 HTTP 测试（3 条）
4. `ui/terminal/chat.py` 改为调用 core 版（去重）+ 人工比对 `--offline` 输出
5. 跑 `pytest -q` 与 `smoke_offline.py`；更新 `handover.md` §5.5
6. 前端模式切换 UI（**单独提交**）

**每步之间跑一次 `pytest -q`**，按项目约定确认没破坏既有功能。
