"""集中读取环境变量。所有可调参数只在这里出现一次。"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# 路径基准：core/ 与其上一级
CORE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = CORE_DIR.parent

# 加载配置。加载顺序（后者覆盖前者）：
#   1. .env                —— 应用配置（模型、端口、超时）
#   2. credentials.env     —— DSH_HOME 与自定义接口地址（单独文件，见下方说明）
#
# ⚠️ 本文件**不读取**任何 API Key。
#   Key 只有一个来源：调用方显式传入 —— 网页来自 Authorization 头，
#   终端与脚本来自环境变量 DEEPSEEK_API_KEY。项目内不保存、不落盘。
#   （曾有过一个「服务端兜底 Key」，已按需求移除，见 docs/maintenance.md）
#
# 为什么 DSH_HOME 要单独一个文件：
#   dsh 启动时会扫描 workspace 根目录的 .env，一旦发现 DSH_* 变量就拒绝启动
#   （它们属于启动环境专属变量）。所以这类值不能出现在 .env 里，
#   只能放在它不扫描的文件中，再由 app/agents/runtime.py 注入子进程环境。
#
# override=True：本项目在 DSH 环境里开发时 DSH 自己会设 DSH_HOME，
#   必须让项目配置覆盖它，否则 SDK 会往主 DSH home 写 profile。
load_dotenv(PROJECT_ROOT / ".env", override=True)
load_dotenv(CORE_DIR / ".env", override=True)
load_dotenv(PROJECT_ROOT / "credentials.env", override=True)
load_dotenv(CORE_DIR / "credentials.env", override=True)


class Settings:
    """运行期配置快照。"""

    def __init__(self) -> None:
        # --- 接口地址（可选，不是凭据）---
        # 走兼容代理端点时才需要设置；默认官方地址。
        # 注意：API Key 不在这里读取 —— 它由调用方逐请求传入，见模块顶部说明。
        self.deepseek_base_url: str | None = os.getenv("DEEPSEEK_BASE_URL")

        # --- DSH 运行时 ---
        # DSH_HOME 通常来自 credentials.env；缺省时用项目内隔离目录。
        # 绝不能让主 DSH 环境的 DSH_HOME 生效，否则 SDK 会往主环境写 profile。
        self.dsh_home: str = os.getenv("DSH_HOME") or str(PROJECT_ROOT / "dsh-home")

        # --- 模型 ---
        # 注意：这里刻意使用 TA_ 前缀。dsh 会拒绝 .env 里任何 DSH_* 变量，
        # 所以项目自己的模型配置不能叫 DSH_MODEL 之类。
        self.provider: str = os.getenv("TA_PROVIDER", "deepseek-official")
        self.model: str = os.getenv("TA_MODEL", "deepseek-v4-flash")
        # 本模型支持 max / high / low / off；medium、none、minimal 会导致启动失败。
        # 默认 low：实测与 max 推荐质量同级，但延迟约 1/2.3。
        self.reasoning_effort: str | None = os.getenv("TA_REASONING_EFFORT") or "low"
        self.max_tokens: int = int(os.getenv("TA_MAX_TOKENS", "8192"))

        # --- Agent 运行时后端 ---
        #   direct（默认）：直连 DeepSeek 官方 API。API Key 逐请求传入，
        #                   因此支持"用户自带 Key"，不落盘、不写运行时目录。
        #   dsh：走 DeepSeekHarness 子进程。其 Key 与 harness 实例绑定
        #        （一个进程一个 Key），**不支持逐请求换 Key**，保留用于调试。
        self.backend: str = (os.getenv("TA_BACKEND") or "direct").strip().lower()

        # --- 服务 ---
        self.host: str = os.getenv("APP_HOST", "127.0.0.1")
        self.port: int = int(os.getenv("APP_PORT", "8000"))
        self.log_level: str = os.getenv("LOG_LEVEL", "INFO")

        # --- 超时 ---
        self.agent1_timeout_s: float = float(os.getenv("AGENT1_TIMEOUT_S", "45"))
        self.agent2_timeout_s: float = float(os.getenv("AGENT2_TIMEOUT_S", "60"))

        # --- 路径 ---
        self.data_dir: Path = CORE_DIR / "data"
        self.prompts_dir: Path = CORE_DIR / "app" / "agents" / "prompts"
        # 前端交互层：所有"壳"都放在仓库根的 ui/ 下，与核心逻辑分层隔离。
        # 这里只登记 Web 壳的静态目录，终端壳不需要路径配置。
        self.web_dir: Path = PROJECT_ROOT / "ui" / "web"

    @property
    def user_key_supported(self) -> bool:
        """是否支持逐请求（用户自带）API Key。

        只有 direct 后端支持：dsh 的 Key 绑在子进程上，无法按请求切换。
        """
        return self.backend != "dsh"

    @property
    def resolved_base_url(self) -> str:
        """官方 API 基地址（direct 后端用）。"""
        return (self.deepseek_base_url or "https://api.deepseek.com").rstrip("/")

    def missing_credentials_hint(self) -> str:
        """没有拿到 API Key 时的可操作提示。

        本项目**不使用服务端内置 Key**（曾有的"兜底 Key"已移除），
        所以 Key 必须由调用方提供。这段文案要同时说清"去哪儿给"和"不会落盘"。
        """
        return (
            "这次请求没有附带 API Key。本项目不使用服务端内置 Key，需要你自己提供：\n"
            "  · 网页版：在页面上的「API Key」一栏填入，再点「给我建议」\n"
            "  · 终端 / 脚本：先设环境变量再运行，例如\n"
            '        $env:DEEPSEEK_API_KEY = "sk-..."\n'
            "  Key 只在本次请求里随 Authorization 头传给本机后端，"
            "不写入日志、不落盘、不入库。\n"
            "  申请地址：https://platform.deepseek.com/api_keys"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def api_key_from_env() -> str:
    """从**进程环境变量**取调用方自己的 API Key（供终端壳与脚本使用）。

    刻意只读环境变量、不读任何文件：本项目不使用服务端内置 Key，
    项目里也不保存 Key（曾有的「服务端兜底 Key」已按需求移除）。

    网页版不走这里 —— 它从 `Authorization` 头逐请求取。
    这里读到的 Key 由调用方显式传给 `parse_diet(..., api_key=...)` /
    `analyze(..., api_key=...)`，不进入任何配置对象。
    """
    return (os.getenv("DEEPSEEK_API_KEY") or "").strip()
