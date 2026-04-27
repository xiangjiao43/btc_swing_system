"""tests/test_coinglass_funding_aggregated.py — Sprint 2.6-F Commit 2。

CoinglassCollector.fetch_funding_rate_aggregated 必须:
- 命中 _PATH_FUNDING_AGG endpoint
- 解析 OHLC close 为 metric_value
- metric_name = 'funding_rate_aggregated'
- 注册在 collect_and_save_all 的 derivatives_tasks 列表
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

from src.data.collectors.coinglass import CoinglassCollector


def _make_collector_with_fake_request(rows: list[dict]) -> CoinglassCollector:
    cg = CoinglassCollector.__new__(CoinglassCollector)
    cg._request = MagicMock(return_value={"data": rows})  # type: ignore[attr-defined]
    cg._unwrap_data = lambda body: body.get("data") or []  # type: ignore[attr-defined]
    return cg


def test_fetch_funding_rate_aggregated_parses_ohlc_close():
    rows = [
        {"t": "1714000000", "o": 0.0001, "h": 0.0002, "l": 0.00005, "c": 0.00015},
        {"t": "1714086400", "o": 0.00015, "h": 0.0003, "l": 0.0001, "c": 0.00020},
    ]
    cg = _make_collector_with_fake_request(rows)

    result = cg.fetch_funding_rate_aggregated(interval="h8", limit=2)

    assert len(result) == 2
    for item in result:
        assert item["metric_name"] == "funding_rate_aggregated"
        assert isinstance(item["metric_value"], (int, float))
        assert "timestamp" in item


def test_fetch_funding_rate_aggregated_uses_oi_weight_path():
    """endpoint 必须是 oi-weight-history,不是普通的 funding-rate/history。"""
    cg = _make_collector_with_fake_request([])
    cg.fetch_funding_rate_aggregated()
    cg._request.assert_called_once()  # type: ignore[attr-defined]
    call_args = cg._request.call_args  # type: ignore[attr-defined]
    method, path = call_args.args[0], call_args.args[1]
    assert method == "GET"
    assert "oi-weight-history" in path
    assert "funding-rate" in path


def test_fetch_funding_rate_aggregated_does_not_send_exchange_param():
    """聚合端点不传 exchange(symbol=BTC 隐含跨所聚合)。"""
    cg = _make_collector_with_fake_request([])
    cg.fetch_funding_rate_aggregated()
    params = cg._request.call_args.kwargs["params"]  # type: ignore[attr-defined]
    assert "exchange" not in params
    assert params["symbol"] == "BTC"


def test_collect_and_save_all_registers_funding_rate_aggregated():
    """source-level guard:funding_rate_aggregated 必须在 derivatives_tasks 列表里。"""
    src = inspect.getsource(CoinglassCollector.collect_and_save_all)
    assert '"funding_rate_aggregated"' in src, (
        "collect_and_save_all must register funding_rate_aggregated label"
    )
    assert "fetch_funding_rate_aggregated" in src, (
        "collect_and_save_all must invoke fetch_funding_rate_aggregated"
    )
