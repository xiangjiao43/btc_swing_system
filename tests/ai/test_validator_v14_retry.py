"""tests/ai/test_validator_v14_retry.py — Sprint 1.10-F commit 5 集成测试。

覆盖 V8/V9/V11/V21/V22 retry 集成:
- V8/V9/V11 失败 → activations.validator_<n>_needs_retry = True
- V21 失败 → needs_retry + validator_21_retry_hint 文本
- V22 SQL 滑动 72h → count_master_failures_in_window
- collect_meta_activations 聚合 needs_retry 决策 + retry_hints
- orchestrator post-validate retry hook(V21 silent → 重试 → new_thesis 成功)
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from src.ai.orchestrator import AIOrchestrator
from src.ai.validator import (
    count_master_failures_in_window,
    validate_master_output,
    validator_8_break_objectivity,
    validator_9_break_distance,
    validator_11_direction_lock,
    validator_21_soft_resistance,
    validator_22_3day_fail,
)


# ============================================================
# 1. V8 / V9 / V11 / V21 needs_retry 单元测试
# ============================================================


def test_v8_breaks_lt_3_sets_needs_retry():
    """V8:break_conditions < 3 → needs_retry=True。"""
    out = {
        "mode": "new_thesis",
        "new_thesis": {
            "break_conditions": [
                "BTC 1d close < 70000",
                "BTC 1d close < 65000",
            ],
        },
    }
    _, act = validator_8_break_objectivity(out, {})
    assert act["validator_8_break_objectivity"] is True
    assert act["validator_8_needs_retry"] is True


def test_v8_subjective_break_sets_needs_retry():
    """V8:含主观词汇(很可能 / 似乎)→ needs_retry。"""
    out = {
        "mode": "new_thesis",
        "new_thesis": {
            "break_conditions": [
                "BTC 1d close < 70000",
                "市场情绪可能转空(很可能)",  # 主观
                "BTC 1d close < 65000",
            ],
        },
    }
    _, act = validator_8_break_objectivity(out, {})
    assert act["validator_8_needs_retry"] is True


def test_v8_objective_breaks_no_retry():
    """V8:3 条客观 break → 不触发 retry。"""
    out = {
        "mode": "new_thesis",
        "new_thesis": {
            "break_conditions": [
                "BTC 1d close < 70000",
                "BTC 1d close < 65000",
                "BTC 1d close < 60000",
            ],
        },
    }
    _, act = validator_8_break_objectivity(out, {})
    assert act["validator_8_break_objectivity"] is False
    assert "validator_8_needs_retry" not in act or \
        act.get("validator_8_needs_retry") is False


def test_v9_break_distance_violation_sets_needs_retry():
    """V9:break 价格距当前 > 20% → needs_retry。"""
    out = {
        "mode": "new_thesis",
        "new_thesis": {
            "break_conditions": [
                "BTC 1d close < 50000",  # 75749 → 50000 距 33%
                "BTC 1d close < 70000",
                "BTC 1d close < 73000",
            ],
        },
    }
    ctx = {"current_btc_price": 75749}
    _, act = validator_9_break_distance(out, ctx)
    assert act["validator_9_break_distance"] is True
    assert act["validator_9_needs_retry"] is True


def test_v11_direction_change_sets_needs_retry():
    """V11:active_thesis.direction=long + master narrative 含'做空' → needs_retry。"""
    out = {
        "mode": "evaluate_existing",
        "narrative": "建议反手做空,目标 65000",
        "one_line_summary": "翻空",
    }
    ctx = {
        "active_thesis": {"direction": "long", "thesis_id": "t_001"},
    }
    _, act = validator_11_direction_lock(out, ctx)
    assert act["validator_11_direction_lock"] is True
    assert act["validator_11_needs_retry"] is True


def test_v21_soft_resistance_sets_needs_retry_with_hint():
    """V21:active_thesis=None + grade=A + master mode=silent_cooldown → needs_retry + hint。"""
    out = {
        "mode": "silent_cooldown",
        "silent_reason": "等下次重评",
    }
    ctx = {
        "active_thesis": None,
        "cooldown_state": {"in_cooldown": False},
        "fuse_state": {"in_14d_fuse": False, "in_thesis_cycle_fuse": False},
        "l3_grade": "A",
    }
    _, act = validator_21_soft_resistance(out, ctx)
    assert act["validator_21_soft_resistance"] is True
    assert act["validator_21_needs_retry"] is True
    assert "V21" in act["validator_21_retry_hint"]
    assert "new_thesis" in act["validator_21_retry_hint"]


# ============================================================
# 2. collect_meta_activations 聚合测试
# ============================================================


def test_meta_activations_aggregates_needs_retry():
    """validate_master_output 聚合 V21 needs_retry 到 validator_needs_retry。"""
    out = {
        "mode": "silent_cooldown",
        "silent_reason": "等下次重评",
    }
    ctx = {
        "active_thesis": None,
        "cooldown_state": {"in_cooldown": False},
        "fuse_state": {"in_14d_fuse": False, "in_thesis_cycle_fuse": False},
        "l3_grade": "B",
    }
    _, activations = validate_master_output(out, ctx)
    assert activations["validator_needs_retry"] is True
    hints = activations.get("validator_retry_hints") or []
    assert any("V21" in h for h in hints)


def test_meta_activations_no_retry_when_no_violation():
    """无 V8/V9/V11/V21 触发 → validator_needs_retry=False。"""
    out = {
        "mode": "silent_cooldown",
        "silent_reason": "cooldown 中",
    }
    ctx = {
        "active_thesis": None,
        "cooldown_state": {"in_cooldown": True, "cooldown_remaining_hours": 5},
        "fuse_state": {"in_14d_fuse": False},
        "l3_grade": "none",
    }
    _, activations = validate_master_output(out, ctx)
    assert activations["validator_needs_retry"] is False
    assert activations.get("validator_retry_hints") == []


# ============================================================
# 3. V22 SQL 滑动 72h helper 测试
# ============================================================


@pytest.fixture
def in_memory_db_with_runs():
    """内存 DB + schema.sql 建表。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    schema_path = "src/data/storage/schema.sql"
    with open(schema_path, encoding="utf-8") as f:
        conn.executescript(f.read())
    yield conn
    conn.close()


