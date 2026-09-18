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

def _guard2_no_session_to_local_upgrade(html: str) -> list[str]:
    """不得把 sessionStorage 的值悄悄搬进 localStorage。

    派生不变式：每一次 `localStorage.setItem` 都必须由「记住 Key」的勾选状态把关
    —— 其前 200 字符内若没有 `rememberEl.checked`，就是绕过用户选择的长期存储。
    """
    bad = []
    for m in re.finditer(r'localStorage\.setItem', html):
        window = html[max(0, m.start() - 200):m.start()]
        if 'rememberEl.checked' not in window:
            bad.append(
                f"第 {html[:m.start()].count(chr(10)) + 1} 行的 localStorage.setItem "
                "没有经 rememberEl.checked 把关"
            )
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
