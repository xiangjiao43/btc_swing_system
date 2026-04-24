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
                "SELECT * FROM fallback_log WHERE triggered_by LIKE ? "
                "ORDER BY run_timestamp_utc DESC LIMIT ?",
                (f"%{stage}%", limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM fallback_log "
                "ORDER BY run_timestamp_utc DESC LIMIT ?",
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
