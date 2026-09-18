"""API Key 处理与日志安全测试。

这一层保证三件事：
1. **逐请求 Key 能正确取出并传递**（用户自带 Key 模式的基础）；
2. **Key 绝不泄露** —— 不进日志、不进响应体、不进异常详情。
   这是硬规则，退化成"把 Key 打进日志"就是事故；
3. 凭据缺失 / 后端不支持时的报错是**可操作的**，而不是被包装成"解析失败"。

本文件全部离线运行，不调用任何网络接口。
"""

from __future__ import annotations

import inspect
import json
import logging

import pytest

from app.agents.direct_api import build_thinking_params
from app.api.auth import extract_api_key
from app.config import get_settings
from app.domain.models import (
    AnalyzeRequest,
    BrewGuide,
    HerbInBlend,
    ParsedFood,
    ParsedMeal,
    Recommendation,
)
from app.services import orchestrator

# 一个绝不可能是真实 Key 的哨兵值，用来断言"它没出现在任何地方"
SENTINEL_KEY = "sk-SENTINEL-DO-NOT-LEAK-0123456789"


# ============================================================
# 1. Authorization 头解析
# ============================================================
@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Bearer sk-abc123", "sk-abc123"),
        ("bearer sk-abc123", "sk-abc123"),          # 前缀大小写不敏感
        ("BEARER sk-abc123", "sk-abc123"),
        ("  Bearer   sk-abc123  ", "sk-abc123"),     # 允许前后空白
        ("Bearer sk-abc123\t", "sk-abc123"),
    ],
)
def test_extract_api_key_accepts_valid_bearer(header: str, expected: str) -> None:
    assert extract_api_key(header) == expected


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "   ",
        "sk-abc123",                      # 少了 Bearer 前缀
        "Basic abc123",                   # 别的认证方式
        "Bearer",                         # 只有前缀没有 Key
        "Bearer ",                        # 前缀后为空
        "Bearer a b",                     # Key 里不允许有空白
        "Bearer " + "x" * 300,            # 超长
    ],
)
def test_extract_api_key_rejects_bad_input(header: str | None) -> None:
    """格式不对一律返回 None（当作"没给 Key"），不抛异常。

    本项目不内置 Key，所以 None 的后果是明确的 400 `NO_API_KEY`，
    而不是"偷偷用了谁的额度"—— 这也正是"格式不对不报 500"的前提。
    """
    assert extract_api_key(header) is None


def test_extract_api_key_never_raises() -> None:
    """任何奇怪输入都不应该让请求 500。"""
    for weird in ["\x00", "Bearer\nsk-x", "Bearer sk-中文", "🎋Bearer sk-x", "Bearer sk-" * 50]:
        extract_api_key(weird)  # 只要求不抛


# ============================================================
# 2. 思考模式参数映射
# ============================================================
def test_thinking_off_disables_thinking() -> None:
    """off 必须真正关闭思考，而不是传一个无效的 effort。

    实测：关闭后 completion 从 135 降到 5 tokens，成本差一个量级。
    """
    for value in ("off", "OFF", "off ", "none", "disabled"):
        params = build_thinking_params(value)
        assert params == {"thinking": {"type": "disabled"}}, value
        # 关闭时不应再传 reasoning_effort，免得两个参数打架
        assert "reasoning_effort" not in params


@pytest.mark.parametrize("level", ["low", "high", "max", "LOW", " high "])
def test_thinking_levels_enable_with_effort(level: str) -> None:
    params = build_thinking_params(level)
    assert params["thinking"] == {"type": "enabled"}
    assert params["reasoning_effort"] == level.strip().lower()


@pytest.mark.parametrize("weird", [None, "", "   ", "bogus", "medium", "ultra"])
def test_thinking_unknown_falls_back_to_low(weird: str | None) -> None:
    """未知取值 → low。宁可慢一点，也不要静默变成官方默认的 high（更贵更慢）。"""
    params = build_thinking_params(weird)
    assert params["thinking"] == {"type": "enabled"}
    assert params["reasoning_effort"] == "low"


