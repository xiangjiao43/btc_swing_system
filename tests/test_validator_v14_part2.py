"""Sprint 1.10-E 单测:Validator 13-23(v1.4 §3.4.4-§3.4.8)。"""
from __future__ import annotations

import pytest

from src.ai.validator import (
    validator_13_objective_evidence,
    validator_14_counter_argument,
    validator_15_confidence_cap,
    validator_16_change_mind,
    validator_17_stop_tightening,
    validator_18_14d_fuse,
    validator_19_60d_cap,
    validator_20_consecutive_fuse,
    validator_21_soft_resistance,
    validator_22_3day_fail,
    validator_23_conflict_resolution,
)


# ============================================================
# V13: objective_evidence 字符串匹配(D3=a)
# ============================================================

def test_v13_evidence_with_real_token_ok():
    """每条 evidence 含 input 中字段名(L3, DXY)→ 通过。"""
    out, act = validator_13_objective_evidence(
        {"new_thesis": {"objective_evidence": ["L3 grade=A", "DXY 当前 105"]}},
        {"l3_output": {"opportunity_grade": "A"}},
    )
    assert not act["validator_13_objective_evidence"]


def test_v13_evidence_no_real_token_violates():
    """evidence 不含 input token → 触发。"""
    out, act = validator_13_objective_evidence(
        {"new_thesis": {"objective_evidence": ["瞎编的内容", "完全不在 input"]}},
        {"l3_output": {"opportunity_grade": "A"}},
    )
    assert act["validator_13_objective_evidence"]


def test_v13_evidence_with_numeric_token_ok():
    """evidence 含 input 中数值 → 通过。"""
    out, act = validator_13_objective_evidence(
        {"thesis_assessment": {"objective_evidence": [
            "current_btc_price 76000 大于 last_5_assessments[0] 持续",
        ]}},
        {"current_btc_price": 76000.0},
    )
    assert not act["validator_13_objective_evidence"]


# ============================================================
# V14: counter_arguments
# ============================================================

def test_v14_counter_present_ok():
    out, act = validator_14_counter_argument(
        {"counter_arguments": ["funding 偏拥挤"]}, {},
    )
    assert not act["validator_14_counter_argument"]


def test_v14_counter_missing_violates():
    out, act = validator_14_counter_argument({"counter_arguments": []}, {})
    assert act["validator_14_counter_argument"]


def test_v14_counter_dict_format_ok():
    """counter_arguments 也接受 dict 格式 {text: '...'}(向后兼容)。"""
    out, act = validator_14_counter_argument(
        {"counter_arguments": [{"text": "funding 偏拥挤"}]}, {},
    )
    assert not act["validator_14_counter_argument"]


# ============================================================
# V15: confidence cap
# ============================================================

def test_v15_confidence_within_cap_ok():
    """confidence_score=70(0.7)≤ 0.95 × 0.90 = 0.855 → 不触发。"""
    out, act = validator_15_confidence_cap(
        {"new_thesis": {"confidence_score": 70}},
        {"data_completeness": 0.95, "historical_precedent_match": 0.90},
    )
    assert not act["validator_15_confidence_capped"]


def test_v15_confidence_exceeds_cap_capped():
    """confidence=90(0.9)> 0.7 × 0.7 = 0.49 → cap 到 49。"""
    out, act = validator_15_confidence_cap(
        {"new_thesis": {"confidence_score": 90}},
        {"data_completeness": 0.7, "historical_precedent_match": 0.7},
    )
    assert act["validator_15_confidence_capped"]
    assert out["new_thesis"]["confidence_score"] == 49.0


def test_v15_fallback_level_caps_to_70():
    """fallback_level=level_1 → cap < 0.7。"""
    out, act = validator_15_confidence_cap(
        {"new_thesis": {"confidence_score": 85}},
        {"data_completeness": 1.0, "historical_precedent_match": 1.0,
         "fallback_level": "level_1"},
    )
    assert act["validator_15_confidence_capped"]
    assert out["new_thesis"]["confidence_score"] < 70


# ============================================================
# V16: what_would_change_mind ≥ 3 客观
# ============================================================

