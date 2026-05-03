"""src/api/routes/review_weekly.py — Sprint 1.10-I 周复盘 API。

对齐 docs/modeling.md b25cfe6(v1.4)§9.5 #16/#17:
- GET /api/review/weekly/latest         → 最新一行 weekly_reviews
- GET /api/review/weekly/history?limit  → 历史 12 周(D3=a 一次返完整 output_json)
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Query, Request


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/review/weekly", tags=["weekly_review"])


def _row_to_dict(row: Any) -> dict[str, Any]:
    """parse output_json TEXT → dict;失败返 raw 字符串。"""
    d = dict(row)
    raw = d.get("output_json")
    if isinstance(raw, str):
        try:
            d["output"] = json.loads(raw)
        except Exception:
            d["output"] = None
            d["output_parse_error"] = True
    return d


@router.get("/latest")
def get_weekly_review_latest(request: Request) -> dict[str, Any]:
    """v1.4 §9.5 #16:最新一行 weekly_reviews(按 triggered_at_utc DESC)。

    Returns: weekly_review dict(含 parsed output)或空 dict(无历史)。
    """
    ctx = request.app.state.ctx
    conn = ctx.conn_factory()
    try:
        row = conn.execute(
            "SELECT * FROM weekly_reviews "
            "ORDER BY triggered_at_utc DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return {}
        return _row_to_dict(row)
    finally:
        try:
            conn.close()
        except Exception:
            pass


@router.get("/history")
def get_weekly_review_history(
    request: Request,
    limit: int = Query(12, ge=1, le=52, description="历史周复盘条数,默认 12 周"),
) -> dict[str, Any]:
    """v1.4 §9.5 #17 + D3=a:历史复盘列表(默认 12 周一次返完整 output_json)。

    避免前端 N+1 query — D3=a 决策。
    """
    ctx = request.app.state.ctx
    conn = ctx.conn_factory()
    try:
        rows = conn.execute(
            "SELECT * FROM weekly_reviews "
            "ORDER BY triggered_at_utc DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        items = [_row_to_dict(r) for r in rows]
        return {"limit": limit, "items": items}
    finally:
        try:
            conn.close()
        except Exception:
            pass
