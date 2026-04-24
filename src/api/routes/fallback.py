"""GET /api/fallback_log — 查看最近 Fallback 事件。"""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Query, Request

from ..models import FallbackLogItem, FallbackLogPage


router = APIRouter(tags=["fallback"])


@router.get("/fallback_log", response_model=FallbackLogPage)
def list_fallback(
    request: Request,
    stage: Optional[str] = Query(None, description="triggered_by 前缀过滤"),
    limit: int = Query(50, ge=1, le=500),
) -> FallbackLogPage:
    ctx = request.app.state.ctx
    conn = ctx.conn_factory()
    try:
        if stage:
            rows = conn.execute(
                "SELECT id, triggered_at_utc AS run_timestamp_utc, "
                "fallback_level, reason AS triggered_by, "
                "resolution_note AS details, triggered_at_utc AS created_at "
                "FROM fallback_events WHERE reason LIKE ? "
                "ORDER BY triggered_at_utc DESC LIMIT ?",
                (f"%{stage}%", limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, triggered_at_utc AS run_timestamp_utc, "
                "fallback_level, reason AS triggered_by, "
                "resolution_note AS details, triggered_at_utc AS created_at "
                "FROM fallback_events "
                "ORDER BY triggered_at_utc DESC LIMIT ?",
                (limit,),
            ).fetchall()
    finally:
        try:
            conn.close()
        except Exception:
            pass

    items: list[FallbackLogItem] = []
    for r in rows:
        d = dict(r)
        raw = d.get("details")
        if isinstance(raw, str) and raw:
            try:
                d["details"] = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                d["details"] = {"_raw": raw}
        items.append(FallbackLogItem(**d))
    return FallbackLogPage(limit=limit, items=items)
