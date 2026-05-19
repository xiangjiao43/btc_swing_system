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
        # Sprint Layer-B Cleanup: composite_factors.cycle_position 已删除
        "composite_factors": {},
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
# Sprint 1.10-K-A commit 7(方案 C):14 档 → thesis dict + system_state 镜像
# ==================================================================

def test_compute_next_output_includes_thesis_and_system_state(sm: StateMachine):
    """方案 C 关键:compute_next 输出含 thesis dict + system_state 镜像
    (向后兼容:14 档 previous_state/current_state 也保留)。"""
    r = sm.compute_next(_state())
    # 14 档枚举字符串保留
    assert r["previous_state"] in VALID_STATES or r["previous_state"] is None
    assert r["current_state"] in VALID_STATES
    # 新字段在
    assert "thesis" in r
    assert "system_state" in r
    assert r["system_state"] in {"normal", "PROTECTION", "review_pending"}


def test_thesis_mirror_long_open(sm: StateMachine):
    """LONG_OPEN → thesis(direction=long, lifecycle_stage=opened, status=active)。"""
    from src.strategy.state_machine_inputs import _utc_now_iso  # noqa: F401
    prev = _prev_record("LONG_OPEN", _ts(-1))
    r = sm.compute_next(_state(), previous_record=prev, now_utc=_ts(0))
    assert r["current_state"] == "LONG_OPEN"
    assert r["thesis"] == {
        "direction": "long",
        "lifecycle_stage": "opened",
        "status": "active",
    }
    assert r["system_state"] == "normal"


def test_thesis_mirror_protection_system_state(sm: StateMachine):
    """PROTECTION → thesis=None,system_state='PROTECTION'。"""
    r = sm.compute_next(_state(l5_extreme=True))
    assert r["current_state"] == "PROTECTION"
    assert r["thesis"] is None
    assert r["system_state"] == "PROTECTION"


def test_thesis_mirror_ppr_review_pending(sm: StateMachine):
    """POST_PROTECTION_REASSESS → thesis=None,system_state='review_pending'。"""
    prev = _prev_record("POST_PROTECTION_REASSESS", _ts(-6))
    r = sm.compute_next(_state(), previous_record=prev, now_utc=_ts(0))
    assert r["current_state"] == "POST_PROTECTION_REASSESS"
    assert r["thesis"] is None
    assert r["system_state"] == "review_pending"


def test_thesis_mirror_flip_watch_normal(sm: StateMachine):
    """FLIP_WATCH → thesis=None(冷却态),system_state='normal'(不是系统态)。"""
    prev = _prev_record("FLIP_WATCH", _ts(-1))
    r = sm.compute_next(_state(), previous_record=prev, now_utc=_ts(0))
    assert r["current_state"] == "FLIP_WATCH"
    assert r["thesis"] is None
    assert r["system_state"] == "normal"


def test_thesis_mirror_flat(sm: StateMachine):
    """FLAT → thesis=None,system_state='normal'。"""
    r = sm.compute_next(_state())
    assert r["thesis"] is None
    assert r["system_state"] == "normal"


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
    """1.10-K-A commit 8 改造:LONG_EXIT → FLIP_WATCH transition 仍可发生
    (_from_LONG_EXIT 不动);进入后 thesis=None + system_state='normal'
    (FLIP_WATCH 是冷却态由 thesis.closed_at 隐式驱动,不是系统态);
    flip_watch_bounds 字段保留 None(_calc_flip_watch_bounds 已删)。"""
    prev = _prev_record("LONG_EXIT", _ts(-2))
    r = sm.compute_next(
        _state(l2_stance="bearish", l1_regime="transition_down"),
        previous_record=prev, now_utc=_ts(0),
    )
    assert r["current_state"] == "FLIP_WATCH"
    # commit 7 方案 C 镜像字段
    assert r["thesis"] is None  # 冷却态无 active thesis
    assert r["system_state"] == "normal"  # 不是系统态(只有 PROTECTION/PPR 才是)
    # commit 5 删 _calc_flip_watch_bounds 后 bounds 永远 None
    assert r["flip_watch_bounds"] is None


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

