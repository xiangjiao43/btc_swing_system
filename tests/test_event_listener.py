"""tests/test_event_listener.py — Sprint 2.7-D 4 类 event 触发逻辑。

§Z 端到端:每个测试 fixture 真 SQLite + 真插入数据 + 真调用 check_and_trigger_events,
断言:
  - 返回的 event_type 列表精确
  - event_throttle 表写入 last_triggered_at_utc(invalidation/price)
  - events_calendar.triggered_at_utc 写入(macro)
  - 节流场景返回空 list
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.data.storage.connection import init_db
from src.data.storage.dao import (
    BTCKlinesDAO, EventRow, EventsCalendarDAO, KlineRow,
)
from src.scheduler.event_listener import (
    _is_throttled, _record_trigger,
    check_and_trigger_events,
)


_NOW = datetime(2026, 4, 28, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def db_conn():
    tmp = Path(tempfile.mkdtemp()) / "ev.db"
    init_db(db_path=tmp, verbose=False)
    # 应用 2.7-D 迁移(给新建的测试 DB 加 event_throttle + triggered_at_utc 列)
    from scripts.migrate_2_7_d import apply_migration
    conn = sqlite3.connect(tmp)
    conn.row_factory = sqlite3.Row
    apply_migration(conn)
    yield conn
    conn.close()


# ============================================================
# Throttle helpers
# ============================================================

def test_record_then_is_throttled(db_conn):
    _record_trigger(db_conn, "event_invalidation", now=_NOW)
    db_conn.commit()
    assert _is_throttled(db_conn, "event_invalidation",
                          cooldown_sec=7200, now=_NOW + timedelta(minutes=30))


def test_not_throttled_after_cooldown(db_conn):
    _record_trigger(db_conn, "event_invalidation",
                    now=_NOW - timedelta(hours=3))
    db_conn.commit()
    assert not _is_throttled(db_conn, "event_invalidation",
                              cooldown_sec=7200, now=_NOW)


def test_no_throttle_record_means_not_throttled(db_conn):
    assert not _is_throttled(db_conn, "event_invalidation", now=_NOW)


# ============================================================
# Helpers to seed data
# ============================================================

def _seed_run_with_lifecycle(
    conn: sqlite3.Connection,
    *,
    direction: str,
    invalidation_price: float,
    run_trigger: str = "scheduled",
    when: datetime = _NOW - timedelta(hours=4),
) -> str:
    """插一条 strategy_runs 行,lifecycle.direction + L4 hard_invalidation_levels。"""
    state = {
        "lifecycle": {"direction": direction},
        "evidence_reports": {
            "layer_4": {"hard_invalidation_levels": [invalidation_price]}
        },
    }
    run_id = f"test-{direction}-{int(when.timestamp())}"
    conn.execute(
        "INSERT INTO strategy_runs "
        "(run_id, generated_at_utc, generated_at_bjt, action_state, "
        " full_state_json, run_trigger) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, when.strftime("%Y-%m-%dT%H:%M:%SZ"),
         when.strftime("%Y-%m-%d %H:%M (BJT)"),
         "FLAT", json.dumps(state), run_trigger),
    )
    conn.commit()
    return run_id


def _seed_klines_1h(conn: sqlite3.Connection, ts_to_close: dict[str, float]):
    rows = [
        KlineRow(timeframe="1h", timestamp=ts,
                 open=close, high=close, low=close, close=close,
                 volume_btc=1.0)
        for ts, close in ts_to_close.items()
    ]
    BTCKlinesDAO.upsert_klines(conn, rows)
    conn.commit()


# ============================================================
# event_invalidation
# ============================================================

def test_event_invalidation_long_position_close_breach(db_conn):
    """long 仓 + 当前 close < invalidation 价 → 触发,event_throttle 被写入。"""
    _seed_run_with_lifecycle(db_conn, direction="long",
                              invalidation_price=50000.0)
    _seed_klines_1h(db_conn, {
        "2026-04-28T11:00:00Z": 49000.0,  # latest, below 50k
    })
    out = check_and_trigger_events(db_conn, now=_NOW)
    assert "event_invalidation" in out
    # event_throttle 行被写入
    row = db_conn.execute(
        "SELECT last_triggered_at_utc FROM event_throttle "
        "WHERE event_type='event_invalidation'"
    ).fetchone()
    assert row is not None


def test_event_invalidation_long_close_above_no_trigger(db_conn):
    """long 仓 + close 仍在 invalidation 之上 → 不触发。"""
    _seed_run_with_lifecycle(db_conn, direction="long",
                              invalidation_price=50000.0)
    _seed_klines_1h(db_conn, {"2026-04-28T11:00:00Z": 51000.0})
    out = check_and_trigger_events(db_conn, now=_NOW)
    assert "event_invalidation" not in out


def test_event_invalidation_short_position_close_breach(db_conn):
    """short 仓 + close 突破上沿 → 触发。"""
    _seed_run_with_lifecycle(db_conn, direction="short",
                              invalidation_price=60000.0)
    _seed_klines_1h(db_conn, {"2026-04-28T11:00:00Z": 61000.0})
    out = check_and_trigger_events(db_conn, now=_NOW)
    assert "event_invalidation" in out


def test_event_invalidation_throttled(db_conn):
    """2h 内已触发过 → 返回空。"""
    _seed_run_with_lifecycle(db_conn, direction="long",
                              invalidation_price=50000.0)
    _seed_klines_1h(db_conn, {"2026-04-28T11:00:00Z": 49000.0})
    _record_trigger(db_conn, "event_invalidation",
                    now=_NOW - timedelta(minutes=30))
    db_conn.commit()
    out = check_and_trigger_events(db_conn, now=_NOW)
    assert "event_invalidation" not in out


def test_event_invalidation_no_lifecycle_direction(db_conn):
    """无 lifecycle.direction → 跳过。"""
    state = {"lifecycle": {}, "evidence_reports": {"layer_4": {}}}
    db_conn.execute(
        "INSERT INTO strategy_runs (run_id, generated_at_utc, generated_at_bjt, "
        "action_state, full_state_json, run_trigger) VALUES (?, ?, ?, ?, ?, ?)",
        ("flat-run", _NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
         _NOW.strftime("%Y-%m-%d %H:%M (BJT)"),
         "FLAT", json.dumps(state), "scheduled"),
    )
    _seed_klines_1h(db_conn, {"2026-04-28T11:00:00Z": 49000.0})
    db_conn.commit()
    out = check_and_trigger_events(db_conn, now=_NOW)
    assert "event_invalidation" not in out


# ============================================================
# event_price
# ============================================================

def test_event_price_3pct_drop_triggers(db_conn):
    """24h 前 60000 → 当前 58000(< -3.3%)→ 触发。"""
    _seed_klines_1h(db_conn, {
        "2026-04-27T11:00:00Z": 60000.0,  # 24h ago
        "2026-04-28T11:00:00Z": 58000.0,  # latest, -3.33%
    })
    out = check_and_trigger_events(db_conn, now=_NOW)
    assert "event_price" in out


def test_event_price_3pct_rise_triggers(db_conn):
    _seed_klines_1h(db_conn, {
        "2026-04-27T11:00:00Z": 50000.0,
        "2026-04-28T11:00:00Z": 51800.0,  # +3.6%
    })
    out = check_and_trigger_events(db_conn, now=_NOW)
    assert "event_price" in out


def test_event_price_under_3pct_no_trigger(db_conn):
    _seed_klines_1h(db_conn, {
        "2026-04-27T11:00:00Z": 50000.0,
        "2026-04-28T11:00:00Z": 50500.0,  # +1%
    })
    out = check_and_trigger_events(db_conn, now=_NOW)
    assert "event_price" not in out


def test_event_price_recently_scheduled_run_skipped(db_conn):
    """30 min 内有 scheduled run → 跳过。"""
    _seed_klines_1h(db_conn, {
        "2026-04-27T11:00:00Z": 60000.0,
        "2026-04-28T11:00:00Z": 58000.0,
    })
    # 模拟 15 分钟前刚跑过 scheduled
    db_conn.execute(
        "INSERT INTO strategy_runs (run_id, generated_at_utc, generated_at_bjt, "
        "action_state, full_state_json, run_trigger) VALUES (?, ?, ?, ?, ?, ?)",
        ("recent-sched",
         (_NOW - timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%SZ"),
         (_NOW - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M (BJT)"),
         "FLAT", "{}", "scheduled"),
    )
    db_conn.commit()
    out = check_and_trigger_events(db_conn, now=_NOW)
    assert "event_price" not in out


def test_event_price_old_scheduled_run_does_not_skip(db_conn):
    """45 min 前的 scheduled run → 不跳过(只 30min 节流)。"""
    _seed_klines_1h(db_conn, {
        "2026-04-27T11:00:00Z": 60000.0,
        "2026-04-28T11:00:00Z": 58000.0,
    })
    db_conn.execute(
        "INSERT INTO strategy_runs (run_id, generated_at_utc, generated_at_bjt, "
        "action_state, full_state_json, run_trigger) VALUES (?, ?, ?, ?, ?, ?)",
        ("old-sched",
         (_NOW - timedelta(minutes=45)).strftime("%Y-%m-%dT%H:%M:%SZ"),
         (_NOW - timedelta(minutes=45)).strftime("%Y-%m-%d %H:%M (BJT)"),
         "FLAT", "{}", "scheduled"),
    )
    db_conn.commit()
    out = check_and_trigger_events(db_conn, now=_NOW)
    assert "event_price" in out


def test_event_price_throttled_no_double_trigger(db_conn):
    _seed_klines_1h(db_conn, {
        "2026-04-27T11:00:00Z": 60000.0,
        "2026-04-28T11:00:00Z": 58000.0,
    })
    _record_trigger(db_conn, "event_price",
                    now=_NOW - timedelta(minutes=30))
    db_conn.commit()
    out = check_and_trigger_events(db_conn, now=_NOW)
    assert "event_price" not in out


# ============================================================
# event_macro
# ============================================================

def test_event_macro_15min_window_hit(db_conn):
    """events_calendar 一行 utc_trigger=now-15min30s 落在窗口内 → 触发 + 写 triggered_at_utc。"""
    # 触发 15min30s 前 → 15min OFFSET 后,trigger_time 落在 [now-16min, now-15min) 内
    trigger_iso = (_NOW - timedelta(minutes=15, seconds=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    EventsCalendarDAO.upsert_events(db_conn, [
        EventRow(event_id="fomc_test", date="2026-04-28",
                 timezone="America/New_York", local_time="08:00",
                 utc_trigger_time=trigger_iso,
                 event_type="fomc", event_name="Test FOMC",
                 impact_level=5, notes=None),
    ])
    db_conn.commit()
    out = check_and_trigger_events(db_conn, now=_NOW)
    assert "event_macro" in out
    # triggered_at_utc 被写
    row = db_conn.execute(
        "SELECT triggered_at_utc FROM events_calendar WHERE event_id='fomc_test'"
    ).fetchone()
    assert row[0] is not None or row["triggered_at_utc"] is not None


def test_event_macro_already_triggered_no_double(db_conn):
    """triggered_at_utc 已写 → 不再触发。"""
    trigger_iso = (_NOW - timedelta(minutes=15, seconds=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    EventsCalendarDAO.upsert_events(db_conn, [
        EventRow(event_id="fomc_already", date="2026-04-28",
                 timezone="America/New_York", local_time="08:00",
                 utc_trigger_time=trigger_iso,
                 event_type="fomc", event_name="Already triggered",
                 impact_level=5, notes=None),
    ])
    db_conn.execute(
        "UPDATE events_calendar SET triggered_at_utc='2026-04-28T11:30:00Z' "
        "WHERE event_id='fomc_already'"
    )
    db_conn.commit()
    out = check_and_trigger_events(db_conn, now=_NOW)
    assert "event_macro" not in out


def test_event_macro_low_impact_skipped(db_conn):
    """impact_level=1 → 不触发。"""
    trigger_iso = (_NOW - timedelta(minutes=15, seconds=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    EventsCalendarDAO.upsert_events(db_conn, [
        EventRow(event_id="low_impact", date="2026-04-28",
                 timezone="America/New_York", local_time="08:00",
                 utc_trigger_time=trigger_iso,
                 event_type="other", event_name="low impact",
                 impact_level=1, notes=None),
    ])
    db_conn.commit()
    out = check_and_trigger_events(db_conn, now=_NOW)
    assert "event_macro" not in out


def test_event_macro_outside_window_no_trigger(db_conn):
    """utc_trigger_time 在 1 小时前(超出 15-16min 窗口) → 不触发。"""
    trigger_iso = (_NOW - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    EventsCalendarDAO.upsert_events(db_conn, [
        EventRow(event_id="out_of_window", date="2026-04-28",
                 timezone="America/New_York", local_time="08:00",
                 utc_trigger_time=trigger_iso,
                 event_type="cpi", event_name="CPI 1h ago",
                 impact_level=4, notes=None),
    ])
    db_conn.commit()
    out = check_and_trigger_events(db_conn, now=_NOW)
    assert "event_macro" not in out


# ============================================================
# Combined / Robustness
# ============================================================

def test_check_and_trigger_returns_empty_with_clean_db(db_conn):
    """空 DB → 返回空 list,不抛错。"""
    out = check_and_trigger_events(db_conn, now=_NOW)
    assert out == []


def test_check_and_trigger_handles_invalidation_exception_gracefully(db_conn):
    """invalidation 路径异常不阻塞 price / macro。

    用 run_trigger='manual' 这样不命中 event_price 的 'scheduled%' 30min 节流
    (manual 触发的 run 不算 scheduled)。
    """
    db_conn.execute(
        "INSERT INTO strategy_runs (run_id, generated_at_utc, generated_at_bjt, "
        "action_state, full_state_json, run_trigger) VALUES (?, ?, ?, ?, ?, ?)",
        ("bad-json",
         _NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
         _NOW.strftime("%Y-%m-%d %H:%M (BJT)"),
         "FLAT", "{not json", "manual"),
    )
    _seed_klines_1h(db_conn, {
        "2026-04-27T11:00:00Z": 60000.0,
        "2026-04-28T11:00:00Z": 58000.0,
    })
    db_conn.commit()
    out = check_and_trigger_events(db_conn, now=_NOW)
    # invalidation 因 JSON 坏而 silent skip,price 仍触发
    assert "event_price" in out
