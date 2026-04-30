"""tests/ai/test_validator.py — Sprint 1.8 Task C Validator 测试。

每条 H1-H10 多场景覆盖:命中 / 未命中 / 边界。
"""

from __future__ import annotations

import pytest

from src.ai.validator import AdjudicatorValidator


# ============================================================
# 通用 mock fixtures
# ============================================================

def _ok_l1():
    return {"regime": "trend_up", "regime_stability": "stable",
            "volatility_regime": "normal", "confidence": 0.90}


def _chaos_l1():
    return {"regime": "chaos", "regime_stability": "shifting",
            "volatility_regime": "extreme", "confidence": 0.60}


def _ok_l2():
    return {"stance": "bullish", "stance_confidence_tier": "high",
            "phase": "early", "confidence": 0.85}


def _ok_l3(grade="A"):
    return {"opportunity_grade": grade,
            "execution_permission": "active_open",
            "anti_pattern_flags": [], "confidence": 0.85}


def _ok_l4():
    return {
        "risk_score": 38, "risk_tier": "moderate",
        "hard_invalidation_levels": [
            {"price": 73200, "type": "swing_low",
             "distance_from_current_pct": -3.36},
            {"price": 71420, "type": "ema_50_break",
             "distance_from_current_pct": -5.71},
            {"price": 65890, "type": "ema_200_break",
             "distance_from_current_pct": -13.02},
        ],
        "position_cap_multiplier": 0.78, "confidence": 0.85,
    }


def _ok_l5(extreme=False):
    return {
        "macro_stance": "extreme_event" if extreme else "supportive",
        "extreme_event_detected": extreme,
        "extreme_event_type": "geopolitical" if extreme else None,
        "position_cap_macro_multiplier": 0.20 if extreme else 1.0,
        "confidence": 0.88,
    }


def _ok_master(**overrides):
    """合法主裁输出基础版。"""
    base = {
        "state_transition": {
            "from_state": "FLAT",
            "to_state": "LONG_PLANNED",
            "transition_reasoning": "5 层齐心",
        },
        "trade_plan": {
            "action": "open",
            "direction": "long",
            "entry_price_zone": [75000, 75500],
            "stop_loss": 73200,
            "take_profit_zones": [78900, 82100, 86000],
            "position_size_pct": 0.40,
            "position_size_reasoning": "...",
        },
        "position_cap_final": {
            "value": 0.4409,
            "composition": {
                "base": 0.70,
                "l4_multiplier": 0.78,
                "crowding_multiplier": 0.85,
                "macro_multiplier": 1.00,
                "event_multiplier": 0.95,
                "raw_product": 0.4409,
                "after_hard_floor": 0.4409,
            },
        },
        "conflict_resolution": [],
        "what_would_change_mind": "若跌破 73200 立即离场",
        "key_observations": ["5 层齐心"],
        "counter_arguments": ["若 swing_high 失败趋势可能反转"],
        "narrative": "BTC 多头机会",
        "confidence": 0.80,
        "data_completeness_pct": 100,
        "notes": [],
    }
    for k, v in overrides.items():
        base[k] = v
    return base


@pytest.fixture
def validator():
    return AdjudicatorValidator()


# ============================================================
# Smoke:合法输出应 passed=True
# ============================================================

def test_pass_ideal_open(validator):
    """理想开仓场景,无违反。"""
    result = validator.validate(
        master_output=_ok_master(),
        l1_output=_ok_l1(), l2_output=_ok_l2(),
        l3_output=_ok_l3("A"), l4_output=_ok_l4(),
        l5_output=_ok_l5(extreme=False),
        current_state="FLAT",
    )
    assert result["passed"] is True
    assert result["violations"] == []


# ============================================================
# H1:opportunity_grade 三重封闭(narrative 一致性)
# ============================================================

