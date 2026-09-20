"""ui/web/index.html 的静态守卫。

这个页面此前**零测试覆盖**：`core/` 里提到它的只有注释与 docstring
（`pyproject.toml:18`、`main.py:10/185`、`build_herb_crosscheck.py:105`），
所以改坏了不会让任何既有测试变红。本文件补的是**结构**守卫，只守
「把 API 配置搬进弹窗时最容易丢的东西」，不守文案与样式。

每条检查都写成**纯函数**（入参 `html: str`），这样正控（真实文件通过）
与负控（合成坏样本被抓出）共用同一份判定代码 —— 与
`test_constitution_readiness._cautions_soft_gap` 的写法一致：
只测「真实数据上没报错」与「检查根本没跑」长得一样，那不是测试。

⚠️ `handover.md` §2.6 的例外：删掉 `ui/` 时请用 `pytest -k "not web_shell"`
排除本文件；文件缺失时本组**报错**而非跳过。
"""

from __future__ import annotations

import re
from pathlib import Path

CORE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = CORE_DIR.parent
WEB = PROJECT_ROOT / "ui" / "web" / "index.html"


def _html() -> str:
    # 文件缺失时报错、不跳过：skip 会造成「样本被治理偷走」式的静默失效
    # （路径一旦算错就永远跳过，还显示通过）。
    assert WEB.is_file(), (
        f"缺少 {WEB}（若已删除 ui/，请用 -k 'not web_shell' 排除本组测试）"
    )
    return WEB.read_text(encoding="utf-8")


# ---------------------------------------------------------------- 守卫 1

def _guard1_remember_defaults_off(html: str) -> list[str]:
    """「记住 Key」必须默认不勾 —— 分叉版本自带 `checked`，会把默认不记住抹掉。"""
    tag = re.search(r'<input[^>]*\bid="remember"[^>]*>', html)
    if not tag:
        return ['找不到 id="remember" 的输入框']
    if re.search(r'\bchecked\b', tag.group(0), re.I):
        return [f"#remember 默认被勾选：{tag.group(0)}"]
    return []


# ---------------------------------------------------------------- 守卫 2

# 长期存储按内容分域：**白名单必须写死在这里**，不可以从页面里反推
# —— 反推 ⇒ 新增一个 key 自动合法 ⇒ 守卫恒真。新增长期存储必须来这里显式登记。
SENSITIVE_STORAGE_KEYS = frozenset({"KEY_LS"})            # API Key：必须经勾选把关
PUBLIC_STORAGE_KEYS = frozenset({"CONSTITUTION_KEY", "DIET_HISTORY_KEY"})  # 非敏感：允许无条件持久化


def _guard2_no_session_to_local_upgrade(html: str) -> list[str]:
    """长期存储分域把关：敏感域要勾选，非敏感域要登记，未登记的报红。

    派生不变式：每一次 `(localStorage|browserStore).setItem` 都必须归属一个域——
      · 敏感域（API Key：`KEY_LS`）⇒ 其前 200 字符内必须有 `rememberEl.checked`；
      · 非敏感域（已登记的白名单常量）⇒ 放行；
      · 其余常量 ⇒ 报红（逼着来 `PUBLIC_STORAGE_KEYS` 登记）。

    ⚠️ 只匹配字面 `localStorage.setItem` 时，`browserStore.setItem`（同一个对象的别名）
    会整体落在视野外 —— 那两处体质写入曾经就是这样静默存在的，所以两种写法都要扫。
    """
    bad = []
    hits = list(
        re.finditer(r'(?:localStorage|browserStore)\.setItem\s*\(\s*([A-Za-z_$][\w$]*)', html)
    )
    if len(hits) < 3:
        bad.append(
            f"只扫到 {len(hits)} 处 setItem 调用（应 ≥3：敏感域 1 处 + 非敏感域 ≥2 处）"
        )
    kinds = {"sensitive": 0, "public": 0}
    for m in hits:
        key = m.group(1)
        line = html[:m.start()].count("\n") + 1
        if key in SENSITIVE_STORAGE_KEYS:
            kinds["sensitive"] += 1
            window = html[max(0, m.start() - 200):m.start()]
            if 'rememberEl.checked' not in window:
                bad.append(f"第 {line} 行的 {key}（敏感域）写入没有经 rememberEl.checked 把关")
        elif key in PUBLIC_STORAGE_KEYS:
            kinds["public"] += 1
        else:
            bad.append(
                f"第 {line} 行写入了未登记的长期存储 {key}；"
                "若确实需要，请显式加入 PUBLIC_STORAGE_KEYS"
            )
    if kinds["sensitive"] == 0:
        bad.append("没扫到敏感域（KEY_LS）写入 ⇒ 判据可能已失效")
    if kinds["public"] < 2:
        bad.append(f"非敏感域只扫到 {kinds['public']} 处（应 ≥2：体质 + 饮食历史）")
    return bad


