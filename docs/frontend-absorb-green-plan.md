# 吸收同学前端 · 🟢 四项方案

> **本轮只出方案，未改动任何代码与数据。**
> 日期：2026-09-18　对照基线：`1eb3d0b`（442 passed）　依据：`docs/frontend-fork-assessment.md` §6
> 改动对象只有一个文件：`ui/web/index.html`（主线 477 行，LF、无 BOM）
>
> ✅ **2026-09-18 五项全部拍板，§6 是最终执行稿**（开工按 §6，§2/§4 保留论证过程）。

---

## 0. 先说三条会改变执行方式的实测事实

### 0.1 分叉拷贝已不在本机（影响"怎么改"）

`D:\work\tea-advisor-main\tea-advisor-main\ui\web\index.html`（1791 行）**已不在盘上**：
全盘扫描 >800 行的 `index.html` = **0 个**，`D:\work\` 下只剩第一次评估的
`tea-advisor-main-assessment.md`。

⇒ **本轮不能"照着他的代码改"**，只能按评估报告里的引用片段 + 主线现状重写。
对 🟢 四项影响不大（它们只是 UI 形态）；对 🟡 第 5 项「记忆逻辑」影响大——那段
`sessionStorage → localStorage` 搬迁代码只在报告 §4.1 有摘录。**继续做 🟡 之前建议先向同学重新要一份。**

### 0.2 主线前端零测试覆盖（影响"测试影响"这一节）

`core/` 内提到 `ui/web/index.html` 的只有 3 处，**全是注释或文档字符串**：

| 位置 | 性质 |
|---|---|
| `core/pyproject.toml:18` | 注释（web extra 说明） |
| `core/app/main.py:10` / `:185-189` | docstring + `FileResponse`（静态托管） |
| `core/scripts/build_herb_crosscheck.py:105` | docstring |

**没有任何测试读取或断言它。**
⇒ 改 HTML 不会让 442 变红；反过来，**回归只能靠人眼**，除非本轮新增守卫（§2.3）。

### 0.3 高风险分支本来就不要 Key（一个反直觉但有用的事实）

`core/app/services/orchestrator.py:229-244` 的顺序是 **安全分支 → 体质闸门 → 凭据校验**，
注释明写「刻意放在凭据校验之前」。所以 `/api/analyze` 不带 `Authorization` 头、
但文本命中高风险关键词时，**返回引导就医，不返回 400 `NO_API_KEY`**。

（测试指引第 3 步说的「秒回、不调用模型、免费」，在**没填 Key** 时也成立。）
这条在 §2.4 会用到。

### 0.4 工作区不是"干净"

`git status --short` 有两个未跟踪文件：`docs/analyze-offline-plan.md`、
`docs/frontend-fork-assessment.md`（上一轮产出，尚未提交）。提交顺序里列为第 0 步。

---

## 1. 总账：4 项在主线其实是 3 个改动

| 评估编号 | 项 | 主线有没有落点 | 判定 |
|---|---|---|---|
| ① | API 配置收进弹窗 | 有（Key 区现在在输入卡里，`index.html:171-183`） | ✅ 做 |
| ② | 配置移出对话区 | **主线没有对话区** ⇒ 与 ① 是同一次改动 | ✅ 并入 ① |
| ⑪ | 「重新分析」按钮 | 有（结果区没有重跑入口） | ✅ 做 |
| ④ | 模式切换隐藏输入框 | **主线没有模式切换，也不会有第二个输入框** | ⚠️ 建议改判，见 §2.4 |

**① 和 ② 在主线合并**：主线是单页、无对话区，API 配置本来就只存在一处（输入卡底部），
「移出对话区」和「收进弹窗」是同一个动作的两端。

---

## 2. 逐项方案

### 2.1 ①+② API 配置收进右上角弹窗

**现状定位**（`ui/web/index.html`）

| 内容 | 行号 |
|---|---|
| `header`（h1 + p，无按钮位） | 119-122 |
| Key 输入行（`label#key` + `input#key` + `label.chk#remember`） | 171-178 |
| `#keyHint`（`/healthz` 提示写这里） | 179-183 |
| `keyEl` / `rememberEl` / `keyHintEl` 取元素 | 199-201 |
| `loadStoredKey` / `saveKey` / `currentKey` | 210-236 |
| `refreshKeyHint()`（调 `/healthz`，写 `#keyHint`） | 239-261 |
| `run()` 里凭据错误分支 + `keyEl.focus()` | 390-398 |
| `rememberEl` / `keyEl` 的 `change` 监听 | 471-472 |

