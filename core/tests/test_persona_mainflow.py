"""personas 高风险闸门接入推荐主流程（orchestrator + offline）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.domain.models import (
    AnalyzeRequest,
    BrewGuide,
    HerbInBlend,
    ParsedFood,
    ParsedMeal,
    Recommendation,
)
from app.domain.safety import high_risk_block_reasons
from app.main import app
from app.services import orchestrator
from app.services.orchestrator import AnalyzeError

SENTINEL_KEY = "sk-TEST-STUB-NOT-A-REAL-KEY"
NORMAL_TEXT = "中午吃了碗麻辣烫"


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
def stub_agents(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    calls = {"agent1": 0, "agent2": 0}

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
        calls["agent2"] += 1
        return _fake_recs()

    monkeypatch.setattr(orchestrator, "parse_diet", fake_parse_diet)
    monkeypatch.setattr(orchestrator, "agent2_recommend", fake_agent2)
    monkeypatch.setattr(get_settings(), "backend", "direct")
    return calls


@pytest.mark.parametrize(
    "persona_id",
    ["pregnant", "chronic_diabetes", "chronic_hypertension"],
)
def test_high_risk_persona_id_blocks_recommend(
    stub_agents: dict[str, int], persona_id: str
) -> None:
    """高风险 persona_id 单独即可拦截：不调 Agent、空 recommendations。"""
    resp = orchestrator.analyze(
        AnalyzeRequest(text=NORMAL_TEXT, persona_id=persona_id)
    )
    assert resp.recommendations == []
    assert resp.meta.degraded is True
    assert resp.meta.degraded_reason == "high_risk_group"
    assert resp.meta.key_source == "not_used"
    assert "请先咨询执业医师或药师" in resp.user_message
    assert any("高风险画像" in g for g in resp.basis.guardrail_applied)
    assert stub_agents["agent1"] == 0
    assert stub_agents["agent2"] == 0


def test_overnight_student_persona_alone_not_blocked(
    stub_agents: dict[str, int],
) -> None:
    """低风险画像 alone 不拦；元数据进 rule_hits，不编造功效。"""
    resp = orchestrator.analyze(
        AnalyzeRequest(text=NORMAL_TEXT, persona_id="overnight_student"),
        api_key=SENTINEL_KEY,
    )
    assert resp.meta.degraded_reason != "high_risk_group"
    assert stub_agents["agent1"] == 1
    hits = resp.basis.rule_hits
    assert "persona:overnight_student" in hits
    assert any(h.startswith("persona_review:") for h in hits)
    assert any("不得作为开方" in h for h in hits)


def test_unknown_persona_id_raises_before_key(stub_agents: dict[str, int]) -> None:
    """未知 persona_id → UNKNOWN_PERSONA，且无需 Key。"""
    with pytest.raises(AnalyzeError) as ei:
        orchestrator.analyze(
            AnalyzeRequest(text=NORMAL_TEXT, persona_id="not_a_real_persona")
        )
    assert ei.value.code == "UNKNOWN_PERSONA"
    assert "not_a_real_persona" in ei.value.message
    assert stub_agents["agent1"] == 0


def test_keyword_high_risk_still_works(stub_agents: dict[str, int]) -> None:
    """原有关键词闸门回归。"""
    resp = orchestrator.analyze(AnalyzeRequest(text="我怀孕了，今天吃了火锅"))
    assert resp.recommendations == []
    assert resp.meta.degraded_reason == "high_risk_group"
    assert stub_agents["agent1"] == 0


def test_high_risk_block_reasons_helper() -> None:
    assert high_risk_block_reasons(NORMAL_TEXT) == []
    assert high_risk_block_reasons(NORMAL_TEXT, persona_id="overnight_student") == []
    reasons = high_risk_block_reasons(NORMAL_TEXT, persona_id="pregnant")
    assert any("高风险画像" in r and "pregnant" in r for r in reasons)
    assert high_risk_block_reasons("糖尿病控糖")


client = TestClient(app)


@pytest.mark.parametrize(
    "persona_id",
    ["pregnant", "chronic_diabetes", "chronic_hypertension"],
)
def test_offline_high_risk_persona_id(persona_id: str) -> None:
    response = client.post(
        "/api/analyze-offline",
        json={
            "text": NORMAL_TEXT,
            "constitution_override": "balanced",
            "persona_id": persona_id,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["recommendations"] == []
    assert body["basis"]["guardrail_applied"]
    assert any("高风险画像" in g for g in body["basis"]["guardrail_applied"])


def test_offline_unknown_persona_id_422() -> None:
    response = client.post(
        "/api/analyze-offline",
        json={
            "text": NORMAL_TEXT,
            "constitution_override": "balanced",
            "persona_id": "totally_fake",
        },
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "UNKNOWN_PERSONA"


def test_offline_overnight_student_still_recommends() -> None:
    response = client.post(
        "/api/analyze-offline",
        json={
            "text": "中午吃了麻辣烫",
            "constitution_override": "balanced",
            "persona_id": "overnight_student",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["meta"].get("degraded_reason") != "高风险拦截"
