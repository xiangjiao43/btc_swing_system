"""Sprint 1.10-F 单测:RetryPolicy(v1.4 §6.3.2)。"""
from __future__ import annotations

import json

import pytest

from src.ai.retry_policy import (
    RetryPolicy,
    FAILURE_TIMEOUT, FAILURE_API_ERROR, FAILURE_PARSE_ERROR,
    FAILURE_VALIDATION, FAILURE_UNKNOWN,
)


# ============================================================
# compute_backoff_seconds(指数退避)
# ============================================================

def test_backoff_first_attempt_5min():
    p = RetryPolicy(intervals_minutes=[5, 10, 20], max_attempts_per_layer=3)
    assert p.compute_backoff_seconds(1) == 300  # 5 * 60


def test_backoff_second_attempt_10min():
    p = RetryPolicy(intervals_minutes=[5, 10, 20], max_attempts_per_layer=3)
    assert p.compute_backoff_seconds(2) == 600


def test_backoff_third_attempt_20min():
    p = RetryPolicy(intervals_minutes=[5, 10, 20], max_attempts_per_layer=3)
    assert p.compute_backoff_seconds(3) == 1200


def test_backoff_over_max_returns_none():
    p = RetryPolicy(intervals_minutes=[5, 10, 20], max_attempts_per_layer=3)
    assert p.compute_backoff_seconds(4) is None
    assert p.compute_backoff_seconds(0) is None


def test_backoff_uses_last_when_intervals_short():
    """intervals 比 max_attempts 短时,后续 attempt 用最后一个值。"""
    p = RetryPolicy(intervals_minutes=[5], max_attempts_per_layer=3)
    assert p.compute_backoff_seconds(1) == 300
    assert p.compute_backoff_seconds(2) == 300  # 兜底


# ============================================================
# is_within_window(2h 窗口)
# ============================================================

def test_window_within_1h_ok():
    p = RetryPolicy(total_window_hours=2)
    assert p.is_within_window(
        "2026-05-03T08:00:00Z", "2026-05-03T09:00:00Z",
    )


def test_window_just_under_2h_ok():
    p = RetryPolicy(total_window_hours=2)
    assert p.is_within_window(
        "2026-05-03T08:00:00Z", "2026-05-03T09:59:59Z",
    )


def test_window_2h_exact_excluded():
    """边界:2h 整 → 不在窗口内(< 严格)。"""
    p = RetryPolicy(total_window_hours=2)
    assert not p.is_within_window(
        "2026-05-03T08:00:00Z", "2026-05-03T10:00:00Z",
    )


def test_window_over_2h_failed():
    p = RetryPolicy(total_window_hours=2)
    assert not p.is_within_window(
        "2026-05-03T08:00:00Z", "2026-05-03T11:00:00Z",
    )


def test_window_invalid_iso_returns_false():
    p = RetryPolicy()
    assert not p.is_within_window("garbage", "2026-05-03T09:00:00Z")


# ============================================================
# should_retry(组合判定)
# ============================================================

def test_should_retry_attempt_within_max_and_window():
    p = RetryPolicy(max_attempts_per_layer=3, total_window_hours=2)
    assert p.should_retry(
        attempt=1, run_started_at_utc="2026-05-03T08:00:00Z",
        now_utc="2026-05-03T08:05:00Z",
    )


def test_should_retry_attempt_over_max_no():
    p = RetryPolicy(max_attempts_per_layer=3)
    assert not p.should_retry(
        attempt=4, run_started_at_utc="2026-05-03T08:00:00Z",
        now_utc="2026-05-03T08:05:00Z",
    )


def test_should_retry_outside_window_no():
    p = RetryPolicy(total_window_hours=2)
    assert not p.should_retry(
        attempt=1, run_started_at_utc="2026-05-03T08:00:00Z",
        now_utc="2026-05-03T11:00:00Z",
    )


# ============================================================
# classify_failure
# ============================================================

def test_classify_timeout():
    assert RetryPolicy.classify_failure(TimeoutError("x")) == FAILURE_TIMEOUT
    assert RetryPolicy.classify_failure(Exception("request timeout exceeded")) == FAILURE_TIMEOUT


def test_classify_parse_error():
    assert RetryPolicy.classify_failure(json.JSONDecodeError("x", "y", 0)) == FAILURE_PARSE_ERROR
    assert RetryPolicy.classify_failure(Exception("failed to parse json")) == FAILURE_PARSE_ERROR


def test_classify_validation():
    assert RetryPolicy.classify_failure(Exception("validator failed")) == FAILURE_VALIDATION
    assert RetryPolicy.classify_failure(Exception("validation rejected")) == FAILURE_VALIDATION


def test_classify_generic_api_error():
    assert RetryPolicy.classify_failure(ValueError("bad request")) == FAILURE_API_ERROR
    assert RetryPolicy.classify_failure(RuntimeError("anthropic 500")) == FAILURE_API_ERROR


def test_classify_unknown():
    """非 Exception 子类(理论 BaseException)→ unknown。"""
    class Weird(BaseException):
        pass
    assert RetryPolicy.classify_failure(Weird("x")) == FAILURE_UNKNOWN


# ============================================================
# config 读取(base.yaml)
# ============================================================

def test_loads_from_base_yaml_defaults():
    """无显式参数时,从 base.yaml 读 ai_retry 段(本 sprint commit 1 已加)。"""
    p = RetryPolicy()
    # base.yaml::ai_retry.intervals_minutes = [5, 10, 20]
    assert p.intervals_minutes == [5, 10, 20]
    assert p.max_attempts_per_layer == 3
    assert p.total_window_hours == 2
