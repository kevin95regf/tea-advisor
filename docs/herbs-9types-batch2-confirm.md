# 批次二确认稿（**已于 2026-09-17 执行**）：5 格「待确认」配伍判定 + 豁免登记出口

> 状态：**四件事已裁决，方案已于 2026-09-17 执行完毕。** 本文件保留为方案留档；
> 实际执行结果（数据 diff、测试数、影响实测）见 `docs/herbs-9types-batch2.md`。
> 日期：2026-09-17　上游：`docs/pending-items.md` B3「需要什么」栏单列的 5 处
> 判定来源：项目所有者转达的**外部专业意见**（`level` 沿用 `docs/herbs-9types-draft.md` §2 的口径）
> 影响面：`core/data/herbs.json` 34 味中的 **4 味**（香薷、荷叶、山楂、槐花）

---

## 0. 四件事的裁决结果（回执）

| # | 问题 | 裁决 |
|---|---|---|
| 1 | 荷叶/山楂 的 cautions 与既有派生不变式冲突，怎么解 | **落地豁免出口**，并强制三条规则（见 §2） |
| 2 | 「依据等级」写哪 | **文案内 + `_meta` 结构化**；不新造条目字段（把空间留给 E2） |
| 3 | 新条款在 `cautions` 的位置 | **追加末尾**（不挤掉硬安全提示） |
| 4 | `docs/herbs-9types-batch2*.md` 两份新文档是否入库 | **入库** |
| 附 | 山楂×气郁「跃居首位」 | **先按现状写入**，在 `_meta` 里标 `priority_review`，请 nanple 优先复核（见 §3.3） |
| 附 | 两处过期既有记录 | 按 §5 同步；另有 1 处**超出清单的更正**一并列出待点头（§5.4） |

---

## 1. 最终写入清单（5 格 + 3 条附带文案）

| # | 格子 | 判定 | `level` | 写入字段 | 措辞强度后果 |
|---|---|---|---|---|---|
| 1 | 香薷 `xiangru` × 阴虚 `yin_deficiency` | **忌** | `evidence` | `unsuitable_for` | **硬屏蔽**（移出阴虚候选集） |
| 2 | 荷叶 `heye` × 阴虚 `yin_deficiency` | 慎用 | `inference` | `cautions` | 软约束，**登记豁免** |
| 3 | 山楂 `shanzha` × 阴虚 `yin_deficiency` | 慎用 | `inference` | `cautions` | 软约束，**登记豁免** |
| 4 | 山楂 `shanzha` × 气郁 `qi_stagnation` | 宜（倾向） | `inference` | `suitable_constitutions` | **升位**（候选表前排）→ 见 §3.3 的 `priority_review` |
| 5 | 槐花 `huaihua` × 血瘀 `blood_stasis` | 慎用（低置信） | `inference` | `cautions` | 软约束（**不触发**既有守卫，见 §1.3） |

附带文案 3 条：

| # | 对象 | 内容 | 落点 |
|---|---|---|---|
| A | 香薷 `cautions` | 补入「阴虚有热者禁用」（直接文献依据） | 条目 `cautions` **末尾** |
| B | 山楂 × 气郁 备注 | 「酸涩收敛忌气郁的说法缺乏文献依据，暂不采纳」 | `_meta` 批次块 `decisions` |
| C | 槐花 × 血瘀 备注 | 「直接迁移证据不足；慎用理由为槐花性凉，低置信」 | `_meta` 批次块 `decisions` |

### 1.1 逐条落到 JSON 的样子（改前 → 改后）

**香薷 `xiangru`** —— 唯一走硬屏蔽的一条（`level = evidence`）

```diff
-      "cautions": ["性温发汗，表虚多汗者不宜", "不宜久煮"],
+      "cautions": ["性温发汗，表虚多汗者不宜", "不宜久煮", "阴虚有热者禁用"],
-      "unsuitable_for": ["qi_deficiency", "damp_heat"],
+      "unsuitable_for": ["qi_deficiency", "damp_heat", "yin_deficiency"],
```

**荷叶 `heye`** —— 只加文案，`unsuitable_for` 保持 `["qi_deficiency","yang_deficiency"]` 不动

