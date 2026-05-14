"""Sprint 1.10-E commit 4 单测:V24 meta + validate_master_output 集成入口
(v1.4 §3.4.9)。"""
from __future__ import annotations

import json

import pytest

from src.ai.validator import (
    collect_meta_activations,
    validate_master_output,
    _DEFAULT_ACTIVATIONS_V24,
)


# ============================================================
# V24:Meta dict 28 字段
# ============================================================

def test_v24_default_dict_has_28_fields():
    """v1.4 §3.4.9 原 28 字段 dict(全 false / None default)。

    Sprint 1.10-F 增加 4 个 retry-mechanism 元字段(validator_needs_retry /
    validator_retry_hints / validator_22_failures_count /
    validator_22_needs_review_pending),总数 32。
    Sprint D 加 1 个 stale 披露元字段(validator_stale_disclosure_missing;
    _needs_retry 是临时聚合用,不持久化),总数 33。
    Sprint E Step 4 加 2 个因子粒度元字段(validator_factor_grain_violation /
    validator_factor_grain_reason;_needs_retry 同样不持久化),总数 35。
    原 28 字段都仍存在。
    """
    assert len(_DEFAULT_ACTIVATIONS_V24) == 35
    # v1.4 §3.4.9 28 个原字段必须仍存在
    v14_28_fields = {
        "validator_1_stop_loss_overridden",
        "validator_2_position_capped",
        "validator_3_entry_size_normalized",
        "validator_4_protection_blocked",
        "validator_5_grade_permission_lock",
        "validator_6_thesis_lock",
        "validator_7_invalidation_check",
        "validator_8_break_objectivity",
        "validator_9_break_distance",
        "validator_10_grade_lock",
        "validator_11_direction_lock",
        "validator_12_evidence_real",
        "validator_13_objective_evidence",
        "validator_14_counter_argument",
        "validator_15_confidence_capped",
        "validator_15_capped_value",
        "validator_16_change_mind",
        "validator_17_stop_tightening",
        "validator_18_14d_fuse_active",
        "validator_19_60d_cap",
        "validator_20_consecutive_fuse",
        "validator_21_soft_resistance",
        "validator_22_3day_fail",
        "validator_23_conflict_missing",
        "position_cap_compressed",
        "thesis_lock_active",
        "in_cooldown",
        "cooldown_remaining_hours",
    }
    for k in v14_28_fields:
        assert k in _DEFAULT_ACTIVATIONS_V24, f"v1.4 §3.4.9 字段缺失: {k}"


def test_v24_collect_meta_activations_no_violations():
    """无任何 V<n> 触发 → constraint_activations 全 default。"""
    raw = {}
    out = collect_meta_activations(
        raw, master_output={}, context={"active_thesis": None,
                                         "cooldown_state": {"in_cooldown": False}},
    )
    assert out["validator_1_stop_loss_overridden"] is False
    assert out["validator_15_capped_value"] is None
    assert out["thesis_lock_active"] is False
    assert out["in_cooldown"] is False


def test_v24_collect_meta_activations_with_violations():
    raw = {
        "validator_1_stop_loss_overridden": True,
        "validator_15_confidence_capped": True,
        "validator_15_capped_value": 65.0,
    }
    out = collect_meta_activations(
        raw, master_output={}, context={"active_thesis": None,
                                         "cooldown_state": {"in_cooldown": False}},
    )
    assert out["validator_1_stop_loss_overridden"] is True
    assert out["validator_15_confidence_capped"] is True
    assert out["validator_15_capped_value"] == 65.0


def test_v24_position_cap_compressed_extracted():
    """master_output 的 entry_orders 最大 size_pct → position_cap_compressed。"""
    out = collect_meta_activations(
        {}, master_output={"new_thesis": {"entry_orders": [
            {"price": 74000, "size_pct": 30},
            {"price": 70000, "size_pct": 40},
        ]}},
        context={"active_thesis": None, "cooldown_state": {}},
    )
    assert out["position_cap_compressed"] == 0.40


def test_v24_thesis_lock_active_from_context():
    out = collect_meta_activations(
        {}, master_output={},
        context={"active_thesis": {"thesis_id": "th_x"},
                 "cooldown_state": {"in_cooldown": False}},
    )
    assert out["thesis_lock_active"] is True


def test_v24_cooldown_state_propagates():
    out = collect_meta_activations(
        {}, master_output={},
        context={"active_thesis": None,
                 "cooldown_state": {"in_cooldown": True,
                                     "cooldown_remaining_hours": 12.5}},
    )
    assert out["in_cooldown"] is True
    assert out["cooldown_remaining_hours"] == 12.5


def test_v24_dict_serializable_to_json():
    """constraint_activations 必须 json.dumps 友好(写入 SQLite TEXT)。"""
    out = collect_meta_activations(
        {"validator_15_confidence_capped": True, "validator_15_capped_value": 65.0},
        master_output={"new_thesis": {"entry_orders": [{"size_pct": 30}]}},
        context={"active_thesis": {"thesis_id": "th_x"},
                 "cooldown_state": {"in_cooldown": True,
                                     "cooldown_remaining_hours": 12.5}},
    )
    js = json.dumps(out)
    assert isinstance(js, str)
    # roundtrip
    decoded = json.loads(js)
    assert decoded["validator_15_capped_value"] == 65.0
    assert decoded["thesis_lock_active"] is True


# ============================================================
# validate_master_output 集成入口
# ============================================================