def test_h1_narrative_inconsistent_grade(validator):
    """L3=A 但 narrative 提到 'B 级机会' → H1 软违反。"""
    master = _ok_master()
    master["narrative"] = "B 级机会窗口出现"
    result = validator.validate(
        master_output=master,
        l1_output=_ok_l1(), l2_output=_ok_l2(),
        l3_output=_ok_l3("A"), l4_output=_ok_l4(),
        l5_output=_ok_l5(),
        current_state="FLAT",
    )
    assert any(v["rule"] == "H1" for v in result["violations"])
    assert "ai_overridden_H1_grade_inconsistent" in (
        result["validated_output"].get("notes") or []
    )


def test_h1_narrative_consistent(validator):
    """L3=A 且 narrative 无矛盾引用 → H1 通过。"""
    master = _ok_master()
    master["narrative"] = "5 层齐心,L3 给 A 级"
    result = validator.validate(
        master_output=master,
        l1_output=_ok_l1(), l2_output=_ok_l2(),
        l3_output=_ok_l3("A"), l4_output=_ok_l4(),
        l5_output=_ok_l5(),
        current_state="FLAT",
    )
    assert all(v["rule"] != "H1" for v in result["violations"])


# ============================================================
# H2:stop_loss 必须从 L4 中选
# ============================================================

def test_h2_stop_loss_off_list(validator):
    """主裁给的 stop_loss 不在 L4 列表 → 强制覆盖。"""
    master = _ok_master()
    master["trade_plan"]["stop_loss"] = 70000  # L4 中没有
    result = validator.validate(
        master_output=master,
        l1_output=_ok_l1(), l2_output=_ok_l2(),
        l3_output=_ok_l3(), l4_output=_ok_l4(),
        l5_output=_ok_l5(),
        current_state="FLAT",
    )
    assert any(v["rule"] == "H2" for v in result["violations"])
    assert (result["validated_output"]["trade_plan"]["stop_loss"]
            == 73200)  # L4 第一个
    assert "ai_overridden_H2" in result["validated_output"]["notes"]


def test_h2_stop_loss_in_list(validator):
    """主裁给合法 stop_loss → H2 不触发。"""
    master = _ok_master()
    master["trade_plan"]["stop_loss"] = 71420  # L4 第二个
    result = validator.validate(
        master_output=master,
        l1_output=_ok_l1(), l2_output=_ok_l2(),
        l3_output=_ok_l3(), l4_output=_ok_l4(),
        l5_output=_ok_l5(),
        current_state="FLAT",
    )
    assert all(v["rule"] != "H2" for v in result["violations"])


def test_h2_no_stop_loss_no_violation(validator):
    """主裁未给 stop_loss(如 hold) → H2 不触发。"""
    master = _ok_master()
    master["trade_plan"] = {"action": "hold", "stop_loss": None}
    result = validator.validate(
        master_output=master,
        l1_output=_ok_l1(), l2_output=_ok_l2(),
        l3_output=_ok_l3("B"), l4_output=_ok_l4(),
        l5_output=_ok_l5(),
        current_state="LONG_HOLD",
    )
    assert all(v["rule"] != "H2" for v in result["violations"])


# ============================================================
# H3:position_cap_final.value ≥ 0.15
# ============================================================

def test_h3_below_floor(validator):
    """主裁给 0.10 < 0.15 → 强制为 0.15。"""
    master = _ok_master()
    master["position_cap_final"]["value"] = 0.10
    master["trade_plan"]["position_size_pct"] = 0.05
    result = validator.validate(
        master_output=master,
        l1_output=_ok_l1(), l2_output=_ok_l2(),
        l3_output=_ok_l3(), l4_output=_ok_l4(),
        l5_output=_ok_l5(),
        current_state="FLAT",
    )
    assert any(v["rule"] == "H3" for v in result["violations"])
    assert result["validated_output"]["position_cap_final"]["value"] == 0.15


def test_h3_at_floor_exact(validator):
    """主裁给 0.15(刚好硬下限)→ H3 不触发。"""
    master = _ok_master()
    master["position_cap_final"]["value"] = 0.15
    master["trade_plan"]["position_size_pct"] = 0.10
    result = validator.validate(
        master_output=master,
        l1_output=_ok_l1(), l2_output=_ok_l2(),
        l3_output=_ok_l3(), l4_output=_ok_l4(),
        l5_output=_ok_l5(),
        current_state="FLAT",
    )
    assert all(v["rule"] != "H3" for v in result["violations"])