```diff
-      "cautions": ["体瘦、气血偏虚者不宜久服", "孕妇不宜"],
+      "cautions": ["体瘦、气血偏虚者不宜久服", "孕妇不宜", "阴虚质慎用（推断，未经人工审核）"],
```

**山楂 `shanzha`** —— 两格都落在这一味上

```diff
-      "cautions": ["胃酸过多、胃溃疡者慎用", "孕妇不宜", "不宜空腹大量饮用"],
+      "cautions": ["胃酸过多、胃溃疡者慎用", "孕妇不宜", "不宜空腹大量饮用", "阴虚质慎用（推断，未经人工审核）"],
-      "suitable_constitutions": ["phlegm_damp", "balanced", "blood_stasis"],
+      "suitable_constitutions": ["phlegm_damp", "balanced", "blood_stasis", "qi_stagnation"],
```

**槐花 `huaihua`** —— 只加文案，`unsuitable_for` 保持 `["yang_deficiency","qi_deficiency"]` 不动

```diff
-      "cautions": ["性凉，脾胃虚寒者不宜", "孕妇不宜"],
+      "cautions": ["性凉，脾胃虚寒者不宜", "孕妇不宜", "血瘀质慎用（低置信，依据为性凉，未经人工审核）"],
```

### 1.2 写入方式（沿用上一批的既定通道）

**文本级精确替换**（按 id 定位块、只重写目标行），不用 `json.load` + `json.dumps` 整体回写
——`herbs.json` 是**内联数组**风格，整体序列化会炸出上千行假 diff。
验收：`git diff --numstat core/data/herbs.json` 恰为 **4 增 4 删**（数据行）＋ `_meta` 区块。

### 1.3 只有荷叶、山楂 需要登记豁免 —— 槐花不触发守卫

既有守卫的关键词集是 `("阴虚", "津液", "口干", "上火", "内热")`（`test_safety.py:261`）。

| 条目 | 新增文案 | 命中守卫关键词？ | 需登记豁免？ |
|---|---|---|---|
| 香薷 | 阴虚有热者禁用 | ✅ 命中「阴虚」 | ❌ 已硬屏蔽，天然满足 |
| 荷叶 | 阴虚质慎用（推断，未经人工审核） | ✅ 命中「阴虚」 | ✅ **需要** |
| 山楂 | 阴虚质慎用（推断，未经人工审核） | ✅ 命中「阴虚」 | ✅ **需要** |
| 槐花 | 血瘀质慎用（低置信，依据为性凉，未经人工审核） | ❌ 一条都不命中 | ❌ 不需要 |

所以豁免登记表**只有 2 条**（`heye`、`shanzha`），且都不是 `evidence` 级 —— 与规则③一致。

---

## 2. 豁免出口的实现方案

### 2.1 登记表放在哪：`_meta.constitution_extension.rulings`

不新造条目字段（把空间留给挂起项 E2），登记表挂在 `_meta` 下，与 `cautions_batch` 同级：

```json
"rulings": {
  "date": "2026-09-17",
  "source": "外部专业意见（项目所有者转达），非项目自有数据",
  "scope": "5 格：香薷×阴虚、荷叶×阴虚、山楂×阴虚、山楂×气郁、槐花×血瘀",
  "cells": [ ... ],
  "decisions": [ ... ],
  "priority_review": [ ... ],
  "review_status": "pending",
  "note": "写入 ≠ 审核通过。evidence → unsuitable_for（硬屏蔽）；inference → 允许 cautions / suitable_constitutions（软通道）。该规则由 core/tests/test_safety.py 强制，不靠人记"
}
```

**为什么叫 `rulings` 而不是 `nanple_batch`**：这份块记录的是**「人对格子的裁定」**，将来还会有下一批、
也可能来自另一位审阅者。用中性名可以持续追加 `cells`，不必为新批次再开一块、或把测试的读取路径钉死在一个人名上。

### 2.2 三条规则 → 具体代码

