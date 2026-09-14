"""Agent 运行时：管理 DeepSeekHarness 子进程的生命周期。

设计要点
--------
1. 进程复用：DeepSeekHarness 启动一次 dsh 子进程，多次 run() 复用，避免每次请求都拉起进程。
2. 凭据隔离：DSH_HOME 指向独立目录（默认 D:\\work\\dsh-home），与你的主 DSH 环境分开，
   避免污染主环境的 profile / settings / sessions。
3. 会话隔离：每个 agent 用独立 session_id 前缀，避免对话历史互相污染。
4. 不设工具：本项目的两个 Agent 都是纯 文本→JSON 任务，不需要读写文件或执行命令。
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

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


class HarnessRuntime:
    """全局单例，进程内复用同一个 DSH 子进程。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._harness = None
        self._settings = get_settings()

    # ------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------
    def ensure_started(self) -> None:
        """按需启动运行时。重复调用不会重复启动。"""
        with self._lock:
            if self._harness is not None:
                return

            if DeepSeekHarness is None:
                raise RuntimeError(
                    "未安装 deepseek-harness-sdk。请执行：pip install deepseek-harness-sdk"
                )
            if not self._settings.has_credentials:
                raise RuntimeError(self._settings.missing_credentials_hint())

            dsh_home = Path(self._settings.dsh_home)
            dsh_home.mkdir(parents=True, exist_ok=True)

            # workspace 用项目根目录；本项目的 agent 不需要读写文件，仅作占位
            workspace = self._settings.data_dir.parent.parent
            workspace.mkdir(parents=True, exist_ok=True)

            kwargs = {
                "dsh_home": str(dsh_home),
                "cwd": str(workspace),
                "provider": self._settings.provider,
                "model": self._settings.model,
                "max_tokens": self._settings.max_tokens,
            }
            if self._settings.reasoning_effort:
                kwargs["reasoning_effort"] = self._settings.reasoning_effort
            # 只有显式配置了才覆盖子进程环境，避免把 None 传进去
            if self._settings.deepseek_api_key:
                kwargs["api_key"] = self._settings.deepseek_api_key
            if self._settings.deepseek_base_url:
                kwargs["base_url"] = self._settings.deepseek_base_url

            logger.info("正在启动 DSH 运行时: model=%s home=%s", self._settings.model, dsh_home)
            self._harness = DeepSeekHarness(**kwargs)
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
    ) -> AgentRun:
        """跑一轮 agent，返回最终助手文本。

        注意：DSH 的 persona 取环境变量 DSH_SYSTEM_PROMPT。若要按 agent 切换
        系统提示词，需要用 patch 文件为每个 profile 单独配置（见 README 的"待验证事项"）。
        因此当前实现把 system_prompt 作为 user 消息的前缀注入，稳妥且无副作用。
        """
        self.ensure_started()
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


_runtime: HarnessRuntime | None = None
_runtime_lock = threading.Lock()


def get_runtime() -> HarnessRuntime:
    """获取全局运行时单例。"""
    global _runtime
    if _runtime is None:
        with _runtime_lock:
            if _runtime is None:
                _runtime = HarnessRuntime()
    return _runtime
