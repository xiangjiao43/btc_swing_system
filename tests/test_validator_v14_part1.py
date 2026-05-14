"""Sprint 1.10-E 单测:Validator 1-12(v1.4 §3.4.1-§3.4.4)。

D1=a 决策:原地重写 src/ai/validator.py;旧 H1-H10 留 commit 4 删。
D2=c 决策:V12 evidence_ref 轻量校验。
"""
from __future__ import annotations

import pytest

from src.ai.validator import (
    validator_1_stop_loss,
    validator_2_position_cap,
    validator_3_entry_size_normalized,
    validator_4_protection_blocked,
    validator_5_grade_permission_lock,
    validator_6_thesis_lock,
    validator_7_invalidation_check,
    validator_8_break_objectivity,
    validator_9_break_distance,
    validator_10_grade_lock,
    validator_11_direction_lock,
    validator_12_evidence_real,
)


# ============================================================
# V1: stop_loss
# ============================================================

def test_v1_stop_loss_in_levels_no_override():
    """sl 已在 levels → 不覆盖。"""
    out, act = validator_1_stop_loss(
        {"new_thesis": {"stop_loss": {"price": 70000.0, "size_pct": 100}}},
        {"l4_hard_invalidation_levels": [70000.0, 67000.0]},
    )
    assert not act["validator_1_stop_loss_overridden"]
    assert out["new_thesis"]["stop_loss"]["price"] == 70000.0


def test_v1_stop_loss_not_in_levels_override():
    """sl 不在 levels → 覆盖为 levels[0]。"""
    out, act = validator_1_stop_loss(
        {"new_thesis": {"stop_loss": {"price": 65000.0, "size_pct": 100}}},
        {"l4_hard_invalidation_levels": [70000.0, 67000.0]},
    )
    assert act["validator_1_stop_loss_overridden"]
    assert out["new_thesis"]["stop_loss"]["price"] == 70000.0
    assert "stop_loss_overridden_by_validator" in out["notes"]


def test_v1_no_new_thesis_skip():
    out, act = validator_1_stop_loss(
        {"mode": "evaluate_existing"}, {"l4_hard_invalidation_levels": [70000]},
    )
    assert not act["validator_1_stop_loss_overridden"]


# ============================================================
# V2: position_cap
# ============================================================

def test_v2_within_cap_no_override():
    out, act = validator_2_position_cap(
        {"new_thesis": {"entry_orders": [{"price": 74000, "size_pct": 30}]}},
        {"l4_position_cap_base": 0.40},
    )
    assert not act["validator_2_position_capped"]


def test_v2_exceeds_cap_proportional_cap():
    out, act = validator_2_position_cap(
        {"new_thesis": {"entry_orders": [{"price": 74000, "size_pct": 50}]}},
        {"l4_position_cap_base": 0.40},
    )
    assert act["validator_2_position_capped"]
    # max size 50% (0.5) > cap 40% → ratio 0.8 → 50 * 0.8 = 40
    assert out["new_thesis"]["entry_orders"][0]["size_pct"] == 40.0


# ============================================================
# V3: entry size sum ≤ 100
# ============================================================

def test_v3_sum_within_100_no_normalize():
    out, act = validator_3_entry_size_normalized(
        {"mode": "new_thesis",
         "new_thesis": {"entry_orders": [
             {"price": 74000, "size_pct": 40},
             {"price": 70000, "size_pct": 50},
         ]}},
        {},
    )
    assert not act["validator_3_entry_size_normalized"]


def test_v3_sum_exceeds_100_normalize():
    """sum=120 → 缩到 100 → 60 + 60。"""
    out, act = validator_3_entry_size_normalized(
        {"mode": "new_thesis",
         "new_thesis": {"entry_orders": [
             {"price": 74000, "size_pct": 60},
             {"price": 70000, "size_pct": 60},
         ]}},
        {},
    )
    assert act["validator_3_entry_size_normalized"]
    sizes = [o["size_pct"] for o in out["new_thesis"]["entry_orders"]]
    assert abs(sum(sizes) - 100.0) < 1e-6


def test_v3_non_new_thesis_skip():
    out, act = validator_3_entry_size_normalized(
        {"mode": "evaluate_existing"}, {},
    )
    assert not act["validator_3_entry_size_normalized"]


# ============================================================
# V4: PROTECTION block
# ============================================================

def test_v4_no_protection_no_block():
    out, act = validator_4_protection_blocked(
        {"mode": "new_thesis", "new_thesis": {"direction": "long"}},
        {"in_protection": False},
    )
    assert not act["validator_4_protection_blocked"]


def test_v4_protection_blocks_new_thesis():
    out, act = validator_4_protection_blocked(
        {"mode": "new_thesis", "new_thesis": {"direction": "long"}},
        {"in_protection": True},
    )
    assert act["validator_4_protection_blocked"]
    assert out["mode"] == "silent_cooldown"
    assert "new_thesis" not in out
    assert "PROTECTION" in out["silent_reason"]


