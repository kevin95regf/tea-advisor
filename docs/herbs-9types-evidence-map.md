# 34 味 × 9 型体质宜忌判定：逐格依据与 `_constitution_evidence` 影子字段映射

> 生成日期：2026-09-20　依据：`docs/herbs-9types-questions.md` §1 契约　状态：**外部评审答复稿，未改 `herbs.json`**
> 配套文件：`herbs-9types-evidence.jsonl`（136 格，契约内四型）、`herbs-9types-evidence-ext.jsonl`（85 格，湿热/平和/五型修订）、
> `herbs-9types-evidence-shadow.json`（影子字段，可直接被回填脚本消费）

---

## §0 判定口径（本轮确立，后续 89 格可直接复用）

### 0.1 三档依据分层

契约 §1.3 只有 `evidence / inference / no_basis` 三值，但「有依据」内部强度不同。本轮加一个**附加字段 `tier`** 把强度记下来，`basis` 取值不变：

| tier | 含义 | 例 | 计入 basis |
|---|---|---|---|
| **E** | 体质学资料**直接点名该饮片**适用于/不适用于该体质 | 《中医养生学》:2285 阴虚质点名「桑椹粥」 | `evidence` |
| **E′** | 教材**点名该饮片的同向证候**，且该证候 ⊂ 该体质的定义特征 | 七版:649 生姜「阴虚内热者忌服」 | `evidence` |
| **I** | 由性味功效、同类药、配方用法**外推** | 麦冬养阴生津→阴虚 | `inference` |
| **X** | 沿用项目既有外部来源（粤中医），本轮未独立复核 | 34 味的湿热列 | `evidence`（带标记） |
| **-** | 无依据 | — | `no_basis` |

> ⚠️ **`tier` 在 JSONL 里存的是 ASCII 的 `E'`**（避免非 ASCII 引号给下游解析添麻烦），本文档为了好读写作 `E′`。两者是同一个值。

**E′ 的边界（这是全案最容易放松的一环）**：判定标准是「教材说的那句话，是否**直接描述该饮片的性味功效或使用注意**，且方向与该体质一致」。

- ✅ 生姜「**本品助火伤阴**，故热盛及阴虚内热者忌服」（七版:649）——功效句 + 使用注意句，直接讲阴。
- ✅ 酸枣仁「**能养心阴**」「**敛阴生津止渴**…治伤津口渴咽干」（七版:7780、7782）——功效句直接讲阴。
- ❌ **山楂**「山楂伍芍药、甘草酸甘化阴」（《中医内科学》:2588）——在**配方**里当配角治**病证**（胃痞阴虚型），不是讲山楂自己的性味功效。**未升为 E′，保留 `caution_only`**。
- ❌ **陈皮**→「柑皮」、《中医养生学》:2347——点名的是柑皮不是陈皮，属同类外推。**降为 I**。
- ❌ **槐花**×血瘀「出血兼瘀滞者不宜单独使用」（七版:5720）→「血瘀质」——是两个集合的跨越，**降为 I**（按 2026-09-17 裁定）。

### 0.2 `caution_only` 的用法

`△` 一律配 `basis: inference`，回填时把 `rationale` 追加进该饮片 `cautions`，**不动两个数组**。
⚠️ `matcher.py:237` 每味只取**第 1 条** caution——追加前须确认不会挤掉原有更重要的条目（如山楂的「胃酸过多、胃溃疡者慎用」必须留在首位）。

### 0.3 三条本轮未采用的判据（刻意留空）

1. **血瘀寒热两途**：寒凉无活血功效的药（菊花、决明子、栀子、淡竹叶、罗汉果、桑椹、百合、麦冬、鱼腥草…）方向相反，一律 `—`。
2. **酸涩不外推**：乌梅是个案（粤中医直接点名）；莲子、酸枣仁、山楂不因味酸涩而判血瘀/气郁忌。
3. **花粉交叉过敏不外推**：花类（菊花、玫瑰花、茉莉花、槐花）对特禀质一律 `—`。《中医饮食营养学》:2243 确有「带鱼古称发物，过敏体质者自应慎用」的体例，但那是**食材发物**，与饮用干花无关。

### 0.4 一处口径差异，请注意

国标九型里的 **平和质** 在本库对应的是《中医养生学》的「正常体质」。该书 :2278 明写：「至于阴阳气血平调的体质……**不必考虑体质问题**」。
因此本轮 **34 味 × 平和质 全部输出 `neutral` + `no_basis`**，并建议清空 `herbs.json` 里 **24 味**的 `balanced` 标注（现分散在 `suitable_constitutions`）。

🔴 **但「清空 `balanced`」会阻断服务，不能按字面执行** —— 见 §6.3。这一条已从「建议」升级为「须先改代码或改判」。count 原写 17，2026-09-20 实测为 **24**（逐味名单见 §6.3）。

---

## §1 统计

### 1.1 契约内四型（136 格）

| verdict \ basis | evidence | inference | no_basis | 合计 |
|---|---|---|---|---|
| suitable（宜） | 14 | 8 | 0 | **22** |
| unsuitable（忌） | 9 | 8 | 0 | **17** |
| caution_only（注意） | 0 | 6 | 0 | **6** |
| neutral（中性） | 0 | 0 | 91 | **91** |
| **合计** | **23** | **22** | **91** | **136** |

tier 分布：— **91**、E **16**、E' **7**、I **22**

### 1.2 分型

