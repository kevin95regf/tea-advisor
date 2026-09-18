# B2　体质标识对齐：问卷侧 `phlegm_dampness` → `phlegm_damp`

> **本文是 B2 的独立方案与执行记录。** 挂起清单 `docs/pending-items.md` 只留状态与结论，
> 决策过程、取证、具体改动清单在这里。
>
> 快照：**2026-09-18**　决定：**采用方案①（问卷侧改名）**，方案②（边界适配映射）不采纳。

---

## 1　结论先说

| | |
|---|---|
| **问题** | 仓库内的 `tcm-constitution-questionnaire/`（国标问卷子项目）用 `phlegm_dampness` 表示痰湿质；`core/` 用 `phlegm_damp`。两边对同一体质给出**不同的标识串** |
| **决定** | **方案①：问卷侧改名**，把子项目里的 `phlegm_dampness` 全部改成 `phlegm_damp`。项目侧（`core/`）**一个字都不动** |
| **为什么不选方案②** | 见 §4。一句话：适配映射是「两边各说一套话，中间加翻译」，改名是「统一说一套话」。B2 的本质是**命名权**问题，不是兼容问题 |
| **不并入的东西** | nanple 那份 `core/app/api/questionnaire.py` **不并入主线**（题库是 T/CACM 1460—2023 附录 A 的 60 题版，主线是 GB/T 46939-2025 的 27 题版，换标准不是小事）。**只吸收它里面的拼写映射，且只作为本方案的素材** |

---

## 2　取证：两套标识逐项对照

问卷侧 = `tcm-constitution-questionnaire/tcm_constitution/questions.py:21-31` 的 `CONSTITUTION_NAMES`；
项目侧 = `core/app/domain/enums.py:75-83` 的 `Constitution`。

| # | 问卷侧（`questions.py`） | 项目侧（`enums.py`） | 一致？ |
|---|---|---|---|
| 1 | `balanced` | `balanced` | ✅ |
| 2 | `qi_deficiency` | `qi_deficiency` | ✅ |
| 3 | `yang_deficiency` | `yang_deficiency` | ✅ |
| 4 | `yin_deficiency` | `yin_deficiency` | ✅ |
| 5 | **`phlegm_dampness`** | **`phlegm_damp`** | ❌ **唯一差异** |
| 6 | `damp_heat` | `damp_heat` | ✅ |
| 7 | `blood_stasis` | `blood_stasis` | ✅ |
| 8 | `qi_stagnation` | `qi_stagnation` | ✅ |
| 9 | `special_diathesis` | `special_diathesis` | ✅ |

**9 个里只有 1 个不同**，且差异只是「痰湿」的英文拼写（`dampness` vs `damp`）。
其余 8 个完全相同 —— 这决定了改名的**成本极低、风险极低**。

> ⚠️ **一处认知纠正**：此前把 B2 记成「nanple 分叉带来的问题」，**不准确**。
> 主线仓库**自己就带着** `tcm-constitution-questionnaire/`（已入库、工作区干净），
> 它内部就已经是 `phlegm_dampness`。分叉里的 `api/questionnaire.py` 只是**又做了一次适配**。
> 也就是说：**即便永远不并那份 questionnaire.py，B2 依然存在。**

---

## 3　拼写映射的提取（出自分叉，仅存档）

分叉文件：`D:\work\tea-advisor-fork-keep\questionnaire\core\app\api\questionnaire.py:24-30`

```python
# 问卷子包沿用国标分量表名称，主应用的公共契约使用
# phlegm_damp。在 API 边界统一，避免问卷结果无法命中推荐规则。
CONSTITUTION_ID_ALIASES = {"phlegm_dampness": "phlegm_damp"}


def public_constitution_id(scale_key: str) -> str:
    return CONSTITUTION_ID_ALIASES.get(scale_key, scale_key)
```

这是**方案②**的实现：子包照旧输出 `phlegm_dampness`，在 API 出口处翻译成 `phlegm_damp`。

**处置：不采纳，不入主线。** 理由见 §4。这段代码的价值在于它**证实了差异真实存在且只有 1 处**
（别名表只有 1 个键），与 §2 的静态清点互相印证。

---

## 4　为什么选方案①而不是方案②

| 维度 | ① 问卷侧改名 | ② API 边界加适配映射 |
|---|---|---|
| 标识串 | 全仓只有 `phlegm_damp` 一种 | 子包内 `phlegm_dampness`、边界外 `phlegm_damp`，**两种并存** |
| 出错面 | 无（不存在可写错的地方） | 每次新增取用点都要记得过 `public_constitution_id()`，**漏一处就静默错** |
| 漏用的后果 | — | 痰湿质打分直接落不进推荐规则，且**从输出表面看不出来**（和「体质无数据」同类静默失效） |
| 谁承担成本 | 改 3 个文件共 8 处（子项目内部） | 永久维护一份别名表 + 每次调用的纪律 |
| 与既有决定的一致 | 项目 id 已在九型里全部确认（B3），**以它为准** | 等于承认两边都有理，无单一事实源 |

**决定性理由**：B2 的本质是**命名权**——两套标识里必须有一个是唯一事实源。
`core/` 的 9 个 id 已在 B3（5→9 型）中确认、被 `constitution.json` / `enums.py` /
`herb_evidence_sources.json` / 三个测试文件共同引用，是**承重**的那一套；
问卷子包目前**没有任何接入方**（`core/` 不 import 它），改名零下游影响。

---

## 5　方案① 的具体改动

### 5.1　代码（3 个文件，8 处）

全部是同一替换：`phlegm_dampness` → `phlegm_damp`。