**怎么改（按项目原则，不照抄）**

1. **容器用原生 `<dialog id="cfg">`**（不用他的水墨 overlay）：
   自带 Esc 关闭、`::backdrop`、焦点陷阱，主线无框架，这是最省事且最不容易写错的一档。
   `<form method="dialog">` + `<button value="close">完成</button>` 原生关闭
   （副作用：在 Key 框里按回车会关闭弹窗——可接受，甚至顺手）。
2. **入口放 header 右上角**：`<button id="cfgOpen">API 设置</button>`，header 改 flex。
   不用他的装饰类名，沿用主线 `button` 样式。
3. **原样搬入**：`171-183` 整块（含 `.chk` 的 `title` 提示）进弹窗，
   `#keyHint` 一起搬——**`/healthz` 提示必须跟着走**（他没做，主线已有，不能丢）。
4. **打开时刷新一次提示**：`cfgOpen.onclick = () => { cfg.showModal(); refreshKeyHint(); }`。
   页面初始化时后端可能还没起，打开弹窗时再取一次 `/healthz` 更准。
5. **主界面补一行 Key 状态**：`<div class="hint" id="keyState">`
   （「未填写 API Key · 打开设置」/「已填写（本页不会显示）· 打开设置」）。
   **这是"配置移出"的代价，必须补**——Key 是 `password` 类型，收进弹窗后主界面完全看不到填没填，
   不补就是让用户盲猜，属静默失效。只显示两级状态，**不显示 Key 的任何部分**。

**三个照抄会踩的坑（本方案逐条规避）**

| # | 坑 | 处理 |
|---|---|---|
| 1 | `run()` 凭据错误时 `keyEl.focus()`（:398）—— 元素进了未打开的 `<dialog>` 后 **focus 无效**，用户看到报错却找不到该去哪 | 改成 `if (isKeyIssue) { openCfg(); keyEl.focus(); }`，**自动打开弹窗再聚焦** |
| 2 | 同一分支的文案写死「见上方 API Key 一栏」（:393）——搬走后方位描述失效 | 改成「已为你打开右上角「API 设置」」 |
| 3 | 弹窗里再显示一遍后端信息，与 `#keyHint` 的双份状态可能漂移 | 只有一处渲染函数（`refreshKeyHint`），弹窗不另写一套 |

**三处必须原样保留（记忆逻辑属 🟡 第 5 项，本轮不动）**

- `<input id="remember" type="checkbox" />` **不带 `checked`**（:176）——主线本就默认不勾，与他的 `checked` 相反；
- `loadStoredKey()` 的 `sessionStorage` 分支**只回填、不搬迁到 localStorage**（:215-218）；
- `saveKey()` **先清两处、再按勾选写一处**（:223-231）。

搬家时这三处是"整块剪切"，不是"重写"。

**人工验收清单**（静态守卫挡不住"弹窗点不开"，必须过一遍）

1. 空 Key 直接点「给我建议」→ 400 `NO_API_KEY` → **弹窗自动打开且焦点在 Key 框**，提示里仍有 `/healthz` 那两句。
2. 勾 / 不勾「记住 Key」各一次 → 刷新页面，行为与改动前一致（不勾则新标签页为空）。
3. `TA_BACKEND=dsh` 启动 → 弹窗里出现红色「当前后端不支持自带 Key」（`user_key_supported=false` 分支）。
4. Esc 能关；关闭后主界面状态行正确（已填 / 未填）。
5. 输入「我怀孕了，今天吃了火锅」→ 即使**没填 Key** 也秒回引导就医（§0.3 的事实，别在这里误判成"没填 Key 所以该报错"）。

---

### 2.2 ⑪ 「重新分析」按钮

**落点**：结果区最后一张卡（与 `meta` 行同卡，`run()` 里拼 html 的地方，:406-411）。
**行为**：调用同一个 `run()`，用 **textarea 的当前值**（不是缓存的上次输入）。

**四条要点**

1. **busy 同步**：现在只有 `btn.disabled = true/false`（:372 / :418）。新增按钮必须一起管——
   写一个 `setBusy(b)` 同时切 `#go` 与「重新分析」，否则「重新分析」可连点。
   注意 `run()` 开头 `if (!text) return`（:366）在 disabled **之前**，空输入时按钮仍处于可点状态。