| 体质 | 宜 | 忌 | 注意项 △ | 中性/待判 | 与项目现状的差异 |
|---|---|---|---|---|---|
| 阴虚 | 7 | 13 | 6 | 8 | 新增 2 宜（山药由 △ 升为宜、酸枣仁由 ? 升为宜）；另有 6 格由 inference 升为 evidence（陈皮/生姜/薄荷/薏苡仁/槐花/藿香）；香薷由 evidence 降为 inference |
| 血瘀 | 4 | 2 | 0 | 28 | 新增 1 宜（玫瑰花 I）；槐花×血瘀按裁定降为 inference 级不宜 |
| 气郁 | 9 | 1 | 0 | 24 | 新增 6 宜（陈皮、玫瑰花、茉莉花、橘红、紫苏 I 级；佛手 E 级；薄荷升级为 evidence） |
| 特禀 | 2 | 1 | 0 | 31 | 维持 2 宜（红枣、山药）；新增 1 忌（酸枣仁） |

### 1.3 扩展层（85 格，`herbs-9types-evidence-ext.jsonl`）

| 体质 | 格数 | 说明 |
|---|---|---|
| 湿热 damp_heat | 34 | 14 宜 / 12 忌 沿用项目现有值（粤中医）；8 中性；生姜 1 格另以 E′ 重出 |
| 平和 balanced | 34 | 全部 neutral + no_basis（见 §0.4） |
| 气虚/阳虚/痰湿 | 17 | 本轮新补依据的格子（4 宜补依据 + 1 宜新增 + 1 改向 + 11 忌补依据/新增） |

---

## §2 四型速查矩阵

图例：`✓`宜 / `✗`忌 / `△`注意项（进 cautions，不进数组）/ `—`中性（no_basis）
后缀：`E` 资料点名 · `E′` 同向证候点名 · `I` 推断 · `*` 外部来源（粤中医）

| # | 饮片 | 阴虚 | 血瘀 | 气郁 | 特禀 |
|---|---|---|---|---|---|
| 1 | 茯苓 | ✗I | — | — | — |
| 2 | 陈皮 | ✗E′ | — | ✓I | — |
| 3 | 山楂 | △ | ✓E | ✓I | — |
| 4 | 枸杞子 | ✓E | — | — | — |
| 5 | 菊花 | △ | — | — | — |
| 6 | 玫瑰花 | △ | ✓I | ✓I | — |
| 7 | 红枣 | △ | ✓E* | ✓E* | ✓E* |
| 8 | 龙眼肉 | ✗I | — | — | — |
| 9 | 麦冬 | ✓E | — | — | — |
| 10 | 荷叶 | △ | — | — | — |
| 11 | 决明子 | — | — | — | — |
| 12 | 生姜 | ✗E′ | ✓E* | — | — |
| 13 | 薄荷 | ✗E′ | — | ✓E | — |
| 14 | 桑椹 | ✓E | — | — | — |
| 15 | 百合 | ✓E | — | — | — |
| 16 | 莲子 | — | — | — | — |
| 17 | 薏苡仁 | ✗E′ | — | — | — |
| 18 | 乌梅 | — | ✗E* | ✗E* | — |
| 19 | 罗汉果 | ✓I | — | — | — |
| 20 | 甘草 | — | — | — | — |
| 21 | 茉莉花 | ✗I | — | ✓I | — |
| 22 | 淡竹叶 | △ | — | — | — |
| 23 | 栀子 | — | — | — | — |
| 24 | 酸枣仁 | ✓E′ | — | — | ✗E |
| 25 | 山药 | ✓E | — | — | ✓E* |
| 26 | 鸡内金 | — | — | — | — |
| 27 | 白扁豆 | — | — | — | — |
| 28 | 橘红 | ✗I | — | ✓I | — |
| 29 | 槐花 | ✗E′ | ✗I | — | — |
| 30 | 藿香 | ✗E′ | — | — | — |
| 31 | 紫苏 | ✗I | — | ✓I | — |
| 32 | 佛手 | ✗I | — | ✓E | — |
| 33 | 香薷 | ✗I | — | — | — |
| 34 | 鱼腥草 | — | — | — | — |

---

## §3 逐格依据（映射表主体）

下表每一行 = `herbs-9types-evidence.jsonl` 里的一条记录；`—`（中性）格不列，共 45 条有效判定。

