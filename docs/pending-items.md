# 挂起事项清单

> **这份清单是挂起事项的唯一真源。** 其他地方（`handover.md`、`maintenance.md`）只提摘要，
> 一律以本文为准。任何一项解决了，就在这里更新状态并记录解决方式。
>
> 快照时间：**2026-09-17**　共 **11** 项记录在案（A/B/C/D/E 五类），
> 其中 **D2、E1 已解决**、**B3 的阻塞已解除**（九型已上线，余下 244 格是完备度而非功能阻塞），其余 8 项待处理。

---

## 概览

| ID | 事项 | 谁来解 | 阻塞什么 | 状态 |
|---|---|---|---|---|
| **A1** | 食性表 147 条全部未人工审核 | 具备资质的中医师/中药师 | ⛔ **对外提供服务** | 待人工 |
| **A2** | A1 核对遗留 4 项待确认（酱油 + 3 味菇等） | 项目所有者 | 不影响功能，影响 3 条数据的最终取值 | 待确认 |
| **B1** | 7 处药典不一致待复核 | nanple | 数据准确性（不阻塞功能） | 待 nanple |
| **B2** | 问卷项目 `phlegm_dampness` 拼写不一致 | nanple | 问卷接入 | 待 nanple |
| **B3** | 244 个配伍判定（九型已上线，余下是完备度） | nanple | 推荐质量（不再阻塞体质模型 5→9 型） | 已部分解决 |
| **C1** | 《中华本草》列全空 | 需取得资料 | 三源交叉验证 | 待外部资料 |
| **C2** | 国标 A 栏是转引，非标准正文 | 需取得资料 | 逐字对齐国标 | 待外部资料 |
| **D1** | 玫瑰花/茉莉花的代码改动 | 项目所有者定时机 | 合规处置落地 | 待实施 |
| **D2** | 本地提交未推送 | 项目所有者 | 协作者看不到这批产出 | ✅ **已解决** |
| **E1** | 3 条食性表缺 `review_status` | 开发 | 无（行为已正确） | ✅ **已解决**（2026-09-17） |
| **E2** | `herbs.json` 34 味缺逐条审核字段 | 开发 | A1 的验收标准落不到 herbs | 待清理 |

**⛔ 标记的是真正的硬阻碍**：只要 A1 没解决，「对外提供服务」就不能说完成。
（B3 原先也标 ⛔，2026-09-17 九型上线后已解除——余下的 244 格影响的是推荐完备度，不再是功能阻塞。）

---

# A 类 · 对外服务的硬阻碍

## A1　食性表 147 条全部未人工审核

| | |
|---|---|
| **现状** | `food_properties.json` 的 147 条（129 食材 + 18 茶饮），逐条 `review_status` **全部是 `pending`**，没有一条 `approved` |
| **范围** | ⚠️ **本项只覆盖 `food_properties.json`。** `herbs.json` 不是「逐条 pending」——它**根本没有逐条审核字段**，审核状态只在文件级 `_meta.review_status`。已单列为 **E2** |
| **影响** | 所有条目虽按 0.9 置信度参与判定，但界面**必须**标「待验证」。这是刻意的保守设计，不是 bug |
| **为何只有人能解** | `approved` 意味着「真·硬规则库、界面不再标注」，必须由具备资质的中医师/中药师逐条确认，并同时填写 `reviewed_by` / `reviewed_at` |
| **需要什么** | 审核人 + 一份逐条审核流程（`docs/maintenance.md` §9.2/§9.3 有正确姿势）。**核验单已就绪**：`docs/food-properties-review-sheet.md`（脚本生成、只读可重跑）。④ 层内部矛盾已清零（4 类于 2026-09-17 修完）。①②③ 层按「官方优先 + 多源兜底 + 无源标空」推进，**第一批已定为「蔬菜/调味/水果中有来源可引的 33 条」**（**① 28 一致 + ② 4 冲突 + ③ 1 无源**），清单见 `docs/food-properties-batch2-confirm.md`。<br>⚠️ **原定第一批「★ 主食/水产/乳饮」已作废**——那 29 条多为加工食品（米饭、饺子、奶茶），50 号文件 §5.2「真无据清单」本就覆盖它们，是**结构性**无来源，不是核对不到位。核验单的「第一批」判据已改为**来源登记表里 `batch=第一批`**（`build_food_review_sheet.py` 里写死类别的 `FIRST_BATCH_CATEGORIES` 已删除），不再按类别判定 |
| **验收标准** | `food_properties.json` 的 `review_status` 分布中 `approved` 条数 > 0，且每条 approved 都有 `reviewed_by` + `reviewed_at` |
| **注意** | ⚠️ **不要为了界面好看而批量置 approved**。标记密度就是审核进度的可见反馈，批量置等于把这个反馈抹掉 |
| **相关文件** | `core/data/food_properties.json`、`docs/food-properties-review-sheet.md`（核验单，脚本生成）、`core/scripts/build_food_review_sheet.py`（生成工具，**只读**，`--check` 可进 CI）、`docs/food-properties-sources.json`（47 条来源登记，①②③ 层的事实源）、`docs/food-properties-batch2-confirm.md`（第一批 33 条清单，待确认）、`docs/food-properties-batch2-plan.md`（核对方案） |

