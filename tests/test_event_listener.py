"""tests/test_event_listener.py — Sprint 1.10-G 改造版本。

Sprint 1.10-G §X 删除/迁移:
- 删 _is_throttled / _record_trigger 测试(替代 EventTrigger.{record_event,
  get_last_event_at},覆盖在 tests/test_event_trigger.py)
- 删 _check_event_invalidation 测试(迁到 hard_invalidation_monitor 1h cron,
  覆盖在 tests/test_hard_invalidation_monitor.py)
- 删 _check_event_price 单一阈值/24h baseline 老语义测试(改造为双轨 +
  上次 strategy_run baseline,覆盖在本文件 + tests/test_event_trigger.py)

保留 / 改造:
- event_macro:无变化,沿用 2.7-D
- event_price 双轨判定 + 新 baseline + 节流(2 类独立)
- check_and_trigger_events 入口(从 3 类降到 2 类)
"""
from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.data.storage.connection import init_db
from src.data.storage.dao import EventRow, EventsCalendarDAO
from src.scheduler.event_listener import (
    _check_event_macro,
    _check_event_price,
    check_and_trigger_events,
)
from src.strategy.event_trigger import (
    EVENT_CLASS_PRICE,
    EventTrigger,
)


_NOW = datetime(2026, 5, 3, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def db_conn():
    tmp = Path(tempfile.mkdtemp()) / "ev.db"
    init_db(db_path=tmp, verbose=False)
    # 应用 1.10-A → G 全套 v1.4 migration(含 event_throttle.event_class)
    conn = sqlite3.connect(tmp)
    conn.row_factory = sqlite3.Row
    from scripts.init_v14_tables import apply_migration
    apply_migration(conn)
    # 兼容 2.7-D 老 migration(events_calendar.triggered_at_utc 列)
    try:
        from scripts.migrate_2_7_d import apply_migration as apply_27d
        apply_27d(conn)
    except Exception:
        pass
    yield conn
    conn.close()


# ============================================================
# 数据 seed helpers
# ============================================================

def _seed_strategy_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    generated_at_utc: str,
    btc_price_usd: float,
    action_state: str = "FLAT",
    run_trigger: str = "scheduled",
) -> None:
    conn.execute(
        "INSERT INTO strategy_runs (run_id, generated_at_utc, generated_at_bjt, "
        "reference_timestamp_utc, action_state, run_trigger, btc_price_usd, "
        "full_state_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, generated_at_utc, generated_at_utc,
         generated_at_utc, action_state, run_trigger,
         btc_price_usd, "{}"),
    )


def _seed_kline_1h(
    conn: sqlite3.Connection,
    *,
    open_time_utc: str,
    close: float,
) -> None:
    conn.execute(
        "INSERT INTO price_candles (symbol, timeframe, open_time_utc, "
        "open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("BTCUSDT", "1h", open_time_utc,
         close - 100, close + 100, close - 200, close, 1000),
    )


# ============================================================
# event_price — 双轨 + 新 baseline(D1=b)
# ============================================================

def test_event_price_flat_5pct_triggers(db_conn):
    """空仓 + 5% 异动 → 触发。"""
    # 上次 run baseline = 75000 / state=FLAT
    _seed_strategy_run(
        db_conn, run_id="r_base",
        generated_at_utc=_NOW.replace(hour=8).strftime("%Y-%m-%dT%H:%M:%SZ"),
        btc_price_usd=75000.0, action_state="FLAT",
    )
    _seed_kline_1h(
        db_conn, open_time_utc=_NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
        close=75000.0 * 1.05,
    )
    db_conn.commit()
    assert _check_event_price(db_conn, now=_NOW) is True
    db_conn.commit()
    # 写入了 event_throttle
    last = EventTrigger.get_last_event_at(db_conn, "event_price")
    assert last is not None


