"""POST /api/pipeline/trigger — 手动触发一次 Pipeline。"""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request

from ...pipeline import StrategyStateBuilder
from ..models import TriggerResponse


router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.post("/trigger", response_model=TriggerResponse)
def trigger_pipeline(request: Request) -> TriggerResponse:
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
