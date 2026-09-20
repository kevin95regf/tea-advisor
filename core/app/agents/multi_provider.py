"""多模型直连 API 运行时。

支持多个 LLM 提供商，通过统一的 OpenAI 兼容接口调用：
- DeepSeek: https://api.deepseek.com
- 通义千问: https://dashscope.aliyuncs.com/compatible-mode/v1
- 小米 MiMo: https://api.xiaomimimo.com/v1 (OpenAI 兼容)
- HY4: https://api.hy4.ai/v1

所有提供商都使用 Bearer Token 认证。
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

from app.agents.runtime import AgentRun, CredentialError

logger = logging.getLogger(__name__)

# 提供商配置：base_url + 模型名映射
# 可通过环境变量覆盖 base_url
PROVIDERS: dict[str, dict[str, Any]] = {
    "deepseek": {
        "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        "models": {
            "deepseek-flash": "deepseek-chat",
            "deepseek-v4-pro": "deepseek-reasoner",
        },
        "name": "DeepSeek",
    },
    "qwen": {
        "base_url": os.getenv(
            "QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ),
        "models": {
            "qwen-3.8": "qwen-plus",
            "qwen-turbo": "qwen-turbo",
            "qwen-max": "qwen-max",
        },
        "name": "通义千问",
    },
    "mimo": {
        # 官方当前端点。旧域名 api-mimo.xiaomi.com 会导致连接失败。
        "base_url": os.getenv("MIMO_BASE_URL", "https://api.xiaomimimo.com/v1"),
        "models": {
            # 模型 ID 区分大小写，官方示例使用全小写。
            "mimo-v2.5": "mimo-v2.5",
            "mimo-v2.5-pro": "mimo-v2.5-pro",
        },
        "name": "小米 MiMo",
    },
    "hy4": {
        "base_url": os.getenv("HY4_BASE_URL", "https://api.hy4.ai/v1"),
        "models": {
            "hy4": "hy4",
        },
        "name": "HY4",
    },
}

# 前端模型选项 → (提供商, 实际模型名)
MODEL_MAPPING: dict[str, tuple[str, str]] = {}
for provider_id, provider_info in PROVIDERS.items():
    for model_key, model_name in provider_info["models"].items():
        MODEL_MAPPING[model_key] = (provider_id, model_name)


def get_provider_for_model(model_key: str) -> tuple[str, str, str]:
    """根据模型 key 返回 (provider_id, base_url, actual_model_name)。"""
    if model_key not in MODEL_MAPPING:
        # 默认使用 DeepSeek
        return "deepseek", PROVIDERS["deepseek"]["base_url"], "deepseek-chat"

    provider_id, model_name = MODEL_MAPPING[model_key]
    base_url = PROVIDERS[provider_id]["base_url"]
    return provider_id, base_url, model_name


def build_request_body(
    provider_id: str,
    actual_model: str,
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    """构造供应商特定的请求体。

    MiMo V2.5 默认开启深度思考，其长度参数名为
    ``max_completion_tokens``。饮食对话不需要暴露思考过程，因此显式关闭，
    同时不发送会被强制覆盖的 temperature。
    """
    body: dict[str, Any] = {
        "model": actual_model,
        "messages": messages,
    }
    if provider_id == "mimo":
        body.update(
            {
                "max_completion_tokens": 4096,
                "thinking": {"type": "disabled"},
            }
        )
    else:
        body.update({"max_tokens": 4096, "temperature": 0.7})
    return body


class MultiProviderRuntime:
    """多提供商直连运行时。"""

    def __init__(self) -> None:
        self._client = httpx.Client(
            timeout=httpx.Timeout(120.0, connect=15.0),
            follow_redirects=False,
        )

    def ensure_started(self) -> None:
        return None

    def close(self) -> None:
        self._client.close()

    def run(
        self,
        prompt: str,
        system_prompt: str | None = None,
        messages: list[dict[str, str]] | None = None,
        session_id: str | None = None,
        timeout_s: float | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> AgentRun:
        """调用指定模型。"""
        key = (api_key or "").strip()
        if not key:
            raise RuntimeError("缺少 API Key。请在界面上填入你的 API Key。")

        model_key = model or "deepseek-flash"
        provider_id, base_url, actual_model = get_provider_for_model(model_key)

        request_messages = list(messages or [])
        if not request_messages:
            if system_prompt:
                request_messages.append({"role": "system", "content": system_prompt})
            request_messages.append({"role": "user", "content": prompt})
        elif system_prompt and request_messages[0].get("role") != "system":
            request_messages.insert(0, {"role": "system", "content": system_prompt})

        body = build_request_body(provider_id, actual_model, request_messages)

        sid = session_id or f"ta-{int(time.time() * 1000)}"
        url = base_url + "/chat/completions"
        provider_name = PROVIDERS.get(provider_id, {}).get("name", provider_id)

        logger.info(
            "调用模型 provider=%s model=%s sid=%s",
            provider_name,
            actual_model,
            sid,
        )

        started = time.perf_counter()
        try:
            resp = self._client.post(
                url,
                json=body,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                timeout=timeout_s or 120.0,
            )
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"调用 {provider_name} 超时（>{timeout_s or 120.0:.0f}s）。"
                "可能是网络慢或模型正忙，重试一次通常就好了。"
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"连接 {provider_name} 失败（{type(exc).__name__}）"
            ) from exc

        elapsed_ms = int((time.perf_counter() - started) * 1000)

        if resp.status_code != 200:
            detail = self._describe_error(resp.status_code, provider_name)
            if resp.status_code in (401, 402, 403):
                raise CredentialError(detail)
            raise RuntimeError(detail)

        try:
            data = resp.json()
        except ValueError as exc:
            raise RuntimeError(f"{provider_name} 返回了无法解析的响应。") from exc
        usage = data.get("usage") or {}
        message = (data.get("choices") or [{}])[0].get("message") or {}
        text = (message.get("content") or "").strip()

        logger.info(
            "调用完成 provider=%s model=%s %dms prompt=%s completion=%s",
            provider_name,
            actual_model,
            elapsed_ms,
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
        )

        if not text:
            raise RuntimeError(
                f"{provider_name} 未返回正文。可能是 max_tokens 太小或模型异常。"
            )

        return AgentRun(
            text=text,
            elapsed_ms=elapsed_ms,
            session_id=sid,
            usage=usage or None,
        )

    @staticmethod
    def _describe_error(status: int, provider_name: str) -> str:
        if status == 401:
            return f"{provider_name} API Key 无效或已失效（HTTP 401）。请检查你填的 Key 是否正确。"
        if status == 402:
            return f"{provider_name} 账户余额不足（HTTP 402）。请充值后重试。"
        if status == 403:
            return f"{provider_name} API Key 无权访问该模型（HTTP 403）。"
        if status == 404:
            return f"{provider_name} 模型不存在或未开通（HTTP 404）。请检查模型名称是否正确。"
        if status == 429:
            return f"{provider_name} 请求过于频繁，被限流（HTTP 429）。稍等片刻再试。"
        if status >= 500:
            return f"{provider_name} 服务端错误（HTTP {status}）。稍后重试。"
        return f"{provider_name} 调用失败（HTTP {status}）。"


# 全局单例
_runtime: MultiProviderRuntime | None = None


def get_multi_provider_runtime() -> MultiProviderRuntime:
    global _runtime
    if _runtime is None:
        _runtime = MultiProviderRuntime()
    return _runtime


def close_multi_provider_runtime() -> None:
    global _runtime
    if _runtime is not None:
        _runtime.close()
        _runtime = None