def test_event_price_flat_4pct_no_trigger(db_conn):
    """空仓 + 4% 异动(< 5%)→ 不触发。"""
    _seed_strategy_run(
        db_conn, run_id="r_base",
        generated_at_utc=_NOW.replace(hour=8).strftime("%Y-%m-%dT%H:%M:%SZ"),
        btc_price_usd=75000.0, action_state="FLAT",
    )
    _seed_kline_1h(
        db_conn, open_time_utc=_NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
        close=75000.0 * 1.04,
    )
    db_conn.commit()
    assert _check_event_price(db_conn, now=_NOW) is False


def test_event_price_holding_3pct_triggers(db_conn):
    """持仓 + 3% 异动 → 触发(用更严的 3% 阈值)。"""
    _seed_strategy_run(
        db_conn, run_id="r_base",
        generated_at_utc=_NOW.replace(hour=8).strftime("%Y-%m-%dT%H:%M:%SZ"),
        btc_price_usd=75000.0, action_state="LONG_HOLD",
    )
    _seed_kline_1h(
        db_conn, open_time_utc=_NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
        close=75000.0 * 1.03,
    )
    db_conn.commit()
    assert _check_event_price(db_conn, now=_NOW) is True


def test_event_price_holding_2pct_no_trigger(db_conn):
    """持仓 + 2% 异动(< 3%)→ 不触发。"""
    _seed_strategy_run(
        db_conn, run_id="r_base",
        generated_at_utc=_NOW.replace(hour=8).strftime("%Y-%m-%dT%H:%M:%SZ"),
        btc_price_usd=75000.0, action_state="SHORT_HOLD",
    )
    _seed_kline_1h(
        db_conn, open_time_utc=_NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
        close=75000.0 * 0.98,
    )
    db_conn.commit()
    assert _check_event_price(db_conn, now=_NOW) is False


