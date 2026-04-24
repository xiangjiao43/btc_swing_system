"""
api/app.py — FastAPI app factory (Sprint 1.15a)

独立 app 工厂:`create_app()` 用于测试(可注入 conn_factory),
模块级 `app` 供 uvicorn 启动时使用。

依赖注入:
  * get_db() 默认用 src.data.storage.connection.get_connection,
    测试时 override 即可指向 in-memory DB。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .routes import alerts as alerts_routes
from .routes import data as data_routes
from .routes import evidence as evidence_routes
from .routes import fallback as fallback_routes
from .routes import health as health_routes
from .routes import lifecycle as lifecycle_routes
from .routes import market as market_routes
from .routes import pipeline as pipeline_routes
from .routes import review as review_routes
from .routes import strategy as strategy_routes
from .routes import system as system_routes
from .state import AppState


logger = logging.getLogger(__name__)

VERSION: str = "1.15.0"

_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent
_WEB_DIR: Path = _PROJECT_ROOT / "web"


def create_app(
    *,
    conn_factory: Optional[Callable[[], Any]] = None,
    pipeline_trigger_cooldown_sec: float = 60.0,
) -> FastAPI:
    """
    Args:
        conn_factory: 无参 callable,每次调用返回一个新的 sqlite3.Connection。
                      None = 使用项目默认 get_connection()。
        pipeline_trigger_cooldown_sec: POST /api/pipeline/trigger 的节流窗口。
    """
    if conn_factory is None:
        from src.data.storage.connection import get_connection as _default
        conn_factory = _default

    state = AppState(
        conn_factory=conn_factory,
        pipeline_trigger_cooldown_sec=pipeline_trigger_cooldown_sec,
        started_at=time.time(),
        version=VERSION,
    )

    app = FastAPI(
        title="BTC Swing System API",
        description="FastAPI routes for the BTC medium-to-long-term swing system.",
        version=VERSION,
    )
    app.state.ctx = state

    # Sprint 1.5c §9.10 对齐:system / strategy / evidence / lifecycle / review
    app.include_router(system_routes.router, prefix="/api")
    app.include_router(strategy_routes.router, prefix="/api")
    app.include_router(evidence_routes.router, prefix="/api")
    app.include_router(lifecycle_routes.router, prefix="/api")
    app.include_router(review_routes.router, prefix="/api")
    # Sprint 2.3 tuning:轻量行情路由,供前端每分钟刷顶栏价格
    app.include_router(market_routes.router, prefix="/api")
    # 老路径 alias(向后兼容旧测试 / 旧前端)
    app.include_router(health_routes.router, prefix="/api")
    app.include_router(pipeline_routes.router, prefix="/api")
    app.include_router(fallback_routes.router, prefix="/api")
    app.include_router(data_routes.router, prefix="/api")
    app.include_router(alerts_routes.router, prefix="/api")

    # Sprint 2.1 §9 前端:web/ 目录作为 StaticFiles 挂在根路径 /
    # 必须放在所有 /api/* 路由之后(StaticFiles 会接管 404 fallback)。
    if _WEB_DIR.exists():
        app.mount(
            "/",
            StaticFiles(directory=str(_WEB_DIR), html=True),
            name="web",
        )
    else:
        logger.warning("web/ directory not found at %s; frontend not mounted",
                       _WEB_DIR)

    return app


# 模块级 app,供 uvicorn 启动
app = create_app()