**规则落点**：`core/tests/test_safety.py` 的 `test_cautions_naming_yinxu_must_be_blocked`
（现有派生不变式的**唯一出口**，其 docstring 里早已写了「或在 docs 里说明为何不写」，本次把它变成代码）。

先把判定逻辑抽成**纯函数**（正向测试与负控制共用，避免「负控制另写一套逻辑」这种假保证）：

```python
# ---- 软约束豁免登记（cautions-only）----
# 登记表的唯一事实源是 herbs.json 的 _meta.constitution_extension.rulings.cells。
# 刻意不在测试里另存一份名单：两处名单必然漂移，而漂移的方向总是「测试放过、数据漏了」。
ROLLING_SOFT_FIELDS = ("cautions", "suitable_constitutions")

CORE_DIR = Path(__file__).resolve().parent.parent      # 新增：本文件原本没读文件
HERBS_JSON = CORE_DIR / "data" / "herbs.json"


def load_rulings() -> dict:
    """读 `_meta.constitution_extension.rulings`（没有则返回空 dict）。"""
    data = json.loads(HERBS_JSON.read_text(encoding="utf-8"))
    ext = ((data.get("_meta") or {}).get("constitution_extension") or {})
    return ext.get("rulings") or {}


def load_rulings_cells() -> list[dict]:
    """展开 rulings.cells；同时校验每格的形状（供 §2.2 的格式检查复用）。"""
    return list(load_rulings().get("cells") or [])


def _cautions_soft_gap(catalog: dict, cells: list[dict]) -> dict:
    """算出『cautions 命中阴虚方向关键词』与『软通道登记』之间的三类缺口。

    纯函数：不读文件、不依赖真实数据 —— 正向测试与负控制共用同一份逻辑。
    返回的每个 key 为空列表即代表该类问题不存在。
    """
    hit = {
        herb_id
        for herb_id, item in catalog.items()
        if any(k in c for c in (item.get("cautions") or []) for k in YINXU_CAUTION_KEYWORDS)
    }
    yin = [c for c in cells if c.get("constitution") == "yin_deficiency"]
    exempt = {c["herb"] for c in yin}
    return {
        "hit": hit,
        # 规则①：豁免项必须 ∈ 命中集（登记表不能当垃圾桶/后门）
        "stray": sorted(exempt - hit),
        # 规则③：登记项 level 不得为 evidence（明确忌必须硬屏蔽）
        "soft_evidence": sorted(c["herb"] for c in yin if c.get("level") == "evidence"),
        # 规则②：命中集里未登记的仍必须硬屏蔽
        "escaped": sorted(
            h for h in hit - exempt
            if "yin_deficiency" not in (catalog[h].get("unsuitable_for") or [])
        ),
    }
```

**正向测试**（改写现有那一条，断言从「零逃脱」升级为「三类缺口都为零」）：

```python
def test_cautions_naming_yinxu_must_be_blocked() -> None:
    """凡 cautions 明写阴虚方向的饮片，都必须被 `yin_deficiency` 挡在候选集外 ——
    除非它在 `_meta.constitution_extension.rulings` 里**登记**为「有意只走 cautions」。

    这是一条**派生不变式**，不是数据快照：它不写死「哪几味被屏蔽」，
    而是从 cautions 与 unsuitable_for 的关系推出来，所以数据怎么变都仍然有效。

    守的是软硬约束的脱节：`cautions` 只进提示词与护栏文案（模型可以不听），
    `unsuitable_for` 才是硬过滤。二者脱节就会出现「项目自己已认定阴虚不宜，
    却照样推给阴虚用户」—— 而这种错误从输出表面**看不出来**。

    豁免出口是 2026-09-17 落地的（`docs/herbs-9types-batch2.md`）。它有三条强制约束，
    都在 `_cautions_soft_gap` 里，缺一条闸门就漏：
      ① 豁免项必须 ∈ 命中集 —— 登记表不能变成绕过检查的后门；
      ② 命中集里**未登记**的仍必须硬屏蔽 —— 防线不松；
      ③ **登记项的依据等级不得为 `evidence`** —— 「明确忌 → 硬屏蔽」由代码强制，
         不靠人记得（香薷是 evidence，它想走软通道会被挡回来）。
    """
    gap = _cautions_soft_gap(load_herb_catalog(), load_rulings_cells())

    assert gap["hit"], "阴虚方向关键词一条都没命中，本测试已失去覆盖面，需同步更新关键词或 cautions"
    assert not gap["stray"], (
        f"这些饮片登记为『只走 cautions』，但 cautions 并不命中阴虚方向关键词：{gap['stray']}。"
        "登记表必须只收录真实命中的格子，否则它就成了绕过检查的后门"
    )
    assert not gap["soft_evidence"], (
        f"这些登记项的依据等级是 evidence，却想走 cautions 软通道：{gap['soft_evidence']}。"
        "evidence 级（明确忌）必须写进 unsuitable_for —— 依据等级决定写哪个字段"
    )
    assert not gap["escaped"], (
        f"这些饮片的 cautions 已明写阴虚方向，却既没被 yin_deficiency 屏蔽、也没登记豁免：{gap['escaped']}。"
        "要么补 unsuitable_for，要么在 `_meta` 的 rulings 块里登记为 cautions-only（等级不得为 evidence）"
    )
```

