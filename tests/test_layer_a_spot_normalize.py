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
    assert out["a1_cycle_stage"]["cycle_stage"] == "trend_hold"
    assert out["a5_spot_adjudicator"]["cycle_stage"] == "trend_hold"
    assert "a1_invalid_cycle_stage_normalized_to_trend_hold" in out["validator"]["warnings"]


def test_fallback_output_is_displayable_hold_low_confidence():
    out = fallback_layer_a_output("AI failed")
    assert out["enabled"] is True
    assert out["a5_spot_adjudicator"]["spot_action"] == "hold"
    assert out["a1_cycle_stage"]["official_cycle_stage"] == "trend_hold"
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


def test_confidence_cap_downgrades_high_when_factor_coverage_is_low():
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
        "unavailable_factors": [],
        "factor_coverage": {"coverage_ratio": 0.45},
    })
    assert out["factor_coverage"]["critical_unavailable_count"] == 0
    assert out["factor_coverage"]["confidence_cap"] == "low"
    assert out["a1_cycle_stage"]["confidence"] == "low"
    assert out["a2_onchain_macro"]["confidence"] == "low"
    assert out["a5_spot_adjudicator"]["confidence"] == "low"
    assert "confidence_capped_by_factor_coverage" in out["validator"]["warnings"]
    assert out["confidence_adjustments"]


def test_confidence_cap_keeps_high_when_only_noncritical_candidates_are_missing():
    out = normalize_layer_a_output({
        "a5_spot_adjudicator": {
            "spot_action": "hold",
            "cycle_stage": "early_bull",
            "confidence": "high",
            "human_summary": "保持观察",
            "what_would_change_mind": ["关键因子恶化"],
        },
        "unavailable_factors": [
            {"factor": "options_iv_skew", "project_status": "not_found"},
            {"factor": "options_iv_skew", "project_status": "not_found"},
        ],
    })
    assert out["factor_coverage"]["critical_unavailable_count"] == 0
    assert out["factor_coverage"]["confidence_cap"] == "high"
    assert out["a5_spot_adjudicator"]["confidence"] == "high"


def test_confidence_cap_downgrades_when_integrated_factor_stale_count_is_high():
    out = normalize_layer_a_output({
        "a5_spot_adjudicator": {
            "spot_action": "hold",
            "cycle_stage": "trend_hold",
            "confidence": "high",
            "human_summary": "保持观察",
            "what_would_change_mind": ["关键因子恢复"],
        },
        "factor_coverage": {
            "coverage_ratio": 0.85,
            "stale_factor_count": 5,
            "missing_integrated_factor_count": 0,
        },
        "unavailable_factors": [],
    })
    assert out["factor_coverage"]["confidence_cap"] == "medium"
    assert out["a5_spot_adjudicator"]["confidence"] == "medium"


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


def test_legacy_layer_a_actions_are_normalized_to_five_action_names():
    out = normalize_layer_a_output({
        "a1_cycle_stage": {
            "cycle_stage": "late_bull",
            "human_summary": "高位派发特征",
        },
        "a3_spot_opportunity": {
            "preferred_action_candidate": "scale_out",
            "human_summary": "分批卖出",
        },
        "a5_spot_adjudicator": {
            "spot_action": "aggressive_sell",
            "cycle_stage": "late_bull",
            "confidence": "medium",
            "human_summary": "强力卖出",
            "what_would_change_mind": ["过热解除"],
        },
    })
    assert out["a3_spot_opportunity"]["preferred_action_candidate"] == "scale_sell"
    assert out["a5_spot_adjudicator"]["cycle_stage"] == "distribution"
    assert out["a5_spot_adjudicator"]["spot_action"] == "scale_sell"


def test_accumulation_to_trend_hold_is_pending_on_first_confirmation():
    out = normalize_layer_a_output({
        "previous_layer_a_state": {
            "cycle_stage_model_version": "layer_a_five_stage_v1",
            "a1_cycle_stage": {"official_cycle_stage": "accumulation"},
        },
        "a1_cycle_stage": {
            "raw_stage_assessment": "trend_hold",
            "cycle_stage": "trend_hold",
            "confidence": "high",
            "human_summary": "趋势持有特征初现",
        },
        "a4_spot_risk": {"spot_risk_level": "moderate", "human_summary": "风险中等"},
        "a5_spot_adjudicator": {
            "spot_action": "hold",
            "cycle_stage": "trend_hold",
            "confidence": "high",
            "human_summary": "持有",
            "what_would_change_mind": ["证据恶化"],
        },
        "factor_coverage": {"coverage_ratio": 0.9, "stale_factor_count": 0},
    })
    assert out["a1_cycle_stage"]["raw_stage_assessment"] == "trend_hold"
    assert out["a1_cycle_stage"]["official_cycle_stage"] == "accumulation"
    assert out["a1_cycle_stage"]["transition_status"] == "pending"
    assert out["a1_cycle_stage"]["confirmation_count"] == 1
    assert out["a1_cycle_stage"]["confirmation_required"] == 2
    assert out["a5_spot_adjudicator"]["cycle_stage"] == "accumulation"
    assert out["a5_spot_adjudicator"]["confidence"] == "medium"


