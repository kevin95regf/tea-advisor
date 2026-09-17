"""Agent 运行时。两个后端，用 TA_BACKEND 选。

  direct（默认）  DirectAPIRuntime —— 直连 DeepSeek 官方 API，见 direct_api.py。
                  API Key 逐请求传入，支持"用户自带 Key"。
  dsh             HarnessRuntime  —— 走 DeepSeekHarness 子进程（本文件）。
                  Key 绑在 harness 实例上，**不支持逐请求换 Key**，保留用于调试。

为什么默认是 direct：dsh 的 Key 生效粒度是「一个 harness 实例 = 一个子进程」
（`DeepSeekHarness.__init__` 把 api_key 写进子进程环境，`run()` 没有凭据参数），
与"每个请求带自己的 Key"直接冲突。详见 direct_api.py 的模块说明。

dsh 后端的设计要点
------------------
1. 进程复用：DeepSeekHarness 启动一次 dsh 子进程，多次 run() 复用，避免每次请求都拉起进程。
2. 凭据隔离：DSH_HOME 指向独立目录（默认 <仓库根>/dsh-home，可用 credentials.env 覆盖），
   与你的主 DSH 环境分开，避免污染主环境的 profile / settings / sessions。
3. 会话隔离：每个 agent 用独立 session_id 前缀，避免对话历史互相污染。
4. 不设工具：本项目的两个 Agent 都是纯 文本→JSON 任务，不需要读写文件或执行命令。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

# SDK 只暴露这一个公开类型；其余细节见官方文档 python/sdk/README
try:  # pragma: no cover - 依赖安装后才会走到
    from deepseek_harness import DeepSeekHarness
except Exception:  # pragma: no cover
    DeepSeekHarness = None  # type: ignore[assignment]


@dataclass
class AgentRun:
    """一次 Agent 调用的结果。"""

    text: str
    elapsed_ms: int
    session_id: str
    # 模型返回的 token 用量（direct 后端会填；dsh 后端拿不到，为 None）。
    # 只用于日志与成本核算，不含任何凭据信息。
    usage: dict[str, Any] | None = None


class CredentialError(RuntimeError):
    """凭据被模型服务方拒绝（Key 无效 / 余额不足 / 无权限）。

    单独一个类型是为了让上层能把它与"解析失败"区分开：
    用户自带 Key 模式下，填错 Key 是最常见的错误，
    必须回一个"去改 Key"的提示，而不是"没看懂你吃了什么"。
    """


class HarnessRuntime:
    """全局单例，进程内复用同一个 DSH 子进程。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._harness = None
        self._key = ""  # 当前子进程用的 Key，用于检测"换 Key"的请求
        self._settings = get_settings()

    # ------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------
    def ensure_started(self, api_key: str | None = None) -> None:
        """按需启动运行时。重复调用不会重复启动。

        `api_key` 必传：本项目不使用服务端内置 Key，Key 由调用方提供。
        由于 dsh 的 Key 与子进程绑定，**只有首次启动时传入的 Key 生效**；
        之后若请求不同的 Key，run() 会明确报错而不是静默复用旧 Key。
        """
        with self._lock:
            if self._harness is not None:
                return

            if DeepSeekHarness is None:
                raise RuntimeError(
                    "未安装 deepseek-harness-sdk。请执行：pip install deepseek-harness-sdk"
                )

            key = (api_key or "").strip()
            if not key:
                raise RuntimeError(self._settings.missing_credentials_hint())

            dsh_home = Path(self._settings.dsh_home)
            dsh_home.mkdir(parents=True, exist_ok=True)

            # workspace 用项目根目录；本项目的 agent 不需要读写文件，仅作占位
            workspace = self._settings.data_dir.parent.parent
            workspace.mkdir(parents=True, exist_ok=True)

            # ------------------------------------------------------------
            # 关键：这些变量必须进入「子进程环境」，不能只放在 .env 里。
            # dsh 会拒绝从 .env 读取 DSH_HOME（它决定进程如何启动与联网），
            # 所以这里显式注入 os.environ，子进程会继承。
            # 同时把 .env 的路径常量清掉，避免 dsh 在 .env 里看到它们再次报错。
            # ------------------------------------------------------------
            _DSH_OWNED_VARS = ("DSH_HOME", "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL")
            for var in _DSH_OWNED_VARS:
                os.environ.pop(var, None)

            os.environ["DSH_HOME"] = str(dsh_home)
            os.environ["DEEPSEEK_API_KEY"] = key
            if self._settings.deepseek_base_url:
                os.environ["DEEPSEEK_BASE_URL"] = self._settings.deepseek_base_url

            kwargs = {
                "dsh_home": str(dsh_home),
                "cwd": str(workspace),
                "provider": self._settings.provider,
                "model": self._settings.model,
                "max_tokens": self._settings.max_tokens,
            }
            if self._settings.reasoning_effort:
                kwargs["reasoning_effort"] = self._settings.reasoning_effort
            # 凭据显式传入（SDK 会用它覆盖子进程环境）
            kwargs["api_key"] = key
            if self._settings.deepseek_base_url:
                kwargs["base_url"] = self._settings.deepseek_base_url

            logger.info("正在启动 DSH 运行时: model=%s home=%s", self._settings.model, dsh_home)
            self._harness = DeepSeekHarness(**kwargs)
            self._key = key
            # DeepSeekHarness 是上下文管理器；这里手动进入以长期持有
            self._harness.__enter__()
            logger.info("DSH 运行时已就绪")

    def close(self) -> None:
        with self._lock:
            if self._harness is not None:
                try:
                    self._harness.__exit__(None, None, None)
                except Exception:  # pragma: no cover
                    logger.warning("关闭 DSH 运行时时出错", exc_info=True)
                finally:
                    self._harness = None

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
        """跑一轮 agent，返回最终助手文本。

        注意：DSH 的 persona 取环境变量 DSH_SYSTEM_PROMPT。若要按 agent 切换
        系统提示词，需要用 patch 文件为每个 profile 单独配置（见 README 的"待验证事项"）。
        因此当前实现把 system_prompt 作为 user 消息的前缀注入，稳妥且无副作用。

        `api_key` 必传。dsh 后端**不支持**逐请求换 Key：子进程只认第一次启动时
        传入的那个 Key。请求了不同的 Key 时宁可明确报错，也不静默复用旧 Key ——
        那会让用户以为自己填的 Key 生效了、以为费用记在自己账上。
        """
        key = (api_key or "").strip()
        if not key:
            raise RuntimeError(self._settings.missing_credentials_hint())

        # 先比对再启动子进程：避免为一个用不了的请求付出 ~2 秒启动成本
        if self._harness is not None and key != self._key:
            raise RuntimeError(
                "当前 dsh 运行时已用另一个 API Key 启动，"
                "dsh 不支持逐请求换 Key（Key 与 harness 子进程绑定）。"
                "请把 TA_BACKEND 设为 direct（默认）后重试，"
                "或重启进程以换用新 Key。"
            )

        self.ensure_started(key)
        assert self._harness is not None

        if system_prompt:
            prompt = f"{system_prompt}\n\n---\n\n{prompt}"

        sid = session_id or f"ta-{int(time.time() * 1000)}"
        started = time.perf_counter()
        with self._lock:  # 串行调用，避免同进程并发对话交错
            result = self._harness.run(prompt, session_id=sid)
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        text = getattr(result, "final_response", None) or ""
        finish_reason = getattr(result, "finish_reason", None)
        if not text:
            raise RuntimeError(
                f"agent 未返回文本 (session_id={sid}, finish_reason={finish_reason})"
            )
        return AgentRun(text=text, elapsed_ms=elapsed_ms, session_id=sid)


