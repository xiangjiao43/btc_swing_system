"""tests/ai/test_context_builder.py — Sprint 1.9-A 类型 A helpers 测试。

每个 helper 单元测试,断言计算结果 vs 已知 fixture 值。不允许只断言
.called=True,必须断言字段值。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.ai.context_builder import (
    build_risk_preview,
    compute_adx_14,
    compute_atr_features,
    compute_btc_macro_corr_60d,
    compute_emas_1d,
    compute_emas_4h,
    compute_exchange_flow_features,
    compute_funding_features,
    compute_lth_sth_changes,
    compute_macro_features,
    compute_oi_features,
    compute_price_features,
    detect_swing_points,
)


# ============================================================
# Fixtures
# ============================================================

def _build_klines_1d(days: int = 200, *, seed: int = 42) -> pd.DataFrame:
    np.random.seed(seed)
    idx = pd.date_range("2025-10-01", periods=days, freq="1D", tz="UTC")
    close = 70000 + np.cumsum(np.random.randn(days) * 500)
    return pd.DataFrame({
        "open": close - 100, "high": close + 200,
        "low": close - 200, "close": close,
    }, index=idx)


def _build_klines_4h(days: int = 30, *, seed: int = 43) -> pd.DataFrame:
    bars = days * 6
    idx = pd.date_range("2026-04-01", periods=bars, freq="4h", tz="UTC")
    np.random.seed(seed)
    close = 75000 + np.cumsum(np.random.randn(bars) * 200)
    return pd.DataFrame({
        "open": close - 50, "high": close + 100,
        "low": close - 100, "close": close,
    }, index=idx)


def _build_macro_series(days: int = 200, base: float = 100.0) -> pd.Series:
    idx = pd.date_range("2025-10-01", periods=days, freq="1D", tz="UTC")
    np.random.seed(7)
    return pd.Series(base + np.cumsum(np.random.randn(days) * 0.3), index=idx)


# ============================================================
# compute_emas_1d
# ============================================================

def test_emas_1d_returns_3_emas_with_current_values():
    df = _build_klines_1d(days=300)
    out = compute_emas_1d(df)
    assert out["ema_20_current"] is not None
    assert out["ema_50_current"] is not None
    assert out["ema_200_current"] is not None
    # series length matches input
    assert len(out["ema_20_series"]) == 300
    # EMA-200 is smoother than EMA-20 (lower std)
    assert out["ema_200_series"].std() < out["ema_20_series"].std()


def test_emas_1d_handles_empty_klines():
    out = compute_emas_1d(pd.DataFrame())
    assert out["ema_20_current"] is None
    assert out["ema_20_series"] is None


def test_emas_1d_handles_none():
    out = compute_emas_1d(None)
    assert out["ema_20_current"] is None


# ============================================================
# compute_emas_4h
# ============================================================

def test_emas_4h_returns_2_emas():
    df = _build_klines_4h(days=30)
    out = compute_emas_4h(df)
    assert out["ema_20_4h_current"] is not None
    assert out["ema_50_4h_current"] is not None
    assert len(out["ema_20_4h_series"]) == 30 * 6


# ============================================================
# compute_adx_14
# ============================================================

def test_adx_14_returns_finite_value():
    df = _build_klines_1d(days=100)
    out = compute_adx_14(df)
    assert out["adx_current"] is not None
    assert 0 <= out["adx_current"] <= 100
    assert out["adx_5d_avg"] is not None
    assert 0 <= out["adx_5d_avg"] <= 100


def test_adx_14_insufficient_data_returns_none():
    df = _build_klines_1d(days=20)  # < 30
    out = compute_adx_14(df)
    assert out["adx_current"] is None


def test_adx_14_higher_for_trending_market():
    """构造强趋势市场,ADX 应明显高于震荡市场。"""
    # 强趋势:连续上涨 200 天,日涨 0.5%
    idx = pd.date_range("2025-10-01", periods=200, freq="1D", tz="UTC")
    close = 70000 * (1.005 ** np.arange(200))
    trend_df = pd.DataFrame({
        "open": close * 0.995, "high": close * 1.01,
        "low": close * 0.99, "close": close,
    }, index=idx)
    trend_adx = compute_adx_14(trend_df)["adx_current"]

    # 震荡:正弦波
    rng_close = 70000 + 1000 * np.sin(np.arange(200) * 0.3)
    rng_df = pd.DataFrame({
        "open": rng_close, "high": rng_close + 200,
        "low": rng_close - 200, "close": rng_close,
    }, index=idx)
    rng_adx = compute_adx_14(rng_df)["adx_current"]
    assert trend_adx > rng_adx


# ============================================================
# compute_atr_features
# ============================================================

def test_atr_features_returns_current_and_percentile():
    df = _build_klines_1d(days=250)
    out = compute_atr_features(df)
    assert out["atr_14_current"] is not None
    assert out["atr_14_current"] > 0
    assert out["atr_180d_percentile"] is not None
    assert 0 <= out["atr_180d_percentile"] <= 100


def test_atr_180d_percentile_is_high_for_volatile_recent():
    """近 5 天波动放大 → 当前 ATR 应在 180d 高分位。"""
    df = _build_klines_1d(days=250)
    df.iloc[-5:, df.columns.get_loc("high")] *= 1.1
    df.iloc[-5:, df.columns.get_loc("low")] *= 0.9
    out = compute_atr_features(df)
    assert out["atr_180d_percentile"] > 70


# ============================================================
# detect_swing_points
# ============================================================

def test_detect_swing_points_finds_high_low():
    df = _build_klines_1d(days=100)
    swings = detect_swing_points(df, depth=5)
    assert len(swings) > 0
    assert all(s["type"] in ("high", "low") for s in swings)
    assert all("date" in s and "price" in s for s in swings)


def test_detect_swing_points_short_data_returns_empty():
    df = _build_klines_1d(days=5)
    swings = detect_swing_points(df, depth=5)
    assert swings == []


def test_detect_swing_points_alternating_pattern():
    """构造明确的高低交替序列,验证检测正确。"""
    idx = pd.date_range("2025-10-01", periods=100, freq="1D", tz="UTC")
    # 三角波:高 200 → 低 -200 → 高 200 ...
    base = 70000
    cycle = 30
    close = np.array([
        base + 200 * np.sin(2 * np.pi * i / cycle) for i in range(100)
    ])
    df = pd.DataFrame({
        "open": close, "high": close + 50,
        "low": close - 50, "close": close,
    }, index=idx)
    swings = detect_swing_points(df, depth=5)
    types = [s["type"] for s in swings]
    # 应该至少有 1 个 high 和 1 个 low
    assert "high" in types
    assert "low" in types


# ============================================================
# compute_lth_sth_changes
# ============================================================

def test_lth_sth_changes_returns_pct_change():
    idx = pd.date_range("2025-10-01", periods=100, freq="1D", tz="UTC")
    onchain = {
        "lth_supply": pd.Series(np.linspace(14_000_000, 14_500_000, 100), index=idx),
        "sth_supply": pd.Series(np.linspace(5_000_000, 4_800_000, 100), index=idx),
        "lth_realized_price": pd.Series(np.linspace(40000, 45000, 100), index=idx),
        "sth_realized_price": pd.Series(np.linspace(70000, 72000, 100), index=idx),
    }
    out = compute_lth_sth_changes(onchain)
    assert out["lth_supply_30d_pct_change"] is not None
    assert out["lth_supply_30d_pct_change"] > 0  # 增长
    assert out["sth_supply_30d_pct_change"] < 0  # 下降
    assert out["lth_realized_price_current"] == pytest.approx(45000.0, abs=1)
    assert out["sth_realized_price_current"] == pytest.approx(72000.0, abs=1)


def test_lth_sth_changes_handles_missing_data():
    out = compute_lth_sth_changes({})
    assert out["lth_supply_30d_pct_change"] is None
    assert out["lth_realized_price_current"] is None


# ============================================================
# compute_exchange_flow_features
# ============================================================

def test_exchange_flow_30d_sum_and_max():
    idx = pd.date_range("2026-04-01", periods=30, freq="1D", tz="UTC")
    flow = pd.Series(
        [-1000.0, -500.0, 200.0, -1500.0, -800.0] + [0.0] * 25, index=idx,
    )
    out = compute_exchange_flow_features({"exchange_net_flow": flow})
    assert out["exchange_net_flow_30d_sum"] == pytest.approx(-3600.0)
    assert out["exchange_net_flow_30d_max_outflow"] == pytest.approx(-1500.0)
    assert len(out["exchange_net_flow_30d_series"]) == 30


def test_exchange_flow_handles_missing():
    out = compute_exchange_flow_features({})
    assert out["exchange_net_flow_30d_sum"] is None


# ============================================================
# compute_funding_features
# ============================================================

def test_funding_features_z_score_current_and_max():
    idx = pd.date_range("2026-01-01", periods=100, freq="1D", tz="UTC")
    funding = pd.Series(
        [0.0001] * 89 + [0.0005, 0.0008, 0.001, 0.0006, 0.0007,
                         0.0009, 0.0006, 0.0005, 0.0006, 0.0006, 0.0008],
        index=idx,
    )
    out = compute_funding_features({"funding_rate": funding})
    assert out["funding_rate_current"] == pytest.approx(0.0008)
    assert out["funding_rate_z_score_90d"] is not None
    # 当前值 0.0008 远高于 90d 平均 → z > 1
    assert out["funding_rate_z_score_90d"] > 1.0
    assert out["funding_rate_30d_max"] == pytest.approx(0.001)


def test_funding_features_short_history_no_z():
    idx = pd.date_range("2026-04-01", periods=20, freq="1D", tz="UTC")
    funding = pd.Series([0.0001] * 20, index=idx)
    out = compute_funding_features({"funding_rate": funding})
    assert out["funding_rate_current"] == pytest.approx(0.0001)
    assert out["funding_rate_z_score_90d"] is None


# ============================================================
# compute_oi_features
# ============================================================

def test_oi_features_current_and_z():
    idx = pd.date_range("2026-01-01", periods=100, freq="1D", tz="UTC")
    oi = pd.Series(
        list(np.linspace(30e9, 36e9, 100)), index=idx,
    )
    out = compute_oi_features({"open_interest": oi})
    assert out["open_interest_current"] == pytest.approx(36e9, rel=1e-3)
    assert out["open_interest_z_score_90d"] is not None
    assert out["open_interest_z_score_90d"] > 0


# ============================================================
# compute_price_features
# ============================================================

def test_price_features_returns_close_and_drawdown():
    df = _build_klines_1d(days=100)
    out = compute_price_features(df)
    assert out["current_close"] is not None
    assert out["max_drawdown_60d_pct"] <= 0  # drawdown 应 ≤ 0
    assert out["ema_50_slope_30d"] is not None


def test_price_features_drawdown_for_known_decline():
    idx = pd.date_range("2026-01-01", periods=80, freq="1D", tz="UTC")
    close = np.array([100.0] * 60 + list(np.linspace(100, 80, 20)))  # 后 20 天 -20%
    df = pd.DataFrame({
        "open": close, "high": close + 1, "low": close - 1, "close": close,
    }, index=idx)
    out = compute_price_features(df)
    assert out["max_drawdown_60d_pct"] < -15
    assert out["max_drawdown_60d_pct"] > -25


# ============================================================
# compute_macro_features
# ============================================================

def test_macro_features_returns_dxy_and_changes():
    macro = {
        "dxy": _build_macro_series(days=100, base=100.0),
        "vix": _build_macro_series(days=100, base=20.0),
    }
    out = compute_macro_features(macro)
    assert out["dxy_current"] is not None
    assert out["dxy_30d_change_pct"] is not None
    assert out["dxy_90d_change_pct"] is not None
    assert out["vix_current"] is not None
    assert out["vix_30d_avg"] is not None
    assert out["vix_90d_max"] is not None


def test_macro_features_dgs10_aliased_to_us10y():
    macro = {"dgs10": _build_macro_series(days=100, base=4.5)}
    out = compute_macro_features(macro)
    assert out["us10y_current"] is not None
    assert out["us10y_30d_change_bps"] is not None


def test_macro_features_yield_curve_spread():
    idx = pd.date_range("2026-01-01", periods=50, freq="1D", tz="UTC")
    macro = {
        "us10y": pd.Series([4.30] * 50, index=idx),
        "us2y": pd.Series([4.65] * 50, index=idx),
    }
    out = compute_macro_features(macro)
    assert out["yield_curve_2_10_spread_bps"] == pytest.approx(-35.0, abs=1)


def test_macro_features_etf_flow_sums():
    idx = pd.date_range("2026-04-01", periods=30, freq="1D", tz="UTC")
    macro = {
        "etf_flow": pd.Series([1e7] * 30, index=idx),
    }
    out = compute_macro_features(macro)
    assert out["etf_flow_30d_sum_usd"] == pytest.approx(3e8)
    assert out["etf_flow_7d_sum_usd"] == pytest.approx(7e7)


# ============================================================
# compute_btc_macro_corr_60d
# ============================================================

def test_btc_macro_corr_returns_float_for_aligned_data():
    df = _build_klines_1d(days=200)
    macro = {"nasdaq": _build_macro_series(days=200, base=18000.0)}
    corr = compute_btc_macro_corr_60d(df, macro, key="nasdaq")
    assert corr is not None
    assert -1.0 <= corr <= 1.0


def test_btc_macro_corr_perfect_positive():
    """构造完全相关的 BTC + nasdaq series → corr ≈ +1。"""
    idx = pd.date_range("2025-10-01", periods=200, freq="1D", tz="UTC")
    np.random.seed(11)
    close = 70000 + np.cumsum(np.random.randn(200) * 500)
    df = pd.DataFrame({
        "open": close, "high": close, "low": close, "close": close,
    }, index=idx)
    nasdaq = pd.Series(close * 0.25, index=idx)  # 完全跟 BTC 同向变化
    corr = compute_btc_macro_corr_60d(df, {"nasdaq": nasdaq}, key="nasdaq")
    assert corr is not None
    assert corr > 0.95


def test_btc_macro_corr_handles_missing():
    corr = compute_btc_macro_corr_60d(None, {}, key="nasdaq")
    assert corr is None


# ============================================================
# build_risk_preview
# ============================================================

def test_build_risk_preview_only_3_keys():
    """L3 prompt v3:risk_preview 只允许 3 个客观字段(铁律 1)。"""
    out = build_risk_preview(funding_z=0.85, oi_z=0.42, events_count_72h=1)
    assert set(out.keys()) == {
        "funding_rate_z_score_90d",
        "open_interest_z_score_90d",
        "events_count_72h",
    }
    assert out["funding_rate_z_score_90d"] == 0.85
    assert out["open_interest_z_score_90d"] == 0.42
    assert out["events_count_72h"] == 1


def test_build_risk_preview_no_rule_label_fields():
    """禁止字段 — 1.9-A.1 删掉的 3 个不应在输出里。"""
    out = build_risk_preview(funding_z=None, oi_z=None, events_count_72h=0)
    assert "crowding_level" not in out
    assert "event_risk_active" not in out
    assert "macro_warning_count" not in out
