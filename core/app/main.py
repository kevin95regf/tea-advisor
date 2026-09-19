"""FastAPI 入口（Web 适配层）。

本服务是同源提供界面与接口的：前端页面由本服务自己返回，
所以浏览器同源请求本来不需要 CORS。

启动（在 core 目录下）：
    python -m uvicorn app.main:app --reload --port 8000

然后打开：
    http://127.0.0.1:8000          本地 Web 界面（ui/web/index.html）
    http://127.0.0.1:8000/docs     接口文档
    http://127.0.0.1:8000/healthz  自检

若只想用终端界面，不需要启动本服务：
    python ui/terminal/chat.py
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api import analyze as analyze_api
from app.api import analyze_offline as analyze_offline_api
from app.api import chat as chat_api
from app.api import medication as medication_api
from app.api import questionnaire as questionnaire_api
from app.config import get_settings
from app.domain.enums import (
    FLAVOR_LABELS,
    MEAL_TIME_LABELS,
    NATURE_LABELS,
    SOURCE_LABELS,
)
from app.domain.models import CatalogHerb, Disclaimer, HealthResponse
from app.domain.safety import load_herb_catalog, ready_constitutions
from app.services.food_lookup import CONF_SHOW_THRESHOLD, COOKING_LABELS, table_stats

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时校验数据，关闭时释放运行时。"""
    herbs = load_herb_catalog()
    logger.info("已加载 %d 味饮片", len(herbs))
    logger.info(
        "Agent 后端：%s（逐请求 API Key %s）",
        settings.backend,
        "支持" if settings.user_key_supported else "不支持",
    )
    logger.info(
        "本项目不使用服务端内置 API Key：Key 由调用方提供"
        "（网页读 Authorization 头，终端与脚本读环境变量 DEEPSEEK_API_KEY）。"
    )
    logger.warning(
        "本服务输出仅供饮食养生参考，不构成医疗建议。上线前请由专业人员复核 herbs.json"
    )
    yield
    # 关闭运行时（direct 后端关 HTTP 连接池；dsh 后端关子进程）
    try:
        from app.agents.runtime import close_runtime

        close_runtime()
    # 只吞掉预期的资源释放错误；编程错误应暴露，避免关闭阶段静默掩盖缺陷。
    except (OSError, RuntimeError):  # pragma: no cover
        logger.warning("关闭主 Agent 运行时时出错", exc_info=True)
    try:
        from app.agents.multi_provider import close_multi_provider_runtime

        close_multi_provider_runtime()
    # 与主运行时保持同一策略，不恢复成会隐藏所有缺陷的 ``except Exception``。
    except (OSError, RuntimeError):  # pragma: no cover
        logger.warning("关闭多模型运行时时出错", exc_info=True)


app = FastAPI(
    title="中医饮食茶饮推荐 API",
    description="根据饮食口述与中医体质，推荐药食同源饮片茶饮。仅供饮食参考，不构成医疗建议。",
    version="0.1.0",
    lifespan=lifespan,
)

# 界面与接口由本服务同源提供，浏览器同源请求本不需要 CORS。
# 这里只放行本机来源，便于你另起一个前端开发服务器时调试。
# ⚠️ 不要改回 ["*"]：那会让局域网内任意网页都能调用你本机的接口。
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"http://127.0.0.1:{settings.port}",
        f"http://localhost:{settings.port}",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(analyze_api.router, prefix="/api", tags=["analyze"])
app.include_router(analyze_offline_api.router, prefix="/api", tags=["analyze"])
app.include_router(questionnaire_api.router, prefix="/api", tags=["questionnaire"])
app.include_router(chat_api.router, prefix="/api", tags=["chat"])
app.include_router(medication_api.router, prefix="/api", tags=["reference"])


# ============================================================
# 辅助接口
# ============================================================
@app.get("/healthz", response_model=HealthResponse, summary="自检")
async def healthz() -> HealthResponse:
    catalog = load_herb_catalog()
    dsh_home = Path(settings.dsh_home)
    data_files_ok = (settings.data_dir / "herbs.json").exists() and (
        settings.data_dir / "constitution.json"
    ).exists()
    return HealthResponse(
        status="ok",
        herbs_loaded=len(catalog),
        data_files_ok=data_files_ok,
        dsh_home=str(dsh_home),
        dsh_home_exists=dsh_home.exists(),
        model=settings.model,
        disclaimer_version=Disclaimer().version,
        backend=settings.backend,
        user_key_supported=settings.user_key_supported,
    )


@app.get("/api/catalog/herbs", response_model=list[CatalogHerb], summary="饮片目录")
async def catalog_herbs() -> list[CatalogHerb]:
    return [CatalogHerb(**item) for item in load_herb_catalog().values()]


@app.get("/api/disclaimer", response_model=Disclaimer, summary="免责声明")
async def disclaimer() -> Disclaimer:
    """前端应优先调用本接口取文案，避免各处硬编码导致版本不一致。"""
    return Disclaimer()


@app.get("/api/constitutions", summary="体质选项")
async def constitutions() -> list[dict]:
    """返回**可对外服务**的体质。

    收录进 constitution.json ≠ 可以对用户开放：枚举加了新体质但 herbs.json 的
    配伍标注还没备齐时，选中它会让 `filter_by_constitution` 抛
    `MissingConstitutionDataError`（500）。所以这里按 `ready_constitutions()`
    过滤——判据是「herbs.json 里至少有 1 味把它标进 suitable_constitutions」，
    与运行时闸门（orchestrator._constitution_of）用的是同一个条件。

    返回字段不变；前端与终端都读这个接口，因此数据一备齐就会自动出现。
    """
    path = settings.data_dir / "constitution.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    ready = ready_constitutions()
    return [
        {"id": item["id"], "label": item["label"], "one_line": item["one_line"]}
        for item in data.get("constitutions", [])
        if item["id"] in ready
    ]


@app.get("/api/meta", summary="展示用标签与显示约定")
async def meta() -> dict:
    """前端展示所需的全部中文标签与阈值约定，**各壳不要再各自硬编码**。

    为什么要单独一个接口：中文标签原本散在后端枚举、终端壳、网页壳三处，
    一改就容易漂移。界面显示规则（要不要显示寒热属性、要不要标「待验证」）
    依赖 `conf_show_threshold` 与 `source` 标签，两边必须完全一致，
    所以统一由这里下发。

    注意：这是**展示元数据**，不参与任何判定逻辑。
    """
    stats = table_stats()
    return {
        "nature": NATURE_LABELS,
        "flavor": FLAVOR_LABELS,
        "meal_time": MEAL_TIME_LABELS,
        "cooking": COOKING_LABELS,
        "source": SOURCE_LABELS,
        # 低于该置信度时界面不显示寒热属性（数据仍会返回）
        "conf_show_threshold": CONF_SHOW_THRESHOLD,
        "food_table_size": stats["total"],
        "disclaimer_version": Disclaimer().version,
    }


@app.get("/", include_in_schema=False)
@app.get("/demo", include_in_schema=False)
async def web_ui() -> FileResponse:
    """本地 Web 界面（仓库根 ui/web/index.html）。

    `/` 与 `/demo` 指向同一个页面；`/demo` 作为历史路径保留，避免旧书签失效。
    """
    return FileResponse(settings.web_dir / "index.html")
