"""集中读取环境变量。所有可调参数只在这里出现一次。"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# 路径基准：backend/ 与其上一级
BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent

# 加载配置。加载顺序（后者覆盖前者）：
#   1. .env                —— 应用配置（模型、端口、超时）
#   2. credentials.env     —— 凭据与 DSH_HOME（单独文件，见下方说明）
#
# 为什么凭据要单独一个文件：
#   dsh 启动时会扫描 workspace 根目录的 .env，一旦发现 DSH_HOME /
#   DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL 就拒绝启动（它们属于启动环境专属变量）。
#   所以这些值不能出现在 .env 里，只能放在它不扫描的文件中，再由
#   app/agents/runtime.py 注入子进程环境。
#
# override=True：本项目在 DSH 环境里开发时 DSH 自己会设 DSH_HOME，
#   必须让项目配置覆盖它，否则 SDK 会往主 DSH home 写 profile。
load_dotenv(PROJECT_ROOT / ".env", override=True)
load_dotenv(BACKEND_DIR / ".env", override=True)
load_dotenv(PROJECT_ROOT / "credentials.env", override=True)
load_dotenv(BACKEND_DIR / "credentials.env", override=True)


class Settings:
    """运行期配置快照。"""

    def __init__(self) -> None:
        # --- 凭据 ---
        self.deepseek_api_key: str | None = os.getenv("DEEPSEEK_API_KEY")
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

        # --- 服务 ---
        self.host: str = os.getenv("APP_HOST", "127.0.0.1")
        self.port: int = int(os.getenv("APP_PORT", "8000"))
        self.log_level: str = os.getenv("LOG_LEVEL", "INFO")

        # --- 超时 ---
        self.agent1_timeout_s: float = float(os.getenv("AGENT1_TIMEOUT_S", "45"))
        self.agent2_timeout_s: float = float(os.getenv("AGENT2_TIMEOUT_S", "60"))

        # --- 路径 ---
        self.data_dir: Path = BACKEND_DIR / "data"
        self.static_dir: Path = BACKEND_DIR / "static"
        self.prompts_dir: Path = BACKEND_DIR / "app" / "agents" / "prompts"

    @property
    def has_credentials(self) -> bool:
        """是否具备调用模型的最低条件。"""
        return bool(self.deepseek_api_key)

    def missing_credentials_hint(self) -> str:
        return (
            "缺少 DEEPSEEK_API_KEY。请执行：\n"
            "  1) 复制 .env.example 为 .env\n"
            "  2) 在 .env 中填入 DEEPSEEK_API_KEY=sk-...\n"
            "  3) 重新运行本命令"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