# ============================================================
# 3. 凭据提示文案（历史坑：曾教用户把 Key 写进文件）
# ============================================================
def test_missing_credentials_hint_points_to_ui_and_env_var() -> None:
    """提示要让用户知道去哪儿给 Key：界面 或 环境变量。

    历史 bug（两次）：文案曾写「在 .env 中填入 DEEPSEEK_API_KEY」，
    后又写「放 credentials.env」—— 后者虽然能工作，但在
    「本项目不保存 Key」的新设计下同样是指错方向。
    """
    hint = get_settings().missing_credentials_hint()
    assert "不使用服务端内置 Key" in hint, "要讲清为什么不给兜底"
    assert "API Key" in hint
    # 两个正确入口都要提到
    assert "Authorization" in hint, "网页版走 Authorization 头"
    assert "DEEPSEEK_API_KEY" in hint and "环境变量" in hint, "终端/脚本走环境变量"
    # 不得再指引用户把 Key 写进任何配置文件
    assert ".env 中填入" not in hint
    assert "credentials.env" not in hint, "本项目不再从文件读 Key"
    # 隐私承诺要写出来
    assert "不落盘" in hint or "不写入日志" in hint


# ============================================================
# 4. 后端与逐请求 Key 的支持判定
# ============================================================
def test_direct_backend_supports_user_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "backend", "direct")
    assert get_settings().user_key_supported is True


def test_dsh_backend_does_not_support_user_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """dsh 的 Key 绑在子进程上，不能按请求切换。"""
    monkeypatch.setattr(get_settings(), "backend", "dsh")
    assert get_settings().user_key_supported is False


def test_runtime_ensure_started_shapes_are_compatible() -> None:
    """两个运行时的 `ensure_started` 必须形状一致：除 self 外不能有必传参数。

    历史 bug：`DirectAPIRuntime.ensure_started` 曾不收任何参数，而
    `scripts/smoke_agents.py` 按 dsh 的形状调 `ensure_started(api_key)`，
    于是该脚本一启动就 `TypeError`。默认后端正是 direct，
    所以这条验证路径自 826b44a 起**从未跑通过**，且没人发现。

    两个运行时的生命周期语义本来就不同（dsh 真的要启动子进程，direct 什么都不用做），
    调用方却共用同一段代码 —— 那就只能靠"形状兼容"来兜住。
    """
    from app.agents.direct_api import DirectAPIRuntime
    from app.agents.runtime import HarnessRuntime

    for cls in (HarnessRuntime, DirectAPIRuntime):
        params = [
            p
            for name, p in inspect.signature(cls.ensure_started).parameters.items()
            if name != "self"
        ]
        for p in params:
            assert (
                p.default is not inspect.Parameter.empty
            ), f"{cls.__name__}.ensure_started 的 {p.name} 是必传的，不带 Key 的调用点会崩"


def test_direct_runtime_ensure_started_tolerates_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """direct 运行时带不带 Key 都能"启动"，且不留下任何凭据痕迹。

    对应 `smoke_agents.py:100` 的实际调用形状，这条测试不需要 Key、不联网。
    """
    monkeypatch.setattr(get_settings(), "backend", "direct")
    from app.agents.runtime import get_runtime

    rt = get_runtime()
    assert rt.ensure_started() is None                        # 不带参
    assert rt.ensure_started(SENTINEL_KEY) is None            # smoke_agents.py 的形状
    assert rt.ensure_started(api_key=SENTINEL_KEY) is None    # 关键字形式

    # 直连后端的 Key 是逐请求传的（run(api_key=...)）：
    # ensure_started 收下即丢弃，不得把它留在实例上。
    assert SENTINEL_KEY not in repr(vars(rt))


# ============================================================
# 5. 编排层：Key 传递、key_source 标注、日志安全
# ============================================================
def _fake_parsed() -> ParsedMeal:
    return ParsedMeal(
        foods=[ParsedFood(name="麻辣烫", amount_desc="一碗")],
        confidence=0.9,
        summary="午餐吃了麻辣烫",
    )


def _fake_recs() -> tuple[list[Recommendation], str, int]:
    rec = Recommendation(
        title="陈皮茯苓饮",
        herbs=[HerbInBlend(name="陈皮", amount_g=5)],
        brew=BrewGuide(),
        fit_reason="测试用",
        score=0.8,
    )
    return [rec], "测试说明", 1


