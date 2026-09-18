# B2 接入：问卷输出接进推荐链路 + 过就绪闸门

> **本文是「B2 接入」的方案，待确认后才动代码。**
> 上一篇 `docs/b2-constitution-id-alignment.md` 解决的只是**标识对齐**（`phlegm_damp`），
> 那一步已经做完。**接入**是另一件事，难点不在改名，而在**语义落差**。
>
> 快照 **2026-09-18**　状态：**待拍板**（本文有 7 个决策点需要你定）

---

## 1　结论先说

| | |
|---|---|
| **要做什么** | 把 `score_questionnaire()` 的输出换算成推荐链路能吃的体质输入，并让它过既有的就绪闸门 |
| **核心难点** | **不是**「接线」，而是国标问卷的输出**语义**与推荐链路的输入**不匹配**（§2） |
| **建议范围** | 只做**换算层 + 闸门 + 四处接入点同步**，**不做**问卷 UI、**不做**用户画像 |
| **最需要你拍的板** | **D2（倾向是怎么办）** 与 **D6（离线路径要不要一起改）**，其余我有明确建议 |

---

## 2　语义落差：三个必须显式处理的地方

### 2.1　落差一：问卷输出**多个**体质，推荐链路只吃**一个**

`score_questionnaire` 的 `notes` 里明写：

> 标准允许**多种偏颇体质同时判定为「是」或「倾向是」**

也就是说 `summary.biased_constitutions_confirmed` 可能是 `["气虚质", "痰湿质"]` —— **兼体质是常态，不是异常**。

而推荐链路的入口是**单值**：`AnalyzeRequest.constitution_override: Constitution | None`
（`models.py:191`），`filter_by_constitution(constitution: str)` 也只收一个。

### 2.2　落差二：「倾向是」**不是判定**

国标分档：`≥40 → 是`、`≥30 且 <40 → 倾向是`、`<30 → 否`。
子包自己的 `notes` 还额外声明 `ranking_nonstandard` **不是国标规定的主导体质诊断**。
把「倾向是」当「是」来配茶，等于把筛查信号当诊断用。

### 2.3　落差三：子包输出的是**中文名**，不是 id

`summary.biased_constitutions_confirmed` / `..._tendency` / `ranking_nonstandard.constitution`
里装的都是 `"痰湿质"` 这类**中文名**。

**这决定了换算必须从 `scores` 字典的键取 id，不能从 `summary` 反查中文名**
—— 反查要维护一张中文名→id 的表，是第二份事实源，会漂移。
（顺带说明：B2 把 `phlegm_dampness` 改成 `phlegm_damp` 的价值就在这一步兑现 ——
`scores` 的键现在**直接就是** `Constitution` 的合法值。）

---

## 3　现状取证：接入点有**四处**，彼此独立

这是本文最重要的发现。**体质在运行时被四处独立消费，它们不共享一次换算**：

| # | 位置 | 干什么 | 收到几个 id |
|---|---|---|---|
| ① | `orchestrator._ensure_constitution_ready`（`orchestrator.py:60`） | **就绪闸门**，不就绪抛 422 `CONSTITUTION_NOT_READY` | 1 |
| ② | `agent2_recommend.py:65` → `filter_by_constitution` | **LLM 路径**构造候选集（`suitable` 收敛 + `unsuitable` 屏蔽） | 1 |
| ③ | `matcher._constitution_default` → `CONSTITUTION_DEFAULT` 表 | **离线/规则路径**按体质查表取默认搭配 | 1 |
| ④ | `_sanitize_recommendations` → `check_constitution_fit`（`orchestrator.py:153`） | **输出护栏**，命中 `unsuitable_for` 出 warning | 1 |

**只改其中一处会怎样**（这就是本项目反复强调的静默失效形状）：

- 只改 ② → LLM 路径对兼体质做了屏蔽，**离线路径 ③ 完全没变**（它走 `CONSTITUTION_DEFAULT` 查表，
  根本不经过 `filter_by_constitution`）⇒ 同一个用户、有无 Key 时拿到**不同的安全边界**。
- 只改 ① → 闸门放行，但 ②③④ 都还按单体质算。
- 只改 ④ → 护栏会警告，但候选集里压根没被排除，等于每次都靠事后拦截。

> 附带发现：`models.py` 里的 `ProfileResponse` / `ProfileUpdateRequest`（`source` 字段写着
> `questionnaire / manual / inferred`）是**预留空壳**——仓库里**没有任何路由**用它们。
> 所以「用户画像」这条线目前是死的，本次不碰。

---

## 4　七个决策点

### D1　兼体质怎么收敛？（建议：**主导体质 + 其余进屏蔽集**）

| 选项 | 做法 | 问题 |
|---|---|---|
| ① **建议** | `primary` = confirmed 里转化分最高者，用于 `suitable` 收敛；**其余 confirmed 全部进 `avoid`**，只做 `unsuitable_for` 屏蔽 | 需要改 4 处（见 D6） |
| ② | 全部 confirmed 求候选集交集 | 交集很可能为空 ⇒ 没有候选 ⇒ 要么报错要么退化，比 ① 更难收场 |
| ③ | 有多个 confirmed 就拒绝，让用户手选 | 把国标允许的常态当成错误处理，体验差 |

