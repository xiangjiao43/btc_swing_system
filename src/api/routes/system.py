"""建模 §9.10 #9-#10:系统级路由。

  GET /api/system/health    — 系统健康(替代 /api/health;保留老路径 alias)
  POST /api/system/run-now  — 手动触发一次 Pipeline(替代 /api/pipeline/trigger)
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request

from ...pipeline import StrategyStateBuilder
from ..models import HealthResponse, TriggerResponse


router = APIRouter(prefix="/system", tags=["system"])


# ---------- GET /api/system/health ----------

def _count_preflight_alerts_24h(conn) -> int:
    """Sprint 2.8-B:最近 24h pre_flight_degraded alerts 数量。"""
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM alerts "
        "WHERE alert_type = 'pre_flight_degraded' AND raised_at_utc >= ?",
        (since,),
    ).fetchone()
    if row is None:
        return 0
    try:
        return int(row["n"])
    except (TypeError, KeyError, IndexError):
        return int(row[0]) if row else 0


def _scheduler_status(request: Request) -> tuple[bool, int]:
    """Sprint 2.8-D:返回 (running, jobs_count)。

    任何错误 → (False, 0)。
    """
    sched = getattr(request.app.state, "scheduler", None)
    if sched is None:
        return False, 0
    try:
        running = bool(getattr(sched, "running", False))
    except Exception:
        running = False
    if not running:
        return False, 0
    try:
        jobs_count = len(sched.get_jobs())
    except Exception:
        jobs_count = 0
    return True, jobs_count


def _health_impl(request: Request) -> HealthResponse:
    ctx = request.app.state.ctx
    db_ok = False
    preflight_24h = 0
    try:
        conn = ctx.conn_factory()
        try:
            conn.execute("SELECT 1").fetchone()
            db_ok = True
            try:
                preflight_24h = _count_preflight_alerts_24h(conn)
            except Exception:
                preflight_24h = 0
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception:
        db_ok = False

    sched_running, sched_jobs = _scheduler_status(request)

    return HealthResponse(
        status="ok" if db_ok else "degraded",
        version=ctx.version,
        uptime_seconds=round(time.time() - ctx.started_at, 3),
        db_accessible=db_ok,
        preflight_alerts_24h=preflight_24h,
        scheduler_running=sched_running,
        scheduler_jobs_count=sched_jobs,
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
