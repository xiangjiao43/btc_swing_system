"""tests/test_alerts_dao.py — Sprint 1.10-J commit 7 单测。

覆盖 AlertsDAO 重构(替代 4 处裸 INSERT)+ events_calendar.triggered_at_utc
条件 ALTER 幂等性。
"""
from __future__ import annotations

import sqlite3

import pytest

from src.data.storage.dao import AlertsDAO


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    with open("src/data/storage/schema.sql", encoding="utf-8") as f:
        c.executescript(f.read())
    yield c
    c.close()


# ============================================================
# AlertsDAO.insert_alert
# ============================================================

def test_insert_alert_returns_id(conn):
    aid = AlertsDAO.insert_alert(
        conn, alert_type="pre_flight_degraded", severity="warning",
        message="test message", raised_at_utc="2026-05-04T08:00:00Z",
    )
    conn.commit()
    assert aid > 0


def test_insert_alert_writes_all_fields(conn):
    AlertsDAO.insert_alert(
        conn, alert_type="overly_conservative", severity="critical",
        message="60d 无 thesis", raised_at_utc="2026-05-04T16:00:00Z",
        related_run_id="r_test_xyz",
    )
    conn.commit()
    row = conn.execute(
        "SELECT alert_type, severity, message, raised_at_utc, related_run_id "
        "FROM alerts WHERE alert_type = ?",
        ("overly_conservative",),
    ).fetchone()
    assert row is not None
    assert row["severity"] == "critical"
    assert row["message"] == "60d 无 thesis"
    assert row["raised_at_utc"] == "2026-05-04T16:00:00Z"
    assert row["related_run_id"] == "r_test_xyz"


def test_insert_alert_default_related_run_id_null(conn):
    """无 related_run_id → DB 写 NULL。"""
    AlertsDAO.insert_alert(
        conn, alert_type="weekly_review", severity="info",
        message="weekly done", raised_at_utc="2026-05-04T22:00:00Z",
    )
    conn.commit()
    row = conn.execute(
        "SELECT related_run_id FROM alerts WHERE alert_type = ?",
        ("weekly_review",),
    ).fetchone()
    assert row["related_run_id"] is None


# ============================================================
# Sprint 1.10-K-B commit 5:AlertsDAO.mark_acknowledged / mark_notified
# ============================================================

def test_mark_acknowledged_happy_path(conn):
    """mark_acknowledged 把 acknowledged 列从 0 → 1,返回 rowcount=1。"""
    aid = AlertsDAO.insert_alert(
        conn, alert_type="t", severity="warning", message="x",
        raised_at_utc="2026-05-04T12:00:00Z",
    )
    conn.commit()
    # 初始 acknowledged=0
    row = conn.execute(
        "SELECT acknowledged FROM alerts WHERE id=?", (aid,),
    ).fetchone()
    assert row["acknowledged"] == 0
    # mark
    affected = AlertsDAO.mark_acknowledged(conn, aid)
    conn.commit()
    assert affected == 1
    row = conn.execute(
        "SELECT acknowledged FROM alerts WHERE id=?", (aid,),
    ).fetchone()
    assert row["acknowledged"] == 1


def test_mark_acknowledged_nonexistent_id_returns_zero(conn):
    """不存在的 alert_id → rowcount=0,不抛异常。"""
    affected = AlertsDAO.mark_acknowledged(conn, 999999)
    conn.commit()
    assert affected == 0


def test_mark_acknowledged_idempotent(conn):
    """二次调用不报错 + acknowledged 仍 1。"""
    aid = AlertsDAO.insert_alert(
        conn, alert_type="t", severity="info", message="x",
        raised_at_utc="2026-05-04T12:00:00Z",
    )
    conn.commit()
    AlertsDAO.mark_acknowledged(conn, aid)
    affected2 = AlertsDAO.mark_acknowledged(conn, aid)
    conn.commit()
    # 第二次仍 rowcount=1(UPDATE 总是匹配那行;值已 1 不变)
    assert affected2 == 1
    row = conn.execute(
        "SELECT acknowledged FROM alerts WHERE id=?", (aid,),
    ).fetchone()
    assert row["acknowledged"] == 1