## A2　A1 核对遗留的 4 项待确认（酱油 + 3 味菇）

> 属于 A1 的一部分，但**不能用「来源核对」解决**——都是「数据该不该改」的决定。单列出来，
> 免得混在 33 条清单里被当成已结案。**未确认前不改数据**。

| | |
|---|---|
| **① 酱油（`jiangyou`）** | 项目记「平」；依据《本草纲目》「酱」记「温」。映射本身可用，但 50 号文件 §5.4 自定「仅经典有载、教材无（**不得当教材用**）」——纲目强度低于教材，**据此改判不成立**，故 nature 不改、单列待确认。核验单 §4.2 已按 ② 层登记 |
| **② 金针菇 / 杏鲍菇 / 平菇** | 三者**暂留在 `mogu` 条目上**，因而随条目被判为**寒**（原 `mogu` 为平）。但它们是另外 3 个物种，50 号文件**无条目**，属 ③ 无源。两条路：随条目暂留（现状）／各自独立成条后标无源待核。**倾向前者**，待确认 |
| **③ 蘑菇拆条的收尾** | `mogu` 已收窄为「蘑菰」（寒，纲目 23487）；新增 `xianggu`「香菇」（平，香蕈）。新条目 `review_status: pending`、无 `reviewed_by`，与全表一致。**待确认的是**：`xianggu` 该不该继承原 `mogu` 的任何审核痕迹（当前**不继承**，按新条目从零开始） |
| **④ C 组 4 条来源值的限定写法** | `shengcai`（生菜→莴苣）、`lianou`（莲藕→藕）、`suan`（蒜→大蒜）三条已采纳并各带限定；`qingcai`（青菜→油菜）**未采纳**、已降级 ③。限定措辞若要调整，改 `docs/food-properties-sources.json` 的 `mapping_review.reason` 即可 |
| **相关文件** | `docs/food-properties-sources.json`（`_meta.mapping_review` 与各条 `mapping_review`）、`docs/food-properties-review-sheet.md` §4.2/§4.3/§4.4、`core/data/food_properties.json` |

---

# B 类 · 等 nanple

## B1　7 处药典不一致待复核

| | |
|---|---|
| **现状** | 《中国药典》2020 年版一部与项目 `herbs.json` 有 **7 处不一致**（34 味中一致 26、未收载 1） |
| **决定** | **2026-09-17 已定：先保留项目值，不改数据，等 nanple 复核后再决定是否改** |
| **差异影响** | 已逐条做过**代码取证**，结论是**这 7 处都不改变任何确定性判定结果**（饮片的四气/五味/归经不参与任何护栏或规则运算，唯一实质消费者是 Agent2 的候选描述提示词）。详见 `docs/herb-nature-crosscheck.md` §3.1/§3.2 |
| **需要什么** | nanple 判断每一处以哪个为准（药典 or 项目），或说明项目值的其他依据 |
| **7 处明细** | 桑椹（凉↔寒）、百合（凉↔寒）、淡竹叶（凉↔寒）、白扁豆（平↔微温）、佛手（缺「酸」、缺「胃」经）、红枣（缺「心」经）、荷叶（多「淡」） |
| **验收标准** | nanple 给出逐条结论；若需改数据，改完运行 `python scripts/build_herb_crosscheck.py --refresh` 重建参考数据，并同步更新 `core/tests/test_herb_crosscheck.py` 的 `EXPECTED_INCONSISTENT` 清单（测试会提示） |
| **相关文件** | `docs/herb-nature-crosscheck.md`、`core/data/herb_nature_reference.json`、`core/scripts/build_herb_crosscheck.py` |

