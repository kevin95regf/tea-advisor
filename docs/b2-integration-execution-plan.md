# B2 接入 · 执行方案

> 上一篇 `docs/b2-questionnaire-integration-plan.md` 已拍板 7 个决策点，**本文是落地步骤**。
> 快照 **2026-09-18**　状态：**全部决策已拍板，待开工**
>
> 决策摘要：D1 主导 + 其余进屏蔽集｜D2 选 B（倾向兜底 + 强制告知）｜D3 平和三档、判不出就拒绝｜
> D4 复用既有闸门｜D5 core 不 import 子包｜D6 选 A（离线路径必做）｜D7 不动 `Basis`
>
> 补充拍板：**D6-A′ 选 ① 离线路径对 `avoid` 硬剔除**（与 LLM 路径一致）；
> **D5′ 选 ① 本次不做网页版**（等 `/api/analyze-offline` 那轮一起定端点）；**阶段 2 终端接线本次做**。

---

## 0　核对时发现的两处 §5 没覆盖到的事

这两条会改变实现位置，必须先说。

### 0.1　`_constitution_default` 不是离线路径的唯一取搭配处

`matcher.fallback_recommend`（`matcher.py:271-279`）是**二选一**：

```python
rule = _pick_rule(parsed)
if rule:
    blend, title, reason = rule["blend"], ...      # ← 命中食物规则，完全不看体质
else:
    blend, title, reason, fallback_note = _constitution_default(constitution)
```

**命中食物规则时，搭配根本不经过体质。** 所以 §5 Step 7 写的
「在 `_constitution_default` 取到搭配后检查」会漏掉 rule 分支。

⇒ **正确位置**：`matcher.py:284` 那一行（已有 `exclude` 过滤的地方），在 blend 确定**之后**统一过滤。
那里天然同时覆盖两个分支：

```python
blend = [(name, amount) for name, amount in blend if name not in exclude]
```

### 0.2　LLM 路径与离线路径对 **primary** 的态度本来就不同（既有问题，不擅自改）

- LLM 路径 `filter_by_constitution`（`safety.py:374`）：`if constitution in unsuitable: continue` ⇒ **硬排除**
- 离线路径 `matcher.py:297`：命中 `unsuitable_for` 只 **追加一句 caution** ⇒ **软提示**

这条不一致**今天就在**，不是本次引入。本次**不碰它**（改它会牵动 `test_matcher` / `test_safety` 的既有期望），
但会在 `pending-items.md` 里**显式登记**，不假装没看见。

由此产生一个子决策，见 §5 的 **D6-A′**（已拍板 ① 硬剔除）。

---

## 1　范围：分三阶段，本次必做的是阶段 1

| 阶段 | 内容 | 本次？ |
|---|---|---|
| **1　链路能力** | 换算层 + 四处接入点同步 + 守卫测试 ⇒ 链路**能**处理兼体质与倾向 | ✅ **必做**（提交 1-5） |
| **2　终端接线** | `ui/terminal/chat.py` 跑问卷 → 换算 → 填 `AnalyzeRequest` | ✅ **本次做**（提交 6） |
| **3　网页版** | 让 557 行的 `ui/web/index.html` 也能用上问卷 | ❌ **本次不做**（D5′ ①，见 §5） |

---

## 2　阶段 1 改动清单（按提交切分，每步都跑 pytest）

### 提交 1 · 换算层（纯新增，不动既有任何文件）

**新文件** `core/app/domain/constitution_resolver.py`

```python
class Resolution(BaseModel):
    primary: Constitution
    avoid: list[Constitution] = Field(default_factory=list)
    status: Literal["confirmed", "tendency", "balanced", "balanced_basic"]
    note: str = ""          # 直接可拼进 AnalyzeResponse.user_message


def resolve_from_scores(scores: Mapping[str, Mapping[str, Any]]) -> Resolution:
    """把 score_questionnaire()["scores"] 换算成推荐链路的输入。

    纯函数：**不 import 子包**，入参就是那个 dict ⇒ core 测试零外部依赖。
    """
```

