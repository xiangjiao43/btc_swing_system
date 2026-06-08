"""
api/app.py — FastAPI app factory (Sprint 1.15a / 2.4)

独立 app 工厂:`create_app()` 用于测试(可注入 conn_factory),
模块级 `app` 供 uvicorn 启动时使用。

依赖注入:
  * get_db() 默认用 src.data.storage.connection.get_connection,
    测试时 override 即可指向 in-memory DB。

Sprint 2.4 新增:
  * startup 事件启动 APScheduler(BackgroundScheduler,读 config/scheduler.yaml)
  * shutdown 事件优雅停止;SCHEDULER_ENABLED=false 可关
  * 启动 log 打印 next_run_time(pipeline_run)
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .routes import alerts as alerts_routes
from .routes import data as data_routes
from .routes import data_sources as data_sources_routes
from .routes import evidence as evidence_routes
from .routes import export as export_routes
from .routes import fallback as fallback_routes
from .routes import health as health_routes
from .routes import lifecycle as lifecycle_routes
from .routes import market as market_routes
from .routes import pipeline as pipeline_routes
from .routes import review as review_routes
from .routes import strategy as strategy_routes
from .routes import system as system_routes
# Sprint 1.10-I 新增 5 个路由(account / theses / orders / review_weekly / review_pending)
from .routes import account as account_routes
from .routes import theses as theses_routes
from .routes import orders as orders_routes
from .routes import review_weekly as review_weekly_routes
from .routes import review_pending as review_pending_routes
from .state import AppState


logger = logging.getLogger(__name__)

VERSION: str = "2.4.0"

_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent
_WEB_DIR: Path = _PROJECT_ROOT / "web"


def _scheduler_enabled_from_env() -> bool:
    """默认开启;SCHEDULER_ENABLED=false / 0 / no / off 可关。"""
    raw = os.environ.get("SCHEDULER_ENABLED", "true").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _log_scheduler_jobs(scheduler: Any) -> None:
    """Sprint 2.8-D:逐 job log next_run_time(BJT)。

    单 job AttributeError 不传播 — APScheduler BackgroundScheduler.start() 与
    内部 dispatcher 线程之间存在 race;`scheduler.start()` 返回后立即读
    `job.next_run_time` 偶尔抛 AttributeError(scheduler 已起来,但 job 还未
    被 schedule 出 next_fire_time)。

    本函数应该在 `app.state.scheduler` 已写入之后才被调用,任何这里抛出的
    异常都不会让 scheduler 实例被丢掉。
    """
    from datetime import timedelta, timezone

    bjt_tz = timezone(timedelta(hours=8))
    for job in scheduler.get_jobs():
        try:
            nxt = job.next_run_time
        except AttributeError:
            logger.info(
                "[Scheduler] job=%s registered (next_run_time pending)",
                job.id,
            )
            continue
        if nxt is not None:
            try:
                bjt = nxt.astimezone(bjt_tz)
                logger.info(
                    "[Scheduler] job=%s next run at %s BJT",
                    job.id, bjt.strftime("%Y-%m-%d %H:%M"),
                )
            except Exception as e:
                logger.warning(
                    "[Scheduler] job=%s next_run_time fmt failed: %s",
                    job.id, e,
                )
        else:
            logger.info(
                "[Scheduler] job=%s registered (no next_run_time)", job.id,
            )


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
    # Sprint B(数据真实性透明化):/api/data_sources/freshness 读 fetch_attempts
    app.include_router(data_sources_routes.router, prefix="/api")
    app.include_router(alerts_routes.router, prefix="/api")
    # Sprint 1.10-I 5 个新路由(v1.4 §9.5 #8-#18)
    app.include_router(account_routes.router, prefix="/api")
    app.include_router(theses_routes.router, prefix="/api")
    app.include_router(orders_routes.router, prefix="/api")
    app.include_router(review_weekly_routes.router, prefix="/api")
    app.include_router(review_pending_routes.router, prefix="/api")
    # 数据导出端点(供外部 AI 分析使用,markdown 文本)
    app.include_router(export_routes.router, prefix="/api")

    # Sprint 2.6-D.1:events_calendar 在 FastAPI startup 时 seed
    # (systemd 跑的是 uvicorn → src.api.app:app,不会走 scheduler/main.run_forever)
    @app.on_event("startup")
    def _seed_events_on_startup_api() -> None:
        try:
            from ..data.collectors.events_seeder import seed_events
            from ..data.storage.connection import get_connection
            conn = get_connection()
            try:
                stats = seed_events(conn)
                logger.info("[Events] seeded on FastAPI startup: %s", stats)
            finally:
                conn.close()
        except Exception as e:
            logger.warning(
                "[Events] seed on startup failed (non-fatal): %s", e,
            )

    # Sprint 2.4 / 2.8-D:APScheduler 嵌入 lifecycle
    # 只在 SCHEDULER_ENABLED(默认 true)时启动;shutdown 时优雅停止。
    #
    # 2.8-D:启动序列分两阶段,避免 race condition 把 scheduler 引用丢掉:
    #   阶段 1 build_scheduler + scheduler.start():失败 → 清空 app.state.scheduler
    #   阶段 2 log next_run_time:延迟 2s 异步执行,即便抛错也不影响 scheduler 引用
    # 之前症状:scheduler.start() 后立即读 job.next_run_time,APScheduler 内部
    # 还没完成 schedule,抛 AttributeError → except 把 scheduler 清成 None →
    # APScheduler 后台线程没有引用 → 4 天 0 触发。
    @app.on_event("startup")
    def _start_scheduler() -> None:
        if not _scheduler_enabled_from_env():
            logger.info("[Scheduler] disabled via SCHEDULER_ENABLED env var")
            app.state.scheduler = None
            return

        # 阶段 1:build + start。失败才清状态
        try:
            from ..scheduler import build_scheduler
            scheduler = build_scheduler(blocking=False)
            scheduler.start()
        except Exception as e:
            logger.exception("[Scheduler] startup failed: %s", e)
            app.state.scheduler = None
            return

        # **关键**:scheduler 已起来,先把引用存进 app.state,
        # 任何后续异常都不应该再清掉它(APScheduler 后台线程要靠这个引用活着)
        app.state.scheduler = scheduler
        logger.info(
            "[Scheduler] started; %d jobs registered",
            len(scheduler.get_jobs()),
        )

        # 阶段 2:延迟 log next_run_time(BJT)
        # 直接 inline 调用 _log_scheduler_jobs 在某些 APScheduler race 场景会
        # 抛 AttributeError;放到 threading.Timer 里 2s 后跑,
        # 让 BackgroundScheduler dispatcher 线程把 next_fire_time 算出来
        import threading
        threading.Timer(2.0, _log_scheduler_jobs, args=(scheduler,)).start()

    @app.on_event("shutdown")
    def _stop_scheduler() -> None:
        sched = getattr(app.state, "scheduler", None)
        if sched is None:
            return
        try:
            sched.shutdown(wait=False)
            logger.info("[Scheduler] stopped")
        except Exception as e:
            logger.warning("[Scheduler] shutdown error: %s", e)

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
