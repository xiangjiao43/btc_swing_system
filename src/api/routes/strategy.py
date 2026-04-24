"""GET /api/strategy/latest, /history, /history/{run_id}"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from ...data.storage.dao import StrategyStateDAO
from ..models import HistoryPage, StrategyStateRow


router = APIRouter(prefix="/strategy", tags=["strategy"])


def _row_to_model(row: dict[str, Any]) -> StrategyStateRow:
    state = row.get("state")
    if isinstance(state, str):
        try:
            state = json.loads(state)
        except (json.JSONDecodeError, ValueError):
            state = {}
    return StrategyStateRow(
        run_timestamp_utc=row["run_timestamp_utc"],
        run_id=row["run_id"],
        run_trigger=row["run_trigger"],
        rules_version=row["rules_version"],
        ai_model_actual=row.get("ai_model_actual"),
        state=state or {},
        created_at=row.get("created_at"),
    )


@router.get("/latest", response_model=StrategyStateRow)
def get_latest(request: Request) -> StrategyStateRow:
    ctx = request.app.state.ctx
    conn = ctx.conn_factory()
    try:
        row = StrategyStateDAO.get_latest_state(conn)
    finally:
        try:
            conn.close()
        except Exception:
            pass
    if row is None:
        raise HTTPException(status_code=404, detail="No strategy state found")
    return _row_to_model(row)


@router.get("/history", response_model=HistoryPage)
def list_history(
    request: Request,
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> HistoryPage:
    ctx = request.app.state.ctx
    conn = ctx.conn_factory()
    try:
        total_row = conn.execute(
            "SELECT COUNT(*) AS n FROM strategy_runs"
        ).fetchone()
        total = int(total_row["n"]) if total_row else 0
        rows = conn.execute(
            "SELECT * FROM strategy_runs "
            "ORDER BY reference_timestamp_utc DESC, generated_at_utc DESC "
            "LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    finally:
        try:
            conn.close()
        except Exception:
            pass

    items: list[StrategyStateRow] = []
    for r in rows:
        d = dict(r)
        d["state"] = json.loads(d.pop("full_state_json"))
        d["run_timestamp_utc"] = d.get("reference_timestamp_utc") or d.get("generated_at_utc")
        d.setdefault("created_at", d.get("generated_at_utc"))
        items.append(_row_to_model(d))
    return HistoryPage(total=total, limit=limit, offset=offset, items=items)


@router.get("/history/{run_id}", response_model=StrategyStateRow)
def get_one_history(request: Request, run_id: str) -> StrategyStateRow:
    ctx = request.app.state.ctx
    conn = ctx.conn_factory()
    try:
        row = conn.execute(
            "SELECT * FROM strategy_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"run_id {run_id} not found",
        )
    d = dict(row)
    d["state"] = json.loads(d.pop("full_state_json"))
    d["run_timestamp_utc"] = d.get("reference_timestamp_utc") or d.get("generated_at_utc")
    d.setdefault("created_at", d.get("generated_at_utc"))
    return _row_to_model(d)
