"""
tests/test_layer2_direction.py — L2 Direction 层单元测试。

12+ cases 覆盖建模 §4.3 判定流的所有路径。
mock composite outputs 手工构造,不依赖实际 K 线。
"""

from __future__ import annotations

from typing import Any, Optional

import pytest

from src.evidence import Layer2Direction


# ==================================================================
# Helpers
# ==================================================================

def _tt(direction: str = "up", band: str = "true_trend",
        health: str = "healthy") -> dict[str, Any]:
    """mock TruthTrend output。"""
    return {
        "factor": "truth_trend",
        "direction": direction,
        "band": band,
        "score": 6.0 if band == "true_trend" else (4.0 if band == "weak_trend" else 2.0),
        "confidence": 0.75 if band == "true_trend" else 0.5,
        "items_triggered": [],
        "health_status": health,
    }


def _bp(phase: str = "early", confidence: float = 0.7,
        health: str = "healthy") -> dict[str, Any]:
    """mock BandPosition output。"""
    return {
        "factor": "band_position",
        "phase": phase,
        "phase_confidence": confidence,
        "impulse_extension_ratio": 0.5,
        "health_status": health,
    }


def _cp(band: str = "early_bull", confidence: float = 0.85,
        health: str = "healthy") -> dict[str, Any]:
    """mock CyclePosition output。"""
    return {
        "factor": "cycle_position",
        "cycle_position": band,
        "cycle_confidence": confidence,
        "voting_pool": [band],
        "last_stable_cycle_position": None,
        "health_status": health,
    }


def _l1(regime: str = "trend_up", vol: str = "normal") -> dict[str, Any]:
    """mock L1 output。"""
    return {
        "layer_id": 1, "layer_name": "regime",
        "regime": regime, "regime_primary": regime,
        "volatility_regime": vol, "volatility_level": vol,
        "trend_direction": "up" if "up" in regime else ("down" if "down" in regime else "flat"),
        "health_status": "healthy",
    }


def _ctx(
    *,
    regime: str = "trend_up", vol: str = "normal",
    tt_dir: str = "up", tt_band: str = "true_trend",
    bp_phase: str = "early",
    cp_band: Optional[str] = "early_bull", cp_confidence: float = 0.85,
    exchange_momentum: Optional[float] = None,
    cold_start: bool = False,
    truth_trend: Any = "default",
    cycle_position: Any = "default",
    band_position: Any = "default",
) -> dict[str, Any]:
    """构造 L2 compute 用的 context。"""
    composites = {}
    if truth_trend == "default":
        composites["truth_trend"] = _tt(tt_dir, tt_band)
    elif truth_trend is not None:
        composites["truth_trend"] = truth_trend

    if band_position == "default":
        composites["band_position"] = _bp(bp_phase)
    elif band_position is not None:
        composites["band_position"] = band_position

    if cycle_position == "default":
        if cp_band is None:
            pass  # 不加入 cycle_position key
        else:
            composites["cycle_position"] = _cp(cp_band, cp_confidence)
    elif cycle_position is not None:
        composites["cycle_position"] = cycle_position

    ctx: dict[str, Any] = {
        "layer_1_output": _l1(regime, vol),
        "composite_factors": composites,
        "single_factors": {},
    }
    if exchange_momentum is not None:
        ctx["single_factors"]["exchange_momentum_score"] = exchange_momentum
    if cold_start:
        ctx["cold_start"] = {"warming_up": True, "days_elapsed": 3}
    return ctx


def _assert_common_fields(out: dict) -> None:
    for k in (
        "layer_id", "layer_name", "reference_timestamp_utc",
        "rules_version", "run_trigger", "data_freshness",
        "health_status", "confidence_tier", "computation_method",
        "stance", "phase", "stance_confidence", "candidate_direction",
        "thresholds_applied", "conflict_flags", "diagnostics",
    ):
        assert k in out, f"missing: {k}"
    assert out["layer_id"] == 2
    assert out["layer_name"] == "direction"


# ==================================================================
# 12 核心 cases
# ==================================================================