**① 的理由**：「任一已确认体质标了 `unsuitable_for` 的饮片都不得进入候选集」是**派生不变式**，
可测、方向明确；而 `suitable` 收敛只能按一个方向做（两个方向的并集没有意义）。

### D2　「倾向是」怎么办？（**需要你拍板**）

| 选项 | 做法 | 理由/风险 |
|---|---|---|
| **A** | 倾向**永不进** primary；confirmed 为空时 → 平和质（前提是 balanced 判为「是/基本是」） | 最保守，符合国标语义。但用户可能明明有明显倾向却拿到平和质方案 |
| **B（建议）** | 倾向**不进** primary，但 confirmed 为空时，取最高分倾向体质作 primary，**并在 `user_message` 里强制写明「问卷未达判定阈值，按倾向处理」** | 兼顾可用与诚实；依据不足这件事**必须让用户看见** |
| **C** | 倾向也进 `avoid` | 过度屏蔽，可能把候选集掏空 |

⚠️ 无论选哪个，**都不能**把倾向当「是」写进 `Basis`（`Basis` 是输出给用户看的依据）。

### D3　平和质怎么判？

`summary.balanced` 有三档：`是`（≥60 且所有偏颇 <30）、`基本是`（≥60 且所有偏颇 <40）、`否`。

- `是` → 平和质
- `基本是` → 平和质，**并把 30–40 分段的偏颇体质列进 `user_message`**（它正是「基本是」的代价）
- `否` 且 confirmed 与 tendency **都为空** → **无法判定** ⇒ 建议**拒绝**并让用户手动选，
  **不要默认平和质**（默认平和质 = 用平和的答案冒充一个判不出来的体质，与
  `_ensure_constitution_ready` 里明令禁止的回落是同一个错误）

### D4　未就绪体质怎么办？（建议：**复用既有闸门，不新造**）

换算出的 `primary` 若不在 `ready_constitutions()` 里 → 沿用 `CONSTITUTION_NOT_READY` 422。
现在 9 型全就绪，这条**几乎不会触发**，但规则必须写明，否则将来补第 10 型时
问卷会直接把一个没数据的体质喂进 `filter_by_constitution` → `MissingConstitutionDataError` → 500。

### D5　依赖怎么接？（建议：**core 不 import 子包**）

| 选项 | 做法 | 问题 |
|---|---|---|
| ① **建议** | 换算层写成**纯函数**（入参 = `score_questionnaire` 的 `scores` dict），放在 `app/domain/`；core **零依赖** | 需要一个地方调用子包计分（见下） |
| ② | `sys.path` 塞路径 import（分叉的做法） | 丑，且 core 的 `pythonpath` 是 `core/`，塞相对路径易碎 |
| ③ | 把 `tcm_constitution` 复制进 `core/app/` | **两份题库**，必然漂移，违单一事实源 |

**① 的好处**：core 的测试可以直接喂 dict，**不依赖子包可安装性** —— 与刚建的
`test_questionnaire_id_alignment.py`（AST 解析、不 import）是同一路数。

**计分由谁做**（需你选）：
- **a. 不新增端点**：前端/终端/CLI 自己调子包（`python -m tcm_constitution` 或直接 import），
  拿到结果后把 `primary` 填进 `constitution_override`、`avoid` 填进新字段。core 只提供换算层 + 校验。
- **b. 新增 `POST /api/questionnaire`**：core 里 `try: from tcm_construction ... except ImportError: 501`。
  好处是前端只跟一个后端说话；代价是 core 多一个**可选依赖**和一条「依赖缺失」的降级路径。

### D6　离线路径（③）要不要一起改？（**需要你拍板**）

`CONSTITUTION_DEFAULT` 是**手工维护**的「每体质一组默认搭配」表（`matcher.py:77`），
与 `herbs.json` 的 `suitable_constitutions` 是**两套独立数据**。
要让它支持 `avoid`，有两种改法：

| 选项 | 做法 | 代价 |
|---|---|---|
| **A（建议）** | 不改表；在 `_constitution_default` 取到搭配后，**逐个检查 `avoid` 里每个体质的 `unsuitable_for`**，命中就走既有 `cautions` 提示或换通用兜底 | 小；复用 `matcher.py:297` 已有的那段检查逻辑，扩成遍历 `avoid` |
| **B** | 给 `CONSTITUTION_DEFAULT` 手工补兼体质组合键（如 `qi_deficiency+phlegm_damp`） | 组合爆炸（8 选 2 就有 28 组），且是第二份人工事实源 |

**若你选「离线路径暂不处理」**，那必须在文档与 `user_message` 里明写「兼体质屏蔽仅在联网路径生效」——
否则就是一处**已知却不告知**的不一致。我建议选 A，改动量不大。

