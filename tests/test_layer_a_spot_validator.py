from __future__ import annotations

from src.ai.spot_strategy_normalizer import normalize_layer_a_output
from src.ai.spot_validator import validate_spot_strategy_output


def _valid_output(action: str = "hold"):
    return normalize_layer_a_output({
        "a1_cycle_stage": {"cycle_stage": "early_bull", "human_summary": "阶段偏早"},
        "a4_spot_risk": {"spot_risk_level": "moderate", "human_summary": "风险中等"},
        "a5_spot_adjudicator": {
            "spot_action": action,
            "cycle_stage": "early_bull",
            "confidence": "medium",
            "headline": "现货保持观察",
            "human_summary": "证据平衡，现货保持观察。",
            "supporting_evidence": ["链上估值不高"],
            "opposing_evidence": ["宏观仍有压力"],
            "what_would_change_mind": ["ETF flow 连续转强"],
            "data_quality_notes": ["部分高价值候选因子未接入"],
        },
    })


def test_short_output_triggers_violation():
    out = _valid_output()
    out["a5_spot_adjudicator"]["human_summary"] = "建议 short"
    guard = validate_spot_strategy_output(out)
    assert guard["passed"] is False
    assert any("forbidden_layer_b_or_short_term" in v for v in guard["violations"])


def test_abc_grade_output_triggers_violation():
    out = _valid_output()
    out["model_notes"].append("A/B/C grade is B")
    guard = validate_spot_strategy_output(out)
    assert guard["passed"] is False


def test_aggressive_buy_requires_two_sided_evidence():
    out = _valid_output("aggressive_buy")
    out["a5_spot_adjudicator"]["opposing_evidence"] = []
    guard = validate_spot_strategy_output(out)
    assert "aggressive_buy_missing_opposing_evidence" in guard["violations"]


def test_valid_hold_passes_guardrail():
    guard = validate_spot_strategy_output(_valid_output())
    assert guard["passed"] is True

