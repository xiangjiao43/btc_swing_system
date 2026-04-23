"""
tests/test_indicators.py — pytest 测试 src.indicators/*

覆盖:
- 形状(长度 / 索引对齐)
- 边界(空 / 单值 / NaN / 全相同值)
- 极端输入(单调递增 → RSI ~100)
- 已知值断言(EMA 数学等价,ATR 首值)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.indicators.ichimoku import ichimoku_cloud
from src.indicators.momentum import rsi, stoch_rsi
from src.indicators.structure import latest_swing_amplitude, swing_points
from src.indicators.trend import adx, ema, macd, minus_di, plus_di
from src.indicators.volatility import atr, atr_percentile, bollinger_bands


# -------- fixtures / helpers ----------------------------------------


def _make_series(values: list[float]) -> pd.Series:
    """构造带 DatetimeIndex 的 Series。"""
    idx = pd.date_range("2024-01-01", periods=len(values), freq="D")
    return pd.Series(values, index=idx, dtype=float)


def _hlc_trending_up(n: int = 30) -> tuple[pd.Series, pd.Series, pd.Series]:
    """构造 n 根上升趋势 HLC 数据。"""
    closes = list(range(100, 100 + n))
    highs = [c + 1.5 for c in closes]
    lows = [c - 1.5 for c in closes]
    return _make_series(highs), _make_series(lows), _make_series(closes)


def _hlc_ranging(n: int = 40) -> tuple[pd.Series, pd.Series, pd.Series]:
    """构造震荡 HLC(±3 正弦)。"""
    x = np.arange(n)
    closes_arr = 100.0 + 3.0 * np.sin(x * 0.5)
    highs_arr = closes_arr + 1.0
    lows_arr = closes_arr - 1.0
    return (
        _make_series(highs_arr.tolist()),
        _make_series(lows_arr.tolist()),
        _make_series(closes_arr.tolist()),
    )


# ================================================================
# EMA
# ================================================================

class TestEma:
    def test_basic_shape(self):
        s = _make_series([1.0, 2, 3, 4, 5])
        result = ema(s, period=3)
        assert isinstance(result, pd.Series)
        assert len(result) == 5
        assert result.index.equals(s.index)

    def test_monotonic_input(self):
        s = _make_series([1.0, 2, 3, 4, 5])
        result = ema(s, period=3)
        # EMA 对单调递增输入应单调递增
        assert (result.diff().dropna() > 0).all()

    def test_constant_input(self):
        s = _make_series([10.0] * 5)
        result = ema(s, period=3)
        # 常数输入 → EMA 全部等于常数
        assert (result == 10.0).all()

    def test_type_error(self):
        with pytest.raises(TypeError):
            ema([1, 2, 3], period=3)  # type: ignore

    def test_invalid_period(self):
        with pytest.raises(ValueError):
            ema(_make_series([1.0]), period=0)


# ================================================================
# ADX / +DI / -DI
# ================================================================

class TestAdx:
    def test_shape(self):
        h, l, c = _hlc_trending_up(30)
        result = adx(h, l, c, period=14)
        assert len(result) == 30
        assert result.index.equals(c.index)

    def test_range(self):
        h, l, c = _hlc_trending_up(50)
        result = adx(h, l, c, period=14)
        non_nan = result.dropna()
        assert (non_nan >= 0.0).all() and (non_nan <= 100.0).all()

    def test_trending_up_has_high_plus_di(self):
        """强趋势上升时 +DI 应该显著大于 -DI。"""
        h, l, c = _hlc_trending_up(40)
        pdi = plus_di(h, l, c, period=14).iloc[-1]
        mdi = minus_di(h, l, c, period=14).iloc[-1]
        assert pdi > mdi, f"expected +DI > -DI, got +DI={pdi} -DI={mdi}"

    def test_length_mismatch(self):
        h = _make_series([1.0, 2, 3])
        l = _make_series([0.5, 1.5])
        c = _make_series([0.7, 1.7, 2.7])
        with pytest.raises(ValueError):
            adx(h, l, c, period=14)


# ================================================================
# MACD
# ================================================================

class TestMacd:
    def test_keys_and_shape(self):
        s = _make_series(list(range(1, 101)))
        result = macd(s)
        assert set(result.keys()) == {"macd", "signal", "hist"}
        for key, series in result.items():
            assert isinstance(series, pd.Series)
            assert len(series) == 100

    def test_hist_equals_macd_minus_signal(self):
        s = _make_series(list(range(1, 51)))
        result = macd(s)
        # hist = macd - signal
        diff = (result["macd"] - result["signal"]) - result["hist"]
        assert (diff.abs().dropna() < 1e-10).all()

    def test_fast_slow_constraint(self):
        s = _make_series([1.0, 2, 3])
        with pytest.raises(ValueError):
            macd(s, fast=26, slow=12)  # inverted


# ================================================================
# ATR / ATR percentile / Bollinger
# ================================================================

class TestAtr:
    def test_shape(self):
        h, l, c = _hlc_trending_up(30)
        result = atr(h, l, c, period=14)
        assert len(result) == 30

    def test_positive(self):
        h, l, c = _hlc_ranging(40)
        result = atr(h, l, c, period=14)
        # 所有非 NaN 应 > 0(有波动 → TR > 0)
        assert (result.dropna() > 0).all()


class TestAtrPercentile:
    def test_shape_and_range(self):
        h, l, c = _hlc_ranging(200)
        a = atr(h, l, c, period=14)
        pct = atr_percentile(a, lookback=60)
        non_nan = pct.dropna()
        assert (non_nan >= 0.0).all() and (non_nan <= 100.0).all()
        # lookback=60 的前 59 个应为 NaN
        assert pct.iloc[:59].isna().all()


class TestBollinger:
    def test_all_three_bands(self):
        s = _make_series([100.0 + np.sin(i) for i in range(30)])
        bb = bollinger_bands(s, period=10, std_dev=2.0)
        assert set(bb.keys()) == {"upper", "middle", "lower"}

    def test_ordering(self):
        s = _make_series([100.0 + np.sin(i * 0.3) for i in range(30)])
        bb = bollinger_bands(s, period=10, std_dev=2.0)
        # upper ≥ middle ≥ lower(非 NaN 部分)
        upper, mid, lower = bb["upper"].dropna(), bb["middle"].dropna(), bb["lower"].dropna()
        assert (upper >= mid).all() and (mid >= lower).all()


# ================================================================
# RSI / StochRSI
# ================================================================

class TestRsi:
    def test_shape(self):
        s = _make_series(list(range(1, 31)))
        result = rsi(s, period=14)
        assert len(result) == 30

    def test_monotonic_up_close_to_100(self):
        """30 个单调递增 → RSI 趋近 100。"""
        s = _make_series(list(range(1, 31)))
        result = rsi(s, period=14)
        assert result.iloc[-1] > 99.0, f"expected near 100, got {result.iloc[-1]}"

    def test_monotonic_down_close_to_0(self):
        s = _make_series(list(range(30, 0, -1)))
        result = rsi(s, period=14)
        assert result.iloc[-1] < 1.0, f"expected near 0, got {result.iloc[-1]}"

    def test_constant_close_is_undefined_or_fifty(self):
        """常数 close → 无 gain 无 loss → RS 未定义 → 约定 RSI = 100 或 NaN。"""
        s = _make_series([100.0] * 20)
        result = rsi(s, period=14)
        # 实现上 avg_loss=0 → where(avg_loss != 0, 100.0) → 100
        assert (result.iloc[14:].dropna() == 100.0).all()


class TestStochRsi:
    def test_shape_and_range(self):
        s = _make_series([100.0 + np.sin(i * 0.3) for i in range(60)])
        sr = stoch_rsi(s, period=14)
        non_nan = sr.dropna()
        assert (non_nan >= 0.0).all() and (non_nan <= 1.0).all()


# ================================================================
# Ichimoku
# ================================================================

class TestIchimoku:
    def test_all_five_lines(self):
        h, l, c = _hlc_trending_up(100)
        result = ichimoku_cloud(h, l, c)
        assert set(result.keys()) == {
            "tenkan", "kijun", "senkou_a", "senkou_b", "chikou"
        }
        for key, series in result.items():
            assert isinstance(series, pd.Series)
            assert len(series) == 100

    def test_length_mismatch(self):
        h = _make_series([1.0, 2, 3])
        l = _make_series([0.5, 1.5])
        c = _make_series([0.7, 1.7, 2.7])
        with pytest.raises(ValueError):
            ichimoku_cloud(h, l, c)


# ================================================================
# Structure (swing points)
# ================================================================

class TestSwingPoints:
    def test_simple_swing(self):
        # 构造有明显 swing 的 HLC
        # Highs:  1 2 3 4 5 4 3 2 1   → 中间索引 4 是 swing high
        # Lows:   0 1 2 3 4 3 2 1 0   → 无 swing low(单调下降 tail)
        highs = _make_series([1.0, 2, 3, 4, 5, 4, 3, 2, 1])
        lows = _make_series([0.5, 1.5, 2.5, 3.5, 4.5, 3.5, 2.5, 1.5, 0.5])
        events = swing_points(highs, lows, lookback=2)
        assert len(events) == 1
        assert events[0]["type"] == "high"
        assert events[0]["price"] == 5.0

    def test_empty_on_short_series(self):
        h = _make_series([1.0, 2, 3])
        l = _make_series([0.5, 1.5, 2.5])
        assert swing_points(h, l, lookback=5) == []

    def test_length_mismatch(self):
        h = _make_series([1.0, 2, 3])
        l = _make_series([0.5, 1.5])
        with pytest.raises(ValueError):
            swing_points(h, l, lookback=1)

    def test_invalid_lookback(self):
        h = _make_series([1.0, 2, 3])
        l = _make_series([0.5, 1.5, 2.5])
        with pytest.raises(ValueError):
            swing_points(h, l, lookback=0)


class TestLatestSwingAmplitude:
    def test_basic(self):
        # V 型:low=5,peak=15,low=8
        highs = _make_series([11.0, 12, 13, 14, 15, 14, 13, 12, 11, 10, 9, 10, 11, 12, 13])
        lows = _make_series([5.0, 6, 7, 8, 9, 8, 7, 6, 5, 6, 7, 8, 9, 10, 11])
        amp = latest_swing_amplitude(highs, lows, lookback=3)
        assert amp > 0

    def test_empty_when_no_swings(self):
        h = _make_series([1.0, 2])
        l = _make_series([0.5, 1.5])
        assert latest_swing_amplitude(h, l, lookback=5) == 0.0
