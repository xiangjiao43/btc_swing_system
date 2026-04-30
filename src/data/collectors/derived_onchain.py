"""src/data/collectors/derived_onchain.py — Sprint 1.6 本地计算派生因子。

LTH-MVRV / STH-MVRV alphanode 不开放(/v1/metrics/market/mvrv_more 在中转
站 404),数学上可由已抓取的 btc_price_close + lth_realized_price +
sth_realized_price 直接计算,本模块每次 data_collection 后跑一次回填到
onchain_metrics 表 source='computed'。

公式(建模 v1.3 §2.4 #5/#6):
  lth_mvrv_t = btc_price_close_t / lth_realized_price_t
  sth_mvrv_t = btc_price_close_t / sth_realized_price_t

调用契约:
  compute_and_save_derived_mvrv(conn) -> dict[str, int]
    Returns {"lth_mvrv": rows_upserted, "sth_mvrv": rows_upserted}
    任一来源 metric 缺失对应日期 → 跳过该日期(不抛错)
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from ..storage.dao import OnchainDAO, OnchainMetric


logger = logging.getLogger(__name__)


def _load_metric_by_ts(
    conn: sqlite3.Connection, metric_name: str,
) -> dict[str, float]:
    """读 onchain_metrics 中某 metric 的全历史 → {timestamp: value}。"""
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


def compute_and_save_derived_mvrv(
    conn: sqlite3.Connection,
) -> dict[str, int]:
    """跑一次 LTH-MVRV / STH-MVRV 本地计算,upsert 到 onchain_metrics。

    数据来源:
      - btc_price_close
      - lth_realized_price
      - sth_realized_price
    在 timestamp 上 inner join,任一来源缺则跳过。
    """
    price_by_ts = _load_metric_by_ts(conn, "btc_price_close")
    lth_rp_by_ts = _load_metric_by_ts(conn, "lth_realized_price")
    sth_rp_by_ts = _load_metric_by_ts(conn, "sth_realized_price")

    if not price_by_ts:
        logger.warning(
            "compute_derived_mvrv: btc_price_close 表为空,跳过整批",
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
