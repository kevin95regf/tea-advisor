"""直连 DeepSeek 官方 API 的 Agent 运行时（不经过 dsh）。

为什么需要这个后端
------------------
`dsh` 的 API Key 生效粒度是「一个 harness 实例 = 一个 dsh 子进程」：
`DeepSeekHarness.__init__` 会把 `api_key` 写进**子进程环境**，
而 `run()` 没有任何凭据参数。所以 dsh 后端天然是「一个进程一个 Key」。

本后端把 Key 当作普通 HTTP 请求头**逐次**传入，因此支持「用户自带 Key」：
不落盘、不进子进程环境、不写运行时目录。这也是默认后端。

与 dsh 后端的三个实质差异（改动提示词相关代码前必读）
----------------------------------------------------
1. **没有 dsh 自带 persona/工具上下文。** dsh 会额外注入一大段上下文
   （实测每次调用缓存命中输入约 9,000 tokens，而本项目的提示词才一两千字符）。
   直连只发送本项目自己的提示词，输入 token 大幅下降，
   但**提示词的遵守度必须重新验证**：
       python scripts/test_food_accuracy.py     # 属性准确率
       python scripts/smoke_agents.py           # 全链路格式
2. **系统提示词改用标准 system 角色。** dsh 后端是把它拼在 user 消息前
   （见 runtime.py 的说明），这里用 `messages=[{system},{user}]`，更规范。
3. **调用是无状态的。** 不存在 dsh 那种「复用 session_id 会延续同一段持久对话」
   的坑；`session_id` 参数仅为兼容接口而保留，不参与请求。

安全约定（硬规则，配套测试见 tests/test_key_handling.py）
-------------------------------------------------------
**绝不记录 Authorization 头，绝不把 Key 写进日志或响应体。**
本模块只记录：模型名、接口主机名、耗时、token 用量。
异常信息里不得出现 Key —— 官方 401 响应体自带掩码（`****0000`），
但为了稳妥，出错时也只截取状态码与固定文案。
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.agents.runtime import AgentRun, CredentialError
from app.config import get_settings

logger = logging.getLogger(__name__)

# 官方 OpenAI 兼容端点
CHAT_PATH = "/chat/completions"

# 官方映射：minimal→low, low→low, medium→high, high→high, xhigh→high, max→max, ultra→max
# 本项目只暴露官方语义明确的三个档位 + 关闭。
_VALID_EFFORTS = ("low", "high", "max")
_OFF_VALUES = ("off", "none", "disabled")


def build_thinking_params(effort: str | None) -> dict[str, Any]:
    """把 TA_REASONING_EFFORT 翻译成官方 API 的思考模式参数。

    * `off` / `none` / `disabled` → 关闭思考。
      实测同一任务输出 token 从 135 降到 5，延迟 1165ms → 889ms。
    * `low` / `high` / `max` → 开启思考并指定强度。
    * 其他值 → 记警告并按 low 处理（宁可慢一点，也不要因为配置写错而静默变贵）。
    * 空值 → 官方默认是「开启 + effort=high」，这里仍按 low 处理，
      与项目原本的默认行为保持一致。
    """
    e = (effort or "").strip().lower()
    if e in _OFF_VALUES:
        return {"thinking": {"type": "disabled"}}
    if e in _VALID_EFFORTS:
        return {"thinking": {"type": "enabled"}, "reasoning_effort": e}
    if e:
        logger.warning("TA_REASONING_EFFORT=%r 不是已知取值，按 low 处理", effort)
    return {"thinking": {"type": "enabled"}, "reasoning_effort": "low"}


class DirectAPIRuntime:
    """逐请求凭据的直连运行时。接口与 HarnessRuntime 一致：run() / close()。"""

    def __init__(self) -> None:
        self._settings = get_settings()
        # 连接池复用：Agent2 单次要十几秒，超时按项目配置给足
        self._client = httpx.Client(
            timeout=httpx.Timeout(120.0, connect=15.0),
            follow_redirects=False,
        )

    # ------------------------------------------------------------
    # 生命周期（直连无需启动任何东西，方法保留是为了接口一致）
    # ------------------------------------------------------------
    def ensure_started(self, api_key: str | None = None) -> None:
        """直连后端没有"启动"这一步；保留方法以对齐 `HarnessRuntime` 的调用形状。

        `api_key` **收下但刻意忽略**：直连后端的 Key 是逐请求传的（`run(api_key=...)`），
        启动时不需要、也不应该记住它 —— 记住就等于让进程持有一份凭据，
        与"本项目不保存 Key"的设计相悖。参数存在只是为了让调用方
        能用同一个形状调用两个运行时。

        历史 bug：本方法曾不收任何参数，而 `scripts/smoke_agents.py` 按 dsh 的形状
        调 `ensure_started(api_key)`，导致该脚本自 826b44a 起一启动就 TypeError、
        从未跑通过（默认后端正是 direct）。所以**形状必须两边兼容**。
        """
        del api_key  # 显式丢弃：既不落盘，也不留在实例上
        return None

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:  # pragma: no cover
            logger.warning("关闭 HTTP 客户端时出错", exc_info=True)

    # ------------------------------------------------------------
    # 调用
    # ------------------------------------------------------------
    def run(
        self,
        prompt: str,
        system_prompt: str | None = None,
        session_id: str | None = None,
        timeout_s: float | None = None,
        api_key: str | None = None,
    ) -> AgentRun:
        """跑一轮 agent。

        `api_key` **必传**：本项目不使用服务端内置 Key，Key 由调用方显式提供
        （网页来自 Authorization 头，终端与脚本来自环境变量）。
        `session_id` 不参与请求（直连无状态），仅用于日志串联。
        """
        key = (api_key or "").strip()
        if not key:
            # 正常情况下编排层会先拦下并给出更精确的 NO_API_KEY；
            # 走到这里说明有调用方绕过了校验，属于代码缺陷，要显式暴露。
            raise RuntimeError(self._settings.missing_credentials_hint())

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        body: dict[str, Any] = {
            "model": self._settings.model,
            "messages": messages,
            "max_tokens": self._settings.max_tokens,
        }
        body.update(build_thinking_params(self._settings.reasoning_effort))

        sid = session_id or f"ta-{int(time.time() * 1000)}"
        url = self._settings.resolved_base_url + CHAT_PATH
        # 只记录主机名，绝不记录 header
        host = self._settings.resolved_base_url

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
                f"调用模型超时（>{timeout_s or 120.0:.0f}s，host={host}）。"
                "可能是网络慢或模型正忙，重试一次通常就好了。"
            ) from exc
        except httpx.HTTPError as exc:
            # 只报异常类型与主机名：httpx 的异常信息里不含 header
            raise RuntimeError(
                f"连接模型服务失败（{type(exc).__name__}，host={host}）"
            ) from exc
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        if resp.status_code != 200:
            detail = self._describe_error(resp.status_code)
            # 凭据类错误用专门的类型，让上层回"去改 Key"而不是"解析失败"
            if resp.status_code in (401, 402, 403):
                raise CredentialError(detail)
            raise RuntimeError(detail)

        data = resp.json()
        usage = data.get("usage") or {}
        message = (data.get("choices") or [{}])[0].get("message") or {}
        text = (message.get("content") or "").strip()
        finish_reason = (data.get("choices") or [{}])[0].get("finish_reason")

        logger.info(
            "直连调用完成 model=%s host=%s sid=%s %dms "
            "prompt=%s completion=%s reasoning=%s cache_hit=%s",
            data.get("model", self._settings.model),
            host,
            sid,
            elapsed_ms,
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
            (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
            usage.get("prompt_cache_hit_tokens"),
        )

        if not text:
            # 实测坑：思考模式下 max_tokens 太小会被思考吃光，content 返回空串。
            reasoning_tokens = (usage.get("completion_tokens_details") or {}).get(
                "reasoning_tokens"
            )
            raise RuntimeError(
                f"模型未返回正文（finish_reason={finish_reason}，"
                f"思考 token={reasoning_tokens}，max_tokens={self._settings.max_tokens}）。"
                "若 max_tokens 偏小，思考会把它耗尽 —— 调大 TA_MAX_TOKENS，"
                "或把 TA_REASONING_EFFORT 设为 off。"
            )

        return AgentRun(
            text=text,
            elapsed_ms=elapsed_ms,
            session_id=sid,
            usage=usage or None,
        )

    @staticmethod
    def _describe_error(status: int) -> str:
        """把 HTTP 状态码翻成可操作的中文。

        刻意**不**回显响应体：官方 401 的响应体里带掩码后的 Key，
        虽然已脱敏，但"绝不回显任何与凭据相关的内容"这条规则更容易守。
        """
        if status == 401:
            return "API Key 无效或已失效（HTTP 401）。请检查你填的 Key 是否正确、是否已被重置。"
        if status == 402:
            return "账户余额不足（HTTP 402）。请在 DeepSeek 平台充值后重试。"
        if status == 403:
            return "API Key 无权访问该模型（HTTP 403）。"
        if status == 429:
            return "请求过于频繁，被限流（HTTP 429）。稍等片刻再试。"
        if status >= 500:
            return f"模型服务端错误（HTTP {status}）。稍后重试。"
        return f"模型调用失败（HTTP {status}）。"
