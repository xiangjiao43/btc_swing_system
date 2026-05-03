"""src/strategy/virtual_account.py — Sprint 1.10-B 虚拟账户管理。

对齐 docs/modeling.md b25cfe6(v1.4)§5.1.5。

职责:
- 浮盈浮亏计算(unrealized_pnl)
- equity 派生(total_equity)
- 收益率计算(日/周/月/年/至今,基于历史快照)

设计纪律:
- **不调用 DAO 写入**(D1=C 用户决策:OrdersEngine 不直接 insert,
  上层协调写入)。本模块产出 dict 供调用方传给
  VirtualAccountDAO.insert_snapshot。
- **不生成挂单**(留 1.10-D master AI)。
- **不推 thesis lifecycle**(留 1.10-C ThesisManager)。

PnL / Equity 公式(§5.1.5):
  unrealized_pnl_long  = long_btc_amount  × (current_price - long_avg_price)
  unrealized_pnl_short = short_btc_amount × (short_avg_price - current_price)
  unrealized_pnl       = sum
  total_equity         = available_cash + long_position_usdt + short_position_usdt + unrealized_pnl
  total_return_pct     = (total_equity - initial_capital) / initial_capital × 100
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional


def compute_snapshot(
    *,
    prev_snapshot: Optional[dict[str, Any]],
    current_btc_price: float,
    fills_since_last: list[dict[str, Any]],
    initial_capital: float,
    snapshot_id: str,
    run_id: str,
    snapshot_at_utc: str,
) -> dict[str, Any]:
    """计算新快照(16 字段 dict),可直接 **kwargs 传 VirtualAccountDAO.insert_snapshot。

    Args:
        prev_snapshot: 上次快照 dict(VirtualAccountDAO.get_latest 返回)。
                       None = 冷启动(无前置快照,从 initial_capital 起)。
        current_btc_price: 当前 BTC 价格(用于浮盈浮亏 mark-to-market)。
        fills_since_last: 本次以来的成交挂单 list(VirtualOrdersDAO.get_filled 或新触发的)。
                          每个 dict 必须含:direction (long/short), order_type (entry only),
                          size_usdt, filled_price, filled_btc_amount。
                          1.10-B 只处理 order_type='entry';stop_loss/take_profit
                          的 fill 留 1.10-C 的 ThesisManager 用 close 流程处理。
        initial_capital: 初始本金,从 base.yaml::virtual_account.initial_capital 读。
        snapshot_id / run_id / snapshot_at_utc: 调用方提供。

    Returns:
        16 字段 dict,字段名严格对齐 v1.4 §5.1.2 schema + insert_snapshot 参数。
    """
    # 起点:prev_snapshot 或冷启动默认值
    if prev_snapshot is None:
        long_position_usdt = 0.0
        long_avg_price: Optional[float] = None
        long_btc_amount = 0.0
        short_position_usdt = 0.0
        short_avg_price: Optional[float] = None
        short_btc_amount = 0.0
        available_cash = float(initial_capital)
        realized_pnl_total = 0.0
    else:
        long_position_usdt = float(prev_snapshot.get("long_position_usdt") or 0.0)
        long_avg_price = prev_snapshot.get("long_avg_price")
        long_btc_amount = float(prev_snapshot.get("long_btc_amount") or 0.0)
        short_position_usdt = float(prev_snapshot.get("short_position_usdt") or 0.0)
        short_avg_price = prev_snapshot.get("short_avg_price")
        short_btc_amount = float(prev_snapshot.get("short_btc_amount") or 0.0)
        available_cash = float(prev_snapshot.get("available_cash") or initial_capital)
        realized_pnl_total = float(prev_snapshot.get("realized_pnl_total") or 0.0)

    # 应用 fills,顺序敏感(entry 先,close 用更新后的 avg_price)
    # 1.10-C 扩展:同时处理 entry / stop_loss / take_profit 三种 order_type
    for fill in fills_since_last:
        order_type = fill.get("order_type")
        direction = fill.get("direction")
        size_usdt = float(fill.get("size_usdt") or 0.0)
        filled_price = float(fill.get("filled_price") or 0.0)
        filled_btc_amount = float(fill.get("filled_btc_amount") or 0.0)

        if order_type == "entry":
            # 加仓:position_usdt + cost_basis,available_cash 扣
            if direction == "long":
                long_position_usdt += size_usdt
                long_btc_amount += filled_btc_amount
                long_avg_price = (long_position_usdt / long_btc_amount) if long_btc_amount > 0 else None
                available_cash -= size_usdt
            elif direction == "short":
                short_position_usdt += size_usdt
                short_btc_amount += filled_btc_amount
                short_avg_price = (short_position_usdt / short_btc_amount) if short_btc_amount > 0 else None
                available_cash -= size_usdt
            # 其他 direction(异常)— 静默跳过,Validator 应在更上层拦截

        elif order_type in ("stop_loss", "take_profit"):
            # 1.10-C 扩展:close 流程(扣减 position + 算 realized_pnl)。
            # 不预 round(继承 1.10-B 教训:SQLite REAL = 64-bit double 不丢精度)。
            # 按 thesis 方向反向扣减:long thesis 的 close 卖 BTC,short thesis 的 close 买回 BTC。
            if direction == "long" and long_btc_amount > 0 and long_avg_price is not None:
                # 防 over-fill:实际平的 BTC 不能超过现持仓
                btc_to_close = min(filled_btc_amount, long_btc_amount)
                pnl_this_fill = btc_to_close * (filled_price - long_avg_price)
                cost_basis_closed = btc_to_close * long_avg_price
                # 持仓扣减 + 现金回收
                long_position_usdt -= cost_basis_closed
                long_btc_amount -= btc_to_close
                available_cash += btc_to_close * filled_price
                realized_pnl_total += pnl_this_fill
                if long_btc_amount <= 0:
                    long_btc_amount = 0.0
                    long_position_usdt = 0.0
                    long_avg_price = None
            elif direction == "short" and short_btc_amount > 0 and short_avg_price is not None:
                btc_to_close = min(filled_btc_amount, short_btc_amount)
                pnl_this_fill = btc_to_close * (short_avg_price - filled_price)
                cost_basis_closed = btc_to_close * short_avg_price
                short_position_usdt -= cost_basis_closed
                short_btc_amount -= btc_to_close
                available_cash += btc_to_close * filled_price
                realized_pnl_total += pnl_this_fill
                if short_btc_amount <= 0:
                    short_btc_amount = 0.0
                    short_position_usdt = 0.0
                    short_avg_price = None
            # 无对应持仓 → 静默跳过(1.10-D Validator 应在更上层拦截)

    # mark-to-market:浮盈浮亏
    unrealized_long = (
        long_btc_amount * (current_btc_price - long_avg_price)
        if long_btc_amount > 0 and long_avg_price is not None
        else 0.0
    )
    unrealized_short = (
        short_btc_amount * (short_avg_price - current_btc_price)
        if short_btc_amount > 0 and short_avg_price is not None
        else 0.0
    )
    unrealized_pnl = unrealized_long + unrealized_short

    # equity 派生(§5.1.5 公式)
    total_equity = (
        available_cash
        + long_position_usdt
        + short_position_usdt
        + unrealized_pnl
    )
    total_return_pct = (
        (total_equity - initial_capital) / initial_capital * 100
        if initial_capital > 0
        else 0.0
    )

    return {
        "snapshot_id": snapshot_id,
        "run_id": run_id,
        "snapshot_at_utc": snapshot_at_utc,
        "btc_price_at_snapshot": float(current_btc_price),
        "initial_capital": float(initial_capital),
        "available_cash": round(available_cash, 8),
        "long_position_usdt": round(long_position_usdt, 8),
        "long_avg_price": round(long_avg_price, 8) if long_avg_price is not None else None,
        "long_btc_amount": round(long_btc_amount, 8),
        "short_position_usdt": round(short_position_usdt, 8),
        "short_avg_price": round(short_avg_price, 8) if short_avg_price is not None else None,
        "short_btc_amount": round(short_btc_amount, 8),
        "total_equity": round(total_equity, 8),
        "realized_pnl_total": round(realized_pnl_total, 8),
        "unrealized_pnl": round(unrealized_pnl, 8),
        "total_return_pct": round(total_return_pct, 4),
    }


def _parse_iso(s: str) -> datetime:
    """容错解析 ISO 8601(支持 Z 后缀);失败返 None。"""
    s = str(s).replace("Z", "+00:00")
    return datetime.fromisoformat(s)


def compute_returns_history(
    snapshots: list[dict[str, Any]],
) -> dict[str, Optional[float]]:
    """基于历史 virtual_account 快照计算多档收益率(v1.4 §5.1.5)。

    Args:
        snapshots: VirtualAccountDAO.get_history(limit=N) 返回的 list,
                   按 snapshot_at_utc DESC(最新在 [0])。

    Returns:
        {daily_pct, weekly_pct, monthly_pct, yearly_pct, total_pct}
        - 任何窗口内无足够历史 → None(不抛异常)
        - 单位:百分比(2.5 = +2.5%)
        - total_pct = vs 最早一条快照(初始化那条)
    """
    empty = {"daily_pct": None, "weekly_pct": None,
             "monthly_pct": None, "yearly_pct": None, "total_pct": None}
    if not snapshots:
        return empty

    latest = snapshots[0]
    latest_equity = float(latest.get("total_equity") or 0.0)
    if latest_equity == 0.0:
        return empty
    try:
        latest_ts = _parse_iso(latest["snapshot_at_utc"])
    except (KeyError, ValueError, TypeError):
        return empty

    def closest_at_or_before(target: datetime) -> Optional[dict[str, Any]]:
        """找 ts ≤ target 的最新快照(如无则返 None)。"""
        candidates = []
        for s in snapshots:
            try:
                ts = _parse_iso(s["snapshot_at_utc"])
            except (KeyError, ValueError, TypeError):
                continue
            if ts <= target:
                candidates.append((ts, s))
        if not candidates:
            return None
        return max(candidates, key=lambda x: x[0])[1]

    def pct_vs_ago(days: int) -> Optional[float]:
        target = latest_ts - timedelta(days=days)
        snap = closest_at_or_before(target)
        if snap is None:
            return None
        base = float(snap.get("total_equity") or 0.0)
        if base == 0.0:
            return None
        return round((latest_equity / base - 1) * 100, 4)

    # total: vs 最早一条
    first = snapshots[-1]
    first_equity = float(first.get("total_equity") or 0.0)
    total_pct = (
        round((latest_equity / first_equity - 1) * 100, 4)
        if first_equity > 0 else None
    )

    return {
        "daily_pct": pct_vs_ago(1),
        "weekly_pct": pct_vs_ago(7),
        "monthly_pct": pct_vs_ago(30),
        "yearly_pct": pct_vs_ago(365),
        "total_pct": total_pct,
    }