| # | 饮片 | 体质 | verdict | basis | tier | conf | source | rationale |
|---|---|---|---|---|---|---|---|---|
| 1 | 茯苓 | 阴虚 | unsuitable | `inference` | I | medium | — | 甘淡渗利，阴虚津少者久服更伤津液 |
| 2 | 陈皮 | 阴虚 | unsuitable | `evidence` | E′ | medium | 《中医饮食营养学》:1354（橘皮粥条） | 原文「辛散温燥，气虚吐血及阴虚燥咳者不宜食用」 |
| 3 | 陈皮 | 气郁 | suitable | `inference` | I | medium | — | 七版:4835 理气健脾方向相符；:2347 点名「柑皮」，陈皮为橘皮属同类外推 |
| 4 | 山楂 | 阴虚 | caution_only | `inference` | I | medium | — | 酸甘化阴见于配伍层；性微温，维持既有慎用判定 |
| 5 | 山楂 | 血瘀 | suitable | `evidence` | E | high | 《中医养生学》:2330 | 原文「山楂粥、花生粥亦颇相宜」；功效行气散瘀 |
| 6 | 山楂 | 气郁 | suitable | `inference` | I | medium | — | 行气散瘀方向相符；功效含行气而非解郁专药 |
| 7 | 枸杞子 | 阴虚 | suitable | `evidence` | E | high | 《中医养生学》:2285、2287 | 阴虚质饮食调养点名「枸杞粥」，药物养生点名枸杞子 |
| 8 | 菊花 | 阴虚 | caution_only | `inference` | I | low | — | 微寒非滋润，不清不补，作注意项 |
| 9 | 玫瑰花 | 阴虚 | caution_only | `inference` | I | low | — | 性温，阴虚者不宜过量；七版无使用注意 |
| 10 | 玫瑰花 | 血瘀 | suitable | `inference` | I | medium | — | 七版:5131 功效活血止痛，方向与血瘀相符 |
| 11 | 玫瑰花 | 气郁 | suitable | `inference` | I | medium | — | 七版:5131 疏肝解郁，方向与气郁相符 |
| 12 | 红枣 | 阴虚 | caution_only | `inference` | I | low | — | 甘温偏补，阴虚有虚火者不宜过量 |
| 13 | 红枣 | 血瘀 | suitable | `evidence` | E | medium | 粤中医（外部来源，非本库） | 项目转引：粤中医点名大枣；《中医养生学》:2338 亦见 |
| 14 | 红枣 | 气郁 | suitable | `evidence` | E | medium | 粤中医（外部来源，非本库） | 项目转引：粤中医点名大枣 |
| 15 | 红枣 | 特禀 | suitable | `evidence` | E | medium | 粤中医（外部来源，非本库） | 项目转引：粤中医点名大枣 |
| 16 | 龙眼肉 | 阴虚 | unsuitable | `inference` | I | medium | — | 甘温易上火、口干舌燥者慎用（项目 cautions） |
| 17 | 麦冬 | 阴虚 | suitable | `evidence` | E | high | 《中医养生学》:2287；《中药学》七版:9431 | 药物养生点名「麦门冬」；教材功效养阴生津 |
| 18 | 荷叶 | 阴虚 | caution_only | `inference` | I | medium | — | 淡渗利水，阴虚多体瘦；已登记软通道豁免 |
| 19 | 生姜 | 阴虚 | unsuitable | `evidence` | E′ | high | 《中药学》七版:649；《中医饮食营养学》:344 | 原文「本品助火伤阴…阴虚内热者忌服」/「阴虚内热…忌服」 |
| 20 | 生姜 | 血瘀 | suitable | `evidence` | E | medium | 粤中医（外部来源，非本库） | 项目转引：粤中医点名生姜 |
| 21 | 薄荷 | 阴虚 | unsuitable | `evidence` | E′ | high | 《中医饮食营养学》:422 | 原文「有表虚自汗及阴虚血燥者不宜食用」 |
| 22 | 薄荷 | 气郁 | suitable | `evidence` | E | high | 《中医饮食营养学》:424 | 原文「适于…肝郁气滞体质者食用…亦可煎汤代茶饮」 |
| 23 | 桑椹 | 阴虚 | suitable | `evidence` | E | high | 《中医养生学》:2285、2287 | 阴虚质饮食调养点名「桑椹粥」，药物养生点名桑椹 |
| 24 | 百合 | 阴虚 | suitable | `evidence` | E | high | 《中医养生学》:2285 | 阴虚质饮食调养点名「百合粥」 |
| 25 | 薏苡仁 | 阴虚 | unsuitable | `evidence` | E′ | high | 《中药学》七版:3989 | 原文「津液不足者慎用」 |
| 26 | 乌梅 | 血瘀 | unsuitable | `evidence` | E | medium | 粤中医（外部来源，非本库） | 项目转引：粤中医明确列为血瘀质应少吃 |
| 27 | 乌梅 | 气郁 | unsuitable | `evidence` | E | medium | 粤中医（外部来源，非本库） | 项目转引：粤中医明确列为气郁质应少吃 |
| 28 | 罗汉果 | 阴虚 | suitable | `inference` | I | medium | — | 甘凉润肺生津，方向与阴虚相符；无直接点名 |
| 29 | 茉莉花 | 阴虚 | unsuitable | `inference` | I | medium | — | 性偏温，口干者减量（项目 cautions）；七版无条目 |
| 30 | 茉莉花 | 气郁 | suitable | `inference` | I | medium | — | 功效理气开郁方向相符；药典与七版均未收载 |
| 31 | 淡竹叶 | 阴虚 | caution_only | `inference` | I | low | — | 利尿通淋与阴虚津少相悖，作注意项 |
| 32 | 酸枣仁 | 阴虚 | suitable | `evidence` | E′ | medium | 《中药学》七版:7780、7782 | 原文「能养心阴」「敛阴生津止渴…治伤津口渴咽干」 |
| 33 | 酸枣仁 | 特禀 | unsuitable | `evidence` | E | medium | 《中药学》七版:7792 | 原文「煎服酸枣仁偶可发生过敏反应」 |
| 34 | 山药 | 阴虚 | suitable | `evidence` | E | high | 《中医养生学》:2285 | 阴虚质饮食调养点名「山药粥」 |
| 35 | 山药 | 特禀 | suitable | `evidence` | E | medium | 粤中医（外部来源，非本库） | 项目转引：粤中医点名山药 |
| 36 | 橘红 | 阴虚 | unsuitable | `inference` | I | medium | — | 性偏温燥，阴虚口干者不宜（项目 cautions） |
| 37 | 橘红 | 气郁 | suitable | `inference` | I | medium | — | 功效理气宽中方向相符；药典收载，七版无正文条目 |
| 38 | 槐花 | 阴虚 | unsuitable | `evidence` | E′ | medium | 《中药学》七版:5790 | 原文「脾胃虚寒及阴虚发热而无实火者慎用」 |
| 39 | 槐花 | 血瘀 | unsuitable | `inference` | I | medium | — | 凉血止血类有止血留瘀之弊，从「出血兼瘀滞」外推至血瘀质（七版:5720） |
| 40 | 藿香 | 阴虚 | unsuitable | `evidence` | E′ | high | 《中药学》七版:3780 | 原文「阴虚血燥者不宜用」 |
| 41 | 紫苏 | 阴虚 | unsuitable | `inference` | I | medium | — | 性温，项目 cautions 明写阴虚内热不宜；七版无使用注意 |
| 42 | 紫苏 | 气郁 | suitable | `inference` | I | medium | — | 七版:620 功效行气宽中，方向相符 |
| 43 | 佛手 | 阴虚 | unsuitable | `inference` | I | medium | — | 性温，项目 cautions 明写阴虚火旺不宜；七版无使用注意 |
| 44 | 佛手 | 气郁 | suitable | `evidence` | E | high | 《中医养生学》:2347 | 气郁质饮食调养点名「佛手」 |
| 45 | 香薷 | 阴虚 | unsuitable | `inference` | I | medium | — | 七版:671 仅记表虚有汗与暑热证，未及阴虚；依据为外部专业意见 |