# ---------------------------------------------------------------- 守卫 3

def _guard3_healthz_hint_kept(html: str) -> list[str]:
    """`/healthz` 提示必须跟着搬进弹窗，且默认文案不能留空。

    后者是搬家中第四个坑：`KEY_HINT_DEFAULT` 在脚本执行那一刻就抓走
    `#keyHint` 的内容当兜底，留空 ⇒ 兜底文案变成空串，且只在 `/healthz`
    取不到时才暴露。
    """
    bad = []
    for token in ('refreshKeyHint', '/healthz', 'id="keyHint"', 'KEY_HINT_DEFAULT'):
        if token not in html:
            bad.append(f"缺少 {token}")

    node = re.search(r'<div[^>]*\bid="keyHint"[^>]*>(.*?)</div>', html, re.S)
    if not node:
        bad.append('找不到 #keyHint 节点')
    elif len(re.sub(r'<[^>]+>|\s', '', node.group(1))) < 10:
        bad.append('#keyHint 默认文案为空 ⇒ KEY_HINT_DEFAULT 会变成空串')
    return bad


# ---------------------------------------------------------------- 守卫 4

def _guard4_key_error_opens_dialog(html: str) -> list[str]:
    """凭据错误时必须先打开弹窗再 focus —— 元素在未打开的 `<dialog>` 里 focus 无效。"""
    if 'openCfg' not in html and 'showModal' not in html:
        return ['既没有 openCfg 也没有 showModal']
    for m in re.finditer(r'isKeyIssue', html):
        window = html[m.start():m.start() + 120]
        if 'openCfg' in window or 'showModal' in window:
            return []
    return ['凭据分支（isKeyIssue）没有打开弹窗就直接 focus']


# ---------------------------------------------------------------- 守卫 5

def _guard5_key_state_no_echo(html: str) -> list[str]:
    """主界面必须有 Key 状态指示（配置收进弹窗后就看不见了），且绝不回显 Key。"""
    bad = []
    if 'id="keyState"' not in html:
        bad.append('主界面缺少 Key 状态指示（#keyState）')
    assigns = re.findall(r'keyStateEl\.innerHTML\s*=\s*([^;]*)', html, re.S)
    if not assigns:
        bad.append('没有对 #keyState 的渲染赋值')
    for a in assigns:
        if 'keyEl.value' in a or 'currentKey()' in a:
            bad.append(f"状态指示回显了 Key 的内容：{a.strip()[:40]}")
    return bad


# ---------------------------------------------------------------- 守卫 6

def _guard6_busy_covers_both_buttons(html: str) -> list[str]:
    """busy 开关必须同时管「给我建议」与「重新分析」—— 否则后者可连点、重复计费。"""
    bad = []
    fn = re.search(r'function\s+setBusy\s*\([^)]*\)\s*\{(.*?)\n\}', html, re.S)
    if not fn:
        bad.append('缺少 setBusy()：两个按钮的 disabled 各管各的')
    else:
        body = fn.group(1)
        if 'btn.disabled' not in body:
            bad.append('setBusy 没有管 #go（btn.disabled）')
        if not re.search(r'getElementById\(\s*[\'"]again[\'"]', body):
            bad.append('setBusy 没有管「重新分析」（#again）')

    # 全文只允许两处 btn.disabled：setBusy 内 1 处 + loadInit 里「初始化失败」1 处
    n = html.count('btn.disabled')
    if n > 2:
        bad.append(f"btn.disabled 出现 {n} 次（应为 setBusy 内 1 次 + loadInit 内 1 次）")
    return bad


