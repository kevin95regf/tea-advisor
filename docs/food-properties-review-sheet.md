# 食性表人工审核核验单（`food_properties.json`）

> ⚠️ **本文件由脚本生成，请勿手工编辑。**
> 生成命令：`cd core && python scripts/build_food_review_sheet.py --out ../docs/food-properties-review-sheet.md`
> 数据源：`core/data/food_properties.json`（本脚本只读，不改数据、不改审核状态）
> 对应挂起项：`docs/pending-items.md` **A1**（食性表 146 条全部未人工审核）

## 0. 这份单子的用法（先读）

A1 不是「造数据」，是**核验已有数据**：146 条的 `nature` / `flavors` 早已填好，
全部是 `pending`。终局动作（`approved` + `reviewed_by` / `reviewed_at`）**只有具备资质的**
中医师/中药师能做，脚本不替你判定。

难点在于**食材偏性没有官方标准**：药典只管药材（34 味有官方接口可比），
GB/T 46939 只管体质分类与判定阈值。食材四气只有「中医饮食养生通行表述」。
所以本单子把 146 条分四层，让审核人只看值得看的格子：

| 层 | 含义 | 谁来做 | 现状 |
|---|---|---|---|
| ① 来源一致 | 找到权威/通行来源且与现值一致 | 脚本抓取 + 人工确认 | 阶段二 |
| ② 来源冲突 | 来源之间或来源与现值不一致 | 人工裁决 | 阶段二 |
| ③ 无来源 | 找不到可引来源，标「无源可引」 | 人工凭专业判断 | 阶段二 |
| ④ 内部矛盾 | 表内自相矛盾，与外部来源无关 | **本脚本已跑完**（§2） | ✅ 见 §2 |

来源口径（**已定**）：**官方优先 + 多源兜底 + 无源标空**——优先引国家卫健委 /
中国营养学会的食养指南与膳食指南；其次 2–3 个通行来源交叉一致；都找不到就明确标
「无源可引」。**不把通行表述伪装成权威依据。**

⚠️ 产物里 `approved` 永远是 0，直到真的有人审核。**不要为了让界面好看批量置 approved**
——标记密度就是审核进度的可见反馈（`docs/maintenance.md` §9.3）。

## 1. 现状

| 项 | 值 |
|---|---|
| 总条数 | **146**（`foods` 128 + `tea_drinks.items` 18） |
| 审核状态 | pending **146** |
| 其中实际缺 `review_status` 字段 | **3** 条（上表按兼容回退计为 pending，见 §2） |
| 文件级 `_meta.review_status` | `pending` |
| ④ 层：矛盾 | **3** 类 |
| ④ 层：存疑 | 2 类 |
| ④ 层：已核对正常 | 2 类 |

按类分布（★ = 第一批，优先审）：

| 类别 | 条数 | 审核状态 |
|---|---|---|
| ★ 主食 | 20 | pending 20 |
| ★ 水产 | 6 | pending 6 |
| ★ 乳饮 | 3 | pending 3 |
| 蔬菜 | 24 | pending 24 |
| 菜肴 | 19 | pending 19 |
| 水果 | 18 | pending 18 |
| （无 category） | 18 | pending 18 |
| 饮料 | 9 | pending 9 |
| 肉类 | 8 | pending 8 |
| 甜点 | 5 | pending 5 |
| 调味 | 4 | pending 4 |
| 豆制品 | 4 | pending 4 |
| 酒类 | 3 | pending 3 |
| 蛋类 | 2 | pending 2 |
| 冷饮 | 1 | pending 1 |
| 甜汤 | 1 | pending 1 |
| 零食 | 1 | pending 1 |

## 2. ④ 层：内部矛盾 / 存疑（机器可查，已跑完）

这一层不依赖任何外部来源，所以脚本当场就能跑完。**矛盾类必须先处理**——
它们与审核无关，是数据自身或数据与代码的关系出了问题。

### 🔴 同一别名指向多条**属性不同**的条目

- **类型**：`别名歧义`　**级别**：矛盾
  - `炸鸡` → jirou（温）、zhaji（热）
- **为什么算问题**：用户说这个词时，命中哪一条取决于遍历顺序；两条四气不同，判定结果会不稳定（`maintenance.md` §10.11 记录过同类现象）。
- **该怎么处理**：改数据：让别名只留在最贴切的那一条上，或干脆拆分/合并条目。

### 🔴 `kafei`（咖啡）的变体属性与兜底规则不一致