# ============================================================
# V5: grade-permission lock
# ============================================================

def test_v5_grade_a_legal_permission():
    out, act = validator_5_grade_permission_lock(
        {"mode": "new_thesis",
         "new_thesis": {"execution_permission": "can_open"}},
        {"l3_grade": "A"},
    )
    assert not act["validator_5_grade_permission_lock"]


def test_v5_grade_c_forces_silent_no_thesis():
    """C 级是观察型机会,不允许创建 thesis。"""
    out, act = validator_5_grade_permission_lock(
        {"mode": "new_thesis",
         "new_thesis": {"execution_permission": "can_open"}},
        {"l3_grade": "C"},
    )
    assert act["validator_5_grade_permission_lock"]
    assert out["mode"] == "silent_cooldown"
    assert "new_thesis" not in out


def test_v5_grade_none_forces_silent():
    """grade=none → 强制 silent_cooldown。"""
    out, act = validator_5_grade_permission_lock(
        {"mode": "new_thesis", "new_thesis": {"direction": "long"}},
        {"l3_grade": "none"},
    )
    assert act["validator_5_grade_permission_lock"]
    assert out["mode"] == "silent_cooldown"
    assert "new_thesis" not in out


def test_v5_grade_b_legal():
    out, act = validator_5_grade_permission_lock(
        {"mode": "new_thesis",
         "new_thesis": {"execution_permission": "cautious_open"}},
        {"l3_grade": "B"},
    )
    assert not act["validator_5_grade_permission_lock"]


# ============================================================
# V6: thesis_lock(active_thesis exists + new_thesis → 拦)
# ============================================================

def test_v6_no_active_thesis_new_thesis_ok():
    out, act = validator_6_thesis_lock(
        {"mode": "new_thesis", "new_thesis": {"direction": "long"}},
        {"active_thesis": None},
    )
    assert not act["validator_6_thesis_lock"]


def test_v6_active_thesis_new_thesis_blocked():
    out, act = validator_6_thesis_lock(
        {"mode": "new_thesis", "new_thesis": {"direction": "long"}},
        {"active_thesis": {"thesis_id": "th_x"}},
    )
    assert act["validator_6_thesis_lock"]
    assert out["mode"] == "evaluate_existing"
    assert "new_thesis" not in out
    assert out["thesis_assessment"]["still_valid"] == "mostly"


def test_v6_active_thesis_evaluate_existing_ok():
    out, act = validator_6_thesis_lock(
        {"mode": "evaluate_existing"},
        {"active_thesis": {"thesis_id": "th_x"}},
    )
    assert not act["validator_6_thesis_lock"]


# ============================================================
# V7: invalidation check
# ============================================================

def test_v7_invalidated_with_matching_break():
    out, act = validator_7_invalidation_check(
        {"mode": "evaluate_existing",
         "thesis_assessment": {
             "still_valid": "invalidated",
             "which_break_triggered": "1D 收盘跌破 70000",
         }},
        {"active_thesis": {"break_conditions": [
            "1D 收盘跌破 70000",
            "DXY 突破 110",
        ]}},
    )
    assert not act["validator_7_invalidation_check"]
    assert out["thesis_assessment"]["still_valid"] == "invalidated"


def test_v7_invalidated_no_match_downgrade_to_weakened():
    """which_break_triggered 不在 break_conditions → 降级 weakened。"""
    out, act = validator_7_invalidation_check(
        {"mode": "evaluate_existing",
         "thesis_assessment": {
             "still_valid": "invalidated",
             "which_break_triggered": "市场情绪转空",  # 不在 break_conditions
         }},
        {"active_thesis": {"break_conditions": [
            "1D 收盘跌破 70000",
            "DXY 突破 110",
        ]}},
    )
    assert act["validator_7_invalidation_check"]
    assert out["thesis_assessment"]["still_valid"] == "weakened"
    assert "invalidation_rejected_no_break_triggered" in out["notes"]


def test_v7_substring_match_ok():
    """which 是 break_conditions 一条的子串 → 通过。"""
    out, act = validator_7_invalidation_check(
        {"mode": "evaluate_existing",
         "thesis_assessment": {
             "still_valid": "invalidated",
             "which_break_triggered": "70000",
         }},
        {"active_thesis": {"break_conditions": [
            "1D 收盘跌破 70000",
            "DXY 突破 110",
        ]}},
    )
    assert not act["validator_7_invalidation_check"]


# ============================================================
# V8: break_conditions 客观性 + ≥ 3 条
# ============================================================

