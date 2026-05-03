"""src/api/routes/account.py — Sprint 1.10-I 虚拟账户 API。

对齐 docs/modeling.md b25cfe6(v1.4)§9.5 #8/#9/#10:
- GET /api/account/current  → VirtualAccountDAO.get_latest
- GET /api/account/history  → VirtualAccountDAO.get_history(用 days 参数过滤)
- GET /api/account/returns  → VirtualAccountManager.compute_returns_history

设计纪律:
- 纯查询,不改 DB;失败返 200 + 空 dict / list(前端可降级渲染)
- ctx.conn_factory() 每次新连接,函数末尾 close
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/account", tags=["account"])


def _to_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@router.get("/current")
def get_account_current(request: Request) -> dict[str, Any]:
    """v1.4 §9.5 #8:virtual_account 最新快照。

    Returns:
      {snapshot_id, run_id, snapshot_at_utc, btc_price_at_snapshot,
       initial_capital, available_cash, total_equity, ...} 或 null 空 dict。
    """
    from src.data.storage.dao import VirtualAccountDAO

    ctx = request.app.state.ctx
    conn = ctx.conn_factory()
    try:
        latest = VirtualAccountDAO.get_latest(conn)
        return latest or {}
    finally:
        try:
            conn.close()
        except Exception:
            pass


@router.get("/history")
def get_account_history(
    request: Request,
    days: int = Query(30, ge=1, le=365, description="回看天数,默认 30 天"),
) -> dict[str, Any]:
    """v1.4 §9.5 #9:资金曲线历史(N 天 snapshots)。

    Sprint 1.10-I D1=c:返回 30 个 (date, total_equity) 点供前端 SVG sparkline。

    Returns:
      {days: int, snapshots: [{snapshot_at_utc, total_equity, ...}, ...]}
    """
    from src.data.storage.dao import VirtualAccountDAO

    ctx = request.app.state.ctx
    conn = ctx.conn_factory()
    try:
        # VirtualAccountDAO.get_history 返按 snapshot_at_utc DESC,我们要 ASC 给前端
        # 先取过去 N 天所有 snapshot(按 snapshot_at_utc 过滤)
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = conn.execute(
            "SELECT * FROM virtual_account "
            "WHERE snapshot_at_utc >= ? "
            "ORDER BY snapshot_at_utc ASC",
            (cutoff,),
        ).fetchall()
        snapshots = [dict(r) for r in rows]
        return {"days": days, "snapshots": snapshots}
    finally:
        try:
            conn.close()
        except Exception:
            pass


@router.get("/returns")
def get_account_returns(request: Request) -> dict[str, Any]:
    """v1.4 §9.5 #10:各周期收益率(日/周/月/年/至今)。

    Returns:
      {daily_pct, weekly_pct, monthly_pct, yearly_pct, since_inception_pct}
      若计算失败 → 各字段 null + error_msg。
    """
    from src.data.storage.dao import VirtualAccountDAO
    from src.strategy.virtual_account import compute_returns_history

    ctx = request.app.state.ctx
    conn = ctx.conn_factory()
    try:
        # compute_returns_history 期望 DESC(最新在 [0])
        rows = conn.execute(
            "SELECT * FROM virtual_account ORDER BY snapshot_at_utc DESC"
        ).fetchall()
        snapshots = [dict(r) for r in rows]
        if not snapshots:
            return {
                "daily_pct": None, "weekly_pct": None, "monthly_pct": None,
                "yearly_pct": None, "total_pct": None,
                "snapshots_count": 0,
            }
        try:
            returns = compute_returns_history(snapshots=snapshots)
            returns["snapshots_count"] = len(snapshots)
            return returns
        except Exception as e:
            logger.warning("compute_returns_history failed: %s", e)
            return {
                "daily_pct": None, "weekly_pct": None, "monthly_pct": None,
                "yearly_pct": None, "total_pct": None,
                "error": str(e)[:200],
            }
    finally:
        try:
            conn.close()
        except Exception:
            pass