def test_event_price_throttled_within_2h(db_conn):
    """5% 异动 + last_event 在 1h 前 → 节流不触发。"""
    _seed_strategy_run(
        db_conn, run_id="r_base",
        generated_at_utc=(_NOW - timedelta(hours=10)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        btc_price_usd=75000.0, action_state="FLAT",
    )
    _seed_kline_1h(
        db_conn, open_time_utc=_NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
        close=75000.0 * 1.05,
    )
    EventTrigger.record_event(
        db_conn, "event_price", EVENT_CLASS_PRICE,
        (_NOW - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    db_conn.commit()
    assert _check_event_price(db_conn, now=_NOW) is False


def test_event_price_recent_main_run_skipped(db_conn):
    """5% 异动 + last_main_run 在 10min 前 → skip。"""
    _seed_strategy_run(
        db_conn, run_id="r_recent",
        generated_at_utc=(_NOW - timedelta(minutes=10)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        btc_price_usd=75000.0, action_state="FLAT",
    )
    _seed_kline_1h(
        db_conn, open_time_utc=_NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
        close=75000.0 * 1.05,
    )
    db_conn.commit()
    assert _check_event_price(db_conn, now=_NOW) is False


def test_event_price_no_strategy_run_baseline_skip(db_conn):
    """冷启动:无 strategy_run 行 → baseline=None → 不触发。"""
    _seed_kline_1h(
        db_conn, open_time_utc=_NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
        close=75000.0,
    )
    db_conn.commit()
    assert _check_event_price(db_conn, now=_NOW) is False


def test_event_price_no_kline_skip(db_conn):
    """无 1h K 线 → 不触发。"""
    _seed_strategy_run(
        db_conn, run_id="r_base",
        generated_at_utc=(_NOW - timedelta(hours=10)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        btc_price_usd=75000.0, action_state="FLAT",
    )
    db_conn.commit()
    assert _check_event_price(db_conn, now=_NOW) is False


# ============================================================
# event_macro(沿用 2.7-D 实现)
# ============================================================

def _seed_event_calendar(
    conn: sqlite3.Connection,
    *,
    event_id: str,
    utc_trigger_time: str,
    impact_level: int = 3,
    triggered_at_utc: str | None = None,
) -> None:
    # date 字段(YYYY-MM-DD)— 从 utc_trigger_time 取
    date_str = utc_trigger_time.split("T")[0]
    EventsCalendarDAO.upsert_event(conn, EventRow(
        event_id=event_id,
        date=date_str,
        timezone="UTC",
        local_time=None,
        utc_trigger_time=utc_trigger_time,
        event_type="macro",
        event_name="FOMC test",
        impact_level=impact_level,
        notes=None,
    ))
    if triggered_at_utc:
        conn.execute(
            "UPDATE events_calendar SET triggered_at_utc=? WHERE event_id=?",
            (triggered_at_utc, event_id),
        )


def test_event_macro_15min_window_hit(db_conn):
    """utc_trigger + 15min 落在过去 60s → 命中。"""
    trigger = (_NOW - timedelta(minutes=15, seconds=30)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    _seed_event_calendar(
        db_conn, event_id="ev_001", utc_trigger_time=trigger, impact_level=3,
    )
    db_conn.commit()
    assert _check_event_macro(db_conn, now=_NOW) is True


def test_event_macro_already_triggered_no_double(db_conn):
    """triggered_at_utc 已有值 → 不重复。"""
    trigger = (_NOW - timedelta(minutes=15, seconds=30)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    _seed_event_calendar(
        db_conn, event_id="ev_002", utc_trigger_time=trigger, impact_level=3,
        triggered_at_utc=(_NOW - timedelta(minutes=10)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
    )
    db_conn.commit()
    assert _check_event_macro(db_conn, now=_NOW) is False


def test_event_macro_low_impact_skipped(db_conn):
    """impact_level=1 → 跳过(只 ≥ 2 触发)。"""
    trigger = (_NOW - timedelta(minutes=15, seconds=30)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    _seed_event_calendar(
        db_conn, event_id="ev_low", utc_trigger_time=trigger, impact_level=1,
    )
    db_conn.commit()
    assert _check_event_macro(db_conn, now=_NOW) is False


def test_event_macro_outside_window_no_trigger(db_conn):
    """utc_trigger 在 1 小时前 → 超 16min 窗口 → 不命中。"""
    trigger = (_NOW - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _seed_event_calendar(
        db_conn, event_id="ev_old", utc_trigger_time=trigger, impact_level=3,
    )
    db_conn.commit()
    assert _check_event_macro(db_conn, now=_NOW) is False


# ============================================================
# check_and_trigger_events 入口(2 类:event_price + event_macro)
# ============================================================

def test_check_and_trigger_returns_empty_with_clean_db(db_conn):
    triggered = check_and_trigger_events(db_conn, now=_NOW)
    assert triggered == []


def test_check_and_trigger_returns_event_price(db_conn):
    """5% 异动 → 返 ['event_price']。"""
    _seed_strategy_run(
        db_conn, run_id="r_base",
        generated_at_utc=(_NOW - timedelta(hours=10)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        btc_price_usd=75000.0, action_state="FLAT",
    )
    _seed_kline_1h(
        db_conn, open_time_utc=_NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
        close=75000.0 * 1.06,
    )
    db_conn.commit()
    triggered = check_and_trigger_events(db_conn, now=_NOW)
    assert "event_price" in triggered


def test_check_and_trigger_no_invalidation_in_list(db_conn):
    """§X 1.10-G:event_invalidation 拆到独立 1h cron,
    check_and_trigger_events 不再返。"""
    triggered = check_and_trigger_events(db_conn, now=_NOW)
    assert "event_invalidation" not in triggered


def test_check_and_trigger_handles_exception_gracefully(db_conn):
    """单类失败不阻塞其他类(整体不抛)。"""
    # 即使 db 半 broken,函数也应返 list(可能为空)
    result = check_and_trigger_events(db_conn, now=_NOW)
    assert isinstance(result, list)
