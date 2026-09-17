# 挂起事项清单

> **这份清单是挂起事项的唯一真源。** 其他地方（`handover.md`、`maintenance.md`）只提摘要，
> 一律以本文为准。任何一项解决了，就在这里更新状态并记录解决方式。
>
> 快照时间：**2026-09-17**　共 **9** 项记录在案（A/B/C/D/E 五类），
> 其中 **D2 已于本次推送解决**，其余 8 项待处理。

---

## 概览

| ID | 事项 | 谁来解 | 阻塞什么 | 状态 |
|---|---|---|---|---|
| **A1** | 146 条食性数据全部未人工审核 | 具备资质的中医师/中药师 | ⛔ **对外提供服务** | 待人工 |
| **B1** | 7 处药典不一致待复核 | nanple | 数据准确性（不阻塞功能） | 待 nanple |
| **B2** | 问卷项目 `phlegm_dampness` 拼写不一致 | nanple | 问卷接入 | 待 nanple |
| **B3** | 244 个配伍判定 | nanple | ⛔ **体质模型 5→9 型** | 待 nanple |
| **C1** | 《中华本草》列全空 | 需取得资料 | 三源交叉验证 | 待外部资料 |
| **C2** | 国标 A 栏是转引，非标准正文 | 需取得资料 | 逐字对齐国标 | 待外部资料 |
| **D1** | 玫瑰花/茉莉花的代码改动 | 项目所有者定时机 | 合规处置落地 | 待实施 |
| **D2** | 本地提交未推送 | 项目所有者 | 协作者看不到这批产出 | ✅ **已解决** |
| **E1** | 3 条食性表缺 `review_status` | 开发 | 无（行为已正确） | 待清理 |

**⛔ 标记的两项是真正的硬阻碍**：只要 A1 和 B3 没解决，「对外提供服务」和「体质模型扩到 9 型」就不能说完成。

---

# A 类 · 对外服务的硬阻碍

## A1　146 条食性数据全部未人工审核

| | |
|---|---|
| **现状** | `food_properties.json` 的 146 条（128 食材 + 18 茶饮）与 `herbs.json` 的 34 味，`review_status` **全部是 `pending`**，没有一条 `approved` |
| **影响** | 所有条目虽按 0.9 置信度参与判定，但界面**必须**标「待验证」。这是刻意的保守设计，不是 bug |
| **为何只有人能解** | `approved` 意味着「真·硬规则库、界面不再标注」，必须由具备资质的中医师/中药师逐条确认，并同时填写 `reviewed_by` / `reviewed_at` |
| **需要什么** | 审核人 + 一份逐条审核流程（`docs/maintenance.md` §9.2/§9.3 有正确姿势） |
| **验收标准** | `review_status` 分布中 `approved` 条数 > 0，且每条 approved 都有 `reviewed_by` + `reviewed_at` |
| **注意** | ⚠️ **不要为了界面好看而批量置 approved**。标记密度就是审核进度的可见反馈，批量置等于把这个反馈抹掉 |

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
| **现状** | 体质模型要从 5 型扩到 9 型，需补阴虚/血瘀/气郁/特禀。**代码量很小（约 100 行）**，卡的是数据：`herbs.json` 里 34 味 × `suitable_constitutions` + 27 味 × `unsuitable_for`，针对 4 个新体质共约 **244 个判定** |
| **为何只有人能解** | **GB/T 46939-2025 只规定体质分类、问卷、计分与判定阈值，不提供任何饮食或饮片建议。** 这 244 条无标准可依 |
| **好消息** | 防错已就位：`filter_by_constitution` 在「该体质一条数据都没有」时**抛错而非静默退化**（静默退化会让阴虚质拿到温补辛温之品，方向相反且从输出表面看不出来）。所以「只加枚举忘了补数据」现在是**安全的失败**，可以分次推进 |
| **需要什么** | nanple（或另一位懂中医的人）给出 244 个判定；或先给一个可接受的初始版本 |
| **验收标准** | 4 个新体质各至少有若干条 `suitable_constitutions` 数据；`pytest` 不再触发 `MissingConstitutionDataError` |
| **相关文件** | `docs/constitution-9-types.md`（已备好的九型资料 + B 栏饮食方向）、`core/data/herbs.json`、`core/data/constitution.json` |
| **附注** | 9 型 id 已全部确认，扩到 9 型时可直接用：`yin_deficiency` / `blood_stasis` / `qi_stagnation` / `special_diathesis` |

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

