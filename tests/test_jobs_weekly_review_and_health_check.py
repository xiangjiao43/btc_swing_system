"""tests/test_jobs_weekly_review_and_health_check.py — Sprint 1.10-H commit 5 单测。

覆盖:
- scheduler.yaml 加 weekly_review cron,_JOB_FUNCTIONS 注册
- job_position_health_check 接通真 AI(D2=a 复用 EmergencySimplifiedA)
- job_weekly_review:input_builder + analyst + UPSERT weekly_reviews + 写 alerts
- EmergencySimplifiedA._build_user_prompt 含 trigger 字段(D2=a)
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.ai.agents.emergency_simplified_a import EmergencySimplifiedA
from src.ai.weekly_review_input_builder import VALIDATOR_KEYS
from src.scheduler import jobs as jobs_module
from src.scheduler.jobs import (
    _JOB_FUNCTIONS,
    _state_from_thesis,
    job_position_health_check,
    job_weekly_review,
)


# ============================================================
# 1. _JOB_FUNCTIONS 注册
# ============================================================

def test_weekly_review_registered():
    """Sprint H Part A:生产 yaml 'weekly_review' 现走 retry wrapper。
    job_weekly_review 通过新 key 'weekly_review_no_retry' 仍可单测直调。"""
    from src.scheduler.jobs import job_weekly_review_with_retry
    assert "weekly_review" in _JOB_FUNCTIONS
    assert _JOB_FUNCTIONS["weekly_review"] is job_weekly_review_with_retry
    assert _JOB_FUNCTIONS["weekly_review_no_retry"] is job_weekly_review


# ============================================================
# 2. EmergencySimplifiedA._build_user_prompt 含 trigger(D2=a)
# ============================================================

def test_prompt_includes_trigger_health_check():
    agent = EmergencySimplifiedA()
    prompt = agent._build_user_prompt({
        "trigger": "health_check",
        "current_strategy_state": "LONG_HOLD",
        "triggered_at_price": 75000.0,
        "baseline_price": 75000.0,
        "pct_change": 0.0,
        "key_factors": {},
        "active_thesis": {"direction": "long", "lifecycle_stage": "open"},
    })
    assert "trigger 类型:health_check" in prompt


def test_prompt_default_trigger_event_price():
    """无 trigger 字段 → 默认 'event_price'(向后兼容 1.10-G)。"""
    agent = EmergencySimplifiedA()
    prompt = agent._build_user_prompt({
        "current_strategy_state": "FLAT",
        "triggered_at_price": 75000.0,
        "baseline_price": 75000.0,
        "pct_change": 0.0,
        "key_factors": {},
        "active_thesis": None,
    })
    assert "trigger 类型:event_price" in prompt


def test_prompt_file_includes_trigger_doc():
    """system prompt 文件也提到 trigger 字段 + health_check 特别说明。"""
    from pathlib import Path
    p = (
        Path(__file__).resolve().parent.parent
        / "src" / "ai" / "agents" / "prompts"
        / "emergency_simplified_a.txt"
    )
    txt = p.read_text(encoding="utf-8")
    assert "trigger" in txt
    assert "health_check" in txt
    assert "event_price" in txt


# ============================================================
# 3. _state_from_thesis 推导
# ============================================================

@pytest.mark.parametrize("direction,stage,expected", [
    ("long", "planned", "LONG_PLANNED"),
    ("long", "opened", "LONG_OPEN"),
    ("long", "holding", "LONG_HOLD"),
    ("long", "trim", "LONG_TRIM"),
    ("short", "opened", "SHORT_OPEN"),
    ("short", "holding", "SHORT_HOLD"),
    ("short", "closed", "FLAT"),
    ("LONG", "HOLDING", "LONG_HOLD"),
    (None, "planned", "FLAT"),
    ("invalid", "planned", "FLAT"),
])
def test_state_from_thesis(direction, stage, expected):
    assert _state_from_thesis({
        "direction": direction, "lifecycle_stage": stage,
    }) == expected


# ============================================================
# 4. job_position_health_check — 真 AI 接通(D2=a)
# ============================================================

@pytest.fixture
def conn_factory(tmp_path):
    """文件 DB(_wrap_job 关闭 conn 后,测试还需查表 — 用文件 DB 重新连)。

    第一次调用 factory() 时初始化 schema + migration;
    后续调用复用同一文件 → _wrap_job 关闭后,测试可重新 sqlite3.connect 查。
    """
    db_path = tmp_path / "test_weekly_review.db"
    initialized = {"flag": False}

    def factory():
        c = sqlite3.connect(str(db_path))
        c.row_factory = sqlite3.Row
        if not initialized["flag"]:
            with open("src/data/storage/schema.sql", encoding="utf-8") as f:
                c.executescript(f.read())
            from scripts.init_v14_tables import apply_migration
            apply_migration(c)
            c.commit()
            initialized["flag"] = True
        return c

    factory.db_path = db_path  # 测试用此读
    yield factory


def _query_conn(factory):
    """打开一个独立 conn 给测试查表用(_wrap_job 关闭工作 conn 后)。"""
    c = sqlite3.connect(str(factory.db_path))
    c.row_factory = sqlite3.Row
    return c


def _seed_thesis_kline_and_run(conn):
    """为 health_check 测试准备:1 active thesis + 1 strategy_run + 1 1h K 线。"""
    from src.strategy import thesis_manager
    spec = {
        "direction": "long", "core_logic": "test", "confidence_score": 70,
        "break_conditions": ["a", "b", "c"],
        "entry_orders": [{"price": 75000.0, "size_pct": 0.30, "size_usdt": 30000.0}],
        "stop_loss_orders": [{"price": 72000.0, "size_pct": 0.30, "size_usdt": 30000.0}],
        "take_profit_orders": [],
    }
    thesis_manager.create_thesis(
        conn, thesis_spec=spec,
        run_id="r_hc_test", now_utc="2026-05-10T12:00:00Z",
        expires_at_utc="2026-05-17T12:00:00Z", thesis_id="t_hc_001",
    )
    conn.execute(
        "INSERT INTO strategy_runs (run_id, generated_at_utc, generated_at_bjt, "
        "reference_timestamp_utc, action_state, run_trigger, btc_price_usd, "
        "full_state_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("r_hc_test", "2026-05-10T08:00:00Z", "2026-05-10T16:00:00+08:00",
         "2026-05-10T08:00:00Z", "LONG_HOLD", "scheduled", 75000.0, "{}"),
    )
    conn.execute(
        "INSERT INTO price_candles (symbol, timeframe, open_time_utc, "
        "open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("BTCUSDT", "1h", "2026-05-10T11:00:00Z",
         75500, 75800, 75200, 75600, 1000),
    )
    conn.commit()


def test_health_check_no_active_thesis_skipped(conn_factory):
    """无 active thesis → 直接返(节约 AI 成本)。"""
    # init schema(triggers initialized flag)
    conn_factory().close()
    result = job_position_health_check(conn_factory=conn_factory)
    body = result.get("by_collector") or {}
    assert body.get("position_health_check") == "no_active_thesis"


def test_health_check_calls_emergency_simplified_a_with_trigger_health_check(conn_factory):
    """有 active thesis → 调 EmergencySimplifiedA(trigger='health_check')。"""
    seed_conn = conn_factory()
    _seed_thesis_kline_and_run(seed_conn)
    seed_conn.close()

    captured_ctx = {}

    def fake_analyze(self, ctx, *, client=None):
        captured_ctx.update(ctx)
        return {
            "agent": "emergency_simplified_a",
            "status": "success",
            "thesis_still_valid": True,
            "immediate_action": "maintain",
            "reasoning": "health_check ok",
        }

    with patch.object(EmergencySimplifiedA, "analyze", fake_analyze):
        result = job_position_health_check(conn_factory=conn_factory)

    # ctx 必须含 trigger='health_check'(D2=a 关键)
    assert captured_ctx.get("trigger") == "health_check"
    assert captured_ctx.get("active_thesis") is not None
    assert captured_ctx["active_thesis"]["thesis_id"] == "t_hc_001"
    body = result.get("by_collector") or {}
    assert body.get("position_health_check") == "ai_evaluated"
    assert body.get("immediate_action") == "maintain"


def test_health_check_writes_alert(conn_factory):
    """health_check 完成 → alerts 表写一行(severity 由 immediate_action 决定)。"""
    seed_conn = conn_factory()
    _seed_thesis_kline_and_run(seed_conn)
    seed_conn.close()

    def fake_analyze(self, ctx, *, client=None):
        return {
            "agent": "emergency_simplified_a", "status": "success",
            "thesis_still_valid": True,
            "immediate_action": "maintain", "reasoning": "ok",
        }

    with patch.object(EmergencySimplifiedA, "analyze", fake_analyze):
        job_position_health_check(conn_factory=conn_factory)

    q = _query_conn(conn_factory)
    try:
        rows = q.execute(
            "SELECT alert_type, severity FROM alerts "
            "WHERE alert_type = 'position_health_check'"
        ).fetchall()
    finally:
        q.close()
    assert len(rows) == 1
    assert rows[0]["severity"] == "info"  # maintain → info


def test_health_check_emergency_exit_writes_critical_alert(conn_factory):
    seed_conn = conn_factory()
    _seed_thesis_kline_and_run(seed_conn)
    seed_conn.close()

    def fake_analyze(self, ctx, *, client=None):
        return {
            "agent": "emergency_simplified_a", "status": "success",
            "thesis_still_valid": False,
            "immediate_action": "emergency_exit",
            "reasoning": "thesis broken",
        }

    with patch.object(EmergencySimplifiedA, "analyze", fake_analyze):
        result = job_position_health_check(conn_factory=conn_factory)

    q = _query_conn(conn_factory)
    try:
        rows = q.execute(
            "SELECT severity FROM alerts WHERE alert_type='position_health_check'",
        ).fetchall()
    finally:
        q.close()
    assert rows[0]["severity"] == "critical"
    assert "position_health_check_critical" in result["events_triggered"]


def test_health_check_no_baseline_skipped(conn_factory):
    """有 active thesis 但无 strategy_run baseline → skipped_no_price_data。"""
    seed_conn = conn_factory()
    from src.strategy import thesis_manager
    spec = {
        "direction": "long", "core_logic": "test", "confidence_score": 70,
        "break_conditions": ["a", "b", "c"],
        "entry_orders": [{"price": 75000.0, "size_pct": 0.30, "size_usdt": 30000.0}],
        "stop_loss_orders": [],
        "take_profit_orders": [],
    }
    thesis_manager.create_thesis(
        seed_conn, thesis_spec=spec,
        run_id="r", now_utc="2026-05-10T12:00:00Z",
        expires_at_utc="2026-05-17T12:00:00Z", thesis_id="t_no_base",
    )
    seed_conn.commit()
    seed_conn.close()

    result = job_position_health_check(conn_factory=conn_factory)
    body = result.get("by_collector") or {}
    assert body.get("position_health_check") == "skipped_no_price_data"


# ============================================================
# 5. job_weekly_review — 端到端
# ============================================================

def _make_full_review_output():
    v_review = {
        k: {"activations": 1, "rate": "1/7 days", "evaluation": "适中"}
        for k in VALIDATOR_KEYS
    }
    return {
        "performance_summary": {
            "total_runs": 7, "successful_runs": 5, "ai_failures": 2,
            "thesis_created": 0, "thesis_closed_profit": 0,
            "thesis_closed_loss": 0,
            "weekly_pnl_pct": 0.5, "max_drawdown_pct": -1.2,
        },
        "system_health_diagnosis": [],
        "strategy_quality": {
            "thesis_quality": "acceptable",
            "break_conditions_calibration": "适中",
            "false_signals": [], "missed_opportunities": [],
            "ai_vs_actual_comparison": [],
        },
        "hard_constraint_activation_review": {
            **v_review,
            "position_cap_compressed_avg": None,
            "thesis_lock_blocks_count": 0,
            "channel_c_uses_count": 0,
            "review_pending_triggers": 0,
            "overall_evaluation": "ok",
            "suggested_actions": [],
        },
        "adjustment_recommendations": [
            {"目标": "x", "建议": "y", "优先级": "low", "影响": "z"},
        ],
    }


def test_weekly_review_writes_to_weekly_reviews_table(conn_factory):
    """job_weekly_review 调 input_builder + agent → UPSERT weekly_reviews。"""
    conn_factory().close()  # init schema

    from src.ai.agents.weekly_review_analyst import WeeklyReviewAnalyst

    def fake_analyze(self, ctx, *, client=None):
        return {**_make_full_review_output(), "status": "success"}

    with patch.object(WeeklyReviewAnalyst, "analyze", fake_analyze):
        result = job_weekly_review(conn_factory=conn_factory)

    body = result.get("by_collector") or {}
    assert body.get("weekly_review") == "completed"

    q = _query_conn(conn_factory)
    try:
        row = q.execute("SELECT * FROM weekly_reviews LIMIT 1").fetchone()
    finally:
        q.close()
    assert row is not None
    assert row["critical_count"] == 0
    parsed = json.loads(row["output_json"])
    assert "performance_summary" in parsed


def test_weekly_review_high_priority_does_not_write_critical_alert(conn_factory):
    """priority='high' 只代表优先处理,不等于 critical alert。"""
    conn_factory().close()
    payload = _make_full_review_output()
    payload["adjustment_recommendations"].append({
        "目标": "high1", "建议": "h", "优先级": "high", "影响": "x",
    })

    from src.ai.agents.weekly_review_analyst import WeeklyReviewAnalyst

    def fake_analyze(self, ctx, *, client=None):
        return {**payload, "status": "success"}

    with patch.object(WeeklyReviewAnalyst, "analyze", fake_analyze):
        result = job_weekly_review(conn_factory=conn_factory)

    body = result.get("by_collector") or {}
    assert body.get("critical_count") == 0
    assert body.get("high_priority_count") == 1

    q = _query_conn(conn_factory)
    try:
        rows = q.execute(
            "SELECT alert_type, severity FROM alerts "
            "WHERE alert_type LIKE 'weekly_review%'"
        ).fetchall()
    finally:
        q.close()
    assert len(rows) == 1
    assert rows[0]["alert_type"] == "weekly_review"
    assert rows[0]["severity"] == "warning"


def test_weekly_review_explicit_critical_writes_critical_alert(conn_factory):
    """只有 explicit severity='critical' 才写 critical alert。"""
    conn_factory().close()
    payload = _make_full_review_output()
    payload["adjustment_recommendations"].append({
        "目标": "critical1",
        "具体调整路径": "x",
        "优先级": "medium",
        "severity": "critical",
        "影响": "y",
    })

    from src.ai.agents.weekly_review_analyst import WeeklyReviewAnalyst

    def fake_analyze(self, ctx, *, client=None):
        return {**payload, "status": "success"}

    with patch.object(WeeklyReviewAnalyst, "analyze", fake_analyze):
        result = job_weekly_review(conn_factory=conn_factory)

    body = result.get("by_collector") or {}
    assert body.get("critical_count") == 1

    q = _query_conn(conn_factory)
    try:
        rows = q.execute(
            "SELECT alert_type, severity FROM alerts "
            "WHERE alert_type LIKE 'weekly_review%'"
        ).fetchall()
    finally:
        q.close()
    assert len(rows) == 1
    assert rows[0]["alert_type"] == "weekly_review_critical_recommendation"
    assert rows[0]["severity"] == "critical"


def test_weekly_review_upsert_idempotent(conn_factory):
    """同周触发 2 次 → UPSERT 覆盖,只有 1 行(week_start_utc PK)。"""
    conn_factory().close()
    from src.ai.agents.weekly_review_analyst import WeeklyReviewAnalyst

    def fake_analyze(self, ctx, *, client=None):
        return {**_make_full_review_output(), "status": "success"}

    with patch.object(WeeklyReviewAnalyst, "analyze", fake_analyze):
        job_weekly_review(conn_factory=conn_factory)
        job_weekly_review(conn_factory=conn_factory)

    q = _query_conn(conn_factory)
    try:
        cnt = q.execute("SELECT COUNT(*) FROM weekly_reviews").fetchone()[0]
    finally:
        q.close()
    assert cnt == 1


def test_weekly_review_ai_failure_still_writes_fallback(conn_factory):
    """AI 抛异常 → fallback 5 段 + 仍写 weekly_reviews,但 high 不自动 critical。"""
    conn_factory().close()
    from src.ai.agents.weekly_review_analyst import WeeklyReviewAnalyst

    def raise_(self, ctx, *, client=None):
        raise RuntimeError("simulated")

    with patch.object(WeeklyReviewAnalyst, "analyze", raise_):
        result = job_weekly_review(conn_factory=conn_factory)

    body = result.get("by_collector") or {}
    assert body.get("weekly_review") == "completed"

    q = _query_conn(conn_factory)
    try:
        row = q.execute("SELECT critical_count FROM weekly_reviews LIMIT 1").fetchone()
    finally:
        q.close()
    assert row is not None
    assert row["critical_count"] == 0
