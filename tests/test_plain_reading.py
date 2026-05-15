"""
tests/test_plain_reading.py — Sprint 2.2 Task C 验收。
覆盖每层至少 6 种典型情况。
"""

from __future__ import annotations

import inspect

from src.evidence.plain_reading import (
    inject_plain_readings, plain_reading_l1, plain_reading_l2,
    plain_reading_l3, plain_reading_l4, plain_reading_l5,
    plain_reading_layer_a_raw_factor,
)


# ================== L1 ==================

def test_l1_trend_up_stable():
    s = plain_reading_l1({
        "regime": "trend_up", "volatility_regime": "normal",
        "regime_stability": "stable", "health_status": "healthy",
    })
    assert "上升趋势" in s
    assert "稳定" in s


def test_l1_trend_down_stable():
    s = plain_reading_l1({
        "regime": "trend_down", "volatility_regime": "elevated",
        "regime_stability": "stable", "health_status": "healthy",
    })
    assert "下跌" in s


def test_l1_chaos():
    s = plain_reading_l1({
        "regime": "chaos", "volatility_regime": "extreme",
        "regime_stability": "unstable", "health_status": "healthy",
    })
    assert "混乱" in s
    assert "观望" in s


def test_l1_transition_up():
    s = plain_reading_l1({
        "regime": "transition_up", "volatility_regime": "low",
        "regime_stability": "slightly_shifting", "health_status": "healthy",
    })
    assert "过渡" in s or "transition" in s.lower()


def test_l1_range():
    s = plain_reading_l1({
        "regime": "range_high", "volatility_regime": "normal",
        "regime_stability": "stable", "health_status": "healthy",
    })
    assert "震荡" in s


def test_l1_insufficient():
    s = plain_reading_l1({
        "regime": "unclear_insufficient", "volatility_regime": "unknown",
        "regime_stability": "unclear", "health_status": "cold_start_warming_up",
    })
    assert "数据不足" in s or "冷启动" in s


# ================== L2 ==================

def test_l2_bullish_mid():
    s = plain_reading_l2({
        "stance": "bullish", "stance_confidence": 0.72, "phase": "mid",
        "health_status": "healthy",
    })
    assert "看多" in s


def test_l2_bullish_late():
    s = plain_reading_l2({
        "stance": "bullish", "stance_confidence": 0.72, "phase": "late",
        "health_status": "healthy",
    })
    assert "末段" in s and "追涨" in s


def test_l2_bearish():
    s = plain_reading_l2({
        "stance": "bearish", "stance_confidence": 0.8, "phase": "early",
        "health_status": "healthy",
    })
    assert "看空" in s


def test_l2_neutral():
    s = plain_reading_l2({
        "stance": "neutral", "stance_confidence": 0.4, "phase": "n_a",
        "health_status": "healthy",
    })
    assert "方向不明" in s and "观望" in s


def test_l2_low_confidence_does_not_open():
    s = plain_reading_l2({
        "stance": "bullish", "stance_confidence": 0.40, "phase": "mid",
        "health_status": "healthy",
    })
    assert "观察" in s or "不下单" in s


def test_l2_insufficient():
    # Sprint 1.10-J commit 6 §X:cold_start_warming_up 已删,改测 health_status='error'
    s = plain_reading_l2({"health_status": "error"})
    assert "数据不足" in s


# ================== L3 ==================

def test_l3_a_grade():
    s = plain_reading_l3({
        "opportunity_grade": "A", "execution_permission": "can_open",
    })
    assert "高等级机会" in s


def test_l3_b_grade():
    s = plain_reading_l3({
        "opportunity_grade": "B", "execution_permission": "cautious_open",
    })
    assert "中等级机会" in s
    assert "70" in s


def test_l3_c_grade_gives_plan_at_40pct():
    s = plain_reading_l3({
        "opportunity_grade": "C", "execution_permission": "cautious_open",
    })
    assert "低等级参考机会" in s
    assert "40" in s


def test_l3_none():
    s = plain_reading_l3({
        "opportunity_grade": "none", "execution_permission": "watch",
    })
    assert "没有" in s or "门槛" in s


def test_l3_anti_pattern():
    s = plain_reading_l3({
        "opportunity_grade": "B", "execution_permission": "cautious_open",
        "anti_pattern_flags": ["over_extended_rally", "funding_extreme"],
    })
    assert "反模式" in s


def test_l3_empty():
    s = plain_reading_l3({})
    assert "数据不足" in s or "没有" in s or "none" in s.lower()


# ================== L4 ==================

def test_l4_low_risk():
    s = plain_reading_l4({
        "overall_risk_level": "low", "position_cap": 0.21,
        "execution_permission": "can_open",
    })
    assert "风险低" in s


def test_l4_moderate_with_structural():
    s = plain_reading_l4({
        "overall_risk_level": "moderate", "position_cap": 0.15,
        "hard_invalidation_levels": [
            {"price": 81200, "priority": 1, "direction": "below"},
            {"price": 79800, "priority": 2},
        ],
    })
    assert "81200" in s
    assert "优先级 1" in s


def test_l4_high_risk():
    s = plain_reading_l4({
        "overall_risk_level": "high", "position_cap": 0.05,
        "execution_permission": "ambush_only",
    })
    assert "风险高" in s or "风险偏高" in s


def test_l4_critical():
    s = plain_reading_l4({
        "overall_risk_level": "critical", "position_cap": 0.0,
        "execution_permission": "protective",
    })
    assert "严重" in s