class TestLayer2Direction:

    # case 1
    def test_strong_bullish_early_bull(self):
        ctx = _ctx(regime="trend_up", tt_dir="up", tt_band="true_trend",
                   cp_band="early_bull", cp_confidence=0.85, bp_phase="early")
        out = Layer2Direction().compute(ctx)
        _assert_common_fields(out)
        assert out["stance"] == "bullish", out["diagnostics"]
        assert out["phase"] == "early"
        assert 0.55 <= out["stance_confidence"] <= 0.75
        # early_bull long_threshold = 0.55,conf > 0.55 → 触发
        assert out["stance_confidence"] > out["thresholds_applied"]["long"]

    # case 2
    def test_strong_bearish_mid_bear(self):
        ctx = _ctx(regime="trend_down", tt_dir="down", tt_band="true_trend",
                   cp_band="mid_bear", cp_confidence=0.85, bp_phase="mid")
        out = Layer2Direction().compute(ctx)
        _assert_common_fields(out)
        assert out["stance"] == "bearish", out["diagnostics"]
        assert out["phase"] == "mid"
        assert out["candidate_direction"] == "bearish"

    # case 3
    def test_range_mid_gives_neutral(self):
        ctx = _ctx(regime="range_mid", tt_dir="flat", tt_band="no_trend",
                   cp_band="accumulation", cp_confidence=0.60,
                   bp_phase="unclear")
        out = Layer2Direction().compute(ctx)
        _assert_common_fields(out)
        assert out["stance"] == "neutral"
        assert out["phase"] == "n_a"

    # case 4
    def test_l1_tt_conflict(self):
        """L1=trend_up 但 truth_trend=no_trend(direction=flat)→ 冲突 → neutral。"""
        ctx = _ctx(regime="trend_up", tt_dir="flat", tt_band="no_trend",
                   cp_band="early_bull", cp_confidence=0.85)
        out = Layer2Direction().compute(ctx)
        assert out["stance"] == "neutral"
        assert "l1_truth_trend_conflict" in out["conflict_flags"]
        assert out["candidate_direction"] == "neutral"

    # case 5
    def test_chaos_gives_neutral_low_confidence(self):
        ctx = _ctx(regime="chaos", vol="extreme",
                   tt_dir="flat", tt_band="no_trend",
                   cp_band="unclear", cp_confidence=0.30,
                   bp_phase="unclear")
        out = Layer2Direction().compute(ctx)
        assert out["stance"] == "neutral"
        assert out["phase"] == "n_a"
        assert out["stance_confidence"] <= 0.55  # chaos 路径不应高置信

    # case 6
    def test_unclear_cycle_caps_confidence_at_ceiling(self):
        """cycle=unclear → stance_confidence ≤ ceiling(0.75),即便其他条件强。"""
        ctx = _ctx(regime="trend_up", tt_dir="up", tt_band="true_trend",
                   cp_band="unclear", cp_confidence=0.30,
                   bp_phase="early")
        out = Layer2Direction().compute(ctx)
        assert "unclear_cycle_position" in out["conflict_flags"]
        assert out["stance_confidence"] <= 0.75

    # case 7
    def test_late_bull_with_exhausted_band_stays_neutral(self):
        """
        late_bull 门槛 0.65 + 强 trend + cp_conf 中档 + bp=exhausted 大幅减分
        → stance_confidence 被压到 < 0.65 → stance='neutral'。
        """
        ctx = _ctx(regime="trend_up", tt_dir="up", tt_band="true_trend",
                   cp_band="late_bull", cp_confidence=0.60,
                   bp_phase="exhausted")
        out = Layer2Direction().compute(ctx)
        long_th = out["thresholds_applied"]["long"]
        assert long_th == 0.65
        assert out["stance_confidence"] <= long_th, out["diagnostics"]
        assert out["stance"] == "neutral", out["diagnostics"]

    # case 8
    def test_transition_up_gives_early_phase(self):
        ctx = _ctx(regime="transition_up", tt_dir="up", tt_band="weak_trend",
                   cp_band="early_bull", cp_confidence=0.60,
                   bp_phase="early")
        out = Layer2Direction().compute(ctx)
        # transition_up 的支持度 0.7,仍可能触发 bullish
        assert out["stance"] in ("bullish", "neutral")
        if out["stance"] == "bullish":
            assert out["phase"] == "early"

    # case 9
    def test_cold_start_downgrades(self):
        ctx = _ctx(regime="trend_up", tt_dir="up", tt_band="true_trend",
                   cp_band="early_bull", cp_confidence=0.85,
                   bp_phase="early", cold_start=True)
        out = Layer2Direction().compute(ctx)
        # stance_confidence 应被 × 0.8
        # 且 base class 会把 health_status 改成 cold_start_warming_up + tier 降档
        assert out["health_status"] == "cold_start_warming_up"
        # 验证 × 0.8 效应:clamp 之后再 × 0.8 会让值 <= 0.6
        assert out["stance_confidence"] <= 0.65
        # notes 含冷启动提示
        assert any("cold_start" in n.lower() or "warming" in n.lower()
                   for n in out["notes"])

    # case 10
    def test_missing_truth_trend_insufficient(self):
        ctx = _ctx(truth_trend=None)
        out = Layer2Direction().compute(ctx)
        assert out["health_status"] == "insufficient_data"
        assert out["stance"] == "neutral"
        assert out["stance_confidence"] == 0.0

    # case 11
    def test_missing_cycle_caps_low(self):
        """cycle 完全缺失(None)→ stance_confidence ≤ 0.30。"""
        ctx = _ctx(cycle_position=None, cp_band=None,
                   regime="trend_up", tt_dir="up", tt_band="true_trend",
                   bp_phase="early")
        out = Layer2Direction().compute(ctx)
        assert "missing_cycle_position" in out["conflict_flags"]
        assert out["stance_confidence"] <= 0.30

    # case 12 (12a)
    def test_exchange_momentum_bullish_conflict_applies_penalty(self):
        ctx_no_em = _ctx(regime="trend_up", tt_dir="up", tt_band="true_trend",
                         cp_band="early_bull", cp_confidence=0.85,
                         bp_phase="early")
        ctx_em_neg = _ctx(regime="trend_up", tt_dir="up", tt_band="true_trend",
                          cp_band="early_bull", cp_confidence=0.85,
                          bp_phase="early", exchange_momentum=-3.0)
        out_no = Layer2Direction().compute(ctx_no_em)
        out_em = Layer2Direction().compute(ctx_em_neg)
        # em 冲突 → stance_confidence 比没 em 的低(× 0.85)
        assert out_em["stance_confidence"] < out_no["stance_confidence"]
        assert "exchange_momentum_divergence" in out_em["conflict_flags"]

    # case 12b
    def test_exchange_momentum_short_side_not_applied(self):
        """B5:空头侧 stance_confidence 不走 exchange_momentum 修正。"""
        ctx = _ctx(regime="trend_down", tt_dir="down", tt_band="true_trend",
                   cp_band="mid_bear", cp_confidence=0.85,
                   bp_phase="mid", exchange_momentum=5.0)
        out = Layer2Direction().compute(ctx)
        assert "exchange_momentum_divergence" not in out["conflict_flags"]


