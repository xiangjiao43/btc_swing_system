"""Sprint 1.10-C 单测:review_pending(v1.4 §4.2.6 / §3.4.6 / §3.4.7)。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.strategy.fuse_monitor import record_14d_fuse_triggered
from src.strategy.review_pending import (
    enter_review_pending, is_in_review_pending,
    exit_a_threshold_adjustment, exit_b_thesis_renewal, exit_c_fuse_reset,
)


_MIGRATION_009 = (
    Path(__file__).resolve().parent.parent
    / "migrations" / "009_v14_virtual_account_thesis.sql"
)
_MIGRATION_010 = (
    Path(__file__).resolve().parent.parent
    / "migrations" / "010_v14_fuse_system_states.sql"
)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE strategy_runs (run_id TEXT PRIMARY KEY)")
    c.executescript(_MIGRATION_009.read_text(encoding="utf-8"))
    c.executescript(_MIGRATION_010.read_text(encoding="utf-8"))
    c.execute("ALTER TABLE theses ADD COLUMN is_60d_capped INTEGER NOT NULL DEFAULT 0")
    yield c
    c.close()


# ============================================================
# enter / is_in
# ============================================================

def test_enter_review_pending_writes_active_row(conn):
    res = enter_review_pending(
        conn, reason="validator_19_60d_cap",
        related_thesis_id="th1",
        entered_at_utc="2026-05-10T08:00:00Z",
    )
    conn.commit()
    assert res["state_id"] > 0
    assert not res["was_already_active"]
    assert res["reason"] == "validator_19_60d_cap"

    status = is_in_review_pending(conn)
    assert status["in_review_pending"]
    assert status["reason"] == "validator_19_60d_cap"
    assert status["related_thesis_id"] == "th1"


def test_enter_idempotent_when_already_active(conn):
    """已在 review_pending 时再调 enter → 返回当前 state_id,不插入新行。"""
    res1 = enter_review_pending(
        conn, reason="validator_19_60d_cap",
        related_thesis_id="th1", entered_at_utc="2026-05-10T08:00:00Z",
    )
    conn.commit()
    res2 = enter_review_pending(
        conn, reason="validator_20_consecutive_fuse",
        related_thesis_id="th2", entered_at_utc="2026-05-11T08:00:00Z",
    )
    conn.commit()
    assert res2["was_already_active"]
    assert res2["state_id"] == res1["state_id"]
    # 第二次 reason 不覆盖
    assert res2["reason"] == "validator_19_60d_cap"
    # DB 只 1 行 active
    cnt = conn.execute(
        "SELECT COUNT(*) FROM system_states "
        "WHERE state_type='review_pending' AND exit_at_utc IS NULL"
    ).fetchone()[0]
    assert cnt == 1


def test_is_in_review_pending_empty(conn):
    s = is_in_review_pending(conn)
    assert not s["in_review_pending"]
    assert s["state_id"] is None


# ============================================================
# 三种出口
# ============================================================

def test_exit_a_writes_exit_fields(conn):
    enter_review_pending(
        conn, reason="validator_19_60d_cap",
        related_thesis_id="th1", entered_at_utc="2026-05-10T08:00:00Z",
    )
    conn.commit()
    res = exit_a_threshold_adjustment(conn, "2026-05-12T08:00:00Z")
    conn.commit()
    assert res["exited"]
    assert res["exit_reason"] == "exit_a_threshold_adjustment"
    # 已退出
    assert not is_in_review_pending(conn)["in_review_pending"]
    row = conn.execute(
        "SELECT exit_at_utc, exit_reason FROM system_states "
        "WHERE state_id=?", (res["state_id"],),
    ).fetchone()
    assert row["exit_at_utc"] == "2026-05-12T08:00:00Z"
    assert row["exit_reason"] == "exit_a_threshold_adjustment"


def test_exit_b_thesis_renewal_with_spec(conn):
    enter_review_pending(
        conn, reason="validator_19_60d_cap",
        related_thesis_id="th1", entered_at_utc="2026-05-10T08:00:00Z",
    )
    conn.commit()
    res = exit_b_thesis_renewal(
        conn, "2026-05-12T08:00:00Z",
        new_thesis_spec={"direction": "long", "core_logic": "renewed"},
    )
    conn.commit()
    assert res["exited"]
    assert res["exit_reason"] == "exit_b_thesis_renewal"
    assert res["new_thesis_spec_received"]


def test_exit_c_fuse_reset_clears_14d_fuse_events(conn):
    """出口 C:删 14d_fuse_triggered 行(避 Validator 20 持续触发)。"""
    record_14d_fuse_triggered(conn, "2026-04-15T08:00:00Z", fuse_subtype="thesis_cycle")
    record_14d_fuse_triggered(conn, "2026-04-25T08:00:00Z", fuse_subtype="channel_c")
    enter_review_pending(
        conn, reason="validator_20_consecutive_fuse",
        related_thesis_id=None, entered_at_utc="2026-05-10T08:00:00Z",
    )
    conn.commit()

    res = exit_c_fuse_reset(conn, "2026-05-12T08:00:00Z")
    conn.commit()
    assert res["exited"]
    assert res["fuse_records_deleted"] == 2
    # 14d_fuse_triggered 全删
    cnt = conn.execute(
        "SELECT COUNT(*) FROM fuse_events WHERE event_type='14d_fuse_triggered'"
    ).fetchone()[0]
    assert cnt == 0


def test_exit_when_not_active_no_op(conn):
    """无 active review_pending 时调 exit → not exited(不报错)。"""
    res = exit_a_threshold_adjustment(conn, "2026-05-12T08:00:00Z")
    assert not res["exited"]
    assert res["reason"] == "no_active_review_pending"


def test_re_enter_after_exit(conn):
    """exit 后可再次 enter(全周期循环)。"""
    enter_review_pending(
        conn, reason="r1", related_thesis_id="th1",
        entered_at_utc="2026-05-10T08:00:00Z",
    )
    exit_a_threshold_adjustment(conn, "2026-05-12T08:00:00Z")
    conn.commit()
    res = enter_review_pending(
        conn, reason="r2", related_thesis_id="th2",
        entered_at_utc="2026-05-15T08:00:00Z",
    )
    conn.commit()
    assert not res["was_already_active"]
    # DB 2 行,但 active=1
    total = conn.execute("SELECT COUNT(*) FROM system_states").fetchone()[0]
    active = conn.execute(
        "SELECT COUNT(*) FROM system_states WHERE exit_at_utc IS NULL"
    ).fetchone()[0]
    assert total == 2
    assert active == 1
