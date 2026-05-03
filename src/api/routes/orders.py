"""src/api/routes/orders.py — Sprint 1.10-I 挂单 API。

对齐 docs/modeling.md b25cfe6(v1.4)§9.5 #14/#15:
- GET /api/orders/pending  → VirtualOrdersDAO.get_pending(active thesis 的)
- GET /api/orders/history  → VirtualOrdersDAO.get_filled + 过期挂单
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Query, Request


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/orders", tags=["orders"])


def _to_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@router.get("/pending")
def get_orders_pending(request: Request) -> dict[str, Any]:
    """v1.4 §9.5 #14:当前 active thesis 的所有 pending 挂单。

    Returns: {active_thesis_id, items: [{order_id, order_type, price, ...}]}
    无 active thesis → items=[]
    """
    from src.data.storage.dao import ThesesDAO, VirtualOrdersDAO

    ctx = request.app.state.ctx
    conn = ctx.conn_factory()
    try:
        active = ThesesDAO.get_active(conn)
        if active is None:
            return {"active_thesis_id": None, "items": []}
        items = VirtualOrdersDAO.get_pending(
            conn, thesis_id=active["thesis_id"],
        )
        return {"active_thesis_id": active["thesis_id"], "items": items}
    finally:
        try:
            conn.close()
        except Exception:
            pass


@router.get("/history")
def get_orders_history(
    request: Request,
    days: int = Query(30, ge=1, le=365, description="回看天数"),
) -> dict[str, Any]:
    """v1.4 §9.5 #15:历史挂单(filled + cancelled + expired,N 天内)。

    返按 filled_at_utc / created_at_utc DESC 排序。
    """
    ctx = request.app.state.ctx
    conn = ctx.conn_factory()
    try:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        # filled 看 filled_at_utc;非 filled(cancelled/expired)看 created_at_utc
        rows = conn.execute(
            "SELECT * FROM virtual_orders "
            "WHERE (filled_at_utc IS NOT NULL AND filled_at_utc >= ?) "
            "   OR (status IN ('cancelled', 'expired') AND created_at_utc >= ?) "
            "ORDER BY COALESCE(filled_at_utc, created_at_utc) DESC",
            (cutoff, cutoff),
        ).fetchall()
        items = [dict(r) for r in rows]
        return {"days": days, "items": items}
    finally:
        try:
            conn.close()
        except Exception:
            pass