def test_h3_above_floor(validator):
    """主裁给 0.50 → H3 不触发。"""
    master = _ok_master()
    master["position_cap_final"]["value"] = 0.50
    result = validator.validate(
        master_output=master,
        l1_output=_ok_l1(), l2_output=_ok_l2(),
        l3_output=_ok_l3(), l4_output=_ok_l4(),
        l5_output=_ok_l5(),
        current_state="FLAT",
    )
    assert all(v["rule"] != "H3" for v in result["violations"])


# ============================================================
# H4:extreme_event=true → state 必须 PROTECTION
# ============================================================

def test_h4_extreme_event_not_protection(validator):
    """L5 extreme_event=true 但主裁给 LONG_HOLD → 强制 PROTECTION。"""
    master = _ok_master()
    master["state_transition"]["to_state"] = "LONG_HOLD"
    result = validator.validate(
        master_output=master,
        l1_output=_chaos_l1(), l2_output=_ok_l2(),
        l3_output=_ok_l3("none"), l4_output=_ok_l4(),
        l5_output=_ok_l5(extreme=True),
        current_state="LONG_HOLD",
    )
    assert any(v["rule"] == "H4" for v in result["violations"])
    assert (result["validated_output"]["state_transition"]["to_state"]
            == "PROTECTION")
    assert (result["validated_output"]["trade_plan"]["action"]
            == "protective")


def test_h4_extreme_event_already_protection(validator):
    """L5 extreme_event=true + 主裁已给 PROTECTION → H4 不触发。"""
    master = _ok_master()
    master["state_transition"]["to_state"] = "PROTECTION"
    master["trade_plan"]["action"] = "protective"
    master["trade_plan"]["stop_loss"] = 65890
    result = validator.validate(
        master_output=master,
        l1_output=_chaos_l1(), l2_output=_ok_l2(),
        l3_output=_ok_l3("none"),
        l4_output={
            "hard_invalidation_levels": [
                {"price": 65890, "type": "ema_200_break",
                 "distance_from_current_pct": -1.95},
            ],
            "confidence": 0.85,
        },
        l5_output=_ok_l5(extreme=True),
        current_state="LONG_HOLD",
    )
    assert all(v["rule"] != "H4" for v in result["violations"])


def test_h4_no_extreme_event(validator):
    """L5 extreme_event=false → H4 不触发。"""
    master = _ok_master()
    result = validator.validate(
        master_output=master,
        l1_output=_ok_l1(), l2_output=_ok_l2(),
        l3_output=_ok_l3(), l4_output=_ok_l4(),
        l5_output=_ok_l5(extreme=False),
        current_state="FLAT",
    )
    assert all(v["rule"] != "H4" for v in result["violations"])


# ============================================================
# H5:L1=chaos → 不能开仓
# ============================================================

def test_h5_chaos_with_open(validator):
    """L1=chaos 但 action=open → 强制 watch。"""
    master = _ok_master()
    result = validator.validate(
        master_output=master,
        l1_output=_chaos_l1(), l2_output=_ok_l2(),
        l3_output=_ok_l3(), l4_output=_ok_l4(),
        l5_output=_ok_l5(),
        current_state="FLAT",
    )
    assert any(v["rule"] == "H5" for v in result["violations"])
    assert result["validated_output"]["trade_plan"]["action"] == "watch"


def test_h5_chaos_in_holding(validator):
    """L1=chaos 但 action=open + current LONG_HOLD → 强制 hold。"""
    master = _ok_master()
    master["trade_plan"]["action"] = "add"
    result = validator.validate(
        master_output=master,
        l1_output=_chaos_l1(), l2_output=_ok_l2(),
        l3_output=_ok_l3(), l4_output=_ok_l4(),
        l5_output=_ok_l5(),
        current_state="LONG_HOLD",
    )
    assert any(v["rule"] == "H5" for v in result["violations"])
    assert result["validated_output"]["trade_plan"]["action"] == "hold"