| 文件 | 处数 | 行（改动前） |
|---|---|---|
| `tcm-constitution-questionnaire/tcm_constitution/questions.py` | 4 | 26（`CONSTITUTION_NAMES` 键）、93、96、99（`ScaleUse("phlegm_dampness")`） |
| `tcm-constitution-questionnaire/questionnaire.csv` | 3 | 15、16、17（`scale` 列首字段） |
| `tcm-constitution-questionnaire/tests/test_scoring.py` | 1 | 66（`item_count` 断言的键） |

**不需要改的**：
- `scoring.py` / `cli.py` / `__init__.py` —— 它们只读 `CONSTITUTION_NAMES` 与 `BIASED_CONSTITUTIONS`，
  从字典**派生**，不写死键名（已 grep 确认无字面量）。
- `examples/answers_balanced.json` —— 内容是题号→分值，不含 scale 键。
- `QUESTIONNAIRE.md` / `README.md` —— grep 无该字面量。
- `core/` 下**任何文件** —— 一个字都不动。

### 5.2　守卫测试（新增）

新增 `core/tests/test_questionnaire_id_alignment.py`，纯函数判定（入参 `str`），沿用本项目的
「**派生不变式 + 负控制**」范式：

| 守卫 | 不变式 | 负控制 |
|---|---|---|
| G1 | `questionnaire.csv` 的 `scale` 列集合 == `Constitution` 全部枚举值 | 造一段含 `phlegm_dampness` 的 CSV 文本，断言校验函数**报出**该键 |
| G2 | `questions.py` 的 `CONSTITUTION_NAMES` 键（AST 解析，含顺序）== 枚举值序列 | 造一份把键改回 `phlegm_dampness` 的源码，断言**不相等** |
| G3 | `questions.py` 里所有 `ScaleUse("...")` 的实参 ∈ 枚举值 | 造一个 `ScaleUse("phlegm_dampness")`，断言被判为非法 |
| G4 | 子包三个文件里**不含**字面量 `phlegm_dampness` | 断言该检查对含旧拼写的文本**会失败** |

G1/G2/G3 都是**派生**的（判据来自 `Constitution` 枚举本身，不是抄一份快照），
所以将来十型、十一型扩枚举时，测试**会自动指出问卷侧没跟上**，而不是静默放行。

> 为什么用 AST 而不是正则或 `import`：
> `core/` 不 import 这个子包（它要靠 `sys.path` 塞路径才能引），硬引会让 `core` 的测试依赖
> 子包的可安装性；正则又太脆。AST 是「读源码结构」，与 `test_agent2_prompt.py` 数 `Basis(` 同一路数。

### 5.3　文档

| 文件 | 改动 |
|---|---|
| `docs/pending-items.md` B2 | 状态 `待 nanple` → `✅ 已解决（2026-09-18，方案①）`，补解决方式；概览表同步 |
| `docs/handover.md` | 决策 28 行补「已于 2026-09-18 由方案①解决」；§8 文档地图加本文 |
| `docs/maintenance.md` | §822 附近的接入提示改为「已对齐，直接可用」 |
| `docs/constitution-9-types.json` | 该处「仍然待处理」的附注改为已处理（改完须重跑 `build_constitution_doc.py`） |
| `docs/constitution-9-types.md` | **不手工编辑**，由上面的脚本重新生成 |

> ⚠️ **重新生成时发现的既有问题（顺带修了）**：`docs/constitution-9-types.json` 的
> 「244 格」条目里那段「仍未完成」是**旧版**（写「另有 3 处待确认已单列」），
> 而 `constitution-9-types.md` 里是新版（已裁定 5 处、余 239 格）—— 也就是说
> 这份生成文档此前**与它的 JSON 事实源不同步**（`--check` 只校结构、不校全文，测不出来）。
> 本次按 `pending-items.md` B3（挂起事项唯一真源）的口径把 **JSON 更新成新版**再重新生成，
> 于是 `.md` 的 diff **只剩 B2 那一行**，没有夹带无关改动。

---

## 6　验收

```bash
# 1. 全量（含新增 8 条：4 守卫 × 正负控）—— 期望 462 passed
cd core && .venv/Scripts/python.exe -m pytest -q

# 2. 问卷子包自带用例（改名后仍应全绿，8 passed）
cd tcm-constitution-questionnaire/tests
PYTHONPATH=".." "../../core/.venv/Scripts/python.exe" -m unittest test_scoring

# 3. 事实源确认
cd core && .venv/Scripts/python.exe -c "
from app.domain.enums import Constitution
print([c.value for c in Constitution])"      # 含 phlegm_damp
```

> 子包的测试目录**没有 `__init__.py`**，所以 `python -m unittest discover -s tests -t .`
> 会报 `Start directory is not importable`。用上面第 2 条的形式（进 `tests/` + `PYTHONPATH=..`）。

**判据**：两边对同一体质给出同一个标识串 `phlegm_damp`；
且 `core/` 无需任何适配层即可直接使用问卷输出的体质 id。

---

## 7　本方案**不做**的事（别越界）

1. **不并入**分叉的 `core/app/api/questionnaire.py` —— 题库标准不同（60 题 T/CACM vs 27 题 GB/T）。
2. **不接入** `multi_provider.py` —— 多供应商不是当前瓶颈，留作参考。
3. **不动** `ui/web/index.html`（557 行版）—— 分叉那份 2075 行版留在
   `D:\work\tea-advisor-fork-keep\reference-not-absorbed\ui\web\index.html` 作 🟡 四项素材。
4. **不改** `core/data/constitution.json` 与 `enums.py` —— 项目侧是事实源。
5. **不解决**问卷的**接入**问题 —— B2 只解决标识对齐。接不接、怎么接是另一件事，
   且接入前还有一道坎：问卷输出的是**倾向性体质**，进推荐前要过 `ready_constitutions()` 就绪闸门。