- **类型**：`变体与规则不一致`　**级别**：矛盾
  - 本味四气 温，处理方式 `cold` 按规则应得 **平**，但 variant_nature 记的是 **凉**
- **为什么算问题**：layer_1 优先，所以当前判定用的是记录值，**不是 bug**；但删掉 variant_nature 就会漂到另一个答案，说明两者必有一个要改。
- **该怎么处理**：人工定：改 variant_nature，还是把该味的 base nature 改对。

### 🔴 条目缺合法三态 `review_status`

- **类型**：`缺 review_status`　**级别**：矛盾
  - `bing_naicha`（冰奶茶）只有旧布尔 `reviewed=False`
  - `qubing_naicha`（去冰奶茶）只有旧布尔 `reviewed=False`
  - `re_naicha`（热奶茶）只有旧布尔 `reviewed=False`
- **为什么算问题**：运行时靠 `food_lookup.py` 的兼容回退照常当 pending 处理，**行为已正确**；风险是以后有人写脚本只读 `review_status` 就会漏掉这几条（pending-items E1）。
- **该怎么处理**：改数据：跑一次 `python scripts/patch_food_table.py`（先 --dry-run）。

### 🟡 同一别名指向多条条目（属性一致）

- **类型**：`别名重复登记`　**级别**：存疑
  - `卤蛋` → lourou（温）、chadan（温）
- **为什么算问题**：属性一致，不影响判定结果；但会让 diff 与维护更难读。
- **该怎么处理**：可不改，或顺手清理。

### 🟡 条目没有 `category`，按类兜底对它们失效

- **类型**：`缺 category`　**级别**：存疑
  - `molihua_cha`（茉莉花茶）
  - `juhua_cha`（菊花茶）
  - `gouqi_cha`（枸杞茶）
  - `meigui_cha`（玫瑰花茶）
  - `puerg`（普洱茶）
  - `lvcha`（绿茶）
  - `hongcha`（红茶）
  - `wulong`（乌龙茶）
  - `damaicha`（大麦茶）
  - `chenpi_cha`（陈皮茶）
  - `jiangcha`（姜茶）
  - `hongzao_cha`（红枣茶）
  - `juemingzi_cha`（决明子茶）
  - `heye_cha`（荷叶茶）
  - `luohanguo_cha`（罗汉果茶）
  - `wumei_cha`（乌梅茶）
  - `putaoyou_cha`（水果茶）
  - `naixicha`（奶盖茶）
- **为什么算问题**：`_meta.field_notes.category` 写着「便于按类兜底判断」。茶饮整体不带 category（结构不对称），不是判定错误，但兜底路径覆盖不到它们。
- **该怎么处理**：人工定：是否给茶饮补 category，或改用 tea_drinks 这一层做兜底。

### ✅ 已核对正常（备查）

- **温度变体与规则一致（列出备查）**（`温度变体（已核对）`）
  - `bing_naicha`（凉）vs 基条目 `naicha`（平）：实际差 -1，规则要求 -1
  - `qubing_naicha`（凉）vs 基条目 `naicha`（平）：实际差 -1，规则要求 -1
  - `re_naicha`（温）vs 基条目 `naicha`（平）：实际差 +1，规则要求 +1
- **茶饮条目与同名饮片四气一致（列出备查）**（`跨表一致性（已核对）`）
  - `molihua_cha`（茉莉花茶）温 vs 饮片 `茉莉花` 温
  - `juhua_cha`（菊花茶）凉 vs 饮片 `菊花` 凉
  - `meigui_cha`（玫瑰花茶）温 vs 饮片 `玫瑰花` 温
  - `chenpi_cha`（陈皮茶）温 vs 饮片 `陈皮` 温
  - `hongzao_cha`（红枣茶）温 vs 饮片 `红枣` 温
  - `juemingzi_cha`（决明子茶）凉 vs 饮片 `决明子` 凉
  - `heye_cha`（荷叶茶）平 vs 饮片 `荷叶` 平
  - `luohanguo_cha`（罗汉果茶）凉 vs 饮片 `罗汉果` 凉
  - `wumei_cha`（乌梅茶）平 vs 饮片 `乌梅` 平

> 附带一个**规则层面**的观察（不在 A1 范围内，只记录）：温度前缀表把「去冰」也当成
> 降温前缀（`nature_math.CHILL_PREFIXES`，-1），所以 `去冰奶茶` 记「凉」与代码是自洽的。
> 但「去掉冰」按直觉应接近常温，这里规则与直觉有出入——属于规则讨论，要改就改
> `nature_math` 那一处前缀表，与本次数据审核无关。

