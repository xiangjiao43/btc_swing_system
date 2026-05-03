"""GET /api/health"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Request

from ..models import HealthResponse


logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


def _check_review_pending(conn: Any) -> dict[str, Any] | None:
    """Sprint 1.10-I D2=a:查 review_pending active 状态(无 active 时返 None)。"""
    try:
        from src.strategy.review_pending import is_in_review_pending
        rp = is_in_review_pending(conn)
        if not rp.get("in_review_pending"):
            return None
        return {
            "active": True,
            "state_id": rp.get("state_id"),
            "reason": rp.get("reason"),
            "entered_at_utc": rp.get("entered_at_utc"),
            "related_thesis_id": rp.get("related_thesis_id"),
        }
    except Exception as e:
        logger.warning("health: review_pending check failed: %s", e)
        return None


@router.get("/health", response_model=HealthResponse)
def get_health(request: Request) -> HealthResponse:
    ctx = request.app.state.ctx
    db_ok = False
    rp_dict: dict[str, Any] | None = None
    try:
        conn = ctx.conn_factory()
        try:
            conn.execute("SELECT 1").fetchone()
            db_ok = True
            # Sprint 1.10-I D2=a:同一连接复用,查 review_pending 状态
            rp_dict = _check_review_pending(conn)
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
        review_pending=rp_dict,
    )
