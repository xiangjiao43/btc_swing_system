"""tests/test_events_seeder.py — Sprint 2.6-D EventsSeeder 覆盖。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.data.collectors.events_seeder import (
    EventsSeeder,
    EventsSeederError,
    seed_events,
)


@pytest.fixture
def in_memory_db():
    conn = sqlite3.connect(":memory:")
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
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def seed_file(tmp_path):
    seed_data = {
        "_meta": {"version": "test"},
        "events": [
            {
                "event_id": "fomc_test_1",
                "date": "2026-04-29",
                "timezone": "America/New_York",
                "local_time": "14:00",
                "utc_trigger_time": "2026-04-29T18:00:00Z",
                "event_type": "fomc",
                "event_name": "Test FOMC",
                "impact_level": 5,
                "notes": "test",
            },
            {
                "event_id": "cpi_test_1",
                "date": "2026-05-13",
                "timezone": "America/New_York",
                "local_time": "08:30",
                "utc_trigger_time": "2026-05-13T12:30:00Z",
                "event_type": "cpi",
                "event_name": "Test CPI",
                "impact_level": 4,
                "notes": "test",
            },
        ],
    }
    p = tmp_path / "events_test.json"
    p.write_text(json.dumps(seed_data))
    return p


# ============================================================
# Load seed
# ============================================================

def test_load_seed_success(seed_file):
    seeder = EventsSeeder(seed_path=seed_file)
    events = seeder.load_seed()
    assert len(events) == 2
    assert events[0]["event_id"] == "fomc_test_1"
    assert events[1]["event_id"] == "cpi_test_1"


def test_load_seed_missing_file(tmp_path):
    fake_path = tmp_path / "does_not_exist.json"
    seeder = EventsSeeder(seed_path=fake_path)
    with pytest.raises(EventsSeederError, match="not found"):
        seeder.load_seed()


def test_load_seed_invalid_json(tmp_path):
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("{not valid json")
    seeder = EventsSeeder(seed_path=bad_file)
    with pytest.raises(EventsSeederError, match="Invalid JSON"):
        seeder.load_seed()


def test_load_seed_events_field_not_list(tmp_path):
    bad_file = tmp_path / "bad_shape.json"
    bad_file.write_text(json.dumps({"events": {"oops": "not a list"}}))
    seeder = EventsSeeder(seed_path=bad_file)
    with pytest.raises(EventsSeederError, match="must be a list"):
        seeder.load_seed()


# ============================================================
# Upsert to DB
# ============================================================

def test_upsert_initial_insert(in_memory_db, seed_file):
    seeder = EventsSeeder(seed_path=seed_file)
    stats = seeder.run(in_memory_db)
    assert stats["valid"] == 2
    assert stats["skipped"] == 0

    cur = in_memory_db.execute("SELECT COUNT(*) FROM events_calendar")
    assert cur.fetchone()[0] == 2


def test_upsert_idempotent(in_memory_db, seed_file):
    """跑两次,行数仍是 2(同 event_id 被 ON CONFLICT 覆盖)。"""
    seeder = EventsSeeder(seed_path=seed_file)
    seeder.run(in_memory_db)
    seeder.run(in_memory_db)

    cur = in_memory_db.execute("SELECT COUNT(*) FROM events_calendar")
    assert cur.fetchone()[0] == 2


def test_upsert_skips_event_without_event_id(in_memory_db, tmp_path):
    seed_data = {"events": [
        {"date": "2026-04-29", "timezone": "UTC",
         "event_type": "fomc", "event_name": "no id",
         "impact_level": 5},
        {"event_id": "ok_1", "date": "2026-04-29", "timezone": "UTC",
         "utc_trigger_time": "2026-04-29T18:00:00Z",
         "event_type": "fomc", "event_name": "ok", "impact_level": 5},
    ]}
    p = tmp_path / "mixed.json"
    p.write_text(json.dumps(seed_data))
    stats = EventsSeeder(seed_path=p).run(in_memory_db)
    assert stats["valid"] == 1
    assert stats["skipped"] == 1


def test_upsert_skips_invalid_timezone(in_memory_db, tmp_path):
    """timezone 不在 schema CHECK 白名单的事件被 skip,不抛 IntegrityError。"""
    seed_data = {"events": [
        {"event_id": "bad_tz", "date": "2026-04-29", "timezone": "Asia/Shanghai",
         "utc_trigger_time": "2026-04-29T18:00:00Z",
         "event_type": "fomc", "event_name": "bad tz", "impact_level": 5},
    ]}
    p = tmp_path / "bad_tz.json"
    p.write_text(json.dumps(seed_data))
    stats = EventsSeeder(seed_path=p).run(in_memory_db)
    assert stats["valid"] == 0
    assert stats["skipped"] == 1


# ============================================================
# Convenience function
# ============================================================

def test_seed_events_convenience(in_memory_db, seed_file):
    stats = seed_events(in_memory_db, seed_file)
    assert stats["valid"] == 2


# ============================================================
# Real seed file works against schema
# ============================================================

def test_real_seed_file_loads_into_real_schema(in_memory_db):
    """data/seeds/events_2026.json 能 100% load 进 schema(无 CHECK 失败)。"""
    project_root = Path(__file__).resolve().parent.parent
    real_seed = project_root / "data" / "seeds" / "events_2026.json"
    assert real_seed.exists(), "seed file should ship with repo"
    stats = seed_events(in_memory_db, real_seed)
    assert stats["valid"] >= 10  # 至少 8 FOMC + 1 NFP + 1 CPI
    assert stats["skipped"] == 0
