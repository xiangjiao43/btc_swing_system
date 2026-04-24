"""GET /api/market/btc-price — 轻量行情拉取,供前端每分钟刷新顶栏价格。

设计纪律(Sprint 2.3 tuning):
  * 零 AI 消耗 — 不触发 adjudicator / pipeline
  * 零证据层运算 — 不经过 L1-L5
  * 只查 price_candles 1h 表;若最新条 > 30 分钟则触发一次 CoinGlass 1h K 线轻量抓取
  * 调用频率前端每 60s 一次,后端无内置节流(轻量 SQL 即可)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from pydantic import BaseModel


logger = logging.getLogger(__name__)
_BJT = ZoneInfo("Asia/Shanghai")


router = APIRouter(prefix="/market", tags=["market"])


class BtcPriceResponse(BaseModel):
    price: Optional[float]
    price_24h_change_pct: Optional[float]
    price_7d_change_pct: Optional[float]
    captured_at_utc: Optional[str]
    captured_at_bjt: Optional[str]
    source: str
    stale: bool
    age_minutes: Optional[float]


def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_bjt_str(dt: datetime) -> str:
    return dt.astimezone(_BJT).strftime("%Y-%m-%d %H:%M (BJT)")


def _parse_iso(s: str) -> Optional[datetime]:
    try:
        s2 = s.replace("Z", "+00:00") if s.endswith("Z") else s
        d = datetime.fromisoformat(s2)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except Exception:
        return None


def _query_latest_1h(conn: Any) -> list[dict[str, Any]]:
    """取最近 8 根 1h K 线(足够算 24h 变化)。"""
    rows = conn.execute(
        "SELECT open_time_utc, close FROM price_candles "
        "WHERE symbol='BTCUSDT' AND timeframe='1h' "
        "ORDER BY open_time_utc DESC LIMIT 200"
    ).fetchall()
    return [dict(r) for r in rows]


def _try_refresh_from_coinglass(conn: Any) -> None:
    """若 1h K 线过期 > 30 分钟,抓一次最新 48 根写入 price_candles。
    失败只打 warning,不抛异常。"""
    try:
        from ...data.collectors.coinglass import CoinglassCollector
        from ...data.storage.dao import BTCKlinesDAO, KlineRow
    except Exception as e:
        logger.warning("coinglass refresh skipped (import failed): %s", e)
        return

    try:
        coll = CoinglassCollector()
        rows = coll.fetch_klines(interval="1h", limit=48) or []
        if not rows:
            return
        klines = [
            KlineRow(
                timeframe="1h", timestamp=r["timestamp"],
                open=r["open"], high=r["high"], low=r["low"], close=r["close"],
                volume_btc=r.get("volume", 0.0) or 0.0,
            )
            for r in rows
        ]
        BTCKlinesDAO.upsert_klines(conn, klines)
        conn.commit()
        logger.info("btc-price route refreshed 1h klines: +%d rows", len(klines))
    except Exception as e:
        logger.warning("coinglass refresh failed: %s", e)


def _compute_changes(rows: list[dict[str, Any]]) -> tuple[
    Optional[float], Optional[float], Optional[float], Optional[datetime]
]:
    """rows 按 open_time_utc DESC,取 current / 24h前(24 根 1h) / 7d前(168 根 1h)。"""
    if not rows:
        return None, None, None, None
    cur_row = rows[0]
    current = float(cur_row["close"])
    ts = _parse_iso(cur_row["open_time_utc"])

    # 24h 前(第 25 条,相当于 24 根前)
    h24 = None
    if len(rows) >= 25:
        try:
            prev = float(rows[24]["close"])
            if prev > 0:
                h24 = (current / prev - 1.0) * 100.0
        except Exception:
            pass

    # 7d 前
    d7 = None
    if len(rows) >= 169:
        try:
            prev = float(rows[168]["close"])
            if prev > 0:
                d7 = (current / prev - 1.0) * 100.0
        except Exception:
            pass

    return current, h24, d7, ts


@router.get("/btc-price", response_model=BtcPriceResponse)
def get_btc_price(request: Request) -> BtcPriceResponse:
    """返回 BTC 现价 + 24h / 7d 变化,时间戳为最新 1h K 线 open_time。

    流程:
      1. 查 price_candles 1h 最近 200 条
      2. 若最新条已超过 30 分钟,触发一次 CoinGlass 轻量抓取 1h 48 根
      3. 重查,再算变化率
    """
    ctx = request.app.state.ctx
    conn = ctx.conn_factory()
    try:
        rows = _query_latest_1h(conn)
        current, h24, d7, ts = _compute_changes(rows)

        # 过期判断
        now = datetime.now(timezone.utc)
        age_min = None
        stale = False
        if ts is not None:
            age_min = (now - ts).total_seconds() / 60.0
            if age_min > 30:
                stale = True

        if stale or current is None:
            _try_refresh_from_coinglass(conn)
            rows = _query_latest_1h(conn)
            current, h24, d7, ts = _compute_changes(rows)
            if ts is not None:
                age_min = (now - ts).total_seconds() / 60.0
                stale = age_min > 30 if age_min is not None else True

        return BtcPriceResponse(
            price=(round(current, 2) if current is not None else None),
            price_24h_change_pct=(round(h24, 2) if h24 is not None else None),
            price_7d_change_pct=(round(d7, 2) if d7 is not None else None),
            captured_at_utc=(_utc_iso(ts) if ts is not None else None),
            captured_at_bjt=(_to_bjt_str(ts) if ts is not None else None),
            source="binance_kline_1h_close_via_coinglass",
            stale=stale,
            age_minutes=(round(age_min, 1) if age_min is not None else None),
        )
    finally:
        try:
            conn.close()
        except Exception:
            pass
