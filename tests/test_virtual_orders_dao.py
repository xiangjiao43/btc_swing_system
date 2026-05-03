"""Sprint 1.10-A 单测:VirtualOrdersDAO(v1.4 §5.2)。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.data.storage.dao import VirtualOrdersDAO


_MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "migrations" / "009_v14_virtual_account_thesis.sql"
)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE strategy_runs (run_id TEXT PRIMARY KEY)")
    c.executescript(_MIGRATION.read_text(encoding="utf-8"))
    yield c
    c.close()


def _make_order(conn, **overrides):
    defaults = dict(
        order_id="o1",
        thesis_id="th1",
        direction="long",
        order_type="entry",
        price=74568.0,
        size_pct=0.20,
        size_usdt=20000.0,
        created_at_utc="2026-05-03T08:00:00Z",
        expires_at_utc="2026-05-10T08:00:00Z",  # +7 天
    )
    defaults.update(overrides)
    VirtualOrdersDAO.create_order(conn, **defaults)


# ============================================================
# happy path
# ============================================================

def test_create_and_get_pending(conn):
    _make_order(conn)
    conn.commit()
    pending = VirtualOrdersDAO.get_pending(conn)
    assert len(pending) == 1
    assert pending[0]["order_id"] == "o1"
    assert pending[0]["status"] == "pending"
    assert pending[0]["price"] == 74568.0


def test_fill_order(conn):
    _make_order(conn)
    n = VirtualOrdersDAO.fill_order(
        conn, order_id="o1",
        filled_at_utc="2026-05-04T10:00:00Z",
        filled_price=74568.0,           # = price (§5.2.4)
        filled_btc_amount=0.2682,        # = 20000 / 74568
    )
    conn.commit()
    assert n == 1
    pending = VirtualOrdersDAO.get_pending(conn)
    assert pending == []
    filled = VirtualOrdersDAO.get_filled(conn)
    assert len(filled) == 1
    assert filled[0]["status"] == "filled"
    assert filled[0]["filled_price"] == 74568.0
    assert filled[0]["filled_btc_amount"] == 0.2682


def test_cancel_order(conn):
    _make_order(conn)
    n = VirtualOrdersDAO.cancel_order(conn, "o1", "thesis_invalidated")
    conn.commit()
    assert n == 1
    assert VirtualOrdersDAO.get_pending(conn) == []
    rows = conn.execute("SELECT status, cancelled_reason FROM virtual_orders").fetchall()
    assert rows[0]["status"] == "cancelled"
    assert rows[0]["cancelled_reason"] == "thesis_invalidated"


def test_mark_expired(conn):
    _make_order(conn, order_id="o1", expires_at_utc="2026-05-01T00:00:00Z")  # 已过期
    _make_order(conn, order_id="o2", expires_at_utc="2026-12-01T00:00:00Z")  # 未到期
    n = VirtualOrdersDAO.mark_expired(conn, now_utc="2026-05-03T08:00:00Z")
    conn.commit()
    assert n == 1
    rows = conn.execute("SELECT order_id, status FROM virtual_orders ORDER BY order_id").fetchall()
    assert rows[0]["order_id"] == "o1" and rows[0]["status"] == "expired"
    assert rows[1]["order_id"] == "o2" and rows[1]["status"] == "pending"


def test_get_pending_by_thesis(conn):
    _make_order(conn, order_id="oA", thesis_id="th1")
    _make_order(conn, order_id="oB", thesis_id="th2")
    conn.commit()
    by_th1 = VirtualOrdersDAO.get_pending(conn, thesis_id="th1")
    assert len(by_th1) == 1
    assert by_th1[0]["order_id"] == "oA"


def test_multiple_fills_same_thesis(conn):
    """§5.2.5 同 1H 多挂单全触发场景。"""
    _make_order(conn, order_id="oA", price=74568.0, size_pct=0.20, size_usdt=20000.0)
    _make_order(conn, order_id="oB", price=70666.0, size_pct=0.30, size_usdt=30000.0)
    VirtualOrdersDAO.fill_order(conn, "oA", "2026-05-04T10:00:00Z", 74568.0, 0.2682)
    VirtualOrdersDAO.fill_order(conn, "oB", "2026-05-04T10:00:00Z", 70666.0, 0.4245)
    conn.commit()
    filled = VirtualOrdersDAO.get_filled(conn, thesis_id="th1")
    assert len(filled) == 2
    total_btc = sum(f["filled_btc_amount"] for f in filled)
    assert abs(total_btc - 0.6927) < 0.0001


# ============================================================
# edge cases
# ============================================================

def test_fill_nonexistent_returns_zero(conn):
    n = VirtualOrdersDAO.fill_order(conn, "missing", "2026-05-04T10:00:00Z", 74568.0, 0.2682)
    assert n == 0


def test_fill_already_filled_returns_zero(conn):
    _make_order(conn)
    VirtualOrdersDAO.fill_order(conn, "o1", "2026-05-04T10:00:00Z", 74568.0, 0.2682)
    n = VirtualOrdersDAO.fill_order(conn, "o1", "2026-05-04T11:00:00Z", 74568.0, 0.2682)
    assert n == 0  # 已 filled,WHERE status='pending' 拦截


def test_cancel_nonexistent_returns_zero(conn):
    n = VirtualOrdersDAO.cancel_order(conn, "missing", "manual")
    assert n == 0


def test_duplicate_order_id_raises(conn):
    _make_order(conn)
    with pytest.raises(sqlite3.IntegrityError):
        _make_order(conn)  # order_id PK 重复


def test_get_pending_empty(conn):
    assert VirtualOrdersDAO.get_pending(conn) == []
    assert VirtualOrdersDAO.get_filled(conn) == []
