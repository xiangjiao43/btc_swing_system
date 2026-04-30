"""GET /api/market/btc-price — 轻量行情拉取,供前端顶栏价格。

Sprint 1.5k:数据源优先级
  1. **现货 1m**(CoinGlass spot/price/history,Binance 现货 BTCUSDT)
     - 颗粒度 1 分钟,延迟 < 1 分钟
     - source = "binance_spot_1m_via_coinglass"
     - stale 阈值 = 2 分钟
  2. fallback **期货 1h K 线**(price_candles 表 + CoinGlass 兜底)
     - 颗粒度 1 小时
     - source = "binance_kline_1h_close_via_coinglass"
     - stale 阈值 = 30 分钟

24h / 7d 变化率独立计算 — 始终用 1h K 线(spot 1m 算 24h 要拉 1440 根,
代价高;变化率精度对小数点后 2 位足够)。

设计纪律(Sprint 2.3 + 1.5k):
  * 零 AI 消耗 — 不触发 adjudicator / pipeline
  * 零证据层运算 — 不经过 L1-L5
  * 现货失败时降级到 1h K 线;两条路径独立,不互相阻塞
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from pydantic import BaseModel


logger = logging.getLogger(__name__)
_BJT = ZoneInfo("Asia/Shanghai")

# Sprint 1.5k:不同数据源的 stale 阈值(分钟)
_STALE_THRESHOLD_SPOT_MIN = 2.0    # 现货 1m → 2 分钟
_STALE_THRESHOLD_KLINE_MIN = 30.0  # 1h K 线 → 30 分钟


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
    """取最近 200 根 1h K 线(足够算 24h / 7d 变化)。"""
    rows = conn.execute(
        "SELECT open_time_utc, close FROM price_candles "
        "WHERE symbol='BTCUSDT' AND timeframe='1h' "
        "ORDER BY open_time_utc DESC LIMIT 200"
    ).fetchall()
    return [dict(r) for r in rows]


def _try_refresh_from_coinglass(conn: Any) -> None:
    """若 1h K 线过期 > 30 分钟,抓一次最新 48 根写入 price_candles。
    失败只打 warning,不抛异常。Sprint 1.5k 起仍保留作为 fallback 兜底。"""
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
    """rows 按 open_time_utc DESC,取 current / 24h前(24 根 1h) / 7d前(168 根 1h)。

    Sprint 1.5k:返回的 current 仅用于 fallback 路径;spot 路径的 price 由
    fetch_spot_price_history 提供,但 24h/7d 变化继续用本函数(K 线 1h 数据)。
    """
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


def _try_fetch_spot_1m() -> tuple[Optional[float], Optional[datetime]]:
    """Sprint 1.5k:取现货 1m 最新 close + bar 时间。
    失败返回 (None, None),由调用方 fallback 到 K 线路径。"""
    try:
        from ...data.collectors.coinglass import CoinglassCollector
    except Exception as e:
        logger.warning("spot 1m import failed: %s", e)
        return None, None
    try:
        coll = CoinglassCollector()
        rows = coll.fetch_spot_price_history(
            symbol="BTCUSDT", exchange="Binance", interval="1m", limit=2,
        )
        if not rows:
            return None, None
        last = rows[-1]
        price = float(last.get("close")) if last.get("close") is not None else None
        ts = _parse_iso(last.get("timestamp", ""))
        return price, ts
    except Exception as e:
        logger.warning("spot 1m fetch failed (will fallback to 1h kline): %s", e)
        return None, None


@router.get("/btc-price", response_model=BtcPriceResponse)
def get_btc_price(request: Request) -> BtcPriceResponse:
    """返回 BTC 现价 + 24h / 7d 变化。

    Sprint 1.5k 流程:
      1. 现货 1m(主):price + captured_at 来自 CoinGlass spot/price/history
      2. 24h / 7d 变化率始终查 price_candles 1h(独立路径,不阻塞主)
      3. 现货失败 → fallback 到 1h K 线(老路径完整保留)
    """
    ctx = request.app.state.ctx
    conn = ctx.conn_factory()
    try:
        now = datetime.now(timezone.utc)

        # ---- 1) 主路径:现货 1m ----
        spot_price, spot_ts = _try_fetch_spot_1m()

        if spot_price is not None and spot_ts is not None:
            age_min = (now - spot_ts).total_seconds() / 60.0
            stale = age_min > _STALE_THRESHOLD_SPOT_MIN

            # 24h / 7d 变化率仍用 1h K 线(独立计算,不阻塞)
            kline_rows = _query_latest_1h(conn)
            _, h24, d7, _ = _compute_changes(kline_rows)

            return BtcPriceResponse(
                price=round(spot_price, 2),
                price_24h_change_pct=(round(h24, 2) if h24 is not None else None),
                price_7d_change_pct=(round(d7, 2) if d7 is not None else None),
                captured_at_utc=_utc_iso(spot_ts),
                captured_at_bjt=_to_bjt_str(spot_ts),
                source="binance_spot_1m_via_coinglass",
                stale=stale,
                age_minutes=round(age_min, 1),
            )

        # ---- 2) Fallback:1h K 线 ----
        rows = _query_latest_1h(conn)
        current, h24, d7, ts = _compute_changes(rows)

        age_min = None
        stale = False
        if ts is not None:
            age_min = (now - ts).total_seconds() / 60.0
            if age_min > _STALE_THRESHOLD_KLINE_MIN:
                stale = True

        if stale or current is None:
            _try_refresh_from_coinglass(conn)
            rows = _query_latest_1h(conn)
            current, h24, d7, ts = _compute_changes(rows)
            if ts is not None:
                age_min = (now - ts).total_seconds() / 60.0
                stale = age_min > _STALE_THRESHOLD_KLINE_MIN

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
