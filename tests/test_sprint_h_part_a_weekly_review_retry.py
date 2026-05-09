"""Sprint H Part A — weekly_review_with_retry 单测。

§Z 端到端断言:
- 失败时 _enqueue_weekly_review 真被调用(retry_scheduled=True)
- attempt 累加 + retry_next_delay_sec = 30/60/60 min(共享 ai_retry)
- attempt > 3 或超 3h 窗口 → retry_exhausted=True 不再调度
- 成功路径不触发 retry
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.scheduler import jobs as jobs_mod
from src.scheduler.jobs import (
    _enqueue_weekly_review,
    job_weekly_review_with_retry,
)


@pytest.fixture(autouse=True)
def _reset_active_scheduler():
    """test 间隔离 _active_scheduler 全局,避免顺序污染。"""
    saved = jobs_mod._active_scheduler
    jobs_mod._active_scheduler = None
    try:
        yield
    finally:
        jobs_mod._active_scheduler = saved


# ============================================================
# 1. AI 成功 → 不 retry
# ============================================================

def test_with_retry_success_no_enqueue():
    """job_weekly_review 返 ai_status=success → 不触发 retry。"""
    success_result = {
        "by_collector": {
            "weekly_review": "completed",
            "ai_status": "success",
            "critical_count": 0,
            "week_start_utc": "2026-05-04",
        },
        "status": "ok",
        "total_upserted": 1,
    }
    with patch.object(jobs_mod, "job_weekly_review", return_value=success_result), \
         patch.object(jobs_mod, "_enqueue_weekly_review") as enq:
        result = job_weekly_review_with_retry(attempt=1)
    enq.assert_not_called()
    assert result.get("retry_scheduled") is None  # 未设置 = 没走 retry 分支


# ============================================================
# 2. AI 失败 attempt=1 → 调度 attempt=2,backoff=1800s(30min)
# ============================================================

def test_with_retry_first_failure_schedules_attempt_2_at_30min():
    """attempt=1 main fail → schedule attempt=2 at +30min(intervals[0])。"""
    failed_result = {
        "by_collector": {
            "weekly_review": "completed",
            "ai_status": "degraded_client_unavailable",
            "critical_count": 1,
        },
        "status": "ok",
    }
    with patch.object(jobs_mod, "job_weekly_review", return_value=failed_result), \
         patch.object(jobs_mod, "_enqueue_weekly_review", return_value=True) as enq:
        result = job_weekly_review_with_retry(attempt=1)
    enq.assert_called_once()
    call = enq.call_args
    assert call.kwargs["attempt"] == 2
    assert call.kwargs["delay_sec"] == 1800   # 30 min × 60(intervals[0])
    assert result["retry_scheduled"] is True
    assert result["retry_next_attempt"] == 2
    assert result["retry_next_delay_sec"] == 1800


def test_with_retry_attempt_3_schedules_attempt_4_at_60min():
    """attempt=3 retry 2 fail → schedule attempt=4 at +60min(intervals[2])。"""
    failed_result = {
        "by_collector": {"ai_status": "degraded_client_unavailable"},
        "status": "ok",
    }
    start_utc = (datetime.now(timezone.utc)
                 - timedelta(minutes=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with patch.object(jobs_mod, "job_weekly_review", return_value=failed_result), \
         patch.object(jobs_mod, "_enqueue_weekly_review", return_value=True) as enq:
        result = job_weekly_review_with_retry(
            attempt=3, retry_start_utc=start_utc,
        )
    enq.assert_called_once()
    assert enq.call_args.kwargs["attempt"] == 4
    assert enq.call_args.kwargs["delay_sec"] == 3600   # intervals[2] = 60min
    assert result["retry_scheduled"] is True


# ============================================================
# 3. attempt=2 失败 → 调度 attempt=3,backoff=3600s(60min)
# ============================================================

def test_with_retry_attempt_2_schedules_attempt_3_at_60min():
    """attempt=2 retry 1 fail → schedule attempt=3 at +60min(intervals[1])。"""
    failed_result = {
        "by_collector": {"ai_status": "degraded_l5_failed"},
        "status": "ok",
    }
    start_utc = (datetime.now(timezone.utc)
                 - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with patch.object(jobs_mod, "job_weekly_review", return_value=failed_result), \
         patch.object(jobs_mod, "_enqueue_weekly_review", return_value=True) as enq:
        result = job_weekly_review_with_retry(
            attempt=2, retry_start_utc=start_utc,
        )
    enq.assert_called_once()
    assert enq.call_args.kwargs["attempt"] == 3
    assert enq.call_args.kwargs["delay_sec"] == 3600   # intervals[1] = 60 min
    assert result["retry_scheduled"] is True


# ============================================================
# 4. attempt=4 失败 → 不再调度(超 max_attempts=4),retry_exhausted=True
# ============================================================

def test_with_retry_fourth_failure_exhausts():
    """main + 3 retry = 4 attempts;attempt=4 fail → no more retry。"""
    failed_result = {
        "by_collector": {"ai_status": "degraded_l5_failed"},
        "status": "ok",
    }
    start_utc = (datetime.now(timezone.utc)
                 - timedelta(minutes=150)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with patch.object(jobs_mod, "job_weekly_review", return_value=failed_result), \
         patch.object(jobs_mod, "_enqueue_weekly_review") as enq:
        result = job_weekly_review_with_retry(
            attempt=4, retry_start_utc=start_utc,
        )
    enq.assert_not_called()
    assert result.get("retry_exhausted") is True
    assert result["retry_attempts"] == 4


# ============================================================
# 5. retry_start_utc 超 3h 窗口 → 不再调度
# ============================================================

def test_with_retry_outside_3h_window_exhausts():
    failed_result = {
        "by_collector": {"ai_status": "degraded_l5_failed"},
        "status": "ok",
    }
    start_utc = (datetime.now(timezone.utc)
                 - timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with patch.object(jobs_mod, "job_weekly_review", return_value=failed_result), \
         patch.object(jobs_mod, "_enqueue_weekly_review") as enq:
        result = job_weekly_review_with_retry(
            attempt=2, retry_start_utc=start_utc,
        )
    enq.assert_not_called()
    assert result.get("retry_exhausted") is True


# ============================================================
# 6. input_builder 失败也应 retry(transient DB 问题)
# ============================================================

def test_with_retry_input_builder_failed_triggers_retry():
    input_failed_result = {
        "by_collector": {
            "weekly_review": "input_builder_failed",
        },
        "status": "ok",
        "total_upserted": 0,
        "errors": {"input_builder": "DB locked"},
    }
    with patch.object(jobs_mod, "job_weekly_review", return_value=input_failed_result), \
         patch.object(jobs_mod, "_enqueue_weekly_review", return_value=True) as enq:
        result = job_weekly_review_with_retry(attempt=1)
    enq.assert_called_once()
    assert result["retry_scheduled"] is True


# ============================================================
# 7. _enqueue_weekly_review:无 scheduler 返 False(单测路径)
# ============================================================

def test_enqueue_no_scheduler_returns_false():
    jobs_mod._active_scheduler = None
    ok = _enqueue_weekly_review(
        delay_sec=1800, attempt=2, retry_start_utc="2026-05-09T22:00:00Z",
    )
    assert ok is False


def test_enqueue_with_scheduler_calls_add_job():
    """_enqueue_weekly_review 真把任务放到 scheduler。"""
    fake_sched = MagicMock()
    jobs_mod._active_scheduler = fake_sched
    try:
        ok = jobs_mod._enqueue_weekly_review(
            delay_sec=1800, attempt=2, retry_start_utc="2026-05-09T22:00:00Z",
        )
    finally:
        jobs_mod._active_scheduler = None
    assert ok is True
    fake_sched.add_job.assert_called_once()
    kwargs = fake_sched.add_job.call_args.kwargs
    assert kwargs["trigger"] == "date"
    inner_kwargs = kwargs["kwargs"]
    assert inner_kwargs["attempt"] == 2
    assert inner_kwargs["retry_start_utc"] == "2026-05-09T22:00:00Z"
    # add_job func 是本 wrapper(下次跑时也走 retry 链路)
    # 用 jobs_mod attribute 而非 import 后的引用,避免 reload 导致 identity 丢失
    assert kwargs["func"] is jobs_mod.job_weekly_review_with_retry


# ============================================================
# 8. _JOB_FUNCTIONS 注册 — 生产 yaml weekly_review 走 retry
# ============================================================

def test_job_functions_weekly_review_uses_retry_wrapper():
    """_JOB_FUNCTIONS['weekly_review'] 必须是 retry wrapper(生产 yaml 用此 key)。"""
    # 用 jobs_mod attribute 而非 import 后的引用,避免 reload 导致 identity 丢失
    assert jobs_mod._JOB_FUNCTIONS["weekly_review"] is jobs_mod.job_weekly_review_with_retry
    # 同时保留无 retry 入口供单测 / 直调
    assert jobs_mod._JOB_FUNCTIONS["weekly_review_no_retry"] is jobs_mod.job_weekly_review
