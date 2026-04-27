"""tests/test_macro_btc_nasdaq_corr_card.py — Sprint 2.6-M B1。

Sprint 2.6-K 调研发现:macro_btc_nasdaq_corr_60d 卡 hardcode current_value=None。
代码注释写"由宏观逆风指数计算",但 emitter 实际没读 composite 数据,也没像同
sprint 2.6-F 黄金卡那样从 macro+klines 算。

修法:与 BTC-黄金卡同模板(_compute_corr_60d 加 nasdaq 即可)。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.strategy.factor_card_emitter import _emit_macro_reference


def _make_klines(n=120):
    rng = pd.date_range("2025-01-01", periods=n, freq="D")
    base = 50000 + np.cumsum(np.linspace(50, 100, n))
    return pd.DataFrame({
        "open": base, "high": base, "low": base, "close": base,
        "volume": np.zeros(n),
    }, index=rng)


def test_btc_nasdaq_corr_card_filled_when_data_present():
    klines_1d = _make_klines(120)
    nasdaq = klines_1d["close"] * 0.95  # tight correlation

    cards = _emit_macro_reference({"nasdaq": nasdaq}, "20260427", klines_1d=klines_1d)
    nas_card = next(c for c in cards if "btc_nasdaq_corr" in c["card_id"])
    assert nas_card["current_value"] is not None
    assert nas_card["current_value"] > 0.95
    assert nas_card["impact_direction"] == "bullish"


def test_btc_nasdaq_corr_card_inverse_correlation_bearish():
    """合成强负相关:btc 上涨日 nasdaq 下跌,反之亦然 → pct_change 序列负相关。"""
    rng = pd.date_range("2025-01-01", periods=120, freq="D")
    rs = np.random.RandomState(7)
    btc_rets = rs.randn(120) * 0.01
    btc_close = pd.Series(50000 * np.cumprod(1 + btc_rets), index=rng)
    nasdaq_rets = -btc_rets  # 完全反向
    nasdaq = pd.Series(15000 * np.cumprod(1 + nasdaq_rets), index=rng)
    klines_1d = pd.DataFrame({
        "open": btc_close, "high": btc_close, "low": btc_close,
        "close": btc_close, "volume": np.zeros(120),
    }, index=rng)

    cards = _emit_macro_reference({"nasdaq": nasdaq}, "20260427", klines_1d=klines_1d)
    nas_card = next(c for c in cards if "btc_nasdaq_corr" in c["card_id"])
    assert nas_card["current_value"] is not None
    assert nas_card["current_value"] < -0.9, nas_card["current_value"]
    assert nas_card["impact_direction"] == "bearish"


def test_btc_nasdaq_corr_card_uncorrelated_neutral():
    klines_1d = _make_klines(120)
    rng_state = np.random.RandomState(42)
    nasdaq = pd.Series(rng_state.randn(120).cumsum() + 15000, index=klines_1d.index)

    cards = _emit_macro_reference({"nasdaq": nasdaq}, "20260427", klines_1d=klines_1d)
    nas_card = next(c for c in cards if "btc_nasdaq_corr" in c["card_id"])
    # 弱相关 → neutral 区间
    assert nas_card["impact_direction"] == "neutral"


def test_btc_nasdaq_corr_card_falls_back_when_data_missing():
    """无 nasdaq 数据 → current_value=None,但卡仍生成,文案说"数据不足"。"""
    klines_1d = _make_klines(120)
    cards = _emit_macro_reference({}, "20260427", klines_1d=klines_1d)
    nas_card = next(c for c in cards if "btc_nasdaq_corr" in c["card_id"])
    assert nas_card["current_value"] is None
    assert "数据不足" in nas_card["plain_interpretation"]


def test_btc_nasdaq_corr_card_falls_back_when_klines_missing():
    """无 klines → 同样降级。"""
    rng = pd.date_range("2025-01-01", periods=120, freq="D")
    nasdaq = pd.Series(np.linspace(15000, 16000, 120), index=rng)
    cards = _emit_macro_reference({"nasdaq": nasdaq}, "20260427", klines_1d=None)
    nas_card = next(c for c in cards if "btc_nasdaq_corr" in c["card_id"])
    assert nas_card["current_value"] is None