| | |
|---|---|
| **现状** | `food_properties.json` 里有 3 条只有旧的 `reviewed` 布尔字段、**没有 `review_status`**：**冰奶茶、去冰奶茶、热奶茶**（其余 143 条正常） |
| **成因** | 这三条是在 `patch_food_table.py` 那次三态迁移之后加入的，漏走了迁移 |
| **✅ 行为已正确，不是 bug** | `food_lookup.py:454-457` 有兼容回退：`status = "approved" if entry.get("reviewed") else "pending"`。这三条 `reviewed` 均为 `false` → 被正确当成 `pending` → 界面照常标「待验证」。实测 `patch_food_table.py --dry-run` 确认：迁移这 3 条后分布为**已通过 0 / 待审核 146 / 不通过 0** |
| **影响** | 无功能影响，**仅数据字段不统一**。风险是以后有人写脚本只读 `review_status`、不做回退，就会漏掉这 3 条 |
| **需要什么** | 跑一次 `python scripts/patch_food_table.py`（先 `--dry-run` 确认是 3 条、0 处修正） |
| **为何没顺手做** | 项目所有者要求数据文件改动走显式决定，不擅自改 |
| **验收标准** | 146 条全部有合法 `review_status`（三态之一） |

---

# 本次巡检的其他发现

以下几项不是「挂起事项」（已解决或已记录），但交接时值得知道：

| 项 | 结论 |
|---|---|
| 仓库根残留一个半成品 `.venv` | 只有 16 个包，缺 pytest/fastapi/httpx/dotenv。**真正可用的是 `core/.venv`（64 个包）**。用错会报 `No module named pytest`。建议删掉根 `.venv` |
| 全仓库无残留 API Key | 扫描 `sk-` 长串（排除 `.git`/`.venv`/`dsh-home`）**无命中**；`credentials.env` 只剩 `DSH_HOME` |
| `miniprogram/` 空目录已删除 | 转型遗留 |
| 三份生成型文档的测试已就位 | 分别有 18 / 23 / 26 项测试守着「层次不混淆」「快照不漂移」「差异不被静默改成一致」 |
| 交接文档自身也有测试 | 26 项，校验章节齐备、挂起项 ID 唯一且都有责任人与状态、引用的仓库路径真实存在、文档里没有 Key 材料 |
| 之前一处文档写错了影响面 | 参考数据曾写「四气差异会影响三层判定里的寒热加减」，经代码取证**是错的**，已更正（见 B1 的差异影响） |
| 维护文档的规模数字整体过时 | 已按 Python 口径重测更新（§1.4 与 §3 两张表）；顺带记录「别用 PowerShell 数行数」的陷阱 |
| 两个 venv 的 Python 都是 3.13.13 | 与 `pyproject.toml` 的 `requires-python = ">=3.10"` 兼容 |

---

## 更新约定

1. 任何一项**解决**后：更新本文的状态列，并在该项下补一行「**解决于** `<日期> <commit>`」。
2. 新增挂起项：按类别分配 ID（A 类对外阻碍 / B 类协作方 / C 类外部资料 / D 类决定 / E 类技术债）。
3. **本文是唯一真源**：`handover.md` 与 `maintenance.md` 只放摘要 + 指向本文的链接，不要在那儿复制明细。
4. 有测试校验本文的结构完整性（每个 ID 唯一、每项都有责任人与状态），改动后跑 `pytest -q`。