**负控制**（本项目铁律：只测「真实数据上没报错」等于没测 —— 那和「检查根本没跑」长得一模一样）：

```python
def test_cautions_soft_gap_negative_controls() -> None:
    """人造数据必须让三类缺口各自报出来 —— 否则上一条测试可能根本没在检查。"""
    catalog = {
        "a": {"cautions": ["阴虚者不宜"], "unsuitable_for": ["yin_deficiency"]},
        "b": {"cautions": ["阴虚者慎用"], "unsuitable_for": []},
        "c": {"cautions": ["孕妇不宜"], "unsuitable_for": []},   # 不命中关键词
    }
    good = [{"herb": "b", "constitution": "yin_deficiency", "level": "inference", "field": "cautions"}]

    g = _cautions_soft_gap(catalog, good)
    assert g["hit"] == {"a", "b"} and not (g["stray"] or g["soft_evidence"] or g["escaped"])

    # ① 登记了一个并不命中的饮片
    g = _cautions_soft_gap(catalog, good + [{"herb": "c", "constitution": "yin_deficiency",
                                             "level": "inference", "field": "cautions"}])
    assert g["stray"] == ["c"], "规则①失效：登记表可以收录没命中的格子"

    # ③ 把登记项改成 evidence
    g = _cautions_soft_gap(catalog, [{**good[0], "level": "evidence"}])
    assert g["soft_evidence"] == ["b"], "规则③失效：明确忌可以走软通道"

    # ② 抹掉一个未登记项的屏蔽
    broken = {**catalog, "a": {"cautions": ["阴虚者不宜"], "unsuitable_for": []}}
    g = _cautions_soft_gap(broken, good)
    assert g["escaped"] == ["a"], "规则②失效：未登记的条目可以逃脱硬屏蔽"
```

**规则③ 的一般化**（不局限于阴虚方向，把「依据等级决定写哪个字段」钉成全局不变量）：

```python
def test_rulings_cells_are_well_formed() -> None:
    """批次块每一格都要齐备，且 level 与 field 的搭配合法：`evidence` 只能写 `unsuitable_for`。

    规则③ 在阴虚方向上由 `_cautions_soft_gap` 强制；这条把它推广到**所有格子**
    —— 因为「明确忌必须硬屏蔽」与方向无关。反向不成立：`inference` 也允许写
    `unsuitable_for`（保守方向，cautions 批次 10 味就是这么做的）。
    """
    cells = load_rulings_cells()
    assert cells, "rulings.cells 为空 —— 要么本批没落地，要么登记被误删"
    for c in cells:
        for k in ("herb", "constitution", "verdict", "level", "field", "basis"):
            assert c.get(k), f"{c.get('herb')} 的登记缺字段 {k}"
        assert c["field"] in ("unsuitable_for",) + ROLLING_SOFT_FIELDS, f"未知 field：{c['field']}"
        if c["level"] == "evidence":
            assert c["field"] == "unsuitable_for", (
                f"{c['herb']}×{c['constitution']} 是 evidence 级却写了 {c['field']}："
                "明确忌必须落 unsuitable_for"
            )
```

