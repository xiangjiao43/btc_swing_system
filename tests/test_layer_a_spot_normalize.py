from __future__ import annotations

from src.ai.spot_strategy_normalizer import (
    fallback_layer_a_output,
    normalize_layer_a_output,
)


def test_normalize_invalid_spot_action_falls_back_to_hold():
    out = normalize_layer_a_output({
        "a5_spot_adjudicator": {
            "spot_action": "trend_short",
            "cycle_stage": "early_bull",
            "human_summary": "bad",
            "what_would_change_mind": ["x"],
        },
    })
    assert out["a5_spot_adjudicator"]["spot_action"] == "hold"
    assert "a5_invalid_spot_action_normalized_to_hold" in out["validator"]["violations"]


def test_normalize_invalid_cycle_stage_falls_back_to_unclear():
    out = normalize_layer_a_output({
        "a1_cycle_stage": {"cycle_stage": "moon", "human_summary": "x"},
        "a5_spot_adjudicator": {
            "spot_action": "hold",
            "cycle_stage": "moon",
            "human_summary": "x",
            "what_would_change_mind": ["x"],
        },
    })
    assert out["a1_cycle_stage"]["cycle_stage"] == "unclear"
    assert out["a5_spot_adjudicator"]["cycle_stage"] == "unclear"
    assert "a1_invalid_cycle_stage_normalized_to_unclear" in out["validator"]["warnings"]


def test_fallback_output_is_displayable_hold_low_confidence():
    out = fallback_layer_a_output("AI failed")
    assert out["enabled"] is True
    assert out["a5_spot_adjudicator"]["spot_action"] == "hold"
    assert out["a5_spot_adjudicator"]["confidence"] == "low"
    assert out["a5_spot_adjudicator"]["human_summary"]


def test_boundary_model_notes_do_not_create_layer_b_like_warning():
    out = normalize_layer_a_output({
        "a5_spot_adjudicator": {
            "spot_action": "hold",
            "cycle_stage": "early_bull",
            "human_summary": "保持观察",
            "do_not_do": ["不要做空", "不创建 thesis，不进入虚拟账户"],
            "what_would_change_mind": ["链上证据改善"],
        },
        "model_notes": ["Layer A 不使用 A/B/C 机会等级"],
    })
    assert "layer_a_output_contains_layer_b_like_terms" not in out["validator"]["warnings"]


def test_actionable_model_notes_keep_layer_b_like_warning():
    out = normalize_layer_a_output({
        "a5_spot_adjudicator": {
            "spot_action": "hold",
            "cycle_stage": "early_bull",
            "human_summary": "保持观察",
            "what_would_change_mind": ["链上证据改善"],
        },
        "model_notes": ["建议做空"],
    })
    assert "layer_a_output_contains_layer_b_like_terms" in out["validator"]["warnings"]