## B2　问卷项目 `phlegm_dampness` 拼写不一致

| | |
|---|---|
| **现状** | nanple 的 `tcm-constitution-questionnaire/` 用 `phlegm_dampness` 表示痰湿质；本项目 `core/data/constitution.json` 与 `enums.py` 用 `phlegm_damp` |
| **影响** | 两边的体质标识无法直接对接。**这也独立证明了 `tcm-constitution-questionnaire/` 目前尚未接入本项目**——如果接过，这个不一致早在跑测试时就暴露了 |
| **决定** | **2026-09-17 已定：作为第一个 Issue 提给 nanple** |
| **需要什么** | 二选一：① 问卷侧改成 `phlegm_damp`；② 项目侧加一层适配映射。**建议 ①**，因为项目侧的 id 已在 9 型里全部确认（见 B3） |
| **验收标准** | 两边对同一体质给出同一个标识串 |
| **相关文件** | `tcm-constitution-questionnaire/tcm_constitution/questions.py`、`core/app/domain/enums.py` |

## B3　244 个配伍判定

| | |
|---|---|
| **现状** | **Step 1 + Step 2 均已完成（2026-09-17）**：枚举 / `constitution.json` / 就绪闸门已扩到 9 型；`herbs.json` 写入 10 格「公开来源直接点名」的配伍标注，**九型已全部就绪并对外可见**。**余下的 244 格是完备度问题，不再是功能阻塞**：4 个新体质逐味判定的完整覆盖约为 34 味 × `suitable_constitutions` + 27 味 × `unsuitable_for`，目前只填了 10 格。<br>同日另有 **cautions 补写批次**：把项目**自有** `cautions` 已明写阴虚不宜的 10 味追加进 `unsuitable_for`（见「附注」），属项目数据一致性修复，不引用外部来源、不含外推 |
| **为何只有人能解** | **GB/T 46939-2025 只规定体质分类、问卷、计分与判定阈值，不提供任何饮食或饮片建议。** 余下的格子无标准可依 |
| **写入口径** | 只写「公开来源**直接点名**该饮片适用于/不适用于该体质」的组合（共 10 格）；药典功效外推、项目 `cautions` 推导**一律不写**，留待人工审核。逐条依据与推导过程见 `docs/herbs-9types-draft.md`。**空缺 ≠ 安全或不宜，空缺只表示「未判定」** |
| **防错（已实战检验）** | `filter_by_constitution` 在「该体质一条数据都没有」时**抛错而非静默退化**（静默退化会让阴虚质拿到温补辛温之品，方向相反且从输出表面看不出来）。这个机制在 Step 1→Step 2 之间被真实验证过：当时 4 型枚举有了、数据没有，被两层闸门稳稳挡住（`/api/constitutions` 不返回；直接指定则 **422 `CONSTITUTION_NOT_READY`**，不静默回落平和质）。Step 2 之后闸门仍在，守的是**将来**新增而未备数据的体质 |
| **需要什么** | nanple（或另一位懂中医的人）给出余下的判定；**5 处已单列待确认**：山楂×阴虚、山楂×气郁、槐花×血瘀（来源/类属映射存疑），外加**香薷×阴虚、荷叶×阴虚**——这两味在阴虚方向的推导里被判为不宜，但 `cautions` 措辞未提阴虚（荷叶只写「体瘦、气血偏虚者不宜久服」，香薷只写「性温发汗，表虚多汗者不宜」），硬写属**外推**，故未写入 |
| **验收标准** | ① ✅ **已达成（2026-09-17）**：`ready_constitutions()` 返回全部 9 型 —— 等价于 `GET /api/constitutions` 返回 9 项、四个新体质已出现在前端下拉框；<br>② ⚠️ **`MissingConstitutionDataError` 不是要消除的目标**，它是设计行为：体质无数据时**必须**抛错，所以测试里**应当保留**主动构造该场景的用例（`test_safety.py`、`test_constitution_readiness.py`）。本条原写作「`pytest` 不再触发 `MissingConstitutionDataError`」，方向反了，且不可判定——没人去测那 4 型时它同样不触发；<br>③ **余项（完备度）**：余下格子经人工判定后可继续补写，**补写不需要改代码**——数据一多，候选集的排序与方向收敛自动变好 |
| **相关文件** | `docs/constitution-9-types.md`（九型资料 + B 栏饮食方向）、`docs/herbs-9types-draft.md`（逐条依据草稿）、`core/data/herbs.json`、`core/data/constitution.json` |
| **附注** | 已写入的 10 格（公开来源点名）：**宜**——桑椹×阴虚，山楂/红枣/生姜×血瘀，红枣/薄荷×气郁，红枣/山药×特禀；**忌**——乌梅×血瘀、乌梅×气郁。**另有 cautions 批次 10 味**（项目自有数据，属推导非权威依据）：茯苓、陈皮、龙眼肉、生姜、薏苡仁、茉莉花、橘红、藿香、紫苏、佛手 → 阴虚 `unsuitable_for`。按 A1 口径，这些都属**未人工审核数据**，界面仍标「待验证」 |

