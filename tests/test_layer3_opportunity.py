"""
tests/test_layer3_opportunity.py — L3 Opportunity 层单元测试。

15+ cases 覆盖 §4.4 判定流 + §7.9 反模式。
mock composite outputs + L1/L2 outputs 手工构造。
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd
import pytest

from src.evidence import Layer3Opportunity


# ==================================================================
# mock 构造器
# ==================================================================

def _l1(regime: str = "trend_up", vol: str = "normal") -> dict[str, Any]:
    return {
        "layer_id": 1, "layer_name": "regime",
        "regime": regime, "regime_primary": regime,
        "volatility_regime": vol, "volatility_level": vol,
        "health_status": "healthy",
    }


def _l2(
    stance: str = "bullish", stance_confidence: float = 0.72,
    phase: str = "early", health: str = "healthy",
    confidence_tier: str = "medium",
) -> dict[str, Any]:
    return {
        "layer_id": 2, "layer_name": "direction",
        "stance": stance, "stance_confidence": stance_confidence,
        "phase": phase,
        "health_status": health,
        "confidence_tier": confidence_tier,
    }


def _composites(
    tt_band: str = "true_trend", tt_direction: str = "up",
    bp_phase: str = "early",
    cp_band: str = "early_bull", cp_conf: float = 0.85,
    crowd_band: str = "normal", crowd_dir: str = "normal",
    er_band: str = "low",
    mh_band: Optional[str] = "neutral_or_tailwind",
    include_mh: bool = True,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "truth_trend": {
            "factor": "truth_trend", "band": tt_band,
            "direction": tt_direction, "score": 7.0,
            "health_status": "healthy",
        },
        "band_position": {
            "factor": "band_position", "phase": bp_phase,
            "phase_confidence": 0.7, "impulse_extension_ratio": 0.4,
            "health_status": "healthy",
        },
        "cycle_position": {
            "factor": "cycle_position",
            "cycle_position": cp_band, "cycle_confidence": cp_conf,
            "health_status": "healthy",
        },
        "crowding": {
            "factor": "crowding",
            "score": 2.0, "direction": crowd_dir, "band": crowd_band,
            "position_cap_multiplier": 1.0,
            "health_status": "healthy",
        },
        "event_risk": {
            "factor": "event_risk", "score": 1.0,
            "band": er_band, "position_cap_multiplier": 1.0,
            "health_status": "healthy",
        },
    }
    if include_mh:
        out["macro_headwind"] = {
            "factor": "macro_headwind", "score": 0.0, "band": mh_band,
            "position_cap_multiplier": 1.0,
            "correlation_amplified": False,
            "health_status": "healthy",
        }
    return out


def _klines_flat(n: int = 30, price: float = 50_000.0) -> pd.DataFrame:
    """构造平盘 K 线(不触发 chasing_high / catching_falling_knife)。"""
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    closes = [price] * n
    return pd.DataFrame({
        "open": closes, "high": [p * 1.005 for p in closes],
        "low": [p * 0.995 for p in closes], "close": closes,
        "volume_btc": [10_000.0] * n,
    }, index=idx)


def _klines_rally_end(
    n: int = 30, rally_pct: float = 0.10, rally_bars: int = 3,
) -> pd.DataFrame:
    """前半段平盘,末尾 rally_bars 根大涨 rally_pct。"""
    price = 50_000.0
    closes = [price] * (n - rally_bars - 1)
    closes.append(price)  # 基准点(第 n-rally_bars 根)
    # 末 rally_bars 根累计涨 rally_pct
    for _ in range(rally_bars):
        closes.append(closes[-1] * (1 + rally_pct / rally_bars))
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({
        "open": closes, "high": [p * 1.005 for p in closes],
        "low": [p * 0.995 for p in closes], "close": closes,
        "volume_btc": [10_000.0] * n,
    }, index=idx)


def _klines_crash_end(
    n: int = 30, drop_pct: float = 0.15, bars: int = 5,
) -> pd.DataFrame:
    """末 N 根急跌 drop_pct。"""
    price = 50_000.0
    closes = [price] * (n - bars - 1)
    closes.append(price)
    for _ in range(bars):
        closes.append(closes[-1] * (1 - drop_pct / bars))
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({
        "open": closes, "high": [p * 1.005 for p in closes],
        "low": [p * 0.995 for p in closes], "close": closes,
        "volume_btc": [10_000.0] * n,
    }, index=idx)


def _ctx(**overrides) -> dict[str, Any]:
    """构造 L3 compute 所需 context。"""
    ctx: dict[str, Any] = {
        "layer_1_output": overrides.pop("l1", _l1()),
        "layer_2_output": overrides.pop("l2", _l2()),
        "composite_factors": overrides.pop("composites", _composites()),
        "klines_1d": overrides.pop("klines_1d", _klines_flat()),
        "events_upcoming_48h": overrides.pop("events", []),
    }
    if "cold_start" in overrides:
        ctx["cold_start"] = overrides.pop("cold_start")
    return ctx


# ==================================================================
# Tests
# ==================================================================

class TestLayer3Opportunity:

    # case 1
    def test_perfect_a(self):
        out = Layer3Opportunity().compute(_ctx())
        assert out["opportunity_grade"] == "A", out["diagnostics"]
        assert out["grade"] == "A"
        assert out["execution_permission"] == "can_open"
        assert out["observation_mode"] == "disciplined_validation"
        assert out["anti_pattern_flags"] == []
        assert out["base_grade_before_anti_patterns"] == "A"

    # case 2
    def test_a_with_chasing_high_downgrades(self):
        """A 级输入但近 3 根涨 10% + phase=late/exhausted → chasing_high 触发。"""
        composites = _composites(bp_phase="late")  # late 时 chasing_high 才真正触发
        klines = _klines_rally_end(rally_pct=0.12, rally_bars=3)
        out = Layer3Opportunity().compute(_ctx(
            composites=composites, klines_1d=klines,
        ))
        assert "chasing_high" in out["anti_pattern_flags"]
        # A 因 bp_phase=late 不满足 A 的 band_position 条件,base 已经不是 A
        # 这里重点验证反模式触发 + grade 被处罚
        assert out["opportunity_grade"] in ("B", "C", "none")

    # case 3
    def test_a_with_crowding_extreme_downgrades(self):
        composites = _composites(crowd_band="extreme", crowd_dir="crowded_long")
        out = Layer3Opportunity().compute(_ctx(composites=composites))
        # A 的 crowding_disallowed_bands 含 extreme → 不过 A
        # + overtrading_crowding 反模式触发
        assert "overtrading_crowding" in out["anti_pattern_flags"]
        # permission cap = no_chase
        assert out["execution_permission"] in ("no_chase", "watch", "hold_only")
        # grade 非 A
        assert out["opportunity_grade"] != "A"

    # case 4
    def test_a_with_high_event_risk_downgrades(self):
        events = [
            {"name": "FOMC_decision", "event_type": "fomc",
             "hours_to": 12},
        ]
        out = Layer3Opportunity().compute(_ctx(events=events))
        assert "event_window_trading" in out["anti_pattern_flags"]
        # permission cap = ambush_only(若 grade 允许)
        assert out["execution_permission"] in ("ambush_only", "watch", "hold_only")

    # case 5
    def test_a_with_macro_headwind_downgrades(self):
        composites = _composites(mh_band="strong_headwind")
        out = Layer3Opportunity().compute(_ctx(composites=composites))
        # A 的 macro_disallowed_bands_bullish 含 strong_headwind → 不过 A
        # + macro_misalignment 反模式触发
        assert "macro_misalignment" in out["anti_pattern_flags"]
        assert out["opportunity_grade"] != "A"

    # case 6
    def test_catching_falling_knife_forces_protective(self):
        """bullish 候选但近 5 根急跌 15% → 强制 grade=none + protective。"""
        klines = _klines_crash_end(drop_pct=0.15, bars=5)
        out = Layer3Opportunity().compute(_ctx(klines_1d=klines))
        assert "catching_falling_knife" in out["anti_pattern_flags"]
        assert out["opportunity_grade"] == "none"
        assert out["execution_permission"] == "protective"

    # case 7
    def test_counter_trend_trade_forces_none(self):
        """L1=trend_up 但 L2.stance=bearish → counter_trend_trade 强制 none。"""
        ctx = _ctx(l1=_l1("trend_up"), l2=_l2(stance="bearish", stance_confidence=0.70))
        # cycle 也改为 bear 档,否则 cycle 不匹配 bearish
        composites = _composites(cp_band="mid_bear", tt_direction="down",
                                  bp_phase="early", crowd_dir="normal")
        ctx["composite_factors"] = composites
        out = Layer3Opportunity().compute(ctx)
        assert "counter_trend_trade" in out["anti_pattern_flags"]
        assert out["opportunity_grade"] == "none"
        assert out["execution_permission"] == "watch"

    # case 8
    def test_l2_neutral_grade_none_watch(self):
        out = Layer3Opportunity().compute(
            _ctx(l2=_l2(stance="neutral", stance_confidence=0.50))
        )
        assert out["opportunity_grade"] == "none"
        assert out["execution_permission"] == "watch"
        assert out["observation_mode"] == "kpi_validation"

    # case 9
    def test_insufficient_data_none(self):
        out = Layer3Opportunity().compute(
            _ctx(l2=_l2(health="insufficient_data", confidence_tier="very_low"))
        )
        assert out["opportunity_grade"] == "none"
        assert out["health_status"] == "insufficient_data"

    # case 10
    def test_b_grade_exact_floor(self):
        """stance_confidence=0.62 刚到 B floor,A 门槛(0.70)不过 → grade=B。"""
        l2 = _l2(stance_confidence=0.62)
        composites = _composites(cp_conf=0.60)   # 刚到 B cycle floor(0.60)
        out = Layer3Opportunity().compute(_ctx(l2=l2, composites=composites))
        assert out["opportunity_grade"] == "B"
        assert out["execution_permission"] == "cautious_open"

    # case 11
    def test_cycle_unclear_caps_at_c(self):
        composites = _composites(cp_band="unclear", cp_conf=0.30)
        out = Layer3Opportunity().compute(_ctx(composites=composites))
        assert out["opportunity_grade"] in ("C", "none")
        assert "cycle=unclear" in " ".join(out["notes"])

    # case 12
    def test_truth_trend_weak_caps_at_c(self):
        composites = _composites(tt_band="no_trend", tt_direction="flat")
        out = Layer3Opportunity().compute(_ctx(composites=composites))
        assert out["opportunity_grade"] in ("C", "none")
        assert any("truth_trend" in n for n in out["notes"])

    # case 13
    def test_cold_start_caps_grade_at_b(self):
        """冷启动期 + 完美 A 条件 → grade 被 cap 到 B。"""
        out = Layer3Opportunity().compute(_ctx(
            cold_start={"warming_up": True, "days_elapsed": 3},
        ))
        assert out["opportunity_grade"] in ("B", "C")
        assert out["base_grade_before_anti_patterns"] == "A"
        assert any("cold_start" in n for n in out["notes"])

    # case 14
    def test_multiple_anti_patterns(self):
        """同时触发 chasing_high + crowding → 取最严格降级。"""
        composites = _composites(bp_phase="late", crowd_band="extreme",
                                  crowd_dir="crowded_long")
        klines = _klines_rally_end(rally_pct=0.12, rally_bars=3)
        out = Layer3Opportunity().compute(_ctx(
            composites=composites, klines_1d=klines,
        ))
        flags = out["anti_pattern_flags"]
        assert "chasing_high" in flags
        assert "overtrading_crowding" in flags
        # 多重降级:A → B → C(甚至 none)
        assert out["opportunity_grade"] in ("C", "none")

    # case 15
    def test_macro_missing_no_trigger(self):
        """macro_headwind 不在 composite_factors 里 → macro_misalignment 不触发。"""
        composites = _composites(include_mh=False)
        out = Layer3Opportunity().compute(_ctx(composites=composites))
        assert "macro_misalignment" not in out["anti_pattern_flags"]
        # macro 缺失 note
        assert any("macro" in n.lower() for n in out["notes"])


# ==================================================================
# Schema 一致性
# ==================================================================

class TestLayer3Schema:

    def test_all_fields_present(self):
        out = Layer3Opportunity().compute(_ctx())
        for k in (
            "opportunity_grade", "grade", "execution_permission",
            "observation_mode", "base_grade_before_anti_patterns",
            "anti_pattern_flags", "anti_pattern_details",
            "thresholds_applied", "hard_rule_check_results",
            "diagnostics", "notes",
            "opportunity_reason", "suggested_entry_plan",
            "timing_assessment", "entry_confirmation_timeframe",
            "layer_id", "layer_name",
            "health_status", "confidence_tier", "computation_method",
            "rules_version", "reference_timestamp_utc",
        ):
            assert k in out, f"missing: {k}"
        assert out["layer_id"] == 3

    def test_valid_grade_enum(self):
        out = Layer3Opportunity().compute(_ctx())
        assert out["opportunity_grade"] in ("A", "B", "C", "none")

    def test_valid_permission_enum(self):
        out = Layer3Opportunity().compute(_ctx())
        valid = {
            "can_open", "cautious_open", "no_chase", "ambush_only",
            "watch", "protective", "hold_only",
        }
        assert out["execution_permission"] in valid

    def test_observation_mode_mapped_by_grade(self):
        # A → disciplined_validation
        a_out = Layer3Opportunity().compute(_ctx())
        assert a_out["observation_mode"] == "disciplined_validation"
        # neutral → kpi_validation
        n_out = Layer3Opportunity().compute(
            _ctx(l2=_l2(stance="neutral"))
        )
        assert n_out["observation_mode"] == "kpi_validation"
