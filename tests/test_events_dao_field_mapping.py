"""tests/test_events_dao_field_mapping.py — Sprint 2.6-D 修复验证。

EventsCalendarDAO.get_upcoming_within_hours 必须把 DB 列 'event_name' 同步映射到
'name' 字段,因为 event_risk.py 读 ev.get("name", "unknown") — 不映射会全部显示
"unknown",生产端 contributing_events 失真。
"""

from __future__ import annotations

import sqlite3

import pytest

from src.data.storage.dao import EventsCalendarDAO


@pytest.fixture
def db_with_one_event():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE events_calendar (
            event_id          TEXT PRIMARY KEY,
            date              TEXT NOT NULL,
            timezone          TEXT NOT NULL
                              CHECK (timezone IN ('America/New_York', 'UTC')),
            local_time        TEXT,
            utc_trigger_time  TEXT,
            event_type        TEXT NOT NULL,
            event_name        TEXT NOT NULL,
            impact_level      INTEGER CHECK (impact_level BETWEEN 1 AND 5),
            notes             TEXT
        )
    """)
    conn.execute(
        "INSERT INTO events_calendar (event_id, date, timezone, local_time, "
        "utc_trigger_time, event_type, event_name, impact_level, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "fomc_test", "2026-04-29", "America/New_York", "14:00",
            "2026-04-29T18:00:00Z", "fomc", "Test FOMC", 5, None,
        ),
    )
    conn.commit()
    yield conn
    conn.close()


def test_get_upcoming_maps_event_name_to_name(db_with_one_event):
    """name 字段必须出现且与 event_name 一致(event_risk.py 期望读 name)。"""
    events = EventsCalendarDAO.get_upcoming_within_hours(
        db_with_one_event,
        hours=72,
        now_utc="2026-04-28T06:00:00Z",
    )
    assert len(events) == 1
    ev = events[0]
    assert "event_name" in ev
    assert "name" in ev
    assert ev["name"] == ev["event_name"] == "Test FOMC"