def test_v8_three_objective_breaks_ok():
    out, act = validator_8_break_objectivity(
        {"mode": "new_thesis",
         "new_thesis": {"break_conditions": [
             "1D 收盘跌破 70000",
             "DXY 突破 108 持续 3 天",
             "L5 极端事件触发",
         ]}},
        {},
    )
    assert not act["validator_8_break_objectivity"]


def test_v8_less_than_3_violates():
    out, act = validator_8_break_objectivity(
        {"mode": "new_thesis",
         "new_thesis": {"break_conditions": ["1D 跌破 70000"]}},
        {},
    )
    assert act["validator_8_break_objectivity"]


def test_v8_subjective_break_violates():
    out, act = validator_8_break_objectivity(
        {"mode": "new_thesis",
         "new_thesis": {"break_conditions": [
             "1D 收盘跌破 70000",
             "市场情绪转空",                          # 主观
             "L5 极端事件触发",
         ]}},
        {},
    )
    assert act["validator_8_break_objectivity"]


# ============================================================
# V9: break distance(价格类 ≤ 20%)
# ============================================================

def test_v9_within_20pct_ok():
    out, act = validator_9_break_distance(
        {"mode": "new_thesis",
         "new_thesis": {"break_conditions": [
             "1D 收盘跌破 70000",  # 当前 80000 → 12.5% 内
             "DXY 突破 108",
             "L5 极端事件触发",
         ]}},
        {"current_btc_price": 80000.0},
    )
    assert not act["validator_9_break_distance"]


def test_v9_exceeds_20pct_violates():
    out, act = validator_9_break_distance(
        {"mode": "new_thesis",
         "new_thesis": {"break_conditions": [
             "1D 跌破 60000",         # 当前 80000 → 25% 外
             "L5 极端事件触发",
         ]}},
        {"current_btc_price": 80000.0},
    )
    assert act["validator_9_break_distance"]


# ============================================================
# V10: grade-confidence range
# ============================================================

def test_v10_grade_a_score_85_ok():
    out, act = validator_10_grade_lock(
        {"mode": "new_thesis", "new_thesis": {"confidence_score": 85}},
        {"l3_grade": "A"},
    )
    assert not act["validator_10_grade_lock"]


def test_v10_grade_a_score_50_overridden():
    """A 级期望 80-100,master 给 50 → 覆盖到中位 90。"""
    out, act = validator_10_grade_lock(
        {"mode": "new_thesis", "new_thesis": {"confidence_score": 50}},
        {"l3_grade": "A"},
    )
    assert act["validator_10_grade_lock"]
    assert out["new_thesis"]["confidence_score"] == 90


def test_v10_grade_c_score_ignored_because_c_has_no_thesis_range():
    """C 级不再是 thesis 创建候选,V10 不再维护 C 级建仓分数区间。"""
    out, act = validator_10_grade_lock(
        {"mode": "new_thesis", "new_thesis": {"confidence_score": 70}},
        {"l3_grade": "C"},
    )
    assert not act["validator_10_grade_lock"]
    assert out["new_thesis"]["confidence_score"] == 70


# ============================================================
# V11: direction lock
# ============================================================

def test_v11_no_direction_change_ok():
    out, act = validator_11_direction_lock(
        {"mode": "evaluate_existing",
         "narrative": "持有 thesis 不变,趋势仍上",
         "one_line_summary": "维持 long thesis"},
        {"active_thesis": {"direction": "long"}},
    )
    assert not act["validator_11_direction_lock"]


def test_v11_direction_flip_in_narrative_violates():
    """narrative 含 '反手做空' 等 hint → 触发。"""
    out, act = validator_11_direction_lock(
        {"mode": "evaluate_existing",
         "narrative": "趋势反转,建议反手做空"},
        {"active_thesis": {"direction": "long"}},
    )
    assert act["validator_11_direction_lock"]


# ============================================================
# V12: evidence_ref 轻量校验(D2=c)
# ============================================================

def test_v12_valid_list_no_change():
    out, act = validator_12_evidence_real(
        {"evidence_ref": ["card_1", "card_2"]}, {},
    )
    assert not act["validator_12_evidence_real"]
    assert out["evidence_ref"] == ["card_1", "card_2"]


def test_v12_non_list_overridden():
    out, act = validator_12_evidence_real(
        {"evidence_ref": "not a list"}, {},
    )
    assert act["validator_12_evidence_real"]
    assert out["evidence_ref"] == []


def test_v12_drops_invalid_items():
    out, act = validator_12_evidence_real(
        {"evidence_ref": ["card_1", "", None, 123, "card_2"]}, {},
    )
    assert act["validator_12_evidence_real"]
    assert out["evidence_ref"] == ["card_1", "card_2"]


def test_v12_missing_evidence_ref_skip():
    """无 evidence_ref 字段 → 不触发(留 V13/V14 校验)。"""
    out, act = validator_12_evidence_real({"mode": "new_thesis"}, {})
    assert not act["validator_12_evidence_real"]