**判定顺序**（严格按 D1/D2/D3）：

| 序 | 条件 | primary | avoid | status |
|---|---|---|---|---|
| 1 | `confirmed` 非空 | confirmed 里转化分最高者（**并列按 `Constitution` 枚举顺序**，保证确定性） | **其余 confirmed**（按分降序） | `confirmed` |
| 2 | confirmed 空、tendency 非空 | tendency 里分最高者 | **空**（倾向不是判定，不进屏蔽集，避免过度屏蔽） | `tendency` |
| 3 | 都空、`balanced == "是"` | `balanced` | 空 | `balanced` |
| 4 | 都空、`balanced == "基本是"` | `balanced` | 空 | `balanced_basic` |
| 5 | 都空、`balanced == "否"` | **抛 `UndeterminedConstitutionError`** | — | — |

**入口校验（派生不变式，不是快照）**：
- `scores` 的每个键都必须是 `Constitution` 的合法值，否则抛 `UnknownConstitutionError`
  （这样 `phlegm_dampness` 之类一旦回流会**当场报错**，与 `test_questionnaire_id_alignment.py` 互为表里）
- 必须含 `balanced` 键；缺键抛 `UnknownConstitutionError`
- 每个键必须有 `status` 与 `transformed_score`

**`note` 文案**（进 `user_message`，D7 要求的强制告知）：
- `confirmed` 且 `len(confirmed) > 1`：「问卷判定你兼有 A、B 两种体质，本次按 A 收敛方向，
  同时对 B 标为不宜的饮片一并排除。」
- `tendency`：**「问卷未达判定阈值，按倾向处理」**（D2-B 的强制文案，一字不能少）+ 列出倾向体质
- `balanced_basic`：列出 `transformed_score >= 30` 的偏颇体质（正是「基本是」的代价）

**测试**（新文件 `core/tests/test_constitution_resolver.py`，纯函数入参 `dict`）：

| 守卫 | 不变式 | 负控制 |
|---|---|---|
| R1 | 输出 `primary` 与 `avoid` 全 ∈ `Constitution` 合法值 | 喂含 `phlegm_dampness` 的 scores，断言抛 `UnknownConstitutionError` |
| R2 | `primary ∉ avoid`（主导体质不得被自己屏蔽） | 造两者相同的返回值，断言被抓 |
| R3 | **每个**「是」都在 `primary ∪ avoid` 里（不丢） | 3 个「是」只收 2 个，断言被抓 |
| R4 | 「倾向是」**永不**在 `primary`（除非 confirmed 为空） | 「1 是 + 1 倾向」⇒ primary ≠ 倾向那个 |
| R5 | `tendency` 状态的 `note` **必含**「未达判定阈值」 | 造一个去掉该句的 Resolution，断言被抓 |
| R6 | 并列分数时 primary **确定**（同输入两次结果相同） | 交换 dict 插入顺序，断言结果不变 |
| R7 | 判不出（序 5）**抛错**而不是回落平和质 | 断言不会返回 `balanced` |

### 提交 2 · 判定层：`filter_by_constitution` 支持 `avoid`

`core/app/domain/safety.py:344`：

```python
def filter_by_constitution(
    constitution: str,
    limit: int = 12,
    *,
    avoid: Sequence[str] = (),      # ← 新增，仅关键字、默认空 ⇒ 既有调用零影响
) -> list[dict]:
```

过滤逻辑改为（**派生不变式**：命任一体质的 `unsuitable_for` 即排除）：

```python
blocked = {constitution, *avoid}
for entry in catalog.values():
    unsuitable = set(entry.get("unsuitable_for") or [])
    if unsuitable & blocked:        # 与既有语义等价（avoid 为空时行为逐字节不变）
        continue
    ...
```

⚠️ 用 `&` 而不是逐个 `in` —— 保证 `avoid=()` 时与现在**完全等价**（既有测试不用改）。

