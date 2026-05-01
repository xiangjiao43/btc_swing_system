"""tests/test_market_route_spot_priority.py — Sprint 1.5k Task B。

/api/market/btc-price 优先 现货 1m,失败 fallback 到 1h K 线。
- spot 成功 → source="binance_spot_1m_via_coinglass", price=spot close, age<2
- spot 失败 → source="binance_kline_1h_close_via_coinglass"
- spot 时间 > 2 分钟 → stale=True
- 24h/7d 变化率始终来自 1h K 线(spot 路径下也用 K 线算)
"""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.data.storage.connection import get_connection, init_db
from src.data.storage.dao import BTCKlinesDAO, KlineRow


@pytest.fixture
def db_path() -> Path:
    tmp = Path(tempfile.mkdtemp()) / "market.db"
    init_db(db_path=tmp, verbose=False)
    return tmp


@pytest.fixture
def client(db_path: Path) -> TestClient:
    app = create_app(conn_factory=lambda: get_connection(db_path))
    return TestClient(app)


def _seed_klines_25h(db_path: Path, base_price: float = 70000.0) -> None:
    """种入 25 根 1h K 线(足够算 24h 变化:0..24,共 25 条)。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        klines = []
        # 25 根:24 小时前 close=70000,当前小时 close=72100(=+3% 变化)
        for h in range(25):
            close = base_price + h * (2100 / 24)  # 线性增长
            ts = f"2026-04-30T{h:02d}:00:00Z" if h < 24 else "2026-05-01T00:00:00Z"
            klines.append(KlineRow(
                timeframe="1h", timestamp=ts,
                open=close, high=close, low=close, close=close,
                volume_btc=1.0,
            ))
        BTCKlinesDAO.upsert_klines(conn, klines)
        conn.commit()
    finally:
        conn.close()


# ============================================================
# Spot 主路径
# ============================================================

def test_spot_success_uses_realtime(client: TestClient, db_path: Path):
    """spot 成功 → source 含 binance_spot,price 来自 spot close,age < 2。"""
    _seed_klines_25h(db_path)
    now = datetime.now(timezone.utc)
    spot_ts = now.strftime("%Y-%m-%dT%H:%M:00Z")  # 当前分钟
    spot_rows = [
        {"timestamp": spot_ts, "open": 76200.0, "high": 76400.0,
         "low": 76100.0, "close": 76300.50, "volume_usd": 1000.0,
         "volume_btc": 0.013},
    ]
    with patch(
        "src.data.collectors.coinglass.CoinglassCollector.fetch_spot_price_history",
        return_value=spot_rows,
    ):
        r = client.get("/api/market/btc-price")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "binance_spot_1m_via_coinglass"
    assert body["price"] == 76300.50
    assert body["age_minutes"] is not None
    assert body["age_minutes"] < 2.0
    assert body["stale"] is False


def test_spot_stale_threshold_2min(client: TestClient, db_path: Path):
    """spot 时间 = 当前 - 3 分钟 → stale=True(2 分钟阈值)。"""
    _seed_klines_25h(db_path)
    now = datetime.now(timezone.utc)
    # 3 分钟前
    spot_ts = now.replace(second=0, microsecond=0).timestamp() - 180
    spot_iso = datetime.fromtimestamp(spot_ts, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:00Z"
    )
    spot_rows = [{
        "timestamp": spot_iso,
        "open": 76300.0, "high": 76400.0, "low": 76200.0,
        "close": 76300.50, "volume_usd": 1000.0, "volume_btc": 0.013,
    }]
    with patch(
        "src.data.collectors.coinglass.CoinglassCollector.fetch_spot_price_history",
        return_value=spot_rows,
    ):
        r = client.get("/api/market/btc-price")
    body = r.json()
    assert body["source"] == "binance_spot_1m_via_coinglass"
    assert body["age_minutes"] >= 2.0
    assert body["stale"] is True


def test_24h_change_uses_kline_even_in_spot_path(
    client: TestClient, db_path: Path,
):
    """关键反退化:price 来自 spot,但 24h 变化必须来自 1h K 线
    (spot 不存历史,变化率独立计算路径)。"""
    _seed_klines_25h(db_path)  # 25 根线性增长 → +3% 24h
    now = datetime.now(timezone.utc)
    spot_ts = now.strftime("%Y-%m-%dT%H:%M:00Z")
    spot_rows = [{
        "timestamp": spot_ts,
        "open": 76200.0, "high": 76400.0, "low": 76100.0,
        "close": 99999.99,  # spot 价跟 K 线值故意不同,验证两源独立
        "volume_usd": 1000.0, "volume_btc": 0.013,
    }]
    with patch(
        "src.data.collectors.coinglass.CoinglassCollector.fetch_spot_price_history",
        return_value=spot_rows,
    ):
        r = client.get("/api/market/btc-price")
    body = r.json()
    # price 来自 spot,不是 K 线
    assert body["price"] == 99999.99
    # 24h 变化来自 K 线(0 → 24,close 从 70000 → 72100,涨 3%)
    assert body["price_24h_change_pct"] is not None
    assert abs(body["price_24h_change_pct"] - 3.0) < 0.1


# ============================================================
# Fallback 路径
# ============================================================

def test_spot_fail_falls_back_to_kline(client: TestClient, db_path: Path):
    """spot fetch 返回空 → fallback 到 K 线路径,source 含 kline_1h。

    Sprint 1.8.1.2:同时 mock _try_refresh_from_coinglass。原因:测试种入
    K 线最后一根 ts=2026-05-01T00:00:00Z(写测试时是"今天"),age 超过
    30 分钟阈值后会触发 endpoint 的 _try_refresh_from_coinglass(),如生产
    环境有 CoinGlass API key,会真请求并把 seeded 70000-72100 覆盖成实时价。
    Mac 本地无 key → silent skip → 测试碰巧 PASS;
    生产 Ubuntu 服务器有 key → 真覆盖 → 断言 fail。
    本次 patch 让 refresh 无操作,环境无关。
    """
    _seed_klines_25h(db_path)
    with patch(
        "src.data.collectors.coinglass.CoinglassCollector.fetch_spot_price_history",
        return_value=[],
    ), patch(
        "src.api.routes.market._try_refresh_from_coinglass",
        return_value=None,
    ):
        r = client.get("/api/market/btc-price")
    body = r.json()
    assert body["source"] == "binance_kline_1h_close_via_coinglass"
    # K 线最后一根的 close = 72100
    assert body["price"] is not None
    assert abs(body["price"] - 72100.0) < 0.1


def test_spot_exception_falls_back_to_kline(client: TestClient, db_path: Path):
    """spot fetch 抛异常 → fallback,不让 endpoint 崩溃。

    Sprint 1.8.1.2:同样 mock _try_refresh_from_coinglass(同 reasoning)。
    """
    _seed_klines_25h(db_path)
    with patch(
        "src.data.collectors.coinglass.CoinglassCollector.fetch_spot_price_history",
        side_effect=RuntimeError("network down"),
    ), patch(
        "src.api.routes.market._try_refresh_from_coinglass",
        return_value=None,
    ):
        r = client.get("/api/market/btc-price")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "binance_kline_1h_close_via_coinglass"


# ============================================================
# Schema 不变
# ============================================================

def test_spot_path_uses_limit_10(client: TestClient, db_path: Path):
    """Sprint 1.5k.1 反退化:_try_fetch_spot_1m 调 fetch_spot_price_history
    时必须 limit=10(spec 校验,防 alphanode 小批量限流)。"""
    _seed_klines_25h(db_path)
    now = datetime.now(timezone.utc)
    spot_rows = [{
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:00Z"),
        "open": 76200.0, "high": 76400.0, "low": 76100.0,
        "close": 76300.50, "volume_usd": 1000.0, "volume_btc": 0.013,
    }]
    with patch(
        "src.data.collectors.coinglass.CoinglassCollector.fetch_spot_price_history",
        return_value=spot_rows,
    ) as mock_spot:
        client.get("/api/market/btc-price")
    assert mock_spot.called
    # 关键 spec:limit=10(不是 2)
    kwargs = mock_spot.call_args.kwargs
    assert kwargs.get("limit") == 10, (
        f"_try_fetch_spot_1m must pass limit=10, got {kwargs.get('limit')} — "
        "1.5k.1 防退回 limit=2"
    )
    assert kwargs.get("interval") == "1m"


def test_response_schema_unchanged(client: TestClient, db_path: Path):
    """BtcPriceResponse 字段未删未改名(只是 source 多了一种枚举值)。"""
    _seed_klines_25h(db_path)
    now = datetime.now(timezone.utc)
    spot_rows = [{
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:00Z"),
        "open": 76200.0, "high": 76400.0, "low": 76100.0,
        "close": 76300.50, "volume_usd": 1000.0, "volume_btc": 0.013,
    }]
    with patch(
        "src.data.collectors.coinglass.CoinglassCollector.fetch_spot_price_history",
        return_value=spot_rows,
    ):
        r = client.get("/api/market/btc-price")
    body = r.json()
    expected_keys = {
        "price", "price_24h_change_pct", "price_7d_change_pct",
        "captured_at_utc", "captured_at_bjt", "source", "stale", "age_minutes",
    }
    assert set(body.keys()) == expected_keys