def test_h5_chaos_with_watch(validator):
    """L1=chaos + action=watch → H5 不触发。"""
    master = _ok_master()
    master["trade_plan"]["action"] = "watch"
    result = validator.validate(
        master_output=master,
        l1_output=_chaos_l1(), l2_output=_ok_l2(),
        l3_output=_ok_l3(), l4_output=_ok_l4(),
        l5_output=_ok_l5(),
        current_state="FLAT",
    )
    assert all(v["rule"] != "H5" for v in result["violations"])


# ============================================================
# H6:L3=none → 不能开仓
# ============================================================

def test_h6_grade_none_with_open(validator):
    """L3=none 但 action=open → 强制 watch。"""
    master = _ok_master()
    result = validator.validate(
        master_output=master,
        l1_output=_ok_l1(), l2_output=_ok_l2(),
        l3_output=_ok_l3("none"), l4_output=_ok_l4(),
        l5_output=_ok_l5(),
        current_state="FLAT",
    )
    assert any(v["rule"] == "H6" for v in result["violations"])
    assert result["validated_output"]["trade_plan"]["action"] == "watch"


def test_h6_grade_none_in_holding(validator):
    """L3=none + LONG_HOLD + action=add → 强制 hold。"""
    master = _ok_master()
    master["trade_plan"]["action"] = "add"
    result = validator.validate(
        master_output=master,
        l1_output=_ok_l1(), l2_output=_ok_l2(),
        l3_output=_ok_l3("none"), l4_output=_ok_l4(),
        l5_output=_ok_l5(),
        current_state="LONG_HOLD",
    )
    assert any(v["rule"] == "H6" for v in result["violations"])
    assert result["validated_output"]["trade_plan"]["action"] == "hold"


def test_h6_grade_a_with_open(validator):
    """L3=A + action=open → H6 不触发。"""
    master = _ok_master()
    result = validator.validate(
        master_output=master,
        l1_output=_ok_l1(), l2_output=_ok_l2(),
        l3_output=_ok_l3("A"), l4_output=_ok_l4(),
        l5_output=_ok_l5(),
        current_state="FLAT",
    )
    assert all(v["rule"] != "H6" for v in result["violations"])


# ============================================================
# H7:状态机非法迁移
# ============================================================

def test_h7_long_exit_to_short_planned(validator):
    """LONG_EXIT → SHORT_PLANNED 直跳 → 强制 FLIP_WATCH。"""
    master = _ok_master()
    master["state_transition"]["from_state"] = "LONG_EXIT"
    master["state_transition"]["to_state"] = "SHORT_PLANNED"
    result = validator.validate(
        master_output=master,
        l1_output=_ok_l1(), l2_output=_ok_l2(),
        l3_output=_ok_l3(), l4_output=_ok_l4(),
        l5_output=_ok_l5(),
        current_state="LONG_EXIT",
    )
    assert any(v["rule"] == "H7" for v in result["violations"])
    assert (result["validated_output"]["state_transition"]["to_state"]
            == "FLIP_WATCH")


def test_h7_long_exit_to_long_planned(validator):
    """LONG_EXIT → LONG_PLANNED 直跳 → 强制 FLIP_WATCH。"""
    master = _ok_master()
    master["state_transition"]["from_state"] = "LONG_EXIT"
    master["state_transition"]["to_state"] = "LONG_PLANNED"
    result = validator.validate(
        master_output=master,
        l1_output=_ok_l1(), l2_output=_ok_l2(),
        l3_output=_ok_l3(), l4_output=_ok_l4(),
        l5_output=_ok_l5(),
        current_state="LONG_EXIT",
    )
    assert any(v["rule"] == "H7" for v in result["violations"])


def test_h7_legal_transition(validator):
    """FLAT → LONG_PLANNED → H7 不触发。"""
    master = _ok_master()
    result = validator.validate(
        master_output=master,
        l1_output=_ok_l1(), l2_output=_ok_l2(),
        l3_output=_ok_l3(), l4_output=_ok_l4(),
        l5_output=_ok_l5(),
        current_state="FLAT",
    )
    assert all(v["rule"] != "H7" for v in result["violations"])