`core/app/agents/agent2_recommend.py`：`_candidate_lines` 与 `agent2_recommend` 增加 `avoid` 形参并透传
（`agent2_recommend.py:65` 是 `filter_by_constitution` 的**唯一**真实调用点）。

### 提交 3 · 编排层 + 离线路径（这两处必须同一提交，否则跨路径守卫过不了）

**`core/app/domain/models.py`**：`AnalyzeRequest` 增
```python
avoid_constitutions: list[Constitution] = Field(default_factory=list)
```
默认空 ⇒ 对既有调用方（前端、终端、测试）**零影响**。

**`core/app/services/orchestrator.py`**：
- `_ensure_constitution_ready` 改为对 `primary` **和** `avoid` 里每个 id 都过 `ready_constitutions()`。
  D4 要求复用既有闸门、不新造 ⇒ 保持 `CONSTITUTION_NOT_READY` 错误码不变，只把入参从单个扩成集合。
- `_sanitize_recommendations` 增 `avoid` 形参，透传给 `check_constitution_fit`（第 ④ 处接入点）。
- `analyze()` 里把 `request.avoid_constitutions` 传给 Agent2、matcher、`_sanitize_recommendations`（三处）。

**`core/app/services/matcher.py`**（D6-A + **D6-A′ ① 硬剔除**）：

签名必须一起改，因为终端 `ui/terminal/chat.py:231` 直接调 `fallback_recommend`：

```python
def fallback_recommend(parsed, constitution, *, avoid: Sequence[str] = ()) -> ...:
```

在 `matcher.py:284` 的 `exclude` 过滤**同一行**加 `avoid` 剔除
（理由见 §0.1：必须放在 blend 确定之后，才能同时覆盖 rule 分支与 `_constitution_default` 分支）：

```python
avoid_names = _herbs_unsuitable_for_any(avoid)        # 新增小助手：查 catalog 的 unsuitable_for
blend = [(n, a) for n, a in blend if n not in exclude and n not in avoid_names]
```

⚠️ **硬剔除（D6-A′ ①）**：命中的饮片直接从 blend 去掉 —— 与 LLM 路径 `filter_by_constitution` 一致。
`primary` 的 `unsuitable_for` 维持现状（软提示，追加 caution），那一条既有不一致按 §0.2 只登记不改。

剔除后 `blend` 为空 ⇒ **退通用兜底**（`GENERIC_FALLBACK_KEY`）并在 `reason` 里写明原因，
**不能**返回空推荐（离线路径的契约是「永远给出合法且安全的搭配」）。

### 提交 4 · 跨路径一致性守卫（本文的收口）

新函数（放 `core/tests/test_constitution_integration.py`，`monkeypatch` 造数据，**不拿真实数据当样本**）：

> **同一个 `(primary, avoid)` 输入下，LLM 路径的候选集与离线路径的默认搭配，
> 对 `avoid` 的屏蔽结论必须一致** —— 即：离线路径留下的饮片，不得出现在
> `filter_by_constitution(primary, avoid=avoid)` 的排除集里。

这条守卫的直接意义：将来有人只改 `safety.py` 忘了 `matcher.py`（或反之），测试立刻变红 ——
也就是把「有无 Key 拿到不同安全边界」这个静默失效**钉死在测试里**。

### 提交 5 · 文档

- `docs/pending-items.md`：**新增一项**「LLM 路径与离线路径对 primary 的 unsuitable 处置不一致
  （硬排除 vs 软提示）」—— §0.2 发现的既有问题，登记但本次不改。
- B2 条目补「接入」的进展与剩余（阶段 3 网页版待定）。
- `docs/handover.md` 文档地图加入本文；决策表补一条。

---

## 3　阶段 2 · 终端接线（提交 6，本次做）

### 3.1　依赖：用 `pip install -e`（子包根有 `pyproject.toml`，可直接装）