@pytest.fixture
def stub_agents(monkeypatch: pytest.MonkeyPatch) -> dict:
    """把两个 Agent 换成离线桩，同时记录它们收到的 api_key。"""
    seen: dict = {"agent1": [], "agent2": []}

    def fake_parse_diet(text, meal_time=None, session_id=None, *, api_key=None):
        seen["agent1"].append(api_key)
        return _fake_parsed(), 1, "sid-a1"

    def fake_agent2(
        parsed,
        constitution,
        exclude_herbs=None,
        session_id=None,
        *,
        api_key=None,
        avoid=(),
    ):
        # 签名跟着 agent2_recommend 走（B2 接入新增 avoid）。
        # 桩不接这个关键字的话，analyze 会当成 Agent2 失败而静默降级到规则兜底，
        # 表现是「agent2 一次都没被调用」——看不出是签名没跟上。
        seen["agent2"].append(api_key)
        return _fake_recs()

    monkeypatch.setattr(orchestrator, "parse_diet", fake_parse_diet)
    monkeypatch.setattr(orchestrator, "agent2_recommend", fake_agent2)
    return seen


def test_user_key_is_threaded_to_both_agents(
    monkeypatch: pytest.MonkeyPatch, stub_agents: dict
) -> None:
    """调用方给的 Key 必须一路传到 Agent1 和 Agent2。"""
    monkeypatch.setattr(get_settings(), "backend", "direct")

    resp = orchestrator.analyze(
        AnalyzeRequest(text="中午吃了碗麻辣烫"), api_key=SENTINEL_KEY
    )

    assert stub_agents["agent1"] == [SENTINEL_KEY]
    assert stub_agents["agent2"] == [SENTINEL_KEY]
    assert resp.meta.key_source == "user"
    assert resp.meta.backend == "direct"


def test_no_key_is_rejected_without_calling_model(
    monkeypatch: pytest.MonkeyPatch, stub_agents: dict
) -> None:
    """不带 Key → 直接 NO_API_KEY，**且一次模型调用都不发**。

    本项目不使用服务端内置 Key（曾有过的"兜底 Key"已移除），
    所以没有 Key 就没有任何可退的地方，必须明确失败而不是偷偷用谁的额度。
    """
    monkeypatch.setattr(get_settings(), "backend", "direct")

    with pytest.raises(orchestrator.AnalyzeError) as ei:
        orchestrator.analyze(AnalyzeRequest(text="中午吃了碗麻辣烫"))

    assert ei.value.code == "NO_API_KEY"
    assert "不使用服务端内置 Key" in ei.value.message
    assert stub_agents["agent1"] == [], "校验应在调用模型之前就拦住"


def test_blank_or_whitespace_key_is_rejected(
    monkeypatch: pytest.MonkeyPatch, stub_agents: dict
) -> None:
    """空串/纯空白等同于没给 Key，不能被当成有效 Key。"""
    monkeypatch.setattr(get_settings(), "backend", "direct")
    for blank in ("", "   ", "\t\n"):
        with pytest.raises(orchestrator.AnalyzeError) as ei:
            orchestrator.analyze(AnalyzeRequest(text="中午吃了碗麻辣烫"), api_key=blank)
        assert ei.value.code == "NO_API_KEY", blank
    assert stub_agents["agent1"] == []


def test_dsh_backend_rejects_user_key_with_clear_error(
    monkeypatch: pytest.MonkeyPatch, stub_agents: dict
) -> None:
    """dsh 后端不支持逐请求 Key：必须明确报错，不能静默换用别的 Key。

    dsh 的 Key 与子进程绑定，一个进程只能有一个；静默复用旧 Key
    会让用户以为自己填的 Key 生效了、以为费用记在自己账上。
    """
    monkeypatch.setattr(get_settings(), "backend", "dsh")

    with pytest.raises(orchestrator.AnalyzeError) as ei:
        orchestrator.analyze(AnalyzeRequest(text="中午吃了碗麻辣烫"), api_key=SENTINEL_KEY)

    assert ei.value.code == "USER_KEY_UNSUPPORTED"
    assert "direct" in ei.value.message, "要告诉用户怎么解决"
    assert stub_agents["agent1"] == [], "报错应发生在调用模型之前"


def test_high_risk_branch_works_without_any_key(stub_agents: dict) -> None:
    """**安全分支必须无条件可用**：一个还没填 Key 的用户输入"我怀孕了"，
    应该看到"请先咨询执业医师"，而不是"缺少 API Key"。

    这个分支不调用模型、不花一分钱，所以凭据校验刻意放在它之后。
    """
    resp = orchestrator.analyze(AnalyzeRequest(text="我怀孕了，今天吃了火锅"))

    assert resp.recommendations == []
    assert resp.meta.key_source == "not_used"
    assert "医师" in resp.user_message or "药师" in resp.user_message
    assert stub_agents["agent1"] == [], "安全分支不应调用模型"