# ============================================================
# H8:position_size_pct ≤ position_cap_final.value
# ============================================================

def test_h8_size_exceeds_cap(validator):
    """size_pct=0.50 但 cap=0.44 → 强制 size=cap。"""
    master = _ok_master()
    master["trade_plan"]["position_size_pct"] = 0.50
    master["position_cap_final"]["value"] = 0.44
    result = validator.validate(
        master_output=master,
        l1_output=_ok_l1(), l2_output=_ok_l2(),
        l3_output=_ok_l3(), l4_output=_ok_l4(),
        l5_output=_ok_l5(),
        current_state="FLAT",
    )
    assert any(v["rule"] == "H8" for v in result["violations"])
    assert (result["validated_output"]["trade_plan"]["position_size_pct"]
            == 0.44)


def test_h8_size_equals_cap(validator):
    """size_pct=cap=0.44 → H8 不触发。"""
    master = _ok_master()
    master["trade_plan"]["position_size_pct"] = 0.44
    master["position_cap_final"]["value"] = 0.44
    result = validator.validate(
        master_output=master,
        l1_output=_ok_l1(), l2_output=_ok_l2(),
        l3_output=_ok_l3(), l4_output=_ok_l4(),
        l5_output=_ok_l5(),
        current_state="FLAT",
    )
    assert all(v["rule"] != "H8" for v in result["violations"])


def test_h8_size_none(validator):
    """size_pct=None(hold 状态) → H8 不触发。"""
    master = _ok_master()
    master["trade_plan"] = {"action": "hold", "position_size_pct": None}
    result = validator.validate(
        master_output=master,
        l1_output=_ok_l1(), l2_output=_ok_l2(),
        l3_output=_ok_l3("B"), l4_output=_ok_l4(),
        l5_output=_ok_l5(),
        current_state="LONG_HOLD",
    )
    assert all(v["rule"] != "H8" for v in result["violations"])


# ============================================================
# H9:counter_arguments ≥ 1 条
# ============================================================

def test_h9_empty_counter(validator):
    """counter_arguments=[] → 添加 placeholder。"""
    master = _ok_master()
    master["counter_arguments"] = []
    result = validator.validate(
        master_output=master,
        l1_output=_ok_l1(), l2_output=_ok_l2(),
        l3_output=_ok_l3(), l4_output=_ok_l4(),
        l5_output=_ok_l5(),
        current_state="FLAT",
    )
    assert any(v["rule"] == "H9" for v in result["violations"])
    assert len(result["validated_output"]["counter_arguments"]) >= 1


def test_h9_missing_counter(validator):
    """counter_arguments 字段不存在 → 添加 placeholder。"""
    master = _ok_master()
    del master["counter_arguments"]
    result = validator.validate(
        master_output=master,
        l1_output=_ok_l1(), l2_output=_ok_l2(),
        l3_output=_ok_l3(), l4_output=_ok_l4(),
        l5_output=_ok_l5(),
        current_state="FLAT",
    )
    assert any(v["rule"] == "H9" for v in result["violations"])


def test_h9_has_counter(validator):
    """counter_arguments=['xxx'] → H9 不触发。"""
    master = _ok_master()
    master["counter_arguments"] = ["若 swing_high 失败趋势可能反转"]
    result = validator.validate(
        master_output=master,
        l1_output=_ok_l1(), l2_output=_ok_l2(),
        l3_output=_ok_l3(), l4_output=_ok_l4(),
        l5_output=_ok_l5(),
        current_state="FLAT",
    )
    assert all(v["rule"] != "H9" for v in result["violations"])


# ============================================================
# H10:confidence ≤ data_completeness × min(L1-L5)
# ============================================================

