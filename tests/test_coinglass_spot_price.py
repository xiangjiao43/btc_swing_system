"""tests/test_coinglass_spot_price.py — Sprint 1.5k Task A。

CoinglassCollector.fetch_spot_price_history 必须:
- 命中 _PATH_SPOT_PRICE endpoint
- 解析 ms epoch time → ISO UTC timestamp
- 字符串数值 → float (open/high/low/close/volume_usd)
- 失败抛 CoinglassCollectorError(由调用方捕获)
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.data.collectors.coinglass import (
    CoinglassCollector, CoinglassCollectorError,
)


def _make_collector_with_fake_request(body: object) -> CoinglassCollector:
    cg = CoinglassCollector.__new__(CoinglassCollector)
    cg._request = MagicMock(return_value=body)  # type: ignore[attr-defined]
    return cg


# ============================================================
# 成功路径
# ============================================================

def test_fetch_spot_price_history_success():
    """实测端点真返回值:{"code":"0","data":[{"time":<ms>,"open":...,"close":...}]}"""
    # 2025-04-30 05:34:00 UTC = 1745991240000 ms
    # 2025-04-30 05:35:00 UTC = 1745991300000 ms
    body = {
        "code": "0",
        "data": [
            {
                "time": 1745991240000,
                "open": "76300.50", "high": "76400.00",
                "low": "76250.00", "close": "76359.07",
                "volume_usd": "1234567.89",
            },
            {
                "time": 1745991300000,
                "open": "76359.07", "high": "76380.00",
                "low": "76340.00", "close": "76370.50",
                "volume_usd": "987654.32",
            },
        ],
    }
    cg = _make_collector_with_fake_request(body)
    result = cg.fetch_spot_price_history(
        symbol="BTCUSDT", exchange="Binance", interval="1m", limit=2,
    )
    assert len(result) == 2
    # 末行 close 是顶栏要用的现价
    assert result[-1]["close"] == 76370.50
    assert result[-1]["open"] == 76359.07
    assert result[-1]["high"] == 76380.00
    assert result[-1]["low"] == 76340.00
    # timestamp 必须是 ISO UTC 字符串(Z 后缀)
    assert isinstance(result[-1]["timestamp"], str)
    assert result[-1]["timestamp"].endswith("Z")
    assert result[-1]["timestamp"] == "2025-04-30T05:35:00Z"
    assert result[-1]["volume_usd"] == 987654.32


def test_fetch_spot_price_hits_correct_endpoint():
    """端点路径必须含 spot/price/history(不能误用 futures)。"""
    body = {"code": "0", "data": []}
    cg = _make_collector_with_fake_request(body)
    cg.fetch_spot_price_history()
    call_args = cg._request.call_args
    path = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs.get("path")
    assert "spot/price/history" in path
    assert "futures" not in path


def test_fetch_spot_price_passes_correct_params():
    body = {"code": "0", "data": []}
    cg = _make_collector_with_fake_request(body)
    cg.fetch_spot_price_history(
        symbol="BTCUSDT", exchange="Binance", interval="1m", limit=10,
    )
    params = cg._request.call_args.kwargs["params"]
    assert params["symbol"] == "BTCUSDT"
    assert params["exchange"] == "Binance"
    assert params["interval"] == "1m"
    assert params["limit"] == 10


def test_fetch_default_limit_is_10():
    """Sprint 1.5k.1 反退化:默认 limit 必须是 10 防 alphanode 小批量限流
    (limit=2 在 30s 轮询下生产 SSH 验证大部分返回 data=[])。"""
    body = {"code": "0", "data": []}
    cg = _make_collector_with_fake_request(body)
    cg.fetch_spot_price_history()  # 不显式传 limit
    params = cg._request.call_args.kwargs["params"]
    assert params["limit"] == 10, (
        f"default limit should be 10, got {params['limit']} — "
        "1.5k.1 防退回 limit=2"
    )


# ============================================================
# 失败路径(由调用方决定 fallback)
# ============================================================

def test_fetch_spot_price_returns_empty_on_empty_data():
    body = {"code": "0", "data": []}
    cg = _make_collector_with_fake_request(body)
    assert cg.fetch_spot_price_history() == []


def test_fetch_spot_price_raises_on_api_error_code():
    """code != "0" → _unwrap_data 抛 CoinglassCollectorError(同其他端点)。"""
    body = {"code": "40001", "msg": "Invalid API key"}
    cg = _make_collector_with_fake_request(body)
    with pytest.raises(CoinglassCollectorError):
        cg.fetch_spot_price_history()


def test_fetch_spot_price_skips_malformed_row():
    """部分行字段不全 → 跳过该行,不让整批失败。"""
    body = {
        "code": "0",
        "data": [
            {
                "time": 1745991240000,
                "open": "76300.50", "high": "76400.00",
                "low": "76250.00", "close": "76359.07",
                "volume_usd": "1000.0",
            },
            {"garbage": "no time field"},  # 异常行
        ],
    }
    cg = _make_collector_with_fake_request(body)
    result = cg.fetch_spot_price_history()
    assert len(result) == 1
    assert result[0]["close"] == 76359.07