def test_adjacent_stage_confirms_after_second_confirmation():
    out = normalize_layer_a_output({
        "previous_layer_a_state": {
            "cycle_stage_model_version": "layer_a_five_stage_v1",
            "a1_cycle_stage": {"official_cycle_stage": "accumulation"},
            "stage_transition": {
                "transition_status": "pending",
                "raw_stage_assessment": "trend_hold",
                "previous_official_stage": "accumulation",
                "confirmation_count": 1,
            },
        },
        "a1_cycle_stage": {
            "raw_stage_assessment": "trend_hold",
            "cycle_stage": "trend_hold",
            "confidence": "medium",
            "human_summary": "趋势持有特征连续出现",
        },
        "a4_spot_risk": {"spot_risk_level": "moderate", "human_summary": "风险中等"},
        "a5_spot_adjudicator": {
            "spot_action": "hold",
            "cycle_stage": "trend_hold",
            "confidence": "medium",
            "human_summary": "持有",
            "what_would_change_mind": ["证据恶化"],
        },
        "factor_coverage": {"coverage_ratio": 0.9, "stale_factor_count": 0},
    })
    assert out["a1_cycle_stage"]["official_cycle_stage"] == "trend_hold"
    assert out["a1_cycle_stage"]["transition_status"] == "confirmed"
    assert out["a1_cycle_stage"]["confirmation_count"] == 2


def test_cross_stage_jump_requires_three_confirmations():
    out = normalize_layer_a_output({
        "previous_layer_a_state": {
            "cycle_stage_model_version": "layer_a_five_stage_v1",
            "a1_cycle_stage": {"official_cycle_stage": "deep_value"},
        },
        "a1_cycle_stage": {
            "raw_stage_assessment": "trend_hold",
            "cycle_stage": "trend_hold",
            "confidence": "medium",
            "human_summary": "跨级特征出现",
        },
        "a4_spot_risk": {"spot_risk_level": "moderate", "human_summary": "风险中等"},
        "a5_spot_adjudicator": {
            "spot_action": "hold",
            "cycle_stage": "trend_hold",
            "confidence": "medium",
            "human_summary": "持有",
            "what_would_change_mind": ["证据恶化"],
        },
        "factor_coverage": {"coverage_ratio": 0.9, "stale_factor_count": 0},
    })
    assert out["a1_cycle_stage"]["official_cycle_stage"] == "deep_value"
    assert out["a1_cycle_stage"]["transition_status"] == "pending"
    assert out["a1_cycle_stage"]["confirmation_required"] == 3


def test_stale_factors_block_stage_upgrade_confirmation():
    out = normalize_layer_a_output({
        "previous_layer_a_state": {
            "cycle_stage_model_version": "layer_a_five_stage_v1",
            "a1_cycle_stage": {"official_cycle_stage": "accumulation"},
            "stage_transition": {
                "transition_status": "pending",
                "raw_stage_assessment": "trend_hold",
                "previous_official_stage": "accumulation",
                "confirmation_count": 1,
            },
        },
        "a1_cycle_stage": {
            "raw_stage_assessment": "trend_hold",
            "cycle_stage": "trend_hold",
            "confidence": "high",
            "human_summary": "趋势持有特征连续出现",
        },
        "a4_spot_risk": {"spot_risk_level": "moderate", "human_summary": "风险中等"},
        "a5_spot_adjudicator": {
            "spot_action": "hold",
            "cycle_stage": "trend_hold",
            "confidence": "high",
            "human_summary": "持有",
            "what_would_change_mind": ["证据恶化"],
        },
        "factor_coverage": {"coverage_ratio": 0.9, "stale_factor_count": 2},
    })
    assert out["a1_cycle_stage"]["official_cycle_stage"] == "accumulation"
    assert out["a1_cycle_stage"]["transition_status"] == "pending"
    assert "过期" in out["a1_cycle_stage"]["confidence_cap_reason"]