---

## §4 `_constitution_evidence` 影子字段

### 4.1 格式（在契约 §1.5 示例上加了 `verdict` 与 `tier` 两个键）

```json
"_constitution_evidence": {
  "yin_deficiency": {
    "verdict": "unsuitable", "basis": "evidence", "tier": "E'",
    "source": "《中药学》七版:649", "reviewed_by": "<署名/资质>", "reviewed_at": "2026-09-20"
  }
}
```

- 只收录**会落到三个出口**的格子（`suitable_constitutions` / `unsuitable_for` / `cautions`）；`neutral` 格不进（它不写任何东西）。
- `tier` 让「哪一格走过 E′ 的口径松动」可被机器筛出来——这正是契约 §1.5 想让审计闭环的地方。
- 完整对象见 `herbs-9types-evidence-shadow.json`（33 味有非中性格）。

### 4.2 映射表（按饮片）

| 饮片 | 体质 | verdict | basis | tier | source |
|---|---|---|---|---|---|
| 茯苓 | 阴虚 | unsuitable | `inference` | I | — |
|  | 阳虚 | unsuitable | `evidence` | E' | 《中药学》七版:3965 |
| 陈皮 | 阴虚 | unsuitable | `evidence` | E' | 《中医饮食营养学》:1354（橘皮粥条） |
|  | 气郁 | suitable | `inference` | I | — |
|  | 湿热 | unsuitable | `evidence` | X | 粤中医（外部来源，非本库） |
| 山楂 | 阴虚 | caution_only | `inference` | I | — |
|  | 血瘀 | suitable | `evidence` | E | 《中医养生学》:2330 |
|  | 气郁 | suitable | `inference` | I | — |
|  | 气虚 | unsuitable | `evidence` | E' | 《中药学》七版:5347 |
| 枸杞子 | 阴虚 | suitable | `evidence` | E | 《中医养生学》:2285、2287 |
|  | 湿热 | unsuitable | `evidence` | X | 粤中医（外部来源，非本库） |
| 菊花 | 阴虚 | caution_only | `inference` | I | — |
|  | 湿热 | suitable | `evidence` | X | 粤中医（外部来源，非本库） |
| 玫瑰花 | 阴虚 | caution_only | `inference` | I | — |
|  | 血瘀 | suitable | `inference` | I | — |
|  | 气郁 | suitable | `inference` | I | — |
| 红枣 | 阴虚 | caution_only | `inference` | I | — |
|  | 血瘀 | suitable | `evidence` | E | 粤中医（外部来源，非本库） |
|  | 气郁 | suitable | `evidence` | E | 粤中医（外部来源，非本库） |
|  | 特禀 | suitable | `evidence` | E | 粤中医（外部来源，非本库） |
|  | 湿热 | unsuitable | `evidence` | X | 粤中医（外部来源，非本库） |
|  | 气虚 | suitable | `evidence` | E | 《中医养生学》:2307 |
|  | 痰湿 | suitable | `evidence` | E | 《中医养生学》:2338 |
| 龙眼肉 | 阴虚 | unsuitable | `inference` | I | — |
|  | 湿热 | unsuitable | `evidence` | X | 粤中医（外部来源，非本库） |
|  | 痰湿 | unsuitable | `evidence` | E' | 《中药学》七版:9335；《中医饮食营养学》:2154 |
| 麦冬 | 阴虚 | suitable | `evidence` | E | 《中医养生学》:2287；《中药学》七版:9431 |
|  | 湿热 | suitable | `evidence` | X | 粤中医（外部来源，非本库） |
| 荷叶 | 阴虚 | caution_only | `inference` | I | — |
|  | 湿热 | suitable | `evidence` | X | 粤中医（外部来源，非本库） |
| 决明子 | 湿热 | suitable | `evidence` | X | 粤中医（外部来源，非本库） |
|  | 气虚 | unsuitable | `evidence` | E' | 《中药学》七版:1427 |
| 生姜 | 阴虚 | unsuitable | `evidence` | E' | 《中药学》七版:649；《中医饮食营养学》:344 |
|  | 血瘀 | suitable | `evidence` | E | 粤中医（外部来源，非本库） |
|  | 湿热 | unsuitable | `evidence` | E' | 《中药学》七版:649 |
| 薄荷 | 阴虚 | unsuitable | `evidence` | E' | 《中医饮食营养学》:422 |
|  | 气郁 | suitable | `evidence` | E | 《中医饮食营养学》:424 |
|  | 湿热 | suitable | `evidence` | X | 粤中医（外部来源，非本库） |
|  | 气虚 | unsuitable | `evidence` | E' | 《中药学》七版:941 |
| 桑椹 | 阴虚 | suitable | `evidence` | E | 《中医养生学》:2285、2287 |
|  | 湿热 | suitable | `evidence` | X | 粤中医（外部来源，非本库） |
| 百合 | 阴虚 | suitable | `evidence` | E | 《中医养生学》:2285 |
|  | 湿热 | suitable | `evidence` | X | 粤中医（外部来源，非本库） |
| 莲子 | — | — | — | — | （无有效判定格） |
| 薏苡仁 | 阴虚 | unsuitable | `evidence` | E' | 《中药学》七版:3989 |
|  | 湿热 | suitable | `evidence` | X | 粤中医（外部来源，非本库） |
|  | 痰湿 | suitable | `evidence` | E | 《中医养生学》:2338 |
| 乌梅 | 血瘀 | unsuitable | `evidence` | E | 粤中医（外部来源，非本库） |
|  | 气郁 | unsuitable | `evidence` | E | 粤中医（外部来源，非本库） |
|  | 湿热 | suitable | `evidence` | X | 粤中医（外部来源，非本库） |
| 罗汉果 | 阴虚 | suitable | `inference` | I | — |
|  | 湿热 | suitable | `evidence` | X | 粤中医（外部来源，非本库） |
| 甘草 | 痰湿 | unsuitable | `evidence` | E' | 《中药学》七版:8595 |
| 茉莉花 | 阴虚 | unsuitable | `inference` | I | — |
|  | 气郁 | suitable | `inference` | I | — |
|  | 湿热 | unsuitable | `evidence` | X | 粤中医（外部来源，非本库） |
| 淡竹叶 | 阴虚 | caution_only | `inference` | I | — |
|  | 湿热 | suitable | `evidence` | X | 粤中医（外部来源，非本库） |
| 栀子 | 湿热 | suitable | `evidence` | X | 粤中医（外部来源，非本库） |
|  | 气虚 | unsuitable | `evidence` | E' | 《中药学》七版:1385 |
| 酸枣仁 | 阴虚 | suitable | `evidence` | E' | 《中药学》七版:7780、7782 |
|  | 特禀 | unsuitable | `evidence` | E | 《中药学》七版:7792 |
|  | 湿热 | unsuitable | `evidence` | X | 粤中医（外部来源，非本库） |
| 山药 | 阴虚 | suitable | `evidence` | E | 《中医养生学》:2285 |
|  | 特禀 | suitable | `evidence` | E | 粤中医（外部来源，非本库） |
|  | 气虚 | suitable | `evidence` | E | 《中医养生学》:2307 |
| 鸡内金 | 气虚 | suitable | `evidence` | E' | 《中医饮食营养学》:1152 |
| 白扁豆 | 痰湿 | suitable | `evidence` | E | 《中医养生学》:2338 |
| 橘红 | 阴虚 | unsuitable | `inference` | I | — |
|  | 气郁 | suitable | `inference` | I | — |
|  | 湿热 | unsuitable | `evidence` | X | 粤中医（外部来源，非本库） |
| 槐花 | 阴虚 | unsuitable | `evidence` | E' | 《中药学》七版:5790 |
|  | 血瘀 | unsuitable | `inference` | I | — |
|  | 湿热 | suitable | `evidence` | X | 粤中医（外部来源，非本库） |
|  | 阳虚 | unsuitable | `evidence` | E' | 《中药学》七版:5790 |
| 藿香 | 阴虚 | unsuitable | `evidence` | E' | 《中药学》七版:3780 |
|  | 湿热 | unsuitable | `evidence` | X | 粤中医（外部来源，非本库） |
| 紫苏 | 阴虚 | unsuitable | `inference` | I | — |
|  | 气郁 | suitable | `inference` | I | — |
|  | 湿热 | unsuitable | `evidence` | X | 粤中医（外部来源，非本库） |
|  | 气虚 | unsuitable | `evidence` | E' | 《中医饮食营养学》:332 |
| 佛手 | 阴虚 | unsuitable | `inference` | I | — |
|  | 气郁 | suitable | `evidence` | E | 《中医养生学》:2347 |
|  | 湿热 | unsuitable | `evidence` | X | 粤中医（外部来源，非本库） |
| 香薷 | 阴虚 | unsuitable | `inference` | I | — |
|  | 湿热 | unsuitable | `evidence` | X | 粤中医（外部来源，非本库） |
|  | 气虚 | unsuitable | `evidence` | E' | 《中药学》七版:671 |
| 鱼腥草 | 湿热 | suitable | `evidence` | X | 粤中医（外部来源，非本库） |
|  | 阳虚 | unsuitable | `evidence` | E' | 《中药学》七版:2022 |

