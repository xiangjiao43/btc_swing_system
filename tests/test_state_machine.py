"""
tests/test_state_machine.py — Sprint 1.13 系统状态分类器单测。

分成三组:
  * 各状态的"典型触发"(12 case)
  * 优先级冲突(2 case)
  * 集成 & 边界(3 case)
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from src.data.storage.connection import get_connection, init_db
from src.data.storage.dao import (
    BTCKlinesDAO, KlineRow, StrategyStateDAO,
)
from src.pipeline import StateMachine, StrategyStateBuilder


# ==================================================================
# Helpers
# ==================================================================

def _base_state(
    *,
    cold_start: bool = False,
    runs_completed: int = 100,
    l1_regime: str = "trend_up",
    volatility_regime: str = "normal",
    l2_stance: str = "neutral",
    l3_grade: str = "none",
    l3_permission: str = "watch",
    l4_cap: float = 0.0,
    l5_env: str = "neutral",
    l5_headwind: str = "neutral",
    btc_nasdaq_corr: float = 0.1,
    event_risk_level: str = "low",
    event_hours_ahead: float = None,
    nearest_event_name: str = None,
    failures: list[dict] = None,
    ref_ts: str = "2024-05-10T12:00:00Z",
) -> dict:
    """造一个 Sprint 1.12 形状的 strategy_state(evidence_reports + composite_factors)。"""
    contributing_events = []
    if event_hours_ahead is not None:
        contributing_events.append({
            "name": nearest_event_name or "SomeEvent",
            "type": "fomc",
            "hours_to": event_hours_ahead,
        })

    return {
        "reference_timestamp_utc": ref_ts,
        "cold_start": {
            "warming_up": cold_start,
            "runs_completed": runs_completed,
            "threshold": 42,
        },
        "evidence_reports": {
            "layer_1": {
                "layer_id": 1, "regime": l1_regime,
                "volatility_regime": volatility_regime,
                "health_status": "healthy",
            },
            "layer_2": {
                "layer_id": 2, "stance": l2_stance,
                "stance_confidence": 0.6,
                "health_status": "healthy",
            },
            "layer_3": {
                "layer_id": 3, "opportunity_grade": l3_grade, "grade": l3_grade,
                "execution_permission": l3_permission,
                "health_status": "healthy",
            },
            "layer_4": {
                "layer_id": 4, "position_cap": l4_cap,
                "health_status": "healthy",
            },
            "layer_5": {
                "layer_id": 5,
                "macro_environment": l5_env,
                "macro_headwind_vs_btc": l5_headwind,
                "btc_nasdaq_correlation": btc_nasdaq_corr,
                "health_status": "healthy",
            },
        },
        "composite_factors": {
            "event_risk": {
                "factor": "event_risk",
                "band": event_risk_level,
                "contributing_events": contributing_events,
            },
        },
        "pipeline_meta": {
            "failures": failures or [],
            "degraded_stages": [],
        },
    }


@pytest.fixture
def sm():
    return StateMachine()


@pytest.fixture
def conn():
    tmp = Path(tempfile.mkdtemp()) / "sm.db"
    init_db(db_path=tmp, verbose=False)
    c = get_connection(tmp)
    yield c
    c.close()


# ==================================================================
# 1. cold_start_warming_up
# ==================================================================

def test_cold_start_triggered(sm):
    state = _base_state(cold_start=True, runs_completed=5)
    r = sm.determine_state(state)
    assert r["current_state"] == "cold_start_warming_up"
    assert "冷启动" in r["transition_reason"]
    # 模板填进来了
    assert "5/42" in r["transition_reason"]


# ==================================================================
# 2. degraded_data_mode(3 个失败)
# ==================================================================

def test_degraded_data_mode(sm):
    failures = [{"stage": s, "error_type": "X", "error_message": "x"}
                for s in ("coinglass", "glassnode", "macro")]
    state = _base_state(failures=failures)
    r = sm.determine_state(state)
    assert r["current_state"] == "degraded_data_mode"
    assert "3" in r["transition_reason"]


# ==================================================================
# 3. chaos_pause
# ==================================================================

def test_chaos_pause(sm):
    state = _base_state(l1_regime="chaos", volatility_regime="extreme")
    r = sm.determine_state(state)
    assert r["current_state"] == "chaos_pause"
    assert "chaos" in r["transition_reason"]


# ==================================================================
# 4. active_long_execution
# ==================================================================

def test_active_long_execution(sm):
    state = _base_state(
        l2_stance="bullish", l3_grade="A", l3_permission="can_open",
        l4_cap=0.12,
    )
    r = sm.determine_state(state)
    assert r["current_state"] == "active_long_execution"
    # 模板字段替换验证
    reason = r["transition_reason"]
    assert "Grade=A" in reason
    assert "0.12" in reason
    assert "can_open" in reason


# ==================================================================
# 5. active_short_execution
# ==================================================================

def test_active_short_execution(sm):
    state = _base_state(
        l2_stance="bearish", l3_grade="A", l3_permission="can_open",
        l4_cap=0.10,
    )
    r = sm.determine_state(state)
    assert r["current_state"] == "active_short_execution"


# ==================================================================
# 6. disciplined_bull_watch
# ==================================================================

def test_disciplined_bull_watch(sm):
    state = _base_state(
        l2_stance="bullish", l3_grade="C", l3_permission="watch",
        l4_cap=0.0,
    )
    r = sm.determine_state(state)
    assert r["current_state"] == "disciplined_bull_watch"


# ==================================================================
# 7. neutral_observation(兜底)
# ==================================================================

def test_neutral_observation(sm):
    state = _base_state(l2_stance="neutral")
    r = sm.determine_state(state)
    assert r["current_state"] == "neutral_observation"


# ==================================================================
# 8. event_window_freeze(high + 12h)
# ==================================================================

def test_event_window_freeze(sm):
    state = _base_state(event_risk_level="high", event_hours_ahead=12,
                        nearest_event_name="FOMC")
    r = sm.determine_state(state)
    assert r["current_state"] == "event_window_freeze"
    assert "FOMC" in r["transition_reason"]
    assert "12" in r["transition_reason"]


# ==================================================================
# 9. macro_shock_pause
# ==================================================================

def test_macro_shock_pause(sm):
    state = _base_state(
        l5_env="risk_off", l5_headwind="strong_headwind",
        btc_nasdaq_corr=0.82,
    )
    r = sm.determine_state(state)
    assert r["current_state"] == "macro_shock_pause"


# ==================================================================
# 10. post_execution_cooldown(30 分钟前 active_*)
# ==================================================================

def test_post_execution_cooldown_30min(sm, conn):
    # 写一条 30 分钟前的 active_long_execution 历史
    past = datetime(2024, 5, 10, 11, 30, tzinfo=timezone.utc)
    past_ts = past.strftime("%Y-%m-%dT%H:%M:%SZ")
    StrategyStateDAO.insert_state(
        conn, run_timestamp_utc=past_ts,
        run_id="r-past", run_trigger="manual", rules_version="v1",
        ai_model_actual=None,
        state={"state_machine": {"current_state": "active_long_execution"}},
    )
    conn.commit()

    state = _base_state(ref_ts="2024-05-10T12:00:00Z",
                        l2_stance="neutral")  # 不给 active 条件
    r = sm.determine_state(state, conn=conn)
    assert r["current_state"] == "post_execution_cooldown"
    # 模板里 minutes 应该 ~30
    assert "30" in r["transition_reason"]


# ==================================================================
# 11. post_execution_cooldown 150 分钟前就不再阻塞
# ==================================================================

def test_post_execution_cooldown_past_window(sm, conn):
    past = datetime(2024, 5, 10, 9, 30, tzinfo=timezone.utc)  # 150 分钟前
    StrategyStateDAO.insert_state(
        conn, run_timestamp_utc=past.strftime("%Y-%m-%dT%H:%M:%SZ"),
        run_id="r-past", run_trigger="manual", rules_version="v1",
        ai_model_actual=None,
        state={"state_machine": {"current_state": "active_long_execution"}},
    )
    conn.commit()

    # 此时给 active_long 条件 → 应进入 active_long_execution(cooldown 已过)
    state = _base_state(
        ref_ts="2024-05-10T12:00:00Z",
        l2_stance="bullish", l3_grade="A", l3_permission="can_open",
        l4_cap=0.12,
    )
    r = sm.determine_state(state, conn=conn)
    assert r["current_state"] == "active_long_execution"


# ==================================================================
# 12. stop_triggered
# ==================================================================

def test_stop_triggered(sm):
    state = _base_state(l2_stance="bullish", l3_grade="A",
                        l3_permission="can_open", l4_cap=0.1)
    account = {"long_position_size": 0.05, "stop_triggered": True}
    r = sm.determine_state(state, account_state=account)
    assert r["current_state"] == "stop_triggered"


# ==================================================================
# 13. 优先级:chaos + active 条件同时满足 → chaos_pause
# ==================================================================

def test_priority_chaos_beats_active(sm):
    state = _base_state(
        l1_regime="chaos", volatility_regime="extreme",
        l2_stance="bullish", l3_grade="A", l3_permission="can_open",
        l4_cap=0.1,
    )
    r = sm.determine_state(state)
    assert r["current_state"] == "chaos_pause"
    # transition_evidence 里能看到 evaluated_order
    assert "chaos_pause" in r["transition_evidence"]["evaluated_order"]


# ==================================================================
# 14. 优先级:event_window + active 同时 → event_window_freeze
# ==================================================================

def test_priority_event_window_beats_active(sm):
    state = _base_state(
        event_risk_level="high", event_hours_ahead=8,
        nearest_event_name="CPI",
        l2_stance="bullish", l3_grade="A", l3_permission="can_open",
        l4_cap=0.1,
    )
    r = sm.determine_state(state)
    assert r["current_state"] == "event_window_freeze"


# ==================================================================
# 15. 集成:StrategyStateBuilder 两次连跑 → previous_state 链式
# ==================================================================

def test_integration_previous_state_chained(conn):
    # 写一些 K 线,让 builder 能跑
    rows = []
    base = datetime(2024, 5, 1, tzinfo=timezone.utc)
    for tf, step_sec in (("1d", 86400), ("4h", 14400),
                        ("1h", 3600), ("1w", 7 * 86400)):
        for i in range(100):
            ts = (base + timedelta(seconds=step_sec * i)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            rows.append(KlineRow(
                timeframe=tf, timestamp=ts,
                open=50000 + i, high=50100 + i, low=49900 + i,
                close=50000 + i, volume_btc=1.0,
            ))
    BTCKlinesDAO.upsert_klines(conn, rows)
    conn.commit()

    def _ai_ok(evid, openai_client=None, **kw):
        return {
            "summary_text": "ok", "model_used": "m", "tokens_in": 10,
            "tokens_out": 5, "latency_ms": 1, "status": "success",
            "error": None,
        }

    builder = StrategyStateBuilder(conn, ai_caller=_ai_ok)
    r1 = builder.run(run_trigger="manual")
    sm_block_1 = r1.state["state_machine"]
    assert r1.persisted is True
    first_state = sm_block_1["current_state"]
    assert first_state is not None

    # 第二次跑:previous_state 应等于第一次的 current_state
    r2 = builder.run(run_trigger="manual")
    sm_block_2 = r2.state["state_machine"]
    assert sm_block_2["previous_state"] == first_state


# ==================================================================
# 16. 边界:previous_record=None → previous_state=None
# ==================================================================

def test_no_previous_record(sm):
    state = _base_state(l2_stance="neutral")
    r = sm.determine_state(state, previous_record=None)
    assert r["previous_state"] is None
    assert r["stable_in_state"] is False


# ==================================================================
# 17. 边界:顶层 shortcut 风格(layer_1 直接在顶层)也能工作
# ==================================================================

def test_top_level_shortcut_shape(sm):
    """不用 evidence_reports,直接 state['layer_1'] = {...}。"""
    state = {
        "reference_timestamp_utc": "2024-05-10T12:00:00Z",
        "cold_start": {"warming_up": False, "runs_completed": 100,
                       "threshold": 42},
        "layer_1": {"regime": "chaos", "volatility_regime": "extreme"},
        "layer_2": {"stance": "neutral"},
        "layer_3": {"grade": "none", "execution_permission": "watch"},
        "layer_4": {"position_cap": 0.0},
        "layer_5": {"macro_environment": "neutral",
                    "macro_headwind_vs_btc": "neutral",
                    "btc_nasdaq_correlation": 0.1},
        "composite_factors": {"event_risk": {"band": "low"}},
        "pipeline_meta": {"failures": [], "degraded_stages": []},
    }
    r = sm.determine_state(state)
    assert r["current_state"] == "chaos_pause"


# ==================================================================
# 18. stable_in_state(连续两次同状态)
# ==================================================================

def test_stable_in_state(sm):
    state = _base_state(l2_stance="neutral")  # neutral_observation
    prev = {
        "run_timestamp_utc": "2024-05-10T11:50:00Z",
        "state": {
            "state_machine": {
                "current_state": "neutral_observation",
                "state_entered_at_utc": "2024-05-10T10:00:00Z",
            },
        },
    }
    r = sm.determine_state(state, previous_record=prev)
    assert r["current_state"] == "neutral_observation"
    assert r["stable_in_state"] is True
    # state_entered_at_utc 应该沿用之前的进入时间
    assert r["state_entered_at_utc"] == "2024-05-10T10:00:00Z"
    # minutes_since_previous_transition ≈ 10(11:50 → 12:00)
    assert r["minutes_since_previous_transition"] == pytest.approx(10.0)


# ==================================================================
# 19. DSL:各 operator 单元验证
# ==================================================================

def test_dsl_operators():
    from src.pipeline.state_machine import _eval_single
    assert _eval_single(5, "gt", 3) is True
    assert _eval_single(3, "gt", 3) is False
    assert _eval_single(3, "gte", 3) is True
    assert _eval_single(2, "lt", 3) is True
    assert _eval_single(3, "lte", 3) is True
    assert _eval_single("A", "in", ["A", "B"]) is True
    assert _eval_single("C", "in", ["A", "B"]) is False
    assert _eval_single(True, "eq", True) is True
    # None → False for numeric ops
    assert _eval_single(None, "gt", 1) is False
    # None == None for eq
    assert _eval_single(None, "eq", None) is True


# ==================================================================
# 20. 缺失字段保守为 False(不会误入 active)
# ==================================================================

def test_missing_fields_are_false(sm):
    """L2 output 缺 → active_long 不应触发。"""
    state = {
        "reference_timestamp_utc": "2024-05-10T12:00:00Z",
        "cold_start": {"warming_up": False, "runs_completed": 100,
                       "threshold": 42},
        "evidence_reports": {},  # 全空
        "composite_factors": {},
        "pipeline_meta": {"failures": [], "degraded_stages": []},
    }
    r = sm.determine_state(state)
    assert r["current_state"] == "neutral_observation"
