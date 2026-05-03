"""tests/ai/test_orchestrator_retry.py — Sprint 1.10-F commit 4 集成测试。

覆盖 orchestrator 改造 + 1.10-D Master fallback 真接通 + L5 macro fallback。

场景:
1. L5 失败 → CircuitBreaker.apply_macro_fallback 替换 l5 输出,master 仍跑
2. Master 失败(无 active_thesis)→ thesis_aware_fallback mode=silent_cooldown
3. Master 失败(有 active_thesis)→ thesis_aware_fallback mode=evaluate_existing
4. retry_log 字段:L5 失败 → macro_fallback_applied=True
5. retry_log 字段:Master 失败 → thesis_aware_fallback_applied=True
6. retry_log 写入 DB:via StrategyStateDAO.insert_state → strategy_runs.retry_log_json
7. 5 层全成功 → retry_log 不写入(None)
8. L5 + Master 同时失败 → 两个 fallback 同时记录到 retry_log
9. macro fallback 字段完整性:macro_stance / headwind_score / cap_multiplier 等
10. thesis_aware_fallback 状态:有 thesis → keep_thesis,无 thesis → silent
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from src.ai.orchestrator import AIOrchestrator
from src.data.storage.dao import StrategyStateDAO


# ============================================================
# Helpers(部分复用 test_orchestrator.py 模式)
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


def _ok_l1() -> dict[str, Any]:
    return {"regime": "trend_up", "confidence": 0.85}


def _ok_l2() -> dict[str, Any]:
    return {
        "stance": "bullish", "phase": "early",
        "stance_confidence_tier": "high", "confidence": 0.85,
    }


def _ok_l3() -> dict[str, Any]:
    return {"opportunity_grade": "B", "confidence": 0.80}


def _ok_l4() -> dict[str, Any]:
    return {
        "risk_tier": "moderate",
        "hard_invalidation_levels": [
            {"price": 73000, "type": "swing_low",
             "distance_from_current_pct": -3.7},
        ],
        "risk_breakdown": {"crowding_risk": 30},
        "confidence": 0.85,
    }


def _ok_l5() -> dict[str, Any]:
    return {
        "macro_stance": "supportive", "extreme_event_detected": False,
        "position_cap_macro_multiplier": 1.0, "confidence": 0.80,
    }


def _ok_master() -> dict[str, Any]:
    """完整 mode=new_thesis 输出,Validator 全 24 条都通过(无 needs_retry)。"""
    return {
        "mode": "new_thesis",
        "new_thesis": {
            "thesis_id": "t_test_001",
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
        "state_transition": {
            "from_state": "FLAT", "to_state": "LONG_PLANNED",
            "transition_reasoning": "...",
        },
        "trade_plan": {
            "action": "open", "direction": "long",
            "stop_loss": 73000, "position_size_pct": 0.40,
        },
        "position_cap_final": {
            "value": 0.4409,
            "composition": {"base": 0.70, "raw_product": 0.4409},
        },
        "counter_arguments": ["..."],
        "narrative": "层间一致,做多",
        "one_line_summary": "做多",
        "evidence_ref": ["l2_bullish"],
        "confidence": 0.80,
        "data_completeness_pct": 100,
    }


def _make_agent(out: dict[str, Any], raise_exc: bool = False) -> Any:
    a = MagicMock()
    out_with_status = {**out}
    out_with_status.setdefault("status", "success")
    if raise_exc:
        a.analyze.side_effect = RuntimeError("simulated AI failure")
    else:
        a.analyze.return_value = out_with_status
    a._fallback_output.return_value = {**out, "status": "degraded"}
    return a


def _build_context(
    current_state: str = "FLAT",
    active_thesis: Any = None,
) -> dict[str, Any]:
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
        "l3": {"risk_preview": {"events_count_72h": 0},
               "current_state": current_state, "previous_l3": None},
        "l4": {"computed_indicators": {"current_close": 75749},
               "current_state": current_state, "previous_l4": None},
        "l5": {"computed_macro_indicators": {},
               "events_calendar_72h": [],
               "extreme_event_flags": extreme_flags,
               "previous_l5": None},
        "master": {
            "current_state": current_state,
            "previous_strategy_run": None,
            "active_thesis": active_thesis,
        },
    }


# ============================================================
# 1. L5 失败 → macro fallback 接通(D4=a)
# ============================================================


def test_l5_failure_triggers_macro_fallback():
    """L5 抛异常 → orchestrator 用 CircuitBreaker.apply_macro_fallback() 替换 l5 输出。"""
    agents = {
        "l1": _make_agent(_ok_l1()),
        "l2": _make_agent(_ok_l2()),
        "l3": _make_agent(_ok_l3()),
        "l4": _make_agent(_ok_l4()),
        "l5": _make_agent(_ok_l5(), raise_exc=True),
        "master": _make_agent(_ok_master()),
    }
    orch = AIOrchestrator(agents=agents)
    result = orch.run_full_a(_build_context())

    l5_out = result["layers"]["l5"]
    # 硬编码 macro fallback 关键字段
    assert l5_out["macro_stance"] == "risk_neutral"
    assert l5_out["headwind_score"] == 0
    assert l5_out["extreme_event_detected"] is False
    assert l5_out["position_cap_macro_multiplier"] == 1.0
    # status 标记为降级
    assert "degraded" in l5_out["status"].lower() \
        or "macro_fallback" in l5_out["status"].lower()


def test_l5_failure_does_not_short_circuit_master():
    """L5 失败但 master 仍跑(§6.4.2 D4=a)。"""
    agents = {
        "l1": _make_agent(_ok_l1()),
        "l2": _make_agent(_ok_l2()),
        "l3": _make_agent(_ok_l3()),
        "l4": _make_agent(_ok_l4()),
        "l5": _make_agent(_ok_l5(), raise_exc=True),
        "master": _make_agent(_ok_master()),
    }
    orch = AIOrchestrator(agents=agents)
    result = orch.run_full_a(_build_context())

    # master 仍出 trade_plan
    assert "master" in result["layers"]
    master = result["layers"]["master"]
    # 经过 validator 后可能被改写,但至少有 trade_plan
    assert "trade_plan" in master or "mode" in master


def test_l5_failure_marks_retry_log_macro_fallback():
    """L5 失败 → retry_log.macro_fallback_applied = True。"""
    agents = {
        "l1": _make_agent(_ok_l1()),
        "l2": _make_agent(_ok_l2()),
        "l3": _make_agent(_ok_l3()),
        "l4": _make_agent(_ok_l4()),
        "l5": _make_agent(_ok_l5(), raise_exc=True),
        "master": _make_agent(_ok_master()),
    }
    orch = AIOrchestrator(agents=agents)
    result = orch.run_full_a(_build_context())

    assert "retry_log" in result
    rl = result["retry_log"]
    assert rl.get("macro_fallback_applied") is True
    assert "l5_failed" in rl.get("macro_fallback_reason", "").lower()


# ============================================================
# 2. Master 失败 + 无 active_thesis → silent_cooldown
# ============================================================


def test_master_failure_no_thesis_silent_cooldown():
    """Master 抛异常 + 无 active_thesis → thesis_aware_fallback mode=silent_cooldown。"""
    agents = {
        "l1": _make_agent(_ok_l1()),
        "l2": _make_agent(_ok_l2()),
        "l3": _make_agent(_ok_l3()),
        "l4": _make_agent(_ok_l4()),
        "l5": _make_agent(_ok_l5()),
        "master": _make_agent(_ok_master(), raise_exc=True),
    }
    orch = AIOrchestrator(agents=agents)
    result = orch.run_full_a(_build_context(active_thesis=None))

    # 注:result["layers"]["master"] 可能被 validator 改写;
    # 但 retry_log 里应有 silent 标记
    rl = result.get("retry_log") or {}
    assert rl.get("thesis_aware_fallback_applied") is True
    assert "silent" in rl.get("thesis_aware_fallback_reason", "").lower()


def test_master_failure_with_thesis_keep_thesis():
    """Master 抛异常 + 有 active_thesis → thesis_aware_fallback mode=evaluate_existing。"""
    active_thesis = {
        "thesis_id": "t_test_001",
        "direction": "long",
        "core_judgment": "...",
        "break_conditions": [
            {"description": "...", "metric": "btc_close",
             "operator": "<", "threshold": 70000, "evaluation_window": "1d_close"},
            {"description": "...", "metric": "btc_close",
             "operator": "<", "threshold": 68000, "evaluation_window": "1d_close"},
            {"description": "...", "metric": "btc_close",
             "operator": "<", "threshold": 65000, "evaluation_window": "1d_close"},
        ],
        "is_60d_capped": False,
    }
    agents = {
        "l1": _make_agent(_ok_l1()),
        "l2": _make_agent(_ok_l2()),
        "l3": _make_agent(_ok_l3()),
        "l4": _make_agent(_ok_l4()),
        "l5": _make_agent(_ok_l5()),
        "master": _make_agent(_ok_master(), raise_exc=True),
    }
    orch = AIOrchestrator(agents=agents)
    result = orch.run_full_a(_build_context(active_thesis=active_thesis))

    rl = result.get("retry_log") or {}
    assert rl.get("thesis_aware_fallback_applied") is True
    assert "keep_thesis" in rl.get("thesis_aware_fallback_reason", "").lower()


# ============================================================
# 3. retry_log 写入 DB(via StrategyStateDAO.insert_state)
# ============================================================


@pytest.fixture
def in_memory_db():
    """内存 DB + schema.sql 建表。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    schema_path = "src/data/storage/schema.sql"
    with open(schema_path, encoding="utf-8") as f:
        conn.executescript(f.read())
    yield conn
    conn.close()