## 3. 核验单骨架（146 条）

阶段二的来源核对结果填进最后两列。**「无源可引」也是一个合法结论**，
不要为了让格子好看而硬找来源。

### 主食（20 条）★ 第一批

| # | id | 名称 | 四气 | 五味 | 审核状态 | 来源核对（阶段二） | 判定（阶段二） |
|---|---|---|---|---|---|---|---|
| 1 | `mifan` | 米饭 | 平 | sweet | pending | | |
| 2 | `zhou` | 白粥 | 平 | sweet | pending | | |
| 3 | `mantou` | 馒头 | 平 | sweet | pending | | |
| 4 | `mianshi` | 面条 | 平 | sweet | pending | | |
| 5 | `miantiao_liang` | 凉面 | 凉 | sweet | pending | | |
| 6 | `jiazi` | 饺子 | 平 | sweet | pending | | |
| 7 | `baozi` | 包子 | 平 | sweet | pending | | |
| 8 | `xiaolongbao` | 小笼包 | 平 | sweet | pending | | |
| 9 | `suantou` | 米粉 | 平 | sweet | pending | | |
| 10 | `yumi` | 玉米 | 平 | sweet | pending | | |
| 11 | `hongshu` | 红薯 | 平 | sweet | pending | | |
| 12 | `tudou` | 土豆 | 平 | sweet | pending | | |
| 13 | `youtiao` | 油条 | 热 | sweet | pending | | |
| 14 | `hanbao` | 汉堡 | 温 | sweet | pending | | |
| 15 | `sanmingzhi` | 三明治 | 平 | sweet | pending | | |
| 16 | `yidali_mian` | 意大利面 | 平 | sweet | pending | | |
| 17 | `shousi` | 寿司 | 凉 | sweet、sour、salty | pending | | |
| 18 | `niurou_hanbao` | 牛肉汉堡 | 温 | salty、sweet | pending | | |
| 19 | `tusi` | 吐司 | 平 | sweet | pending | | |
| 20 | `sanmingzhi_huotui` | 火腿三明治 | 平 | salty | pending | | |

### 水产（6 条）★ 第一批

| # | id | 名称 | 四气 | 五味 | 审核状态 | 来源核对（阶段二） | 判定（阶段二） |
|---|---|---|---|---|---|---|---|
| 1 | `yuxia` | 鱼 | 平 | sweet | pending | | |
| 2 | `xia` | 虾 | 温 | sweet、salty | pending | | |
| 3 | `pangxie` | 螃蟹 | 寒 | salty | pending | | |
| 4 | `shengyu` | 生鱼片 | 寒 | sweet | pending | | |
| 5 | `haili` | 海带 | 凉 | salty | pending | | |
| 6 | `zicai` | 紫菜 | 凉 | salty、sweet | pending | | |

### 乳饮（3 条）★ 第一批

| # | id | 名称 | 四气 | 五味 | 审核状态 | 来源核对（阶段二） | 判定（阶段二） |
|---|---|---|---|---|---|---|---|
| 1 | `niunai` | 牛奶 | 平 | sweet | pending | | |
| 2 | `suannai` | 酸奶 | 平 | sweet、sour | pending | | |
| 3 | `xila_suannai` | 希腊酸奶 | 凉 | sweet、sour | pending | | |

### 蔬菜（24 条）