2. **费用提示必须写**：按钮旁一行 `.hint`「会再次调用模型（约 1 分钱），按当前输入框内容重新分析」
   （成本口径见 `handover.md` §5.4：一次完整查询约 1.02–2.03 分）。不写这行等于诱导重复付费。
3. **语义要写明**：改了输入框内容再点，分析的是**新内容**——与「重新分析上一次」的直觉相反，
   所以文案必须是「按当前输入重新分析」，不是「重新分析」。
4. **事件委托绑定**：按钮在 `out.innerHTML` 里，每次 render 都会重建。
   沿用 `#examples` 已有的委托写法（:464-469），不要每次 render 后 `addEventListener`。
   样式沿用主线 `button` + `.hint`，**不搬他的水墨/涟漪/呼吸动画**。

---

### 2.3 测试影响

**现有 442：不受影响。** 依据 §0.2 的实测——没有任何测试读 `ui/web/index.html`；
本轮**不动 Python、不动数据、不动端点**。

**新增 `core/tests/test_web_shell.py`**（建议），静态守卫 `index.html`，约 6 项：

| # | 守卫 | 挡什么 |
|---|---|---|
| 1 | `#remember` **不带** `checked` 属性 | 「默认记住 Key」复辟（他的版本自带 `checked`） |
| 2 | 全文不含 `sessionStorage → localStorage` 的搬迁模式 | 静默把"仅本标签页"升级成长期存储 |
| 3 | `refreshKeyHint` 仍被调用，`#keyHint` / `KEY_HINT_DEFAULT` 都在 | 搬弹窗时把 `/healthz` 提示弄丢 |
| 4 | 弹窗容器 + 打开入口存在，凭据错误分支有 `openCfg()` | 报错却打不开弹窗（§2.1 坑 1） |
| 5 | Key 状态指示行存在 | 配置收进弹窗后主界面看不见状态（§2.1 第 5 点） |
| 6 | `#go` 与「重新分析」走同一个 busy 开关 | 连点重复付费 |

路径解析沿用 `core/tests/test_handover_docs.py:16-20` 的既有写法
（`CORE_DIR → PROJECT_ROOT → ui/web/index.html`），不新造约定。

> ⚠️ **一处需要你拍板的冲突**：`handover.md` §2.6 的验收是
> 「删掉 `ui/` 目录，`core/` 必须仍然通过 `pytest`」。新增的 HTML 守卫会让这条**在字面上不成立**。
> - **(甲)** 文件缺失时 `fail`（不 skip），并在 §2.6 补一句例外
>   （「静态守卫除外，可用 `-k 'not web_shell'` 排除」）—— **推荐**：
>   skip 版会造成"样本被治理偷走"式的静默失效（路径一旦算错就永远跳过，还显示通过）。
> - **(乙)** 不进 pytest，写成 `core/scripts/check_web_shell.py`（`--check` 进 CI，
>   与 `build_*.py` 同风格）——不动 §2.6 口径，但**不是自动守卫**。
> - **(丙)** 不写守卫，只留人工验收清单——最省，但回归全靠记忆。

**边界要说清**：静态守卫挡得住"代码被改坏"，挡不住"弹窗点不开"。
所以每项配人工验收清单（§2.1 末），提交前跑一遍。

---

### 2.4 ④ 模式切换隐藏输入框 —— 建议改判为「不适用」

三条实测理由：

1. **主线没有模式切换**：单页单模式（必须填 Key）。他有两种模式
   （⚡ 规则速览离线 / 🌐 联网对话），主线连离线模式都没有——那要等 `/api/analyze-offline` 立项
   （见 `docs/analyze-offline-plan.md`）。
2. **主线也永远不会有第二个输入框**：他隐藏的是"饮食输入框"，因为对话区自带输入框；
   而 `/api/chat` 本轮判定 🔴 不吸收（四道护栏一道不走）。没有对话区 ⇒ 没有第二个输入框
   ⇒ **没有可隐藏的东西**。
3. **即使将来有离线模式，主线两种模式都需要饮食输入**：主线若做离线，语义是
   "把你这顿饭过一遍规则"（`matcher.fallback_recommend` 那条链），仍要输入框；
   他那版的"规则速览"是不用输入的，是另一回事。所以在主线做「切换即隐藏输入框」是**反向有害**的。

