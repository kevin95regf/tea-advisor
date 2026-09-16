"""API Key 处理与日志安全测试。

这一层保证三件事：
1. **逐请求 Key 能正确取出并传递**（用户自带 Key 模式的基础）；
2. **Key 绝不泄露** —— 不进日志、不进响应体、不进异常详情。
   这是硬规则，退化成"把 Key 打进日志"就是事故；
3. 凭据缺失 / 后端不支持时的报错是**可操作的**，而不是被包装成"解析失败"。

本文件全部离线运行，不调用任何网络接口。
"""

from __future__ import annotations

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
    """格式不对一律返回 None（回退服务端 Key），不抛异常。

    回退是安全的：meta.key_source 会变成 server，前端会显示
    「本次使用服务端 Key」，用户因此能看出自己填的 Key 没生效。
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
# 3. 凭据提示文案（曾把用户带进 .env 的坑）
# ============================================================
def test_missing_credentials_hint_does_not_tell_user_to_use_dotenv() -> None:
    """回归：提示文案必须指向 credentials.env，不能教用户写进 .env。

    历史 bug：文案写着「在 .env 中填入 DEEPSEEK_API_KEY」，
    而 dsh 会因为 .env 里出现该变量而**拒绝启动** —— 照着做必踩坑。
    """
    hint = get_settings().missing_credentials_hint()
    assert "credentials.env" in hint, "必须指明正确位置是 credentials.env"
    # 关键断言：不得出现"在 .env 中填入 DEEPSEEK_API_KEY"这类指令
    assert "在 .env 中填入 DEEPSEEK_API_KEY" not in hint
    assert "不能放 .env" in hint or "必须放 credentials.env" in hint, (
        "要明确警告不能放 .env，否则用户还是会踩坑"
    )


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

    def fake_agent2(parsed, constitution, exclude_herbs=None, session_id=None, *, api_key=None):
        seen["agent2"].append(api_key)
        return _fake_recs()

    monkeypatch.setattr(orchestrator, "parse_diet", fake_parse_diet)
    monkeypatch.setattr(orchestrator, "agent2_recommend", fake_agent2)
    return seen


def test_user_key_is_threaded_to_both_agents(
    monkeypatch: pytest.MonkeyPatch, stub_agents: dict
) -> None:
    """用户自带的 Key 必须一路传到 Agent1 和 Agent2。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "backend", "direct")
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-server-fallback")

    resp = orchestrator.analyze(
        AnalyzeRequest(text="中午吃了碗麻辣烫"), api_key=SENTINEL_KEY
    )

    assert stub_agents["agent1"] == [SENTINEL_KEY]
    assert stub_agents["agent2"] == [SENTINEL_KEY]
    assert resp.meta.key_source == "user"
    assert resp.meta.backend == "direct"


def test_no_user_key_falls_back_to_server_and_is_marked(
    monkeypatch: pytest.MonkeyPatch, stub_agents: dict
) -> None:
    """没带 Key → 用服务端兜底，且必须标注出来（前端要显示）。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "backend", "direct")
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-server-fallback")

    resp = orchestrator.analyze(AnalyzeRequest(text="中午吃了碗麻辣烫"))

    assert stub_agents["agent1"] == [None], "没有用户 Key 时应传 None，由运行时回退"
    assert resp.meta.key_source == "server"


def test_no_key_anywhere_raises_actionable_error(
    monkeypatch: pytest.MonkeyPatch, stub_agents: dict
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "backend", "direct")
    monkeypatch.setattr(settings, "deepseek_api_key", None)

    with pytest.raises(orchestrator.AnalyzeError) as ei:
        orchestrator.analyze(AnalyzeRequest(text="中午吃了碗麻辣烫"))

    assert ei.value.code == "NO_API_KEY"
    assert "credentials.env" in ei.value.message


def test_dsh_backend_rejects_user_key_with_clear_error(
    monkeypatch: pytest.MonkeyPatch, stub_agents: dict
) -> None:
    """dsh 后端不支持逐请求 Key：必须明确报错，不能静默改用服务端 Key。

    静默回退会让用户以为自己填的 Key 生效了、以为费用记在自己账上。
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "backend", "dsh")
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-server-fallback")

    with pytest.raises(orchestrator.AnalyzeError) as ei:
        orchestrator.analyze(AnalyzeRequest(text="中午吃了碗麻辣烫"), api_key=SENTINEL_KEY)

    assert ei.value.code == "USER_KEY_UNSUPPORTED"
    assert "direct" in ei.value.message, "要告诉用户怎么解决"
    assert stub_agents["agent1"] == [], "报错应发生在调用模型之前"