def test_v16_three_objective_ok():
    out, act = validator_16_change_mind(
        {"what_would_change_mind": [
            "1D 收盘跌破 70000",
            "DXY 突破 108 持续 3 天",
            "L5 极端事件触发",
        ]}, {},
    )
    assert not act["validator_16_change_mind"]


def test_v16_less_than_3_violates():
    out, act = validator_16_change_mind(
        {"what_would_change_mind": ["1D 跌破 70000"]}, {},
    )
    assert act["validator_16_change_mind"]


def test_v16_subjective_not_counted():
    out, act = validator_16_change_mind(
        {"what_would_change_mind": [
            "1D 跌破 70000",
            "市场情绪转空",   # 主观
            "趋势反转",        # 主观
        ]}, {},
    )
    # 只 1 条客观 → 触发
    assert act["validator_16_change_mind"]


# ============================================================
# V17: stop_tightening 上限
# ============================================================

def test_v17_no_adjustment_skip():
    out, act = validator_17_stop_tightening(
        {"mode": "evaluate_existing",
         "thesis_assessment": {"still_valid": "weakened",
                                "stop_loss_adjustment": None}},
        {"stop_tightening_count_so_far": 0},
    )
    assert not act["validator_17_stop_tightening"]


def test_v17_third_tightening_blocked():
    """已收紧 2 次 → 第 3 次拒绝。"""
    out, act = validator_17_stop_tightening(
        {"mode": "evaluate_existing",
         "thesis_assessment": {"still_valid": "weakened",
                                "stop_loss_adjustment": 70000.0}},
        {"stop_tightening_count_so_far": 2},
    )
    assert act["validator_17_stop_tightening"]
    assert out["thesis_assessment"]["stop_loss_adjustment"] is None


def test_v17_distance_below_50pct_blocked():
    """初始 stop 距离 10%(80000→72000),新 stop 距离 3%(80000→77600)< 5% 上限 → 拒。"""
    out, act = validator_17_stop_tightening(
        {"mode": "evaluate_existing",
         "thesis_assessment": {"still_valid": "weakened",
                                "stop_loss_adjustment": 77600.0}},
        {"stop_tightening_count_so_far": 0,
         "initial_stop_loss_price": 72000.0,
         "active_thesis_avg_price": 80000.0},
    )
    assert act["validator_17_stop_tightening"]


def test_v17_non_weakened_skip():
    out, act = validator_17_stop_tightening(
        {"mode": "evaluate_existing",
         "thesis_assessment": {"still_valid": "fully",
                                "stop_loss_adjustment": 70000.0}},
        {},
    )
    assert not act["validator_17_stop_tightening"]


# ============================================================
# V18: 14d 熔断
# ============================================================

def test_v18_no_fuse_no_block():
    out, act = validator_18_14d_fuse(
        {"mode": "new_thesis", "new_thesis": {"direction": "long"}},
        {"fuse_state": {"in_14d_fuse": False, "in_thesis_cycle_fuse": False}},
    )
    assert not act["validator_18_14d_fuse_active"]


def test_v18_in_fuse_blocks_new_thesis():
    out, act = validator_18_14d_fuse(
        {"mode": "new_thesis", "new_thesis": {"direction": "long"}},
        {"fuse_state": {"in_14d_fuse": True}},
    )
    assert act["validator_18_14d_fuse_active"]
    assert out["mode"] == "silent_cooldown"
    assert "14 天熔断" in out["silent_reason"]


# ============================================================
# V19: 60d 上限
# ============================================================

def test_v19_no_60d_cap_skip():
    out, act = validator_19_60d_cap(
        {"mode": "evaluate_existing"},
        {"active_thesis": {"is_60d_capped": False}},
    )
    assert not act["validator_19_60d_cap"]


def test_v19_60d_capped_blocks_stop_adjustment():
    out, act = validator_19_60d_cap(
        {"mode": "evaluate_existing",
         "thesis_assessment": {"still_valid": "weakened",
                                "stop_loss_adjustment": 70000.0}},
        {"active_thesis": {"is_60d_capped": True}},
    )
    assert act["validator_19_60d_cap"]
    assert out["thesis_assessment"]["stop_loss_adjustment"] is None


