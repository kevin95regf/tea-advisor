"""集中读取环境变量。所有可调参数只在这里出现一次。"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# 路径基准：backend/ 与其上一级
BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent

# 加载 .env（存在才加载，不报错）
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(BACKEND_DIR / ".env")


class Settings:
    """运行期配置快照。"""

    def __init__(self) -> None:
        # --- 凭据 ---
        self.deepseek_api_key: str | None = os.getenv("DEEPSEEK_API_KEY")
        self.deepseek_base_url: str | None = os.getenv("DEEPSEEK_BASE_URL")

        # --- DSH 运行时 ---
        # 默认使用项目内独立 home，避免污染你主 DSH 环境的 profile/settings/sessions。
        # 需要覆盖时在 .env 里显式设置 DSH_HOME（必须是纯英文绝对路径）。
        self.dsh_home: str = os.getenv("DSH_HOME") or str(PROJECT_ROOT / "dsh-home")
        self.provider: str = os.getenv("DSH_PROVIDER", "deepseek-official")
        self.model: str = os.getenv("DSH_MODEL", "deepseek-v4-flash")
        self.reasoning_effort: str | None = os.getenv("DSH_REASONING_EFFORT") or None
        self.max_tokens: int = int(os.getenv("DSH_MAX_TOKENS", "8192"))

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