```bash
core/.venv/Scripts/python.exe -m pip install -e tcm-constitution-questionnaire
```

⚠️ **只装进 venv，不写进 `core` 的依赖声明** —— 子包对 core 是**可选**依赖，
core 的任何模块都不许 import 它（D5）。终端（`ui/terminal/`）是**外部调用方**，可以 import。

### 3.2　子包侧可复用的入口（不用自己写问答循环）

- `tcm_constitution.cli.run_interactive()` → `(answers: dict[str,int], sex: str)`
- `tcm_constitution.scoring.score_questionnaire(answers, sex)` → `{"scores": {id: {...}}, "summary": {...}}`

⇒ 终端只做「跑这两个 → 拿 `scores` → 交给 `resolve_from_scores`」，**不重复实现国标计分**。

### 3.3　`ui/terminal/chat.py` 的改动点

| 位置 | 改动 |
|---|---|
| 顶部 import | 增 `from app.domain.constitution_resolver import resolve_from_scores` |
| 新增 `_run_questionnaire()` | **try-import 子包**；成功 → 答题 + 计分 + 换算，返回 `(primary, avoid, note)`；`ImportError` → 打印明确指引（`pip install -e ...`）并 `return 2`，**不抛 `ModuleNotFoundError`** |
| `pick_constitution`（`chat.py:309`） | 保持单值返回不变（既有行为不动） |
| `cmd_full` / `cmd_offline` / `_offline_analyze`（`chat.py:203/235/257`） | 增 `avoid: Sequence[Constitution] = ()` 形参，透传给 `AnalyzeRequest(avoid_constitutions=...)`（`chat.py:283`）与 `matcher.fallback_recommend(..., avoid=...)`（`chat.py:231`） |
| `repl`（`chat.py:319`） | 增 `:qz` 命令：跑问卷 → 设置 primary/avoid → 打印 `note` |
| `main`（`chat.py:360`） | 增 `--questionnaire`；与 `--constitution` 同时给时报参数冲突 |

`note` 的打印：`resolve_from_scores` 产出，直接原样输出（D7 的强制告知就在里面）。
**不做**任何改写或摘要 —— 文案由换算层一处定义，避免两处漂移。

### 3.4　`core/scripts/check_setup.py` 增第 6 节

现在脚本是 `[1/5]`…`[5/5]`，新增后需把五处编号改成 `[n/6]`：

- **节名**：`[6/6] 问卷子包（可选依赖）`
- **判定**：`importlib.util.find_spec("tcm_constitution")` 能找到 → `OK`
- **缺失时**：**`WARN` 而不是 `FAIL`** ⚠️ —— 它是可选依赖，标 FAIL 会让 `check_setup` 退出码变 1，
  把「没装问卷」误报成环境不健康，破坏既有流程
- **文案**：`未安装 —— 终端 --questionnaire 不可用；安装：pip install -e tcm-constitution-questionnaire`

### 3.5　阶段 2 不做什么

- 不改 `pick_constitution` 的既有默认（仍是平和质）
- 不新增测试（`ui/terminal/` 当前无测试覆盖，本次不引入新测试目录）
- 网页版不动（D5′ ①）

---

## 4　验收

```bash
cd core && .venv/Scripts/python.exe -m pytest -q
```

| 判据 | 怎么验 |
|---|---|
| 兼体质不出现相冲饮片 | 合成 `scores`（2 个「是」）→ `resolve_from_scores` → 喂 `filter_by_constitution`，断言候选集里没有对第二个体质标 `unsuitable_for` 的饮片 |
| 倾向被明确告知 | `note` 含「未达判定阈值」，且不进 `Basis` |
| 未就绪被 422 拦下而非 500 | `monkeypatch` `ready_constitutions` 造未就绪 id，断言 `CONSTITUTION_NOT_READY` |
| 跨路径一致 | 提交 4 的守卫 |
| 判不出不冒充平和质 | R7 |

