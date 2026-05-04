"""tests/test_no_opportunity_8_scenarios.py — Sprint 1.5m Task C3。

8 个场景各 1 个集成测试:
- 注入触发场景的 facts + state
- 断言 detect_scenario 命中正确场景
- 断言 narrative 含【结构】+ 至少 1 个数值
- 断言不含老机器化模板词
"""

from __future__ import annotations

import re

from src.strategy.no_opportunity_narrator import (
    SCENARIO_COLD_START, SCENARIO_EXTREME_EVENT, SCENARIO_PROTECTION,
    SCENARIO_FALLBACK_DEGRADED, SCENARIO_POST_PROTECTION,
    SCENARIO_PERMISSION_RESTRICTED, SCENARIO_POSITION_CAP_ZERO,
    SCENARIO_GRADE_NONE,
    detect_scenario, generate_no_opportunity_narrative,
)


_OLD_TEMPLATE_PHRASES = (
    "执行许可被收紧到",
    "系统不允许新开仓",
)


def _has_old_template(text: str) -> bool:
    return any(p in text for p in _OLD_TEMPLATE_PHRASES)


def _has_concrete_value(text: str) -> bool:
    return bool(re.search(r"-?\d+\.?\d*", text))


def _factor_cards_sample() -> list[dict]:
    return [
        {
            "card_id": "structure_btc_price",
            "category": "price_structure",
            "name": "BTC 现价",
            "current_value": 75700.0,
            "value_unit": "USDT",
        },
        {
            "card_id": "deriv_funding_now",
            "category": "derivatives",
            "name": "Binance 资金费率 · 当前",
            "current_value": -0.41,
            "value_unit": "%",
        },
    ]


def _composite_sample() -> dict:
    return {
        "cycle_position": {"cycle_position": "mid_bull",
                           "cycle_confidence": 0.5},
        "crowding": {"crowding_level": "high", "crowding_score": 11},
        "macro_headwind": {"macro_headwind_level": "mild",
                           "headwind_score": -2},
        "event_risk": {"event_risk_level": "high",
                       "event_risk_score": 11.5},
    }


# ============================================================
# 1. cold_start
# Sprint 1.10-J commit 6 §X:test_scenario_cold_start 整删
# (cold_start_warming_up 路由已删,v1.4 §11.2 删 cold_start)
# SCENARIO_COLD_START 留 1.10-K 跟 narrator 整重写
# ============================================================


# ============================================================
# 2. extreme_event
# ============================================================

def test_scenario_extreme_event():
    facts = {"l5_extreme_event_detected": True}
    state = {
        "evidence_reports": {
            "layer_5": {
                "extreme_event_detected": True,
                "extreme_event_details": {
                    "event_name": "FOMC 紧急加息",
                    "severity": "critical",
                },
            },
        },
        "factor_cards": _factor_cards_sample(),
    }
    assert detect_scenario(facts, state) == SCENARIO_EXTREME_EVENT
    out = generate_no_opportunity_narrative(facts, state)
    assert "【结构】" in out["narrative"]
    assert "FOMC" in out["narrative"]
    assert not _has_old_template(out["narrative"])


# ============================================================
# 3. protection
# ============================================================

def test_scenario_protection():
    facts = {"state_machine_current": "PROTECTION"}
    state = {
        "risks": {"protection_reason": "L4 风险层 critical"},
        "factor_cards": _factor_cards_sample(),
    }
    assert detect_scenario(facts, state) == SCENARIO_PROTECTION
    out = generate_no_opportunity_narrative(facts, state)
    assert "【结构】" in out["narrative"]
    assert not _has_old_template(out["narrative"])


# ============================================================
# 4. fallback_degraded
# ============================================================

def test_scenario_fallback_degraded():
    facts = {"fallback_level": "level_3"}
    state = {
        "evidence_reports": {
            "layer_5": {"data_freshness": "red"},
            "layer_3": {"data_freshness": {"status": "yellow"}},
        },
    }
    assert detect_scenario(facts, state) == SCENARIO_FALLBACK_DEGRADED
    out = generate_no_opportunity_narrative(facts, state)
    assert "【结构】" in out["narrative"]
    assert "L3 严重降级" in out["narrative"]
    assert not _has_old_template(out["narrative"])


