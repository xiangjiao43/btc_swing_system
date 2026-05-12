from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from tests.ai.test_orchestrator import (
    _build_context,
    _make_layered_mock_agents,
)
from src.ai.orchestrator import AIOrchestrator


def _agent(out: dict[str, Any]):
    a = MagicMock()
    a.analyze.return_value = {**out, "status": "success"}
    a._fallback_output.return_value = {**out, "status": "degraded"}
    return a


def test_layer_a_ai_failure_does_not_change_layer_b_master():
    agents = _make_layered_mock_agents(
        {"regime": "trend_up", "confidence": 0.9},
        {"stance": "bullish", "phase": "early", "confidence": 0.8},
        {"opportunity_grade": "B", "execution_permission": "cautious_open"},
        {"risk_tier": "moderate", "hard_invalidation_levels": [], "risk_breakdown": {}},
        {"macro_stance": "neutral", "extreme_event_detected": False},
        {
            "state_transition": {"from_state": "FLAT", "to_state": "FLAT"},
            "trade_plan": {"action": "watch", "direction": None},
            "counter_arguments": ["x"],
            "narrative": "Layer B unchanged",
            "confidence": 0.5,
            "data_completeness_pct": 90,
        },
    )
    agents["a1"] = _agent({"cycle_stage": "early_bull", "human_summary": "x"})
    agents["a2"] = _agent({"onchain_macro_stance": "bullish", "human_summary": "x"})
    agents["a3"] = _agent({"preferred_action_candidate": "hold", "human_summary": "x"})
    agents["a4"] = _agent({"spot_risk_level": "moderate", "human_summary": "x"})
    agents["a5"] = _agent({
        "spot_action": "trend_short",
        "cycle_stage": "early_bull",
        "human_summary": "bad output",
        "what_would_change_mind": ["x"],
    })

    ctx = _build_context()
    ctx["layer_a_spot_context"] = {
        "unavailable_factors": [],
        "data_quality_notes": ["ok"],
    }
    result = AIOrchestrator(agents=agents).run_full_a(ctx)

    assert result["layers"]["master"]["trade_plan"]["action"] == "watch"
    assert "layer_a_spot_strategy" not in result["layers"]
    assert result["layer_a_spot_strategy"]["a5_spot_adjudicator"]["spot_action"] == "hold"
    assert result["layer_a_spot_strategy"]["validator"]["passed"] is False
    assert "virtual_account" not in result["layer_a_spot_strategy"]
    assert "thesis" not in result["layer_a_spot_strategy"]