外加一条**回归**：既有调用方不传 `avoid_constitutions` 时，**行为逐字节不变**（`avoid=()` 等价性，
由提交 2 的负控制守住）。

---

## 5　两个待定项（**已拍板**）

### D6-A′　离线路径对 `avoid` 用**硬剔除**还是**软提示**？→ **① 硬剔除**

| 选项 | 行为 | 与 LLM 路径 |
|---|---|---|
| **① 已选中：硬剔除** | 命中的饮片直接从 blend 去掉，剔空则退通用兜底 | **一致**（LLM 也是硬排除） |
| ② 软提示 | 只加一句 caution，饮片仍在 | 不一致（同一个兼体质用户，有无 Key 结果不同） |

选中理由（你的原话）：**不能留「已知却不告知的不一致」**。
⚠️ ① **只针对 `avoid`**；`primary` 维持现状（软提示），那条既有不一致按 §0.2 只登记不改。

### D5′　网页版怎么办？→ **① 本次不做**

D5-a 说「计分由前端/终端/CLI 自己调子包」。但 `ui/web/index.html` 是**纯静态 JS**，
跑不了 Python 子包 ⇒ **网页版拿不到 `scores`**，除非：

| 选项 | 做法 | 结论 |
|---|---|---|
| **① 已选中：本次不做网页版** | 阶段 1+2 交付，网页版继续用体质下拉框 | ✅ 等 `/api/analyze-offline` 那轮一起定端点 |
| ② 加 `POST /api/questionnaire` | core 计分 + 换算，需 import 子包 | ❌ 与 D5 冲突，需 try-import + 501 降级 |
| ③ 加 `POST /api/constitution/resolve` | 只换算不积分 | ❌ 伪选项：前端还是得先有 scores，对纯静态前端无解 |
| ④ 前端用 JS 重写国标计分 | 两份实现 | ❌ 必然漂移，直接排除 |

⇒ **接受的代价**：网页版本次用不上问卷。已记入 §6 明确不做。

---

## 6　明确不做

1. 不改 `herbs.json`、`constitution.json` 等 `core/data/*.json`
2. 不改 `Basis`（D7），说明走 `user_message`
3. 不动 `/api/analyze` 的既有字段语义（`avoid_constitutions` 默认空）
4. 不做用户画像（`ProfileResponse` 是无路由的预留空壳）
5. 不并 `questionnaire.py`、不接 `multi_provider.py`
6. **不做网页版问卷**（D5′ ①）—— `ui/web/index.html` 一行不动，等 `/api/analyze-offline` 那轮定端点
7. **不改 `primary` 在离线路径的既有软提示行为**（§0.2，只登记）
8. **不把问卷子包写成 core 的依赖**（D5）—— 只 `pip install -e` 进 venv，core 模块零 import

---

## 7　提交总表（开工后按序执行，每步跑 pytest）

| # | 内容 | 新增/改动文件 | 预期测试数 |
|---|---|---|---|
| 1 | 换算层 | + `core/app/domain/constitution_resolver.py`<br>+ `core/tests/test_constitution_resolver.py` | +7 |
| 2 | 判定层支持 `avoid` | `core/app/domain/safety.py`、`core/app/agents/agent2_recommend.py` | +2（含 `avoid=()` 等价性负控） |
| 3 | 编排层 + 离线路径 | `core/app/domain/models.py`、`core/app/services/orchestrator.py`、`core/app/services/matcher.py` | +2 |
| 4 | 跨路径一致性守卫 | + `core/tests/test_constitution_integration.py` | +2 |
| 5 | 文档 | `docs/pending-items.md`、`docs/handover.md` | 0 |
| 6 | 终端接线（阶段 2） | `ui/terminal/chat.py`、`core/scripts/check_setup.py`、README | 0 |

**收口判据**：`core` 全量 `pytest` 绿，且**既有 462 条一条都不能改期望** ——
`avoid=()` 与 `avoid_constitutions=[]` 时行为必须与现状逐字节等价。