---

# C 类 · 需要先拿到外部资料

## C1　《中华本草》列全空

| | |
|---|---|
| **现状** | `docs/herb-nature-crosscheck.md` 的《中华本草》列**一格都没填**，全部标注「待确认」 |
| **原因** | **取不到公开数据，不是遗漏。** 实测记录（完整版在 `core/data/herb_nature_reference.json` 的 `_meta.zhonghua_bencao_status`）：<br>① 药智网「中华本草数据库」需登录<br>② tcmdoc.cn 页面标题就是「中国药典、中药大辞典、中华本草、全国中草药汇编」，但返回 **403**<br>③ 中医世家 zysj.com.cn **拒绝连接**<br>④ wiki8.cn **403**、zhongyoo.com **521**<br>⑤ yao86.com 虽在【参考文献】里引用《中华本草》，但它展示的【药性】是**药典**的值 —— 不能当《中华本草》的来源用 |
| **决定** | **2026-09-17 已定：统一标「待确认」，不猜。** 按项目所有者的判断，不值得为它拉长工期——药典是官方标准，比《中华本草》更合规、也更可抓取 |
| **⚠️ 关键提醒** | **空缺 = 未核实，不等于与药典相同。** 《中华本草》与《中国药典》对同一味药的性味归经多数相同但并非全部相同（药典是药品标准，会随版次修订）。任何人引用这份文档时都不能把空缺读成「一致」 |
| **需要什么** | 《中华本草》（上海科学技术出版社，国家中医药管理局《中华本草》编委会）的电子版或复印件 |
| **拿到后怎么做** | 把数据给我/开发，补进 `herb_nature_reference.json` 的每条记录，新增一个 `zhonghua_bencao` 字段并与药典列逐条比对（脚本已按「参考列」结构预留） |
| **相关文件** | `docs/herb-nature-crosscheck.md` §6、`core/data/herb_nature_reference.json` |

## C2　国标 A 栏是转引，非标准正文

| | |
|---|---|
| **现状** | `docs/constitution-9-types.md` 的 A 栏（九型特征）**全部是官方解读/权威媒体的转引**，每一条都标注了来源与「非标准正文」 |
| **原因** | **标准正文取不到。** 已实测：<br>① 国家标准全文公开系统的「在线预览」在非浏览器环境只返回「当前浏览器暂不支持标准全文在线预览服务」回退页<br>② 同页「下载标准」走同一条在线预览链路，未暴露可直接下载的 PDF 地址<br>③ 中国标准出版社在人人文库上传的正版 PDF（20 页 / 295 KB）需 44 积分，无文本预览 |
| **决定** | **2026-09-17 已定：用官方解读/起草人访谈转引，逐条标注「非标准正文，系转引」**，不冒充原文 |
| **当前 A 栏来源** | 科技日报 2026-02-10 专访王琦院士（标准主要起草人）为主；辅以央广网、广东省中医药局 |
| **需要什么** | 用 Chrome/Edge 打开 [国家标准全文公开系统](https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno=827D6D266BA52A2983F93638DA871028) 的在线预览，或取得中国标准出版社正版 PDF |
| **拿到后怎么做** | 把 PDF 给我/开发，逐条替换 A 栏为原文并标注条款号；同时可核对「判定阈值 40 分」的口径（该条也是转引，见 `docs/constitution-9-types.md` §7） |
| **相关文件** | `docs/constitution-9-types.md` §1.1、`docs/constitution-9-types.json` 的 `standard.fulltext_status` |

---

# D 类 · 等决定或等实施

## D1　玫瑰花/茉莉花的代码改动

