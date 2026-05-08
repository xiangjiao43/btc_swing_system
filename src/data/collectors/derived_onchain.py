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
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from ..storage.dao import OnchainDAO, OnchainMetric


logger = logging.getLogger(__name__)


# Sprint C(2026-05-08):上游一手 Glassnode 数据 stale 阈值。
# Glassnode 日级 bar 自然延迟 ≈ 1 天(May 8 BJT 8:35 fetch 拿到的最新 bar
# 通常是 May 6 或 May 7,captured_at_utc 以 bar 开盘 UTC 为准 → 24-48h
# 老属正常)。> 48h 才视为真 stale,避免在健康日把正常延迟的派生计算误 abort。
_UPSTREAM_STALE_THRESHOLD_HOURS: int = 48

# 一手 Glassnode source 标签(与 jobs.py 的 _ONCHAIN_FIRST_HAND_SOURCES 同义,
# 但本文件保持自己的常量,避免反向 import)。
_FIRST_HAND_SOURCES: tuple[str, ...] = (
    "glassnode_primary",
    "glassnode_display",
    "glassnode_derived_breakdown_by_age",
)


def _upstream_glassnode_stale(conn: sqlite3.Connection) -> tuple[bool, Optional[str]]:
    """检查 onchain_metrics 一手 Glassnode 数据的 MAX(captured_at_utc) 是否 stale。

    返回 (is_stale, max_iso)。is_stale=True 时调用方应跳过派生计算 +
    日志 warning。空表 / 查询失败也视为 stale(防御性)。
    """
    placeholders = ",".join(["?"] * len(_FIRST_HAND_SOURCES))
    try:
        row = conn.execute(
            f"SELECT MAX(captured_at_utc) FROM onchain_metrics "
            f"WHERE source IN ({placeholders})",
            _FIRST_HAND_SOURCES,
        ).fetchone()
    except Exception as e:
        logger.warning(
            "_upstream_glassnode_stale: query failed: %s — treat as stale", e,
        )
        return True, None
    max_iso: Optional[str] = row[0] if row and row[0] else None
    if max_iso is None:
        return True, None
    try:
        s = max_iso.replace("Z", "+00:00") if max_iso.endswith("Z") else max_iso
        max_dt = datetime.fromisoformat(s)
        if max_dt.tzinfo is None:
            max_dt = max_dt.replace(tzinfo=timezone.utc)
    except Exception:
        return True, max_iso
    age = datetime.now(timezone.utc) - max_dt
    is_stale = age > timedelta(hours=_UPSTREAM_STALE_THRESHOLD_HOURS)
    return is_stale, max_iso


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

    Sprint C(2026-05-08):上游一手 Glassnode 数据 > 48h 老 → 跳过整批,
    不让 derived 行刷新 onchain_metrics MAX(captured_at_utc) 误导网页 +
    state_builder。
    """
    is_stale, max_iso = _upstream_glassnode_stale(conn)
    if is_stale:
        logger.warning(
            "compute_derived_mvrv: 一手 Glassnode stale (max=%s, threshold=%dh) "
            "→ 跳过派生计算,不写新行",
            max_iso, _UPSTREAM_STALE_THRESHOLD_HOURS,
        )
        return {"lth_mvrv": 0, "sth_mvrv": 0}

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