# 1.10-K-A commit 8 §X 删除:test_21_flip_watch_to_short_planned_after_min
# (FLIP_WATCH → SHORT_PLANNED 反手出口由 thesis_manager 接管,future sprint;
#  本测试无 thesis-driven 等价行为可验证)
#
# 1.10-K-A commit 8 §X 删除:test_22_flip_watch_to_flat_after_max
# (FLIP_WATCH → FLAT 超时出口已废,冷却由 thesis.closed_at 隐式驱动;
#  thesis_manager 接管后留 future sprint)
#
# 1.10-K-A commit 8 §X 删除:test_24_flip_watch_multipliers_late_bull_low_vol
# (_calc_flip_watch_bounds 整删,cycle_position / volatility 乘数计算无替代)


def test_23_flip_watch_stub_stays_when_prev_is_flip_watch(sm: StateMachine):
    """1.10-K-A commit 8 改造:_from_FLIP_WATCH stub 行为(方案 5A)。
    prev_state='FLIP_WATCH' → stub 返 None target → wrapper stay FLIP_WATCH。
    任何 fields 输入 stub 都忽略(冷却由 thesis.closed_at 驱动)。"""
    prev = _prev_record("FLIP_WATCH", _ts(-5))
    # 即使给"反手条件齐全"的 fields,stub 也忽略
    r = sm.compute_next(
        _state(l2_stance="bearish", l2_stance_confidence=0.9,
               l3_grade="A", l3_permission="can_open",
               l1_regime="trend_down"),
        previous_record=prev, now_utc=_ts(0),
    )
    # stub stay
    assert r["current_state"] == "FLIP_WATCH"
    assert r["stable_in_state"] is True
    # commit 7 方案 C 镜像字段
    assert r["thesis"] is None
    assert r["system_state"] == "normal"


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


# 1.10-K-A commit 8 §X 删除:test_29_ppr_allows_flat_or_flip_watch
# (_PPR_ALLOWED_TARGETS 整删,PPR → FLAT/FLIP_WATCH 白名单出口已废;
#  review_pending 路由由 system_state='review_pending' 驱动 — 已在
#  test_thesis_mirror_ppr_review_pending 覆盖,本测试无独立 thesis-driven 等价)


def test_30_ppr_stub_stays_regardless_of_min_hold(sm: StateMachine):
    """1.10-K-A commit 8 改造:PPR stub stay 行为(原 min_hold_hours 4H 校验已废)。
    stub 忽略 hours_in / post_protection_next_target,永远 stay。"""
    prev = _prev_record("POST_PROTECTION_REASSESS", _ts(-2))
    r = sm.compute_next(
        _state(lifecycle={"post_protection_next_target": "FLAT"}),
        previous_record=prev, now_utc=_ts(0),
    )
    # stub stay(无论 hours_in 或 next_target 是什么)
    assert r["current_state"] == "POST_PROTECTION_REASSESS"
    # commit 7 方案 C 镜像
    assert r["thesis"] is None
    assert r["system_state"] == "review_pending"


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


# 1.10-K-A commit 8 §X 删除:test_36_flip_watch_on_enter_has_bounds
# (_on_enter_effects FLIP_WATCH bounds 字段已删 + lock_flip_watch_effective_bounds
#  action 已删;_calc_flip_watch_bounds 整删,无替代行为可测)


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


# ==================================================================
# Sprint 1.5b Task B3:cycle_position 字段链路显式验证
# ==================================================================

# 1.10-K-A commit 8 §X 删除:test_41_flip_watch_reads_cycle_position_nested_field
# (_calc_flip_watch_bounds 整删,cycle_position 读取路径已废;
#  CyclePositionFactor 仍输出此字段,但已无 FLIP_WATCH 乘数消费方)
#
# 1.10-K-A commit 8 §X 删除:test_42_flip_watch_legacy_band_field_fallback
# (_calc_flip_watch_bounds 整删,legacy band 字段 fallback 路径已废)