> ⚠️ 注意 `test_cautions_exemption_registry_is_vacuous` 这类「登记表必须非空」的断言已并入
> 上面这条（`assert cells`）。**不写死「恰好 2 条」** —— 那会随批次失效，属数据快照。

### 2.3 为什么这不会把红线放松

| 担心的场景 | 结果 |
|---|---|
| 以后有人想偷偷把某味饮片从阴虚候选集里放出来 | 得先写一条 `rulings` 记录，而记录里 `level` 一填 `evidence` 就被规则③挡住；填 `inference` 则必须在 `verdict`/`basis` 里留下理由 —— **留痕**，且在 §3.3 的 `priority_review` 同级可见 |
| 以后有人往 cautions 里加词来试探 | 规则②会把未登记项报出来，**强制**做一次显式决定 |
| 登记表被当成垃圾桶，反正写进去就不报错 | 规则① 挡住：只有真命中关键词的格子才允许登记 |

---

## 3. `_meta` 的完整改动

### 3.1 版本与作废字段

```diff
-    "version": "0.3.0",
+    "version": "0.4.0",
```

`cautions_batch` 内的两条过期字段（原意：「这两味属外推，不写，待 nanple」）：

```diff
-        "excluded": ["heye", "xiangru"],
-        "excluded_reason": "docs/herbs-9types-draft.md 的阴虚 ✗ 列共 12 味，这两味的 cautions 措辞未提阴虚（荷叶只写『体瘦、气血偏虚者不宜久服』，香薷只写『性温发汗，表虚多汗者不宜』），依据属外推，不写入，已登记为待 nanple 判断",
+        "excluded_resolved": "原 `excluded`（荷叶、香薷）已于 2026-09-17 由外部专业意见裁决：香薷走硬屏蔽（unsuitable_for，evidence），荷叶走 cautions（软通道，inference）。见同级 `rulings` 块与 docs/herbs-9types-batch2.md",
```

> 「整条作废」的确切含义：**删掉 `excluded` / `excluded_reason` 两个键**，改为 `excluded_resolved` 一行指针。
> 留一行指针是为了保住审计线索（为什么当初没写），而不是把历史抹掉。

### 3.2 新增 `rulings` 块（草案）

```json
"rulings": {
  "date": "2026-09-17",
  "source": "外部专业意见（项目所有者转达），非项目自有数据",
  "scope": "5 格：香薷×阴虚、荷叶×阴虚、山楂×阴虚、山楂×气郁、槐花×血瘀",
  "cells": [
    {"herb": "xiangru", "constitution": "yin_deficiency", "verdict": "忌", "level": "evidence", "field": "unsuitable_for", "basis": "明确忌；另补 cautions『阴虚有热者禁用』（直接文献依据）"},
    {"herb": "heye", "constitution": "yin_deficiency", "verdict": "慎用", "level": "inference", "field": "cautions", "basis": "不硬屏蔽，登记为 cautions-only"},
    {"herb": "shanzha", "constitution": "yin_deficiency", "verdict": "慎用", "level": "inference", "field": "cautions", "basis": "不硬屏蔽，登记为 cautions-only"},
    {"herb": "shanzha", "constitution": "qi_stagnation", "verdict": "宜（倾向）", "level": "inference", "field": "suitable_constitutions", "basis": "倾向判定，写入后升位至气郁候选首位，见 priority_review"},
    {"herb": "huaihua", "constitution": "blood_stasis", "verdict": "慎用", "level": "inference", "field": "cautions", "confidence": "低", "basis": "依据为性凉；直接迁移证据不足"}
  ],
  "decisions": [
    "山楂×气郁：酸涩收敛忌气郁的说法缺乏文献依据，暂不采纳",
    "槐花×血瘀：直接迁移证据不足；慎用理由为槐花性凉，低置信"
  ],
  "priority_review": [
    {
      "cell": "shanzha × qi_stagnation",
      "severity": "高",
      "issue": "本格是 inference 级「倾向」判定，但写入 suitable_constitutions 后会获得『升位』效果：山楂 catalog 下标 2，早于红枣(6)、薄荷(12)，因此跃居气郁候选清单第 1 位，直接进 Agent2 提示词首行。倾向性判定不宜带有升位效果。",
      "options": ["改走 cautions（降为注意项，不升位）", "撤回该格", "维持现状（接受升位）"],
      "requested_by": "项目所有者 2026-09-17"
    }
  ],
  "review_status": "pending",
  "note": "写入 ≠ 审核通过，界面照旧标「待验证」。evidence → unsuitable_for（硬屏蔽）；inference → 允许 cautions / suitable_constitutions（软通道）。该规则由 core/tests/test_safety.py 强制，不靠人记"
}
```