| # | id | 名称 | 四气 | 五味 | 审核状态 | 来源核对（阶段二） | 判定（阶段二） |
|---|---|---|---|---|---|---|---|
| 1 | `baicai` | 白菜 | 凉 | sweet | pending | | |
| 2 | `qingcai` | 青菜 | 凉 | sweet | pending | | |
| 3 | `bocai` | 菠菜 | 凉 | sweet | pending | | |
| 4 | `shengcai` | 生菜 | 凉 | sweet、bitter | pending | | |
| 5 | `huanggua` | 黄瓜 | 凉 | sweet | pending | | |
| 6 | `xihongshi` | 西红柿 | 凉 | sweet、sour | pending | | |
| 7 | `luobo` | 白萝卜 | 凉 | pungent、sweet | pending | | |
| 8 | `huluobo` | 胡萝卜 | 平 | sweet | pending | | |
| 9 | `qincai` | 芹菜 | 凉 | pungent、sweet | pending | | |
| 10 | `jiecai` | 芥菜 | 温 | pungent | pending | | |
| 11 | `jiucai` | 韭菜 | 温 | pungent | pending | | |
| 12 | `jiachang` | 茄子 | 凉 | sweet | pending | | |
| 13 | `donggua` | 冬瓜 | 凉 | sweet、bland | pending | | |
| 14 | `nangua` | 南瓜 | 温 | sweet | pending | | |
| 15 | `sigua` | 丝瓜 | 凉 | sweet | pending | | |
| 16 | `kugua` | 苦瓜 | 寒 | bitter | pending | | |
| 17 | `lajiao` | 辣椒 | 热 | pungent | pending | | |
| 18 | `cong` | 葱 | 温 | pungent | pending | | |
| 19 | `suan` | 蒜 | 温 | pungent | pending | | |
| 20 | `jiang` | 姜 | 温 | pungent | pending | | |
| 21 | `mogu` | 蘑菇 | 平 | sweet | pending | | |
| 22 | `muer` | 木耳 | 平 | sweet | pending | | |
| 23 | `lianou` | 莲藕 | 凉 | sweet | pending | | |
| 24 | `douya` | 豆芽 | 凉 | sweet | pending | | |

### 菜肴（19 条）

| # | id | 名称 | 四气 | 五味 | 审核状态 | 来源核对（阶段二） | 判定（阶段二） |
|---|---|---|---|---|---|---|---|
| 1 | `mahuoguo` | 火锅 | 热 | pungent | pending | | |
| 2 | `malatang` | 麻辣烫 | 热 | pungent、salty | pending | | |
| 3 | `malahuoguo` | 麻辣香锅 | 热 | pungent、salty | pending | | |
| 4 | `shaokao` | 烧烤 | 热 | pungent、salty | pending | | |
| 5 | `hongshao` | 红烧肉 | 温 | sweet、salty | pending | | |
| 6 | `lajiao_chao` | 辣炒菜 | 热 | pungent | pending | | |
| 7 | `zhajiang` | 炸酱面 | 温 | salty | pending | | |
| 8 | `guanzhudong` | 关东煮 | 温 | salty | pending | | |
| 9 | `shala` | 沙拉 | 凉 | sweet、sour | pending | | |
| 10 | `pisa` | 披萨 | 温 | salty、sweet | pending | | |
| 11 | `zhaji` | 炸鸡 | 热 | salty、pungent | pending | | |
| 12 | `shuijiao_rou` | 螺蛳粉 | 热 | pungent、sour | pending | | |
| 13 | `huntun` | 馄饨 | 平 | sweet | pending | | |
| 14 | `hanshi_zhaji` | 韩式炸鸡 | 热 | salty、pungent、sweet | pending | | |
| 15 | `zhayu_shutiao` | 炸鱼薯条 | 热 | salty | pending | | |
| 16 | `niuyouguo_shala` | 牛油果沙拉 | 凉 | sweet、sour | pending | | |
| 17 | `hanshi_banfan` | 韩式拌饭 | 温 | pungent、salty、sweet | pending | | |
| 18 | `rishi_lamian` | 日式拉面 | 温 | salty、sweet | pending | | |
| 19 | `gali` | 咖喱 | 热 | pungent、salty | pending | | |

### 水果（18 条）

| # | id | 名称 | 四气 | 五味 | 审核状态 | 来源核对（阶段二） | 判定（阶段二） |
|---|---|---|---|---|---|---|---|
| 1 | `pingguo` | 苹果 | 凉 | sweet、sour | pending | | |
| 2 | `xiangjiao` | 香蕉 | 寒 | sweet | pending | | |
| 3 | `juzi` | 橘子 | 凉 | sweet、sour | pending | | |
| 4 | `xigua` | 西瓜 | 寒 | sweet | pending | | |
| 5 | `putao` | 葡萄 | 平 | sweet、sour | pending | | |
| 6 | `li` | 梨 | 凉 | sweet、sour | pending | | |
| 7 | `caomei` | 草莓 | 凉 | sweet、sour | pending | | |
| 8 | `mangguo` | 芒果 | 凉 | sweet、sour | pending | | |
| 9 | `lizhi` | 荔枝 | 温 | sweet、sour | pending | | |
| 10 | `longyan` | 龙眼 | 温 | sweet | pending | | |
| 11 | `taozi` | 桃子 | 温 | sweet、sour | pending | | |
| 12 | `yingtao` | 樱桃 | 温 | sweet | pending | | |
| 13 | `shanzha_guo` | 山楂果 | 温 | sour、sweet | pending | | |
| 14 | `ningmeng` | 柠檬 | 凉 | sour、sweet | pending | | |
| 15 | `niuyouguo` | 牛油果 | 平 | sweet | pending | | |
| 16 | `huolongguo` | 火龙果 | 凉 | sweet | pending | | |
| 17 | `shizi` | 柿子 | 寒 | sweet、astringent | pending | | |
| 18 | `shanzhu` | 山竹 | 凉 | sweet、sour | pending | | |