**建议：④ 从 🟢 改判为 ⚪ 不适用（不吸收）**，等 `/api/analyze-offline` 立项时一并重新评估。
若坚持现在做，唯一诚实的形态是"先做模式切换骨架、第二种模式禁用"——不建议，那是形式主义。

---

## 3. 提交顺序

每步**前**跑 `pytest -q`（期望仍 442），每步**后** `git status --short` 复核落盘范围。

| 步 | 内容 | 说明 |
|---|---|---|
| **0** | 提交两份未跟踪文档：`docs/analyze-offline-plan.md` + `docs/frontend-fork-assessment.md` | `docs:` 提交，与代码分开 |
| **1** | ①+② 弹窗搬家（记忆逻辑三处原样保留）+ 守卫 1–5 | 纯 UI；与守卫同批，避免出现"改完了没守卫"的窗口 |
| **2** | ⑪ 重新分析按钮 + `setBusy` 同步 + 守卫 6 | 独立可回滚 |
| **3** | 文档收尾：`handover.md` §2.6 例外说明（若选甲）、§5.1 行数表（可选） | ⚠️ **不要动 `pending-items.md`**：这四项做完即关闭，不是挂起项；而它有结构校验测试，手抖改坏会红 |

理由：弹窗与按钮是两处独立改动，分开提交便于回滚。

---

## 4. 拍板结果（2026-09-18 全部通过）

| # | 问题 | 结果 |
|---|---|---|
| 1 | ④ 改判「不适用」 | ✅ 接受（三条理由成立：无模式切换／`/api/chat` 不吸收／主线离线模式仍需饮食输入） |
| 2 | 守卫落法 | ✅ **甲**：进 pytest + `handover.md` §2.6 补例外；**fail 不 skip** |
| 3 | 弹窗容器 | ✅ 原生 `<dialog>` |
| 4 | Key 状态粒度 | ✅ 只两级（已填写 / 未填写），不显示 Key 任何部分 |
| 5 | 空输入时禁用「重新分析」 | ✅ 不禁用，与「给我建议」行为一致 |

另已确认：`core/tests/test_web_shell.py` 文件缺失时**报错**而非跳过；记忆逻辑三处整块剪切不改一行。

---

## 5. 边界（本轮不做）

- 不动 `core/` 任何 Python、不动数据、不动端点。
- 🟡 四项、🔴 三项一律不动；`/api/chat` 不因本项解禁。
- **A1（147 条全部未人工审核）状态不变，仍是唯一硬阻碍** —— 这四项纯 UI，
  既不推进也不削弱它。

---

## 6. 最终执行稿（2026-09-18 五项已拍板）

> 本节是开工稿。行号均以 `1eb3d0b` 的 `ui/web/index.html`（477 行）为准。
> **约定**：所有改动只碰 `ui/web/index.html` + 新增 `core/tests/test_web_shell.py`
> + `docs/handover.md`（一行例外说明）。**其余文件一律不动。**

## 6.1 提交 1 —— ①+② API 配置收进 `<dialog>` 弹窗

### 6.1.1 CSS（在 `</style>` 前追加，约 12 行）

```css
  header.bar { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
  button.ghost { background: transparent; color: var(--accent); border: 1px solid var(--line); padding: 7px 14px; font-weight: 500; }
  dialog#cfg { border: 1px solid var(--line); border-radius: 12px; padding: 18px; max-width: 520px; width: calc(100% - 32px); color: var(--ink); }
  dialog#cfg::backdrop { background: rgba(46, 42, 36, .35); }
  dialog#cfg h2 { margin-top: 0; }
  .cfgstate { font-size: 12.5px; color: var(--muted); }
  .cfgstate .dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 6px; vertical-align: 1px; }
  .cfgstate.off .dot { background: var(--warn); }
  .cfgstate.on .dot { background: #3f7a48; }
```

### 6.1.2 header（替换 119-122）

```html
<header class="bar">
  <div>
    <h1>今日茶饮建议</h1>
    <p>说说你今天吃了什么，结合你的体质给一杯药食同源的冲泡建议 · 本地运行</p>
  </div>
  <button id="cfgOpen" class="ghost opencfg" type="button">API 设置</button>
</header>
```

### 6.1.3 主卡片内（替换 170-183：原 `hr` + Key 行 + `#keyHint`）

