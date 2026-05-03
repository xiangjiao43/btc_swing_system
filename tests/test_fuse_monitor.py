"""Sprint 1.10-C 单测:FuseMonitor + migration 010(v1.4 §4.3.4 / Validator 18-20)。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.data.storage.dao import ThesesDAO
from src.strategy.fuse_monitor import (
    record_thesis_cycle, record_channel_c_use, record_14d_fuse_triggered,
    check_14d_fuse, check_60d_cap, mark_60d_capped, check_consecutive_fuse,
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
    # ALTER 由 init_v14_tables.py 处理;测试里手工加(对齐生产)
    c.execute("ALTER TABLE theses ADD COLUMN is_60d_capped INTEGER NOT NULL DEFAULT 0")
    yield c
    c.close()


# ============================================================
# fuse_events 写入
# ============================================================

def test_record_thesis_cycle_writes_event(conn):
    rid = record_thesis_cycle(conn, "th1", "2026-05-10T08:00:00Z")
    conn.commit()
    assert rid > 0
    row = conn.execute("SELECT * FROM fuse_events WHERE id=?", (rid,)).fetchone()
    assert row["event_type"] == "thesis_cycle_completed"
    assert row["thesis_id"] == "th1"
    assert row["triggered_at_utc"] == "2026-05-10T08:00:00Z"


def test_record_channel_c_use_writes_event(conn):
    rid = record_channel_c_use(conn, "th1", "2026-05-10T08:00:00Z",
                               metadata={"prev_thesis_loss_pct": -3.5})
    conn.commit()
    row = conn.execute("SELECT * FROM fuse_events WHERE id=?", (rid,)).fetchone()
    assert row["event_type"] == "channel_c_used"
    assert "prev_thesis_loss_pct" in row["metadata_json"]


# ============================================================
# Validator 18:14 天熔断双触发
# ============================================================

def test_14d_fuse_no_events_no_fuse(conn):
    r = check_14d_fuse(conn, "2026-05-10T08:00:00Z")
    assert r["thesis_cycle_count_14d"] == 0
    assert r["channel_c_count_14d"] == 0
    assert not r["in_fuse"]


def test_14d_fuse_one_thesis_cycle_no_fuse(conn):
    record_thesis_cycle(conn, "th1", "2026-05-08T08:00:00Z")
    conn.commit()
    r = check_14d_fuse(conn, "2026-05-10T08:00:00Z")
    assert r["thesis_cycle_count_14d"] == 1
    assert not r["in_thesis_cycle_fuse"]
    assert not r["in_fuse"]


def test_14d_fuse_two_thesis_cycles_triggers(conn):
    """14 天内 2 次 thesis 完整周期 → in_thesis_cycle_fuse=True。"""
    record_thesis_cycle(conn, "th1", "2026-05-01T08:00:00Z")
    record_thesis_cycle(conn, "th2", "2026-05-08T08:00:00Z")
    conn.commit()
    r = check_14d_fuse(conn, "2026-05-10T08:00:00Z")
    assert r["thesis_cycle_count_14d"] == 2
    assert r["in_thesis_cycle_fuse"]
    assert r["in_fuse"]


def test_14d_fuse_two_channel_c_disables_c(conn):
    """14 天内 2 次通道 C → channel_c_disabled=True。"""
    record_channel_c_use(conn, "th1", "2026-05-02T08:00:00Z")
    record_channel_c_use(conn, "th2", "2026-05-09T08:00:00Z")
    conn.commit()
    r = check_14d_fuse(conn, "2026-05-10T08:00:00Z")
    assert r["channel_c_count_14d"] == 2
    assert r["channel_c_disabled"]
    assert r["in_fuse"]


def test_14d_fuse_15_days_ago_excluded(conn):
    """15 天前的事件不计入 14 天窗口。"""
    record_thesis_cycle(conn, "th_old", "2026-04-25T08:00:00Z")
    record_thesis_cycle(conn, "th1", "2026-05-08T08:00:00Z")
    conn.commit()
    # now=5-10:5-10 - 14 天 = 4-26;4-25 在窗口外,只 1 个
    r = check_14d_fuse(conn, "2026-05-10T08:00:00Z")
    assert r["thesis_cycle_count_14d"] == 1
    assert not r["in_thesis_cycle_fuse"]


def test_14d_fuse_13d_23h_within_window(conn):
    """13 天 23 小时(刚不到 14 天)→ 仍在窗口内。"""
    record_thesis_cycle(conn, "th_edge", "2026-04-26T09:00:00Z")
    record_thesis_cycle(conn, "th1", "2026-05-08T08:00:00Z")
    conn.commit()
    # now=5-10 08:00:5-10 - 14 天 = 4-26 08:00;4-26 09:00 在窗口内
    r = check_14d_fuse(conn, "2026-05-10T08:00:00Z")
    assert r["thesis_cycle_count_14d"] == 2
    assert r["in_thesis_cycle_fuse"]


# ============================================================
# Validator 19:60 天上限
# ============================================================

def _make_thesis_active(conn, thesis_id, created_at_utc):
    ThesesDAO.create(
        conn, thesis_id=thesis_id, created_at_run_id="r1",
        created_at_utc=created_at_utc, direction="long",
        core_logic="test", confidence_score=70,
        break_conditions=["c1", "c2", "c3"],
    )


def test_60d_cap_under_60_days_no_trigger(conn):
    _make_thesis_active(conn, "th1", "2026-05-01T08:00:00Z")
    conn.commit()
    # +30 天还差 30 天到 60 天上限
    assert not check_60d_cap(conn, "th1", "2026-05-31T08:00:00Z")


def test_60d_cap_at_60_days_triggers(conn):
    _make_thesis_active(conn, "th1", "2026-05-01T08:00:00Z")
    conn.commit()
    # 5-1 + 60 天 = 6-30
    assert check_60d_cap(conn, "th1", "2026-06-30T08:00:00Z")


def test_60d_cap_already_marked_no_trigger(conn):
    _make_thesis_active(conn, "th1", "2026-05-01T08:00:00Z")
    conn.commit()
    n = mark_60d_capped(conn, "th1")
    conn.commit()
    assert n == 1
    # 已标记 → 不再触发
    assert not check_60d_cap(conn, "th1", "2026-08-01T08:00:00Z")


def test_60d_cap_closed_thesis_no_trigger(conn):
    _make_thesis_active(conn, "th1", "2026-05-01T08:00:00Z")
    conn.execute("UPDATE theses SET status='closed_profit' WHERE thesis_id='th1'")
    conn.commit()
    assert not check_60d_cap(conn, "th1", "2026-08-01T08:00:00Z")


def test_60d_cap_unknown_thesis_no_trigger(conn):
    assert not check_60d_cap(conn, "missing", "2026-08-01T08:00:00Z")


def test_mark_60d_capped_persists_field(conn):
    _make_thesis_active(conn, "th1", "2026-05-01T08:00:00Z")
    conn.commit()
    mark_60d_capped(conn, "th1")
    conn.commit()
    row = conn.execute(
        "SELECT is_60d_capped, status, lifecycle_stage FROM theses WHERE thesis_id='th1'"
    ).fetchone()
    assert row["is_60d_capped"] == 1
    # D4=b:lifecycle_stage 维持 active 不进 closed
    assert row["status"] == "active"
    assert row["lifecycle_stage"] == "planned"  # 未变更


# ============================================================
# Validator 20:连续 14 天熔断
# ============================================================

def test_consecutive_fuse_no_events(conn):
    r = check_consecutive_fuse(conn, "2026-05-10T08:00:00Z")
    assert r["fuse_count_90d"] == 0
    assert not r["triggers_review_pending"]


def test_consecutive_fuse_one_no_trigger(conn):
    record_14d_fuse_triggered(conn, "2026-04-15T08:00:00Z",
                              fuse_subtype="thesis_cycle")
    conn.commit()
    r = check_consecutive_fuse(conn, "2026-05-10T08:00:00Z")
    assert r["fuse_count_90d"] == 1
    assert not r["triggers_review_pending"]


def test_consecutive_fuse_two_triggers_review_pending(conn):
    """90 天内 2 次 14d_fuse → triggers review_pending。"""
    record_14d_fuse_triggered(conn, "2026-03-15T08:00:00Z",
                              fuse_subtype="thesis_cycle")
    record_14d_fuse_triggered(conn, "2026-04-25T08:00:00Z",
                              fuse_subtype="channel_c")
    conn.commit()
    r = check_consecutive_fuse(conn, "2026-05-10T08:00:00Z")
    assert r["fuse_count_90d"] == 2
    assert r["triggers_review_pending"]
    assert r["latest_fuse_at_utc"] == "2026-04-25T08:00:00Z"


def test_consecutive_fuse_old_events_excluded(conn):
    """超过 90 天的熔断不计入。"""
    record_14d_fuse_triggered(conn, "2026-01-01T08:00:00Z",
                              fuse_subtype="thesis_cycle")
    record_14d_fuse_triggered(conn, "2026-04-25T08:00:00Z",
                              fuse_subtype="channel_c")
    conn.commit()
    # now=5-10,5-10-90d=2-9;1-1 在窗口外
    r = check_consecutive_fuse(conn, "2026-05-10T08:00:00Z")
    assert r["fuse_count_90d"] == 1
    assert not r["triggers_review_pending"]