---

## §5 须裁决的变更与冲突（**回填前逐条拍板**）

### 5.0 裁定台账（2026-09-20 更新）

> 原列 6 项（5.1 / 5.2 / 5.3 / 5.4 / 5.5 / 5.10）。经项目所有者裁定，**其中 4 项已关闭**；另发现 **§5.6 麦冬**一格同样带决策（升级 + 升位），故**待拍板共 3 项**。

| # | 格子 | 建议 | 回填动作 | 状态 |
|---|---|---|---|---|
| 5.1 | 山楂 × 阴虚 | `caution_only` | **零字段变更**（已由 `rulings.cells` 登记） | ✅ 已裁定：维持 caution_only |
| 5.2 | 红枣 × 痰湿 | `caution_only`（两教材冲突，不选边） | 从 `unsuitable_for` **移出** `phlegm_damp` | ✅ 已裁定：改判 caution_only |
| 5.3 | 香薷 × 阴虚 | 降 `level` → `inference` | **字段不动**（仍留 `unsuitable_for`） | ✅ 已裁定：降为 I |
| 5.4 | 酸枣仁 × 阴虚 | `suitable` / `E′` | **新增** `suitable_constitutions`（阴虚第 3 位） | ⏳ **待拍板** |
| 5.5 | 山药 × 阴虚 | `suitable` / `E` | **新增** `suitable_constitutions`（阴虚第 4 位） | ✅ 已裁定：填上 |
| 5.6 | 麦冬 × 阴虚 | `suitable` / `E` | **新增** `suitable_constitutions`（**阴虚第 1 位**） | ⏳ **待拍板**（升级 + 升位） |
| 5.10 | 紫苏 × 气虚 | `unsuitable` / `E′` | **新增硬屏蔽** `unsuitable_for` | 🔴 **待单独确认** |

