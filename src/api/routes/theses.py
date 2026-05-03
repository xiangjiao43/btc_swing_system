"""src/api/routes/theses.py — Sprint 1.10-I theses API。

对齐 docs/modeling.md b25cfe6(v1.4)§9.5 #11/#12/#13:
- GET /api/theses/active        → ThesesDAO.get_active
- GET /api/theses/history       → ThesesDAO.get_history(limit 默认 20)
- GET /api/theses/{thesis_id}   → ThesesDAO.get_by_id(commit 2 新加 1 行)
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/theses", tags=["theses"])


@router.get("/active")
def get_thesis_active(request: Request) -> dict[str, Any]:
    """v1.4 §9.5 #11:当前 active thesis。

    Returns: thesis dict 或空 dict(无 active)。
    """
    from src.data.storage.dao import ThesesDAO

    ctx = request.app.state.ctx
    conn = ctx.conn_factory()
    try:
        active = ThesesDAO.get_active(conn)
        return active or {}
    finally:
        try:
            conn.close()
        except Exception:
            pass


@router.get("/history")
def get_thesis_history(
    request: Request,
    limit: int = Query(20, ge=1, le=200, description="历史 thesis 条数"),
) -> dict[str, Any]:
    """v1.4 §9.5 #12:历史 thesis 列表(按 created_at_utc DESC)。"""
    from src.data.storage.dao import ThesesDAO

    ctx = request.app.state.ctx
    conn = ctx.conn_factory()
    try:
        items = ThesesDAO.get_history(conn, limit=limit)
        return {"limit": limit, "items": items}
    finally:
        try:
            conn.close()
        except Exception:
            pass


# 注:本路由必须放在 /history 之后,否则 thesis_id="history" 会匹配 /{thesis_id}
@router.get("/{thesis_id}")
def get_thesis_by_id(request: Request, thesis_id: str) -> dict[str, Any]:
    """v1.4 §9.5 #13:单个 thesis 详情(PK 直查)。

    404 if thesis_id 不存在。
    """
    from src.data.storage.dao import ThesesDAO

    ctx = request.app.state.ctx
    conn = ctx.conn_factory()
    try:
        thesis = ThesesDAO.get_by_id(conn, thesis_id=thesis_id)
        if thesis is None:
            raise HTTPException(
                status_code=404, detail=f"thesis_id not found: {thesis_id!r}",
            )
        return thesis
    finally:
        try:
            conn.close()
        except Exception:
            pass
