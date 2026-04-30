"""src/data/collectors/derived_onchain.py — Sprint 1.6 本地计算派生因子。

LTH-MVRV / STH-MVRV alphanode 不开放(/v1/metrics/market/mvrv_more 在中转
站 404),数学上可由已抓取的 BTC 收盘价 + lth_realized_price +
sth_realized_price 直接计算,本模块每次 data_collection 后跑一次回填到
onchain_metrics 表 source='computed'。

公式(建模 v1.3 §2.4 #5/#6):
  lth_mvrv_t = btc_close_t / lth_realized_price_t
  sth_mvrv_t = btc_close_t / sth_realized_price_t

数据来源(Sprint 1.6.1 修正):
  - btc_close:price_candles 表 timeframe='1d' / symbol='BTCUSDT' 的 close
    (1.6 误以为在 onchain_metrics.btc_price_close,生产实测发现该 metric
    不存在 — BTC 收盘价唯一来源是 price_candles 1d K 线)
  - lth_realized_price / sth_realized_price:onchain_metrics 表
    (Glassnode 原生 metric,正常入库)

调用契约:
  compute_and_save_derived_mvrv(conn) -> dict[str, int]
    Returns {"lth_mvrv": rows_upserted, "sth_mvrv": rows_upserted}
    任一来源缺失对应日期 → 跳过该日期(不抛错)
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from ..storage.dao import OnchainDAO, OnchainMetric


logger = logging.getLogger(__name__)


def _load_onchain_metric_by_ts(
    conn: sqlite3.Connection, metric_name: str,
) -> dict[str, float]:
    """读 onchain_metrics 中某 metric 的全历史 → {captured_at_utc: value}。"""
    out: dict[str, float] = {}
    try:
        rows = conn.execute(
            "SELECT captured_at_utc, value FROM onchain_metrics "
            "WHERE metric_name = ? AND value IS NOT NULL",
            (metric_name,),
        ).fetchall()
    except Exception as e:
        logger.warning("load %s failed: %s", metric_name, e)
        return out
    for r in rows:
        ts = r[0] if not hasattr(r, "keys") else r["captured_at_utc"]
        v = r[1] if not hasattr(r, "keys") else r["value"]
        try:
            out[ts] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def _load_btc_close_by_date(
    conn: sqlite3.Connection,
) -> dict[str, float]:
    """Sprint 1.6.1:从 price_candles 读 1d 收盘价 → {date_iso: close}。

    返回 key 是 ISO 日期(YYYY-MM-DDT00:00:00Z),与 Glassnode onchain_metrics
    captured_at_utc 同形态(daily 落在 UTC 0:00),便于直接 dict 键 join。
    """
    out: dict[str, float] = {}
    try:
        rows = conn.execute(
            "SELECT open_time_utc, close FROM price_candles "
            "WHERE timeframe = '1d' AND symbol = 'BTCUSDT' "
            "AND close IS NOT NULL"
        ).fetchall()
    except Exception as e:
        logger.warning("load price_candles 1d failed: %s", e)
        return out
    for r in rows:
        ts = r[0] if not hasattr(r, "keys") else r["open_time_utc"]
        v = r[1] if not hasattr(r, "keys") else r["close"]
        try:
            out[ts] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def compute_and_save_derived_mvrv(
    conn: sqlite3.Connection,
) -> dict[str, int]:
    """跑一次 LTH-MVRV / STH-MVRV 本地计算,upsert 到 onchain_metrics。

    数据来源(Sprint 1.6.1 修正):
      - btc_close ← price_candles WHERE timeframe='1d' AND symbol='BTCUSDT'
      - lth_realized_price / sth_realized_price ← onchain_metrics(Glassnode)
    在 timestamp(date)上 inner join,任一来源缺则跳过。
    """
    price_by_ts = _load_btc_close_by_date(conn)
    lth_rp_by_ts = _load_onchain_metric_by_ts(conn, "lth_realized_price")
    sth_rp_by_ts = _load_onchain_metric_by_ts(conn, "sth_realized_price")

    if not price_by_ts:
        logger.warning(
            "compute_derived_mvrv: price_candles 1d 表为空,跳过整批",
        )
        return {"lth_mvrv": 0, "sth_mvrv": 0}

    lth_rows: list[OnchainMetric] = []
    sth_rows: list[OnchainMetric] = []

    # LTH-MVRV
    for ts, price in price_by_ts.items():
        lth_rp = lth_rp_by_ts.get(ts)
        if lth_rp is None or lth_rp <= 0:
            continue
        lth_rows.append(OnchainMetric(
            timestamp=ts, metric_name="lth_mvrv",
            metric_value=float(price) / float(lth_rp),
            source="computed",  # type: ignore[arg-type]
        ))

    # STH-MVRV
    for ts, price in price_by_ts.items():
        sth_rp = sth_rp_by_ts.get(ts)
        if sth_rp is None or sth_rp <= 0:
            continue
        sth_rows.append(OnchainMetric(
            timestamp=ts, metric_name="sth_mvrv",
            metric_value=float(price) / float(sth_rp),
            source="computed",  # type: ignore[arg-type]
        ))

    stats: dict[str, int] = {"lth_mvrv": 0, "sth_mvrv": 0}
    try:
        if lth_rows:
            stats["lth_mvrv"] = OnchainDAO.upsert_batch(conn, lth_rows)
        if sth_rows:
            stats["sth_mvrv"] = OnchainDAO.upsert_batch(conn, sth_rows)
        conn.commit()
    except Exception as e:
        logger.warning("upsert derived mvrv failed: %s", e)

    logger.info(
        "compute_and_save_derived_mvrv: lth=%d sth=%d (price ts=%d / "
        "lth_rp ts=%d / sth_rp ts=%d)",
        stats["lth_mvrv"], stats["sth_mvrv"],
        len(price_by_ts), len(lth_rp_by_ts), len(sth_rp_by_ts),
    )
    return stats