| | |
|---|---|
| **现状** | 两个决定**已登记但代码未动**，状态为 `待实施（等 nanple 审数据）` |
| **决定内容** | **玫瑰花**：保留，但名称需明确品种为「玫瑰花（重瓣红玫瑰）」<br>**茉莉花**：标注「仅作参考」，推荐时排除 |
| **为何没直接做** | 都有真实技术约束：<br>① **改名会打断白名单匹配** —— `herb_by_name()` 是 `check_blend` / `check_constitution_fit` / `filter_by_constitution` 唯一的名称索引，`if name not in catalog: blocked`。改名而不同时加别名，Agent2 输出的「玫瑰花」会被判成白名单外饮片**直接拦掉**，这是行为回归<br>② **「推荐时排除」需要新增能力** —— 现有 `exclude_herbs` 是**每请求的用户自选排除**，不是目录级开关 |
| **⚠️ 必须知道的限制** | 品种约束**代码表达得了、核实不了**。「原料确为重瓣红玫瑰」是采购/供应链要求，代码只能把它写在数据里。按项目所有者自己定的规则（做不到这个约束就标「仅作参考」），若无法保证原料品种，玫瑰花应降级为「仅作参考」 |
| **实现方案（已备好）** | `models.py` 给 `CatalogHerb` 加两个可选字段（`aliases` / `reference_only`）+ `safety.py` 的名称索引加别名 + `filter_by_constitution` 与 `matcher.fallback_recommend` 过滤 `reference_only` + 测试 |
| **风险提示** | 不改的后果是**「文档说改了、代码没改」**——正是这个项目踩过的坑，所以状态明确标成「待实施」而不是「已实施」 |
| **验收标准** | 决定状态从「待实施」变为「已实施」，且 `python scripts/check_herb_catalog.py --format md --out ../docs/catalog-compliance.md` 重新生成后文档同步 |
| **相关文件** | `core/scripts/check_herb_catalog.py` 的 `DECISIONS` 常量、`docs/catalog-compliance.md` §处置决定 |

## D2　本地提交未推送

| | |
|---|---|
| **现状** | ✅ **已解决。** 2026-09-17 推送 `010db2f..7ed495a`（6 个提交）到 `origin/main` |
| **验收结果** | `git log --oneline origin/main..HEAD` 输出为空；`git ls-remote origin refs/heads/main` 返回 `7ed495a7be…` |
| **影响** | nanple 现在能在 GitHub 上看到这批产出（食药物质目录、九型资料、药典核对、四项决定、交接文档） |
| **约定** | 此后的推送仍由项目所有者决定，**不属于开发默认动作** |

**解决于** 2026-09-17，推送范围 `010db2f..7ed495a`。

推送前的安全检查（5 项）全部通过：工作区干净；6 个待推送提交；`.env`/`credentials.env`/`dsh-home/`
均为误跟踪且历史上从未被 `add`；31 个提交的全历史扫描只命中测试哨兵常量
`sk-SENTINEL-DO-NOT-LEAK-…`（13 处，全在 `core/tests/test_key_handling.py`）。

---

# E 类 · 技术债（开发可自行处理）

## E1　3 条食性表缺 `review_status`

> **状态：已解决（2026-09-17）** —— 随 A1 的 D5 批次一并补齐，三条奶茶已写入 `review_status: "pending"`。

| | |
|---|---|
| **现状** | ~~3 条缺字段~~ → **0 条**。三条奶茶（冰奶茶、去冰奶茶、热奶茶）已随 2026-09-17 的 D5 批次补上 `review_status`，现全表 147 条字段统一 |
| **成因** | 这三条是在 `patch_food_table.py` 那次三态迁移之后加入的，漏走了迁移 |
| **✅ 行为本来就正确，不是 bug** | `food_lookup.py:454-457` 有兼容回退：`status = "approved" if entry.get("reviewed") else "pending"`。这三条 `reviewed` 均为 `false` → 被正确当成 `pending` → 界面照常标「待验证」。实测 `patch_food_table.py --dry-run` 确认：迁移这 3 条后分布为**已通过 0 / 待审核 147 / 不通过 0** |
| **影响** | 原本无功能性影响，**仅数据字段不统一**。风险是以后有人写脚本只读 `review_status`、不做回退，就会漏掉这 3 条 —— 这正是后来补它的理由 |
| **怎么解的** | 在 `core/scripts/patch_food_table.py` 的 `ENTRY_FIXES` 里给这 3 条补 `review_status: "pending"`，再跑 `python scripts/patch_food_table.py`（数据改动走正规通道，幂等、强制 LF） |
| **验收标准** | 全表 147 条全部有合法 `review_status`（三态之一）。`core/tests/test_handover_docs.py::test_pending_e1_matches_actual_data_state` 已由「恰好 3 条缺字段」的**数据快照**改为**派生不变式**（有缺即红 + 概览状态必须已关） |