### D7　输出里怎么体现问卷依据？

**建议：不动 `Basis`。** 理由：
- `Basis` 有**唯一构造点**纪律（`orchestrator._build_basis()`，AST 守卫数 `Basis(` 恰 1 处），
  加字段会牵连多个测试；
- `AnalyzeResponse.user_message`（`models.py:211`）**已经是**「需要向用户补充说明的话」，
  兼体质、倾向、依据不足的说明正好放这里，**零契约改动**。

---

## 5　改动清单（按上面的建议选项）

| Step | 文件 | 改动 |
|---|---|---|
| 1 | `core/app/domain/constitution_resolver.py`（新） | 纯函数：`resolve_from_scores(scores: dict) -> Resolution`；`Resolution = (primary, avoid, status, caveats)`。**不 import 子包** |
| 2 | `core/app/domain/enums.py` | 不改（`phlegm_damp` 已是事实源）。若 D5-b 需要，加可选 import 守卫 |
| 3 | `core/app/domain/models.py` | `AnalyzeRequest` 增 `avoid_constitutions: list[Constitution] = []`（默认空 ⇒ 对既有调用方**零影响**） |
| 4 | `core/app/services/orchestrator.py` | ① 闸门：对 `primary` **和** `avoid` 里每个 id 都过 `ready_constitutions()`；③/④ 处把 `avoid` 传下去 |
| 5 | `core/app/domain/safety.py` | `filter_by_constitution(constitution, *, avoid=())`：派生不变式——命中任一 avoid 的 `unsuitable_for` 即排除 |
| 6 | `core/app/agents/agent2_recommend.py` | 把 `avoid` 透传给 `filter_by_constitution` |
| 7 | `core/app/services/matcher.py` | D6-A：把 `matcher.py:297` 的单体质检查扩成遍历 `avoid` |
| 8 | （可选，D5-b）`core/app/api/questionnaire.py` | 新端点；`try import` 失败 → 501 + 明确 message |

**不动**：`core/data/*.json`、`Basis`、`/api/analyze` 的既有字段语义、前端。

---

## 6　守卫测试设计

沿用「**派生不变式 + 负控制**」，纯函数入参 `dict`，**不 import 子包**：

| 守卫 | 不变式 | 负控制 |
|---|---|---|
| G1 | `resolve_from_scores` 返回的 `primary` 与 `avoid` **全部** ∈ `Constitution` 合法值 | 喂一个含 `phlegm_dampness` 的 scores，必须报错而不是静默接受 |
| G2 | `avoid` 与 `primary` **不相交**（主导体质不能同时被屏蔽） | 造一个两者相同的输出，断言被抓 |
| G3 | **每个**「是」的体质都在 `primary ∪ avoid` 里（不丢） | 造 3 个「是」只收 2 个的合成输入，断言被抓 |
| G4 | 「倾向是」**永不在** `primary`（除非 confirmed 为空且选了 D2-B） | 造「1 个是 + 1 个倾向」的输入，断言倾向体质的 id 不在 primary |
| G5 | 输出的每个 id 都在 `ready_constitutions()` 里，否则闸门拦下 | `monkeypatch` 掉 `ready_constitutions` 造未就绪场景（**不拿真实数据当样本**） |
| G6 | `filter_by_constitution(avoid=...)`：候选集里**不存在**任何对 avoid 体质标了 `unsuitable_for` 的饮片 | 真实数据 + 合成 catalog，`monkeypatch` 造 |

另加一条**跨路径一致性**守卫（防 §3 说的「只改一处」）：
**同一个 `(primary, avoid)` 输入，② 的候选集与 ③ 的默认搭配，对 avoid 的屏蔽结论必须一致**。

---

## 7　验收

```bash
cd core && .venv/Scripts/python.exe -m pytest -q        # 全绿

# 手跑一条真问卷（子包自带样例）
cd tcm-constitution-questionnaire/tests
PYTHONPATH=".." "../../core/.venv/Scripts/python.exe" -c "
import json, tcm_constitution
from tcm_constitution import score_questionnaire
a=json.load(open('../examples/answers_balanced.json'))
r=score_questionnaire(a['answers'], a['sex'])
print(json.dumps(r['scores'], ensure_ascii=False, indent=1)[:600])
"
```

**判据**：① 兼体质时不出现对任一已确认体质「不宜」的饮片；② 倾向体质被明确告知而非静默采用；
③ 未就绪体质被 422 拦下而不是 500。

---

## 8　本方案不做的事

1. **不做问卷 UI**（前端 26 题表单）—— 属 🟡，等 `/api/analyze-offline` 之后。
2. **不做用户画像** —— `ProfileResponse` 虽已预留但**无路由**，是另一条线。
3. **不改 `herbs.json`** —— 本次不新增配伍标注。
4. **不改 `Basis`** —— 依据说明走 `user_message`。
5. **不并 `questionnaire.py`**、**不接 `multi_provider.py`** —— 已拍板。