# ---------------------------------------------------------------- 守卫 7

def _guard7_browser_store_is_local(html: str) -> list[str]:
    """跨会话数据（体质、饮食历史）必须落在 localStorage。

    `browserStore` 是个常量别名；一旦被改成 `sessionStorage`，持久化会静默失效
    （关掉标签页就没了），而没有任何测试会红 —— 所以这里钉死它的落点。
    """
    m = re.search(r'const\s+browserStore\s*=\s*([^;]+);', html)
    if not m:
        return ['找不到 browserStore 的定义（体质/饮食历史的持久化入口消失了？）']
    expr = m.group(1)
    if 'sessionStorage' in expr:
        return [f"browserStore 指向了 sessionStorage ⇒ 跨会话数据会丢：{expr.strip()}"]
    if 'localStorage' not in expr:
        return [f"browserStore 没有指向 localStorage：{expr.strip()}"]
    return []


# ---------------------------------------------------------------- 守卫 8

def _guard8_storage_copy_kept(html: str) -> list[str]:
    """问卷结果必须说清两件事：只存在本机浏览器（换设备要重测）、以及有个「重新测」入口。

    ⚠️ 第二条**不能用关键词匹配**：页面里那句「…需重新测」的说明会把它兜住
    —— 实测把按钮整个删掉后，按「重(?:新)?测」匹配仍然通过（判据恒真）。
    所以直接钉结构：按钮存在 + 事件已绑定。
    """
    bad = []
    if not re.search(r"本机浏览器", html):
        bad.append("少了「结果只存在本机浏览器」的说明")
    if not re.search(r'id="resetQuestionnaire"', html):
        bad.append('少了「重新测」按钮（id="resetQuestionnaire"）')
    if not re.search(r"getElementById\('resetQuestionnaire'\)", html):
        bad.append("「重新测」按钮没有绑定点击事件")
    return bad


# ---------------------------------------------------------------- 守卫 9

def _guard9_questionnaire_fetch_checks_ok(html: str) -> list[str]:
    """问卷的两次 fetch 都必须检查 `res.ok`。

    子包缺失时端点返回 501，不判 ok 就把 `{"detail": "…安装指令…"}` 当成功结果渲染。
    """
    endpoints = ("/api/questionnaire/questions", "'/api/questionnaire'")
    bad = []
    checked = 0
    for ep in endpoints:
        m = re.search(re.escape(ep), html)
        if not m:
            bad.append(f"找不到问卷端点 {ep}")
            continue
        window = html[m.start():m.start() + 400]
        if 'res.ok' in window:
            checked += 1
        else:
            bad.append(f"{ep} 的响应没有检查 res.ok")
    if checked < 2:
        bad.append(f"只有 {checked} 处检查了 res.ok（应 2 处）")
    return bad


# ---------------------------------------------------------------- 负控制样本

BAD1_REMEMBER_CHECKED = '<input id="remember" type="checkbox" checked /> 记住 Key'

BAD2_SESSION_TO_LOCAL = """
const sess = sessionStorage.getItem(KEY_SS);
if (sess) localStorage.setItem(KEY_LS, sess);
"""

# 守卫 3 有两个失效形状，都要能被抓出：丢掉 /healthz 提示、以及默认文案被清空
BAD3_NO_REFRESH = '<div class="hint" id="keyHint">说明文字</div>'
BAD3_EMPTY_HINT = """
async function refreshKeyHint() { fetch('/healthz'); }
const KEY_HINT_DEFAULT = keyHintEl.innerHTML;
<div class="hint" id="keyHint"></div>
"""

BAD4_FOCUS_WITHOUT_OPEN = """
function openCfg() { if (cfgEl) cfgEl.showModal(); }
const isKeyIssue = d.code === 'NO_API_KEY' || d.code === 'API_KEY_REJECTED';
if (isKeyIssue && keyEl) keyEl.focus();
"""

