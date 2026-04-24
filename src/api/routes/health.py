"""GET /api/health"""

from __future__ import annotations

import time

from fastapi import APIRouter, Request

from ..models import HealthResponse


router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def get_health(request: Request) -> HealthResponse:
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