def test_mark_notified_happy_path(conn):
    """mark_notified 把 notification_sent 列从 0 → 1,返回 rowcount=1。"""
    aid = AlertsDAO.insert_alert(
        conn, alert_type="t", severity="critical", message="y",
        raised_at_utc="2026-05-04T12:00:00Z",
    )
    conn.commit()
    row = conn.execute(
        "SELECT notification_sent FROM alerts WHERE id=?", (aid,),
    ).fetchone()
    assert row["notification_sent"] == 0
    affected = AlertsDAO.mark_notified(conn, aid)
    conn.commit()
    assert affected == 1
    row = conn.execute(
        "SELECT notification_sent FROM alerts WHERE id=?", (aid,),
    ).fetchone()
    assert row["notification_sent"] == 1


def test_mark_notified_nonexistent_id_returns_zero(conn):
    """不存在的 alert_id → rowcount=0,不抛异常。"""
    affected = AlertsDAO.mark_notified(conn, 999999)
    conn.commit()
    assert affected == 0


def test_mark_acknowledged_and_notified_independent(conn):
    """两个标记独立:mark_acknowledged 不影响 notification_sent,反之亦然。"""
    aid = AlertsDAO.insert_alert(
        conn, alert_type="t", severity="warning", message="z",
        raised_at_utc="2026-05-04T12:00:00Z",
    )
    conn.commit()
    AlertsDAO.mark_acknowledged(conn, aid)
    conn.commit()
    row = conn.execute(
        "SELECT acknowledged, notification_sent FROM alerts WHERE id=?", (aid,),
    ).fetchone()
    assert row["acknowledged"] == 1
    assert row["notification_sent"] == 0  # 未动


# ============================================================
# AlertsDAO.normalize_severity
# ============================================================

@pytest.mark.parametrize("input_sev,expected", [
    ("critical", "critical"),
    ("warning", "warning"),
    ("info", "info"),
    ("invalid", "info"),
    ("CRITICAL", "info"),  # case sensitive
    ("", "info"),
    (None, "info"),
])
def test_normalize_severity(input_sev, expected):
    assert AlertsDAO.normalize_severity(input_sev) == expected


# ============================================================
# AlertsDAO.get_recent
# ============================================================

