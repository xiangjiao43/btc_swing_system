"""建模 §9.10 #8:GET /api/review/{lifecycle_id}

某条生命周期的复盘报告(review_reports 表)。
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request


router = APIRouter(prefix="/review", tags=["review"])


@router.get("/{lifecycle_id}")
def get_review_by_lifecycle(
    request: Request,
    lifecycle_id: str,
) -> dict[str, Any]:
    """§9.10 #8:某 lifecycle 的复盘报告(若有多次复盘,返回最新一条)。"""
    ctx = request.app.state.ctx
    conn = ctx.conn_factory()
    try:
        row = conn.execute(
            "SELECT * FROM review_reports "
            "WHERE lifecycle_id = ? "
            "ORDER BY generated_at_utc DESC LIMIT 1",
            (lifecycle_id,),
        ).fetchone()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"No review for lifecycle_id={lifecycle_id}",
        )
    d = dict(row)
    raw = d.pop("full_report_json", None)
    if raw:
        try:
            d["report"] = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            d["report"] = {"_raw": raw}
    else:
        d["report"] = None
    return d