### （无 category）（18 条）

| # | id | 名称 | 四气 | 五味 | 审核状态 | 来源核对（阶段二） | 判定（阶段二） |
|---|---|---|---|---|---|---|---|
| 1 | `molihua_cha` | 茉莉花茶 | 温 | sweet、pungent | pending | | |
| 2 | `juhua_cha` | 菊花茶 | 凉 | sweet、bitter | pending | | |
| 3 | `gouqi_cha` | 枸杞茶 | 平 | sweet | pending | | |
| 4 | `meigui_cha` | 玫瑰花茶 | 温 | sweet、bitter | pending | | |
| 5 | `puerg` | 普洱茶 | 温 | bitter、sweet | pending | | |
| 6 | `lvcha` | 绿茶 | 凉 | bitter、sweet | pending | | |
| 7 | `hongcha` | 红茶 | 温 | sweet、bitter | pending | | |
| 8 | `wulong` | 乌龙茶 | 平 | sweet、bitter | pending | | |
| 9 | `damaicha` | 大麦茶 | 平 | sweet | pending | | |
| 10 | `chenpi_cha` | 陈皮茶 | 温 | pungent、bitter | pending | | |
| 11 | `jiangcha` | 姜茶 | 温 | pungent | pending | | |
| 12 | `hongzao_cha` | 红枣茶 | 温 | sweet | pending | | |
| 13 | `juemingzi_cha` | 决明子茶 | 凉 | sweet、bitter | pending | | |
| 14 | `heye_cha` | 荷叶茶 | 平 | bitter、bland | pending | | |
| 15 | `luohanguo_cha` | 罗汉果茶 | 凉 | sweet | pending | | |
| 16 | `wumei_cha` | 乌梅茶 | 平 | sour、astringent | pending | | |
| 17 | `putaoyou_cha` | 水果茶 | 凉 | sweet、sour | pending | | |
| 18 | `naixicha` | 奶盖茶 | 平 | sweet | pending | | |

### 饮料（9 条）

| # | id | 名称 | 四气 | 五味 | 审核状态 | 来源核对（阶段二） | 判定（阶段二） |
|---|---|---|---|---|---|---|---|
| 1 | `kele` | 可乐 | 凉 | sweet | pending | | |
| 2 | `naicha` | 奶茶 | 平 | sweet | pending | | |
| 3 | `kafei` | 咖啡 | 温 | bitter | pending | | |
| 4 | `suanmeitang` | 酸梅汤 | 平 | sour、sweet | pending | | |
| 5 | `liangcha` | 凉茶 | 寒 | bitter、sweet | pending | | |
| 6 | `guozhi` | 果汁 | 凉 | sweet、sour | pending | | |
| 7 | `bing_naicha` | 冰奶茶 | 凉 | sweet | ⚠️ 缺字段 | | |
| 8 | `qubing_naicha` | 去冰奶茶 | 凉 | sweet | ⚠️ 缺字段 | | |
| 9 | `re_naicha` | 热奶茶 | 温 | sweet | ⚠️ 缺字段 | | |

### 肉类（8 条）

| # | id | 名称 | 四气 | 五味 | 审核状态 | 来源核对（阶段二） | 判定（阶段二） |
|---|---|---|---|---|---|---|---|
| 1 | `zhurou` | 猪肉 | 平 | sweet、salty | pending | | |
| 2 | `niurou` | 牛肉 | 温 | sweet | pending | | |
| 3 | `yangrou` | 羊肉 | 热 | sweet | pending | | |
| 4 | `jirou` | 鸡肉 | 温 | sweet | pending | | |
| 5 | `yakuai` | 鸭肉 | 凉 | sweet、salty | pending | | |
| 6 | `lourou` | 卤肉 | 温 | salty | pending | | |
| 7 | `huotui` | 火腿 | 温 | salty | pending | | |
| 8 | `xiangchang` | 香肠 | 温 | salty | pending | | |

