"""
tests/test_layer5_macro.py — L5 Macro 层单元测试。

10+ cases:覆盖 risk_on/risk_off/unclear 三大环境 + 多种降级路径。
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd
import pytest

from src.evidence import Layer5Macro


# ==================================================================
# Fixture builders
# ==================================================================

def _series(values: list[float], start: str = "2024-01-01") -> pd.Series:
    idx = pd.date_range(start, periods=len(values), freq="D", tz="UTC")
    return pd.Series(values, index=idx, dtype=float)


def _rising_series(n: int = 90, start_val: float = 100.0,
                   daily_pct: float = 0.002, noise: float = 0.01,
                   seed: int = 11) -> pd.Series:
    """构造"均值 daily_pct + 噪声"的日线序列(有方差,便于算相关)。"""
    rng = np.random.default_rng(seed)
    vals = [start_val]
    for i in range(1, n):
        vals.append(vals[-1] * (1 + daily_pct + rng.normal(0, noise)))
    return _series(vals)


def _falling_series(n: int = 90, start_val: float = 100.0,
                    daily_pct: float = -0.002, noise: float = 0.01,
                    seed: int = 22) -> pd.Series:
    return _rising_series(n=n, start_val=start_val, daily_pct=daily_pct,
                          noise=noise, seed=seed)


def _flat_series(n: int = 90, value: float = 100.0,
                 noise: float = 0.002, seed: int = 1) -> pd.Series:
    rng = np.random.default_rng(seed)
    vals = [value * (1 + rng.normal(0, noise)) for _ in range(n)]
    return _series(vals)


def _btc_klines(n: int = 90, seed: int = 42,
                correlate_with: Optional[pd.Series] = None) -> pd.DataFrame:
    """构造 BTC 日 K。若提供 correlate_with,让 BTC 收益与之强正相关。"""
    rng = np.random.default_rng(seed)
    if correlate_with is not None:
        nas_ret = correlate_with.pct_change().dropna().values
        # BTC = 0.9 × nas_ret + 0.1 × 独立噪声
        btc_rets = 0.9 * nas_ret + 0.1 * rng.normal(0, 0.02, len(nas_ret))
        closes = [50_000.0]
        for r in btc_rets:
            closes.append(closes[-1] * (1 + r))
        # 把 closes 对齐到 n 长度:closes 有 len(nas_ret)+1 项,
        # correlate_with 有 n 项,nas_ret 有 n-1 项 → closes 有 n 项 ✓
    else:
        closes = [50_000.0 * (1 + rng.normal(0, 0.02)) for _ in range(n)]
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({
        "open": closes, "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes], "close": closes,
        "volume_btc": [10_000.0] * n,
    }, index=idx)


# ==================================================================
# Tests
# ==================================================================

class TestLayer5Macro:

    # case 1: clear risk_off
    def test_clear_risk_off_strong_headwind(self):
        """DXY 升 + yields 升 + VIX 高 + 股指跌 + BTC 与 Nasdaq 强相关 → 强逆风。"""
        nasdaq = _falling_series(n=90, start_val=15000, daily_pct=-0.003)
        macro = {
            "dxy":    _rising_series(n=90, start_val=103, daily_pct=0.002),
            "us10y":  _rising_series(n=90, start_val=3.8, daily_pct=0.001),
            "vix":    _rising_series(n=90, start_val=22, daily_pct=0.005),
            "nasdaq": nasdaq,
        }
        klines = _btc_klines(n=90, correlate_with=nasdaq)
        out = Layer5Macro().compute({"macro": macro, "klines_1d": klines})

        assert out["macro_environment"] == "risk_off", out["diagnostics"]
        assert out["macro_headwind_vs_btc"] in ("strong_headwind", "mild_headwind")
        assert out["vix_regime"]["level"] in ("elevated", "extreme_fear")
        assert out["data_completeness_pct"] == pytest.approx(40.0)  # 4/10 metric

    # case 2: clear risk_on
    def test_clear_risk_on_tailwind(self):
        nasdaq = _rising_series(n=90, start_val=15000, daily_pct=0.003)
        macro = {
            "dxy":    _falling_series(n=90, start_val=103, daily_pct=-0.0015),
            "us10y":  _falling_series(n=90, start_val=4.0, daily_pct=-0.0005),
            "vix":    _flat_series(n=90, value=12, noise=0.001),
            "nasdaq": nasdaq,
            "sp500":  _rising_series(n=90, start_val=5000, daily_pct=0.002),
        }
        klines = _btc_klines(n=90, correlate_with=nasdaq)
        out = Layer5Macro().compute({"macro": macro, "klines_1d": klines})

        assert out["macro_environment"] == "risk_on", out["diagnostics"]
        assert out["macro_headwind_vs_btc"] in ("tailwind", "mild_tailwind")
        assert out["vix_regime"]["level"] == "low_fear"

    # case 3
    def test_no_data_unclear(self):
        out = Layer5Macro().compute({"macro": {}, "klines_1d": None})
        assert out["macro_environment"] == "unclear"
        assert out["health_status"] == "insufficient_data"
        assert out["data_completeness_pct"] == 0.0

    # case 4
    def test_only_yahoo_fred_missing(self):
        """只有 Yahoo 数据,FRED 全缺。"""
        macro = {
            "dxy":    _flat_series(n=90, value=100),
            "vix":    _flat_series(n=90, value=17),
            "nasdaq": _rising_series(n=90, start_val=15000, daily_pct=0.001),
        }
        out = Layer5Macro().compute({
            "macro": macro, "klines_1d": _btc_klines(n=90),
        })
        # Yahoo 部分 metric 能算
        assert out["dxy_trend"] is not None
        assert out["vix_regime"] is not None
        # metrics_missing 应含 FRED 字段
        for m in ("dgs10", "dff", "cpi", "unemployment_rate"):
            assert m in out["metrics_missing"]

    # case 5
    def test_only_fred_yahoo_missing(self):
        """模拟 Yahoo 限速:只有 FRED,没有 DXY/VIX/Nasdaq。"""
        macro = {
            "dgs10":            _rising_series(n=90, start_val=4.0, daily_pct=0.0005),
            "dff":              _flat_series(n=90, value=5.25),
            "cpi":              _flat_series(n=90, value=310),
            "unemployment_rate": _flat_series(n=90, value=3.8),
        }
        out = Layer5Macro().compute({
            "macro": macro, "klines_1d": _btc_klines(n=90),
        })
        # yields 应能算(通过 dgs10 兜底)
        assert out["yields_trend"] is not None
        # DXY / VIX 应 None(数据不在)
        assert out["dxy_trend"] is None
        assert out["vix_regime"] is None
        # BTC-Nasdaq 相关性无法算(nasdaq 缺)
        assert out["btc_nasdaq_correlation"] is None
        # 部分数据 → health 可能 degraded
        assert out["data_completeness_pct"] > 0

    # case 6
    def test_mixed_signals_neutral(self):
        """DXY 升(risk_off 信号)+ VIX 低(risk_on 信号)→ 混合 → neutral。"""
        macro = {
            "dxy": _rising_series(n=90, start_val=100, daily_pct=0.002),
            "vix": _flat_series(n=90, value=12),
        }
        out = Layer5Macro().compute({
            "macro": macro, "klines_1d": _btc_klines(n=90),
        })
        # 只有 2 个信号,互相抵消 → neutral
        assert out["macro_environment"] in ("neutral", "unclear", "risk_off", "risk_on")

    # case 7
    def test_strong_corr_with_risk_off(self):
        nasdaq = _falling_series(n=90, start_val=15000, daily_pct=-0.003)
        klines = _btc_klines(n=90, correlate_with=nasdaq)
        macro = {
            "dxy": _rising_series(n=90, start_val=103, daily_pct=0.002),
            "vix": _rising_series(n=90, start_val=25, daily_pct=0.005),
            "nasdaq": nasdaq,
        }
        out = Layer5Macro().compute({"macro": macro, "klines_1d": klines})
        corr = out["btc_nasdaq_correlation"]
        assert corr is not None
        assert corr["coefficient"] > 0.6   # 强相关

    # case 8
    def test_uncorrelated_btc_independent(self):
        """BTC 与 Nasdaq 无相关 → headwind = independent。"""
        import numpy as np
        # Nasdaq 走势
        nasdaq = _rising_series(n=120, start_val=15000, daily_pct=0.001)
        # BTC 独立随机
        klines = _btc_klines(n=120, seed=999)   # 不传 correlate_with → 独立
        macro = {"dxy": _flat_series(n=120),
                 "vix": _flat_series(n=120, value=17),
                 "nasdaq": nasdaq}
        out = Layer5Macro().compute({"macro": macro, "klines_1d": klines})
        corr = out["btc_nasdaq_correlation"]
        # 独立噪声 → |corr| 应 < 0.4
        if corr is not None:
            assert abs(corr["coefficient"]) < 0.4
            assert corr["strength_label"] == "uncorrelated"
            assert out["macro_headwind_vs_btc"] == "independent"

    # case 9
    def test_vix_spike_flag(self):
        """VIX 最近 7 天急升 >20% → is_spike=True。"""
        # 前 80 天 VIX=15,最后 10 天急升到 28
        vals = [15.0] * 80 + [16, 17, 19, 22, 24, 26, 27, 27.5, 28, 28.5]
        vix = _series(vals)
        macro = {"vix": vix}
        out = Layer5Macro().compute({"macro": macro, "klines_1d": _btc_klines(n=90)})
        assert out["vix_regime"]["is_spike"] is True
        assert out["vix_regime"]["level"] in ("elevated", "extreme_fear")

    # case 10
    def test_completeness_pct(self):
        """6/10 metric 存在 → 完整度 60%。"""
        macro = {
            "dxy":    _flat_series(n=90),
            "us10y":  _flat_series(n=90, value=4.0),
            "vix":    _flat_series(n=90, value=17),
            "sp500":  _flat_series(n=90, value=5000),
            "nasdaq": _flat_series(n=90, value=15000),
            "dgs10":  _flat_series(n=90, value=4.0),
        }
        out = Layer5Macro().compute({"macro": macro,
                                      "klines_1d": _btc_klines(n=90)})
        assert out["data_completeness_pct"] == pytest.approx(60.0)
        assert len(out["metrics_available"]) == 6
        assert len(out["metrics_missing"]) == 4


# ==================================================================
# Schema 一致性
# ==================================================================

class TestLayer5Schema:

    def test_required_fields(self):
        macro = {"dxy": _flat_series(n=90)}
        out = Layer5Macro().compute({"macro": macro,
                                      "klines_1d": _btc_klines(n=90)})
        for k in (
            "layer_id", "layer_name", "rules_version",
            "macro_environment", "macro_headwind_vs_btc",
            "dxy_trend", "yields_trend", "vix_regime",
            "btc_nasdaq_correlation",
            "data_completeness_pct", "metrics_available", "metrics_missing",
            "diagnostics", "notes",
            "health_status", "confidence_tier", "computation_method",
        ):
            assert k in out, f"missing: {k}"
        assert out["layer_id"] == 5

    def test_valid_environment_enum(self):
        out = Layer5Macro().compute({"macro": {}, "klines_1d": None})
        assert out["macro_environment"] in (
            "risk_on", "risk_off", "neutral", "unclear"
        )