```html
    <hr style="border:0;border-top:1px solid var(--line);margin:14px 0 12px" />
    <div class="row" style="margin-top:0">
      <span class="cfgstate off" id="keyState"><span class="dot"></span>未填写 API Key</span>
      <button class="ghost opencfg" type="button">打开设置</button>
    </div>
```

### 6.1.4 弹窗（新增，放在 `</main>` 之后、`<script>` 之前）

```html
<dialog id="cfg">
  <form method="dialog">
    <h2>API 设置</h2>
    <div class="row" style="margin-top:0">
      <label for="key">API Key</label>
      <input id="key" type="password" autocomplete="off" spellcheck="false"
             placeholder="sk-…（必填；本服务不内置 Key）" />
    </div>
    <div class="row">
      <label class="chk" title="勾选后写入浏览器 localStorage；不勾选只存在本次标签页，关掉即失效">
        <input id="remember" type="checkbox" /> 记住 Key
      </label>
    </div>
    <div class="hint" id="keyHint">
      你的 Key 只随本次请求通过 Authorization 头发给本机后端，再由后端转给模型服务；
      <b>不写入服务器日志、不落盘、不入库</b>。
      默认不勾选「记住 Key」，只保存在本标签页内。
    </div>
    <div class="row"><button type="submit" value="close">完成</button></div>
  </form>
</dialog>
```

> ⚠️ **`#keyHint` 的默认文案必须原样带过来，不能留空**：`KEY_HINT_DEFAULT = keyHintEl.innerHTML`（:208）
> 在脚本执行时就把它抓走当兜底文案（`refreshKeyHint()` 失败时回填）。留空 ⇒ 兜底文案变成空串。
> 这是搬家过程中**第四个**容易踩的坑（前三个见 §2.1）。

### 6.1.5 JS 改动（6 处）

| # | 位置 | 改动 |
|---|---|---|
| 1 | `:201` 后 | 新增 `const cfgEl = document.getElementById('cfg');` 与 `const keyStateEl = document.getElementById('keyState');` |
| 2 | `refreshKeyHint()` 后（:261 后） | 新增 `openCfg()` 与 `updateKeyState()`（代码见下） |
| 3 | `loadInit()` :276-277 | `loadStoredKey();` 之后加一行 `updateKeyState();` |
| 4 | `run()` :391-398 | 凭据分支文案 + 行为（见下） |
| 5 | `:470-472` 监听区 | 保留原两行不动，**追加**三行 |
| 6 | —— | `saveKey()` / `loadStoredKey()` / `#remember` 三处**一个字符都不改** |

```js
function openCfg() {
  if (!cfgEl) return;
  if (typeof cfgEl.showModal === 'function') cfgEl.showModal();
  else cfgEl.setAttribute('open', '');   // 极老浏览器兜底
  refreshKeyHint();   // 后端可能是在页面打开之后才启动的，打开时再取一次 /healthz
}

/** 主界面只显示「已填写 / 未填写」两级；绝不回显 Key 的任何部分 */
function updateKeyState() {
  if (!keyStateEl) return;
  const filled = !!currentKey();
  keyStateEl.className = 'cfgstate ' + (filled ? 'on' : 'off');
  keyStateEl.innerHTML = '<span class="dot"></span>'
    + (filled ? '已填写 API Key（本页不显示）' : '未填写 API Key');
}
```

`run()` 凭据分支（:391-398）改为：

```js
      const extra = isKeyIssue
        ? '<div class="hint">已为你打开右上角「API 设置」。</div>'
        : '<div class="hint">排查：打开 <code>http://127.0.0.1:8000/healthz</code> '
          + '看后端与饮片是否就绪。</div>';
      out.innerHTML = `<div class="card error"><b>${isKeyIssue ? '凭据问题' : '出错了'}</b><br>`
        + `${esc(d.message || JSON.stringify(data))}${extra}</div>`;
      // Key 输入框在 <dialog> 里：不先打开弹窗，focus() 是无效的
      if (isKeyIssue) { openCfg(); if (keyEl) keyEl.focus(); }
```

监听区（**保留** `rememberEl`／`keyEl` 的 `change` → `saveKey` 两行，追加）：

```js
keyEl.addEventListener('input', updateKeyState);    // 只更新状态，不写存储
keyEl.addEventListener('change', updateKeyState);
rememberEl.addEventListener('change', updateKeyState);
document.querySelectorAll('.opencfg').forEach(b => b.addEventListener('click', openCfg));
```

