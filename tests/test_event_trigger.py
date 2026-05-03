"""tests/test_event_trigger.py — Sprint 1.10-G commit 2 EventTrigger 单测。

覆盖 v1.4 §6.2.3 双轨阈值 + D1=b baseline + D2=b 两类节流。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from src.strategy.event_trigger import (
    EVENT_CLASS_INVALIDATION,
    EVENT_CLASS_PRICE,
    EventTrigger,
    EventTriggerConfig,
    is_holding_state,
)


# ============================================================
# is_holding_state 工具函数
# ============================================================

@pytest.mark.parametrize("state,expected", [
    ("LONG_OPEN", True), ("LONG_HOLD", True), ("LONG_TRIM", True),
    ("SHORT_OPEN", True), ("SHORT_HOLD", True), ("SHORT_TRIM", True),
    ("FLAT", False), ("LONG_PLANNED", False), ("SHORT_PLANNED", False),
    ("FLIP_WATCH", False), ("PROTECTION", False),
    ("LONG_EXIT", False), ("SHORT_EXIT", False), ("POST_PROTECTION_REASSESS", False),
    (None, False), ("", False),
    ("long_open", True),  # case-insensitive
])
def test_is_holding_state(state, expected):
    assert is_holding_state(state) is expected


# ============================================================
# EventTriggerConfig.from_dict
# ============================================================

def test_config_from_dict_full():
    cfg = EventTriggerConfig.from_dict({
        "event_trigger": {
            "price_pct_flat": 0.04,
            "price_pct_holding": 0.025,
            "event_cooldown_seconds": 3600,
            "skip_if_recent_scheduled_seconds": 900,
        }
    })
    assert cfg.price_pct_flat == 0.04
    assert cfg.price_pct_holding == 0.025
    assert cfg.event_cooldown_seconds == 3600
    assert cfg.skip_if_recent_scheduled_seconds == 900


def test_config_from_dict_defaults():
    cfg = EventTriggerConfig.from_dict({})
    assert cfg.price_pct_flat == 0.05
    assert cfg.price_pct_holding == 0.03
    assert cfg.event_cooldown_seconds == 7200
    assert cfg.skip_if_recent_scheduled_seconds == 1800


# ============================================================
# 双轨阈值判定
# ============================================================

def _now() -> datetime:
    return datetime(2026, 5, 3, 12, 0, 0, tzinfo=timezone.utc)


def test_flat_below_5pct_no_trigger():
    """空仓 + 4.99% 异动 → 不触发。"""
    et = EventTrigger()
    triggered, reason = et.should_trigger_event_price(
        current_price=78500.0 * 1.0499,
        baseline_price=78500.0,
        current_state="FLAT",
        now_utc=_now(),
    )
    assert triggered is False
    assert reason == "below_threshold"


def test_flat_exactly_5pct_triggers():
    """空仓 + 刚好 5% → 触发(等号)。"""
    et = EventTrigger()
    triggered, reason = et.should_trigger_event_price(
        current_price=78500.0 * 1.05,
        baseline_price=78500.0,
        current_state="FLAT",
        now_utc=_now(),
    )
    assert triggered is True
    assert reason == "triggered_flat_5pct"


def test_flat_above_5pct_triggers_drop():
    """空仓 + 跌 6% → 触发(对称)。"""
    et = EventTrigger()
    triggered, reason = et.should_trigger_event_price(
        current_price=78500.0 * 0.94,
        baseline_price=78500.0,
        current_state="FLAT",
        now_utc=_now(),
    )
    assert triggered is True
    assert reason == "triggered_flat_5pct"


def test_holding_below_3pct_no_trigger():
    """持仓 + 2.99% → 不触发。"""
    et = EventTrigger()
    triggered, reason = et.should_trigger_event_price(
        current_price=78500.0 * 1.0299,
        baseline_price=78500.0,
        current_state="LONG_HOLD",
        now_utc=_now(),
    )
    assert triggered is False
    assert reason == "below_threshold"


def test_holding_exactly_3pct_triggers():
    """持仓 + 刚好 3% → 触发(等号)。"""
    et = EventTrigger()
    triggered, reason = et.should_trigger_event_price(
        current_price=78500.0 * 1.03,
        baseline_price=78500.0,
        current_state="LONG_HOLD",
        now_utc=_now(),
    )
    assert triggered is True
    assert reason == "triggered_holding_3pct"


def test_holding_above_3pct_triggers_drop():
    """持仓 + 跌 4% → 触发(对称)。"""
    et = EventTrigger()
    triggered, reason = et.should_trigger_event_price(
        current_price=78500.0 * 0.96,
        baseline_price=78500.0,
        current_state="SHORT_HOLD",
        now_utc=_now(),
    )
    assert triggered is True
    assert reason == "triggered_holding_3pct"


def test_planned_uses_flat_threshold():
    """LONG_PLANNED 不算持仓 → 用 5% 阈值。"""
    et = EventTrigger()
    # 4% 不触发(>3% 但 <5%)
    triggered, _ = et.should_trigger_event_price(
        current_price=78500.0 * 1.04,
        baseline_price=78500.0,
        current_state="LONG_PLANNED",
        now_utc=_now(),
    )
    assert triggered is False


# ============================================================
# 节流 1:同 event_class 2h cooldown
# ============================================================

def test_throttled_event_price_cooldown():
    """空仓 + 5% 异动 + last_event 在 1h 前 → 节流不触发。"""
    et = EventTrigger()
    now = _now()
    last_evt = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    triggered, reason = et.should_trigger_event_price(
        current_price=78500.0 * 1.05,
        baseline_price=78500.0,
        current_state="FLAT",
        last_event_at_utc=last_evt,
        now_utc=now,
    )
    assert triggered is False
    assert reason == "throttled_event_price"


def test_after_cooldown_triggers():
    """5% 异动 + last_event 在 3h 前(超 2h cooldown)→ 触发。"""
    et = EventTrigger()
    now = _now()
    last_evt = (now - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    triggered, reason = et.should_trigger_event_price(
        current_price=78500.0 * 1.05,
        baseline_price=78500.0,
        current_state="FLAT",
        last_event_at_utc=last_evt,
        now_utc=now,
    )
    assert triggered is True


# ============================================================
# 节流 2:距 last_main_run < 30min 跳过
# ============================================================

def test_throttled_recent_main_run():
    """5% 异动 + last_main_run 在 10min 前 → skip。"""
    et = EventTrigger()
    now = _now()
    last_run = (now - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    triggered, reason = et.should_trigger_event_price(
        current_price=78500.0 * 1.05,
        baseline_price=78500.0,
        current_state="FLAT",
        last_main_run_at_utc=last_run,
        now_utc=now,
    )
    assert triggered is False
    assert reason == "throttled_recent_main_run"


def test_after_recent_run_window_triggers():
    """5% 异动 + last_main_run 在 35min 前(超 30min 窗)→ 触发。"""
    et = EventTrigger()
    now = _now()
    last_run = (now - timedelta(minutes=35)).strftime("%Y-%m-%dT%H:%M:%SZ")
    triggered, reason = et.should_trigger_event_price(
        current_price=78500.0 * 1.05,
        baseline_price=78500.0,
        current_state="FLAT",
        last_main_run_at_utc=last_run,
        now_utc=now,
    )
    assert triggered is True


# ============================================================
# 边界 / 错误输入
# ============================================================

def test_invalid_baseline_zero():
    et = EventTrigger()
    triggered, reason = et.should_trigger_event_price(
        current_price=78500.0, baseline_price=0,
        current_state="FLAT", now_utc=_now(),
    )
    assert triggered is False
    assert reason == "invalid_baseline"


def test_invalid_baseline_none():
    et = EventTrigger()
    triggered, reason = et.should_trigger_event_price(
        current_price=78500.0, baseline_price=None,
        current_state="FLAT", now_utc=_now(),
    )
    assert triggered is False


def test_invalid_current_price():
    et = EventTrigger()
    triggered, reason = et.should_trigger_event_price(
        current_price=0, baseline_price=78500.0,
        current_state="FLAT", now_utc=_now(),
    )
    assert triggered is False
    assert reason == "invalid_baseline"


# ============================================================
# event_throttle 表 helpers(D2=b 两类独立)
# ============================================================

@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    with open("src/data/storage/schema.sql", encoding="utf-8") as f:
        c.executescript(f.read())
    yield c
    c.close()


def test_record_event_writes_throttle_row(conn):
    EventTrigger.record_event(
        conn, event_type="event_price",
        event_class=EVENT_CLASS_PRICE,
        triggered_at_utc="2026-05-03T12:00:00Z",
    )
    conn.commit()
    row = conn.execute(
        "SELECT event_type, last_triggered_at_utc, event_class FROM event_throttle "
        "WHERE event_type = ?", ("event_price",),
    ).fetchone()
    assert row is not None
    assert row["last_triggered_at_utc"] == "2026-05-03T12:00:00Z"
    assert row["event_class"] == EVENT_CLASS_PRICE


def test_record_event_upserts(conn):
    """同 event_type 重复 record → 覆盖 last_triggered_at_utc。"""
    EventTrigger.record_event(
        conn, "event_price", EVENT_CLASS_PRICE, "2026-05-03T10:00:00Z",
    )
    EventTrigger.record_event(
        conn, "event_price", EVENT_CLASS_PRICE, "2026-05-03T12:00:00Z",
    )
    conn.commit()
    row = conn.execute(
        "SELECT last_triggered_at_utc FROM event_throttle WHERE event_type = ?",
        ("event_price",),
    ).fetchone()
    assert row["last_triggered_at_utc"] == "2026-05-03T12:00:00Z"


def test_two_classes_independent(conn):
    """D2=b:event_price 与 event_invalidation 独立(不同 PK 行,互不挡)。"""
    EventTrigger.record_event(
        conn, "event_price", EVENT_CLASS_PRICE, "2026-05-03T10:00:00Z",
    )
    EventTrigger.record_event(
        conn, "event_invalidation", EVENT_CLASS_INVALIDATION,
        "2026-05-03T11:00:00Z",
    )
    conn.commit()
    rows = conn.execute(
        "SELECT event_type, event_class FROM event_throttle ORDER BY event_type",
    ).fetchall()
    assert len(rows) == 2
    classes = {r["event_type"]: r["event_class"] for r in rows}
    assert classes["event_price"] == EVENT_CLASS_PRICE
    assert classes["event_invalidation"] == EVENT_CLASS_INVALIDATION


def test_get_last_event_at(conn):
    EventTrigger.record_event(
        conn, "event_price", EVENT_CLASS_PRICE, "2026-05-03T12:00:00Z",
    )
    conn.commit()
    last = EventTrigger.get_last_event_at(conn, "event_price")
    assert last == "2026-05-03T12:00:00Z"
    # 未触发的 event_type → None
    assert EventTrigger.get_last_event_at(conn, "event_invalidation") is None


def test_get_baseline_price_from_strategy_runs(conn):
    """D1=b:get_baseline_price 读 strategy_runs 最新行 btc_price_usd。"""
    conn.execute(
        "INSERT INTO strategy_runs (run_id, generated_at_utc, generated_at_bjt, "
        "reference_timestamp_utc, action_state, run_trigger, btc_price_usd, "
        "full_state_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("r1", "2026-05-03T10:00:00Z", "2026-05-03T18:00:00+08:00",
         "2026-05-03T10:00:00Z", "FLAT", "test", 75000.0, "{}"),
    )
    conn.execute(
        "INSERT INTO strategy_runs (run_id, generated_at_utc, generated_at_bjt, "
        "reference_timestamp_utc, action_state, run_trigger, btc_price_usd, "
        "full_state_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("r2", "2026-05-03T16:00:00Z", "2026-05-04T00:00:00+08:00",
         "2026-05-03T16:00:00Z", "FLAT", "test", 78500.0, "{}"),
    )
    conn.commit()
    baseline = EventTrigger.get_baseline_price(conn)
    assert baseline == 78500.0


def test_get_baseline_price_no_runs(conn):
    """冷启动 → strategy_runs 空 → 返 None。"""
    assert EventTrigger.get_baseline_price(conn) is None


def test_get_last_main_run_at_returns_latest(conn):
    conn.execute(
        "INSERT INTO strategy_runs (run_id, generated_at_utc, generated_at_bjt, "
        "reference_timestamp_utc, action_state, run_trigger, full_state_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("r_old", "2026-05-03T10:00:00Z", "2026-05-03T18:00:00+08:00",
         "2026-05-03T10:00:00Z", "FLAT", "test", "{}"),
    )
    conn.execute(
        "INSERT INTO strategy_runs (run_id, generated_at_utc, generated_at_bjt, "
        "reference_timestamp_utc, action_state, run_trigger, full_state_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("r_new", "2026-05-03T16:00:00Z", "2026-05-04T00:00:00+08:00",
         "2026-05-03T16:00:00Z", "FLAT", "test", "{}"),
    )
    conn.commit()
    last = EventTrigger.get_last_main_run_at(conn)
    assert last == "2026-05-03T16:00:00Z"