**另有非 §5 项、但决定回填能否进行的一项：**
- 🔴 **`balanced` 清空会阻断服务**（详见 §6.3）—— 需在 ① 不清空 / ② 清空+改代码 / ③ 留 1 味兜底 中选一。**这一项不解决，回填不能开工。**

### 5.1 山楂 × 阴虚 —— 我把方案表里的 ✓E 回调了

上轮方案表这一格我标的是 `✓E`。交付时改为 **`caution_only` / `inference`（维持项目现状）**，理由：

唯一支撑是《中医内科学》:2588「山楂伍芍药、甘草酸甘化阴」（治胃痞**阴虚型**）与 :2590「生山楂…润胃敛阴」。
但那是**配方**里的配角、治的是**病证**、用的是**大剂量**——不满足 §0.1 里 E′ 的判定标准（该饮片自己的性味功效或使用注意直接讲阴）。
另外山楂 catalog 下标是 **2**，一旦写入 `suitable_constitutions` 会跃居阴虚候选首位，与你已登记的 `priority_review`（山楂×气郁升位过强）是同一个问题。

**若要按方案表执行**：把该行 `verdict` 改 `suitable`、`basis` 改 `evidence`、`tier` 改 `E'`、`source` 填 `《中医内科学》:2588、2590`，并**同时补一条 `priority_review`**。

**另有一条反向证据支持维持现状**：《中医饮食营养学》**:1132**（山楂条【使用注意】）「凡脾虚胃弱无积滞、气虚便溏者，慎用。**生食大量山楂后，令人嘈杂易饥**。」
「嘈杂易饥」正是胃阴虚/虚火的典型表现——教材把「大量生山楂」直接与这个反应绑定，方向上不利于「阴虚宜」。**两条证据互抵，维持 `caution_only` 更稳。**

### 5.2 红枣 × 痰湿 —— 教材「宜」vs 饮食物「忌」，已判 `caution_only` ✅

**原方案（已被下方 2026-09-20 裁定取代，保留供追溯）**：《中医养生学》:2338 痰湿质饮食调理**点名「大枣」宜** → 从 `unsuitable_for` 移出 `phlegm_damp`、并**加入 `suitable_constitutions`**。

⚠️ 但红枣 `cautions` 第 1 条正是「**湿盛腹胀、痰湿偏重者不宜多食**」——改向会让**数据说宜、文案说忌**，直接矛盾。
三种收尾方式，请选一：① 同时改写 cautions 第 1 条（则原有气泡提示消失）；② 保留 cautions，接受错位（用户会同时看到「推荐」与「不宜多食」）；③ 红枣×痰湿改判 `caution_only`。
**这是全批最需要拍板的一格。**

> ✅ **裁定（2026-09-20，项目所有者）：选 ③ —— 改判 `caution_only`。**
> 理由：两书体例不同、都不算错；取「宜」会造成「数据说宜、文案说忌」的自相矛盾，`caution_only` 两边都不否定。
>
> **回填动作已核实**：只需从 `unsuitable_for` 移出 `phlegm_damp`，**`cautions[0]` 原样保留**（它本来就是 caution_only 的文案，不用改写）。
> 移出后红枣落入 `filter_by_constitution` 的 `neutral_fallback` 分支（实测痰湿 fallback 12 → 13 味），**既不进 `suitable_constitutions`（不会被推为首选）、也不再被硬屏蔽** —— 这正是 `caution_only` 的定义，且与 cautions 无矛盾。

#### 🔴 补一条你可能没料到的反向证据（2026-09-20 交付前新查）

《中医饮食营养学》**:1197**（大枣条【使用注意】）写着：

> 「凡有**湿痰**、积滞、齿病、虫病者，**均不相宜**。」

也就是说 **两本教材在这一格上方向相反**：

| 来源 | 原文 | 方向 |
|---|---|---|
| 《中医养生学》:2338 | 痰湿质饮食调理应多食「白萝卜、荸荠、紫菜…**大枣、扁豆、薏苡仁**…」 | **宜** |
| 《中医饮食营养学》:1197 | 「凡有**湿痰**、积滞…均不相宜」 | **忌** |

两书的**体例不同**，这可能就是分歧来源：`:2338` 是**体质学**的「宜食方向清单」（痰湿质兼见脾虚者，大枣健脾有用）；`:1197` 是**饮食物**的「使用注意」（湿痰已成、积滞未化时不宜）。**前者讲倾向，后者讲禁忌。**

→ **我的建议改为「③ 判 `caution_only`」**：两边都不否定，写进 cautions「痰湿偏重、腹胀者不宜多食」（这句项目 cautions 里本来就有）。这样既吸收了教材 :2338 的点名，又不在两本教材冲突时强行选边。
→ 但这是**你的裁定**，我只把冲突摆出来。若坚持取 :2338「宜」，请同时处理上面 ①②的矛盾。

### 5.3 香薷 × 阴虚 —— 降级（字段不动，只改 level）

`_meta.rulings` 现记 `level: evidence`，但本库语料七版:671 只有「表虚有汗及暑热证当忌用」，**不含阴虚**；当时依据是外部专业意见（不可引用文献）。按你的裁定降为 `inference`。
⚠️ **字段不动**（仍留 `unsuitable_for`，硬屏蔽与方向都不受影响）；规则③只约束软通道，降级不会让 `test_rulings_cells_are_well_formed` 报错。

### 5.4 酸枣仁 × 阴虚 —— 本轮新发现（P1-C 原判「无需标注」）

七版:7780「**能养心阴**，益肝血而有安神之效」、:7782「**敛阴生津止渴**…用治伤津口渴咽干者」→ 判 `suitable` / `E′`。
这会新增一个 `suitable_constitutions` 条目（酸枣仁 catalog 下标 23，升位影响远小于山楂）。**若你认为应保持 P1-C 的「从简确认」，把这行改回 `neutral` / `no_basis` 即可。**

