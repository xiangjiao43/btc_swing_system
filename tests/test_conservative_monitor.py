"""tests/test_conservative_monitor.py — Sprint 1.10-H commit 4 单测。

覆盖 v1.4 §8.2 S3 过度保守监控 + D4=b2 EXIT_D 联动。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from src.strategy.conservative_monitor import (
    ALERT_TYPE,
    CRITICAL_THRESHOLD_DAYS,
    REVIEW_PENDING_REASON,
    WARNING_THRESHOLD_DAYS,
    ConservativeMonitor,
)
from src.strategy.review_pending import (
    EXIT_D,
    enter_review_pending,
    exit_d_thesis_resumed,
    is_in_review_pending,
)


_NOW = datetime(2026, 5, 10, 16, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    with open("src/data/storage/schema.sql", encoding="utf-8") as f:
        c.executescript(f.read())
    from scripts.init_v14_tables import apply_migration
    apply_migration(c)
    yield c
    c.close()


def _seed_thesis(conn, *, thesis_id, created_at_utc):
    conn.execute(
        "INSERT INTO theses (thesis_id, created_at_run_id, created_at_utc, "
        "direction, core_logic, confidence_score, break_conditions, "
        "lifecycle_stage, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (thesis_id, "r_test", created_at_utc, "long",
         "test", 70, "[]", "planned", "active"),
    )


# ============================================================
# 1. check_recent_thesis_count
# ============================================================

def test_no_thesis_ever_returns_severity_none(conn):
    """系统从未创建过 thesis(冷启动)→ severity='none' 不触发(避免冷启动期误报)。"""
    r = ConservativeMonitor.check_recent_thesis_count(conn, now_utc=_NOW)
    assert r["severity"] == "none"
    assert r["threshold_breached"] is False
    assert r["last_thesis_created_at_utc"] is None


def test_thesis_created_29_days_ago_no_trigger(conn):
    """29 天前创建过 thesis(< 30 天阈值)→ 不触发。"""
    _seed_thesis(
        conn, thesis_id="t_29d",
        created_at_utc=(_NOW - timedelta(days=29)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    conn.commit()
    r = ConservativeMonitor.check_recent_thesis_count(conn, now_utc=_NOW)
    assert r["severity"] == "none"
    assert r["threshold_breached"] is False


def test_thesis_created_30_days_ago_warning(conn):
    """刚好 30 天前 → severity='warning'(等号触发)。"""
    _seed_thesis(
        conn, thesis_id="t_30d",
        created_at_utc=(_NOW - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    conn.commit()
    r = ConservativeMonitor.check_recent_thesis_count(conn, now_utc=_NOW)
    assert r["severity"] == "warning"
    assert r["threshold_breached"] is True
    assert r["days_no_thesis"] >= 30.0


def test_thesis_created_45_days_ago_warning(conn):
    """45 天(30 < x < 60)→ warning。"""
    _seed_thesis(
        conn, thesis_id="t_45d",
        created_at_utc=(_NOW - timedelta(days=45)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    conn.commit()
    r = ConservativeMonitor.check_recent_thesis_count(conn, now_utc=_NOW)
    assert r["severity"] == "warning"


def test_thesis_created_60_days_ago_critical(conn):
    """刚好 60 天 → critical(等号触发)。"""
    _seed_thesis(
        conn, thesis_id="t_60d",
        created_at_utc=(_NOW - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    conn.commit()
    r = ConservativeMonitor.check_recent_thesis_count(conn, now_utc=_NOW)
    assert r["severity"] == "critical"
    assert r["threshold_breached"] is True


def test_uses_most_recent_thesis(conn):
    """有多个 thesis,只看最近一个的 created_at_utc。"""
    _seed_thesis(
        conn, thesis_id="t_old",
        created_at_utc=(_NOW - timedelta(days=70)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    _seed_thesis(
        conn, thesis_id="t_recent",
        created_at_utc=(_NOW - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    conn.commit()
    r = ConservativeMonitor.check_recent_thesis_count(conn, now_utc=_NOW)
    assert r["severity"] == "none"


# ============================================================
# 2. check_and_alert(写 alerts + 进 review_pending)
# ============================================================

def test_warning_writes_alert_no_review_pending(conn):
    """warning → 写 alerts 1 行,不进 review_pending。"""
    _seed_thesis(
        conn, thesis_id="t_45d",
        created_at_utc=(_NOW - timedelta(days=45)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    conn.commit()
    r = ConservativeMonitor.check_and_alert(conn, now_utc=_NOW)
    conn.commit()
    assert r["severity"] == "warning"
    assert r["alert_written"] is True
    assert r["review_pending_entered"] is False
    # alerts 表有 1 行
    cnt = conn.execute(
        "SELECT COUNT(*) FROM alerts WHERE alert_type = ?",
        (ALERT_TYPE,),
    ).fetchone()[0]
    assert cnt == 1
    # 不在 review_pending
    rp = is_in_review_pending(conn)
    assert rp["in_review_pending"] is False


def test_critical_writes_alert_and_enters_review_pending(conn):
    """critical → 写 alerts + 进 review_pending(reason='overly_conservative')。"""
    _seed_thesis(
        conn, thesis_id="t_70d",
        created_at_utc=(_NOW - timedelta(days=70)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    conn.commit()
    r = ConservativeMonitor.check_and_alert(conn, now_utc=_NOW)
    conn.commit()
    assert r["severity"] == "critical"
    assert r["alert_written"] is True
    assert r["review_pending_entered"] is True
    rp = is_in_review_pending(conn)
    assert rp["in_review_pending"] is True
    assert rp["reason"] == "overly_conservative"


def test_idempotent_within_24h_no_double_alert(conn):
    """同一 severity 24h 内只写一次 alerts(幂等)。"""
    _seed_thesis(
        conn, thesis_id="t_45d",
        created_at_utc=(_NOW - timedelta(days=45)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    conn.commit()
    r1 = ConservativeMonitor.check_and_alert(conn, now_utc=_NOW)
    conn.commit()
    r2 = ConservativeMonitor.check_and_alert(
        conn, now_utc=_NOW + timedelta(hours=2),
    )
    conn.commit()
    assert r1["alert_written"] is True
    assert r2["alert_written"] is False  # 幂等
    cnt = conn.execute(
        "SELECT COUNT(*) FROM alerts WHERE alert_type = ?",
        (ALERT_TYPE,),
    ).fetchone()[0]
    assert cnt == 1


def test_no_action_when_below_threshold(conn):
    """29 天 → severity='none' → 不写 alerts 不进 RP。"""
    _seed_thesis(
        conn, thesis_id="t_29d",
        created_at_utc=(_NOW - timedelta(days=29)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    conn.commit()
    r = ConservativeMonitor.check_and_alert(conn, now_utc=_NOW)
    assert r["alert_written"] is False
    assert r["review_pending_entered"] is False


def test_critical_review_pending_idempotent(conn):
    """已在 review_pending(overly_conservative)→ 不重复进。"""
    enter_review_pending(
        conn, reason="overly_conservative",
        related_thesis_id=None,
        entered_at_utc=(_NOW - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    _seed_thesis(
        conn, thesis_id="t_70d",
        created_at_utc=(_NOW - timedelta(days=70)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    conn.commit()
    r = ConservativeMonitor.check_and_alert(conn, now_utc=_NOW)
    conn.commit()
    # was_already_active=True → review_pending_entered=False
    assert r["review_pending_entered"] is False
    # 但仍在 review_pending
    rp = is_in_review_pending(conn)
    assert rp["in_review_pending"] is True


# ============================================================
# 3. EXIT_D = 'exit_d_thesis_resumed'(D4=b2)
# ============================================================

def test_exit_d_constant_value():
    assert EXIT_D == "exit_d_thesis_resumed"


def test_exit_d_only_works_for_overly_conservative(conn):
    """exit_d 只对 reason='overly_conservative' 生效;其他 reason 不退出。"""
    enter_review_pending(
        conn, reason="60d_cap",  # 非 overly_conservative
        related_thesis_id="t_60d",
        entered_at_utc=(_NOW - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    conn.commit()
    res = exit_d_thesis_resumed(
        conn, exit_at_utc=_NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
        new_thesis_id="t_new",
    )
    assert res["exited"] is False
    assert "exit_d_only_for_overly_conservative" in res["reason"]
    rp = is_in_review_pending(conn)
    assert rp["in_review_pending"] is True  # 仍 active


def test_exit_d_succeeds_for_overly_conservative(conn):
    """reason='overly_conservative' + 调 exit_d → 退出 + exit_reason='exit_d_thesis_resumed'。"""
    enter_review_pending(
        conn, reason="overly_conservative",
        related_thesis_id=None,
        entered_at_utc=(_NOW - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    conn.commit()
    res = exit_d_thesis_resumed(
        conn, exit_at_utc=_NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
        new_thesis_id="t_new_resumed",
    )
    conn.commit()
    assert res["exited"] is True
    assert res["new_thesis_id"] == "t_new_resumed"
    rp = is_in_review_pending(conn)
    assert rp["in_review_pending"] is False
    # exit_reason 写入
    row = conn.execute(
        "SELECT exit_reason FROM system_states WHERE state_id = ?",
        (res["state_id"],),
    ).fetchone()
    assert row["exit_reason"] == EXIT_D


def test_exit_d_no_active_review_pending(conn):
    """无 active review_pending → exit_d 返 'no_active_review_pending'。"""
    res = exit_d_thesis_resumed(
        conn, exit_at_utc=_NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    assert res["exited"] is False
    assert res["reason"] == "no_active_review_pending"


# ============================================================
# 4. 阈值常量
# ============================================================

def test_thresholds_match_v14():
    assert WARNING_THRESHOLD_DAYS == 30
    assert CRITICAL_THRESHOLD_DAYS == 60
    assert REVIEW_PENDING_REASON == "overly_conservative"
