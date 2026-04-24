"""建模 §9.10 #5:GET /api/evidence/card/{card_id}/history

证据指标时序。从 evidence_card_history 表按 card_id 取最近 N 条。
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Query, Request


router = APIRouter(prefix="/evidence", tags=["evidence"])


@router.get("/card/{card_id}/history")
def get_evidence_card_history(
    request: Request,
    card_id: str,
    limit: int = Query(100, ge=1, le=1000),
) -> dict[str, Any]:
    """§9.10 #5:某证据卡的历史时序。"""
    ctx = request.app.state.ctx
    conn = ctx.conn_factory()
    try:
        rows = conn.execute(
            "SELECT id, card_id, run_id, captured_at_utc, "
            "value_numeric, value_text, data_fresh, full_data_json "
            "FROM evidence_card_history "
            "WHERE card_id = ? "
            "ORDER BY captured_at_utc DESC LIMIT ?",
            (card_id, limit),
        ).fetchall()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    items: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        raw = d.pop("full_data_json", None)
        if raw:
            try:
                d["full_data"] = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                d["full_data"] = None
        else:
            d["full_data"] = None
        items.append(d)
    return {
        "card_id": card_id,
        "limit": limit,
        "count": len(items),
        "items": items,
    }
