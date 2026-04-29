"""tests/test_events_seeder_orphan_cleanup.py — Sprint 1.5d.1 §X 孤儿清理。

§Z 真 init_db + 真 EventsSeeder.upsert_to_db,断言:
- 同 (event_type, date) 但 event_id 改名 → 旧 id 被 DELETE
- 不在新 seed 的 event_type 不算孤儿(只比较 type+date 命中的)
- 第一次/第二次 seed 都幂等
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.data.collectors.events_seeder import EventsSeeder
from src.data.storage.connection import init_db


def _row_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM events_calendar").fetchone()[0]


@pytest.fixture
def db_path():
    tmp = Path(tempfile.mkdtemp()) / "orphan.db"
    init_db(db_path=tmp, verbose=False)
    return tmp


def _seed(events: list[dict]) -> EventsSeeder:
    """构造内存 seeder(直接传 events 跳过 load_seed)。"""
    return EventsSeeder()


# ============================================================
# 孤儿清理:event_id 重命名
# ============================================================

def test_orphan_removal_on_event_id_rename(db_path):
    """同 (type='fomc', date='2026-01-28') 但 event_id 不同 → 旧 id 删,
    新 id INSERT。"""
    conn = sqlite3.connect(db_path)
    seeder = _seed([])
    try:
        # 第一次 seed:event_id="fomc_old_id"
        old_seed = [{
            "event_id": "fomc_old_id",
            "date": "2026-01-28",
            "timezone": "America/New_York",
            "local_time": "14:00",
            "utc_trigger_time": "2026-01-28T19:00:00Z",
            "event_type": "fomc",
            "event_name": "FOMC v1",
            "impact_level": 5,
            "notes": "",
        }]
        r1 = seeder.upsert_to_db(conn, old_seed)
        assert r1["valid"] == 1
        assert r1["orphans_removed"] == 0  # 第一次没旧记录
        assert _row_count(conn) == 1

        # 第二次 seed:event_id 改名为 "fomc_new_id",同 type + date
        new_seed = [{
            "event_id": "fomc_new_id",
            "date": "2026-01-28",
            "timezone": "America/New_York",
            "local_time": "14:00",
            "utc_trigger_time": "2026-01-28T19:00:00Z",
            "event_type": "fomc",
            "event_name": "FOMC v2",
            "impact_level": 5,
            "notes": "Renamed",
        }]
        r2 = seeder.upsert_to_db(conn, new_seed)
        # 关键反退化:旧 fomc_old_id 应已删,只剩 fomc_new_id
        assert r2["orphans_removed"] == 1
        assert _row_count(conn) == 1
        ids = [r[0] for r in conn.execute(
            "SELECT event_id FROM events_calendar"
        ).fetchall()]
        assert ids == ["fomc_new_id"]
    finally:
        conn.close()


def test_no_orphan_for_unrelated_records(db_path):
    """旧表 fomc + cpi 各 1 条;新 seed 只含 cpi(不同 date)→
    fomc 那条不被清理(不同 type 不算孤儿)。"""
    conn = sqlite3.connect(db_path)
    seeder = _seed([])
    try:
        # 先 seed 两类
        first = [
            {"event_id": "fomc_1", "date": "2026-01-28",
             "timezone": "America/New_York", "local_time": "14:00",
             "utc_trigger_time": "2026-01-28T19:00:00Z",
             "event_type": "fomc", "event_name": "FOMC",
             "impact_level": 5, "notes": ""},
            {"event_id": "cpi_1", "date": "2026-02-13",
             "timezone": "America/New_York", "local_time": "08:30",
             "utc_trigger_time": "2026-02-13T13:30:00Z",
             "event_type": "cpi", "event_name": "CPI",
             "impact_level": 4, "notes": ""},
        ]
        seeder.upsert_to_db(conn, first)
        assert _row_count(conn) == 2

        # 第二次 seed 只重 seed cpi(不同 date,不命中 fomc 那行)
        second = [{
            "event_id": "cpi_1", "date": "2026-02-13",
            "timezone": "America/New_York", "local_time": "08:30",
            "utc_trigger_time": "2026-02-13T13:30:00Z",
            "event_type": "cpi", "event_name": "CPI v2",
            "impact_level": 4, "notes": "",
        }]
        r = seeder.upsert_to_db(conn, second)
        # fomc 那条应保留(不算孤儿,没在新 seed 的 type+date 命中)
        assert r["orphans_removed"] == 0
        assert _row_count(conn) == 2
    finally:
        conn.close()


def test_orphan_only_within_same_type_date(db_path):
    """fomc 改 id 同 date,cpi 不变 id → 只 fomc 旧 id 删,cpi 不动。"""
    conn = sqlite3.connect(db_path)
    seeder = _seed([])
    try:
        first = [
            {"event_id": "fomc_old", "date": "2026-01-28",
             "timezone": "America/New_York", "local_time": "14:00",
             "utc_trigger_time": "2026-01-28T19:00:00Z",
             "event_type": "fomc", "event_name": "FOMC",
             "impact_level": 5, "notes": ""},
            {"event_id": "cpi_stable", "date": "2026-02-13",
             "timezone": "America/New_York", "local_time": "08:30",
             "utc_trigger_time": "2026-02-13T13:30:00Z",
             "event_type": "cpi", "event_name": "CPI",
             "impact_level": 4, "notes": ""},
        ]
        seeder.upsert_to_db(conn, first)
        assert _row_count(conn) == 2

        second = [
            {"event_id": "fomc_new", "date": "2026-01-28",
             "timezone": "America/New_York", "local_time": "14:00",
             "utc_trigger_time": "2026-01-28T19:00:00Z",
             "event_type": "fomc", "event_name": "FOMC v2",
             "impact_level": 5, "notes": ""},
            {"event_id": "cpi_stable", "date": "2026-02-13",
             "timezone": "America/New_York", "local_time": "08:30",
             "utc_trigger_time": "2026-02-13T13:30:00Z",
             "event_type": "cpi", "event_name": "CPI v2",
             "impact_level": 4, "notes": ""},
        ]
        r = seeder.upsert_to_db(conn, second)
        assert r["orphans_removed"] == 1  # 只有 fomc_old
        assert _row_count(conn) == 2
        ids = sorted(r[0] for r in conn.execute(
            "SELECT event_id FROM events_calendar"
        ).fetchall())
        assert ids == ["cpi_stable", "fomc_new"]
    finally:
        conn.close()


def test_idempotent_no_orphans_on_repeat(db_path):
    """同样的 seed 跑两次,第二次 orphans_removed=0。"""
    conn = sqlite3.connect(db_path)
    seeder = _seed([])
    try:
        events = [{
            "event_id": "fomc_1", "date": "2026-01-28",
            "timezone": "America/New_York", "local_time": "14:00",
            "utc_trigger_time": "2026-01-28T19:00:00Z",
            "event_type": "fomc", "event_name": "FOMC",
            "impact_level": 5, "notes": "",
        }]
        seeder.upsert_to_db(conn, events)
        r = seeder.upsert_to_db(conn, events)
        assert r["orphans_removed"] == 0
        assert _row_count(conn) == 1
    finally:
        conn.close()


# ============================================================
# 真生产场景:options_expiry 重命名(1.5d 翻车场景)
# ============================================================

def test_orphan_cleanup_options_expiry_rename(db_path):
    """模拟 1.5d 真翻车:options_expiry_2026_03 改名 options_expiry_major_2026_03。
    同 type='options_expiry_major' + date='2026-03-27' → 旧 id 应清。"""
    conn = sqlite3.connect(db_path)
    seeder = _seed([])
    try:
        # 1.5c 旧 id
        old = [{
            "event_id": "options_expiry_2026_03",
            "date": "2026-03-27",
            "timezone": "UTC", "local_time": "08:00",
            "utc_trigger_time": "2026-03-27T08:00:00Z",
            "event_type": "options_expiry_major",
            "event_name": "BTC options expiry March",
            "impact_level": 3, "notes": "",
        }]
        seeder.upsert_to_db(conn, old)
        assert _row_count(conn) == 1

        # 1.5d 新 id
        new = [{
            "event_id": "options_expiry_major_2026_03",
            "date": "2026-03-27",
            "timezone": "UTC", "local_time": "08:00",
            "utc_trigger_time": "2026-03-27T08:00:00Z",
            "event_type": "options_expiry_major",
            "event_name": "BTC quarterly options expiry March",
            "impact_level": 4, "notes": "Q1 quarterly expiry",
        }]
        r = seeder.upsert_to_db(conn, new)
        assert r["orphans_removed"] == 1
        # 现在只剩 1 条新 id
        assert _row_count(conn) == 1
        ids = [r[0] for r in conn.execute(
            "SELECT event_id FROM events_calendar"
        ).fetchall()]
        assert ids == ["options_expiry_major_2026_03"]
    finally:
        conn.close()