def _insert_strategy_run(
    conn: sqlite3.Connection,
    run_id: str,
    generated_at_utc: str,
    retry_log: dict | None = None,
) -> None:
    rl_json = json.dumps(retry_log) if retry_log else None
    conn.execute(
        """
        INSERT INTO strategy_runs
            (run_id, generated_at_utc, generated_at_bjt,
             reference_timestamp_utc, action_state,
             run_trigger, full_state_json, retry_log_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (run_id, generated_at_utc, generated_at_utc,
         generated_at_utc, "FLAT", "test", "{}", rl_json),
    )


def test_v22_sql_helper_counts_master_failures_in_72h(in_memory_db_with_runs):
    """count_master_failures_in_window 正确统计 72h 内 master_fail。"""
    now = datetime(2026, 5, 1, 16, 0, 0, tzinfo=timezone.utc)
    # 4 行:3 个 72h 内 master_fail + 1 个超出窗口
    _insert_strategy_run(
        in_memory_db_with_runs, "r1",
        (now - timedelta(hours=10)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        retry_log={"thesis_aware_fallback_applied": True,
                   "thesis_aware_fallback_reason": "master_failed_silent"},
    )
    _insert_strategy_run(
        in_memory_db_with_runs, "r2",
        (now - timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        retry_log={"thesis_aware_fallback_applied": True,
                   "thesis_aware_fallback_reason": "master_failed_keep_thesis"},
    )
    _insert_strategy_run(
        in_memory_db_with_runs, "r3",
        (now - timedelta(hours=60)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        retry_log={"thesis_aware_fallback_applied": True,
                   "failed_layers": ["master"]},
    )
    _insert_strategy_run(
        in_memory_db_with_runs, "r4",
        (now - timedelta(hours=120)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        retry_log={"thesis_aware_fallback_applied": True},
    )
    in_memory_db_with_runs.commit()

    count = count_master_failures_in_window(
        in_memory_db_with_runs, window_hours=72, now_utc=now,
    )
    assert count == 3


def test_v22_sql_helper_excludes_no_retry_log(in_memory_db_with_runs):
    """retry_log_json IS NULL 不计入。"""
    now = datetime(2026, 5, 1, 16, 0, 0, tzinfo=timezone.utc)
    _insert_strategy_run(
        in_memory_db_with_runs, "ok1",
        (now - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        retry_log=None,
    )
    in_memory_db_with_runs.commit()

    count = count_master_failures_in_window(
        in_memory_db_with_runs, window_hours=72, now_utc=now,
    )
    assert count == 0


def test_v22_uses_master_failures_in_72h_when_provided():
    """V22 优先使用 context.master_failures_in_72h(orchestrator 注入)。"""
    out: dict[str, Any] = {}
    ctx = {"master_failures_in_72h": 3}
    _, act = validator_22_3day_fail(out, ctx)
    assert act["validator_22_3day_fail"] is True
    assert act["validator_22_needs_review_pending"] is True
    assert act["validator_22_failures_count"] == 3


def test_v22_below_threshold_no_review_pending():
    """V22:窗口内 < 3 次失败 → 不触发。"""
    out: dict[str, Any] = {}
    ctx = {"master_failures_in_72h": 2}
    _, act = validator_22_3day_fail(out, ctx)
    assert act["validator_22_3day_fail"] is False


# ============================================================
# 4. Orchestrator validator-triggered retry 集成
# ============================================================


def _build_mock_klines_1d(days: int = 200) -> pd.DataFrame:
    idx = pd.date_range("2025-10-01", periods=days, freq="1D", tz="UTC")
    np.random.seed(42)
    close = 70000 + np.cumsum(np.random.randn(days) * 500)
    return pd.DataFrame({
        "open": close - 100, "high": close + 200,
        "low": close - 200, "close": close,
    }, index=idx)


def _build_mock_klines_4h(days: int = 30) -> pd.DataFrame:
    bars = days * 6
    idx = pd.date_range("2026-04-01", periods=bars, freq="4h", tz="UTC")
    np.random.seed(43)
    close = 75000 + np.cumsum(np.random.randn(bars) * 200)
    return pd.DataFrame({
        "open": close - 50, "high": close + 100,
        "low": close - 100, "close": close,
    }, index=idx)


def _ctx() -> dict[str, Any]:
    klines_1d = _build_mock_klines_1d()
    extreme_flags = {
        "geopolitical_conflict_active": False,
        "major_bank_crisis_signal": False,
        "regulatory_crackdown_recent": False,
        "flash_crash_detected_24h": False,
        "stablecoin_depeg_active": False,
    }
    return {
        "_shared": {
            "klines_1d": klines_1d,
            "klines_4h": _build_mock_klines_4h(),
            "current_close": 75749,
            "events_count_72h": 0,
        },
        "l1": {"klines_1d_30d_close": klines_1d["close"].iloc[-30:].tolist(),
               "computed_indicators": {}, "previous_l1": None},
        "l2": {"klines_1d_30d_close": klines_1d["close"].iloc[-30:].tolist(),
               "computed_indicators": {}, "previous_l2": None},
        "l3": {"risk_preview": {}, "current_state": "FLAT", "previous_l3": None},
        "l4": {"computed_indicators": {}, "current_state": "FLAT",
               "previous_l4": None},
        "l5": {"computed_macro_indicators": {},
               "events_calendar_72h": [],
               "extreme_event_flags": extreme_flags,
               "previous_l5": None},
        "master": {
            "current_state": "FLAT",
            "previous_strategy_run": None,
            "active_thesis": None,
            "cooldown_state": {"in_cooldown": False},
            "fuse_state": {"in_14d_fuse": False, "in_thesis_cycle_fuse": False},
        },
    }


def _agent(out: dict[str, Any]) -> Any:
    a = MagicMock()
    out_with_status = {**out}
    out_with_status.setdefault("status", "success")
    a.analyze.return_value = out_with_status
    a._fallback_output.return_value = {**out, "status": "degraded"}
    return a


def _ok_layers() -> dict[str, Any]:
    return {
        "l1": _agent({"regime": "trend_up", "confidence": 0.85}),
        "l2": _agent({"stance": "bullish", "phase": "early",
                      "stance_confidence_tier": "high", "confidence": 0.85}),
        "l3": _agent({"opportunity_grade": "B", "confidence": 0.80}),
        "l4": _agent({"risk_tier": "moderate",
                      "hard_invalidation_levels": [
                          {"price": 73000, "type": "swing_low",
                           "distance_from_current_pct": -3.7},
                      ],
                      "risk_breakdown": {"crowding_risk": 30},
                      "confidence": 0.85}),
        "l5": _agent({"macro_stance": "supportive",
                      "extreme_event_detected": False,
                      "position_cap_macro_multiplier": 1.0,
                      "confidence": 0.80}),
    }


def test_orchestrator_v21_retry_succeeds_on_second_pass():
    """Master 第 1 次出 silent_cooldown(V21 触发)→ 第 2 次出 new_thesis(成功)。"""
    layers = _ok_layers()

    silent_out = {
        "mode": "silent_cooldown",
        "silent_reason": "保守等下次",
        "narrative": "层间齐心,但保守 silent",
        "one_line_summary": "silent cooldown",
    }
    new_thesis_out = {
        "mode": "new_thesis",
        "new_thesis": {
            "thesis_id": "t_retry_001",
            "direction": "long",
            "core_judgment": "做多 BTC",
            "confidence_score": 70,
            "break_conditions": [
                "BTC 1d close < 73000",
                "BTC 1d close < 70000",
                "BTC 1d close < 68000",
            ],
            "is_60d_capped": False,
        },
        "narrative": "层间一致,做多",
        "one_line_summary": "做多",
        "evidence_ref": ["l2_bullish", "l3_grade_b"],
        "counter_arguments": ["risk: ..."],
    }
    master_agent = MagicMock()
    master_agent.analyze.side_effect = [
        {**silent_out, "status": "success"},
        {**new_thesis_out, "status": "success"},
    ]
    master_agent._fallback_output.return_value = {**silent_out, "status": "degraded"}
    layers["master"] = master_agent

    orch = AIOrchestrator(agents=layers)
    result = orch.run_full_a(_ctx())

    rl = result.get("retry_log") or {}
    assert rl.get("validator_triggered_retry_applied") is True
    assert rl.get("validator_triggered_retry_succeeded") is True
    # 第二次的 mode=new_thesis 被接受
    assert result["layers"]["master"].get("mode") == "new_thesis"


def test_orchestrator_v21_retry_fails_keeps_first_output():
    """Master 第 1 次 + 第 2 次都 silent_cooldown → 保留第一次输出 + 标记 succeeded=False。"""
    layers = _ok_layers()
    silent_out = {
        "mode": "silent_cooldown",
        "silent_reason": "保守等下次",
        "narrative": "层间齐心,但保守 silent",
        "one_line_summary": "silent cooldown",
    }
    master_agent = MagicMock()
    master_agent.analyze.side_effect = [
        {**silent_out, "status": "success"},
        {**silent_out, "status": "success"},
    ]
    master_agent._fallback_output.return_value = {**silent_out, "status": "degraded"}
    layers["master"] = master_agent

    orch = AIOrchestrator(agents=layers)
    result = orch.run_full_a(_ctx())

    rl = result.get("retry_log") or {}
    assert rl.get("validator_triggered_retry_applied") is True
    assert rl.get("validator_triggered_retry_succeeded") is False


def test_orchestrator_no_retry_when_no_violation():
    """V8/V9/V11/V21 都不触发 → 不重试 master。"""
    layers = _ok_layers()
    new_thesis_out = {
        "mode": "new_thesis",
        "new_thesis": {
            "thesis_id": "t_001",
            "direction": "long",
            "core_judgment": "做多",
            "confidence_score": 70,
            "break_conditions": [
                "BTC 1d close < 73000",
                "BTC 1d close < 70000",
                "BTC 1d close < 68000",
            ],
            "is_60d_capped": False,
        },
        "narrative": "层间一致,做多",
        "one_line_summary": "做多",
        "evidence_ref": ["l2_bullish"],
        "counter_arguments": ["..."],
    }
    layers["master"] = _agent(new_thesis_out)

    orch = AIOrchestrator(agents=layers)
    result = orch.run_full_a(_ctx())

    # master 只调一次
    assert layers["master"].analyze.call_count == 1
    rl = result.get("retry_log") or {}
    assert "validator_triggered_retry_applied" not in rl