# ==================================================================
# Schema 一致性
# ==================================================================

class TestLayer2Schema:
    def test_all_common_fields(self):
        ctx = _ctx()
        out = Layer2Direction().compute(ctx)
        _assert_common_fields(out)

    def test_valid_stance_enum(self):
        ctx = _ctx()
        out = Layer2Direction().compute(ctx)
        assert out["stance"] in ("bullish", "bearish", "neutral")

    def test_valid_phase_enum(self):
        ctx = _ctx()
        out = Layer2Direction().compute(ctx)
        valid = ("early", "mid", "late", "exhausted", "unclear", "n_a")
        assert out["phase"] in valid

    def test_thresholds_applied_has_source_band(self):
        ctx = _ctx(cp_band="mid_bull")
        out = Layer2Direction().compute(ctx)
        assert out["thresholds_applied"]["source_band"] == "mid_bull"
        assert out["thresholds_applied"]["long"] == 0.60  # mid_bull

    def test_rules_version_propagated(self):
        ctx = _ctx()
        out = Layer2Direction().compute(ctx, rules_version="v1.2.5")
        assert out["rules_version"] == "v1.2.5"

    def test_long_cycle_context_present(self):
        """schemas.yaml L2 专属字段 long_cycle_context。"""
        ctx = _ctx()
        out = Layer2Direction().compute(ctx)
        assert "long_cycle_context" in out
        assert out["long_cycle_context"]["cycle_position"] == "early_bull"