def test_l4_elevated():
    s = plain_reading_l4({
        "overall_risk_level": "elevated", "position_cap": 0.10,
        "execution_permission": "cautious_open",
    })
    assert "偏高" in s


def test_l4_empty():
    assert "数据不足" in plain_reading_l4({})


# ================== L5 ==================

def test_l5_risk_on():
    s = plain_reading_l5({"macro_stance": "risk_on"})
    assert "顺风" in s or "风险偏好" in s


def test_l5_risk_off():
    s = plain_reading_l5({"macro_stance": "risk_off"})
    assert "逆风" in s


def test_l5_extreme():
    s = plain_reading_l5({"extreme_event_detected": True})
    assert "极端" in s


def test_l5_neutral():
    s = plain_reading_l5({"macro_stance": "risk_neutral"})
    assert "中性" in s


def test_l5_low_completeness():
    s = plain_reading_l5({"macro_stance": "unclear", "data_completeness_pct": 30})
    assert "30" in s or "参考" in s


def test_l5_extreme_risk_off():
    s = plain_reading_l5({"macro_stance": "extreme_risk_off"})
    assert "禁止" in s or "极端" in s


# ================== inject ==================

def test_inject_writes_five_fields():
    state = {
        "evidence_reports": {
            "layer_1": {"regime": "trend_up", "health_status": "healthy"},
            "layer_2": {"stance": "bullish", "stance_confidence": 0.7,
                        "phase": "early", "health_status": "healthy"},
            "layer_3": {"opportunity_grade": "A", "execution_permission": "can_open"},
            "layer_4": {"overall_risk_level": "low", "position_cap": 0.15},
            "layer_5": {"macro_stance": "risk_neutral"},
        },
    }
    inject_plain_readings(state)
    for i in range(1, 6):
        pr = state["evidence_reports"][f"layer_{i}"]["plain_reading"]
        assert isinstance(pr, str) and len(pr) > 5


# ================== Layer A raw factor cards ==================

def test_layer_a_raw_factor_plain_readings_cover_new_factors():
    """Layer A 原始因子的人话说明走规则模板,不是 AI 生成。"""
    keys = (
        "lth_sopr",
        "sth_sopr",
        "rhodl_ratio",
        "reserve_risk",
        "puell_multiple",
        "lth_net_position_change",
        "percent_supply_in_profit",
        "percent_supply_in_loss",
        "exchange_balance",
        "exchange_net_position_change",
        "us2y",
        "fed_funds_rate",
        "real_yield",
        "cpi",
        "core_cpi",
        "m2",
        "fed_balance_sheet",
        "monthly_ohlc_structure",
        "major_support_resistance_zones",
        "hodl_waves_1y_plus_aggregate",
    )
    for key in keys:
        text = plain_reading_layer_a_raw_factor(
            key, {"actual_value": 1.02, "status": "available"}
        )
        assert "📊" in text
        assert "当前" in text
        assert "Layer A context" not in text


def test_layer_a_raw_factor_unavailable_text_hides_internal_errors():
    text = plain_reading_layer_a_raw_factor(
        "lth_sopr", {"status": "proxy_endpoint_404"}
    )
    assert "LTH SOPR 用于观察长期持有人" in text
    assert "未接入" in text
    assert "proxy_endpoint_404" not in text

    limited = plain_reading_layer_a_raw_factor(
        "reserve_risk", {"status": "uncertain_rate_limited"}
    )
    assert "Reserve Risk 用于观察长期持有者" in limited
    assert "数据受限" in limited
    assert "uncertain_rate_limited" not in limited


def test_layer_a_raw_factor_cpi_core_cpi_plain_readings_are_monthly_macro_readable():
    cpi = plain_reading_layer_a_raw_factor(
        "cpi", {"actual_value": 332.407, "status": "available"}
    )
    core = plain_reading_layer_a_raw_factor(
        "core_cpi", {"actual_value": 335.423, "status": "available"}
    )
    assert "当前 CPI 为" in cpi
    assert "整体通胀水平" in cpi
    assert "当前 Core CPI 为" in core
    assert "剔除食品和能源" in core


def test_layer_a_p0_raw_factor_plain_readings_are_deterministic_and_readable():
    monthly = plain_reading_layer_a_raw_factor(
        "monthly_ohlc_structure",
        {
            "actual_value": "recovering",
            "status": "available",
            "monthly_trend": "recovering",
        },
    )
    levels = plain_reading_layer_a_raw_factor(
        "major_support_resistance_zones",
        {"actual_value": "支撑 74,800 / 阻力 85,000", "status": "available"},
    )
    hodl = plain_reading_layer_a_raw_factor(
        "hodl_waves_1y_plus_aggregate",
        {"actual_value": 62.3, "status": "available", "value_unit": "%"},
    )

    assert "当前月线结构显示为修复中" in monthly
    assert "当前长期结构为 支撑 74,800 / 阻力 85,000" in levels
    assert "当前 1Y+ 长期持有筹码占比为 62.3%" in hodl
    for text in (monthly, levels, hodl):
        assert "Layer A context" not in text
        assert "endpoint" not in text
        assert "exception" not in text


def test_layer_a_raw_factor_plain_reading_has_no_ai_call_dependency():
    src = inspect.getsource(plain_reading_layer_a_raw_factor)
    forbidden = ("ai_client", "call_ai", "run_agent", "BaseAgent", "prompt")
    assert not any(term in src for term in forbidden)
