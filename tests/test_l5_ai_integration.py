"""tests/test_l5_ai_integration.py — Sprint 2.6-E Commit 2/3。

覆盖:
1. Layer5Macro 走 AI 路径(mock'd MacroL5Adjudicator)→ output 含 §6.8 字段
2. Layer5Macro 走规则路径(AI fail)→ output 含 §6.8 占位
3. Layer5Macro data_completeness < 50 → 不调 AI
4. apply_l5_ai_loopback:AI 未启用 → 原样返回
5. apply_l5_ai_loopback:AI 给 strong headwind → step 4 multiplier=0.7,position_cap 缩
6. apply_l5_ai_loopback:adjustment_guidance.permission_adjustment='tighten' → 一档更严
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from src.evidence.layer4_risk import (
    _shift_permission, apply_l5_ai_loopback,
)
from src.evidence.layer5_macro import Layer5Macro


_AI_PAYLOAD_RISK_OFF = {
    "macro_stance": "risk_off",
    "macro_trend": "deteriorating",
    "structured_macro": {"dxy": 105.5, "vix": 28.0},
    "active_macro_tags": ["dxy_strengthening", "vix_elevated"],
    "active_event_summaries": [
        {"name": "FOMC", "type": "fomc", "severity": 5,
         "btc_impact": "bearish", "duration": "1-3 days", "confidence": 0.85},
    ],
    "extreme_event_detected": False,
    "extreme_event_details": None,
    "adjustment_guidance": {
        "stance_modifier": "challenge",
        "position_cap_multiplier": 0.7,
        "permission_adjustment": "tighten",
        "note": "FOMC + DXY 走强,缩仓位防尾部",
    },
    "macro_headwind_score": -6.0,  # 落入 ≤ -5 桶 → multiplier=0.7
    "_meta": {"model": "mock", "tokens_in": 1, "tokens_out": 1,
              "latency_ms": 1, "attempts": 1},
}


# ============================================================
# 1. Layer5Macro AI path
# ============================================================

def _make_macro_dict_full() -> dict:
    """6/10 metrics(>= 50%)→ 触发 AI。"""
    rng = pd.date_range("2026-01-01", periods=120, freq="D")
    return {
        "dxy": pd.Series(range(120), index=rng, dtype=float),
        "us10y": pd.Series([4.0] * 120, index=rng, dtype=float),
        "vix": pd.Series([20.0] * 120, index=rng, dtype=float),
        "nasdaq": pd.Series(range(15000, 15120), index=rng, dtype=float),
        "sp500": pd.Series(range(5000, 5120), index=rng, dtype=float),
        "gold_price": pd.Series([2000.0] * 120, index=rng, dtype=float),
    }


def test_layer5_calls_ai_when_completeness_above_50():
    macro = _make_macro_dict_full()
    rng = pd.date_range("2026-01-01", periods=120, freq="D")
    klines = pd.DataFrame({
        "open": range(50000, 50120),
        "high": range(50100, 50220),
        "low": range(49900, 50020),
        "close": range(50000, 50120),
        "volume": [1.0] * 120,
    }, index=rng)
    ctx = {"macro": macro, "klines_1d": klines, "events_upcoming_48h": []}

    with patch(
        "src.ai.macro_l5_adjudicator.MacroL5Adjudicator.adjudicate",
        return_value=_AI_PAYLOAD_RISK_OFF,
    ):
        out = Layer5Macro().compute(ctx, rules_version="v1")

    assert out["computation_method"] == "ai_assisted"
    assert out["macro_stance"] == "risk_off"
    assert out["macro_headwind_score"] == -6.0
    assert out["adjustment_guidance"]["position_cap_multiplier"] == 0.7
    assert "L5 AI assisted" in " ".join(out.get("notes") or [])


def test_layer5_falls_back_to_rule_when_ai_returns_none():
    macro = _make_macro_dict_full()
    ctx = {"macro": macro, "klines_1d": None, "events_upcoming_48h": []}

    with patch(
        "src.ai.macro_l5_adjudicator.MacroL5Adjudicator.adjudicate",
        return_value=None,
    ):
        out = Layer5Macro().compute(ctx, rules_version="v1")

    assert out["computation_method"] == "rule_based"
    assert out["macro_headwind_score"] == 0.0  # §6.8 fallback
    assert out["adjustment_guidance"]["stance_modifier"] == "neutral"


def test_layer5_skips_ai_when_completeness_below_50():
    """1 个 metric / 10 = 10% completeness → 不调 AI。"""
    rng = pd.date_range("2026-01-01", periods=120, freq="D")
    macro = {"dxy": pd.Series(range(120), index=rng, dtype=float)}
    ctx = {"macro": macro, "klines_1d": None, "events_upcoming_48h": []}

    call_count = {"n": 0}

    def fake_adjudicate(self, facts):
        call_count["n"] += 1
        return _AI_PAYLOAD_RISK_OFF

    with patch.object(
        __import__("src.ai.macro_l5_adjudicator",
                   fromlist=["MacroL5Adjudicator"]).MacroL5Adjudicator,
        "adjudicate", new=fake_adjudicate,
    ):
        out = Layer5Macro().compute(ctx, rules_version="v1")

    assert call_count["n"] == 0  # AI 未被调用
    assert out["computation_method"] == "rule_based"


# ============================================================
# 2. apply_l5_ai_loopback
# ============================================================

def _make_l4_output(*, after_l4_crowding=49.0, event_mult=1.0):
    """构造一个 L4 已经跑过的 output(走 composite rule-based macro)。"""
    return {
        "execution_permission_l4": "cautious_open",
        "overall_risk_level": "moderate",
        "position_cap_pct": 41.65,
        "position_cap": 0.4165,
        "position_cap_composition": {
            "base": 70.0,
            "after_l4_risk": 49.0,
            "l4_risk_multiplier": 0.9,
            "after_l4_crowding": after_l4_crowding,
            "l4_crowding_multiplier": 1.0,
            "after_l5_macro": 49.0,
            "l5_macro_headwind_multiplier": 1.0,
            "after_l4_event": 49.0 * event_mult,
            "l4_event_risk_multiplier": event_mult,
            "hard_floor_pct": 15.0,
            "hard_floor_applied_to_final": False,
            "final_before_floor_gate": 49.0 * event_mult,
            "final": 49.0 * event_mult,
        },
    }


def test_loopback_noop_when_l5_not_ai_assisted():
    l4 = _make_l4_output()
    l5 = {"computation_method": "rule_based",
          "macro_headwind_score": -6.0,
          "adjustment_guidance": {
              "stance_modifier": "challenge",
              "position_cap_multiplier": 0.7,
              "permission_adjustment": "tighten",
              "note": "n/a",
          }}
    out = apply_l5_ai_loopback(l4, l5)
    assert out is l4  # 同一对象,no-op


def test_loopback_applies_strong_headwind_multiplier():
    """AI 给 score=-6 → step 4 multiplier 落到 0.7 桶 → cap 缩。"""
    l4 = _make_l4_output(after_l4_crowding=49.0, event_mult=1.0)
    # original cap = 49 (after_l5_macro 1.0 × after_l4_event 1.0)
    l5 = {
        "computation_method": "ai_assisted",
        "macro_headwind_score": -6.0,
        "adjustment_guidance": {
            "stance_modifier": "challenge",
            "position_cap_multiplier": 0.7,
            "permission_adjustment": "neutral",
            "note": "headwind",
        },
    }
    out = apply_l5_ai_loopback(l4, l5)

    comp = out["position_cap_composition"]
    assert comp["l5_ai_override_applied"] is True
    assert comp["l5_macro_headwind_multiplier"] == 0.7
    # after_l5_macro = 49 × 0.7 = 34.3
    assert comp["after_l5_macro"] == pytest.approx(34.3, abs=0.01)
    # Sprint 1.5q:删除 step 5(× event_risk),final_before_floor_gate
    # 直接 = after_l5_macro
    assert comp["final_before_floor_gate"] == pytest.approx(34.3, abs=0.01)
    # final cap reflects new value
    assert out["position_cap_pct"] == pytest.approx(34.3, abs=0.01)
    assert comp["macro_headwind_score_source"] == "l5_ai"


def test_loopback_tighten_shifts_permission_one_step():
    l4 = _make_l4_output()
    l4["execution_permission_l4"] = "can_open"
    l5 = {
        "computation_method": "ai_assisted",
        "macro_headwind_score": -3.0,
        "adjustment_guidance": {
            "stance_modifier": "challenge",
            "position_cap_multiplier": 0.85,
            "permission_adjustment": "tighten",
            "note": "tighten one notch",
        },
    }
    out = apply_l5_ai_loopback(l4, l5)
    assert out["execution_permission_l4_pre_l5_ai"] == "can_open"
    assert out["execution_permission_l4"] == "cautious_open"


def test_loopback_loosen_shifts_permission_one_step():
    l4 = _make_l4_output()
    l4["execution_permission_l4"] = "ambush_only"
    l5 = {
        "computation_method": "ai_assisted",
        "macro_headwind_score": 2.0,
        "adjustment_guidance": {
            "stance_modifier": "support",
            "position_cap_multiplier": 1.05,
            "permission_adjustment": "loosen",
            "note": "tailwind, loosen",
        },
    }
    out = apply_l5_ai_loopback(l4, l5)
    assert out["execution_permission_l4_pre_l5_ai"] == "ambush_only"
    assert out["execution_permission_l4"] == "cautious_open"


# ============================================================
# 3. _shift_permission utility
# ============================================================

def test_shift_permission_tighter_clamps_at_protective():
    assert _shift_permission("protective", direction="tighter") == "protective"


def test_shift_permission_looser_clamps_at_can_open():
    assert _shift_permission("can_open", direction="looser") == "can_open"


def test_shift_permission_unknown_returns_unchanged():
    assert _shift_permission("weird", direction="tighter") == "weird"
