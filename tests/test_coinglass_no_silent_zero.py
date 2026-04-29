"""tests/test_coinglass_no_silent_zero.py — Sprint 1.5e 静默 0 修复反退化。

§Z 老 bug:`(long_val or 0.0) + (short_val or 0.0)` 单边 None 时把 total 写
成另一侧值,污染 DB 历史分位计算。修复后:仅当两边都拿到真值才 emit total。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.data.collectors.coinglass import CoinglassCollector


def _liq_body_partial(long_v=None, short_v=None) -> dict:
    """构造单边 None 的 liquidation 响应。"""
    row = {"time": 1714386600000}
    if long_v is not None:
        row["longLiquidationUsd"] = long_v
    if short_v is not None:
        row["shortLiquidationUsd"] = short_v
    return {"code": "0", "data": [row]}


def test_partial_long_only_no_total_emitted():
    """只拿到 long_val 没 short_val → 只 emit liquidation_long,不 emit total。"""
    cg = CoinglassCollector()
    with patch.object(cg, "_request",
                       return_value=_liq_body_partial(long_v=1_500_000.0)):
        rows = cg.fetch_liquidation_history(interval="1h", limit=24)
    metric_names = [r["metric_name"] for r in rows]
    assert "liquidation_long" in metric_names
    assert "liquidation_short" not in metric_names
    # **关键反退化**:total 不能被 emit(否则 = long 单值会被当 total 写入 DB)
    assert "liquidation_total" not in metric_names


def test_partial_short_only_no_total_emitted():
    cg = CoinglassCollector()
    with patch.object(cg, "_request",
                       return_value=_liq_body_partial(short_v=900_000.0)):
        rows = cg.fetch_liquidation_history(interval="1h", limit=24)
    metric_names = [r["metric_name"] for r in rows]
    assert "liquidation_short" in metric_names
    assert "liquidation_long" not in metric_names
    assert "liquidation_total" not in metric_names


def test_both_values_present_total_correct():
    cg = CoinglassCollector()
    body = _liq_body_partial(long_v=1_500_000.0, short_v=800_000.0)
    with patch.object(cg, "_request", return_value=body):
        rows = cg.fetch_liquidation_history(interval="1h", limit=24)
    by_name = {r["metric_name"]: r["metric_value"] for r in rows}
    assert by_name["liquidation_long"] == 1_500_000.0
    assert by_name["liquidation_short"] == 800_000.0
    assert by_name["liquidation_total"] == 2_300_000.0


def test_all_variants_fail_returns_empty_no_zeros():
    """所有 variant 都失败 → 不写任何 0 到 DB,raise(被 collector 上游 try 捕获)。"""
    cg = CoinglassCollector()
    with patch.object(cg, "_request",
                       side_effect=RuntimeError("全 variant 400")):
        with pytest.raises(RuntimeError):
            cg.fetch_liquidation_history(interval="1h", limit=24)


def test_no_zeros_in_emitted_when_both_none():
    """单 row 两侧都 None → 跳过整 row,不 emit 任何 metric。"""
    cg = CoinglassCollector()
    body = _liq_body_partial()  # long & short both missing
    with patch.object(cg, "_request", return_value=body):
        rows = cg.fetch_liquidation_history(interval="1h", limit=24)
    assert rows == []
