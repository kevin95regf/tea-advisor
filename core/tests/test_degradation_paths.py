"""降级路径与护栏扫描面的契约（`orchestrator.analyze` + 离线路径）。

守的是「失败时**给出有用的东西**而不是崩掉」这条设计底线，前三条各自对应一个出口：
 1. 高风险人群：不调模型、不给推荐、引导就医 —— 且**不需要 Key**。
    安全提示不能被配置问题挡住，所以凭据校验刻意排在它之后；
 2. Agent2 抛异常：降级到 `matcher.fallback_recommend`，推荐仍非空；
 3. 护栏把推荐全清掉：再兜底一次，并把 `degraded_reason` 钉成
    `guardrail_removed_all`，而不是静默返回空列表。

后三条守**扫描面**（2026-09-26 扩展）：禁用表述写进 `role` 或 `brew.steps` 也必须拦住
—— 旧口径只拼 `title + fit_reason + cautions`，这两个字段能绕过护栏；
且离线路径与 LLM 路径共用 `safety.recommendation_scan_text` 这**一份**扫描面。

六条**全离线**：两个 Agent 全部打桩，不调模型、不需要真实 Key。
"""

from __future__ import annotations

import pytest

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

# 打桩专用哨兵值：本文件不发任何网络请求，它只用来穿过凭据校验那一关
SENTINEL_KEY = "sk-TEST-STUB-NOT-A-REAL-KEY"

# 一条普通口述：不命中任何高风险关键词（HIGH_RISK_KEYWORDS）
NORMAL_TEXT = "中午吃了碗麻辣烫"


