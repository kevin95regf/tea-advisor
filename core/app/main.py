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
from app.config import get_settings
from app.domain.models import CatalogHerb, Disclaimer, HealthResponse
from app.domain.safety import load_herb_catalog

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时校验数据与凭据，关闭时释放 DSH 子进程。"""
    herbs = load_herb_catalog()
    logger.info("已加载 %d 味饮片", len(herbs))
    if not settings.has_credentials:
        logger.warning("未检测到 DEEPSEEK_API_KEY，接口会在调用模型时报错")
    logger.warning(
        "本服务输出仅供饮食养生参考，不构成医疗建议。上线前请由专业人员复核 herbs.json"
    )
    yield
    # 关闭 DSH 子进程
    try:
        from app.agents.runtime import _runtime

        if _runtime is not None:
            _runtime.close()
    except Exception:  # pragma: no cover
        pass


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
        credentials_ok=settings.has_credentials,
        herbs_loaded=len(catalog),
        data_files_ok=data_files_ok,
        dsh_home=str(dsh_home),
        dsh_home_exists=dsh_home.exists(),
        model=settings.model,
        disclaimer_version=Disclaimer().version,
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
    path = settings.data_dir / "constitution.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        {"id": item["id"], "label": item["label"], "one_line": item["one_line"]}
        for item in data.get("constitutions", [])
    ]


@app.get("/", include_in_schema=False)
@app.get("/demo", include_in_schema=False)
async def web_ui() -> FileResponse:
    """本地 Web 界面（仓库根 ui/web/index.html）。

    `/` 与 `/demo` 指向同一个页面；`/demo` 作为历史路径保留，避免旧书签失效。
    """
    return FileResponse(settings.web_dir / "index.html")
