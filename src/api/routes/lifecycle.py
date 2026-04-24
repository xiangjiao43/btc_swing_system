"""建模 §9.10 #6-#7:生命周期相关路由。

  GET /api/lifecycle/current   — 当前生命周期(从 strategy_runs 派生)
  GET /api/lifecycle/history   — 生命周期归档历史

lifecycles 表在 Sprint 1.5c 新建但 Sprint 1.5b 并未填充(由 Sprint 2+ 的
lifecycle_manager 写入)。v1 先从 strategy_runs.full_state_json.lifecycle 读。
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Query, Request


router = APIRouter(prefix="/lifecycle", tags=["lifecycle"])


@router.get("/current")
def get_current_lifecycle(request: Request) -> dict[str, Any]:
    """§9.10 #6:当前生命周期。

    v1 实现:读最新 strategy_runs 的 state.lifecycle 块。若为
    pending_lifecycle_manager 占位,也原样返回(前端自己处理)。
    """
    ctx = request.app.state.ctx
    conn = ctx.conn_factory()
    try:
        row = conn.execute(
            "SELECT run_id, reference_timestamp_utc, full_state_json "
            "FROM strategy_runs "
            "ORDER BY reference_timestamp_utc DESC LIMIT 1"
        ).fetchone()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    if row is None:
        return {"lifecycle": None, "message": "No strategy run yet"}
    state = json.loads(row["full_state_json"])
    lifecycle = state.get("lifecycle") or {}
    return {
        "lifecycle": lifecycle,
        "run_id": row["run_id"],
        "reference_timestamp_utc": row["reference_timestamp_utc"],
    }


@router.get("/history")
def list_lifecycles(
    request: Request,
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    """§9.10 #7:生命周期历史。从 lifecycles 表读。"""
    ctx = request.app.state.ctx
    conn = ctx.conn_factory()
    try:
        if status:
            rows = conn.execute(
                "SELECT * FROM lifecycles WHERE status = ? "
                "ORDER BY entry_time_utc DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM lifecycles "
                "ORDER BY entry_time_utc DESC LIMIT ?",
                (limit,),
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
    return {"count": len(items), "limit": limit, "items": items}
