"""/api/chat 的 pet_signals：只给互动小人状态，不给内容。

为什么要单测：这个字段是给前端动画看的，最容易被人顺手塞进
「命中的关键词」「模型回复片段」之类的内容，那就违背了「只碰状态」的约定。
全部用假运行时，不发任何出站请求。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.agents.runtime import AgentRun
from app.api import chat as chat_api
from app.main import app

client = TestClient(app)
FAKE_KEY = "sk-PET-SIGNAL-TEST-0000000000"


def _fail_if_called() -> None:
    raise AssertionError("不该发出任何出站调用")


def test_high_risk_sets_safety_flag_without_content(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_api, "get_multi_provider_runtime", _fail_if_called)
    text = "我怀孕了，正在吃药，能喝什么茶"
    r = client.post("/api/chat", json={"messages": [{"role": "user", "content": text}]})
    assert r.status_code == 200
    sig = r.json()["pet_signals"]
    assert sig == {"tool_used": False, "tools": [], "safety_flag": True}
    # 信号里不能出现用户原文的任何片段
    assert "怀孕" not in str(sig) and "吃药" not in str(sig)


def test_normal_reply_reports_kb_lookup_names_only(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeRuntime:
        def run(self, **kwargs):  # noqa: ANN001
            return AgentRun(text="可以试试清淡一些的饮食。", elapsed_ms=1, session_id="t", usage=None)

    monkeypatch.setattr(chat_api, "get_multi_provider_runtime", lambda: FakeRuntime())
    r = client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "中午吃了火锅"}], "constitution": "balanced"},
        headers={"Authorization": "Bearer " + FAKE_KEY},
    )
    assert r.status_code == 200, r.text
    sig = r.json()["pet_signals"]
    assert sig["tool_used"] is True
    assert sig["tools"] == ["filter_by_constitution", "herb_evidence"]
    assert sig["safety_flag"] is False
    assert set(sig) == {"tool_used", "tools", "safety_flag"}
    assert "火锅" not in str(sig) and "清淡" not in str(sig)
