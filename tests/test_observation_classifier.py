"""
tests/test_observation_classifier.py — Sprint 1.5b 建模 §4.7 单测。

覆盖:
  * 四档分别触发
  * disciplined 七条硬触发任一成立即归 disciplined
  * possibly_suppressed streak(需 ≥ 42 次,不足时归 watchful)
  * cold_start_warming_up 冷启动期临时标签
  * 告警级别 warning / critical
  * 纪律条款字段存在(只读字段,不进入决策路径)
"""

from __future__ import annotations

from typing import Any, Optional

import pytest

from src.strategy import classify


# ==================================================================
# Helpers
# ==================================================================

def _state(
    *,
    l1_regime: str = "trend_up",
    l1_volatility: str = "normal",
    l1_regime_confidence: float = 0.8,
    l2_stance: str = "bullish",
    l2_stance_confidence: float = 0.7,
    l3_grade: str = "A",
    l4_overall_risk: str = "moderate",
    l5_macro_stance: str = "risk_neutral",
    cycle_position: Optional[str] = "mid_bull",
    sm_current: Optional[str] = "FLAT",
    cold_warming_up: bool = False,
    runs_completed: int = 100,
) -> dict[str, Any]:
    return {
        "evidence_reports": {
            "layer_1": {
                "regime": l1_regime,
                "volatility_regime": l1_volatility,
                "regime_confidence": l1_regime_confidence,
            },
            "layer_2": {
                "stance": l2_stance,
                "stance_confidence": l2_stance_confidence,
            },
            "layer_3": {
                "opportunity_grade": l3_grade,
            },
            "layer_4": {"overall_risk_level": l4_overall_risk},
            "layer_5": {"macro_stance": l5_macro_stance},
        },
        "composite_factors": {
            "cycle_position": (
                {"cycle_position": cycle_position}
                if cycle_position else {}
            ),
        },
        "cold_start": {
            "warming_up": cold_warming_up,
            "runs_completed": runs_completed,
            "threshold": 42,
        },
        "state_machine": {"current_state": sm_current},
    }


def _prior_records(n_suppressed: int) -> list[dict[str, Any]]:
    """构造 n 条 suppressed_base_satisfied=True 的历史记录(越新越靠前)。"""
    return [
        {
            "state": {
                "observation": {
                    "suppressed_base_satisfied": True,
                    "observation_category": "possibly_suppressed",
                },
            },
        }
        for _ in range(n_suppressed)
    ]


# ==================================================================
# 四档触发
# ==================================================================

def test_01_cold_start_warming_up_temporary_label():
    r = classify(_state(cold_warming_up=True, runs_completed=10))
    assert r["observation_category"] == "cold_start_warming_up"
    assert r["alert_level"] is None


def test_02_disciplined_l1_chaos():
    r = classify(_state(l1_regime="chaos", runs_completed=100))
    assert r["observation_category"] == "disciplined"
    assert any("l1_regime=chaos" in s for s in r["reason"].split(";") + [r["reason"]])


def test_03_watchful_when_c_grade_with_risk_ok():
    r = classify(_state(
        l3_grade="C", l4_overall_risk="moderate",
        l2_stance="bullish", runs_completed=100,
    ))
    assert r["observation_category"] == "watchful"


def test_04_possibly_suppressed_after_42_prior_runs():
    # 当前 tick 满足 suppressed_base 六条:
    # trend_up + regime_conf=0.8 + stance_conf=0.7 + cycle!=unclear + grade=none
    r = classify(
        _state(
            l1_regime="trend_up", l1_regime_confidence=0.8,
            l2_stance="bullish", l2_stance_confidence=0.7,
            l3_grade="none", cycle_position="mid_bull",
            runs_completed=200,
        ),
        previous_records=_prior_records(42),
    )
    assert r["observation_category"] == "possibly_suppressed"
    assert r["streak_runs"] == 43  # 42 prior + current


# ==================================================================
# disciplined 七条硬触发(任一)
# ==================================================================

def test_05_disciplined_vol_extreme():
    r = classify(_state(l1_volatility="extreme", runs_completed=100))
    assert r["observation_category"] == "disciplined"


def test_06_disciplined_l2_neutral():
    r = classify(_state(l2_stance="neutral", runs_completed=100))
    assert r["observation_category"] == "disciplined"


def test_07_disciplined_cycle_unclear():
    r = classify(_state(cycle_position="unclear", runs_completed=100))
    assert r["observation_category"] == "disciplined"


def test_08_disciplined_l4_critical():
    r = classify(_state(l4_overall_risk="critical", runs_completed=100))
    assert r["observation_category"] == "disciplined"