# ============================================================
# 后端选择
# ============================================================
_harness_runtime: HarnessRuntime | None = None
_direct_runtime: Any | None = None
_runtime_lock = threading.Lock()


def get_harness_runtime() -> HarnessRuntime:
    """dsh 后端单例（TA_BACKEND=dsh 时使用）。"""
    global _harness_runtime
    if _harness_runtime is None:
        with _runtime_lock:
            if _harness_runtime is None:
                _harness_runtime = HarnessRuntime()
    return _harness_runtime


def get_runtime() -> Any:
    """按 TA_BACKEND 返回当前后端。

    * `direct`（默认）：DirectAPIRuntime，支持逐请求 API Key
    * `dsh`：HarnessRuntime，Key 绑在子进程上，不支持逐请求换 Key

    direct_api 采用**延迟导入**：它需要从本模块拿 AgentRun，
    放在模块顶部会形成循环导入。
    """
    if get_settings().backend == "dsh":
        return get_harness_runtime()

    global _direct_runtime
    if _direct_runtime is None:
        with _runtime_lock:
            if _direct_runtime is None:
                from app.agents.direct_api import DirectAPIRuntime

                _direct_runtime = DirectAPIRuntime()
    return _direct_runtime


def close_runtime() -> None:
    """关闭所有已创建的后端（供 FastAPI lifespan 调用）。"""
    global _harness_runtime, _direct_runtime
    with _runtime_lock:
        for rt in (_harness_runtime, _direct_runtime):
            if rt is not None:
                rt.close()
        _harness_runtime = None
        _direct_runtime = None
