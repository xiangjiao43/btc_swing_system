"""
tests/test_state_machine.py — Sprint 1.5a 14 档状态机单测(对齐建模 §5)。

覆盖:
  * 所有 §5.2 迁移规则的"全满足触发 / 缺一不迁"路径
  * §5.3 FLIP_WATCH 动态冷却乘数计算
  * §5.4 三条核心纪律(拒绝 HOLD→反向 PLANNED、PROTECTION→不经 PPR、PPR→PLANNED)
  * §5.5 on_enter 副作用字段填充
  * PROTECTION 全局入口(任何状态都能触发)+ POST_PROTECTION_REASSESS 出口
  * 对称空头分支
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pytest

from src.strategy.state_machine import (
    DisciplineViolation,
    StateMachine,
    VALID_STATES,
)


# ==================================================================
# Helpers
# ==================================================================

def _ts(delta_hours: float = 0, *, base: str = "2026-04-24T12:00:00Z") -> str:
    b = datetime.strptime(base, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (b + timedelta(hours=delta_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _state(
    *,
    l1_regime: str = "trend_up",
    volatility_regime: str = "normal",
    l2_stance: str = "neutral",
    l2_stance_confidence: float = 0.5,
    l3_grade: str = "none",
    l3_permission: str = "watch",
    l4_overall_risk: str = "moderate",
    l5_macro_stance: str = "risk_neutral",
    cycle_position: Optional[str] = None,
    l5_extreme: bool = False,
    fallback_level: Optional[int] = None,
    trade_plan: Optional[dict] = None,
    lifecycle: Optional[dict] = None,
    adjudicator: Optional[dict] = None,
    macro_events: Optional[dict] = None,
    pipeline_meta: Optional[dict] = None,
    protection_mode: bool = False,
    ref_ts: str = "2026-04-24T12:00:00Z",
) -> dict:
    return {
        "reference_timestamp_utc": ref_ts,
        "protection_mode": protection_mode,
        "evidence_reports": {
            "layer_1": {
                "regime": l1_regime,
                "volatility_regime": volatility_regime,
            },
            "layer_2": {
                "stance": l2_stance,
                "stance_confidence": l2_stance_confidence,
            },
            "layer_3": {
                "opportunity_grade": l3_grade,
                "execution_permission": l3_permission,
            },
            "layer_4": {"overall_risk_level": l4_overall_risk},
            "layer_5": {
                "macro_stance": l5_macro_stance,
                "extreme_event_detected": l5_extreme,
            },
        },
        "composite_factors": {
            "cycle_position": (
                {"cycle_position": cycle_position} if cycle_position else {}
            ),
        },
        "trade_plan": trade_plan or {},
        "lifecycle": lifecycle or {},
        "adjudicator": adjudicator or {},
        "macro_events": macro_events or {},
        "pipeline_meta": {
            **(pipeline_meta or {}),
            "fallback_level": fallback_level,
        },
    }


def _prev_record(
    current_state: str,
    state_entered_at_utc: str,
    flip_watch_bounds: Optional[dict] = None,
) -> dict:
    return {
        "run_timestamp_utc": state_entered_at_utc,
        "state": {
            "state_machine": {
                "current_state": current_state,
                "state_entered_at_utc": state_entered_at_utc,
                "flip_watch_bounds": flip_watch_bounds,
            },
        },
    }


@pytest.fixture(scope="module")
def sm() -> StateMachine:
    return StateMachine()


# ==================================================================
# Discipline/validity pre-checks
# ==================================================================

def test_returned_state_always_in_14_whitelist(sm: StateMachine):
    r = sm.compute_next(_state())
    assert r["current_state"] in VALID_STATES


# ==================================================================
# FLAT → LONG_PLANNED / SHORT_PLANNED
# ==================================================================

_LP_OK_KW = dict(
    l1_regime="trend_up",
    l2_stance="bullish",
    l2_stance_confidence=0.7,
    l3_grade="A",
    l3_permission="can_open",
    l4_overall_risk="moderate",
    l5_macro_stance="risk_neutral",
)


def test_01_flat_to_long_planned_all_satisfied(sm: StateMachine):
    r = sm.compute_next(_state(**_LP_OK_KW))
    assert r["previous_state"] == "FLAT"
    assert r["current_state"] == "LONG_PLANNED"
    assert "多头条件满足" in r["transition_reason"]
    # §5.5 on_enter_effects 生效
    assert r["on_enter_effects"]["applied"] is True
    assert "create_lifecycle_draft" in r["on_enter_effects"]["actions"]


def test_02_flat_no_l1_regime_wrong_stays(sm: StateMachine):
    r = sm.compute_next(_state(**{**_LP_OK_KW, "l1_regime": "chaos"}))
    assert r["current_state"] == "FLAT"


def test_03_flat_stance_confidence_below_threshold_stays(sm: StateMachine):
    r = sm.compute_next(
        _state(**{**_LP_OK_KW, "l2_stance_confidence": 0.55}),
    )
    assert r["current_state"] == "FLAT"


def test_04_flat_l3_grade_C_stays(sm: StateMachine):
    r = sm.compute_next(_state(**{**_LP_OK_KW, "l3_grade": "C"}))
    assert r["current_state"] == "FLAT"


def test_05_flat_l4_critical_risk_stays(sm: StateMachine):
    r = sm.compute_next(
        _state(**{**_LP_OK_KW, "l4_overall_risk": "critical"}),
    )
    assert r["current_state"] == "FLAT"


def test_06_flat_l5_extreme_risk_off_stays(sm: StateMachine):
    r = sm.compute_next(
        _state(**{**_LP_OK_KW, "l5_macro_stance": "extreme_risk_off"}),
    )
    assert r["current_state"] == "FLAT"


def test_07_flat_to_short_planned_dynamic_threshold(sm: StateMachine):
    r = sm.compute_next(_state(
        l1_regime="trend_down",
        l2_stance="bearish",
        l2_stance_confidence=0.7,
        l3_grade="A",
        l3_permission="can_open",
        l4_overall_risk="moderate",
        l5_macro_stance="risk_neutral",
    ))
    assert r["current_state"] == "SHORT_PLANNED"


def test_08_flat_short_confidence_below_threshold_stays(sm: StateMachine):
    r = sm.compute_next(_state(
        l1_regime="trend_down",
        l2_stance="bearish",
        l2_stance_confidence=0.6,  # below short_min=0.65
        l3_grade="A", l3_permission="can_open",
    ))
    assert r["current_state"] == "FLAT"


# ==================================================================
# LONG_PLANNED → LONG_OPEN(1H 收盘确认)
# ==================================================================

def test_09_long_planned_to_long_open_entry_filled(sm: StateMachine):
    prev = _prev_record(
        current_state="LONG_PLANNED",
        state_entered_at_utc=_ts(-2),
    )
    state = _state(
        trade_plan={"entry_zone_filled_confirmed_1h": True},
    )
    r = sm.compute_next(state, previous_record=prev, now_utc=_ts(0))
    assert r["previous_state"] == "LONG_PLANNED"
    assert r["current_state"] == "LONG_OPEN"


def test_10_long_planned_no_fill_stays(sm: StateMachine):
    prev = _prev_record(
        current_state="LONG_PLANNED", state_entered_at_utc=_ts(-2),
    )
    r = sm.compute_next(_state(), previous_record=prev, now_utc=_ts(0))
    assert r["current_state"] == "LONG_PLANNED"


# ==================================================================
# LONG_OPEN → LONG_HOLD 的四种走势条件
# ==================================================================

def test_11_long_open_to_hold_time_plus_pnl(sm: StateMachine):
    prev = _prev_record("LONG_OPEN", _ts(-25))
    r = sm.compute_next(
        _state(lifecycle={"hours_since_open": 25, "floating_pnl_pct": 3.0}),
        previous_record=prev, now_utc=_ts(0),
    )
    assert r["current_state"] == "LONG_HOLD"


def test_12_long_open_to_hold_time_plus_structure(sm: StateMachine):
    prev = _prev_record("LONG_OPEN", _ts(-25))
    r = sm.compute_next(
        _state(lifecycle={
            "hours_since_open": 25,
            "crossed_first_4h_close_no_reverse": True,
        }),
        previous_record=prev, now_utc=_ts(0),
    )
    assert r["current_state"] == "LONG_HOLD"


def test_13_long_open_to_hold_time_plus_pullback(sm: StateMachine):
    prev = _prev_record("LONG_OPEN", _ts(-25))
    r = sm.compute_next(
        _state(lifecycle={
            "hours_since_open": 25,
            "survived_pullback_rebound_cycle": True,
        }),
        previous_record=prev, now_utc=_ts(0),
    )
    assert r["current_state"] == "LONG_HOLD"


def test_14_long_open_to_hold_tp1_half_distance(sm: StateMachine):
    prev = _prev_record("LONG_OPEN", _ts(-5))  # time condition not met
    r = sm.compute_next(
        _state(lifecycle={
            "hours_since_open": 5,
            "tp1_distance_progress_pct": 50,
        }),
        previous_record=prev, now_utc=_ts(0),
    )
    assert r["current_state"] == "LONG_HOLD"


# ==================================================================
# LONG_OPEN → LONG_EXIT 的三种触发
# ==================================================================

def test_15_long_open_to_exit_hard_invalidation(sm: StateMachine):
    prev = _prev_record("LONG_OPEN", _ts(-3))
    state = _state()
    state["evidence_reports"]["layer_4"]["hard_invalidation_breached"] = True
    r = sm.compute_next(state, previous_record=prev, now_utc=_ts(0))
    assert r["current_state"] == "LONG_EXIT"


def test_16_long_open_to_exit_stance_flip_within_12h(sm: StateMachine):
    prev = _prev_record("LONG_OPEN", _ts(-6))
    r = sm.compute_next(
        _state(
            l2_stance="bearish",
            l2_stance_confidence=0.8,
            lifecycle={"hours_since_open": 6, "l2_stance_flipped": True},
        ),
        previous_record=prev, now_utc=_ts(0),
    )
    # L2 stance_flipped + confidence 0.8 + within 12h → LONG_EXIT
    # but _state builder puts stance_flipped in lifecycle; our extractor reads l2.stance_flipped
    # Let's also set it via evidence_reports
    # Actually the extractor reads l2.stance_flipped; lifecycle isn't wired there.
    # So let's redo:
    state = _state(
        l2_stance="bearish", l2_stance_confidence=0.8,
        lifecycle={"hours_since_open": 6},
    )
    state["evidence_reports"]["layer_2"]["stance_flipped"] = True
    r = sm.compute_next(state, previous_record=prev, now_utc=_ts(0))
    assert r["current_state"] == "LONG_EXIT"
    assert any("stance_flip_within" in m for m in r["matched_conditions"])


def test_17_long_open_to_exit_thesis_invalidated(sm: StateMachine):
    prev = _prev_record("LONG_OPEN", _ts(-10))
    r = sm.compute_next(
        _state(
            lifecycle={
                "hours_since_open": 10,
                "thesis_still_valid": "invalidated",
            },
        ),
        previous_record=prev, now_utc=_ts(0),
    )
    assert r["current_state"] == "LONG_EXIT"


# ==================================================================
# LONG_HOLD → LONG_TRIM(任一触发)
# ==================================================================

def test_18_long_hold_to_trim_tp_target(sm: StateMachine):
    prev = _prev_record("LONG_HOLD", _ts(-48))
    r = sm.compute_next(
        _state(lifecycle={"tp_target_hit": True}),
        previous_record=prev, now_utc=_ts(0),
    )
    assert r["current_state"] == "LONG_TRIM"


# ==================================================================
# LONG_EXIT → FLIP_WATCH / FLAT
# ==================================================================

def test_19_long_exit_to_flip_watch(sm: StateMachine):
    prev = _prev_record("LONG_EXIT", _ts(-2))
    r = sm.compute_next(
        _state(l2_stance="bearish", l1_regime="transition_down"),
        previous_record=prev, now_utc=_ts(0),
    )
    assert r["current_state"] == "FLIP_WATCH"
    # 进入时锁定 FLIP_WATCH bounds
    b = r["flip_watch_bounds"]
    assert b is not None
    assert b["effective_min_hours"] >= 8
    assert b["effective_max_hours"] <= 168


def test_20_long_exit_to_flat_no_flip_conditions(sm: StateMachine):
    prev = _prev_record("LONG_EXIT", _ts(-2))
    # L1 still trend_up → no flip
    r = sm.compute_next(
        _state(l2_stance="neutral", l1_regime="trend_up"),
        previous_record=prev, now_utc=_ts(0),
    )
    assert r["current_state"] == "FLAT"


# ==================================================================
# FLIP_WATCH 动态冷却 + 迁出
# ==================================================================

def test_21_flip_watch_to_short_planned_after_min(sm: StateMachine):
    # 进入 FLIP_WATCH 20 小时(超过 base min 18h)
    bounds = {
        "effective_min_hours": 18, "effective_max_hours": 96,
    }
    prev = _prev_record(
        "FLIP_WATCH", _ts(-20), flip_watch_bounds=bounds,
    )
    r = sm.compute_next(
        _state(
            l2_stance="bearish", l2_stance_confidence=0.7,
            l3_grade="A", l3_permission="can_open",
            l1_regime="trend_down",
            l4_overall_risk="moderate",
            lifecycle={"prev_cycle_side": "long", "long_thesis_invalidated": True},
        ),
        previous_record=prev, now_utc=_ts(0),
    )
    assert r["current_state"] == "SHORT_PLANNED"


def test_22_flip_watch_to_flat_after_max(sm: StateMachine):
    bounds = {"effective_min_hours": 18, "effective_max_hours": 96}
    prev = _prev_record(
        "FLIP_WATCH", _ts(-100), flip_watch_bounds=bounds,
    )
    r = sm.compute_next(
        _state(l1_regime="trend_up", l2_stance="bullish",
               lifecycle={"prev_cycle_side": "long"}),
        previous_record=prev, now_utc=_ts(0),
    )
    assert r["current_state"] == "FLAT"


def test_23_flip_watch_cooling_stays_within_min(sm: StateMachine):
    bounds = {"effective_min_hours": 18, "effective_max_hours": 96}
    prev = _prev_record("FLIP_WATCH", _ts(-5), flip_watch_bounds=bounds)
    r = sm.compute_next(
        _state(l2_stance="bearish", l2_stance_confidence=0.9,
               l3_grade="A", l3_permission="can_open",
               l1_regime="trend_down",
               lifecycle={"prev_cycle_side": "long", "long_thesis_invalidated": True}),
        previous_record=prev, now_utc=_ts(0),
    )
    # hours_in=5 < min=18 → 保持 FLIP_WATCH
    assert r["current_state"] == "FLIP_WATCH"


def test_24_flip_watch_multipliers_late_bull_low_vol(sm: StateMachine):
    """§5.3 乘数验证:cycle_position=late_bull × volatility=low = 0.7 × 0.8 = 0.56
       effective_min = max(8, 18*0.56)= max(8, 10.08) = 10.08
       effective_max = min(168, 96*0.56)= min(168, 53.76) = 53.76
    """
    prev = _prev_record("LONG_EXIT", _ts(-1))
    r = sm.compute_next(
        _state(
            l1_regime="trend_down", l2_stance="bearish",
            cycle_position="late_bull", volatility_regime="low",
        ),
        previous_record=prev, now_utc=_ts(0),
    )
    assert r["current_state"] == "FLIP_WATCH"
    b = r["flip_watch_bounds"]
    assert b["effective_min_hours"] == pytest.approx(10.08, abs=0.02)
    assert b["effective_max_hours"] == pytest.approx(53.76, abs=0.02)
    assert b["multiplier_product"] == pytest.approx(0.56, abs=0.01)


# ==================================================================
# PROTECTION 全局入口 + POST_PROTECTION_REASSESS
# ==================================================================

def test_25_any_state_to_protection_on_extreme_event(sm: StateMachine):
    prev = _prev_record("LONG_HOLD", _ts(-10))
    r = sm.compute_next(
        _state(l5_extreme=True),
        previous_record=prev, now_utc=_ts(0),
    )
    assert r["current_state"] == "PROTECTION"


def test_26_protection_to_post_protection_reassess(sm: StateMachine):
    prev = _prev_record("PROTECTION", _ts(-6))
    r = sm.compute_next(
        _state(
            l5_extreme=False,
            macro_events={"extreme_event_ended": True},
            pipeline_meta={"data_health_ok": True},
        ),
        previous_record=prev, now_utc=_ts(0),
    )
    assert r["current_state"] == "POST_PROTECTION_REASSESS"


# ==================================================================
# 纪律 1:HOLD 不能直跳反向 PLANNED
# ==================================================================

def test_27_long_hold_to_short_planned_raises(sm: StateMachine):
    # 我们手动绕过迁移函数,直接走 _build_result 来验证纪律校验
    prev = _prev_record("LONG_HOLD", _ts(-1))
    fields = {}
    with pytest.raises(DisciplineViolation):
        sm._build_result(
            prev_state="LONG_HOLD",
            target="SHORT_PLANNED",
            reason="forced",
            matched=[],
            fields=fields,
            prev_entered_at=_ts(-1),
            now=_ts(0),
        )


# ==================================================================
# 纪律 3:POST_PROTECTION_REASSESS 禁止进入 PLANNED
# ==================================================================

def test_28_ppr_refuses_planned_target(sm: StateMachine):
    prev = _prev_record("POST_PROTECTION_REASSESS", _ts(-6))
    r = sm.compute_next(
        _state(
            lifecycle={"post_protection_next_target": "LONG_PLANNED"},
        ),
        previous_record=prev, now_utc=_ts(0),
    )
    # 外部指定 LONG_PLANNED → 拒绝,保持 POST_PROTECTION_REASSESS
    assert r["current_state"] == "POST_PROTECTION_REASSESS"


def test_29_ppr_allows_flat_or_flip_watch(sm: StateMachine):
    prev = _prev_record("POST_PROTECTION_REASSESS", _ts(-6))
    r = sm.compute_next(
        _state(lifecycle={"post_protection_next_target": "FLAT"}),
        previous_record=prev, now_utc=_ts(0),
    )
    assert r["current_state"] == "FLAT"


def test_30_ppr_force_min_hold_hours(sm: StateMachine):
    """§5.2:POST_PROTECTION_REASSESS 强制持续至少一个 4H 周期"""
    prev = _prev_record("POST_PROTECTION_REASSESS", _ts(-2))
    r = sm.compute_next(
        _state(lifecycle={"post_protection_next_target": "FLAT"}),
        previous_record=prev, now_utc=_ts(0),
    )
    # 2h < 4h → 保持
    assert r["current_state"] == "POST_PROTECTION_REASSESS"


# ==================================================================
# 对称空头:SHORT_OPEN → SHORT_HOLD, SHORT_EXIT → FLIP_WATCH 等
# ==================================================================

def test_31_short_planned_to_short_open(sm: StateMachine):
    prev = _prev_record("SHORT_PLANNED", _ts(-2))
    r = sm.compute_next(
        _state(trade_plan={"entry_zone_filled_confirmed_1h": True}),
        previous_record=prev, now_utc=_ts(0),
    )
    assert r["current_state"] == "SHORT_OPEN"


def test_32_short_open_to_short_hold_time_plus_pnl(sm: StateMachine):
    prev = _prev_record("SHORT_OPEN", _ts(-25))
    r = sm.compute_next(
        _state(lifecycle={"hours_since_open": 25, "floating_pnl_pct": 3.0}),
        previous_record=prev, now_utc=_ts(0),
    )
    assert r["current_state"] == "SHORT_HOLD"


def test_33_short_hold_to_short_trim_tp_target(sm: StateMachine):
    prev = _prev_record("SHORT_HOLD", _ts(-24))
    r = sm.compute_next(
        _state(lifecycle={"tp_target_hit": True}),
        previous_record=prev, now_utc=_ts(0),
    )
    assert r["current_state"] == "SHORT_TRIM"


def test_34_short_exit_to_flip_watch(sm: StateMachine):
    prev = _prev_record("SHORT_EXIT", _ts(-1))
    r = sm.compute_next(
        _state(l1_regime="trend_up", l2_stance="bullish"),
        previous_record=prev, now_utc=_ts(0),
    )
    assert r["current_state"] == "FLIP_WATCH"


# ==================================================================
# on_enter 副作用 & no-op 行为
# ==================================================================

def test_35_stable_no_on_enter_effects(sm: StateMachine):
    prev = _prev_record("FLAT", _ts(-10))
    r = sm.compute_next(_state(), previous_record=prev, now_utc=_ts(0))
    assert r["current_state"] == "FLAT"
    assert r["stable_in_state"] is True
    assert r["on_enter_effects"]["applied"] is False


def test_36_flip_watch_on_enter_has_bounds(sm: StateMachine):
    prev = _prev_record("LONG_EXIT", _ts(-1))
    r = sm.compute_next(
        _state(l1_regime="trend_down", l2_stance="bearish"),
        previous_record=prev, now_utc=_ts(0),
    )
    assert r["current_state"] == "FLIP_WATCH"
    assert "lock_flip_watch_effective_bounds" in r["on_enter_effects"]["actions"]
    assert r["on_enter_effects"]["flip_watch_bounds"] is not None


# ==================================================================
# 初次运行 / 未知 previous_state 归零到 FLAT
# ==================================================================

def test_37_no_previous_record_starts_from_flat(sm: StateMachine):
    r = sm.compute_next(_state(), previous_record=None)
    assert r["previous_state"] == "FLAT"


def test_38_unknown_previous_state_normalized_to_flat(sm: StateMachine):
    prev = _prev_record("active_long_execution", _ts(-5))  # old name, invalid
    r = sm.compute_next(_state(), previous_record=prev, now_utc=_ts(0))
    assert r["previous_state"] == "FLAT"


# ==================================================================
# 1H 信号不能单独触发方向切换(纪律 2 的意图验证)
# ==================================================================

def test_39_1h_only_stance_flip_outside_open_phase_no_exit(sm: StateMachine):
    """LONG_HOLD 时 stance 翻转单独不会触发 LONG_EXIT;
       §5.2 早期保护仅限 LONG_OPEN 且 < 12h。"""
    prev = _prev_record("LONG_HOLD", _ts(-48))
    state = _state(
        l2_stance="bearish", l2_stance_confidence=0.9,
    )
    state["evidence_reports"]["layer_2"]["stance_flipped"] = True
    r = sm.compute_next(state, previous_record=prev, now_utc=_ts(0))
    # HOLD 时 L2 翻转不直接进 EXIT;需 thesis_still_valid 或 macro 等任一成立
    assert r["current_state"] in {"LONG_HOLD", "LONG_TRIM"}  # 不是 EXIT / SHORT_PLANNED


# ==================================================================
# Fallback Level 3 触发 PROTECTION
# ==================================================================

def test_40_fallback_level_3_triggers_protection(sm: StateMachine):
    prev = _prev_record("FLAT", _ts(-1))
    r = sm.compute_next(
        _state(fallback_level=3),
        previous_record=prev, now_utc=_ts(0),
    )
    assert r["current_state"] == "PROTECTION"
