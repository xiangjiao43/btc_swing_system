"""Sprint 1.10-B 单测:OrdersEngine(v1.4 §5.2.3 / §5.2.4 / §5.2.5)。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.data.storage.dao import (
    ThesesDAO, VirtualOrdersDAO, VirtualAccountDAO,
)
from src.strategy.orders_engine import check_and_fill_orders


_MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "migrations" / "009_v14_virtual_account_thesis.sql"
)

# minimal price_candles schema(对齐 src/data/storage/schema.sql)
_PRICE_CANDLES_SCHEMA = """
CREATE TABLE IF NOT EXISTS price_candles (
    symbol            TEXT NOT NULL,
    timeframe         TEXT NOT NULL,
    open_time_utc     TEXT NOT NULL,
    open              REAL,
    high              REAL,
    low               REAL,
    close             REAL,
    volume            REAL,
    inserted_at_utc   TEXT,
    PRIMARY KEY (symbol, timeframe, open_time_utc)
);
"""


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE strategy_runs (run_id TEXT PRIMARY KEY)")
    c.executescript(_PRICE_CANDLES_SCHEMA)
    c.executescript(_MIGRATION.read_text(encoding="utf-8"))
    yield c
    c.close()


def _insert_kline(conn, open_time_utc, low, high, close=None, open_=None):
    conn.execute(
        "INSERT INTO price_candles (symbol, timeframe, open_time_utc, open, high, low, close, volume) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("BTCUSDT", "1h", open_time_utc, open_ or low, high, low, close or high, 100.0),
    )


def _make_thesis(conn, thesis_id="th1"):
    ThesesDAO.create(
        conn,
        thesis_id=thesis_id,
        created_at_run_id="run_test",
        created_at_utc="2026-05-03T08:00:00Z",
        direction="long",
        core_logic="test",
        confidence_score=70,
        break_conditions=["c1", "c2", "c3"],
    )


def _make_order(conn, order_id, price, size_usdt=20000.0, size_pct=0.20,
                thesis_id="th1", order_type="entry", direction="long",
                expires_at_utc="2026-05-10T08:00:00Z"):
    VirtualOrdersDAO.create_order(
        conn,
        order_id=order_id, thesis_id=thesis_id,
        direction=direction, order_type=order_type,
        price=price, size_pct=size_pct, size_usdt=size_usdt,
        created_at_utc="2026-05-03T08:00:00Z",
        expires_at_utc=expires_at_utc,
    )


# ============================================================
# happy path
# ============================================================

def test_single_order_within_kline_range_fills(conn):
    """单挂单 low≤price≤high → fill,价格 = 挂单价(§5.2.4)。"""
    _make_thesis(conn)
    _make_order(conn, "o1", price=74568.0)
    _insert_kline(conn, "2026-05-04T10:00:00Z", low=73500.0, high=76000.0)
    conn.commit()

    res = check_and_fill_orders(
        conn, thesis_id="th1",
        last_check_utc="2026-05-04T00:00:00Z",
        now_utc="2026-05-04T20:00:00Z",
        current_btc_price=75500.0,
        initial_capital=100000.0,
        snapshot_id="s1", run_id="r1",
        snapshot_at_utc="2026-05-04T20:00:00Z",
    )
    assert len(res["filled_orders"]) == 1
    f = res["filled_orders"][0]
    assert f["order_id"] == "o1"
    assert f["filled_price"] == 74568.0           # §5.2.4 入场价 = 挂单价
    assert abs(f["filled_btc_amount"] - 0.26821157) < 1e-6  # 20000 / 74568
    assert res["expired_count"] == 0


def test_multi_order_same_kline_all_trigger(conn):
    """§5.2.5 同 1H 多挂单全触发(low ≤ price ≤ high 任一满足)。"""
    _make_thesis(conn)
    _make_order(conn, "oA", price=74568.0, size_usdt=20000.0)
    _make_order(conn, "oB", price=70666.0, size_usdt=30000.0)
    _make_order(conn, "oC", price=66000.0, size_usdt=20000.0)  # 不在范围
    _insert_kline(conn, "2026-05-04T10:00:00Z", low=70000.0, high=76000.0)
    conn.commit()

    res = check_and_fill_orders(
        conn, thesis_id="th1",
        last_check_utc="2026-05-04T00:00:00Z",
        now_utc="2026-05-04T20:00:00Z",
        current_btc_price=72000.0,
        initial_capital=100000.0,
        snapshot_id="s1", run_id="r1",
        snapshot_at_utc="2026-05-04T20:00:00Z",
    )
    filled_ids = {f["order_id"] for f in res["filled_orders"]}
    assert filled_ids == {"oA", "oB"}
    assert len(res["filled_orders"]) == 2
    # oC 仍 pending
    pending = VirtualOrdersDAO.get_pending(conn, thesis_id="th1")
    assert len(pending) == 1
    assert pending[0]["order_id"] == "oC"
    # computed_snapshot 加权 avg
    snap = res["computed_snapshot_for_account"]
    assert snap["long_position_usdt"] == 50000.0
    assert snap["available_cash"] == 50000.0


def test_price_exactly_at_high_or_low_fills(conn):
    """边界等号:price = high 或 price = low 都触发。"""
    _make_thesis(conn)
    _make_order(conn, "o_high", price=76000.0)  # = high
    _make_order(conn, "o_low", price=70000.0)   # = low
    _insert_kline(conn, "2026-05-04T10:00:00Z", low=70000.0, high=76000.0)
    conn.commit()

    res = check_and_fill_orders(
        conn, thesis_id="th1",
        last_check_utc="2026-05-04T00:00:00Z",
        now_utc="2026-05-04T20:00:00Z",
        current_btc_price=73000.0,
        initial_capital=100000.0,
        snapshot_id="s1", run_id="r1",
        snapshot_at_utc="2026-05-04T20:00:00Z",
    )
    assert len(res["filled_orders"]) == 2
    assert {f["order_id"] for f in res["filled_orders"]} == {"o_high", "o_low"}


def test_price_outside_kline_range_does_not_fill(conn):
    """price < low 或 price > high → 不触发。"""
    _make_thesis(conn)
    _make_order(conn, "o_too_low", price=65000.0)
    _make_order(conn, "o_too_high", price=80000.0)
    _insert_kline(conn, "2026-05-04T10:00:00Z", low=70000.0, high=76000.0)
    conn.commit()

    res = check_and_fill_orders(
        conn, thesis_id="th1",
        last_check_utc="2026-05-04T00:00:00Z",
        now_utc="2026-05-04T20:00:00Z",
        current_btc_price=73000.0,
        initial_capital=100000.0,
        snapshot_id="s1", run_id="r1",
        snapshot_at_utc="2026-05-04T20:00:00Z",
    )
    assert res["filled_orders"] == []
    pending = VirtualOrdersDAO.get_pending(conn, thesis_id="th1")
    assert len(pending) == 2


def test_multi_kline_order_fills_at_correct_kline(conn):
    """多 K 线序列,挂单在第 3 根穿过 → 触发,filled_at_utc 是该 K 线时间。"""
    _make_thesis(conn)
    _make_order(conn, "o1", price=72000.0)
    _insert_kline(conn, "2026-05-04T08:00:00Z", low=75000.0, high=78000.0)  # 不穿
    _insert_kline(conn, "2026-05-04T09:00:00Z", low=74000.0, high=77000.0)  # 不穿
    _insert_kline(conn, "2026-05-04T10:00:00Z", low=70000.0, high=76000.0)  # 穿过 ✓
    _insert_kline(conn, "2026-05-04T11:00:00Z", low=68000.0, high=73000.0)  # 也穿,但已 filled
    conn.commit()

    res = check_and_fill_orders(
        conn, thesis_id="th1",
        last_check_utc="2026-05-04T00:00:00Z",
        now_utc="2026-05-04T20:00:00Z",
        current_btc_price=70000.0,
        initial_capital=100000.0,
        snapshot_id="s1", run_id="r1",
        snapshot_at_utc="2026-05-04T20:00:00Z",
    )
    assert len(res["filled_orders"]) == 1
    f = res["filled_orders"][0]
    assert f["filled_at_utc"] == "2026-05-04T10:00:00Z"  # 第一次穿过的 K 线


def test_already_filled_not_retriggered(conn):
    """挂单已 filled,再次调用不重复触发(WHERE status='pending' 拦截)。"""
    _make_thesis(conn)
    _make_order(conn, "o1", price=74568.0)
    _insert_kline(conn, "2026-05-04T10:00:00Z", low=73500.0, high=76000.0)
    conn.commit()

    # 第 1 次
    res1 = check_and_fill_orders(
        conn, thesis_id="th1",
        last_check_utc="2026-05-04T00:00:00Z",
        now_utc="2026-05-04T20:00:00Z",
        current_btc_price=75000.0,
        initial_capital=100000.0,
        snapshot_id="s1", run_id="r1",
        snapshot_at_utc="2026-05-04T20:00:00Z",
    )
    assert len(res1["filled_orders"]) == 1
    conn.commit()

    # 第 2 次(同一个 K 线还在范围内)
    res2 = check_and_fill_orders(
        conn, thesis_id="th1",
        last_check_utc="2026-05-04T00:00:00Z",
        now_utc="2026-05-04T20:00:00Z",
        current_btc_price=75000.0,
        initial_capital=100000.0,
        snapshot_id="s2", run_id="r2",
        snapshot_at_utc="2026-05-04T21:00:00Z",
    )
    assert res2["filled_orders"] == []  # 不重复


def test_expired_orders_marked(conn):
    """挂单 expires_at_utc < now → mark_expired,不进 fills。"""
    _make_thesis(conn)
    _make_order(conn, "o_alive", price=74000.0, expires_at_utc="2026-12-01T00:00:00Z")
    _make_order(conn, "o_expired", price=75000.0, expires_at_utc="2026-05-01T00:00:00Z")
    _insert_kline(conn, "2026-05-04T10:00:00Z", low=73000.0, high=76000.0)
    conn.commit()

    res = check_and_fill_orders(
        conn, thesis_id="th1",
        last_check_utc="2026-05-04T00:00:00Z",
        now_utc="2026-05-04T20:00:00Z",
        current_btc_price=74500.0,
        initial_capital=100000.0,
        snapshot_id="s1", run_id="r1",
        snapshot_at_utc="2026-05-04T20:00:00Z",
    )
    assert res["expired_count"] == 1
    # o_alive 触发,o_expired 已被 mark_expired(虽在 K 线范围内但 status 已变)
    filled_ids = {f["order_id"] for f in res["filled_orders"]}
    assert filled_ids == {"o_alive"}
    rows = conn.execute(
        "SELECT order_id, status, cancelled_reason FROM virtual_orders ORDER BY order_id"
    ).fetchall()
    by_id = {r["order_id"]: dict(r) for r in rows}
    assert by_id["o_alive"]["status"] == "filled"
    assert by_id["o_expired"]["status"] == "expired"
    assert by_id["o_expired"]["cancelled_reason"] == "expired"


def test_no_klines_returns_no_fills(conn):
    """无 1H K 线 → 不报错,fills 空。"""
    _make_thesis(conn)
    _make_order(conn, "o1", price=74000.0)
    conn.commit()

    res = check_and_fill_orders(
        conn, thesis_id="th1",
        last_check_utc="2026-05-04T00:00:00Z",
        now_utc="2026-05-04T20:00:00Z",
        current_btc_price=74500.0,
        initial_capital=100000.0,
        snapshot_id="s1", run_id="r1",
        snapshot_at_utc="2026-05-04T20:00:00Z",
    )
    assert res["filled_orders"] == []
    assert res["expired_count"] == 0
    snap = res["computed_snapshot_for_account"]
    # 无 fill,equity = initial(因 prev_snapshot=None,fills 空)
    assert snap["total_equity"] == 100000.0


def test_non_entry_orders_skipped(conn):
    """D2=a:order_type != 'entry' 跳过,记录到 skipped_orders。"""
    _make_thesis(conn)
    _make_order(conn, "o_entry", price=74000.0, order_type="entry")
    _make_order(conn, "o_stop", price=70000.0, order_type="stop_loss")
    _make_order(conn, "o_tp", price=80000.0, order_type="take_profit")
    _insert_kline(conn, "2026-05-04T10:00:00Z", low=68000.0, high=82000.0)  # 全在范围
    conn.commit()

    res = check_and_fill_orders(
        conn, thesis_id="th1",
        last_check_utc="2026-05-04T00:00:00Z",
        now_utc="2026-05-04T20:00:00Z",
        current_btc_price=75000.0,
        initial_capital=100000.0,
        snapshot_id="s1", run_id="r1",
        snapshot_at_utc="2026-05-04T20:00:00Z",
    )
    # 只 o_entry 触发
    assert len(res["filled_orders"]) == 1
    assert res["filled_orders"][0]["order_id"] == "o_entry"
    # stop / tp 在 skipped
    skipped_ids = {s["order_id"] for s in res["skipped_orders"]}
    assert skipped_ids == {"o_stop", "o_tp"}
    # 它们仍 pending(没被 fill,也没 expired)
    pending = VirtualOrdersDAO.get_pending(conn)
    assert {p["order_id"] for p in pending} == {"o_stop", "o_tp"}


def test_orders_filtered_by_thesis_id(conn):
    """只触发指定 thesis 的挂单,其他 thesis 的不动。"""
    _make_thesis(conn, thesis_id="th1")
    _make_thesis(conn, thesis_id="th2")
    _make_order(conn, "o_th1", price=74000.0, thesis_id="th1")
    _make_order(conn, "o_th2", price=74000.0, thesis_id="th2")
    _insert_kline(conn, "2026-05-04T10:00:00Z", low=73000.0, high=76000.0)
    conn.commit()

    res = check_and_fill_orders(
        conn, thesis_id="th1",
        last_check_utc="2026-05-04T00:00:00Z",
        now_utc="2026-05-04T20:00:00Z",
        current_btc_price=74500.0,
        initial_capital=100000.0,
        snapshot_id="s1", run_id="r1",
        snapshot_at_utc="2026-05-04T20:00:00Z",
    )
    assert len(res["filled_orders"]) == 1
    assert res["filled_orders"][0]["order_id"] == "o_th1"
    # th2 仍 pending
    th2_pending = VirtualOrdersDAO.get_pending(conn, thesis_id="th2")
    assert len(th2_pending) == 1


def test_deterministic_tie_break_order_id_lex(conn):
    """同 K 线内多触发 → 按 order_id 字典序触发(确定性)。"""
    _make_thesis(conn)
    _make_order(conn, "z_last", price=74000.0)
    _make_order(conn, "a_first", price=72000.0)
    _make_order(conn, "m_mid", price=73000.0)
    _insert_kline(conn, "2026-05-04T10:00:00Z", low=70000.0, high=76000.0)
    conn.commit()

    res = check_and_fill_orders(
        conn, thesis_id="th1",
        last_check_utc="2026-05-04T00:00:00Z",
        now_utc="2026-05-04T20:00:00Z",
        current_btc_price=73000.0,
        initial_capital=100000.0,
        snapshot_id="s1", run_id="r1",
        snapshot_at_utc="2026-05-04T20:00:00Z",
    )
    # 全 fill
    ids_in_order = [f["order_id"] for f in res["filled_orders"]]
    assert ids_in_order == ["a_first", "m_mid", "z_last"]


def test_computed_snapshot_uses_prev_snapshot(conn):
    """已有 prev_snapshot 时 → 加仓,avg_price 重算。"""
    _make_thesis(conn)
    # 先写一个 prev snapshot(已有 long 0.25 BTC @ 80000)
    VirtualAccountDAO.insert_snapshot(
        conn,
        snapshot_id="prev", run_id="run_prev",
        snapshot_at_utc="2026-05-03T08:00:00Z",
        btc_price_at_snapshot=80000.0,
        initial_capital=100000.0,
        available_cash=80000.0,
        long_position_usdt=20000.0,
        long_avg_price=80000.0,
        long_btc_amount=0.25,
        total_equity=100000.0,
    )
    # 新挂单加仓 @ 75000
    _make_order(conn, "o_add", price=75000.0, size_usdt=20000.0)
    _insert_kline(conn, "2026-05-04T10:00:00Z", low=73000.0, high=76000.0)
    conn.commit()

    res = check_and_fill_orders(
        conn, thesis_id="th1",
        last_check_utc="2026-05-04T00:00:00Z",
        now_utc="2026-05-04T20:00:00Z",
        current_btc_price=75000.0,
        initial_capital=100000.0,
        snapshot_id="s_new", run_id="r_new",
        snapshot_at_utc="2026-05-04T20:00:00Z",
    )
    assert len(res["filled_orders"]) == 1
    snap = res["computed_snapshot_for_account"]
    assert snap["long_position_usdt"] == 40000.0
    expected_btc = 0.25 + 20000.0 / 75000.0
    assert abs(snap["long_btc_amount"] - expected_btc) < 1e-6
    expected_avg = 40000.0 / expected_btc
    assert abs(snap["long_avg_price"] - expected_avg) < 0.01
    # 浮亏
    assert snap["unrealized_pnl"] < 0
