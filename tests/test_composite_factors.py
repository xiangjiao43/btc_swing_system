"""
tests/test_composite_factors.py — 6 个组合因子的单元测试。

每个因子至少 3 个 case:
  - 正常数据 → 预期输出
  - 空数据 / 部分缺失 → 降级(health_status != healthy)
  - 边界值 → 输出稳定

用手工构造的 mock 数据,不访问真实 API。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.composite.band_position import BandPositionFactor
from src.composite.crowding import CrowdingFactor
from src.composite.cycle_position import CyclePositionFactor
from src.composite.event_risk import EventRiskFactor
from src.composite.macro_headwind import MacroHeadwindFactor
from src.composite.truth_trend import TruthTrendFactor


# ==================================================================
# Helpers
# ==================================================================

def _klines_trending_up(n: int = 100, start: float = 50_000.0,
                        slope: float = 0.01) -> pd.DataFrame:
    """构造上升趋势 K 线。每日上升 slope%,附带 0.5% 噪声。"""
    rng = np.random.default_rng(42)
    closes = [start]
    for i in range(1, n):
        closes.append(closes[-1] * (1 + slope + rng.normal(0, 0.005)))
    highs = [c * 1.008 for c in closes]
    lows = [c * 0.992 for c in closes]
    opens = [closes[i - 1] if i > 0 else closes[0] for i in range(n)]
    vols_btc = [rng.uniform(25_000, 55_000) for _ in range(n)]
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({
        "open": opens, "high": highs, "low": lows, "close": closes,
        "volume_btc": vols_btc,
        "volume_usdt": [c * v for c, v in zip(closes, vols_btc)],
    }, index=idx)


def _klines_flat(n: int = 100, price: float = 50_000.0) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    closes = [price * (1 + rng.normal(0, 0.003)) for _ in range(n)]
    highs = [c * 1.005 for c in closes]
    lows = [c * 0.995 for c in closes]
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({
        "open": closes, "high": highs, "low": lows, "close": closes,
        "volume_btc": [10_000.0] * n,
        "volume_usdt": [c * 10_000.0 for c in closes],
    }, index=idx)


def _klines_trending_down(n: int = 100, start: float = 60_000.0,
                          slope: float = -0.01) -> pd.DataFrame:
    return _klines_trending_up(n=n, start=start, slope=slope)


# ==================================================================
# TruthTrend
# ==================================================================

class TestTruthTrend:
    def test_strong_uptrend_gives_true_trend(self):
        klines_1d = _klines_trending_up(n=120, slope=0.015)
        klines_4h = _klines_trending_up(n=240, slope=0.003)
        klines_1w = _klines_trending_up(n=40, slope=0.05)
        factor = TruthTrendFactor()
        out = factor.compute({
            "klines_1d": klines_1d,
            "klines_4h": klines_4h,
            "klines_1w": klines_1w,
        })
        assert out["factor"] == "truth_trend"
        assert out["health_status"] == "healthy"
        assert out["direction"] in ("up", "flat")   # 稳健:应该是 up
        assert out["score"] >= 4   # 至少 weak_trend
        assert out["band"] in ("weak_trend", "true_trend")

    def test_flat_market_no_trend(self):
        klines_1d = _klines_flat(n=120)
        factor = TruthTrendFactor()
        out = factor.compute({"klines_1d": klines_1d})
        assert out["health_status"] == "healthy"
        # 平盘市场 score 应较低
        assert out["score"] <= 3
        assert out["band"] in ("no_trend", "weak_trend")

    def test_insufficient_data(self):
        factor = TruthTrendFactor()
        out = factor.compute({"klines_1d": None})
        assert out["health_status"] == "insufficient_data"

        out2 = factor.compute({"klines_1d": pd.DataFrame()})
        assert out2["health_status"] == "insufficient_data"

    def test_output_has_required_fields(self):
        klines_1d = _klines_trending_up(n=80)
        factor = TruthTrendFactor()
        out = factor.compute({"klines_1d": klines_1d})
        for key in ("score", "band", "items_triggered", "confidence",
                    "confidence_tier", "direction",
                    "computation_method", "health_status"):
            assert key in out, f"missing key: {key}"


# ==================================================================
# BandPosition
# ==================================================================

class TestBandPosition:
    def test_uptrend_gives_phase(self):
        klines = _klines_trending_up(n=120, slope=0.01)
        factor = BandPositionFactor()
        out = factor.compute({"klines_1d": klines})
        assert out["health_status"] == "healthy"
        assert out["phase"] in (
            "early", "mid", "late", "exhausted", "unclear"
        )
        assert 0.0 <= out["phase_confidence"] <= 1.0
        assert "scoring_breakdown" in out

    def test_insufficient_data(self):
        factor = BandPositionFactor()
        out = factor.compute({"klines_1d": None})
        assert out["health_status"] == "insufficient_data"
        assert out["phase"] == "unclear"

    def test_phase_confidence_valid_range(self):
        klines = _klines_flat(n=100)
        factor = BandPositionFactor()
        out = factor.compute({"klines_1d": klines})
        assert 0.0 <= out["phase_confidence"] <= 1.0


# ==================================================================
# CyclePosition
# ==================================================================

class TestCyclePosition:
    def _make_context(self, mvrv_z: float | None, nupl: float | None,
                      lth_now: float | None, lth_90d_ago: float | None,
                      ath_drawdown: float = 0.0,
                      mvrv_trend: str = "flat") -> dict:
        """构造 cycle_position 测试 context。"""
        idx = pd.date_range("2024-01-01", periods=120, freq="D", tz="UTC")

        # MVRV Z 序列:根据 mvrv_trend 决定近期趋势
        if mvrv_z is not None:
            base = mvrv_z
            if mvrv_trend == "up":
                mvrv_vals = [base - 0.5 + i * 0.005 for i in range(120)]
            elif mvrv_trend == "down":
                mvrv_vals = [base + 0.5 - i * 0.005 for i in range(120)]
            else:
                mvrv_vals = [base] * 120
            mvrv_series = pd.Series(mvrv_vals, index=idx)
        else:
            mvrv_series = None

        nupl_series = pd.Series([nupl] * 120, index=idx) if nupl is not None else None

        # LTH supply: 用两端点构造 pct change
        if lth_now is not None and lth_90d_ago is not None:
            lth_vals = np.linspace(lth_90d_ago, lth_now, 120)
            lth_series = pd.Series(lth_vals, index=idx)
        else:
            lth_series = None

        # Klines with ath_drawdown
        price_now = 50_000.0
        ath_price = price_now / max(1e-9, 1 - ath_drawdown)
        klines_data = [ath_price] * 50 + list(
            np.linspace(ath_price, price_now, 70)
        )
        klines_idx = pd.date_range("2024-01-01", periods=120, freq="D", tz="UTC")
        klines = pd.DataFrame({
            "open": klines_data, "high": [p * 1.01 for p in klines_data],
            "low": [p * 0.99 for p in klines_data], "close": klines_data,
            "volume_btc": [10_000.0] * 120,
            "volume_usdt": [p * 10_000 for p in klines_data],
        }, index=klines_idx)

        return {
            "onchain": {
                "mvrv_z_score": mvrv_series,
                "nupl": nupl_series,
                "lth_supply": lth_series,
            },
            "klines_1d": klines,
        }

    def test_early_bull_three_agree(self):
        """MVRV Z=1, NUPL=0.15, LTH 90d +2.5% → 三票 early_bull。"""
        ctx = self._make_context(
            mvrv_z=1.0, nupl=0.15,
            lth_now=1.025e6, lth_90d_ago=1.0e6,
        )
        factor = CyclePositionFactor()
        out = factor.compute(ctx)
        assert out["cycle_position"] == "early_bull"
        # three_agree_confidence=0.85(可能被 halving_window 削 0.15 到 0.70)
        assert out["cycle_confidence"] >= 0.60

    def test_unclear_when_all_missing(self):
        factor = CyclePositionFactor()
        out = factor.compute({"onchain": {}})
        assert out["cycle_position"] == "unclear"
        assert out["cycle_confidence"] <= 0.30
        assert out["health_status"] == "insufficient_data"
        # 池空时 last_stable 默认 None(Sprint 1.6 占位)
        assert out["last_stable_cycle_position"] is None

    def test_late_bear_stabilizing_check(self):
        """late_bear 候选,MVRV Z 企稳 → 候选应被剔除。"""
        ctx = self._make_context(
            mvrv_z=-0.8, nupl=-0.3,
            lth_now=1.0e6, lth_90d_ago=1.0e6,
            mvrv_trend="up",  # 企稳 → 剔除 late_bear
        )
        factor = CyclePositionFactor()
        out = factor.compute(ctx)
        # late_bear 不应成为主票(因为已企稳,被剔除)
        assert out["voting_breakdown"]["mvrv_z_candidate"] != "late_bear"
        # stabilizing check 结果应该是 True(up trend → stabilizing)
        assert out["mvrv_z_stabilizing_check_result"] is True

    def test_output_has_required_fields(self):
        ctx = self._make_context(mvrv_z=1.0, nupl=0.2, lth_now=1.0e6, lth_90d_ago=1.0e6)
        factor = CyclePositionFactor()
        out = factor.compute(ctx)
        for key in ("cycle_position", "cycle_confidence", "voting_pool",
                    "voting_breakdown", "aux_conditions_passed",
                    "last_stable_cycle_position", "halving_window_active",
                    "mvrv_z_stabilizing_check_result"):
            assert key in out, f"missing: {key}"


# ==================================================================
# Crowding
# ==================================================================

class TestCrowding:
    def test_extreme_crowding_long(self):
        # funding 极端 × 3 次(+2)+ OI spike +20% (+1)+ LSR=3 (+1)= 4 分
        # 不注入 liquidation 数据,避免 upward_liquidation_density(-1)干扰。
        idx = pd.date_range("2024-01-01", periods=10, freq="h", tz="UTC")
        derivatives = {
            "funding_rate": pd.Series([0.0005] * 10, index=idx),
            "open_interest": pd.Series([1_000, 1_200], index=idx[:2]),
            "long_short_ratio": pd.Series([3.0], index=idx[:1]),
        }
        factor = CrowdingFactor()
        out = factor.compute({"derivatives": derivatives})
        assert out["score"] >= 4  # 触发多个 items
        assert out["direction"] == "crowded_long"
        # 至少 mild (≥4) 或 extreme (≥6)
        assert out["band"] in ("mild", "extreme")

    def test_no_data_skipped(self):
        factor = CrowdingFactor()
        out = factor.compute({"derivatives": {}})
        assert out["score"] == 0.0
        assert out["band"] == "normal"
        assert out["health_status"] in ("degraded", "insufficient_data")
        assert len(out["items_skipped"]) >= 4  # 大部分 item 被 skip

    def test_output_has_required_fields(self):
        factor = CrowdingFactor()
        out = factor.compute({"derivatives": {}})
        for key in ("score", "direction", "band", "position_cap_multiplier",
                    "items_triggered", "items_skipped"):
            assert key in out, f"missing: {key}"


# ==================================================================
# MacroHeadwind
# ==================================================================

class TestMacroHeadwind:
    def _series(self, values: list[float]) -> pd.Series:
        idx = pd.date_range("2024-01-01", periods=len(values), freq="D", tz="UTC")
        return pd.Series(values, index=idx)

    def test_strong_headwind(self):
        # DXY 上涨 3%(>2%)+ VIX 30(>25) + 纳指 -8%(<-5%)
        macro = {
            "dxy": self._series([100.0] * 20 + [103.0]),
            "us10y": self._series([3.0] * 20 + [3.5]),  # +50bp (>30)
            "vix": self._series([30.0] * 21),
            "nasdaq": self._series([100.0] * 20 + [91.0]),  # -9%
        }
        factor = MacroHeadwindFactor()
        out = factor.compute({"macro": macro})
        # -2 × 4 = -8;clip 到 -10;band = strong_headwind(-5 阈值)
        assert out["score"] <= -5
        assert out["band"] == "strong_headwind"
        assert out["position_cap_multiplier"] == 0.7

    def test_all_macro_missing(self):
        factor = MacroHeadwindFactor()
        out = factor.compute({"macro": {}})
        assert out["health_status"] == "insufficient_data"
        assert out["band"] == "unknown"
        assert out["position_cap_multiplier"] == 1.0

    def test_partial_macro_degraded(self):
        macro = {
            "dxy": self._series([100.0] * 21),       # 无变化
            "vix": self._series([15.0] * 21),        # 低
            # us10y / nasdaq 缺失
        }
        factor = MacroHeadwindFactor()
        out = factor.compute({"macro": macro})
        assert out["health_status"] == "degraded"
        assert out["data_completeness_pct"] == 50.0

    def test_output_has_required_fields(self):
        factor = MacroHeadwindFactor()
        out = factor.compute({"macro": {}})
        for key in ("score", "band", "position_cap_multiplier",
                    "correlation_amplified", "items_triggered",
                    "data_completeness_pct", "driver_breakdown"):
            assert key in out, f"missing: {key}"


# ==================================================================
# EventRisk
# ==================================================================

class TestEventRisk:
    def test_fomc_within_24h_high(self):
        events = [
            {"name": "FOMC_decision", "event_type": "fomc",
             "hours_to": 12, "impact_level": 5},
        ]
        factor = EventRiskFactor()
        out = factor.compute({"events_upcoming_48h": events})
        # fomc=4 × 1.5 = 6;band=medium(≥4) 或 high(≥8)? 6 < 8 → medium
        assert out["score"] == 6.0
        assert out["band"] == "medium"
        assert out["position_cap_multiplier"] == 0.85

    def test_high_score_triggers_permission_adjustment(self):
        events = [
            {"name": "FOMC_decision", "event_type": "fomc", "hours_to": 12},
            {"name": "CPI", "event_type": "cpi", "hours_to": 20},
        ]
        # 4*1.5 + 3*1.5 = 10.5 > 8 → high
        factor = EventRiskFactor()
        out = factor.compute({
            "events_upcoming_48h": events,
            "btc_nasdaq_correlated": False,
        })
        assert out["score"] >= 8.0
        assert out["band"] == "high"
        assert out["permission_adjustment"] == "ambush_only"

    def test_no_events_low(self):
        factor = EventRiskFactor()
        out = factor.compute({"events_upcoming_48h": []})
        assert out["score"] == 0.0
        assert out["band"] == "low"
        assert out["position_cap_multiplier"] == 1.0

    def test_us_corr_bonus(self):
        events = [
            {"name": "CPI", "event_type": "cpi", "hours_to": 12},
        ]
        # 无相关性:3 × 1.5 = 4.5
        factor = EventRiskFactor()
        out_no_corr = factor.compute({
            "events_upcoming_48h": events,
            "btc_nasdaq_correlated": False,
        })
        # 有相关性:3 × 1.5 + 1 = 5.5
        out_with_corr = factor.compute({
            "events_upcoming_48h": events,
            "btc_nasdaq_correlated": True,
        })
        assert out_with_corr["score"] > out_no_corr["score"]

    def test_output_has_required_fields(self):
        factor = EventRiskFactor()
        out = factor.compute({"events_upcoming_48h": []})
        for key in ("score", "band", "position_cap_multiplier",
                    "permission_adjustment", "contributing_events",
                    "upcoming_events_count"):
            assert key in out, f"missing: {key}"