def test_retry_log_persisted_to_strategy_runs(in_memory_db):
    """retry_log 字段经 DAO 写入 strategy_runs.retry_log_json,JSON 可还原。"""
    state = {
        "generated_at_utc": "2026-05-01T16:00:00Z",
        "generated_at_bjt": "2026-05-02T00:00:00+08:00",
        "retry_log": {
            "macro_fallback_applied": True,
            "macro_fallback_reason": "l5_failed_apply_hardcoded_macro_d4_a",
            "thesis_aware_fallback_applied": True,
            "thesis_aware_fallback_reason": "master_failed_keep_thesis",
            "layers_status": {
                "l1": "success", "l2": "success", "l3": "success",
                "l4": "success", "l5": "fallback", "master": "fallback",
            },
            "failed_layers": ["l5", "master"],
        },
        "state_machine": {"current_state": "LONG_HOLD", "stable_in_state": True},
        "ai_layers": {"l2": {"stance": "bullish"}},
        "market_snapshot": {"btc_price_usd": 75749},
        "observation": {"observation_category": "trend_up"},
    }
    StrategyStateDAO.insert_state(
        in_memory_db,
        run_timestamp_utc="2026-05-01T16:00:00Z",
        run_id="test_retry_001",
        run_trigger="manual_test",
        rules_version="v1.4",
        ai_model_actual="claude-opus-4-7",
        state=state,
    )
    in_memory_db.commit()

    row = in_memory_db.execute(
        "SELECT retry_log_json FROM strategy_runs WHERE run_id = ?",
        ("test_retry_001",),
    ).fetchone()
    assert row is not None
    assert row["retry_log_json"] is not None
    parsed = json.loads(row["retry_log_json"])
    assert parsed["macro_fallback_applied"] is True
    assert parsed["thesis_aware_fallback_applied"] is True
    assert parsed["failed_layers"] == ["l5", "master"]


