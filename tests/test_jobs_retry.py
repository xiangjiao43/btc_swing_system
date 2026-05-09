"""tests/test_jobs_retry.py — Sprint 1.10-G commit 5a 单测。

覆盖 RetryPolicy 异步调度接通(D3=a)+ hard_invalidation_monitor / position_health_check
2 个新 cron job 的入口注册。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.scheduler import jobs as jobs_module
from src.scheduler.jobs import (
    _JOB_FUNCTIONS,
    _enqueue_pipeline_run,
    job_hard_invalidation_monitor,
    job_pipeline_run_with_retry,
    job_position_health_check,
)


# ============================================================
# job 注册到 _JOB_FUNCTIONS
# ============================================================

def test_new_jobs_registered():
    assert "hard_invalidation_monitor" in _JOB_FUNCTIONS
    assert "position_health_check" in _JOB_FUNCTIONS
    assert "pipeline_run_with_retry" in _JOB_FUNCTIONS
    assert _JOB_FUNCTIONS["hard_invalidation_monitor"] is job_hard_invalidation_monitor
    assert _JOB_FUNCTIONS["position_health_check"] is job_position_health_check


# ============================================================
# pipeline_run_with_retry — happy path 不重试
# ============================================================

def test_with_retry_success_no_retry():
    """job_pipeline_run 返回 status='ok' → 不调度 retry。"""
    mock_pipeline = MagicMock(return_value={"status": "ok", "ai_status": "success"})
    mock_enq = MagicMock(return_value=True)
    with patch.object(jobs_module, "job_pipeline_run", mock_pipeline), \
         patch.object(jobs_module, "_enqueue_pipeline_run", mock_enq):
        result = job_pipeline_run_with_retry(run_trigger="event_price")
    assert result["status"] == "ok"
    assert "retry_scheduled" not in result
    mock_enq.assert_not_called()


# ============================================================
# pipeline_run_with_retry — 失败触发 retry
# ============================================================

def test_with_retry_error_schedules_retry():
    """job_pipeline_run 返回 status='error' + attempt=1 → 调度 attempt=2。
    Sprint F.2:间隔 5/10/20 → 30/60/60,attempt=2 backoff = 60min = 3600s。"""
    mock_pipeline = MagicMock(return_value={
        "status": "error", "error_type": "RuntimeError", "error_message": "x",
    })
    mock_enq = MagicMock(return_value=True)
    with patch.object(jobs_module, "job_pipeline_run", mock_pipeline), \
         patch.object(jobs_module, "_enqueue_pipeline_run", mock_enq):
        result = job_pipeline_run_with_retry(
            run_trigger="event_price", attempt=1,
        )
    assert result["retry_scheduled"] is True
    assert result["retry_next_attempt"] == 2
    # backoff = 3600s(intervals_minutes[1] = 60 min,attempt=2)
    assert result["retry_next_delay_sec"] == 3600
    mock_enq.assert_called_once()
    call = mock_enq.call_args
    assert call.kwargs["attempt"] == 2
    assert call.kwargs["delay_sec"] == 3600


def test_with_retry_degraded_ai_schedules_retry():
    """ai_status='degraded_l1_failed' 也算失败 → retry。"""
    mock_pipeline = MagicMock(return_value={
        "status": "ok", "ai_status": "degraded_l1_failed",
    })
    mock_enq = MagicMock(return_value=True)
    with patch.object(jobs_module, "job_pipeline_run", mock_pipeline), \
         patch.object(jobs_module, "_enqueue_pipeline_run", mock_enq):
        result = job_pipeline_run_with_retry(
            run_trigger="scheduled", attempt=1,
        )
    assert result["retry_scheduled"] is True


def test_with_retry_attempt_3_then_fail_exhausts():
    """attempt=3 失败 → should_retry(attempt=4) 返 False → exhausted。"""
    mock_pipeline = MagicMock(return_value={"status": "error"})
    mock_enq = MagicMock()
    # 用过去 1 分钟前的 retry_start_utc(在 2h 窗口内,但 attempt+1=4 > 3 → 退出)
    start = (datetime.now(timezone.utc).replace(microsecond=0)).isoformat()
    with patch.object(jobs_module, "job_pipeline_run", mock_pipeline), \
         patch.object(jobs_module, "_enqueue_pipeline_run", mock_enq):
        result = job_pipeline_run_with_retry(
            run_trigger="event_price", attempt=3,
            retry_start_utc=start,
        )
    assert result.get("retry_exhausted") is True
    assert result["retry_attempts"] == 3
    mock_enq.assert_not_called()


def test_with_retry_outside_3h_window_exhausts():
    """retry_start_utc = 4 小时前 → is_within_window=False → exhausted。
    Sprint F.2:窗口 2h → 3h,所以用 4h 才确保越界。"""
    mock_pipeline = MagicMock(return_value={"status": "error"})
    mock_enq = MagicMock()
    # 4 小时前(超 3h 窗口)
    from datetime import timedelta
    start = (datetime.now(timezone.utc) - timedelta(hours=4)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    with patch.object(jobs_module, "job_pipeline_run", mock_pipeline), \
         patch.object(jobs_module, "_enqueue_pipeline_run", mock_enq):
        result = job_pipeline_run_with_retry(
            run_trigger="event_price", attempt=1,
            retry_start_utc=start,
        )
    assert result.get("retry_exhausted") is True
    mock_enq.assert_not_called()


# ============================================================
# _enqueue_pipeline_run — 携带 attempt + retry_start_utc 给 wrapper
# ============================================================

def test_enqueue_passes_attempt_and_retry_start():
    """_enqueue_pipeline_run 把 attempt + retry_start_utc 传给 add_job kwargs。"""
    fake_sched = MagicMock()
    jobs_module._active_scheduler = fake_sched
    try:
        ok = _enqueue_pipeline_run(
            "event_price", delay_sec=300, attempt=2,
            retry_start_utc="2026-05-03T16:00:00Z",
        )
    finally:
        jobs_module._active_scheduler = None
    assert ok is True
    fake_sched.add_job.assert_called_once()
    kwargs = fake_sched.add_job.call_args.kwargs["kwargs"]
    assert kwargs["run_trigger"] == "event_price"
    assert kwargs["attempt"] == 2
    assert kwargs["retry_start_utc"] == "2026-05-03T16:00:00Z"
    # add_job func 是 wrapper
    assert (
        fake_sched.add_job.call_args.kwargs["func"]
        is jobs_module.job_pipeline_run_with_retry
    )


def test_enqueue_no_scheduler_returns_false():
    jobs_module._active_scheduler = None
    ok = _enqueue_pipeline_run(
        "event_price", delay_sec=10, attempt=1,
    )
    assert ok is False


# ============================================================
# job_hard_invalidation_monitor — 端到端
# ============================================================

@pytest.fixture
def in_memory_db_factory():
    """每次调用返新 in-memory DB(模拟 conn_factory)。"""
    conns = []

    def factory():
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        with open("src/data/storage/schema.sql", encoding="utf-8") as f:
            c.executescript(f.read())
        from scripts.init_v14_tables import apply_migration
        apply_migration(c)
        c.commit()
        conns.append(c)
        return c

    yield factory
    for c in conns:
        try:
            c.close()
        except Exception:
            pass


def test_hard_invalidation_monitor_no_active_thesis(in_memory_db_factory):
    """无 active thesis + 无 1h K 线 → 返 no_kline 错误。"""
    result = job_hard_invalidation_monitor(conn_factory=in_memory_db_factory)
    assert result["status"] in ("ok", "skipped")
    body = result.get("by_collector") or {}
    assert body.get("hard_invalidation") == 0


def test_hard_invalidation_monitor_no_breach(in_memory_db_factory):
    """有 1h K 线 + 无 active thesis → events_triggered=[]。"""
    conn = in_memory_db_factory()
    conn.execute(
        "INSERT INTO price_candles (symbol, timeframe, open_time_utc, "
        "open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("BTCUSDT", "1h", "2026-05-03T16:00:00Z",
         78000, 78500, 77800, 78400, 1000),
    )
    conn.commit()
    # job 用自己的 conn(从 factory 拿新的 — 但本测试里 schema 已建)
    result = job_hard_invalidation_monitor(conn_factory=lambda: conn)
    assert result["status"] in ("ok", "skipped")
    assert result.get("events_triggered") == []


# ============================================================
# job_position_health_check — stub 行为
# ============================================================

def test_position_health_check_no_active_thesis(in_memory_db_factory):
    """无 active thesis → 直接返,不调 AI(本 sprint stub)。"""
    result = job_position_health_check(conn_factory=in_memory_db_factory)
    assert result["status"] in ("ok", "skipped")
    body = result.get("by_collector") or {}
    assert body.get("position_health_check") == "no_active_thesis"


def test_position_health_check_with_active_thesis_no_baseline(in_memory_db_factory):
    """1.10-H 改造后:有 active thesis 但无 baseline(无 strategy_run + 无 1h K 线)
    → skipped_no_price_data。完整 AI 接通验证见 tests/test_jobs_weekly_review_and_health_check.py。"""
    conn = in_memory_db_factory()
    from src.strategy import thesis_manager
    spec = {
        "direction": "long", "core_logic": "test", "confidence_score": 70,
        "break_conditions": ["a", "b", "c"],
        "entry_orders": [{"price": 75000.0, "size_pct": 0.30, "size_usdt": 30000.0}],
        "stop_loss_orders": [],
        "take_profit_orders": [],
    }
    thesis_manager.create_thesis(
        conn, thesis_spec=spec, run_id="r", now_utc="2026-05-03T12:00:00Z",
        expires_at_utc="2026-05-10T12:00:00Z", thesis_id="t_health_001",
    )
    conn.commit()
    result = job_position_health_check(conn_factory=lambda: conn)
    body = result.get("by_collector") or {}
    assert body.get("position_health_check") == "skipped_no_price_data"