> 为什么用 `input` 而不是把 `saveKey()` 也挂上：原代码刻意「在提交时落定，避免每敲一个键就写一次存储」
> （:368 注释）。状态指示要**实时**，存储时机要**不变** ⇒ 两条监听分开。

## 6.2 提交 1 的守卫 1–5（`core/tests/test_web_shell.py`）

**文件骨架**（路径写法沿用 `core/tests/test_handover_docs.py:16-20`）：

```python
CORE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = CORE_DIR.parent
WEB = PROJECT_ROOT / "ui" / "web" / "index.html"


def _html() -> str:
    # 文件缺失时**报错**不跳过：skip 会造成「样本被治理偷走」式的静默失效。
    # handover §2.6 的例外：删掉 ui/ 时用 -k "not web_shell" 排除本文件。
    assert WEB.is_file(), f"缺少 {WEB}（若已删除 ui/，请用 -k 'not web_shell' 排除本组测试）"
    return WEB.read_text(encoding="utf-8")
```

**五项检查**都写成**纯函数**（入参 `html: str`），这样正控（真实文件通过）与负控（合成坏样本被抓出）
共用同一份判定代码 —— 与 `_cautions_soft_gap()` 的写法一致。

| # | 检查 | 判据（派生不变式，不写死文案） | 负控制（合成样本） |
|---|---|---|---|
| 1 | `#remember` 默认不勾 | 取出 `id="remember"` 的那个标签，`checked` 不在其中 | 给该标签加 `checked` → 必须被抓出 |
| 2 | 无 sessionStorage→localStorage 搬迁 | 每处 `localStorage.setItem` 的前 200 字符内必须出现 `rememberEl.checked` | 合成一段 `sess = sessionStorage.getItem(...)` + `localStorage.setItem(KEY_LS, sess)` → 必须被抓出 |
| 3 | `/healthz` 提示仍在 | 同时含 `refreshKeyHint`、`/healthz`、`id="keyHint"`、`KEY_HINT_DEFAULT` | 删掉 `refreshKeyHint` 调用 → 必须被抓出 |
| 4 | 凭据错误会打开弹窗 | `isKeyIssue` 之后 300 字符内出现 `openCfg`（或 `showModal`） | 只留 `keyEl.focus()` 不调 `openCfg` → 必须被抓出 |
| 5 | Key 状态指示存在且不回显 Key | 有 `id="keyState"`；`keyStateEl.innerHTML` 的赋值里**不含** `keyEl.value` ／ `currentKey()` 的返回值 | 把 `keyEl.value` 写进 `keyState` → 必须被抓出 |

## 6.3 提交 2 —— ⑪ 「按当前输入重新分析」按钮

| # | 位置 | 改动 |
|---|---|---|
| 1 | `:407-411`（结果 html 拼装末尾） | 追加一张卡：按钮 `#again` + 一行费用/语义提示 |
| 2 | `:372` / `:418` | `btn.disabled = true/false` → `setBusy(true/false)`（**`loadInit` 里 :289 那处不动**，那是初始化失败，语义不同） |
| 3 | `run()` 之前 | 新增 `setBusy(b)` |
| 4 | `:464-469` 委托区 | 给 `#out` 加一个委托监听，命中 `#again` 就 `run()` |

```js
function setBusy(b) {
  btn.disabled = b;
  const again = document.getElementById('again');
  if (again) again.disabled = b;
}
```

```html
    <div class="card"><div class="row" style="margin-top:0">
      <button id="again" type="button">按当前输入重新分析</button>
      <span class="hint">会再次调用模型（约 1 分钱），以输入框里的当前内容为准。</span>
    </div></div>
```

```js
// 结果区是整体重绘的，按钮每次都换新 ⇒ 用委托，不要 render 后 addEventListener
document.getElementById('out').addEventListener('click', e => {
  if (e.target && e.target.id === 'again') run();
});
```

**两条语义要点**（文案里已经写死，别简化掉）：
① 「按当前输入」——改了输入框再点，分析的是新内容，与「重跑上一次」的直觉相反；
② 「约 1 分钱」——`handover.md` §5.4 的口径，不写等于诱导重复付费。
③ **空输入不禁用**：点了照样走 `run()` 的「先说说你吃了什么吧」，与「给我建议」一致。