### 5.5 山药 × 阴虚 —— 由 △ 升为宜（你已确认）

《中医养生学》:2285 点名「山药粥」→ 写入 `suitable_constitutions`，**无配套 cautions 需要撤下**。

> ⚠️ **本节 2026-09-20 更正**：原文写「需同时撤下山药 `cautions` 的『阴虚质慎用（推断，未经人工审核）』」——**山药没有这条 caution**，实测山药 `cautions` 只有「湿盛腹胀者不宜多食」「感冒发热期间不宜」两条。
> 那条「阴虚质慎用（推断，未经人工审核）」实际挂在 **山楂 `cautions[3]`** 与 **荷叶 `cautions[2]`** 上；二者已登记在 `_meta.constitution_extension.rulings.cells`（`field: cautions`，`level: inference`），**属正常登记，不要动**。
> 特此更正：本格回填只需加 `suitable_constitutions`，不涉及 cautions 增删。

### 5.6 麦冬 × 阴虚 —— 由 I 升为 E

上轮方案表给的是 `I`（药典功效外推）。本轮在《中医养生学》**:2287「药物养生」**清单里找到「**麦门冬**」**直接点名** → 升为 `E`。
枸杞子、桑椹同在该 :2287 清单内，与 :2285 的食单互相印证。

🔴 **但这一格带来的排位变化比 §5.4 大得多，请注意**（2026-09-20 实测）：阴虚列现状**只有 1 味**在 `suitable_constitutions`（桑椹）。写入山药 / 麦冬 / 酸枣仁三格后，阴虚候选变为 **`麦冬(下标8) → 桑椹(13) → 酸枣仁(23) → 山药(24)`** —— **麦冬直接成为阴虚候选第 1 位**，排在你现有的桑椹之前。这与 `rulings.priority_review` 登记的山楂×气郁属同一类问题（下标靠前的药写入即升位）。麦冬是 `E` 级（教材直接点名），比山楂那格硬，但**是否接受它居首仍须你拍板**（见 §6.5）。

### 5.7 两处引用口径，引的时候别写错

- **薄荷 × 阴虚** 的依据是《中医饮食营养学》**:422**（「阴虚血燥者不宜食用」）。七版:941 只说「体虚多汗者不宜使用」，**是气虚方向，不含阴虚**——不要引成七版。
- **陈皮 × 阴虚** 的依据是《中医饮食营养学》**:1354**，且那条的条目名是**「橘皮粥」（食疗方）**，不是陈皮药材条。引用时保留「橘皮粥条」四字。

### 5.8 湿热 34 格与 `tier: X`

- 8 味（茯苓、山楂、玫瑰花、莲子、甘草、山药、鸡内金、白扁豆）**粤中医清单里没有**，本轮维持中性；其余 26 味沿用现有值。
- 全部标 `tier: X` + source 内注明「外部来源，非本库」。⚠️ **这 26 格不构成本轮 evidence 增量**——只是给已有的 5 型值补上出处标记，**不代表我复核过粤中医原文**。
- **生姜 × 湿热** 是特例：除 X 级外，七版:649「热盛…忌服」可作 E′ 支撑，但「热盛」⊃「湿热」属包含关系非等价，`confidence: low`。是否采纳由你定。

### 5.9 与 2026-09-17 P1-A 答复稿的三处不一致（**以本稿为准**）

| 格子 | P1-A 答复稿 | 本稿 | 原因 |
|---|---|---|---|
| 山楂 × 阴虚 | `suitable` / `evidence` | **`caution_only` / `inference`** | 见 §5.1，配方层证据不足以支撑体质层「宜」 |
| 槐花 × 血瘀 | `unsuitable` / `evidence` | **`unsuitable` / `inference`** | 按 2026-09-19 裁定降级，`source` 置 null |
| 酸枣仁 × 特禀 | `unsuitable` / `evidence`（批次外发现） | 同 | 一致，已正式收进本批 136 格 |

其余 24 格与 P1-A 答复稿一致。

### 5.10 🔴 交付前新查出的一格：紫苏 × 气虚（**新增硬屏蔽**）

《中医饮食营养学》**:332**（紫苏条【使用注意】）「**气虚多汗者不宜食用**；本品芳香，不宜久煮，可冲泡饮或煮汤。」

「气虚多汗」正是气虚质的定义特征（《中医养生学》:2299「常自汗出，动则尤甚」）→ 判 `unsuitable` / `E′`。
⚠️ 紫苏现值 `unsuitable_for = [damp_heat, yin_deficiency]`，**气虚不在其中**——这一格是**新增硬屏蔽**，会让紫苏退出气虚候选集。与其他「支持现有值」的格子性质不同，请单独确认。
（附带收获：同一行的「**可冲泡饮或煮汤**」是紫苏的代茶饮适性依据，与 `whitelist-expansion-scan.md` 相关。）

### 5.11 三条**未采纳**的线索（怕你以后翻不到，留个记录）

| 线索 | 原文 | 为何未采纳 |
|---|---|---|
| 酸枣仁 × 湿热 | 《中医饮食营养学》:2813「养心安神宜熟食；若有**实热郁火**不宜食用」 | 「实热郁火」既非「湿热」也非「气郁化火」的同义词，属跨集合。**保留为候选**，未升格 |
| 山楂 × 气虚（第二源） | 《中医饮食营养学》:1132「脾虚胃弱无积滞、**气虚便溏**者慎用」 | 已采纳，与七版:5347 并列——此处仅记录它同时含「生食大量→嘈杂易饥」，见 §5.1 |
| 山药 泡饮 | 《中医饮食营养学》:1256「**既可以切片煎汁当茶饮**，又可以轧细煮粥喝」 | 不属体质宜忌通道；留给 `whitelist-expansion-scan.md` 的代茶饮适性用 |

