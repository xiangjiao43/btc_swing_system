"""tests/test_coinglass_endpoints_contract.py — Sprint 1.5e CoinGlass v4 契约修复。

§Z mock _request 真返回数据,断言:
- 单交易所端点(liquidation / LSR / net_position / funding_single)variants 包含 Binance + Bybit
- 聚合端点(funding_aggregated / open_interest)variants 仅 BTC + 无 exchange
- variant 优先级:Binance 先 → Bybit 兜底
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.data.collectors.coinglass import (
    CoinglassCollector, CoinglassCollectorError,
)


def _fake_ohlc_body(value: float = 0.0001) -> dict:
    """构造 CoinGlass v4 OHLC 响应 body。"""
    return {
        "code": "0",
        "data": [
            {"time": 1714386600000, "open": value, "high": value,
             "low": value, "close": value, "value": value},
        ],
    }


def _fake_lsr_body(ratio: float = 1.5) -> dict:
    return {
        "code": "0",
        "data": [
            {"time": 1714386600000, "longAccount": 60.0,
             "shortAccount": 40.0, "longShortRatio": ratio},
        ],
    }


def _fake_liquidation_body(long_v: float, short_v: float) -> dict:
    return {
        "code": "0",
        "data": [
            {"time": 1714386600000,
             "longLiquidationUsd": long_v,
             "shortLiquidationUsd": short_v},
        ],
    }


# ============================================================
# 单交易所端点 variants 包含 Binance + Bybit
# ============================================================

def test_liquidation_first_variant_is_binance():
    """fetch_liquidation_history 首个 variant 是 (symbol=BTCUSDT, exchange=Binance)。"""
    cg = CoinglassCollector()
    captured = []

    def fake_request(method, path, params=None, **kw):
        captured.append({"path": path, "params": dict(params or {})})
        return _fake_liquidation_body(1_000_000.0, 800_000.0)

    with patch.object(cg, "_request", side_effect=fake_request):
        rows = cg.fetch_liquidation_history(interval="1h", limit=24)
    # 首次调用应是 Binance variant
    assert captured[0]["params"]["symbol"] == "BTCUSDT"
    assert captured[0]["params"]["exchange"] == "Binance"
    # 数据正确返回
    assert any(r["metric_name"] == "liquidation_total" for r in rows)


def test_liquidation_falls_back_to_bybit_on_first_failure():
    """Binance 失败 → fallback Bybit。"""
    cg = CoinglassCollector()
    captured = []

    def fake_request(method, path, params=None, **kw):
        captured.append({"path": path, "params": dict(params or {})})
        if (params or {}).get("exchange") == "Binance":
            raise CoinglassCollectorError("Binance 400")
        return _fake_liquidation_body(2_000_000.0, 1_500_000.0)

    with patch.object(cg, "_request", side_effect=fake_request):
        rows = cg.fetch_liquidation_history(interval="1h", limit=24)

    # 第 1 次:Binance 失败,第 2 次:Bybit 成功
    assert len(captured) >= 2
    assert captured[0]["params"]["exchange"] == "Binance"
    assert captured[1]["params"]["exchange"] == "Bybit"
    # 拿到 Bybit 数据
    assert any(r["metric_name"] == "liquidation_total" for r in rows)


def test_long_short_ratio_uses_btcusdt_with_exchange():
    cg = CoinglassCollector()
    captured = []

    def fake_request(method, path, params=None, **kw):
        captured.append({"path": path, "params": dict(params or {})})
        return _fake_lsr_body(2.1)

    with patch.object(cg, "_request", side_effect=fake_request):
        cg.fetch_long_short_ratio_history(interval="1h", limit=24)
    assert captured[0]["params"]["symbol"] == "BTCUSDT"
    assert captured[0]["params"]["exchange"] == "Binance"


def test_net_position_uses_btcusdt_with_exchange():
    cg = CoinglassCollector()
    captured = []

    def fake_request(method, path, params=None, **kw):
        captured.append({"path": path, "params": dict(params or {})})
        return {"code": "0", "data": []}  # empty rows OK,只验 params shape

    with patch.object(cg, "_request", side_effect=fake_request):
        cg.fetch_net_position_history(interval="1h", limit=24)
    assert captured[0]["params"]["symbol"] == "BTCUSDT"
    assert captured[0]["params"]["exchange"] == "Binance"


def test_funding_single_uses_btcusdt_with_exchange():
    cg = CoinglassCollector()
    captured = []

    def fake_request(method, path, params=None, **kw):
        captured.append({"path": path, "params": dict(params or {})})
        return _fake_ohlc_body(0.0002)

    with patch.object(cg, "_request", side_effect=fake_request):
        cg.fetch_funding_rate_history(interval="1h", limit=24)
    assert captured[0]["params"]["symbol"] == "BTCUSDT"
    assert captured[0]["params"]["exchange"] == "Binance"


# ============================================================
# 聚合端点 variants 不带 exchange
# ============================================================

def test_funding_aggregated_uses_btc_no_exchange():
    cg = CoinglassCollector()
    captured = []

    def fake_request(method, path, params=None, **kw):
        captured.append({"path": path, "params": dict(params or {})})
        return _fake_ohlc_body(0.0001)

    with patch.object(cg, "_request", side_effect=fake_request):
        cg.fetch_funding_rate_aggregated(interval="h8", limit=24)
    p = captured[0]["params"]
    assert p["symbol"] == "BTC"
    assert "exchange" not in p
    assert "exchange_list" not in p


def test_open_interest_uses_btc_no_exchange():
    cg = CoinglassCollector()
    captured = []

    def fake_request(method, path, params=None, **kw):
        captured.append({"path": path, "params": dict(params or {})})
        return _fake_ohlc_body(50_000_000_000.0)

    with patch.object(cg, "_request", side_effect=fake_request):
        cg.fetch_open_interest_history(interval="1h", limit=24)
    p = captured[0]["params"]
    assert p["symbol"] == "BTC"
    assert "exchange" not in p