# ============================================================
# 5. post_protection_reassess
# ============================================================

def test_scenario_post_protection():
    facts = {"state_machine_current": "POST_PROTECTION_REASSESS"}
    state = {
        "factor_cards": _factor_cards_sample(),
        "composite_factors": _composite_sample(),
    }
    assert detect_scenario(facts, state) == SCENARIO_POST_PROTECTION
    out = generate_no_opportunity_narrative(facts, state)
    assert "【结构】" in out["narrative"]
    assert "重评期" in out["narrative"]
    assert not _has_old_template(out["narrative"])


# ============================================================
# 6. permission_restricted
# ============================================================

def test_scenario_permission_restricted():
    facts = {
        "l3_permission": "watch",
        "l3_grade": "none",
    }
    state = {
        "factor_cards": _factor_cards_sample(),
        "composite_factors": _composite_sample(),
    }
    assert detect_scenario(facts, state) == SCENARIO_PERMISSION_RESTRICTED
    out = generate_no_opportunity_narrative(facts, state)
    assert "【结构】" in out["narrative"]
    assert "仅观察" in out["narrative"] or "permission" in out["narrative"].lower()
    assert not _has_old_template(out["narrative"])
    # primary_drivers 至少含具体数值
    assert any(_has_concrete_value(d.get("text", ""))
               for d in out["primary_drivers"])


# ============================================================
# 7. position_cap_zero
# ============================================================

def test_scenario_position_cap_zero():
    facts = {
        "l4_position_cap": 0.0,
        "l3_permission": "can_open",  # 不会落到 permission_restricted
    }
    state = {
        "factor_cards": _factor_cards_sample(),
        "composite_factors": _composite_sample(),
    }
    assert detect_scenario(facts, state) == SCENARIO_POSITION_CAP_ZERO
    out = generate_no_opportunity_narrative(facts, state)
    assert "【结构】" in out["narrative"]
    assert "0%" in out["narrative"] or "critical" in out["narrative"]
    assert not _has_old_template(out["narrative"])


# ============================================================
# 8. grade_none(最常见,FLAT 状态机)
# ============================================================

def test_scenario_grade_none():
    facts = {
        "l3_grade": "none",
        "l3_permission": "can_open",  # 不触发 permission_restricted
        "l4_position_cap": 0.10,
        "state_machine_current": "FLAT",
    }
    state = {
        "factor_cards": _factor_cards_sample(),
        "composite_factors": _composite_sample(),
    }
    assert detect_scenario(facts, state) == SCENARIO_GRADE_NONE
    out = generate_no_opportunity_narrative(facts, state)
    assert "【结构】" in out["narrative"]
    assert "【解读】" in out["narrative"]
    assert "【关键】" in out["narrative"]
    assert "【结论】" in out["narrative"]
    assert not _has_old_template(out["narrative"])
    # primary_drivers 至少 3 条
    assert len(out["primary_drivers"]) >= 3


# ============================================================
# 跨场景:全部不含老模板词(总反退化)
# ============================================================

def test_no_scenario_has_old_template_words():
    """跨 8 场景跑一遍,任何场景都不能输出"执行许可被收紧到"等老模板词。"""
    scenarios = [
        ({"cold_start_warming_up": True}, {}),
        ({"l5_extreme_event_detected": True}, {}),
        ({"state_machine_current": "PROTECTION"}, {}),
        ({"fallback_level": "level_3"}, {}),
        ({"state_machine_current": "POST_PROTECTION_REASSESS"}, {}),
        ({"l3_permission": "watch"}, {}),
        ({"l4_position_cap": 0.0, "l3_permission": "can_open"}, {}),
        ({"l3_grade": "none", "l3_permission": "can_open",
          "state_machine_current": "FLAT"}, {}),
    ]
    for facts, state in scenarios:
        out = generate_no_opportunity_narrative(facts, state)
        assert not _has_old_template(out["narrative"]), (
            f"narrative 含老模板词 (facts={facts}): {out['narrative']!r}"
        )
