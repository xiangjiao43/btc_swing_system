"""tests/ai/test_anti_pattern_signals.py — Sprint 1.9-A.3 反模式 5 类 bool。

每个独立检测器 + 主入口 compute_anti_pattern_signals 都测触发/不触发。
"""

from __future__ import annotations

import pytest

from src.ai.anti_pattern_signals import (
    compute_anti_pattern_signals,
    is_after_extreme_event_no_reset,
    is_against_long_cycle,
    is_chasing_breakout_no_pullback,
    is_extending_late_phase,
    is_failing_at_resistance,
)


# ============================================================
# is_extending_late_phase
# ============================================================

def test_extending_late_phase_triggers_for_late():
    assert is_extending_late_phase({"phase": "late"}) is True


def test_extending_late_phase_triggers_for_exhausted():
    assert is_extending_late_phase({"phase": "exhausted"}) is True


def test_extending_late_phase_no_trigger_for_early():
    assert is_extending_late_phase({"phase": "early"}) is False
    assert is_extending_late_phase({"phase": "mid"}) is False


def test_extending_late_phase_handles_missing():
    assert is_extending_late_phase({}) is False
    assert is_extending_late_phase(None) is False


# ============================================================
# is_against_long_cycle
# ============================================================

def test_against_long_cycle_bullish_in_distribution():
    """stance=bullish + cycle=distribution → True。"""
    l2 = {
        "stance": "bullish",
        "long_cycle_context": {"rule_cycle_position": "distribution"},
    }
    assert is_against_long_cycle(l2) is True


def test_against_long_cycle_bearish_in_accumulation():
    l2 = {
        "stance": "bearish",
        "long_cycle_context": {"rule_cycle_position": "accumulation"},
    }
    assert is_against_long_cycle(l2) is True


def test_against_long_cycle_aligned_no_trigger():
    """stance=bullish + cycle=early_bull → False(同向)。"""
    l2 = {
        "stance": "bullish",
        "long_cycle_context": {"rule_cycle_position": "early_bull"},
    }
    assert is_against_long_cycle(l2) is False


def test_against_long_cycle_uses_ai_alternative():
    """有 ai_alternative 时优先用它(覆盖 rule)。"""
    l2 = {
        "stance": "bullish",
        "long_cycle_context": {
            "rule_cycle_position": "accumulation",
            "ai_alternative": "late_bull",   # AI disagree → 用这个
        },
    }
    # ai_alternative=late_bull 是 bearish_cycle → 触发
    assert is_against_long_cycle(l2) is True


# ============================================================
# is_chasing_breakout_no_pullback
# ============================================================

def test_chasing_breakout_bullish_just_above_resistance():
    """突破阻力 0.5%(< 1%)+ phase=early → True。"""
    l2 = {
        "stance": "bullish", "phase": "early",
        "key_levels": {"nearest_resistance": 78900},
    }
    assert is_chasing_breakout_no_pullback(l2, 79295.0) is True  # +0.5%


def test_chasing_breakout_no_trigger_when_far_above():
    """突破 > 1% → 不算"刚突破" → False。"""
    l2 = {
        "stance": "bullish", "phase": "early",
        "key_levels": {"nearest_resistance": 78900},
    }
    assert is_chasing_breakout_no_pullback(l2, 80000.0) is False  # +1.4%


def test_chasing_breakout_no_trigger_for_late_phase():
    """phase=late → False(不在 chase 范围)。"""
    l2 = {
        "stance": "bullish", "phase": "late",
        "key_levels": {"nearest_resistance": 78900},
    }
    assert is_chasing_breakout_no_pullback(l2, 79295.0) is False


def test_chasing_breakout_bearish_below_support():
    """stance=bearish + 跌破 nearest_support 0.5% → True。"""
    l2 = {
        "stance": "bearish", "phase": "mid",
        "key_levels": {"nearest_support": 75320},
    }
    assert is_chasing_breakout_no_pullback(l2, 74943.0) is True  # -0.5%


# ============================================================
# is_failing_at_resistance
# ============================================================

def test_failing_at_resistance_bullish_just_below():
    """价格在 nearest_resistance 下方 0.3%(< 0.5%)+ stance=bullish → True。"""
    l2 = {
        "stance": "bullish",
        "key_levels": {"nearest_resistance": 78900},
    }
    assert is_failing_at_resistance(l2, 78663.0) is True  # -0.3%


def test_failing_at_resistance_no_trigger_far_below():
    """距阻力 > 0.5% → False。"""
    l2 = {
        "stance": "bullish",
        "key_levels": {"nearest_resistance": 78900},
    }
    assert is_failing_at_resistance(l2, 77000.0) is False


def test_failing_at_resistance_bearish_just_above_support():
    l2 = {
        "stance": "bearish",
        "key_levels": {"nearest_support": 75320},
    }
    assert is_failing_at_resistance(l2, 75547.0) is True  # +0.3%


# ============================================================
# is_after_extreme_event_no_reset
# ============================================================

def test_after_extreme_event_triggers_when_any_flag_true():
    flags = {"flash_crash_detected_24h": True, "stablecoin_depeg_active": False}
    assert is_after_extreme_event_no_reset(flags) is True


def test_after_extreme_event_no_trigger_when_all_false():
    flags = {
        "flash_crash_detected_24h": False,
        "stablecoin_depeg_active": False,
        "geopolitical_conflict_active": False,
    }
    assert is_after_extreme_event_no_reset(flags) is False


def test_after_extreme_event_handles_missing():
    assert is_after_extreme_event_no_reset({}) is False
    assert is_after_extreme_event_no_reset(None) is False


# ============================================================
# 主入口 compute_anti_pattern_signals
# ============================================================

def test_compute_anti_pattern_signals_returns_5_keys():
    out = compute_anti_pattern_signals(
        l1_output={"regime": "trend_up"},
        l2_output={"stance": "bullish", "phase": "early",
                   "key_levels": {"nearest_resistance": 78900,
                                  "nearest_support": 75320},
                   "long_cycle_context": {"rule_cycle_position": "early_bull"}},
        current_close=75320.0,
        extreme_event_flags={"flash_crash_detected_24h": False},
    )
    assert set(out.keys()) == {
        "is_extending_late_phase",
        "is_against_long_cycle",
        "is_chasing_breakout_no_pullback",
        "is_failing_at_resistance",
        "is_after_extreme_event_no_reset",
    }
    # 在 nearest_support 上(75320),距 nearest_resistance 78900 还有 4.5% → failing 不触发
    assert out["is_failing_at_resistance"] is False
    assert out["is_extending_late_phase"] is False
    assert out["is_against_long_cycle"] is False


def test_compute_anti_pattern_signals_late_phase_triggers():
    out = compute_anti_pattern_signals(
        l1_output={},
        l2_output={"stance": "bullish", "phase": "late",
                   "key_levels": {},
                   "long_cycle_context": {"rule_cycle_position": "early_bull"}},
        current_close=80000.0,
    )
    assert out["is_extending_late_phase"] is True


def test_compute_anti_pattern_signals_neutral_stance_minimal_trigger():
    """stance=neutral(L2 空仓信号)→ 大多数 anti_pattern 不触发。"""
    out = compute_anti_pattern_signals(
        l1_output={"regime": "chaos"},
        l2_output={"stance": "neutral", "phase": "n_a", "key_levels": {}},
        current_close=75000.0,
    )
    assert out["is_extending_late_phase"] is False
    assert out["is_against_long_cycle"] is False
    assert out["is_chasing_breakout_no_pullback"] is False
    assert out["is_failing_at_resistance"] is False
    assert out["is_after_extreme_event_no_reset"] is False