> `cells` 是**唯一事实源**：§2.2 的豁免登记就是从它里面筛出来的（`field != "unsuitable_for"`），
> 不再单独维护第二份名单。

### 3.3 山楂×气郁 的 `priority_review`（对应本次裁决的第 5 条）

上面 `priority_review` 里那一条即本次裁决的落点：**先按现状写入，但把「升位过强」这个疑虑写进数据**，
让 nanple 复核时第一眼就看到。同时在 `docs/pending-items.md` B3 里加一句（清单是唯一真源，不能只藏在数据里）。

---

## 4. 预期影响（已实测，不是推断）

### 4.1 候选集变化

| 体质 | 池大小 | 变化 | 变化明细 |
|---|---|---|---|
| 阴虚 `yin_deficiency` | 24 → **23** | 少 1 味 | 香薷被硬屏蔽。**前 12 条不变**（香薷 catalog 下标 32，本就在截断线外） |
| 气郁 `qi_stagnation` | 33 → 33 | 不变 | `suitable` 由 `红枣、薄荷` 变为 **`山楂、红枣、薄荷`** |
| 血瘀 `blood_stasis` | 33 → 33 | 不变 | 山楂本就在 `suitable` 首位 |
| 其余 6 型 | 不变 | — | — |

⚠️ **阴虚只看 top12 看不出这次改动**（香薷排在 32 位）—— 与上一批同样的陷阱，
验收必须用大 `limit` 取全池。

### 4.2 山楂×气郁 升位的连带效应

1. **升位到第一位**（`filter_by_constitution` 的排序是 `suitable（按 catalog 顺序）+ neutral_fallback`）
   → 已按裁决写进 `priority_review`，请 nanple 优先看。
2. **与项目自有文档存在方向张力（但不是直接冲突）**：`constitution.json` 的 `qi_stagnation`
   里 `principles` 有「少食酸涩收敛之物」、`avoid` 列「石榴、乌梅、柿子」，而 `direction`
   点名的宜用是「橙子、白萝卜、薄荷」——**未点名山楂**。附带文案 B 正是解释这处偏离。
3. **不影响闸门**：`ready_constitutions()` 与 `/api/constitutions` 均不变（气郁早已就绪）。

### 4.3 cautions 新增条款的实际可见性（知情项）

`cautions` 的真实出口有两个（**不是**项目文档写的「只进 Agent2 提示词」）：

- `matcher.py:257` 兜底路径的 `Recommendation.cautions` —— **只取每味第 1 条**，所以**追加末尾的新条款在兜底路径下看不到**；
- `safety.check_blend` 把每条 caution 转 warning → `Basis.guardrail_applied`（进 API 响应）—— **全部可见**。

按裁决「追加末尾」，含义是：新条款不会挤掉硬安全提示（荷叶的「气血偏虚」、山楂的「胃酸过多」保住了首位），
代价是兜底路径看不到它。另注：「（推断，未经人工审核）」这类内部审核语汇会出现在 `guardrail_applied` 里，
使**用户可见** —— 这是裁决 2「文案内 + `_meta` 结构化」的已知代价，可接受（与 A1「界面标待验证」口径一致）。

### 4.4 测试预期

