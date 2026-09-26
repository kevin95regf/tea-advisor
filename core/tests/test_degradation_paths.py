"""降级路径的三条契约（`orchestrator.analyze`）。

守的是「失败时**给出有用的东西**而不是崩掉」这条设计底线，三条各自对应一个出口：
 1. 高风险人群：不调模型、不给推荐、引导就医 —— 且**不需要 Key**。
    安全提示不能被配置问题挡住，所以凭据校验刻意排在它之后；
 2. Agent2 抛异常：降级到 `matcher.fallback_recommend`，推荐仍非空；
 3. 护栏把推荐全清掉：再兜底一次，并把 `degraded_reason` 钉成
    `guardrail_removed_all`，而不是静默返回空列表。

三条**全离线**：两个 Agent 全部打桩，不调模型、不需要真实 Key。
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
