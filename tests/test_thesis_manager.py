"""Sprint 1.10-C 单测:ThesisManager(v1.4 §4.2 / §5.3)。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.data.storage.dao import (
    ThesesDAO, VirtualAccountDAO, VirtualOrdersDAO,
)
from src.strategy.thesis_manager import (
    create_thesis, advance_lifecycle, close_thesis,
)
from src.strategy.virtual_account import compute_snapshot


_MIGRATION_009 = (
    Path(__file__).resolve().parent.parent
    / "migrations" / "009_v14_virtual_account_thesis.sql"
)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE strategy_runs (run_id TEXT PRIMARY KEY)")
    c.executescript(_MIGRATION_009.read_text(encoding="utf-8"))
    yield c
    c.close()


def _spec_long():
    return {
        "direction": "long",
        "core_logic": "test long thesis",
        "confidence_score": 70,
        "break_conditions": ["c1", "c2", "c3"],
        "entry_orders": [
            {"price": 74000.0, "size_pct": 0.20, "size_usdt": 20000.0},
            {"price": 70000.0, "size_pct": 0.30, "size_usdt": 30000.0},
        ],
        "stop_loss_orders": [
            {"price": 67000.0, "size_pct": 1.00, "size_usdt": 50000.0},
        ],
        "take_profit_orders": [
            {"price": 80000.0, "size_pct": 0.50, "size_usdt": 25000.0},
            {"price": 85000.0, "size_pct": 0.50, "size_usdt": 25000.0},
        ],
    }


# ============================================================
# create_thesis
# ============================================================

def test_create_thesis_writes_theses_and_orders(conn):
    res = create_thesis(
        conn, thesis_spec=_spec_long(),
        run_id="run_001", now_utc="2026-05-03T08:00:00Z",
        expires_at_utc="2026-05-10T08:00:00Z",
    )
    conn.commit()
    assert res["thesis_id"].startswith("th_")
    assert len(res["entry_order_ids"]) == 2
    assert len(res["stop_loss_order_ids"]) == 1
    assert len(res["take_profit_order_ids"]) == 2

    th = ThesesDAO.get_active(conn)
    assert th is not None
    assert th["direction"] == "long"
    assert th["lifecycle_stage"] == "planned"
    assert th["status"] == "active"
    assert len(th["break_conditions"]) == 3

    # 5 个挂单 pending
    pending = VirtualOrdersDAO.get_pending(conn)
    assert len(pending) == 5


def test_create_thesis_short(conn):
    spec = _spec_long()
    spec["direction"] = "short"
    res = create_thesis(
        conn, thesis_spec=spec,
        run_id="run_002", now_utc="2026-05-03T08:00:00Z",
        expires_at_utc="2026-05-10T08:00:00Z",
    )
    conn.commit()
    th = ThesesDAO.get_active(conn)
    assert th["direction"] == "short"


def test_create_thesis_invalid_direction_raises(conn):
    spec = _spec_long()
    spec["direction"] = "neutral"
    with pytest.raises(ValueError):
        create_thesis(
            conn, thesis_spec=spec, run_id="r", now_utc="t", expires_at_utc="e",
        )


def test_create_thesis_with_explicit_thesis_id(conn):
    res = create_thesis(
        conn, thesis_spec=_spec_long(), run_id="r1",
        now_utc="2026-05-03T08:00:00Z",
        expires_at_utc="2026-05-10T08:00:00Z",
        thesis_id="my_custom_id",
    )
    conn.commit()
    assert res["thesis_id"] == "my_custom_id"


# ============================================================
# advance_lifecycle — 5 档迁移
# ============================================================

def test_planned_to_opened(conn):
    res = create_thesis(conn, thesis_spec=_spec_long(),
                        run_id="r1", now_utc="2026-05-03T08:00:00Z",
                        expires_at_utc="2026-05-10T08:00:00Z",
                        thesis_id="th1")
    conn.commit()

    # 模拟 1 entry filled
    entry_id = res["entry_order_ids"][0]
    VirtualOrdersDAO.fill_order(conn, entry_id, "2026-05-04T10:00:00Z", 74000.0, 20000.0/74000.0)
    conn.commit()

    fills = [{
        "order_id": entry_id, "thesis_id": "th1", "direction": "long",
        "order_type": "entry", "size_usdt": 20000.0,
        "filled_price": 74000.0, "filled_btc_amount": 20000.0/74000.0,
        "filled_at_utc": "2026-05-04T10:00:00Z",
    }]
    r = advance_lifecycle(
        conn, thesis_id="th1", fills=fills,
        prev_snapshot=None, current_btc_price=74000.0,
        now_utc="2026-05-04T10:01:00Z",
    )
    assert r["old_stage"] == "planned"
    assert r["new_stage"] == "opened"
    assert not r["ready_to_close"]


def test_opened_to_holding_requires_24h_and_pnl(conn):
    """opened → holding 需 24h + 浮盈 ≥ 2%。"""
    res = create_thesis(conn, thesis_spec=_spec_long(),
                        run_id="r1", now_utc="2026-05-03T08:00:00Z",
                        expires_at_utc="2026-05-10T08:00:00Z",
                        thesis_id="th1")
    conn.commit()
    entry_id = res["entry_order_ids"][0]
    VirtualOrdersDAO.fill_order(conn, entry_id, "2026-05-04T10:00:00Z", 74000.0, 20000.0/74000.0)
    conn.execute("UPDATE theses SET lifecycle_stage='opened' WHERE thesis_id='th1'")
    conn.commit()

    prev_snap = {
        "long_avg_price": 74000.0, "long_btc_amount": 20000.0/74000.0,
        "long_position_usdt": 20000.0, "available_cash": 80000.0,
        "short_avg_price": None, "short_btc_amount": 0.0,
        "short_position_usdt": 0.0, "realized_pnl_total": 0.0,
    }
    # 不到 24h → 不推进
    r1 = advance_lifecycle(
        conn, thesis_id="th1", fills=[],
        prev_snapshot=prev_snap, current_btc_price=76000.0,  # +2.7%
        now_utc="2026-05-04T20:00:00Z",  # 距 fill 仅 10h
    )
    assert r1["new_stage"] == "opened"  # 没推进

    # 24h+ 但浮盈 < 2% → 不推进
    r2 = advance_lifecycle(
        conn, thesis_id="th1", fills=[],
        prev_snapshot=prev_snap, current_btc_price=74500.0,  # +0.68%
        now_utc="2026-05-05T11:00:00Z",  # +25h
    )
    assert r2["new_stage"] == "opened"

    # 24h+ + 浮盈 ≥ 2% → holding
    r3 = advance_lifecycle(
        conn, thesis_id="th1", fills=[],
        prev_snapshot=prev_snap, current_btc_price=76000.0,  # +2.7%
        now_utc="2026-05-05T11:00:00Z",
    )
    assert r3["new_stage"] == "holding"


def test_holding_to_trim_on_tp_fill(conn):
    res = create_thesis(conn, thesis_spec=_spec_long(),
                        run_id="r1", now_utc="2026-05-03T08:00:00Z",
                        expires_at_utc="2026-05-10T08:00:00Z",
                        thesis_id="th1")
    conn.execute("UPDATE theses SET lifecycle_stage='holding' WHERE thesis_id='th1'")
    conn.commit()

    tp_id = res["take_profit_order_ids"][0]
    VirtualOrdersDAO.fill_order(conn, tp_id, "2026-05-10T08:00:00Z", 80000.0, 25000.0/80000.0)
    conn.commit()
    fills = [{
        "order_id": tp_id, "thesis_id": "th1", "direction": "long",
        "order_type": "take_profit", "size_usdt": 25000.0,
        "filled_price": 80000.0, "filled_btc_amount": 25000.0/80000.0,
        "filled_at_utc": "2026-05-10T08:00:00Z",
    }]
    r = advance_lifecycle(
        conn, thesis_id="th1", fills=fills,
        prev_snapshot=None, current_btc_price=80000.0,
        now_utc="2026-05-10T08:01:00Z",
    )
    assert r["new_stage"] == "trim"
    assert not r["ready_to_close"]  # 还有 1 个 tp 未 filled


def test_trim_to_ready_to_close_when_all_tp_filled(conn):
    res = create_thesis(conn, thesis_spec=_spec_long(),
                        run_id="r1", now_utc="2026-05-03T08:00:00Z",
                        expires_at_utc="2026-05-10T08:00:00Z",
                        thesis_id="th1")
    conn.execute("UPDATE theses SET lifecycle_stage='trim' WHERE thesis_id='th1'")
    # 全部 tp filled
    for i, tp_id in enumerate(res["take_profit_order_ids"]):
        VirtualOrdersDAO.fill_order(
            conn, tp_id, f"2026-05-10T0{8+i}:00:00Z",
            float(80000 + i * 5000), 25000.0 / (80000 + i * 5000),
        )
    conn.commit()
    fills = [{
        "order_id": res["take_profit_order_ids"][1], "thesis_id": "th1",
        "direction": "long", "order_type": "take_profit",
        "size_usdt": 25000.0, "filled_price": 85000.0,
        "filled_btc_amount": 25000.0/85000.0,
        "filled_at_utc": "2026-05-10T09:00:00Z",
    }]
    r = advance_lifecycle(
        conn, thesis_id="th1", fills=fills,
        prev_snapshot=None, current_btc_price=85000.0,
        now_utc="2026-05-10T09:01:00Z",
    )
    assert r["ready_to_close"]
    assert r["close_reason"] == "all_take_profit_filled"


def test_stop_loss_fill_triggers_ready_to_close(conn):
    res = create_thesis(conn, thesis_spec=_spec_long(),
                        run_id="r1", now_utc="2026-05-03T08:00:00Z",
                        expires_at_utc="2026-05-10T08:00:00Z",
                        thesis_id="th1")
    conn.execute("UPDATE theses SET lifecycle_stage='holding' WHERE thesis_id='th1'")
    conn.commit()

    sl_id = res["stop_loss_order_ids"][0]
    fills = [{
        "order_id": sl_id, "thesis_id": "th1", "direction": "long",
        "order_type": "stop_loss", "size_usdt": 50000.0,
        "filled_price": 67000.0, "filled_btc_amount": 50000.0/67000.0,
        "filled_at_utc": "2026-05-08T14:00:00Z",
    }]
    r = advance_lifecycle(
        conn, thesis_id="th1", fills=fills,
        prev_snapshot=None, current_btc_price=67000.0,
        now_utc="2026-05-08T14:01:00Z",
    )
    assert r["ready_to_close"]
    assert r["close_reason"] == "stop_loss_filled"


def test_advance_no_fills_no_change(conn):
    create_thesis(conn, thesis_spec=_spec_long(),
                  run_id="r1", now_utc="2026-05-03T08:00:00Z",
                  expires_at_utc="2026-05-10T08:00:00Z", thesis_id="th1")
    conn.commit()
    r = advance_lifecycle(
        conn, thesis_id="th1", fills=[],
        prev_snapshot=None, current_btc_price=74000.0,
        now_utc="2026-05-04T10:00:00Z",
    )
    assert r["old_stage"] == r["new_stage"] == "planned"
    assert not r["ready_to_close"]


def test_advance_closed_thesis_returns_skipped(conn):
    """closed thesis 不能 advance(防御)。"""
    create_thesis(conn, thesis_spec=_spec_long(),
                  run_id="r1", now_utc="2026-05-03T08:00:00Z",
                  expires_at_utc="2026-05-10T08:00:00Z", thesis_id="th1")
    conn.execute(
        "UPDATE theses SET status='closed_profit', lifecycle_stage='closed' "
        "WHERE thesis_id='th1'"
    )
    conn.commit()
    r = advance_lifecycle(
        conn, thesis_id="th1", fills=[],
        prev_snapshot=None, current_btc_price=80000.0,
        now_utc="2026-05-15T08:00:00Z",
    )
    assert r["new_stage"] == "closed"
    assert "skipped_reason" in r


def test_advance_unknown_thesis_raises(conn):
    with pytest.raises(ValueError):
        advance_lifecycle(
            conn, thesis_id="missing", fills=[],
            prev_snapshot=None, current_btc_price=74000.0,
            now_utc="2026-05-04T10:00:00Z",
        )


# ============================================================
# close_thesis
# ============================================================

def _setup_open_long_position(conn, thesis_id="th1"):
    """辅助:创建已开仓的 long thesis。"""
    create_thesis(
        conn, thesis_spec=_spec_long(),
        run_id="r1", now_utc="2026-05-03T08:00:00Z",
        expires_at_utc="2026-05-10T08:00:00Z", thesis_id=thesis_id,
    )
    # prev snapshot:已持仓 0.27027... BTC @ 74000
    btc = 20000.0 / 74000.0
    VirtualAccountDAO.insert_snapshot(
        conn, snapshot_id="prev", run_id="r1",
        snapshot_at_utc="2026-05-04T08:00:00Z",
        btc_price_at_snapshot=74000.0,
        initial_capital=100000.0,
        available_cash=80000.0,
        long_position_usdt=20000.0,
        long_avg_price=74000.0,
        long_btc_amount=btc,
        total_equity=100000.0,
    )
    conn.commit()


def test_close_thesis_with_take_profit_profit(conn):
    """全 tp 触发 → closed_profit + realized_pnl > 0。"""
    _setup_open_long_position(conn)
    fills_for_close = [{
        "order_id": "x_tp", "thesis_id": "th1", "direction": "long",
        "order_type": "take_profit", "size_usdt": 20000.0,
        "filled_price": 80000.0,
        "filled_btc_amount": 20000.0/74000.0,  # 全平
        "filled_at_utc": "2026-05-10T08:00:00Z",
    }]
    res = close_thesis(
        conn, thesis_id="th1",
        reason="all_take_profit_filled",
        close_channel="A",
        closed_at_utc="2026-05-10T08:00:00Z",
        fills_for_close=fills_for_close,
        current_btc_price=80000.0,
        initial_capital=100000.0,
        snapshot_id="snap_close", run_id="r_close",
        snapshot_at_utc="2026-05-10T08:01:00Z",
    )
    conn.commit()
    assert res["status"] == "closed_profit"
    assert res["close_channel"] == "A"
    assert res["final_outcome"] == "profit"
    # PnL = 0.27027 BTC * (80000 - 74000) = 1621.62
    assert abs(res["final_realized_pnl"] - 1621.6216216) < 0.01
    assert res["final_realized_pnl_pct"] > 0
    # 残余挂单全 cancel
    pending = VirtualOrdersDAO.get_pending(conn, thesis_id="th1")
    assert pending == []
    # theses 状态
    th = conn.execute("SELECT * FROM theses WHERE thesis_id='th1'").fetchone()
    assert th["status"] == "closed_profit"
    assert th["closed_at_utc"] == "2026-05-10T08:00:00Z"
    assert th["lifecycle_stage"] == "closed"


def test_close_thesis_with_stop_loss_loss(conn):
    """stop_loss 触发 → closed_loss + realized_pnl < 0。"""
    _setup_open_long_position(conn)
    fills_for_close = [{
        "order_id": "x_sl", "thesis_id": "th1", "direction": "long",
        "order_type": "stop_loss", "size_usdt": 20000.0,
        "filled_price": 67000.0,
        "filled_btc_amount": 20000.0/74000.0,
        "filled_at_utc": "2026-05-08T14:00:00Z",
    }]
    res = close_thesis(
        conn, thesis_id="th1",
        reason="stop_loss_filled", close_channel="A",
        closed_at_utc="2026-05-08T14:00:00Z",
        fills_for_close=fills_for_close,
        current_btc_price=67000.0,
        initial_capital=100000.0,
        snapshot_id="snap_sl", run_id="r_sl",
        snapshot_at_utc="2026-05-08T14:01:00Z",
    )
    conn.commit()
    assert res["status"] == "closed_loss"
    # PnL = 0.27027 * (67000 - 74000) = -1891.89
    assert res["final_realized_pnl"] < 0
    assert abs(res["final_realized_pnl"] + 1891.8918918) < 0.01


def test_close_thesis_invalidated_channel_b(conn):
    """break 触发 → invalidated + 通道 B。"""
    _setup_open_long_position(conn)
    fills_for_close = [{
        "order_id": "x_inv", "thesis_id": "th1", "direction": "long",
        "order_type": "stop_loss", "size_usdt": 20000.0,
        "filled_price": 70000.0,
        "filled_btc_amount": 20000.0/74000.0,
        "filled_at_utc": "2026-05-09T10:00:00Z",
    }]
    res = close_thesis(
        conn, thesis_id="th1",
        reason="invalidated", close_channel="B",
        closed_at_utc="2026-05-09T10:00:00Z",
        fills_for_close=fills_for_close,
        current_btc_price=70000.0,
        initial_capital=100000.0,
        snapshot_id="snap_inv", run_id="r_inv",
        snapshot_at_utc="2026-05-09T10:01:00Z",
        invalidated_reason="DXY 突破 110 持续 3 天 已触发",
    )
    conn.commit()
    assert res["status"] == "invalidated"
    assert res["close_channel"] == "B"
    th = conn.execute("SELECT invalidated_reason FROM theses WHERE thesis_id='th1'").fetchone()
    assert th["invalidated_reason"] == "DXY 突破 110 持续 3 天 已触发"


def test_close_thesis_unknown_reason_raises(conn):
    _setup_open_long_position(conn)
    with pytest.raises(ValueError):
        close_thesis(
            conn, thesis_id="th1",
            reason="hallucinated_reason", close_channel="A",
            closed_at_utc="2026-05-10T08:00:00Z",
            fills_for_close=[], current_btc_price=80000.0,
            initial_capital=100000.0,
            snapshot_id="x", run_id="x", snapshot_at_utc="x",
        )


def test_close_thesis_cancels_pending_orders(conn):
    """close 后所有 pending 挂单 cancelled。"""
    _setup_open_long_position(conn)
    pending_before = VirtualOrdersDAO.get_pending(conn, thesis_id="th1")
    assert len(pending_before) >= 3  # 至少剩余 entry + sl + tp
    fills_for_close = [{
        "order_id": "x_tp", "thesis_id": "th1", "direction": "long",
        "order_type": "take_profit", "size_usdt": 20000.0,
        "filled_price": 80000.0,
        "filled_btc_amount": 20000.0/74000.0,
        "filled_at_utc": "2026-05-10T08:00:00Z",
    }]
    res = close_thesis(
        conn, thesis_id="th1",
        reason="all_take_profit_filled", close_channel="A",
        closed_at_utc="2026-05-10T08:00:00Z",
        fills_for_close=fills_for_close,
        current_btc_price=80000.0,
        initial_capital=100000.0,
        snapshot_id="snap_x", run_id="r_x",
        snapshot_at_utc="2026-05-10T08:01:00Z",
    )
    conn.commit()
    assert res["cancelled_pending_count"] >= 3
    pending_after = VirtualOrdersDAO.get_pending(conn, thesis_id="th1")
    assert pending_after == []


def test_compute_snapshot_handles_close_fills_long(conn):
    """compute_snapshot 扩展处理 long close fill(扣减 position + 算 PnL)。"""
    prev = {
        "long_position_usdt": 20000.0,
        "long_avg_price": 74000.0,
        "long_btc_amount": 20000.0 / 74000.0,
        "short_position_usdt": 0.0, "short_avg_price": None, "short_btc_amount": 0.0,
        "available_cash": 80000.0,
        "realized_pnl_total": 0.0,
    }
    # take_profit @ 80000 卖出 0.135135 BTC(一半)
    snap = compute_snapshot(
        prev_snapshot=prev,
        current_btc_price=80000.0,
        fills_since_last=[{
            "direction": "long", "order_type": "take_profit",
            "size_usdt": 10000.0, "filled_price": 80000.0,
            "filled_btc_amount": (20000.0/74000.0) / 2,
        }],
        initial_capital=100000.0,
        snapshot_id="s", run_id="r",
        snapshot_at_utc="2026-05-10T08:00:00Z",
    )
    # 平掉一半:long_btc_amount 减半
    expected_remaining_btc = (20000.0/74000.0) / 2
    assert abs(snap["long_btc_amount"] - expected_remaining_btc) < 1e-6
    # PnL = 0.13513 * (80000 - 74000) = 810.81
    assert abs(snap["realized_pnl_total"] - 810.8108) < 0.01
    # available_cash 增加 = 0.13513 * 80000 = 10810.81
    assert abs(snap["available_cash"] - (80000 + 10810.8108)) < 0.01


def test_compute_snapshot_close_short_position(conn):
    """short 平仓:price 跌 → realized_pnl > 0。"""
    btc = 20000.0 / 80000.0  # 0.25 BTC short @ 80000
    prev = {
        "long_position_usdt": 0.0, "long_avg_price": None, "long_btc_amount": 0.0,
        "short_position_usdt": 20000.0,
        "short_avg_price": 80000.0,
        "short_btc_amount": btc,
        "available_cash": 80000.0,
        "realized_pnl_total": 0.0,
    }
    # take_profit short:买回 BTC @ 76000(price 跌了)
    snap = compute_snapshot(
        prev_snapshot=prev,
        current_btc_price=76000.0,
        fills_since_last=[{
            "direction": "short", "order_type": "take_profit",
            "size_usdt": 19000.0, "filled_price": 76000.0,
            "filled_btc_amount": btc,
        }],
        initial_capital=100000.0,
        snapshot_id="s", run_id="r",
        snapshot_at_utc="2026-05-10T08:00:00Z",
    )
    # 全平
    assert snap["short_btc_amount"] == 0
    # PnL = 0.25 * (80000 - 76000) = 1000
    assert abs(snap["realized_pnl_total"] - 1000.0) < 1e-6


def test_compute_snapshot_over_fill_capped(conn):
    """over-fill 防御:实际平 BTC ≤ 现持仓。"""
    prev = {
        "long_position_usdt": 20000.0,
        "long_avg_price": 74000.0,
        "long_btc_amount": 0.10,  # 假定只剩 0.10
        "short_position_usdt": 0.0, "short_avg_price": None, "short_btc_amount": 0.0,
        "available_cash": 80000.0,
        "realized_pnl_total": 0.0,
    }
    # 试图平 0.50(超过持仓)
    snap = compute_snapshot(
        prev_snapshot=prev,
        current_btc_price=80000.0,
        fills_since_last=[{
            "direction": "long", "order_type": "take_profit",
            "size_usdt": 40000.0, "filled_price": 80000.0,
            "filled_btc_amount": 0.50,  # over
        }],
        initial_capital=100000.0,
        snapshot_id="s", run_id="r",
        snapshot_at_utc="2026-05-10T08:00:00Z",
    )
    # 只能平 0.10
    assert snap["long_btc_amount"] == 0.0
    assert snap["long_position_usdt"] == 0.0
    # PnL = 0.10 * (80000 - 74000) = 600(只算实际平的)
    assert abs(snap["realized_pnl_total"] - 600.0) < 1e-6


# ============================================================
# 集成:planned → opened → ready_to_close 完整周期
# ============================================================

def test_full_lifecycle_long_profit(conn):
    """planned → opened → trim → close (profit)。"""
    res = create_thesis(
        conn, thesis_spec=_spec_long(),
        run_id="r1", now_utc="2026-05-03T08:00:00Z",
        expires_at_utc="2026-05-10T08:00:00Z", thesis_id="th_full",
    )
    conn.commit()

    # 1. entry filled → opened
    eid = res["entry_order_ids"][0]
    VirtualOrdersDAO.fill_order(conn, eid, "2026-05-04T10:00:00Z", 74000.0, 20000.0/74000.0)
    conn.commit()
    fills_entry = [{
        "order_id": eid, "thesis_id": "th_full", "direction": "long",
        "order_type": "entry", "size_usdt": 20000.0,
        "filled_price": 74000.0, "filled_btc_amount": 20000.0/74000.0,
        "filled_at_utc": "2026-05-04T10:00:00Z",
    }]
    r1 = advance_lifecycle(
        conn, thesis_id="th_full", fills=fills_entry,
        prev_snapshot=None, current_btc_price=74000.0,
        now_utc="2026-05-04T10:01:00Z",
    )
    assert r1["new_stage"] == "opened"
    conn.commit()

    # 2. tp filled → trim(skip holding,直接 trim)
    tid = res["take_profit_order_ids"][0]
    VirtualOrdersDAO.fill_order(conn, tid, "2026-05-10T08:00:00Z", 80000.0, 25000.0/80000.0)
    conn.execute(
        "UPDATE theses SET lifecycle_stage='holding' WHERE thesis_id='th_full'"
    )
    conn.commit()
    fills_tp = [{
        "order_id": tid, "thesis_id": "th_full", "direction": "long",
        "order_type": "take_profit", "size_usdt": 25000.0,
        "filled_price": 80000.0, "filled_btc_amount": 25000.0/80000.0,
        "filled_at_utc": "2026-05-10T08:00:00Z",
    }]
    r2 = advance_lifecycle(
        conn, thesis_id="th_full", fills=fills_tp,
        prev_snapshot=None, current_btc_price=80000.0,
        now_utc="2026-05-10T08:01:00Z",
    )
    assert r2["new_stage"] == "trim"

    # 3. 第二个 tp filled → ready_to_close
    tid2 = res["take_profit_order_ids"][1]
    VirtualOrdersDAO.fill_order(conn, tid2, "2026-05-10T09:00:00Z", 85000.0, 25000.0/85000.0)
    conn.commit()
    fills_tp2 = [{
        "order_id": tid2, "thesis_id": "th_full", "direction": "long",
        "order_type": "take_profit", "size_usdt": 25000.0,
        "filled_price": 85000.0, "filled_btc_amount": 25000.0/85000.0,
        "filled_at_utc": "2026-05-10T09:00:00Z",
    }]
    r3 = advance_lifecycle(
        conn, thesis_id="th_full", fills=fills_tp2,
        prev_snapshot=None, current_btc_price=85000.0,
        now_utc="2026-05-10T09:01:00Z",
    )
    assert r3["ready_to_close"]
    assert r3["close_reason"] == "all_take_profit_filled"


# ============================================================
# Sprint 1.10-L commit 4:close_thesis 幂等检查(P0 #2 方案 (A) 双调用)
# ============================================================

def _close_long_first_time(conn, thesis_id="th_idem"):
    """辅助:open + close 一次,返回首次 close result。"""
    _setup_open_long_position(conn, thesis_id=thesis_id)
    fills = [{
        "order_id": "x_sl", "thesis_id": thesis_id, "direction": "long",
        "order_type": "stop_loss", "size_usdt": 20000.0,
        "filled_price": 67000.0,
        "filled_btc_amount": 20000.0 / 74000.0,
        "filled_at_utc": "2026-05-08T14:00:00Z",
    }]
    res = close_thesis(
        conn, thesis_id=thesis_id,
        reason="stop_loss_filled",
        close_channel="A",
        closed_at_utc="2026-05-08T14:00:00Z",
        fills_for_close=fills,
        current_btc_price=67000.0,
        initial_capital=100000.0,
        snapshot_id="snap_close1", run_id="r_close1",
        snapshot_at_utc="2026-05-08T14:01:00Z",
    )
    conn.commit()
    return res


def test_close_thesis_idempotent_already_closed_loss(conn):
    """第一次 close → status='closed_loss';第二次 close → noop_already_closed。"""
    r1 = _close_long_first_time(conn, thesis_id="th_idem_1")
    assert r1["status"] == "closed_loss"
    assert r1.get("noop_already_closed") is None  # 第一次不是 noop
    # 第二次 close(模拟 hard_invalidation_monitor + lifecycle_manager 双调用)
    r2 = close_thesis(
        conn, thesis_id="th_idem_1",
        reason="invalidated",                # 不同 reason 也应 noop
        close_channel="B",
        closed_at_utc="2026-05-08T15:00:00Z",
        fills_for_close=[],
        current_btc_price=67500.0,
        initial_capital=100000.0,
        snapshot_id="snap_close2", run_id="r_close2",
        snapshot_at_utc="2026-05-08T15:01:00Z",
    )
    assert r2["noop_already_closed"] is True
    # status 不变(仍是首次 close 的 closed_loss),不被 invalidated 覆盖
    assert r2["status"] == "closed_loss"
    assert r2["close_channel"] == "A"           # 首次的 channel,未被覆盖
    assert r2["rows_updated"] == 0
    assert r2["cancelled_pending_count"] == 0
    th = conn.execute(
        "SELECT status, close_channel FROM theses WHERE thesis_id=?",
        ("th_idem_1",),
    ).fetchone()
    assert th["status"] == "closed_loss"
    assert th["close_channel"] == "A"


def test_close_thesis_idempotent_closed_profit(conn):
    """closed_profit 也是 CLOSED_STATUSES 之一,二次 close 应 noop。"""
    _setup_open_long_position(conn, thesis_id="th_idem_p")
    fills_tp = [{
        "order_id": "x_tp", "thesis_id": "th_idem_p", "direction": "long",
        "order_type": "take_profit", "size_usdt": 20000.0,
        "filled_price": 80000.0,
        "filled_btc_amount": 20000.0 / 74000.0,
        "filled_at_utc": "2026-05-10T08:00:00Z",
    }]
    r1 = close_thesis(
        conn, thesis_id="th_idem_p",
        reason="all_take_profit_filled",
        close_channel="A",
        closed_at_utc="2026-05-10T08:00:00Z",
        fills_for_close=fills_tp,
        current_btc_price=80000.0,
        initial_capital=100000.0,
        snapshot_id="snap_p1", run_id="r_p1",
        snapshot_at_utc="2026-05-10T08:01:00Z",
    )
    conn.commit()
    assert r1["status"] == "closed_profit"
    # 第二次 close
    r2 = close_thesis(
        conn, thesis_id="th_idem_p",
        reason="stop_loss_filled",
        close_channel="C",
        closed_at_utc="2026-05-10T09:00:00Z",
        fills_for_close=[],
        current_btc_price=80500.0,
        initial_capital=100000.0,
        snapshot_id="snap_p2", run_id="r_p2",
        snapshot_at_utc="2026-05-10T09:01:00Z",
    )
    assert r2["noop_already_closed"] is True
    assert r2["status"] == "closed_profit"


def test_close_thesis_idempotent_invalidated(conn):
    """invalidated 也在 CLOSED_STATUSES,二次 close 应 noop。"""
    _setup_open_long_position(conn, thesis_id="th_idem_inv")
    r1 = close_thesis(
        conn, thesis_id="th_idem_inv",
        reason="invalidated",
        close_channel="B",
        closed_at_utc="2026-05-08T14:00:00Z",
        fills_for_close=[],
        current_btc_price=67000.0,
        initial_capital=100000.0,
        snapshot_id="snap_i1", run_id="r_i1",
        snapshot_at_utc="2026-05-08T14:01:00Z",
        invalidated_reason="break_condition_1 触发",
    )
    conn.commit()
    assert r1["status"] == "invalidated"
    r2 = close_thesis(
        conn, thesis_id="th_idem_inv",
        reason="stop_loss_filled",
        close_channel="A",
        closed_at_utc="2026-05-08T15:00:00Z",
        fills_for_close=[],
        current_btc_price=66500.0,
        initial_capital=100000.0,
        snapshot_id="snap_i2", run_id="r_i2",
        snapshot_at_utc="2026-05-08T15:01:00Z",
    )
    assert r2["noop_already_closed"] is True
    assert r2["status"] == "invalidated"


def test_close_thesis_first_close_normal_no_noop_flag(conn):
    """正常第一次 close → noop_already_closed key 不在返回 dict(只在 noop 时才有)。"""
    r = _close_long_first_time(conn, thesis_id="th_idem_first")
    assert r["status"] == "closed_loss"
    assert "noop_already_closed" not in r           # 第一次正常 close,无标记
    assert r["rows_updated"] == 1                   # 真写入


def test_close_thesis_idempotent_unknown_thesis_still_works_normally(conn):
    """thesis_id 不存在 → get_by_id 返 None → 正常走 close 流程(后续 ThesesDAO.close 可能 rowcount=0)。"""
    # 不 seed thesis,直接 close
    res = close_thesis(
        conn, thesis_id="th_does_not_exist",
        reason="stop_loss_filled",
        close_channel="A",
        closed_at_utc="2026-05-08T14:00:00Z",
        fills_for_close=[],
        current_btc_price=70000.0,
        initial_capital=100000.0,
        snapshot_id="snap_x", run_id="r_x",
        snapshot_at_utc="2026-05-08T14:01:00Z",
    )
    # 不是 noop(没 closed status)— 正常走完,rows_updated=0(thesis 不存在)
    assert "noop_already_closed" not in res
    assert res["rows_updated"] == 0