# ============================================================
# V20: 连续熔断
# ============================================================

def test_v20_no_consecutive_fuse_skip():
    out, act = validator_20_consecutive_fuse(
        {"mode": "evaluate_existing"},
        {"consecutive_fuse_triggered": False},
    )
    assert not act["validator_20_consecutive_fuse"]


def test_v20_consecutive_fuse_marks_activations():
    out, act = validator_20_consecutive_fuse(
        {"mode": "evaluate_existing"},
        {"consecutive_fuse_triggered": True},
    )
    assert act["validator_20_consecutive_fuse"]
    assert "v20_consecutive_fuse_triggers_review_pending" in out["notes"]


# ============================================================
# V21: master 软抗拒识别
# ============================================================

def test_v21_soft_resistance_detected():
    """满足创建条件但 master silent → 软抗拒触发。"""
    out, act = validator_21_soft_resistance(
        {"mode": "silent_cooldown", "silent_reason": "暂时观察"},
        {
            "active_thesis": None,
            "cooldown_state": {"in_cooldown": False},
            "fuse_state": {"in_14d_fuse": False},
            "l3_grade": "A",
        },
    )
    assert act["validator_21_soft_resistance"]
    assert "v21_soft_resistance_detected" in out["notes"][0]


def test_v21_with_active_thesis_skip():
    """有 active_thesis → 不算软抗拒。"""
    out, act = validator_21_soft_resistance(
        {"mode": "silent_cooldown"},
        {
            "active_thesis": {"thesis_id": "th_x"},
            "cooldown_state": {"in_cooldown": False},
            "fuse_state": {"in_14d_fuse": False},
            "l3_grade": "A",
        },
    )
    assert not act["validator_21_soft_resistance"]


def test_v21_in_cooldown_skip():
    out, act = validator_21_soft_resistance(
        {"mode": "silent_cooldown"},
        {
            "active_thesis": None,
            "cooldown_state": {"in_cooldown": True},
            "fuse_state": {"in_14d_fuse": False},
            "l3_grade": "A",
        },
    )
    assert not act["validator_21_soft_resistance"]


def test_v21_grade_none_skip():
    """grade=none → 不应该出 thesis,silent 是正确的不算软抗拒。"""
    out, act = validator_21_soft_resistance(
        {"mode": "silent_cooldown"},
        {
            "active_thesis": None,
            "cooldown_state": {"in_cooldown": False},
            "fuse_state": {"in_14d_fuse": False},
            "l3_grade": "none",
        },
    )
    assert not act["validator_21_soft_resistance"]


def test_v21_master_outputs_new_thesis_skip():
    """master 出 new_thesis → 不是 silent → 不触发。"""
    out, act = validator_21_soft_resistance(
        {"mode": "new_thesis", "new_thesis": {"direction": "long"}},
        {
            "active_thesis": None,
            "cooldown_state": {"in_cooldown": False},
            "fuse_state": {"in_14d_fuse": False},
            "l3_grade": "A",
        },
    )
    assert not act["validator_21_soft_resistance"]


# ============================================================
# V22: master 连续 3 天失败
# ============================================================

def test_v22_no_failures_skip():
    out, act = validator_22_3day_fail({}, {"master_consecutive_failures": 0})
    assert not act["validator_22_3day_fail"]


def test_v22_three_failures_triggers():
    out, act = validator_22_3day_fail({}, {"master_consecutive_failures": 3})
    assert act["validator_22_3day_fail"]


def test_v22_two_failures_skip():
    out, act = validator_22_3day_fail({}, {"master_consecutive_failures": 2})
    assert not act["validator_22_3day_fail"]


# ============================================================
# V23: conflict_resolution
# ============================================================

def test_v23_narrative_with_conflict_keyword_ok():
    out, act = validator_23_conflict_resolution(
        {"narrative": "L1-L5 五层一致看多,无层间矛盾"}, {},
    )
    assert not act["validator_23_conflict_missing"]


def test_v23_narrative_no_conflict_keyword_violates():
    out, act = validator_23_conflict_resolution(
        {"narrative": "BTC 趋势上行,继续持有"}, {},
    )
    assert act["validator_23_conflict_missing"]
