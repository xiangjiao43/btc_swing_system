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


def test_descriptive_funding_short_text_does_not_create_warning():
    out = normalize_layer_a_output({
        "a4_spot_risk": {
            "human_summary": "负资金费率说明做多需支付做空，属于机制解释。",
        },
        "a5_spot_adjudicator": {
            "spot_action": "hold",
            "cycle_stage": "early_bull",
            "human_summary": "保持观察",
            "what_would_change_mind": ["链上证据改善"],
        },
    })
    assert "layer_a_output_contains_layer_b_like_terms" not in out["validator"]["warnings"]


def test_confidence_cap_downgrades_high_when_five_critical_factors_missing():
    missing = [
        {"factor": name, "project_status": "not_found"}
        for name in (
            "rhodl_ratio", "reserve_risk", "puell_multiple",
            "lth_net_position_change", "lth_sopr",
        )
    ]
    out = normalize_layer_a_output({
        "a1_cycle_stage": {
            "cycle_stage": "accumulation",
            "confidence": "high",
            "human_summary": "偏吸筹",
        },
        "a2_onchain_macro": {
            "onchain_macro_stance": "bullish",
            "confidence": "high",
            "human_summary": "偏多",
        },
        "a5_spot_adjudicator": {
            "spot_action": "dca_buy",
            "cycle_stage": "accumulation",
            "confidence": "high",
            "human_summary": "分批买入",
            "what_would_change_mind": ["关键因子改善"],
        },
        "unavailable_factors": missing,
    })
    assert out["factor_coverage"]["critical_unavailable_count"] == 5
    assert out["factor_coverage"]["confidence_cap"] == "medium"
    assert out["a1_cycle_stage"]["confidence"] == "medium"
    assert out["a2_onchain_macro"]["confidence"] == "medium"
    assert out["a5_spot_adjudicator"]["confidence"] == "medium"
    assert "confidence_capped_by_factor_coverage" in out["validator"]["warnings"]
    assert out["confidence_adjustments"]


def test_confidence_cap_keeps_high_when_critical_missing_is_small():
    out = normalize_layer_a_output({
        "a5_spot_adjudicator": {
            "spot_action": "hold",
            "cycle_stage": "early_bull",
            "confidence": "high",
            "human_summary": "保持观察",
            "what_would_change_mind": ["关键因子恶化"],
        },
        "unavailable_factors": [
            {"factor": "rhodl_ratio", "project_status": "not_found"},
            {"factor": "options_iv_skew", "project_status": "not_found"},
        ],
    })
    assert out["factor_coverage"]["critical_unavailable_count"] == 1
    assert out["factor_coverage"]["confidence_cap"] == "high"
    assert out["a5_spot_adjudicator"]["confidence"] == "high"


def test_confidence_cap_downgrades_to_low_when_coverage_ratio_is_low():
    out = normalize_layer_a_output({
        "a5_spot_adjudicator": {
            "spot_action": "hold",
            "cycle_stage": "unclear",
            "confidence": "high",
            "human_summary": "数据不足",
            "what_would_change_mind": ["数据恢复"],
        },
        "factor_coverage": {"coverage_ratio": 0.25},
        "unavailable_factors": [
            {"factor": "rhodl_ratio", "project_status": "not_found"},
        ],
    })
    assert out["factor_coverage"]["confidence_cap"] == "low"
    assert out["a5_spot_adjudicator"]["confidence"] == "low"