## 6.4 提交 2 的守卫 6

| # | 检查 | 判据 | 负控制 |
|---|---|---|---|
| 6 | busy 开关同时管两个按钮 | 存在 `function setBusy`，且 `setBusy` 内引用了 `btn.disabled` 与 `document.getElementById('again')`；全文 `btn.disabled` 出现次数 **≤ 2**（`setBusy` 内 1 + `loadInit` 内 1） | 只有 `btn.disabled` 没有 `setBusy` → 必须被抓出 |

## 6.5 提交 3 —— 文档收尾

只改 `docs/handover.md` §2.6，在「验收方式很硬核……」那句下面追加：

```markdown
> ⚠️ **唯一的例外**：`core/tests/test_web_shell.py` 是 `ui/web/index.html` 的静态守卫，
> 它必须读到那个文件。**删掉 `ui/` 时请用 `pytest -k "not web_shell"` 排除它** ——
> 分层约束（删掉 `ui/` 后 `core/` 仍能独立工作）依然成立，
> 只是这条守卫本身依赖它被守卫的对象。
```

可选（你若要求同步）：§5.1 规模表的 `ui/web` 行数 449 → 实测值。
⚠️ **`docs/pending-items.md` 一个字都不要动** —— 这四项做完即关闭，不是挂起项；而它有结构校验测试。

## 6.6 人工验收清单（每个提交前跑一遍）

静态守卫挡不住"弹窗点不开"，必须过一遍浏览器：

1. 空 Key 点「给我建议」→ 400 `NO_API_KEY` → **弹窗自动打开、焦点在 Key 框**，提示里仍有 `/healthz` 那两句。
2. 勾 / 不勾「记住 Key」各一次 → 刷新页面，行为与改动前一致（不勾则新标签页为空）。
3. `TA_BACKEND=dsh` 启动 → 弹窗里出现红色「当前后端不支持自带 Key」。
4. Esc 能关弹窗；关闭后状态行正确（已填 / 未填）。
5. 输入「我怀孕了，今天吃了火锅」→ **即使没填 Key** 也秒回引导就医（§0.3，别误判成"没填 Key 该报 400"）。
6. 结果区「按当前输入重新分析」：点一次能跑；跑的过程中两个按钮都灰；结果出来后按钮回来。

## 6.7 提交顺序与信息草稿

| 步 | 命令/内容 | 期望 |
|---|---|---|
| 0 | `git add docs/analyze-offline-plan.md docs/frontend-fork-assessment.md` | 两份上一轮产出 |
| 1 | `ui/web/index.html` + `core/tests/test_web_shell.py`（守卫 1–5） | pytest 442 → **452** |
| 2 | `ui/web/index.html`（按钮 + `setBusy`）+ 守卫 6 | pytest 452 → **454** |
| 3 | `docs/handover.md` §2.6 例外 + 本方案文档 | pytest 454（不变） |

提交信息（用 `git commit -F <文件>`，`core/var/` 用完删）：

- 0：`docs: 补录 analyze-offline 与前端分叉评估两份方案文档`
- 1：`feat(web): API 配置收进弹窗，主界面补 Key 状态指示\n\n纯 UI 搬家：Key 区从输入卡移入 <dialog>，\n/healthz 提示随行；凭据错误时自动打开弹窗再聚焦。\n记忆逻辑三处原样保留，不随本次改动。\n新增 core/tests/test_web_shell.py 静态守卫（1-5）。`
- 2：`feat(web): 结果区加「按当前输入重新分析」\n\n与「给我建议」共用 setBusy，防连点重复计费；\n文案写明会再次调用模型与费用量级。守卫 6。`
- 3：`docs(handover): §2.6 补"删 ui/ 时排除 web_shell 守卫"的例外`

## 6.8 风险与回滚

- **风险最低的一项**：本轮不动 Python 主逻辑、不动数据、不动端点，纯静态壳；`pytest` 现有 442 项预期全绿。
- **回滚**：两个提交各自独立，任一出问题 `git revert` 即可，`ui/web/index.html` 无状态、无迁移。
- **唯一新增的永久约束**：`core/tests/test_web_shell.py` 让「删掉 `ui/` 仍过 pytest」需要 `-k "not web_shell"`
  （已写进 §2.6 例外，且测试报错信息里也提示了这条命令）。