def test_get_recent_returns_within_window(conn):
    """24h 内 alerts 全返,超窗口排除。"""
    from datetime import datetime, timedelta, timezone
    now = datetime(2026, 5, 4, 16, 0, 0, tzinfo=timezone.utc)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    # 1h 前
    AlertsDAO.insert_alert(
        conn, alert_type="t1", severity="info", message="recent",
        raised_at_utc=(now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    # 30h 前(超 24h 窗)
    AlertsDAO.insert_alert(
        conn, alert_type="t1", severity="info", message="old",
        raised_at_utc=(now - timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    conn.commit()
    rows = AlertsDAO.get_recent(conn, within_hours=24, now_utc=now_iso)
    assert len(rows) == 1
    assert rows[0]["message"] == "recent"


def test_get_recent_filters_alert_type(conn):
    AlertsDAO.insert_alert(
        conn, alert_type="weekly_review", severity="info", message="x",
        raised_at_utc="2026-05-04T15:00:00Z",
    )
    AlertsDAO.insert_alert(
        conn, alert_type="overly_conservative", severity="warning", message="y",
        raised_at_utc="2026-05-04T15:00:00Z",
    )
    conn.commit()
    rows = AlertsDAO.get_recent(
        conn, within_hours=24, alert_type="weekly_review",
        now_utc="2026-05-04T16:00:00Z",
    )
    assert len(rows) == 1
    assert rows[0]["alert_type"] == "weekly_review"


def test_get_recent_filters_severity(conn):
    AlertsDAO.insert_alert(
        conn, alert_type="t", severity="critical", message="x",
        raised_at_utc="2026-05-04T15:00:00Z",
    )
    AlertsDAO.insert_alert(
        conn, alert_type="t", severity="info", message="y",
        raised_at_utc="2026-05-04T15:00:00Z",
    )
    conn.commit()
    rows = AlertsDAO.get_recent(
        conn, within_hours=24, severity="critical",
        now_utc="2026-05-04T16:00:00Z",
    )
    assert len(rows) == 1
    assert rows[0]["severity"] == "critical"


def test_get_recent_empty_table(conn):
    rows = AlertsDAO.get_recent(
        conn, within_hours=24, now_utc="2026-05-04T16:00:00Z",
    )
    assert rows == []


def test_get_recent_orders_desc(conn):
    """按 raised_at_utc DESC(最新在前)。"""
    for i, hr in enumerate([5, 1, 3]):
        AlertsDAO.insert_alert(
            conn, alert_type="ord", severity="info",
            message=f"alert_{i}",
            raised_at_utc=f"2026-05-04T{16-hr:02d}:00:00Z",
        )
    conn.commit()
    rows = AlertsDAO.get_recent(
        conn, within_hours=24, now_utc="2026-05-04T17:00:00Z",
    )
    # 顺序:1h ago(15:00) > 3h ago(13:00) > 5h ago(11:00)
    assert rows[0]["raised_at_utc"] == "2026-05-04T15:00:00Z"
    assert rows[1]["raised_at_utc"] == "2026-05-04T13:00:00Z"
    assert rows[2]["raised_at_utc"] == "2026-05-04T11:00:00Z"


# ============================================================
# init_v14_tables.apply_migration:events_calendar.triggered_at_utc 条件 ALTER
# ============================================================

def test_apply_migration_adds_triggered_at_utc_when_missing():
    """模拟生产 DB 缺 triggered_at_utc 列 → apply_migration 加列。

    用完整 schema 但手动 DROP triggered_at_utc 列(via 重建表)。
    """
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    with open("src/data/storage/schema.sql", encoding="utf-8") as f:
        c.executescript(f.read())
    # 模拟 2.7-D 之前的 schema:DROP triggered_at_utc 列
    # SQLite 不支持 DROP COLUMN 直接,需 CREATE TABLE 复制
    c.execute(
        "CREATE TABLE events_calendar_old AS SELECT "
        "event_id, date, timezone, local_time, utc_trigger_time, "
        "event_type, event_name, impact_level, notes FROM events_calendar"
    )
    c.execute("DROP TABLE events_calendar")
    c.execute(
        "ALTER TABLE events_calendar_old RENAME TO events_calendar"
    )
    cols = [r[1] for r in c.execute(
        "PRAGMA table_info(events_calendar)").fetchall()]
    assert "triggered_at_utc" not in cols

    # apply_migration 应该 detect 缺列 + ALTER 加上
    from scripts.init_v14_tables import apply_migration
    apply_migration(c)
    c.commit()

    cols2 = [r[1] for r in c.execute(
        "PRAGMA table_info(events_calendar)").fetchall()]
    assert "triggered_at_utc" in cols2
    c.close()


def test_apply_migration_idempotent_when_column_exists():
    """已有 triggered_at_utc 列 → apply_migration 跳过,不抛异常。"""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    with open("src/data/storage/schema.sql", encoding="utf-8") as f:
        c.executescript(f.read())
    # apply_migration 第一次
    from scripts.init_v14_tables import apply_migration
    apply_migration(c)
    c.commit()
    # apply_migration 第二次(应幂等不抛)
    apply_migration(c)
    c.commit()
    cols = [r[1] for r in c.execute(
        "PRAGMA table_info(events_calendar)").fetchall()]
    assert "triggered_at_utc" in cols
    # 列只有一个(没重复)
    assert cols.count("triggered_at_utc") == 1
    c.close()


# ============================================================
# 4 处裸 INSERT 调用方都通过 AlertsDAO(集成验证)
# ============================================================

def test_conservative_monitor_uses_alerts_dao(conn):
    """ConservativeMonitor._write_alert 调 AlertsDAO.insert_alert。"""
    # 应用 v1.4 migrations 让 theses / system_states 表存在
    from scripts.init_v14_tables import apply_migration
    apply_migration(conn)
    # mock thesis 70 天前(critical)
    from datetime import datetime, timedelta, timezone
    long_ago = (datetime(2026, 5, 4, tzinfo=timezone.utc)
                 - timedelta(days=70))
    conn.execute(
        "INSERT INTO theses (thesis_id, created_at_run_id, created_at_utc, "
        "direction, core_logic, confidence_score, break_conditions, "
        "lifecycle_stage, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("t_old", "r", long_ago.strftime("%Y-%m-%dT%H:%M:%SZ"),
         "long", "test", 70, "[]", "closed", "closed_loss"),
    )
    conn.commit()

    from src.strategy.conservative_monitor import ConservativeMonitor
    res = ConservativeMonitor.check_and_alert(
        conn, now_utc=datetime(2026, 5, 4, 16, 0, tzinfo=timezone.utc),
    )
    conn.commit()
    assert res["alert_written"] is True

    # alerts 表里有新 row(via AlertsDAO)
    rows = AlertsDAO.get_recent(conn, within_hours=1, now_utc="2026-05-04T16:00:00Z")
    assert len(rows) >= 1
    assert any(r["alert_type"] == "overly_conservative" for r in rows)