# 故意带上 id="keyState"，确保这条样本是被「回显 Key」抓出来的，不是因为缺字段
BAD5_STATE_ECHOES_KEY = """
<span id="keyState"></span>
keyStateEl.innerHTML = '<span class="dot"></span>' + (filled ? '已填：' + keyEl.value.slice(0, 4) : '未填写');
"""

BAD6_BUSY_ONLY_GO = """
async function run() {
  btn.disabled = true;
  try { await fetch('/api/analyze'); } finally { btn.disabled = false; }
}
document.getElementById('out').addEventListener('click', e => {
  if (e.target && e.target.id === 'again') run();
});
"""

BAD7_BROWSER_STORE_SESSION = """
const browserStore = window.sessionStorage;
const CONSTITUTION_KEY = 'ta_constitution_v1';
"""

BAD8_NO_STORAGE_COPY = """
<details id="questionnairePanel"><summary>中医九种体质问卷</summary>
  <button id="loadQuestions" type="button">加载问卷</button>
</details>
"""

BAD9_NO_OK_CHECK = """
async function loadQuestionnaire() {
  const res = await fetch('/api/questionnaire/questions?sex=' + sex);
  const data = await res.json();
}
async function submitQuestionnaire() {
  const res = await fetch('/api/questionnaire', { method: 'POST' });
  const data = await res.json();
}
"""

# 未登记的长期存储：必须被守卫 2 抓出来（这是白名单制的牙）
BAD2_UNREGISTERED_KEY = """
const NEW_STORE_KEY = 'ta_something_v1';
browserStore.setItem(NEW_STORE_KEY, v);
"""

# ================================================================ 正控（真实文件）

def test_guard1_positive() -> None:
    assert _guard1_remember_defaults_off(_html()) == []


def test_guard2_positive() -> None:
    assert _guard2_no_session_to_local_upgrade(_html()) == []


def test_guard3_positive() -> None:
    assert _guard3_healthz_hint_kept(_html()) == []


def test_guard4_positive() -> None:
    assert _guard4_key_error_opens_dialog(_html()) == []


def test_guard5_positive() -> None:
    assert _guard5_key_state_no_echo(_html()) == []


def test_guard6_positive() -> None:
    assert _guard6_busy_covers_both_buttons(_html()) == []


# ================================================================ 负控（合成样本）

def test_guard1_negative() -> None:
    assert _guard1_remember_defaults_off(BAD1_REMEMBER_CHECKED) != []


def test_guard2_negative() -> None:
    assert _guard2_no_session_to_local_upgrade(BAD2_SESSION_TO_LOCAL) != []


def test_guard3_negative() -> None:
    assert _guard3_healthz_hint_kept(BAD3_NO_REFRESH) != []
    assert _guard3_healthz_hint_kept(BAD3_EMPTY_HINT) != []


def test_guard4_negative() -> None:
    assert _guard4_key_error_opens_dialog(BAD4_FOCUS_WITHOUT_OPEN) != []


def test_guard5_negative() -> None:
    assert _guard5_key_state_no_echo(BAD5_STATE_ECHOES_KEY) != []


def test_guard6_negative() -> None:
    assert _guard6_busy_covers_both_buttons(BAD6_BUSY_ONLY_GO) != []


def test_guard7_positive() -> None:
    assert _guard7_browser_store_is_local(_html()) == []


def test_guard7_negative() -> None:
    assert _guard7_browser_store_is_local(BAD7_BROWSER_STORE_SESSION) != []


def test_guard8_positive() -> None:
    assert _guard8_storage_copy_kept(_html()) == []


def test_guard8_negative() -> None:
    # 两个词同时缺才红是不够的：任意一个词消失都必须红，否则判据被另一个词兜住
    assert _guard8_storage_copy_kept(BAD8_NO_STORAGE_COPY) != []


def test_guard9_positive() -> None:
    assert _guard9_questionnaire_fetch_checks_ok(_html()) == []


def test_guard9_negative() -> None:
    assert _guard9_questionnaire_fetch_checks_ok(BAD9_NO_OK_CHECK) != []


def test_guard2_unregistered_storage_key_negative() -> None:
    assert _guard2_no_session_to_local_upgrade(BAD2_UNREGISTERED_KEY) != []