| 项 | 预期 |
|---|---|
| `pytest -q` | **382 → 384 passed**（现有 1 条改写 + 新增 2 条：负控制、批次块格式检查） |
| 现有会变红的测试 | 仅 `test_cautions_naming_yinxu_must_be_blocked`（已实测：写入后 `escaped == ['heye','shanzha']`），随本次改写解决 |
| 其它测试 | 无池大小 / 无 4 味 id 的硬编码断言（已 grep 确认）；`test_yinxu_cautions_batch_is_blocked_at_runtime` 不受影响 |

---

## 5. 连带需要同步的既有记录

### 5.1 `core/data/herbs.json`

见 §3.1、§3.2。

### 5.2 `docs/herbs-cautions-yinxu-batch.md`

| 位置 | 现有内容 | 改成 |
|---|---|---|
| 执行结果（§「先读这一节」，第 14 行） | 「**刻意没写**：荷叶、香薷（见 §2，依据属外推，已登记为待 nanple）」 | 「**后续（2026-09-17）**：荷叶、香薷两味已由外部专业意见裁决 —— 香薷走硬屏蔽（`evidence`，补 cautions「阴虚有热者禁用」），荷叶走 `cautions`（`inference`，登记豁免）。见 `docs/herbs-9types-batch2.md`」 |
| §2 标题与内容 | 「单列：……（**不属于本批口径**，已登记待 nanple）」 | 加一行「**已裁决**：2026-09-17，见 `docs/herbs-9types-batch2.md`」；原推导描述保留（是审计线索） |
| §3.2 守卫测试表 | 只写「要么补 `unsuitable_for`，要么在 docs 里说明为何不写」 | 补一句：第二条出口已于 2026-09-17 落成代码（`_meta` 的 `rulings` 登记 + 三条约束） |

### 5.3 `docs/herbs-9types-draft.md`

| 位置 | 改动 |
|---|---|
| 文首「执行结果」宜/忌表 | 阴虚行加「忌：香薷」；气郁行加「宜：山楂」；表下补第二批说明（5 格已裁定 + `priority_review`） |
| 文首「没写入的部分」段（第 23–25 行） | 原文说「§6.4 的『山楂×阴虚』……待专业复核后另批写入」→ 改为「已于 2026-09-17 另批写入，见 `docs/herbs-9types-batch2.md`」 |
| §4 主表 5 格 | 山楂 阴虚 `？`→`△`；山楂 气郁 `？`→`✓`；荷叶 阴虚 `✗`→`△`；香薷 阴虚 `✗`（符号不变，依据列注明「已写入」）；槐花 血瘀 `？`→`△`。依据列同步补一句批次出处 |
| §4 汇总表（阴虚行） | `✓5 / ✗12 / △6 / ？11` → `✓5 / ✗11 / △8 / ？10`（荷叶 ✗→△、山楂 ？→△） |
| §4 汇总表（气郁/血瘀/特禀行） | 气郁 宜 4 → 5（+山楂）；其余不变 |
| §6.2 / §6.4 相关段 | 「山楂×阴虚」由待判断改为已裁定（`△`，cautions）；§6.2 三选一的描述补「已按最保守口径执行」 |
| 文末「未修改 herbs.json → 已按严格 evidence 口径写入 10 格」 | 补第二批（4 味 5 格） |

> 附注：本文档第 1 行标着「**草稿，未入库**」，但 `git ls-files` 显示它**已在库里**、且被
> `pending-items.md` 等引用 —— 表头那句已过期。本次顺手改正为「草稿 → 已部分落地」。

### 5.4 ⚠️ 附加更正（**超出你说的「两处」**，请一并点头）

`docs/herbs-cautions-yinxu-batch.md` §0 与 `herbs.json` 的 `_meta.cautions_batch.why` 都写着
**「`cautions` 只进 Agent2 的提示词」**。代码里不是这样（真实出口见 §4.3）。

方向性结论不变（`cautions` 仍远比 `unsuitable_for` 软），但这句是**错的**，会让后来者低估 cautions 的影响面。
建议连同本批一起改成准确描述。若你希望留到下轮单独处理，我就只记录不改。

### 5.5 `docs/pending-items.md`