def test_rejected_key_maps_to_dedicated_error_code(
    monkeypatch: pytest.MonkeyPatch, stub_agents: dict
) -> None:
    """Key 被模型服务方拒绝时，要回"去改 Key"，不能是"饮食解析失败"。

    填错 Key 是这个模式下最常见的第一个错误；
    回 AGENT1_FAILED 会把人的注意力引向"我描述得不对"。
    """
    from app.agents.runtime import CredentialError

    monkeypatch.setattr(get_settings(), "backend", "direct")

    def boom(*args, **kwargs):
        raise CredentialError("API Key 无效或已失效（HTTP 401）。")

    monkeypatch.setattr(orchestrator, "parse_diet", boom)

    with pytest.raises(orchestrator.AnalyzeError) as ei:
        orchestrator.analyze(AnalyzeRequest(text="中午吃了碗麻辣烫"), api_key=SENTINEL_KEY)

    assert ei.value.code == "API_KEY_REJECTED"
    assert "Key" in ei.value.message
    assert SENTINEL_KEY not in ei.value.message, "错误信息里不得出现 Key"


# ------------------------------------------------------------
# 日志安全：这是本文件的重点
# ------------------------------------------------------------
def test_key_never_appears_in_logs(
    monkeypatch: pytest.MonkeyPatch, stub_agents: dict, caplog: pytest.LogCaptureFixture
) -> None:
    """带 Key 跑完整编排，日志里绝不能出现这个 Key。"""
    monkeypatch.setattr(get_settings(), "backend", "direct")

    with caplog.at_level(logging.DEBUG):
        orchestrator.analyze(AnalyzeRequest(text="中午吃了碗麻辣烫"), api_key=SENTINEL_KEY)

    blob = "\n".join(r.getMessage() for r in caplog.records)
    blob += "\n" + "\n".join(str(r.args) for r in caplog.records)
    assert SENTINEL_KEY not in blob, "Key 出现在日志里了"
    assert "SENTINEL" not in blob
    assert "Bearer" not in blob, "Authorization 头不应进日志"


def test_key_never_appears_in_response(
    monkeypatch: pytest.MonkeyPatch, stub_agents: dict
) -> None:
    """响应体（含 meta / 错误详情）绝不能回显 Key。"""
    monkeypatch.setattr(get_settings(), "backend", "direct")

    resp = orchestrator.analyze(
        AnalyzeRequest(text="中午吃了碗麻辣烫"), api_key=SENTINEL_KEY
    )
    dumped = resp.model_dump_json()
    assert SENTINEL_KEY not in dumped
    assert "SENTINEL" not in dumped


def test_key_never_appears_in_error_messages(
    monkeypatch: pytest.MonkeyPatch, stub_agents: dict
) -> None:
    """报错信息里也不能带 Key。"""
    monkeypatch.setattr(get_settings(), "backend", "dsh")

    with pytest.raises(orchestrator.AnalyzeError) as ei:
        orchestrator.analyze(AnalyzeRequest(text="中午吃了碗麻辣烫"), api_key=SENTINEL_KEY)

    assert SENTINEL_KEY not in str(ei.value)
    assert SENTINEL_KEY not in ei.value.message


def test_direct_runtime_error_messages_do_not_include_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """运行时的各条错误文案都不得包含 Key（逐条检查状态码映射）。"""
    from app.agents.direct_api import DirectAPIRuntime

    for status in (400, 401, 402, 403, 429, 500, 503):
        msg = DirectAPIRuntime._describe_error(status)
        assert SENTINEL_KEY not in msg
        assert "Bearer" not in msg
        assert str(status) in msg, "错误文案里应带状态码，方便排查"


# ============================================================
# 6. HTTP 层（需要 [web] extra；缺失时跳过而不是失败）
# ============================================================
@pytest.fixture
def http_client(monkeypatch: pytest.MonkeyPatch, stub_agents: dict):
    pytest.importorskip("fastapi", reason="HTTP 层测试需要 [web] extra")
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


