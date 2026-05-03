"""tests/test_hard_invalidation_monitor.py — Sprint 1.10-G commit 3 单测。

覆盖 v1.4 §6.2.3 event_invalidation 规则平仓 + D4=b1(复用 stop_loss_filled
reason + retry_log_marker)。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from src.data.storage.dao import (
    ThesesDAO, VirtualAccountDAO, VirtualOrdersDAO,
)
from src.strategy import thesis_manager
from src.strategy.hard_invalidation_monitor import HardInvalidationMonitor


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    with open("src/data/storage/schema.sql", encoding="utf-8") as f:
        c.executescript(f.read())
    # apply_migration 加 v1.4 三表(virtual_account/theses/virtual_orders 等)
    from scripts.init_v14_tables import apply_migration
    apply_migration(c)
    # 初始化 virtual_account snapshot(close_thesis 需 prev_snapshot)
    VirtualAccountDAO.insert_snapshot(
        c,
        snapshot_id="init_001",
        run_id="init_run",
        snapshot_at_utc="2026-05-01T00:00:00Z",
        btc_price_at_snapshot=80000.0,
        initial_capital=100000.0,
        available_cash=100000.0,
        total_equity=100000.0,
    )
    c.commit()
    yield c
    c.close()


def _create_active_thesis_with_sl(
    conn: sqlite3.Connection,
    *,
    direction: str,
    sl_price: float,
    sl_size_usdt: float = 30000.0,
    thesis_id: str = "t_test_001",
) -> str:
    """创建 1 个 active thesis + 1 条 stop_loss 挂单(via thesis_manager.create_thesis)。

    Returns: stop_loss_order_id
    """
    spec = {
        "direction": direction,
        "core_logic": "test",
        "confidence_score": 70,
        "break_conditions": ["BTC < x", "BTC < y", "BTC < z"],
        "entry_orders": [{"price": 75000.0, "size_pct": 0.30, "size_usdt": 30000.0}],
        "stop_loss_orders": [{"price": sl_price, "size_pct": 0.30, "size_usdt": sl_size_usdt}],
        "take_profit_orders": [],
    }
    result = thesis_manager.create_thesis(
        conn, thesis_spec=spec,
        run_id="r_test", now_utc="2026-05-03T12:00:00Z",
        expires_at_utc="2026-05-10T12:00:00Z",
        thesis_id=thesis_id,
    )
    conn.commit()
    return result["stop_loss_order_ids"][0]


# ============================================================
# check_active_theses
# ============================================================

def test_no_active_thesis_returns_empty(conn):
    breaches = HardInvalidationMonitor.check_active_theses(
        conn, current_btc_price=70000.0,
    )
    assert breaches == []


def test_long_thesis_not_breached(conn):
    """long + sl=72000 + current=75000 → 未击穿。"""
    _create_active_thesis_with_sl(conn, direction="long", sl_price=72000.0)
    breaches = HardInvalidationMonitor.check_active_theses(
        conn, current_btc_price=75000.0,
    )
    assert breaches == []


def test_long_thesis_breached(conn):
    """long + sl=72000 + current=71000 → 击穿。"""
    sl_id = _create_active_thesis_with_sl(conn, direction="long", sl_price=72000.0)
    breaches = HardInvalidationMonitor.check_active_theses(
        conn, current_btc_price=71000.0,
    )
    assert len(breaches) == 1
    b = breaches[0]
    assert b["direction"] == "long"
    assert b["stop_loss_price"] == 72000.0
    assert b["stop_loss_order_id"] == sl_id
    assert b["current_price"] == 71000.0
    assert b["breached_by"] < 0  # 跌破


def test_short_thesis_breached(conn):
    """short + sl=78000 + current=79000 → 击穿(向上突破)。"""
    sl_id = _create_active_thesis_with_sl(
        conn, direction="short", sl_price=78000.0, thesis_id="t_short_001",
    )
    breaches = HardInvalidationMonitor.check_active_theses(
        conn, current_btc_price=79000.0,
    )
    assert len(breaches) == 1
    assert breaches[0]["direction"] == "short"
    assert breaches[0]["breached_by"] > 0  # 突破向上


def test_short_thesis_not_breached(conn):
    """short + sl=78000 + current=77000 → 未击穿。"""
    _create_active_thesis_with_sl(
        conn, direction="short", sl_price=78000.0, thesis_id="t_short_002",
    )
    breaches = HardInvalidationMonitor.check_active_theses(
        conn, current_btc_price=77000.0,
    )
    assert breaches == []


def test_thesis_with_no_stop_loss_returns_empty(conn):
    """active thesis 但无 stop_loss 挂单 → 空 list。"""
    spec = {
        "direction": "long", "core_logic": "test", "confidence_score": 70,
        "break_conditions": ["a", "b", "c"],
        "entry_orders": [{"price": 75000.0, "size_pct": 0.30, "size_usdt": 30000.0}],
        "stop_loss_orders": [],
        "take_profit_orders": [],
    }
    thesis_manager.create_thesis(
        conn, thesis_spec=spec, run_id="r", now_utc="2026-05-03T12:00:00Z",
        expires_at_utc="2026-05-10T12:00:00Z", thesis_id="t_no_sl",
    )
    conn.commit()
    breaches = HardInvalidationMonitor.check_active_theses(
        conn, current_btc_price=70000.0,
    )
    assert breaches == []


def test_invalid_current_price_returns_empty(conn):
    _create_active_thesis_with_sl(conn, direction="long", sl_price=72000.0,
                                   thesis_id="t_zero_price")
    assert HardInvalidationMonitor.check_active_theses(
        conn, current_btc_price=0,
    ) == []
    assert HardInvalidationMonitor.check_active_theses(
        conn, current_btc_price=None,
    ) == []


# ============================================================
# execute_invalidation
# ============================================================

def test_execute_invalidation_fills_stop_loss(conn):
    """规则平仓:fill_order + close_thesis(reason=stop_loss_filled, channel=A)。"""
    sl_id = _create_active_thesis_with_sl(
        conn, direction="long", sl_price=72000.0, thesis_id="t_exec_001",
    )
    # 写一个 strategy_run 给 run_id 兜底
    conn.execute(
        "INSERT INTO strategy_runs (run_id, generated_at_utc, generated_at_bjt, "
        "reference_timestamp_utc, action_state, run_trigger, full_state_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("r_exec", "2026-05-03T16:00:00Z", "2026-05-04T00:00:00+08:00",
         "2026-05-03T16:00:00Z", "LONG_HOLD", "scheduled", "{}"),
    )
    conn.commit()

    result = HardInvalidationMonitor.execute_invalidation(
        conn,
        thesis_id="t_exec_001",
        stop_loss_order_id=sl_id,
        current_btc_price=71000.0,
        initial_capital=100000.0,
        now_utc=datetime(2026, 5, 3, 16, 5, 0, tzinfo=timezone.utc),
    )
    conn.commit()

    assert result["status"] == "event_invalidation_executed"
    # stop_loss 挂单已 filled
    sl_row = conn.execute(
        "SELECT status, filled_price FROM virtual_orders WHERE order_id = ?",
        (sl_id,),
    ).fetchone()
    assert sl_row["status"] == "filled"
    assert sl_row["filled_price"] == 71000.0

    # thesis 已 closed
    th_row = conn.execute(
        "SELECT status, close_channel FROM theses WHERE thesis_id = ?",
        ("t_exec_001",),
    ).fetchone()
    assert th_row["status"] == "closed_loss"  # stop_loss_filled → closed_loss
    assert th_row["close_channel"] == "A"     # D4=b1


def test_execute_invalidation_returns_retry_log_marker(conn):
    """D4=b1:retry_log_marker 含 event_invalidation_triggered=True 等 5 字段。"""
    sl_id = _create_active_thesis_with_sl(
        conn, direction="long", sl_price=72000.0, thesis_id="t_marker_001",
    )
    conn.execute(
        "INSERT INTO strategy_runs (run_id, generated_at_utc, generated_at_bjt, "
        "reference_timestamp_utc, action_state, run_trigger, full_state_json) "
        "VALUES ('r_m', '2026-05-03T16:00:00Z', '2026-05-04T00:00:00+08:00', "
        "'2026-05-03T16:00:00Z', 'LONG_HOLD', 'scheduled', '{}')",
    )
    conn.commit()

    result = HardInvalidationMonitor.execute_invalidation(
        conn, thesis_id="t_marker_001", stop_loss_order_id=sl_id,
        current_btc_price=71000.0, initial_capital=100000.0,
        now_utc=datetime(2026, 5, 3, 16, 0, 0, tzinfo=timezone.utc),
    )
    marker = result["retry_log_marker"]
    assert marker["event_invalidation_triggered"] is True
    assert marker["event_invalidation_thesis_id"] == "t_marker_001"
    assert marker["event_invalidation_close_channel"] == "A"
    assert marker["event_invalidation_close_reason"] == "stop_loss_filled"
    assert marker["event_invalidation_at_utc"] == "2026-05-03T16:00:00Z"


def test_execute_invalidation_unknown_order_returns_skipped(conn):
    """stop_loss_order_id 不在 pending → status=skipped_order_not_pending。"""
    _create_active_thesis_with_sl(conn, direction="long", sl_price=72000.0,
                                   thesis_id="t_unknown_sl")
    result = HardInvalidationMonitor.execute_invalidation(
        conn, thesis_id="t_unknown_sl",
        stop_loss_order_id="bogus_id_xxx",
        current_btc_price=71000.0, initial_capital=100000.0,
    )
    assert result["status"] == "skipped_order_not_pending"


def test_execute_invalidation_does_not_call_ai(conn, monkeypatch):
    """v1.4 §6.2.3 硬约束:execute_invalidation 不能调任何 AI / build_anthropic_client。"""
    sl_id = _create_active_thesis_with_sl(
        conn, direction="long", sl_price=72000.0, thesis_id="t_no_ai_001",
    )
    conn.execute(
        "INSERT INTO strategy_runs (run_id, generated_at_utc, generated_at_bjt, "
        "reference_timestamp_utc, action_state, run_trigger, full_state_json) "
        "VALUES ('r_no_ai', '2026-05-03T16:00:00Z', '2026-05-04T00:00:00+08:00', "
        "'2026-05-03T16:00:00Z', 'LONG_HOLD', 'scheduled', '{}')",
    )
    conn.commit()

    # mock build_anthropic_client 抛异常 — 若 HardInvalidationMonitor 真调 AI 就挂
    import src.ai.client as client_mod
    called = {"flag": False}
    def _raise(*a, **k):
        called["flag"] = True
        raise RuntimeError("HardInvalidationMonitor 不应调 AI(v1.4 §6.2.3 硬约束)")
    monkeypatch.setattr(client_mod, "build_anthropic_client", _raise)

    result = HardInvalidationMonitor.execute_invalidation(
        conn, thesis_id="t_no_ai_001", stop_loss_order_id=sl_id,
        current_btc_price=71000.0, initial_capital=100000.0,
    )
    assert called["flag"] is False
    assert result["status"] == "event_invalidation_executed"


# ============================================================
# get_latest_btc_price
# ============================================================

def test_get_latest_btc_price_from_kline(conn):
    conn.execute(
        "INSERT INTO price_candles (symbol, timeframe, open_time_utc, "
        "open, high, low, close, volume) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("BTCUSDT", "1h", "2026-05-03T16:00:00Z",
         78000, 78500, 77800, 78400, 1234.5),
    )
    conn.commit()
    px = HardInvalidationMonitor.get_latest_btc_price(conn)
    assert px == 78400.0


def test_get_latest_btc_price_no_kline(conn):
    assert HardInvalidationMonitor.get_latest_btc_price(conn) is None