| 位置 | 改动 |
|---|---|
| B3 概览行 | 状态仍为「已部分解决」；事项描述补「余 239 格」（244 − 5） |
| B3「现状」 | 补第二批：4 味 5 格已按外部专业意见写入（3 格 cautions 软通道 / 1 格硬屏蔽 / 1 格升位） |
| B3「需要什么」 | 删掉「5 处已单列待确认」整句，改为「5 处已于 2026-09-17 裁定并写入（见 `docs/herbs-9types-batch2.md`）；其中**山楂×气郁 升位过强**请优先复核」 |
| B3「附注」 | 补第二批：香薷×阴虚（忌，evidence）、荷叶×阴虚（慎用，inference）、山楂×阴虚（慎用，inference）、山楂×气郁（宜，inference）、槐花×血瘀（慎用，inference，低置信） |

---

## 6. 文件清单

### 会改动

| 文件 | 改动 |
|---|---|
| `core/data/herbs.json` | 4 条条目 + `_meta`（新增 `rulings`、作废 `excluded`、`0.3.0`→`0.4.0`） |
| `core/tests/test_safety.py` | 豁免出口（三条约束）+ 纯函数 + 负控制 + 批次块格式检查 |
| `docs/herbs-cautions-yinxu-batch.md` | §执行结果 / §2 / §3.2（+ §0，若 §5.4 获准） |
| `docs/herbs-9types-draft.md` | 文首执行结果 / §4 主表与汇总表 / §6 相关段 / 文末 |
| `docs/pending-items.md` | B3 四处 |
| `docs/herbs-9types-batch2.md` | **新建**：本批记录（体例仿 `herbs-cautions-yinxu-batch.md`） |
| `docs/herbs-9types-batch2-confirm.md` | 本文件，确认后转「已执行」 |

### 不动

`food_properties.json`、`constitution.json`、`constitution-9-types.json`、`herb_nature_reference.json`
（四气/五味/归经均未动 → `build_herb_crosscheck.py` 无需 refresh）、`catalog-compliance.md`
（饮片名未动 → `check_herb_catalog.py` 无需重跑）。

`.gitignore` **无需改动**：`docs/herbs-9types-batch2-confirm.md` 实测未被忽略
（已核对 `git check-ignore`），`git add` 直接生效。

---

## 7. 执行顺序（确认后照此走）

1. **落地测试出口**：改 `core/tests/test_safety.py`（抽纯函数 + 改写正向测试 + 2 条新测试）
   —— 先让它在**旧数据**上通过（豁免表此时为空，所以旧数据本就没问题）。
2. **写 `herbs.json`**：文本级精确替换（4 条条目 + `_meta`），改完立刻 `json.load` 校验一次
   （上一批踩过「替换 `note` 行时把闭合大括号一起替掉」的坑）。
3. **跑测试**：预期只剩 `test_cautions_naming_yinxu_must_be_blocked` 需要靠新登记放行 —— 若它仍红，
   说明登记没读对（不要改测试去迁就数据）。同时确认 `pytest -q` 全绿。
4. **同步 4 份既有文档**（§5.2–§5.5），并新建批次记录 `docs/herbs-9types-batch2.md`。
5. **自检**：`pytest -q` 全绿 → `smoke_offline.py` 全过 → `git status` 干净 → 无敏感文件被误加
   → 实测复核（阴虚池 23、气郁 suitable 首位为山楂）。
6. **commit + push**，然后回报 commit hash / 改动文件 / 测试结果 / 留待 nanple 的项。

---

## 8. 需要你点头的（最后一批）

| # | 事项 | 状态 |
|---|---|---|
| 1 | 最终写入清单（§1） | ✅ 已执行（2026-09-17） |
| 2 | 豁免出口实现方案（§2，登记表落在 `_meta.constitution_extension.rulings`，三条约束 + 负控制） | ✅ 已落地并测试通过 |
| 3 | 登记块命名用中性的 `rulings`（而非 `nanple_batch`） | ✅ 已采纳 |
| 4 | §5.4 的**附加更正**（`cautions` 出口的表述）是否一并改 | ✅ 已一并更正（`herbs.json` 的 `why` + `herbs-cautions-yinxu-batch.md` §0） |