def test_http_authorization_header_reaches_orchestrator(
    monkeypatch: pytest.MonkeyPatch, stub_agents: dict, http_client
) -> None:
    """整条 HTTP 路径：Authorization 头 → HTTP 层 → 编排层 → 两个 Agent。"""
    monkeypatch.setattr(get_settings(), "backend", "direct")

    r = http_client.post(
        "/api/analyze",
        json={"text": "中午吃了碗麻辣烫"},
        headers={"Authorization": f"Bearer {SENTINEL_KEY}"},
    )
    assert r.status_code == 200
    assert stub_agents["agent1"] == [SENTINEL_KEY]
    assert stub_agents["agent2"] == [SENTINEL_KEY]
    body = r.json()
    assert body["meta"]["key_source"] == "user"
    assert SENTINEL_KEY not in r.text, "响应体里出现了 Key"


def test_http_without_authorization_is_rejected(
    monkeypatch: pytest.MonkeyPatch, stub_agents: dict, http_client
) -> None:
    """不带 Authorization → 400 NO_API_KEY（本服务不内置 Key，没有兜底可退）。"""
    monkeypatch.setattr(get_settings(), "backend", "direct")

    r = http_client.post("/api/analyze", json={"text": "中午吃了碗麻辣烫"})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "NO_API_KEY"
    assert stub_agents["agent1"] == [], "不该发出任何模型调用"


def test_http_no_key_returns_400_with_actionable_code(
    monkeypatch: pytest.MonkeyPatch, stub_agents: dict, http_client
) -> None:
    """没有 Key 时用 400（配置问题），不是 422（换种说法也没用）。"""
    monkeypatch.setattr(get_settings(), "backend", "direct")

    r = http_client.post("/api/analyze", json={"text": "中午吃了碗麻辣烫"})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "NO_API_KEY"
    msg = r.json()["detail"]["message"]
    assert "不使用服务端内置 Key" in msg
    assert "Authorization" in msg or "环境变量" in msg, "要告诉用户去哪儿给 Key"


def test_http_malformed_authorization_is_not_500(
    monkeypatch: pytest.MonkeyPatch, stub_agents: dict, http_client
) -> None:
    """头写得不对也不能 500：当作"没给 Key"，回 400 并说明。"""
    monkeypatch.setattr(get_settings(), "backend", "direct")

    for bad in ["sk-no-bearer", "Basic xyz", "Bearer"]:
        r = http_client.post(
            "/api/analyze", json={"text": "中午吃了碗麻辣烫"},
            headers={"Authorization": bad},
        )
        assert r.status_code == 400, bad
        assert r.json()["detail"]["code"] == "NO_API_KEY", bad
        assert bad not in r.text
    assert stub_agents["agent1"] == [], "格式不对时也不该调用模型"


def test_healthz_exposes_backend_and_key_support(http_client) -> None:
    """前端要知道"你到底需不需要填 Key"。"""
    r = http_client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert "backend" in body
    assert "user_key_supported" in body
    assert isinstance(body["user_key_supported"], bool)
    # 刻意没有 credentials_ok —— 本项目不使用服务端内置 Key
    assert "credentials_ok" not in body
    assert SENTINEL_KEY not in r.text


def test_http_rejected_key_returns_400_not_422(
    monkeypatch: pytest.MonkeyPatch, stub_agents: dict, http_client
) -> None:
    """Key 被拒 → 400 + API_KEY_REJECTED，前端据此把焦点移到 Key 输入框。"""
    from app.agents.runtime import CredentialError

    monkeypatch.setattr(get_settings(), "backend", "direct")

    def boom(*args, **kwargs):
        raise CredentialError("API Key 无效或已失效（HTTP 401）。")

    monkeypatch.setattr(orchestrator, "parse_diet", boom)

    r = http_client.post(
        "/api/analyze",
        json={"text": "中午吃了碗麻辣烫"},
        headers={"Authorization": f"Bearer {SENTINEL_KEY}"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "API_KEY_REJECTED"
    assert SENTINEL_KEY not in r.text


def test_http_high_risk_works_without_key(http_client) -> None:
    """安全分支在 HTTP 层也必须无需 Key 就能给出引导就医。"""
    r = http_client.post(
        "/api/analyze", json={"text": "我怀孕了，今天吃了火锅，能喝什么茶"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["recommendations"] == []
    assert body["meta"]["key_source"] == "not_used"
    assert "医师" in body["user_message"] or "药师" in body["user_message"]


def test_openapi_declares_authorization_header(http_client) -> None:
    """接口文档里要能看到可以传 Authorization，否则用户不知道能自带 Key。"""
    spec = http_client.get("/openapi.json").json()
    params = spec["paths"]["/api/analyze"]["post"].get("parameters", [])
    names = {p.get("name", "").lower() for p in params}
    assert "authorization" in names