def test_09_disciplined_l5_extreme_risk_off():
    r = classify(_state(l5_macro_stance="extreme_risk_off", runs_completed=100))
    assert r["observation_category"] == "disciplined"


def test_10_disciplined_state_protection():
    r = classify(_state(sm_current="PROTECTION", runs_completed=100))
    assert r["observation_category"] == "disciplined"


def test_11_disciplined_state_post_protection_reassess():
    r = classify(
        _state(sm_current="POST_PROTECTION_REASSESS", runs_completed=100),
    )
    assert r["observation_category"] == "disciplined"


# ==================================================================
# possibly_suppressed 持续性检查
# ==================================================================

def test_12_insufficient_streak_stays_watchful():
    """基础条件满足但 prior streak 不够 42 → 归 watchful(grade=none 但 regime 明确)。

    但由于 grade=none,_watchful_conditions_met 要求 grade ∈ {C, none} + 其他。
    这里 L1 regime=trend_up / L2 bullish / L4 moderate,所以算 watchful。
    """
    r = classify(
        _state(
            l1_regime="trend_up", l1_regime_confidence=0.8,
            l2_stance="bullish", l2_stance_confidence=0.7,
            l3_grade="none", cycle_position="mid_bull",
            runs_completed=200,
        ),
        previous_records=_prior_records(5),  # 不足 42
    )
    # 不是 possibly_suppressed(streak 不够)→ 归 watchful
    assert r["observation_category"] == "watchful"
    assert r["streak_runs"] == 6
    assert r["suppressed_base_satisfied"] is True


def test_13_streak_broken_by_prior_non_match():
    """中间有一次 suppressed_base=False → streak 断掉。"""
    prior: list[dict] = [
        {"state": {"observation": {"suppressed_base_satisfied": True}}},
        {"state": {"observation": {"suppressed_base_satisfied": True}}},
        {"state": {"observation": {"suppressed_base_satisfied": False}}},  # 断点
    ]
    prior.extend(
        {"state": {"observation": {"suppressed_base_satisfied": True}}}
        for _ in range(40)
    )
    r = classify(
        _state(
            l1_regime="trend_up", l1_regime_confidence=0.8,
            l2_stance="bullish", l2_stance_confidence=0.7,
            l3_grade="none", cycle_position="mid_bull",
            runs_completed=200,
        ),
        previous_records=prior,
    )
    assert r["streak_runs"] == 3  # 2 prior + current(第 3 条 False 截断)


def test_14_suppressed_base_fails_if_grade_not_none():
    """L3.grade 非 none → suppressed_base_satisfied=False。"""
    r = classify(
        _state(
            l1_regime="trend_up", l1_regime_confidence=0.8,
            l3_grade="A",  # grade=A → base fails
            runs_completed=200,
        ),
        previous_records=_prior_records(100),
    )
    assert r["suppressed_base_satisfied"] is False
    # 当前 run grade=A,非 none 非 C,也非 neutral → 非 watchful 条件(grade 不在 C/none)
    # 会走到最后的 watchful 兜底
    assert r["observation_category"] == "watchful"


# ==================================================================
# 告警级别 §4.7.5
# ==================================================================

def test_15_warning_alert_at_84_run_streak():
    r = classify(
        _state(
            l1_regime="trend_up", l1_regime_confidence=0.8,
            l2_stance="bullish", l2_stance_confidence=0.7,
            l3_grade="none", cycle_position="mid_bull",
            runs_completed=200,
        ),
        previous_records=_prior_records(83),
    )
    assert r["observation_category"] == "possibly_suppressed"
    assert r["streak_runs"] == 84
    assert r["alert_level"] == "warning"


def test_16_critical_alert_at_180_run_streak():
    r = classify(
        _state(
            l1_regime="trend_up", l1_regime_confidence=0.8,
            l2_stance="bullish", l2_stance_confidence=0.7,
            l3_grade="none", cycle_position="mid_bull",
            runs_completed=300,
        ),
        previous_records=_prior_records(179),
    )
    assert r["observation_category"] == "possibly_suppressed"
    assert r["streak_runs"] == 180
    assert r["alert_level"] == "critical"


# ==================================================================
# 纪律条款(读字段)
# ==================================================================

def test_17_discipline_note_field_present():
    r = classify(_state())
    assert "discipline_note" in r
    assert "只读" in r["discipline_note"]
    assert "决策路径" in r["discipline_note"]


# ==================================================================
# cold_start 优先级:cold_start + 满足 disciplined 硬触发 → 仍归 disciplined
# ==================================================================

def test_18_cold_start_overridden_by_disciplined_hard_trigger():
    r = classify(_state(
        cold_warming_up=True, runs_completed=10,
        l1_regime="chaos",  # disciplined 硬触发
    ))
    assert r["observation_category"] == "disciplined"