def _fake_parsed() -> ParsedMeal:
    """Agent1 的桩输出：只需有食物，够走完后续链路。"""
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
def stub_agents(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """把两个 Agent 换成离线桩，并记下 Agent1 被调用了几次。

    ⚠️ Agent2 的桩**必须接 `avoid=`**（B2 接入新增的关键字参数）：不接的话
    `analyze` 会当成 Agent2 失败而静默降级到规则兜底，表现是「明明打了桩却走了
    降级」，看不出其实是签名没跟上 —— 这个坑在 `test_key_handling.py` 里踩过。
    """
    calls = {"agent1": 0}

    def fake_parse_diet(text, meal_time=None, session_id=None, *, api_key=None):
        calls["agent1"] += 1
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
        return _fake_recs()

    monkeypatch.setattr(orchestrator, "parse_diet", fake_parse_diet)
    monkeypatch.setattr(orchestrator, "agent2_recommend", fake_agent2)
    monkeypatch.setattr(get_settings(), "backend", "direct")
    return calls


def test_high_risk_returns_medical_advice(stub_agents: dict[str, int]) -> None:
    """命中高风险关键词 → 不给推荐、引导就医，且**无需 Key**（本分支不调模型）。

    高风险分支刻意排在凭据校验之前：一个还没填 Key 的用户输入"我怀孕了"，
    应该看到"请先咨询执业医师"，而不是"缺少 API Key"。
    """
    resp = orchestrator.analyze(AnalyzeRequest(text="我怀孕了，今天吃了火锅"))

    assert resp.recommendations == []
    assert resp.meta.degraded is True
    assert resp.meta.degraded_reason == "high_risk_group"
    assert resp.meta.key_source == "not_used"
    assert "请先咨询执业医师或药师" in resp.user_message
    # 安全分支不该发出任何模型调用（一次都不许）
    assert stub_agents["agent1"] == 0


def test_agent2_failure_falls_back(
    monkeypatch: pytest.MonkeyPatch, stub_agents: dict[str, int]
) -> None:
    """Agent2 挂了也要给得出东西：降级到规则匹配，并把异常原因如实带上。

    `degraded_reason` 是 `str(exc)[:200]`，所以断言用"包含"而不是等值 ——
    截断长度是编排层的实现细节，不该钉在测试里。
    """
    def boom(*args, **kwargs):
        raise RuntimeError("Agent2 模型超时（测试桩）")

    monkeypatch.setattr(orchestrator, "agent2_recommend", boom)

    resp = orchestrator.analyze(AnalyzeRequest(text=NORMAL_TEXT), api_key=SENTINEL_KEY)

    assert resp.meta.degraded is True
    assert "Agent2 模型超时（测试桩）" in (resp.meta.degraded_reason or "")
    # 契约是「降级而非失败」：兜底必须真的给出非空搭配
    assert resp.recommendations, "降级后仍须给出推荐，空列表等于没兜住"
    assert all(rec.herbs for rec in resp.recommendations)


def test_guardrail_removes_all_falls_back(
    monkeypatch: pytest.MonkeyPatch, stub_agents: dict[str, int]
) -> None:
    """护栏把推荐全清掉 → 再兜底一次，并把原因钉成 `guardrail_removed_all`。

    用例里的"根治"取自 `safety.FORBIDDEN_PHRASES`：用真实的禁词，
    这样以后有人把这条改成了别的护栏分支（比如改成剂量拦截），测试会红。
    """
    def dirty_agent2(*args, **kwargs):
        rec = Recommendation(
            title="祛湿茶",
            herbs=[HerbInBlend(name="陈皮", amount_g=5)],
            brew=BrewGuide(),
            fit_reason="坚持喝两周可根治湿气",  # 「根治」是禁用表述
            score=0.8,
        )
        return [rec], "测试说明", 1

    monkeypatch.setattr(orchestrator, "agent2_recommend", dirty_agent2)

    resp = orchestrator.analyze(AnalyzeRequest(text=NORMAL_TEXT), api_key=SENTINEL_KEY)

    assert resp.meta.degraded is True
    assert resp.meta.degraded_reason == "guardrail_removed_all"
    # 留痕：被拦下的原因进 basis，前端能看见，不能只是"悄悄没了"
    assert any("禁用表述" in item for item in resp.basis.guardrail_applied)


def test_forbidden_phrase_in_herb_role_is_blocked(
    monkeypatch: pytest.MonkeyPatch, stub_agents: dict[str, int]
) -> None:
    """禁用表述写进某味饮片的 `role`，整条推荐作废（扫描面扩展的回归）。

    `role` 是**直接展示给用户**的字段，却不在旧扫描面里（旧口径只拼
    title + fit_reason + cautions）⇒ 旧实现下这条会一路透出去。
    用真实禁词「根治」：谁把扫描面改回去，或用例改成恒真写法，它都会红。
    """
    def dirty_role_agent2(*args, **kwargs):
        rec = Recommendation(
            title="祛湿茶",
            herbs=[HerbInBlend(name="陈皮", amount_g=5, role="坚持喝两周可根治湿气")],
            brew=BrewGuide(),
            fit_reason="测试用",
            score=0.8,
        )
        return [rec], "测试说明", 1

    monkeypatch.setattr(orchestrator, "agent2_recommend", dirty_role_agent2)

    resp = orchestrator.analyze(AnalyzeRequest(text=NORMAL_TEXT), api_key=SENTINEL_KEY)

    assert resp.meta.degraded_reason == "guardrail_removed_all"
    assert any("禁用表述" in item for item in resp.basis.guardrail_applied)
    # 整条作废：脏推荐不得出现在返回值里（role 是它的判别特征）
    assert all(
        "根治" not in (h.role or "")
        for rec in resp.recommendations
        for h in rec.herbs
    ), "含禁用表述的 role 透出去了"


def test_forbidden_phrase_in_brew_steps_is_blocked(
    monkeypatch: pytest.MonkeyPatch, stub_agents: dict[str, int]
) -> None:
    """禁用表述写进冲泡步骤，整条推荐作废（`brew.steps` 同样不在旧扫描面里）。"""
    def dirty_steps_agent2(*args, **kwargs):
        rec = Recommendation(
            title="祛湿茶",
            herbs=[HerbInBlend(name="陈皮", amount_g=5)],
            brew=BrewGuide(steps=["煮开后温饮，坚持两周可根治湿气"]),
            fit_reason="测试用",
            score=0.8,
        )
        return [rec], "测试说明", 1

    monkeypatch.setattr(orchestrator, "agent2_recommend", dirty_steps_agent2)

    resp = orchestrator.analyze(AnalyzeRequest(text=NORMAL_TEXT), api_key=SENTINEL_KEY)

    assert resp.meta.degraded_reason == "guardrail_removed_all"
    assert any("禁用表述" in item for item in resp.basis.guardrail_applied)
    assert all(
        "根治" not in step
        for rec in resp.recommendations
        for step in rec.brew.steps
    ), "含禁用表述的冲泡步骤透出去了"


def test_offline_path_shares_the_scan_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """离线路径共用**同一份**扫描面：脏的 `role` 一样被剔掉并留痕。

    与 LLM 路径的唯一差别是处置方式（离线是"移除该条"，LLM 是"整条作废后兜底"），
    判据必须同源 —— `safety.recommendation_scan_text` 是唯一入口。
    """
    pytest.importorskip("fastapi", reason="HTTP 层测试需要 [web] extra")
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import matcher

    def dirty_fallback(parsed, constitution, exclude_herbs=None, *, avoid=()):
        rec = Recommendation(
            title="祛湿茶",
            herbs=[HerbInBlend(name="陈皮", amount_g=5, role="坚持喝可根治湿气")],
            brew=BrewGuide(),
            fit_reason="测试用",
            score=0.6,
        )
        return [rec], "离线说明", []

    monkeypatch.setattr(matcher, "fallback_recommend", dirty_fallback)

    resp = TestClient(app).post(
        "/api/analyze-offline",
        json={"text": NORMAL_TEXT, "constitution_override": "balanced"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["recommendations"] == [], "未通过安全检查的推荐没被移除"
    assert any("禁用表述" in item for item in body["basis"]["guardrail_applied"])
    assert "未通过安全检查" in body["user_message"]