def test_high_risk_branch_marks_key_not_used(
    monkeypatch: pytest.MonkeyPatch, stub_agents: dict
) -> None:
    """高风险分支不调用模型，key_source 应为 not_used，不要误标成用了某个 Key。"""
    monkeypatch.setattr(get_settings(), "backend", "direct")
    monkeypatch.setattr(get_settings(), "deepseek_api_key", "sk-server-fallback")

    resp = orchestrator.analyze(AnalyzeRequest(text="我怀孕了，今天吃了火锅"))

    assert resp.recommendations == []
    assert resp.meta.key_source == "not_used"
    assert stub_agents["agent1"] == []


def test_rejected_key_maps_to_dedicated_error_code(
    monkeypatch: pytest.MonkeyPatch, stub_agents: dict
) -> None:
    """Key 被模型服务方拒绝时，要回"去改 Key"，不能是"饮食解析失败"。

    用户自带 Key 模式下，填错 Key 是最常见的第一个错误；
    回 AGENT1_FAILED 会把人的注意力引向"我描述得不对"。
    """
    from app.agents.runtime import CredentialError

    settings = get_settings()
    monkeypatch.setattr(settings, "backend", "direct")
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-server-fallback")

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
    """带用户 Key 跑完整编排，日志里绝不能出现这个 Key。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "backend", "direct")
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-server-fallback")

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
    settings = get_settings()
    monkeypatch.setattr(settings, "backend", "direct")
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-server-fallback")

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
    settings = get_settings()
    monkeypatch.setattr(settings, "backend", "dsh")
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-server-fallback")

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
    settings = get_settings()
    monkeypatch.setattr(settings, "backend", "direct")
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-server-fallback")

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


def test_http_without_authorization_uses_server_key(
    monkeypatch: pytest.MonkeyPatch, stub_agents: dict, http_client
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "backend", "direct")
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-server-fallback")

    r = http_client.post("/api/analyze", json={"text": "中午吃了碗麻辣烫"})
    assert r.status_code == 200
    assert r.json()["meta"]["key_source"] == "server"


def test_http_no_key_returns_400_with_actionable_code(
    monkeypatch: pytest.MonkeyPatch, stub_agents: dict, http_client
) -> None:
    """没有 Key 时用 400（配置问题），不是 422（换种说法也没用）。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "backend", "direct")
    monkeypatch.setattr(settings, "deepseek_api_key", None)

    r = http_client.post("/api/analyze", json={"text": "中午吃了碗麻辣烫"})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "NO_API_KEY"


def test_http_malformed_authorization_falls_back_not_500(
    monkeypatch: pytest.MonkeyPatch, stub_agents: dict, http_client
) -> None:
    """头写得不对也不能 500：回退服务端 Key，并标注出来。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "backend", "direct")
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-server-fallback")

    for bad in ["sk-no-bearer", "Basic xyz", "Bearer"]:
        r = http_client.post(
            "/api/analyze", json={"text": "中午吃了碗麻辣烫"},
            headers={"Authorization": bad},
        )
        assert r.status_code == 200, bad
        assert r.json()["meta"]["key_source"] == "server", bad
        assert bad not in r.text


def test_healthz_exposes_backend_and_key_support(http_client) -> None:
    """前端要知道"你到底需不需要填 Key"。"""
    r = http_client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert "backend" in body
    assert "user_key_supported" in body
    assert isinstance(body["user_key_supported"], bool)
    assert SENTINEL_KEY not in r.text


def test_http_rejected_key_returns_400_not_422(
    monkeypatch: pytest.MonkeyPatch, stub_agents: dict, http_client
) -> None:
    """Key 被拒 → 400 + API_KEY_REJECTED，前端据此把焦点移到 Key 输入框。"""
    from app.agents.runtime import CredentialError

    settings = get_settings()
    monkeypatch.setattr(settings, "backend", "direct")
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-server-fallback")

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


def test_openapi_declares_authorization_header(http_client) -> None:
    """接口文档里要能看到可以传 Authorization，否则用户不知道能自带 Key。"""
    spec = http_client.get("/openapi.json").json()
    params = spec["paths"]["/api/analyze"]["post"].get("parameters", [])
    names = {p.get("name", "").lower() for p in params}
    assert "authorization" in names