def test_h10_master_too_confident(validator):
    """L1-L5 min=0.60 + master=0.95 → 强制为 0.60。"""
    master = _ok_master()
    master["confidence"] = 0.95
    master["data_completeness_pct"] = 100
    l4_low_conf = _ok_l4()
    l4_low_conf["confidence"] = 0.60
    result = validator.validate(
        master_output=master,
        l1_output=_ok_l1(), l2_output=_ok_l2(),
        l3_output=_ok_l3(), l4_output=l4_low_conf,
        l5_output=_ok_l5(),
        current_state="FLAT",
    )
    assert any(v["rule"] == "H10" for v in result["violations"])
    assert result["validated_output"]["confidence"] == 0.60


def test_h10_within_limit(validator):
    """master=0.80 < min(L1-L5)=0.85 → H10 不触发。"""
    master = _ok_master()
    master["confidence"] = 0.80
    result = validator.validate(
        master_output=master,
        l1_output=_ok_l1(), l2_output=_ok_l2(),
        l3_output=_ok_l3(), l4_output=_ok_l4(),
        l5_output=_ok_l5(),
        current_state="FLAT",
    )
    assert all(v["rule"] != "H10" for v in result["violations"])


def test_h10_data_pct_lowers_cap(validator):
    """data_completeness_pct=50 + master=0.80 → max=0.5×0.85=0.425 → 强制。"""
    master = _ok_master()
    master["confidence"] = 0.80
    master["data_completeness_pct"] = 50
    result = validator.validate(
        master_output=master,
        l1_output=_ok_l1(), l2_output=_ok_l2(),
        l3_output=_ok_l3(), l4_output=_ok_l4(),
        l5_output=_ok_l5(),
        current_state="FLAT",
    )
    assert any(v["rule"] == "H10" for v in result["violations"])
    # 0.5 × 0.85 (l2 conf) = 0.425
    assert result["validated_output"]["confidence"] == pytest.approx(
        0.42, abs=0.01,
    )


# ============================================================
# 多重违反场景(综合测试)
# ============================================================

def test_multiple_violations_chaos_extreme(validator):
    """L1=chaos + L5=extreme_event + 主裁给 LONG_PLANNED + active_open。
    应触发 H4 + H5(可能)+ position_cap 串"""
    master = _ok_master()
    master["state_transition"]["to_state"] = "LONG_PLANNED"
    master["trade_plan"]["action"] = "open"
    result = validator.validate(
        master_output=master,
        l1_output=_chaos_l1(), l2_output=_ok_l2(),
        l3_output=_ok_l3("none"),  # 顺便加 H6
        l4_output=_ok_l4(),
        l5_output=_ok_l5(extreme=True),
        current_state="FLAT",
    )
    rules = [v["rule"] for v in result["violations"]]
    assert "H4" in rules
    # H4 已强制 to_state=PROTECTION + action=protective,
    # 所以 H5/H6 在覆盖前可能也触发
    assert (result["validated_output"]["state_transition"]["to_state"]
            == "PROTECTION")
    assert (result["validated_output"]["trade_plan"]["action"]
            == "protective")
    assert result["passed"] is False


def test_no_violations_returns_passed_true(validator):
    """完全合法的输出 → passed=True。"""
    result = validator.validate(
        master_output=_ok_master(),
        l1_output=_ok_l1(), l2_output=_ok_l2(),
        l3_output=_ok_l3(), l4_output=_ok_l4(),
        l5_output=_ok_l5(),
        current_state="FLAT",
    )
    assert result["passed"] is True
    assert result["violations"] == []
    assert "ai_overridden" not in str(
        result["validated_output"].get("notes") or []
    )


def test_does_not_mutate_input(validator):
    """validator 不能 mutate 调用方传入的 master_output。"""
    master = _ok_master()
    master["trade_plan"]["stop_loss"] = 70000  # 触发 H2
    original_stop = master["trade_plan"]["stop_loss"]
    validator.validate(
        master_output=master,
        l1_output=_ok_l1(), l2_output=_ok_l2(),
        l3_output=_ok_l3(), l4_output=_ok_l4(),
        l5_output=_ok_l5(),
        current_state="FLAT",
    )
    # 原 dict 应保持不变
    assert master["trade_plan"]["stop_loss"] == original_stop