def test_retry_log_absent_when_no_failure(in_memory_db):
    """所有层成功 → state["retry_log"] 不存在 → DB 写 NULL。"""
    state = {
        "generated_at_utc": "2026-05-01T16:00:00Z",
        "generated_at_bjt": "2026-05-02T00:00:00+08:00",
        # 注:无 retry_log 字段
        "state_machine": {"current_state": "FLAT", "stable_in_state": True},
        "ai_layers": {},
        "market_snapshot": {"btc_price_usd": 75749},
        "observation": {"observation_category": "neutral"},
    }
    StrategyStateDAO.insert_state(
        in_memory_db,
        run_timestamp_utc="2026-05-01T16:00:00Z",
        run_id="test_no_retry_001",
        run_trigger="manual_test",
        rules_version="v1.4",
        ai_model_actual="claude-opus-4-7",
        state=state,
    )
    in_memory_db.commit()

    row = in_memory_db.execute(
        "SELECT retry_log_json FROM strategy_runs WHERE run_id = ?",
        ("test_no_retry_001",),
    ).fetchone()
    assert row is not None
    assert row["retry_log_json"] is None


# ============================================================
# 4. L5 + Master 同时失败 → 两个 fallback 同时记录
# ============================================================


def test_l5_and_master_both_fail_records_both_fallbacks():
    """L5 失败 → macro fallback;Master 也失败 → thesis fallback。retry_log 含两条。"""
    agents = {
        "l1": _make_agent(_ok_l1()),
        "l2": _make_agent(_ok_l2()),
        "l3": _make_agent(_ok_l3()),
        "l4": _make_agent(_ok_l4()),
        "l5": _make_agent(_ok_l5(), raise_exc=True),
        "master": _make_agent(_ok_master(), raise_exc=True),
    }
    orch = AIOrchestrator(agents=agents)
    result = orch.run_full_a(_build_context(active_thesis=None))

    rl = result.get("retry_log") or {}
    assert rl.get("macro_fallback_applied") is True
    assert rl.get("thesis_aware_fallback_applied") is True


# ============================================================
# 5. happy path:全成功 → retry_log 不存在
# ============================================================


def test_happy_path_no_retry_log():
    """5 层 + master 全成功 → result 中无 retry_log 字段(或为空)。"""
    agents = {
        "l1": _make_agent(_ok_l1()),
        "l2": _make_agent(_ok_l2()),
        "l3": _make_agent(_ok_l3()),
        "l4": _make_agent(_ok_l4()),
        "l5": _make_agent(_ok_l5()),
        "master": _make_agent(_ok_master()),
    }
    orch = AIOrchestrator(agents=agents)
    result = orch.run_full_a(_build_context())

    rl = result.get("retry_log")
    assert not rl  # None 或 空 dict 都接受