### 甜点（5 条）

| # | id | 名称 | 四气 | 五味 | 审核状态 | 来源核对（阶段二） | 判定（阶段二） |
|---|---|---|---|---|---|---|---|
| 1 | `dangao` | 蛋糕 | 平 | sweet | pending | | |
| 2 | `lvdougao` | 绿豆糕 | 凉 | sweet | pending | | |
| 3 | `qiaokeli` | 巧克力 | 温 | sweet、bitter | pending | | |
| 4 | `binggan` | 饼干 | 温 | sweet | pending | | |
| 5 | `suannai_wan` | 酸奶碗 | 凉 | sweet、sour | pending | | |

### 调味（4 条）

| # | id | 名称 | 四气 | 五味 | 审核状态 | 来源核对（阶段二） | 判定（阶段二） |
|---|---|---|---|---|---|---|---|
| 1 | `tang` | 糖 | 平 | sweet | pending | | |
| 2 | `yan` | 盐 | 寒 | salty | pending | | |
| 3 | `cu` | 醋 | 温 | sour | pending | | |
| 4 | `jiangyou` | 酱油 | 平 | salty | pending | | |

### 豆制品（4 条）

| # | id | 名称 | 四气 | 五味 | 审核状态 | 来源核对（阶段二） | 判定（阶段二） |
|---|---|---|---|---|---|---|---|
| 1 | `doufu` | 豆腐 | 凉 | sweet | pending | | |
| 2 | `doujiang` | 豆浆 | 平 | sweet | pending | | |
| 3 | `fuzhu` | 腐竹 | 平 | sweet | pending | | |
| 4 | `maodou` | 毛豆 | 平 | sweet | pending | | |

### 酒类（3 条）

| # | id | 名称 | 四气 | 五味 | 审核状态 | 来源核对（阶段二） | 判定（阶段二） |
|---|---|---|---|---|---|---|---|
| 1 | `pijiu` | 啤酒 | 凉 | bitter、sweet | pending | | |
| 2 | `baijiu` | 白酒 | 热 | pungent、sweet | pending | | |
| 3 | `hongjiu` | 红酒 | 温 | sweet、sour | pending | | |

### 蛋类（2 条）

| # | id | 名称 | 四气 | 五味 | 审核状态 | 来源核对（阶段二） | 判定（阶段二） |
|---|---|---|---|---|---|---|---|
| 1 | `chadan` | 茶叶蛋 | 温 | salty | pending | | |
| 2 | `jidan` | 鸡蛋 | 平 | sweet | pending | | |

### 冷饮（1 条）

| # | id | 名称 | 四气 | 五味 | 审核状态 | 来源核对（阶段二） | 判定（阶段二） |
|---|---|---|---|---|---|---|---|
| 1 | `bingqilin` | 冰淇淋 | 寒 | sweet | pending | | |

### 甜汤（1 条）

| # | id | 名称 | 四气 | 五味 | 审核状态 | 来源核对（阶段二） | 判定（阶段二） |
|---|---|---|---|---|---|---|---|
| 1 | `yiner` | 银耳 | 平 | sweet、bland | pending | | |

### 零食（1 条）

| # | id | 名称 | 四气 | 五味 | 审核状态 | 来源核对（阶段二） | 判定（阶段二） |
|---|---|---|---|---|---|---|---|
| 1 | `shujiaotiao` | 薯条 | 热 | salty | pending | | |

## 4. 阶段二作业口径（已定：官方优先 + 多源兜底 + 无源标空）

| 优先级 | 来源 | 说明 |
|---|---|---|
| 1 | 国家卫健委 / 中国营养学会的**食养指南与膳食指南** | 半官方、可引用性最高；但按疾病/人群编写，**不按食材列四气**，覆盖不全 |
| 2 | 中医饮食养生**通行表述**的多源交叉 | 2–3 源一致才记「来源一致」；结论只能是「来源一致」，**不能**写成「正确」 |
| 3 | 找不到任何来源 | 标**「无源可引」**，留给审核人凭专业判断 |

两条纪律：

1. **不把通行表述伪装成权威依据**——引用时必须写清是第 2 档来源，不得混入指南口径。
2. **第一批只做 ★ 主食 / 乳饮 / 水产**：这些大类在指南里覆盖最好，最可能先产出 `approved`，
   让 A1 的验收标准（`approved > 0`）先动起来。菜肴 / 饮料 / 冷饮 / 甜点最易错，放后面。