## E2　`herbs.json` 34 味缺逐条审核字段

| | |
|---|---|
| **现状** | `herbs.json` 的 34 味条目**完全没有逐条审核字段**：既无 `review_status`，也无 `reviewed` / `reviewed_by` / `reviewed_at`。审核状态只存在于文件级的 `_meta.review_status`（值为 `pending`） |
| **为何单列** | A1 原先把 `food_properties.json` 与 `herbs.json` 并列描述成「逐条 `review_status` 全 pending」。实测对 herbs **不成立**——34 味里没有一条含该字段 |
| **影响** | ① A1 的验收标准（每条 approved 都要有 `reviewed_by` + `reviewed_at`）对 herbs 无从落地，那些字段在 herbs 里根本不存在；② 以后有人写脚本按 `review_status` 过滤 herbs 会**全部落空且不报错**，属于静默失败 |
| **为什么现在没补** | 补字段要先定方案：照搬 `food_properties.json` 的三态 + 审核人字段，还是只加 `review_status`。**这决定审核流程怎么走**，属于数据结构的决定——按项目所有者的规则不擅自改（同 E1 的处理原则） |
| **需要什么** | 先定字段方案（**建议与 `food_properties.json` 对齐**：三态 + `reviewed_by` / `reviewed_at` / `review_note`），再一次性补齐 34 味 |
| **验收标准** | 34 味全部有合法 `review_status`（三态之一），且审核时能填 `reviewed_by` / `reviewed_at` |
| **相关文件** | `core/data/herbs.json`、`core/data/food_properties.json`（参照其后者的条目字段体系） |

---

# 本次巡检的其他发现

以下几项不是「挂起事项」（已解决或已记录），但交接时值得知道：

| 项 | 结论 |
|---|---|
| 仓库根残留一个半成品 `.venv` | 已装发行版数约为 `core/.venv` 的 1/5，缺 pytest/fastapi/httpx/dotenv。**真正可用的是 `core/.venv`**。用错会报 `No module named pytest`。建议删掉根 `.venv`（绝对包数随安装而变，故不写死） |
| 全仓库无残留 API Key | 扫描 `sk-` 长串（排除 `.git`/`.venv`/`dsh-home`）**无命中**；`credentials.env` 只剩 `DSH_HOME` |
| `miniprogram/` 空目录已删除 | 转型遗留 |
| 三份生成型文档的测试已就位 | 分别有 18 / 23 / 26 项测试守着「层次不混淆」「快照不漂移」「差异不被静默改成一致」 |
| 交接文档自身也有测试 | 26 项，校验章节齐备、挂起项 ID 唯一且都有责任人与状态、引用的仓库路径真实存在、文档里没有 Key 材料 |
| 之前一处文档写错了影响面 | 参考数据曾写「四气差异会影响三层判定里的寒热加减」，经代码取证**是错的**，已更正（见 B1 的差异影响） |
| 维护文档的规模数字整体过时 | 已按 Python 口径重测更新（§1.4 与 §3 两张表）；顺带记录「别用 PowerShell 数行数」的陷阱 |
| 两个 venv 的 Python 都是 3.13.13 | 与 `pyproject.toml` 的 `requires-python = ">=3.10"` 兼容 |
| `NOTES.local.md` 已部分过期 | 仍写「尚无远程」「`miniprogram/` 空目录待删」「全部提交都是占位符身份」「pytest 230 项」，均与现状不符。它不入版本控制、不会随文档同步；已在 `docs/handover.md` §9.2 加了「以 `docs/` 为准」的提醒 |

---

## 更新约定

1. 任何一项**解决**后：更新本文的状态列，并在该项下补一行「**解决于** `<日期> <commit>`」。
2. 新增挂起项：按类别分配 ID（A 类对外阻碍 / B 类协作方 / C 类外部资料 / D 类决定 / E 类技术债）。
3. **本文是唯一真源**：`handover.md` 与 `maintenance.md` 只放摘要 + 指向本文的链接，不要在那儿复制明细。
4. 有测试校验本文的结构完整性（每个 ID 唯一、每项都有责任人与状态），改动后跑 `pytest -q`。
