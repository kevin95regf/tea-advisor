"""用户主画像 personas.json：加载、闸门、引用完整性、只读工具。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

CORE = Path(__file__).resolve().parent.parent
DATA = CORE / "data"

EXPECTED_IDS = {
    "overnight_student",
    "alcohol_middle_age",
    "regular_office",
    "takeout_heavy",
    "fitness",
    "vegetarian",
    "pregnant",
    "weight_loss_youth",
    "retired_elder",
    "chronic_diabetes",
    "chronic_hypertension",
}

EXPECTED_DISPLAY = {
    "overnight_student": "熬夜大学生",
    "alcohol_middle_age": "爱喝酒中年人",
    "regular_office": "规律上班族",
    "takeout_heavy": "外卖党",
    "fitness": "健身人群",
    "vegetarian": "素食者",
    "pregnant": "孕期女性",
    "weight_loss_youth": "减肥年轻人",
    "retired_elder": "退休老人",
    "chronic_diabetes": "慢性病糖尿病",
    "chronic_hypertension": "慢性病高血压",
}

HIGH_RISK_IDS = {"pregnant", "chronic_diabetes", "chronic_hypertension"}

SAMPLE_COUNTS = {
    "overnight_student": 3000,
    "alcohol_middle_age": 3000,
    "regular_office": 3000,
    "takeout_heavy": 3000,
    "fitness": 3000,
    "vegetarian": 3000,
    "pregnant": 3000,
    "weight_loss_youth": 3000,
    "retired_elder": 3000,
    "chronic_diabetes": 1500,
    "chronic_hypertension": 1500,
}


@pytest.fixture(scope="module")
def constitution_ids():
    raw = json.loads((DATA / "constitution.json").read_text(encoding="utf-8"))
    items = raw.get("constitutions") or raw.get("items") or []
    return {c["id"] for c in items if isinstance(c, dict) and c.get("id")}


@pytest.fixture(scope="module")
def signal_ids():
    raw = json.loads((DATA / "diet_signals.json").read_text(encoding="utf-8"))
    items = raw.get("signals") or raw.get("items") or []
    return {s["id"] for s in items if isinstance(s, dict) and s.get("id")}


@pytest.fixture(scope="module")
def personas_payload():
    path = DATA / "personas.json"
    assert path.is_file(), "personas.json 必须存在"
    return json.loads(path.read_text(encoding="utf-8"))


def test_personas_file_exactly_eleven(personas_payload):
    meta = personas_payload.get("_meta") or {}
    assert meta.get("version") == "0.1.0"
    assert meta.get("review_status") == "unreviewed"
    personas = personas_payload["personas"]
    assert len(personas) == 11
    ids = {p["id"] for p in personas}
    assert ids == EXPECTED_IDS
    names = {p["display_name"] for p in personas}
    assert len(names) == 11


def test_display_names_and_notes_match_sample(personas_payload):
    by_id = {p["id"]: p for p in personas_payload["personas"]}
    for pid, name in EXPECTED_DISPLAY.items():
        assert by_id[pid]["display_name"] == name
        assert by_id[pid]["sample_primary_count"] == SAMPLE_COUNTS[pid]
        assert isinstance(by_id[pid]["brief_note"], str) and by_id[pid]["brief_note"].strip()
        assert by_id[pid]["review_status"] == "pending"


def test_three_high_risk_gates(personas_payload):
    by_id = {p["id"]: p for p in personas_payload["personas"]}
    for pid in HIGH_RISK_IDS:
        p = by_id[pid]
        assert p["safety_gate"] == "high_risk"
        kws = p.get("high_risk_keywords") or []
        assert kws, pid
    assert by_id["pregnant"]["high_risk_keywords"]
    assert "孕期" in by_id["pregnant"]["high_risk_keywords"]
    assert "孕妇" in by_id["pregnant"]["high_risk_keywords"]
    assert "糖尿病" in by_id["chronic_diabetes"]["high_risk_keywords"]
    assert "高血压" in by_id["chronic_hypertension"]["high_risk_keywords"]
    for pid, p in by_id.items():
        if pid not in HIGH_RISK_IDS:
            assert p["safety_gate"] == "none"


def test_constitution_and_signal_refs(personas_payload, constitution_ids, signal_ids):
    for p in personas_payload["personas"]:
        for h in p.get("constitution_hints") or []:
            assert h["constitution_id"] in constitution_ids, (p["id"], h)
            assert h["tendency"] in {"likely", "possible", "avoid_claim"}
        for s in p.get("diet_signal_tendencies") or []:
            assert s["signal_id"] in signal_ids, (p["id"], s)
            assert s["tendency"] in {"elevated", "reduced", "neutral"}
        # 高风险画像不得写「推荐茶/汤」类 suitable
        blob = json.dumps(p, ensure_ascii=False)
        assert "suitable_teas" not in p
        assert "推荐茶" not in blob
        assert "推荐汤" not in blob


def test_loader_and_tools():
    from app.services.personas import (
        clear_personas_cache,
        get_persona,
        list_personas,
        load_personas,
        match_persona_keywords,
        persona_is_high_risk,
        PersonaNotFound,
        PersonasError,
        validate_personas_payload,
    )

    clear_personas_cache()
    data = load_personas()
    assert len(data["personas"]) == 11

    all_p = list_personas()
    assert len(all_p) == 11
    assert list_personas(include_pending=False) == []

    preg = get_persona("pregnant")
    assert preg["display_name"] == "孕期女性"
    assert preg["_query_meta"]["auto_recommend_allowed"] is False

    with pytest.raises(PersonaNotFound):
        get_persona("not_a_real_persona")

    assert persona_is_high_risk("pregnant") is True
    assert persona_is_high_risk("regular_office") is False
    assert persona_is_high_risk("nope") is False

    assert "pregnant" in match_persona_keywords("我是孕期女性少食多餐")
    assert "chronic_diabetes" in match_persona_keywords("有糖尿病要注意")
    assert "chronic_hypertension" in match_persona_keywords("高血压患者")

    # 校验器拒绝非法 id 引用
    bad = json.loads(json.dumps(data))
    bad["personas"][0]["constitution_hints"] = [
        {"constitution_id": "not_real", "tendency": "possible", "note": "x"}
    ]
    with pytest.raises(PersonasError):
        validate_personas_payload(bad)


def test_detect_high_risk_keywords_still_hit():
    from app.domain.safety import (
        HIGH_RISK_KEYWORDS,
        detect_high_risk,
        persona_id_is_high_risk,
        text_hits_high_risk_persona,
    )

    assert "孕期" in HIGH_RISK_KEYWORDS
    assert "孕期" in detect_high_risk("孕期需要注意饮食")
    assert "糖尿病" in detect_high_risk("糖尿病控糖")
    assert "高血压" in detect_high_risk("高血压少盐")

    assert persona_id_is_high_risk("pregnant") is True
    assert persona_id_is_high_risk("takeout_heavy") is False
    assert "pregnant" in text_hits_high_risk_persona("孕期女性咨询")
    assert "chronic_diabetes" in text_hits_high_risk_persona("慢性病糖尿病")


def test_tool_registry_stub_resolves_persona_tools():
    from app.agents.tool_registry_stub import iter_tool_specs, resolve_tool

    names = {s["name"] for s in iter_tool_specs()}
    assert "list_personas" in names and "get_persona" in names
    lst = resolve_tool("list_personas")
    get = resolve_tool("get_persona")
    assert callable(lst) and callable(get)
    assert len(lst()) == 11
    assert get("fitness")["id"] == "fitness"
