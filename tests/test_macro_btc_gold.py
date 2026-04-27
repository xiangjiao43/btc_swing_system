"""tests/test_macro_btc_gold.py — Sprint 2.6-F Commit 3。

覆盖:
1. FRED SERIES_TO_METRIC 含 GOLDPMGBD228NLBM → gold_price
2. _compute_corr_60d:对齐 BTC 收盘价与 macro series 的 pct_change → Pearson
3. _emit_macro_reference 在有 gold + klines 时填 current_value(≠ None)
4. 数据不足时回退 None,不抛异常
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.data.collectors.fred import SERIES_TO_METRIC
from src.strategy.factor_card_emitter import (
    _compute_corr_60d,
    _emit_macro_reference,
)


def test_fred_series_includes_gold():
    assert "GOLDPMGBD228NLBM" in SERIES_TO_METRIC
    assert SERIES_TO_METRIC["GOLDPMGBD228NLBM"] == "gold_price"


def test_compute_corr_60d_returns_high_when_synthetic_correlated():
    rng = pd.date_range("2026-01-01", periods=100, freq="D")
    btc = pd.Series(np.cumprod(1 + np.linspace(0.001, 0.01, 100)) * 50000, index=rng)
    # gold = btc * 1.01 (essentially same returns) → corr ≈ 1
    gold = btc * 1.01

    df = pd.DataFrame({"close": btc})
    corr = _compute_corr_60d(df, gold)
    assert corr is not None
    assert corr > 0.99


def test_compute_corr_60d_returns_low_when_uncorrelated():
    rng = pd.date_range("2026-01-01", periods=100, freq="D")
    rng_state = np.random.RandomState(42)
    btc = pd.Series(rng_state.randn(100).cumsum() + 50000, index=rng)
    gold = pd.Series(rng_state.randn(100).cumsum() + 2000, index=rng)
    df = pd.DataFrame({"close": btc})
    corr = _compute_corr_60d(df, gold)
    assert corr is not None
    assert -0.4 < corr < 0.4  # uncorrelated


def test_compute_corr_60d_returns_none_when_insufficient():
    rng = pd.date_range("2026-01-01", periods=10, freq="D")
    btc = pd.Series(range(10), index=rng, dtype=float)
    gold = pd.Series(range(10), index=rng, dtype=float)
    df = pd.DataFrame({"close": btc})
    assert _compute_corr_60d(df, gold) is None


def test_compute_corr_60d_handles_missing_inputs():
    assert _compute_corr_60d(None, None) is None
    assert _compute_corr_60d(pd.DataFrame({"close": [1, 2]}), None) is None
    assert _compute_corr_60d(None, pd.Series([1, 2])) is None


def test_emit_macro_reference_fills_btc_gold_card_with_value():
    rng = pd.date_range("2026-01-01", periods=100, freq="D")
    btc = pd.Series(np.cumprod(1 + np.linspace(0.001, 0.005, 100)) * 50000, index=rng)
    gold = btc * 1.01  # high correlation
    df = pd.DataFrame({"close": btc, "open": btc, "high": btc, "low": btc, "volume": 0.0})
    macro = {"gold_price": gold}

    cards = _emit_macro_reference(macro, "2026-04-27", klines_1d=df)
    gold_cards = [c for c in cards if "btc_gold_corr_60d" in c.get("card_id", "")]
    assert len(gold_cards) == 1
    assert gold_cards[0]["current_value"] is not None
    assert isinstance(gold_cards[0]["current_value"], float)


def test_emit_macro_reference_no_klines_falls_back_to_none():
    """无 klines 也不该抛 — 卡仍生成,current_value=None。"""
    cards = _emit_macro_reference({"gold_price": pd.Series([2000, 2010])},
                                  "2026-04-27", klines_1d=None)
    gold_cards = [c for c in cards if "btc_gold_corr_60d" in c.get("card_id", "")]
    assert len(gold_cards) == 1
    assert gold_cards[0]["current_value"] is None
