"""
tests/test_lifecycle_fsm.py — Sprint 1.14b 单测

覆盖:
  * 基本迁移链(FLAT → LONG_PLANNED → LONG_OPEN → ...)
  * auto timeout(LONG_CLOSED / COOLDOWN / STOP_TRIGGERED / FLAT_AFTER_STOP)
  * 方向冲突(LONG_OPEN + open_short)
  * _default 分支
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.pipeline.lifecycle_fsm import LifecycleFSM


def _now(delta_minutes: float = 0) -> str:
    """固定基准时间,加/减 delta_minutes。"""
    base = datetime(2026, 4, 24, 12, 0, 0, tzinfo=timezone.utc)
    t = base + timedelta(minutes=delta_minutes)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture(scope="module")
def fsm() -> LifecycleFSM:
    return LifecycleFSM()


# ==================================================================
# 基本 LONG 链
# ==================================================================

def test_flat_open_long(fsm: LifecycleFSM):
    out = fsm.compute_next("FLAT", "open_long", _now(), _now())
    assert out["current_lifecycle"] == "LONG_PLANNED"
    assert out["previous_lifecycle"] == "FLAT"
    assert out["transition_triggered_by"] == "action"
    assert out["conflict_detected"] is False


def test_long_planned_open_long(fsm: LifecycleFSM):
    out = fsm.compute_next("LONG_PLANNED", "open_long", _now(), _now())
    assert out["current_lifecycle"] == "LONG_OPEN"


def test_long_open_scale_in_long_moves_to_scaling(fsm: LifecycleFSM):
    out = fsm.compute_next("LONG_OPEN", "scale_in_long", _now(), _now())
    assert out["current_lifecycle"] == "LONG_SCALING"


def test_long_scaling_hold_returns_to_open(fsm: LifecycleFSM):
    out = fsm.compute_next("LONG_SCALING", "hold", _now(), _now())
    assert out["current_lifecycle"] == "LONG_OPEN"


def test_long_open_reduce_long_moves_to_reducing(fsm: LifecycleFSM):
    out = fsm.compute_next("LONG_OPEN", "reduce_long", _now(), _now())
    assert out["current_lifecycle"] == "LONG_REDUCING"


def test_long_reducing_close_long_moves_to_closed(fsm: LifecycleFSM):
    out = fsm.compute_next("LONG_REDUCING", "close_long", _now(), _now())
    assert out["current_lifecycle"] == "LONG_CLOSED"


# ==================================================================
# Auto timeout
# ==================================================================

def test_long_closed_auto_to_flat_after_60_minutes(fsm: LifecycleFSM):
    out = fsm.compute_next(
        "LONG_CLOSED", "hold",
        current_timestamp=_now(61),
        previous_transition_timestamp=_now(0),
    )
    assert out["current_lifecycle"] == "FLAT"
    assert out["transition_triggered_by"] == "auto_timeout"


def test_long_closed_stays_within_timeout(fsm: LifecycleFSM):
    out = fsm.compute_next(
        "LONG_CLOSED", "hold",
        current_timestamp=_now(30),
        previous_transition_timestamp=_now(0),
    )
    # 未到 60 分钟,保持 LONG_CLOSED(该状态无 action 分支,走 no_op)
    assert out["current_lifecycle"] == "LONG_CLOSED"
    assert out["transition_triggered_by"] == "no_op"


def test_cooldown_auto_to_flat_after_60_minutes(fsm: LifecycleFSM):
    out = fsm.compute_next(
        "COOLDOWN", "hold",
        current_timestamp=_now(61),
        previous_transition_timestamp=_now(0),
    )
    assert out["current_lifecycle"] == "FLAT"
    assert out["transition_triggered_by"] == "auto_timeout"


def test_long_open_pause_to_cooldown(fsm: LifecycleFSM):
    out = fsm.compute_next("LONG_OPEN", "pause", _now(), _now())
    assert out["current_lifecycle"] == "COOLDOWN"


# ==================================================================
# SHORT 镜像
# ==================================================================

def test_flat_open_short(fsm: LifecycleFSM):
    out = fsm.compute_next("FLAT", "open_short", _now(), _now())
    assert out["current_lifecycle"] == "SHORT_PLANNED"


def test_short_open_close_short_to_closed(fsm: LifecycleFSM):
    out = fsm.compute_next("SHORT_OPEN", "close_short", _now(), _now())
    assert out["current_lifecycle"] == "SHORT_CLOSED"


# ==================================================================
# 方向冲突
# ==================================================================

def test_long_open_open_short_is_conflict(fsm: LifecycleFSM):
    out = fsm.compute_next("LONG_OPEN", "open_short", _now(), _now())
    assert out["current_lifecycle"] == "LONG_OPEN"
    assert out["conflict_detected"] is True
    assert out["transition_triggered_by"] == "direction_conflict_blocked"


# ==================================================================
# 额外:STOP_TRIGGERED / FLAT_AFTER_STOP 链
# ==================================================================

def test_stop_triggered_auto_to_flat_after_stop(fsm: LifecycleFSM):
    out = fsm.compute_next(
        "STOP_TRIGGERED", "hold",
        current_timestamp=_now(121),
        previous_transition_timestamp=_now(0),
    )
    assert out["current_lifecycle"] == "FLAT_AFTER_STOP"


def test_flat_after_stop_auto_to_flat(fsm: LifecycleFSM):
    out = fsm.compute_next(
        "FLAT_AFTER_STOP", "hold",
        current_timestamp=_now(241),
        previous_transition_timestamp=_now(0),
    )
    assert out["current_lifecycle"] == "FLAT"


# ==================================================================
# _default 分支
# ==================================================================

def test_long_open_unknown_action_falls_to_default(fsm: LifecycleFSM):
    out = fsm.compute_next("LONG_OPEN", "watch", _now(), _now())
    # LONG_OPEN 没有 watch 分支,走 _default(LONG_OPEN)
    assert out["current_lifecycle"] == "LONG_OPEN"
    assert out["transition_triggered_by"] == "default"
