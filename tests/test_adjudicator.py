"""
tests/test_adjudicator.py — Sprint 1.5b 单测(对齐建模 14 档状态机 + §6.5)

覆盖:
  * 硬约束前置:各种 permission / state / cap / extreme / fallback / cold_start
    情况下不调 AI
  * AI 路径:grade + permission + state 正常,mock AI 返回合法/非法 JSON
  * 约束覆盖:AI 返回违反硬约束的 action → override
  * evidence_gaps:L5 数据缺失应被标记
  * cold_start 优先于 L3 grade
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.ai.adjudicator import AIAdjudicator


# ==================================================================
# Helpers
# ==================================================================

def _mock_ai_response(
    action: str = "open_long",
    direction: str = "long",
    confidence: float = 0.7,
    rationale: str = "mock rationale",
    evidence_gaps: list[str] = None,
    *,
    raw_override: str = None,
    model: str = "claude-sonnet-4-5-20250929",
    tokens_in: int = 120,
    tokens_out: int = 80,
) -> MagicMock:
    if raw_override is not None:
        content = raw_override
    else:
        content = json.dumps({
            "action": action,
            "direction": direction,
            "confidence": confidence,
            "rationale": rationale,
            "evidence_gaps": evidence_gaps or [],
        }, ensure_ascii=False)
    r = MagicMock()
    r.model = model
    r.choices = [MagicMock()]
    r.choices[0].message.content = content
    r.usage = MagicMock(prompt_tokens=tokens_in, completion_tokens=tokens_out)
    return r


def _state(
    *,
    l1_regime: str = "trend_up",
    l1_volatility: str = "normal",
    l2_stance: str = "bullish",
    l2_confidence: float = 0.7,
    l2_phase: str = "early",
    l3_grade: str = "A",
    l3_permission: str = "can_open",
    l4_cap: float = 0.15,
    l4_risk: str = "moderate",
    l5_env: str = "risk_on",
    l5_macro_stance: str = "risk_on",
    l5_headwind: str = "tailwind",
    l5_completeness: float = 80.0,
    l5_health: str = "healthy",
    l5_extreme_event: bool = False,
    sm_state: str = "FLAT",
    cold_start: bool = False,
    fallback_level: Any = None,
    account: dict = None,
) -> dict[str, Any]:
    return {
        "evidence_reports": {
            "layer_1": {
                "regime": l1_regime,
                "volatility_regime": l1_volatility,
                "health_status": "healthy",
            },
            "layer_2": {
                "stance": l2_stance,
                "stance_confidence": l2_confidence,
                "phase": l2_phase,
                "health_status": "healthy",
            },
            "layer_3": {
                "opportunity_grade": l3_grade,
                "execution_permission": l3_permission,
                "anti_pattern_flags": [],
                "health_status": "healthy",
            },
            "layer_4": {
                "position_cap": l4_cap,
                "stop_loss_reference": {"price": 45000},
                "risk_reward_ratio": 2.2,
                "overall_risk_level": l4_risk,
                "health_status": "healthy",
            },
            "layer_5": {
                "macro_environment": l5_env,
                "macro_stance": l5_macro_stance,
                "macro_headwind_vs_btc": l5_headwind,
                "data_completeness_pct": l5_completeness,
                "health_status": l5_health,
                "extreme_event_detected": l5_extreme_event,
            },
        },
        "state_machine": {
            "current_state": sm_state,
            "previous_state": None,
        },
        "cold_start": {
            "warming_up": cold_start,
            "runs_completed": 0 if cold_start else 100,
        },
        "account_state": account or {},
        "pipeline_meta": {"fallback_level": fallback_level},
    }


# ==================================================================
# 硬约束路径:不调 AI
# ==================================================================

class TestHardConstraints:
    def test_l3_watch_forces_watch(self):
        client = MagicMock()
        adj = AIAdjudicator(openai_client=client)
        state = _state(l3_permission="watch", l3_grade="A",
                       sm_state="FLAT")
        out = adj.decide(state)
        assert out["action"] == "watch"
        assert out["status"] == "success"
        client.chat.completions.create.assert_not_called()

    def test_l3_protective_with_long_position_reduces(self):
        client = MagicMock()
        adj = AIAdjudicator(openai_client=client)
        state = _state(
            l3_permission="protective",
            account={"long_position_size": 0.5},
        )
        out = adj.decide(state)
        assert out["action"] == "reduce_long"
        assert out["direction"] == "long"
        client.chat.completions.create.assert_not_called()

    def test_l4_cap_zero_forces_watch(self):
        client = MagicMock()
        adj = AIAdjudicator(openai_client=client)
        state = _state(l4_cap=0.0, l3_permission="can_open",
                       l3_grade="A", sm_state="FLAT")
        out = adj.decide(state)
        assert out["action"] == "watch"
        client.chat.completions.create.assert_not_called()

    def test_protection_state_forces_pause(self):
        client = MagicMock()
        adj = AIAdjudicator(openai_client=client)
        state = _state(sm_state="PROTECTION")
        out = adj.decide(state)
        assert out["action"] == "pause"
        client.chat.completions.create.assert_not_called()

    def test_l5_extreme_event_forces_pause(self):
        client = MagicMock()
        adj = AIAdjudicator(openai_client=client)
        state = _state(l5_extreme_event=True, sm_state="FLAT")
        out = adj.decide(state)
        assert out["action"] == "pause"
        client.chat.completions.create.assert_not_called()

    def test_cold_start_forces_watch_even_with_grade_A(self):
        client = MagicMock()
        adj = AIAdjudicator(openai_client=client)
        state = _state(
            l3_grade="A", l3_permission="can_open",
            sm_state="FLAT", cold_start=True,
        )
        out = adj.decide(state)
        assert out["action"] == "watch"
        client.chat.completions.create.assert_not_called()

    def test_hold_only_forces_hold(self):
        client = MagicMock()
        adj = AIAdjudicator(openai_client=client)
        state = _state(l3_permission="hold_only", l3_grade="A")
        out = adj.decide(state)
        assert out["action"] == "hold"
        client.chat.completions.create.assert_not_called()

    def test_fallback_level_2_forces_watch(self):
        client = MagicMock()
        adj = AIAdjudicator(openai_client=client)
        state = _state(
            sm_state="FLAT", l3_grade="A", l3_permission="can_open",
            fallback_level="level_2",
        )
        out = adj.decide(state)
        assert out["action"] == "watch"
        client.chat.completions.create.assert_not_called()

    def test_fallback_level_3_forces_watch(self):
        client = MagicMock()
        adj = AIAdjudicator(openai_client=client)
        state = _state(
            sm_state="FLAT", l3_grade="A", l3_permission="can_open",
            fallback_level=3,
        )
        out = adj.decide(state)
        assert out["action"] == "watch"
        client.chat.completions.create.assert_not_called()

    def test_post_protection_reassess_forces_hold(self):
        client = MagicMock()
        adj = AIAdjudicator(openai_client=client)
        state = _state(
            sm_state="POST_PROTECTION_REASSESS",
            l3_grade="A", l3_permission="can_open",
        )
        out = adj.decide(state)
        assert out["action"] == "hold"
        client.chat.completions.create.assert_not_called()


# ==================================================================
# AI 路径(新 14 档)
# ==================================================================

class TestAIPath:
    def test_flat_with_grade_A_bullish_calls_ai(self):
        """FLAT + grade A + bullish + can_open → AI 路径(建议进 LONG_PLANNED)"""
        client = MagicMock()
        client.chat.completions.create.return_value = _mock_ai_response(
            action="open_long", direction="long", confidence=0.72,
        )
        adj = AIAdjudicator(openai_client=client)
        state = _state(
            l2_stance="bullish", l3_grade="A", l3_permission="can_open",
            sm_state="FLAT",
        )
        out = adj.decide(state)
        assert out["action"] == "open_long"
        assert out["status"] == "success"
        client.chat.completions.create.assert_called_once()

    def test_flat_with_grade_B_bearish_calls_ai(self):
        client = MagicMock()
        client.chat.completions.create.return_value = _mock_ai_response(
            action="open_short", direction="short", confidence=0.6,
        )
        adj = AIAdjudicator(openai_client=client)
        state = _state(
            l2_stance="bearish", l3_grade="B", l3_permission="cautious_open",
            sm_state="FLAT",
        )
        out = adj.decide(state)
        assert out["action"] == "open_short"

    def test_long_hold_calls_ai_for_hold_or_reduce(self):
        client = MagicMock()
        client.chat.completions.create.return_value = _mock_ai_response(
            action="hold", direction=None, confidence=0.7,
        )
        adj = AIAdjudicator(openai_client=client)
        state = _state(
            l2_stance="bullish", l3_grade="A", l3_permission="can_open",
            sm_state="LONG_HOLD",
            account={"long_position_size": 0.5},
        )
        out = adj.decide(state)
        assert out["action"] == "hold"

    def test_ai_invalid_json_retries_then_degrades(self):
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            _mock_ai_response(raw_override="this is not JSON at all"),
            _mock_ai_response(raw_override="still garbage, no braces here"),
        ]
        adj = AIAdjudicator(openai_client=client)
        state = _state(
            l3_grade="A", l3_permission="can_open",
            sm_state="FLAT",
        )
        out = adj.decide(state)
        assert out["status"] == "degraded_structured"
        assert out["action"] == "watch"
        assert "ai_parse_failed" in out["notes"]
        assert client.chat.completions.create.call_count == 2

    def test_ai_violating_hard_constraint_gets_overridden(self):
        """FLAT + bullish,AI 返回 open_short → override。"""
        client = MagicMock()
        client.chat.completions.create.return_value = _mock_ai_response(
            action="open_short", direction="short", confidence=0.8,
        )
        adj = AIAdjudicator(openai_client=client)
        state = _state(
            l2_stance="bullish", l3_grade="A", l3_permission="can_open",
            sm_state="FLAT",
        )
        out = adj.decide(state)
        assert out["action"] != "open_short"
        assert "ai_action_overridden_by_constraints" in out["notes"]

    def test_evidence_gaps_include_macro_incomplete(self):
        client = MagicMock()
        client.chat.completions.create.return_value = _mock_ai_response(
            action="open_long", direction="long", confidence=0.65,
            evidence_gaps=[],
        )
        adj = AIAdjudicator(openai_client=client)
        state = _state(
            l3_grade="A", l3_permission="can_open",
            sm_state="FLAT",
            l5_completeness=20.0,
            l5_health="degraded",
        )
        out = adj.decide(state)
        assert "macro_data_incomplete" in out["evidence_gaps"]


# ==================================================================
# 非 AI、非硬约束:规则路径 watch
# ==================================================================

class TestRulePathNeutral:
    def test_grade_none_skips_ai(self):
        client = MagicMock()
        adj = AIAdjudicator(openai_client=client)
        state = _state(
            l2_stance="neutral",
            l3_grade="none",
            l3_permission="can_open",
            sm_state="FLAT",
        )
        out = adj.decide(state)
        assert out["action"] == "watch"
        assert out["status"] == "success"
        client.chat.completions.create.assert_not_called()

    def test_flip_watch_cooling_with_grade_none_rule_path(self):
        """FLIP_WATCH + grade=none(还没到反手门槛)→ 规则 watch。"""
        client = MagicMock()
        adj = AIAdjudicator(openai_client=client)
        state = _state(
            sm_state="FLIP_WATCH", l3_grade="none", l3_permission="can_open",
        )
        out = adj.decide(state)
        assert out["action"] == "watch"
        client.chat.completions.create.assert_not_called()


# ==================================================================
# Output shape
# ==================================================================

class TestOutputShape:
    def test_output_has_all_required_fields(self):
        client = MagicMock()
        client.chat.completions.create.return_value = _mock_ai_response()
        adj = AIAdjudicator(openai_client=client)
        state = _state()
        out = adj.decide(state)
        for field in (
            "action", "direction", "confidence", "rationale",
            "constraints", "evidence_gaps", "model_used",
            "tokens_in", "tokens_out", "latency_ms", "status", "notes",
        ):
            assert field in out, f"missing field: {field}"
        for c in (
            "max_position_size", "stop_loss_reference",
            "event_risk_warning", "execution_permission_binding",
        ):
            assert c in out["constraints"]
