"""Sprint 1.10-A 单测:VirtualAccountDAO(v1.4 §5.1)。

用 in-memory SQLite,不污染真实 DB。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.data.storage.dao import VirtualAccountDAO


_MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "migrations" / "009_v14_virtual_account_thesis.sql"
)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    # FK target stub
    c.execute("CREATE TABLE strategy_runs (run_id TEXT PRIMARY KEY)")
    c.executescript(_MIGRATION.read_text(encoding="utf-8"))
    yield c
    c.close()


# ============================================================
# happy path
# ============================================================

def test_insert_and_get_latest(conn):
    """insert_snapshot 后 get_latest 返回该行。"""
    VirtualAccountDAO.insert_snapshot(
        conn,
        snapshot_id="snap_001",
        run_id="run_001",
        snapshot_at_utc="2026-05-03T08:00:00Z",
        btc_price_at_snapshot=80000.0,
        initial_capital=100000.0,
        available_cash=100000.0,
        total_equity=100000.0,
    )
    conn.commit()

    latest = VirtualAccountDAO.get_latest(conn)
    assert latest is not None
    assert latest["snapshot_id"] == "snap_001"
    assert latest["run_id"] == "run_001"
    assert latest["initial_capital"] == 100000.0
    assert latest["available_cash"] == 100000.0
    assert latest["total_equity"] == 100000.0
    assert latest["long_position_usdt"] == 0.0
    assert latest["short_position_usdt"] == 0.0


def test_get_history_returns_desc_order(conn):
    """get_history 按 snapshot_at_utc DESC 排序。"""
    for i, ts in enumerate([
        "2026-05-01T08:00:00Z",
        "2026-05-02T08:00:00Z",
        "2026-05-03T08:00:00Z",
    ]):
        VirtualAccountDAO.insert_snapshot(
            conn,
            snapshot_id=f"snap_{i}",
            run_id=f"run_{i}",
            snapshot_at_utc=ts,
            btc_price_at_snapshot=80000.0 + i * 100,
            initial_capital=100000.0,
            available_cash=100000.0,
            total_equity=100000.0 + i * 50,
        )
    conn.commit()

    hist = VirtualAccountDAO.get_history(conn, limit=10)
    assert len(hist) == 3
    assert hist[0]["snapshot_at_utc"] == "2026-05-03T08:00:00Z"
    assert hist[2]["snapshot_at_utc"] == "2026-05-01T08:00:00Z"


def test_get_history_respects_limit(conn):
    """limit 参数生效。"""
    for i in range(5):
        VirtualAccountDAO.insert_snapshot(
            conn,
            snapshot_id=f"snap_{i}",
            run_id=f"run_{i}",
            snapshot_at_utc=f"2026-05-0{i+1}T08:00:00Z",
            btc_price_at_snapshot=80000.0,
            initial_capital=100000.0,
            available_cash=100000.0,
            total_equity=100000.0,
        )
    conn.commit()

    hist = VirtualAccountDAO.get_history(conn, limit=2)
    assert len(hist) == 2


# ============================================================
# edge cases
# ============================================================

def test_get_latest_empty_returns_none(conn):
    """无记录返 None,不抛异常。"""
    assert VirtualAccountDAO.get_latest(conn) is None


def test_get_history_empty_returns_empty_list(conn):
    """无记录返空 list。"""
    assert VirtualAccountDAO.get_history(conn) == []


def test_duplicate_run_id_raises(conn):
    """run_id 是 UNIQUE,重复插入抛 IntegrityError。"""
    VirtualAccountDAO.insert_snapshot(
        conn,
        snapshot_id="snap_001",
        run_id="run_dup",
        snapshot_at_utc="2026-05-03T08:00:00Z",
        btc_price_at_snapshot=80000.0,
        initial_capital=100000.0,
        available_cash=100000.0,
        total_equity=100000.0,
    )
    with pytest.raises(sqlite3.IntegrityError):
        VirtualAccountDAO.insert_snapshot(
            conn,
            snapshot_id="snap_002",
            run_id="run_dup",  # ← 重复
            snapshot_at_utc="2026-05-03T09:00:00Z",
            btc_price_at_snapshot=80100.0,
            initial_capital=100000.0,
            available_cash=100000.0,
            total_equity=100000.0,
        )


def test_with_position(conn):
    """带多空仓位 + 浮盈快照。"""
    VirtualAccountDAO.insert_snapshot(
        conn,
        snapshot_id="snap_pos",
        run_id="run_pos",
        snapshot_at_utc="2026-05-03T08:00:00Z",
        btc_price_at_snapshot=82000.0,
        initial_capital=100000.0,
        available_cash=80000.0,
        long_position_usdt=20000.0,
        long_avg_price=80000.0,
        long_btc_amount=0.25,
        total_equity=100500.0,
        realized_pnl_total=0.0,
        unrealized_pnl=500.0,
        total_return_pct=0.5,
    )
    conn.commit()

    latest = VirtualAccountDAO.get_latest(conn)
    assert latest["long_position_usdt"] == 20000.0
    assert latest["long_btc_amount"] == 0.25
    assert latest["unrealized_pnl"] == 500.0
    assert latest["total_return_pct"] == 0.5
