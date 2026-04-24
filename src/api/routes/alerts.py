"""GET /api/alerts — 活跃告警列表(Sprint 1.16c)。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from ...monitoring import check_alerts


router = APIRouter(tags=["alerts"])


@router.get("/alerts")
def list_alerts(
    request: Request,
    lookback_hours: int = Query(24, ge=1, le=168),
) -> dict[str, Any]:
    ctx = request.app.state.ctx
    conn = ctx.conn_factory()
    try:
        alerts = check_alerts(conn, lookback_hours=lookback_hours)
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return {
        "lookback_hours": lookback_hours,
        "count": len(alerts),
        "alerts": alerts,
    }
