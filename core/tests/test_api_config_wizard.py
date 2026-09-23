"""五步配置向导的后端支撑与静态资源。

界面（ui/web/index.html）的 API 配置已改成
**选择供应商 → API Key → 模型名称 → 连接测试 → 功能选项**，
对应三条各自最容易悄悄坏掉的链路：

1. 供应商列表列出来的模型必须**真的能调** —— 界面能选、后端 422 是骗人；
2. 连接测试的 Key **绝不能回显**，且要映射成和 /api/chat 同一套错误码，
   否则前端得为测试单做一套引导；
3. three.js 是随仓库内联的，静态路由没挂上时 3D 小人会**静默**退回二维图 ——
   没有测试的话这个退化不会有人发现（那正是最难查的一类问题）。
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.agents.multi_provider import MODEL_MAPPING, PROVIDERS
from app.agents.runtime import AgentRun, CredentialError
from app.api import chat as chat_api
from app.main import app

client = TestClient(app)

# 哨兵值：断言它一次都不出现在响应体里
SENTINEL_KEY = "sk-SENTINEL-DO-NOT-LEAK-0123456789"


# ============================================================
# 1. 第 1 步：选择供应商
# ============================================================
def test_providers_endpoint_covers_every_provider() -> None:
    r = client.get("/api/chat/providers")
    assert r.status_code == 200
    providers = r.json()

    assert {item["id"] for item in providers} == set(PROVIDERS)
    for item in providers:
        assert item["name"], f"{item['id']} 缺展示名"
        # 请求地址必须露出来：让人盲填 Key 是这类配置界面最常见的问题
        assert item["base_url"].startswith("http"), item["base_url"]
        assert item["models"], f"{item['id']} 没有可选模型"
        assert item["default_model"] in {m["id"] for m in item["models"]}
        for model in item["models"]:
            assert model["id"] in MODEL_MAPPING, (
                f"界面列出 {item['id']} 的模型 {model['id']}，但后端调不了"
            )


def test_provider_base_url_matches_runtime() -> None:
    """/chat/test 与 /chat 必须发往同一个地址。

    两者各读一份配置的话，测试通过而真实请求打到别处是完全可能的 ——
    那样「连接测试」就成了安慰剂。
    """
    for item in client.get("/api/chat/providers").json():
        assert item["base_url"] == PROVIDERS[item["id"]]["base_url"]


# ============================================================
# 2. 第 4 步：连接测试
# ============================================================
def _fail_if_called() -> None:
    raise AssertionError("不该发出任何出站调用")


def test_unknown_model_is_rejected_before_any_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_api, "get_multi_provider_runtime", _fail_if_called)
    r = client.post(
        "/api/chat/test",
        json={"model": "not-a-model"},
        headers={"Authorization": "Bearer " + SENTINEL_KEY},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "UNKNOWN_MODEL"


def test_missing_key_is_rejected_before_any_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_api, "get_multi_provider_runtime", _fail_if_called)
    r = client.post("/api/chat/test", json={"model": "deepseek-flash"})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "NO_API_KEY"


def test_connection_test_success_reports_target_and_hides_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    class FakeRuntime:
        def run(self, **kwargs):  # noqa: ANN001 - 形状与真实运行时一致即可
            captured.update(kwargs)
            return AgentRun(
                text="OK",
                elapsed_ms=3,
                session_id="test",
                usage={"prompt_tokens": 5, "completion_tokens": 1},
            )

    monkeypatch.setattr(chat_api, "get_multi_provider_runtime", lambda: FakeRuntime())
    r = client.post(
        "/api/chat/test",
        json={"model": "mimo-v2.5"},
        headers={"Authorization": "Bearer " + SENTINEL_KEY},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["provider"] == "mimo"
    assert body["provider_name"] == PROVIDERS["mimo"]["name"]
    assert body["remote_model"] == "mimo-v2.5"
    assert body["base_url"] == PROVIDERS["mimo"]["base_url"]
    assert body["elapsed_ms"] >= 0

    assert captured["api_key"] == SENTINEL_KEY, "Key 必须真的送到运行时"
    # Key 绝不回显：响应体里既不能有 Key，也不能有 Authorization 头的痕迹
    assert SENTINEL_KEY not in r.text
    assert "Bearer" not in r.text


def test_connection_test_uses_a_short_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """连接测试不该让人对着转圈等 120 秒 —— 它只需要一次极小的往返。"""
    captured: dict = {}

    class FakeRuntime:
        def run(self, **kwargs):  # noqa: ANN001
            captured.update(kwargs)
            return AgentRun(text="OK", elapsed_ms=1, session_id="t")

    monkeypatch.setattr(chat_api, "get_multi_provider_runtime", lambda: FakeRuntime())
    client.post(
        "/api/chat/test",
        json={"model": "deepseek-flash"},
        headers={"Authorization": "Bearer " + SENTINEL_KEY},
    )
    assert captured.get("timeout_s") is not None
    assert captured["timeout_s"] <= 20


def test_credential_error_maps_to_400(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeRuntime:
        def run(self, **kwargs):  # noqa: ANN001
            raise CredentialError("API Key 无效或已失效（HTTP 401）。")

    monkeypatch.setattr(chat_api, "get_multi_provider_runtime", lambda: FakeRuntime())
    r = client.post(
        "/api/chat/test",
        json={"model": "deepseek-flash"},
        headers={"Authorization": "Bearer " + SENTINEL_KEY},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "API_KEY_REJECTED"
    assert SENTINEL_KEY not in r.text


def test_runtime_error_maps_to_502(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeRuntime:
        def run(self, **kwargs):  # noqa: ANN001
            raise RuntimeError("DeepSeek 调用失败（ConnectError）")

    monkeypatch.setattr(chat_api, "get_multi_provider_runtime", lambda: FakeRuntime())
    r = client.post(
        "/api/chat/test",
        json={"model": "deepseek-flash"},
        headers={"Authorization": "Bearer " + SENTINEL_KEY},
    )
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "MODEL_ERROR"
    assert SENTINEL_KEY not in r.text


# ============================================================
# 3. 3D 小人：内联静态资源必须真的被服务出来
# ============================================================
def test_three_js_is_served_from_local_app() -> None:
    r = client.get("/assets/three.module.min.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    # 错误页/占位文件不会带 MIT 头，也不会有这个体积
    assert b"Three.js Authors" in r.content[:400]
    assert len(r.content) > 300_000


def test_mascot3d_module_is_served_and_wired_into_page() -> None:
    module = client.get("/assets/mascot3d.js")
    assert module.status_code == 200
    assert "mascotStage" in module.text

    page = client.get("/").text
    assert 'type="module" src="assets/mascot3d.js"' in page
    assert 'id="mascotStage"' in page
    assert 'id="mascotCanvas"' in page
    # 3D 起不来时必须还有二维图可看（同时也是 test_web_assets 的依赖）
    assert re.search(r'<img[^>]+src="[^"]*mascot\.png"', page)


# ============================================================
# 4. 五步结构本身
# ============================================================
def test_config_dialog_lists_five_steps_in_order() -> None:
    page = client.get("/").text
    titles = ["选择供应商", "API Key", "模型名称", "连接测试", "功能选项"]
    positions = [page.index(title) for title in titles]
    assert positions == sorted(positions), f"步骤顺序不对：{list(zip(titles, positions))}"
    for step in range(1, 6):
        assert f'data-step="{step}"' in page


def test_connection_test_button_and_function_options_exist() -> None:
    page = client.get("/").text
    assert 'id="connTest"' in page
    assert 'id="connResult"' in page
    # 「自动生成建议后记入饮食记录」默认必须勾选：否则改动会静默改变既有行为
    save_history = re.search(r'<input[^>]*\bid="saveHistory"[^>]*>', page)
    assert save_history is not None
    assert re.search(r"\bchecked\b", save_history.group(0)), "饮食记录应默认继续记"
    # 反过来，「记住 API Key」默认不能勾（守卫 1 也盯着这条）
    remember = re.search(r'<input[^>]*\bid="remember"[^>]*>', page)
    assert remember is not None
    assert not re.search(r"\bchecked\b", remember.group(0))
