"""tests/ai/test_orchestrator_event_a.py — Sprint 1.10-G commit 5b 单测。

覆盖 AIOrchestrator.run_event_a 入口(简化 A 应急 AI,event_price 触发用)。
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.ai.agents.emergency_simplified_a import EmergencySimplifiedA
from src.ai.orchestrator import AIOrchestrator


def _mock_emergency_agent(out: dict[str, Any], raise_exc: bool = False) -> Any:
    """Mock EmergencySimplifiedA 的 analyze。"""
    a = MagicMock()
    full = {**out}
    full.setdefault("status", "success")
    if raise_exc:
        a.analyze.side_effect = RuntimeError("simulated AI failure")
    else:
        a.analyze.return_value = full
    a._fallback_output.return_value = {
        "agent": "emergency_simplified_a",
        "status": "degraded",
        "thesis_still_valid": None,
        "immediate_action": "maintain",
        "reasoning": "fallback",
    }
    return a


def test_run_event_a_returns_layers_emergency():
    """happy:agent 返 maintain → result.layers.emergency_simplified_a。"""
    payload = {
        "thesis_still_valid": True,
        "immediate_action": "maintain",
        "reasoning": "持仓 + 异动温和",
    }
    agent = _mock_emergency_agent(payload)
    orch = AIOrchestrator(agents={"emergency_simplified_a": agent})
    result = orch.run_event_a(
        event_type="event_price",
        triggered_at_price=78500.0,
        baseline_price=75000.0,
        current_strategy_state="LONG_HOLD",
        key_factors={"funding_rate": 0.0001},
        active_thesis={"direction": "long", "lifecycle_stage": "open"},
    )
    assert result["status"] == "ok"
    assert result["run_trigger"] == "event_price"
    assert result["current_strategy_state"] == "LONG_HOLD"
    layers = result["layers"]
    assert "emergency_simplified_a" in layers
    out = layers["emergency_simplified_a"]
    assert out["immediate_action"] == "maintain"
    assert out["thesis_still_valid"] is True


def test_run_event_a_pct_change_calculation():
    """pct_change = (triggered - baseline) / baseline。"""
    agent = _mock_emergency_agent({
        "thesis_still_valid": None, "immediate_action": "wait_next_full",
        "reasoning": "x",
    })
    orch = AIOrchestrator(agents={"emergency_simplified_a": agent})
    result = orch.run_event_a(
        event_type="event_price",
        triggered_at_price=75000.0 * 1.05,
        baseline_price=75000.0,
        current_strategy_state="FLAT",
    )
    assert abs(result["pct_change"] - 0.05) < 1e-9


def test_run_event_a_emergency_exit_action():
    """持仓 + thesis 失效 → emergency_exit。"""
    agent = _mock_emergency_agent({
        "thesis_still_valid": False,
        "immediate_action": "emergency_exit",
        "reasoning": "stop_loss 临近击穿,thesis 失效",
    })
    orch = AIOrchestrator(agents={"emergency_simplified_a": agent})
    result = orch.run_event_a(
        event_type="event_price",
        triggered_at_price=72500.0,  # -3.3% from baseline 75000
        baseline_price=75000.0,
        current_strategy_state="LONG_HOLD",
        active_thesis={
            "direction": "long", "lifecycle_stage": "open",
            "stop_loss_price": 72000.0,
        },
    )
    assert result["layers"]["emergency_simplified_a"]["immediate_action"] == "emergency_exit"


def test_run_event_a_ai_failure_falls_back():
    """agent.analyze 抛 → fallback maintain + status='degraded'。"""
    agent = _mock_emergency_agent({}, raise_exc=True)
    orch = AIOrchestrator(agents={"emergency_simplified_a": agent})
    result = orch.run_event_a(
        event_type="event_price",
        triggered_at_price=78500.0, baseline_price=75000.0,
        current_strategy_state="FLAT",
    )
    assert result["status"] == "degraded"
    out = result["layers"]["emergency_simplified_a"]
    assert out["immediate_action"] == "maintain"


def test_run_event_a_normalizes_invalid_action():
    """agent 返非法 immediate_action → orchestrator normalize 为 maintain。"""
    agent = _mock_emergency_agent({
        "thesis_still_valid": True,
        "immediate_action": "bogus_action",  # 非法
        "reasoning": "x",
    })
    orch = AIOrchestrator(agents={"emergency_simplified_a": agent})
    result = orch.run_event_a(
        event_type="event_price",
        triggered_at_price=78500.0, baseline_price=75000.0,
        current_strategy_state="FLAT",
    )
    out = result["layers"]["emergency_simplified_a"]
    assert out["immediate_action"] == "maintain"
    notes = out.get("notes") or []
    assert any("invalid_action_normalized" in n for n in notes)


def test_run_event_a_no_active_thesis():
    """无 active_thesis → ctx.active_thesis=None 传给 agent。"""
    agent = _mock_emergency_agent({
        "thesis_still_valid": None,
        "immediate_action": "wait_next_full",
        "reasoning": "空仓无 thesis,等下次 run",
    })
    orch = AIOrchestrator(agents={"emergency_simplified_a": agent})
    result = orch.run_event_a(
        event_type="event_price",
        triggered_at_price=78500.0, baseline_price=75000.0,
        current_strategy_state="FLAT",
        active_thesis=None,
    )
    assert result["layers"]["emergency_simplified_a"]["thesis_still_valid"] is None
    # ctx 传入的 active_thesis 应该是 None
    call = agent.analyze.call_args
    ctx = call.args[0] if call.args else call.kwargs.get("context")
    assert ctx["active_thesis"] is None


def test_run_event_a_run_trigger_passed_through():
    """event_type 字段在 result 里。"""
    agent = _mock_emergency_agent({
        "thesis_still_valid": True, "immediate_action": "maintain",
        "reasoning": "x",
    })
    orch = AIOrchestrator(agents={"emergency_simplified_a": agent})
    result = orch.run_event_a(
        event_type="event_price_holding",
        triggered_at_price=78500.0, baseline_price=75000.0,
        current_strategy_state="LONG_HOLD",
    )
    assert result["run_trigger"] == "event_price_holding"
