"""建模 §9.10 #9-#10:系统级路由。

  GET /api/system/health    — 系统健康(替代 /api/health;保留老路径 alias)
  POST /api/system/run-now  — 手动触发一次 Pipeline(替代 /api/pipeline/trigger)
"""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request

from ...pipeline import StrategyStateBuilder
from ..models import HealthResponse, TriggerResponse


router = APIRouter(prefix="/system", tags=["system"])


# ---------- GET /api/system/health ----------

def _health_impl(request: Request) -> HealthResponse:
    ctx = request.app.state.ctx
    db_ok = False
    try:
        conn = ctx.conn_factory()
        try:
            conn.execute("SELECT 1").fetchone()
            db_ok = True
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception:
        db_ok = False
    return HealthResponse(
        status="ok" if db_ok else "degraded",
        version=ctx.version,
        uptime_seconds=round(time.time() - ctx.started_at, 3),
        db_accessible=db_ok,
    )


@router.get("/health", response_model=HealthResponse)
def get_system_health(request: Request) -> HealthResponse:
    """§9.10 #9:系统健康。"""
    return _health_impl(request)


# ---------- POST /api/system/run-now ----------

def _run_now_impl(request: Request) -> TriggerResponse:
    ctx = request.app.state.ctx
    now_ts = time.time()

    with ctx.trigger_lock:
        if ctx.within_cooldown(now_ts):
            remaining = int(
                ctx.pipeline_trigger_cooldown_sec
                - (now_ts - (ctx.last_trigger_ts or now_ts))
            )
            raise HTTPException(
                status_code=429,
                detail=(
                    "pipeline trigger rate-limited; "
                    f"retry in ~{max(1, remaining)}s"
                ),
            )
        ctx.register_trigger(now_ts)

    conn = ctx.conn_factory()
    try:
        builder = StrategyStateBuilder(conn)
        result = builder.run(run_trigger="manual_api")
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return TriggerResponse(
        status="success" if result.persisted else "failed",
        run_id=result.run_id,
        run_timestamp_utc=result.run_timestamp_utc,
        persisted=result.persisted,
        ai_status=result.ai_status,
        duration_ms=result.duration_ms,
        degraded_stages=result.degraded_stages,
        failure_count=len(result.failures),
    )


@router.post("/run-now", response_model=TriggerResponse)
def trigger_run_now(request: Request) -> TriggerResponse:
    """§9.10 #10:手动触发一次 Pipeline(调试 / 排查)。"""
    return _run_now_impl(request)