def test_validate_silent_cooldown_no_violations():
    """合法 silent_cooldown → 多数 V 不触发。"""
    output, activations = validate_master_output(
        {"mode": "silent_cooldown", "silent_reason": "在冷却",
         "narrative": "L1-L5 一致看多但在冷却,无层间矛盾",
         "counter_arguments": ["funding 偏高"],
         "what_would_change_mind": ["A", "B", "C"],
         "evidence_ref": []},
        {"active_thesis": None,
         "cooldown_state": {"in_cooldown": True, "cooldown_remaining_hours": 12.0},
         "fuse_state": {}, "l3_grade": "A"},
    )
    assert output["mode"] == "silent_cooldown"
    assert activations["validator_1_stop_loss_overridden"] is False
    # cooldown 状态正确反映在 meta
    assert activations["in_cooldown"] is True
    assert activations["cooldown_remaining_hours"] == 12.0


def test_validate_v6_thesis_lock_overrides_new_thesis():
    """有 active_thesis + master 出 new_thesis → V6 强制 evaluate_existing。"""
    output, activations = validate_master_output(
        {"mode": "new_thesis",
         "new_thesis": {"direction": "long", "confidence_score": 75,
                         "execution_permission": "can_open"},
         "narrative": "看多新机会,无层间矛盾"},
        {"active_thesis": {"thesis_id": "th_x", "direction": "long",
                            "break_conditions": ["c1", "c2", "c3"]},
         "cooldown_state": {}, "fuse_state": {}, "l3_grade": "A"},
    )
    assert output["mode"] == "evaluate_existing"
    assert "new_thesis" not in output
    assert activations["validator_6_thesis_lock"] is True
    assert activations["thesis_lock_active"] is True


def test_validate_v18_fuse_blocks_new_thesis():
    """in_14d_fuse=True + master 出 new_thesis → V18 强制 silent_cooldown。"""
    output, activations = validate_master_output(
        {"mode": "new_thesis", "new_thesis": {"direction": "long"},
         "narrative": "看多新机会,L1-L5 一致"},
        {"active_thesis": None,
         "cooldown_state": {"in_cooldown": False},
         "fuse_state": {"in_14d_fuse": True},
         "l3_grade": "A"},
    )
    assert output["mode"] == "silent_cooldown"
    assert activations["validator_18_14d_fuse_active"] is True


def test_validate_v1_v2_v5_combined_overrides():
    """new_thesis + 多约束触发(stop_loss + position_cap + grade=B 但 permission=can_open)。"""
    output, activations = validate_master_output(
        {"mode": "new_thesis",
         "new_thesis": {
             "direction": "long",
             "confidence_score": 70,                     # B 级范围 60-80 ✓
             "execution_permission": "can_open",          # B 级只允许 cautious_open / ambush_only
             "entry_orders": [{"price": 74000, "size_pct": 60}],  # 单笔 0.60 > cap 0.40
             "stop_loss": {"price": 65000, "size_pct": 100},      # 不在 [70000, 67000]
         },
         "narrative": "新看多,无层间矛盾",
         "counter_arguments": ["funding 拥挤"],
         "what_would_change_mind": ["1D 跌破 70000",
                                      "DXY 突破 110",
                                      "L5 极端事件"]},
        {"active_thesis": None,
         "cooldown_state": {"in_cooldown": False},
         "fuse_state": {"in_14d_fuse": False},
         "l3_grade": "B",
         "l4_hard_invalidation_levels": [70000.0, 67000.0],
         "l4_position_cap_base": 0.40,
         "current_btc_price": 76000.0},
    )
    # V1 stop_loss 覆盖
    assert activations["validator_1_stop_loss_overridden"] is True
    assert output["new_thesis"]["stop_loss"]["price"] == 70000.0
    # V2 position_capped(60% > cap 40%)
    assert activations["validator_2_position_capped"] is True
    # V5 grade_permission_lock(B 级不允许 can_open)
    assert activations["validator_5_grade_permission_lock"] is True
    assert output["new_thesis"]["execution_permission"] in {"ambush_only", "cautious_open"}


def test_validate_grade_c_blocks_new_thesis():
    """C 级是观察型机会,validator 保守改为 silent,与 persistence 不创建 thesis 对齐。"""
    output, activations = validate_master_output(
        {"mode": "new_thesis",
         "new_thesis": {
             "direction": "long",
             "confidence_score": 50,
             "execution_permission": "ambush_only",
             "entry_orders": [{"price": 74000, "size_pct": 20}],
             "stop_loss": {"price": 70000, "size_pct": 100},
         },
         "narrative": "C 级观察机会,层间仍有分歧",
         "counter_arguments": ["机会质量偏低"],
         "what_would_change_mind": ["1D 收盘突破 78000",
                                      "L3 升级到 B",
                                      "funding 回落"]},
        {"active_thesis": None,
         "cooldown_state": {"in_cooldown": False},
         "fuse_state": {"in_14d_fuse": False},
         "l3_grade": "C",
         "l4_hard_invalidation_levels": [70000.0],
         "l4_position_cap_base": 0.40,
         "current_btc_price": 76000.0},
    )
    assert output["mode"] == "silent_cooldown"
    assert "new_thesis" not in output
    assert activations["validator_5_grade_permission_lock"] is True


def test_validate_dict_28_field_complete():
    """validate_master_output 返回的 activations 必须含全 33 字段。

    v1.4 §3.4.9 28 字段 + Sprint 1.10-F 新增 4 retry 元字段 +
    Sprint D 新增 1 stale 披露字段 + Sprint E Step 4 新增 2 因子粒度字段
    (_needs_retry 临时聚合) = 35。
    """
    _, activations = validate_master_output(
        {"mode": "silent_cooldown", "silent_reason": "x",
         "narrative": "无层间矛盾"},
        {"active_thesis": None, "cooldown_state": {}, "fuse_state": {}},
    )
    assert len(activations) == 35
    # 所有 default 字段都在
    for key in _DEFAULT_ACTIVATIONS_V24:
        assert key in activations