---

## §6 回填前必须处理的事（代码与数据）

1. **契约枚举**：`herbs-9types-evidence.jsonl` 只用四型 id，可被现有回填脚本直接消费；`-ext.jsonl` 含 `damp_heat` / `balanced` / 五型 id，**需先确认脚本不校验枚举**（`constitution.json` 已含全部 9 型，`models.Constitution` 亦已扩过）。
2. **`models.HerbEntry` 加 `_constitution_evidence`** —— 属挂起项 **E2**，本轮未做，影子字段交付为独立 JSON 供其消费。
3. 🔴 **`balanced` 清理会动 24 味，且按字面执行会阻断整个服务** —— **本轮最大发现，必须先裁决**：
   原稿写「17 味 + 先跑守卫测试」，2026-09-20 实测：**24 味**含 `balanced`（逐味见下），且守卫测试**已经跑过**（代码级推演，非目测）。
   - `safety.ready_constitutions()` 的判据是「至少 1 味把该体质标进 `suitable_constitutions`」。清空 `balanced` 后这 24 味全部不再标注 → **`balanced` 掉出 `ready_constitutions()`**（实测：现状 9 型全就绪，清空后只剩 8 型）。
   - `orchestrator._constitution_of`（`orchestrator.py:56`）在**请求不带体质时默认 `Constitution.BALANCED`**；`_ensure_constitution_ready`（`:61`）对未就绪体质抛 `CONSTITUTION_NOT_READY`。
   - 二者相接 ⇒ **任何不带 `constitution_override` 的请求都会 500/报错**。`tests/test_constitution_readiness.py:258 test_default_constitution_is_ready` 的 docstring 写死了这条：「**请求不带体质时落到平和质，而平和质必须始终可用（否则整个服务打不开）**」。该测试会转红。
   - 另外 `matcher.CONSTITUTION_DEFAULT["balanced"]` 是**通用兜底搭配**（`test_safety.py:457、471` 依赖它），平和质还兼任「体质缺失时的降级目标」。
   - **三个选项**（须你选一）：① **不清空**，`balanced` 原样保留，本轮判定的「平和全中性」只体现在影子字段里，不动数据 —— 零风险；② **清空 + 改代码**：给平和质写一条「恒就绪」例外（如 `ready_constitutions()` 里把 `balanced` 无条件并入），这是**设计变更**，要同步改 `test_constitution_readiness.py`；③ 清空但**刻意留 1 味**兜底以维持就绪 —— 为过闸门而留数据，不干净，不建议。
   - 逐味名单（24 味）：`fuling chenpi shanzha gouqizi juhua meiguihua hongzao maidong juemingzi shengjiang bohe sangshen baihe lianzi wumei luohanguo gancao molihua danzhuye suanzaoren shanyao jineijin baibiandou huaihua`
4. **`cautions` 追加 △ 文案**：遵守「追加末尾、不挤第 1 条」；`matcher.py:237` 每味只取第 1 条，**新条款在兜底路径下看不到**。追加前须跑 `tests/test_safety.py`：`test_cautions_naming_yinxu_must_be_blocked` 是**派生不变式**——凡 cautions 命中「阴虚/津液/口干/上火/内热」的饮片，必须要么在 `unsuitable_for` 里有 `yin_deficiency`，要么登记在 `rulings.cells`（且 `level != evidence`）。
5. **写入 `suitable_constitutions` 的升位效应**（本轮实测）：新写入的饮片按 catalog 下标排序，**排位会变** —— 阴虚列现状仅 1 味（桑椹），写入后变为 `麦冬(下标8) → 桑椹(13) → 酸枣仁(23) → 山药(24)`，**麦冬跃居阴虚候选第 1 位**。这与 `rulings.priority_review` 里山楂×气郁登记的是同一类问题（下标靠前的药写入即升位），**须逐格确认是否接受**。
6. **`_meta.version`** 0.5.0 → 递增；`_meta.constitution_extension` 下建议新增 `evidence_batch` 块记录本批（口径、格数、tier 分布、来源）。
7. **写入方式**：文本级精确替换（按 id 定位块 + 只重写目标行），**不要 `json.load` + `json.dumps` 整体回写**——`herbs.json` 是内联数组风格，整体序列化会炸出上千行假 diff。替换后先 `json.load` 校验再落盘。

---

## §7 本文件未做的事 / 已知缺口

- **未改** `core/data/herbs.json`、`constitution.json`、`constitution-9-types.json`，未动任何代码或测试。
- **未复核粤中医原文**：26 格 `tier: X` 是转引项目既有取值，不是我的独立判定。
- **未做 5 型 170 格的追溯评级**：除本轮补依据的 16 格外，现有 5 型值绝大多数**仍无 source**。典型例子——**莲子 × 气虚** 已在 `suitable_constitutions` 里，但本轮查不到任何可引用来源，影子字段里也没有它。
- **P1-A/B/C/P2/P3 五批共 115 格已被本次一并覆盖**（本批做的是四型**全量** 136 格，含那 115 格与 21 格已有高置信结论）。逐格差异见 §5.9。
- **炮制品未单列**：本库对炙/炒/煅多不单列【性能】条。若日后有「炒白扁豆 vs 白扁豆」这类需求，只能给原药材四气，炮制后的变化属推断层。
- **体质层无源的型**：平和（已按 :2278 置中性）、湿热（沿用粤中医）、特禀（34 味里仅 3 格有据）。
- **行号绑定语料版本**：所有 `《中药学》七版:` / `《中医养生学》:` / `《中医饮食营养学》:` 行号绑定当前语料副本，换版本会失效。

