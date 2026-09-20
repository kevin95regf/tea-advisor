"""从旧版迁移回来的协作功能回归测试。"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents.runtime import AgentRun
from app.api import chat as chat_api
from app.main import app
from app.services import medication_reference

client = TestClient(app)


def test_web_starts_without_optional_questionnaire_package():
    """已安装的开发环境也必须覆盖一次“问卷子包不存在”的真实导入链。"""
    code = textwrap.dedent(
        """
        import importlib.abc
        import sys

        class BlockQuestionnaire(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "tcm_constitution" or fullname.startswith("tcm_constitution."):
                    raise ModuleNotFoundError(
                        f"No module named {fullname!r}", name=fullname
                    )
                return None

        sys.meta_path.insert(0, BlockQuestionnaire())

        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        assert client.get("/healthz").status_code == 200

        questions = client.get("/api/questionnaire/questions?sex=male")
        assert questions.status_code == 501, questions.text
        assert "问卷子包未安装" in questions.json()["detail"]

        result = client.post(
            "/api/questionnaire",
            json={"sex": "male", "answers": {}},
        )
        assert result.status_code == 501, result.text
        assert "问卷子包未安装" in result.json()["detail"]
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_offline_analysis_needs_no_key_and_keeps_contract():
    response = client.post(
        "/api/analyze-offline",
        json={"text": "中午吃了麻辣烫", "constitution_override": "balanced"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["backend"] == "offline"
    assert body["meta"]["key_source"] == "not_used"
    assert body["parsed"]["foods"]
    assert body["disclaimer"]["is_medical_advice"] is False


def test_offline_high_risk_returns_no_recommendation():
    response = client.post(
        "/api/analyze-offline",
        json={"text": "我怀孕了，今天吃了火锅", "constitution_override": "balanced"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["recommendations"] == []
    assert body["basis"]["guardrail_applied"]


def test_questionnaire_round_trip_and_core_id_contract():
    questions = client.get("/api/questionnaire/questions?sex=male")
    assert questions.status_code == 200
    payload = questions.json()
    assert payload["questions"]
    assert payload["answer_labels"]["3"]

    answers = {item["id"]: 3 for item in payload["questions"]}
    result = client.post(
        "/api/questionnaire",
        json={"sex": "male", "answers": answers},
    )
    assert result.status_code == 200
    body = result.json()
    ids = {item["id"] for item in body["scores"]}
    assert "phlegm_damp" in ids
    assert "phlegm_dampness" not in ids


def test_chat_preserves_role_history_and_uses_selected_model(monkeypatch):
    captured = {}

    class FakeRuntime:
        def run(self, **kwargs):
            captured.update(kwargs)
            return AgentRun(
                text="建议已结合上轮饮食。",
                elapsed_ms=5,
                session_id="test",
                usage={"prompt_tokens": 20, "completion_tokens": 8},
            )

    monkeypatch.setattr(chat_api, "get_multi_provider_runtime", lambda: FakeRuntime())
    response = client.post(
        "/api/chat",
        headers={"Authorization": "Bearer test-key"},
        json={
            "messages": [
                {"role": "user", "content": "我刚吃了火锅"},
                {"role": "assistant", "content": "可以少量温饮"},
                {"role": "user", "content": "那现在喝什么？"},
            ],
            "model": "deepseek-flash",
            "constitution": "balanced",
        },
    )
    assert response.status_code == 200
    assert response.json()["remembered_messages"] == 3
    assert captured["model"] == "deepseek-flash"
    assert [item["role"] for item in captured["messages"]] == [
        "system",
        "user",
        "assistant",
        "user",
    ]


@pytest.mark.parametrize(
    "authorization",
    ["bearer test-key", "BEARER test-key", "BeArEr test-key", "  Bearer test-key"],
)
def test_chat_uses_shared_case_insensitive_key_parser(monkeypatch, authorization):
    class FakeRuntime:
        def run(self, **kwargs):
            assert kwargs["api_key"] == "test-key"
            return AgentRun(text="可以试试温水。", elapsed_ms=1, session_id="test")

    monkeypatch.setattr(chat_api, "get_multi_provider_runtime", lambda: FakeRuntime())
    response = client.post(
        "/api/chat",
        headers={"Authorization": authorization},
        json={"messages": [{"role": "user", "content": "你好"}]},
    )
    assert response.status_code == 200


def test_chat_rejects_overlong_key_before_provider_call(monkeypatch):
    def fail_if_called():
        raise AssertionError("超长 Key 不应送到模型提供商")

    monkeypatch.setattr(chat_api, "get_multi_provider_runtime", fail_if_called)
    response = client.post(
        "/api/chat",
        headers={"Authorization": "Bearer " + "x" * 300},
        json={"messages": [{"role": "user", "content": "你好"}]},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "NO_API_KEY"


def test_chat_rejects_unknown_model_without_calling_provider():
    response = client.post(
        "/api/chat",
        headers={"Authorization": "Bearer test-key"},
        json={
            "messages": [{"role": "user", "content": "你好"}],
            "model": "not-a-model",
            "constitution": "balanced",
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "UNKNOWN_MODEL"


def test_medication_reference_is_read_only_and_has_no_dosage():
    response = client.get("/api/medication-reference/yang_deficiency")
    assert response.status_code == 200
    body = response.json()
    assert body["profile"]["label"] == "阳虚质"
    assert body["disclaimer"]
    assert "用药建议" in body["usage_policy"]

    raw = medication_reference.load_medication_reference()
    assert "amount_g" not in str(raw)
    assert "max_daily_g" not in str(raw)


def test_new_web_features_are_additive():
    page = Path(__file__).resolve().parents[2] / "ui" / "web" / "index.html"
    source = page.read_text(encoding="utf-8")
    for marker in (
        'id="go"',
        "function run()",
        "renderReferences",
        'id="offline"',
        'id="questionnairePanel"',
        'id="historyPanel"',
        'id="chatPanel"',
        'id="medicationPanel"',
    ):
        assert marker in source
