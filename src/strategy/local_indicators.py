"""src/strategy/local_indicators.py — 纯本地计算的衍生指标。

从 price_candles 1d 直接算,无外部数据源依赖。供
src/api/routes/export.py 的 markdown snapshot 使用,不进入
SpotCycleContextBuilder / ContextBuilder 的 AI 链路(那两个由建模锁定)。
"""

from __future__ import annotations

import sqlite3
from typing import Any


def _fetch_1d_closes(
    conn: sqlite3.Connection, n: int = 400,
) -> list[tuple[str, float]]:
    """取最近 n 根 BTC 1d 收盘价 (open_time_utc, close),按时间升序返回。"""
    rows = conn.execute(
        "SELECT open_time_utc, close FROM price_candles "
        "WHERE symbol='BTCUSDT' AND timeframe='1d' "
        "ORDER BY open_time_utc DESC LIMIT ?",
        (n,),
    ).fetchall()
    pairs = [(r["open_time_utc"], float(r["close"])) for r in rows]
    pairs.reverse()
    return pairs


def compute_pi_cycle(conn: sqlite3.Connection) -> dict[str, Any]:
    """Pi Cycle Top: SMA-111 vs SMA-350×2。

    历史读法:SMA-111 上穿 SMA-350×2 → 大周期顶部信号(2013/2017/2021 都精准)。
    本函数输出 ratio = sma_111 / sma_350x2:
      ratio < 0.7   → 远离顶部
      0.7 ~ 0.95    → 中段
      0.95 ~ 1.0    → 接近触发
      >= 1.0        → 已触发顶部信号
    """
    closes = _fetch_1d_closes(conn, n=400)
    if len(closes) < 350:
        return {"status": "missing", "bars_available": len(closes),
                "reason": "insufficient_1d_history_<350"}
    vals = [c for _, c in closes]
    sma_111 = sum(vals[-111:]) / 111.0
    sma_350 = sum(vals[-350:]) / 350.0
    sma_350x2 = sma_350 * 2.0
    ratio = (sma_111 / sma_350x2) if sma_350x2 > 0 else None
    return {
        "status": "available",
        "sma_111": sma_111,
        "sma_350x2": sma_350x2,
        "ratio": ratio,
        "as_of": closes[-1][0],
        "bars_available": len(closes),
    }


def compute_mayer_multiple(conn: sqlite3.Connection) -> dict[str, Any]:
    """Mayer Multiple = current_close / SMA-200。

    历史参照(非红线):
      > 2.4    偏高(历史顶部前夜常见)
      1 ~ 2.4  健康
      < 1      偏低(熊底常见)
    """
    closes = _fetch_1d_closes(conn, n=250)
    if len(closes) < 200:
        return {"status": "missing", "bars_available": len(closes),
                "reason": "insufficient_1d_history_<200"}
    vals = [c for _, c in closes]
    sma_200 = sum(vals[-200:]) / 200.0
    current = vals[-1]
    mayer = (current / sma_200) if sma_200 > 0 else None
    return {
        "status": "available",
        "sma_200": sma_200,
        "current_close": current,
        "mayer": mayer,
        "as_of": closes[-1][0],
        "bars_available": len(closes),
    }


__all__ = ["compute_pi_cycle", "compute_mayer_multiple"]
