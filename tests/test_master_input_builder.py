"""Sprint 1.10-D 单测:master_input_builder(v1.4 §3.3.6 input)。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.data.storage.dao import (
    ThesesDAO, VirtualAccountDAO, VirtualOrdersDAO,
)
from src.ai.master_input_builder import build_master_input
from src.strategy.fuse_monitor import (
    record_thesis_cycle, record_channel_c_use,
)


_MIGRATION_009 = (
    Path(__file__).resolve().parent.parent
    / "migrations" / "009_v14_virtual_account_thesis.sql"
)
_MIGRATION_010 = (
    Path(__file__).resolve().parent.parent
    / "migrations" / "010_v14_fuse_system_states.sql"
)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE strategy_runs (run_id TEXT PRIMARY KEY)")
    c.executescript(_MIGRATION_009.read_text(encoding="utf-8"))
    c.executescript(_MIGRATION_010.read_text(encoding="utf-8"))
    c.execute("ALTER TABLE theses ADD COLUMN is_60d_capped INTEGER NOT NULL DEFAULT 0")
    yield c
    c.close()


def _layer_outs():
    return {
        "l1": {"regime": "trend_up", "confidence": 0.85},
        "l2": {"stance": "bullish", "stance_confidence_tier": "high"},
        "l3": {"opportunity_grade": "A", "execution_permission": "active_open"},
        "l4": {"risk_level": "elevated", "position_cap_pct": 0.40},
        "l5": {"macro_stance": "neutral"},
    }


# ============================================================
# happy
# ============================================================

def test_no_active_thesis_returns_none(conn):
    """空 DB → active_thesis=None,current_position=None,pending_orders=[]。"""
    res = build_master_input(
        conn, layer_outputs=_layer_outs(),
        current_btc_price=80000.0, now_utc="2026-05-03T08:00:00Z",
    )
    assert res["active_thesis"] is None
    assert res["current_position"] is None
    assert res["pending_orders"] == []
    assert res["cooldown_state"]["in_cooldown"] is False
    assert res["fuse_state"]["in_14d_fuse"] is False
    assert res["fuse_state"]["thesis_cycles_in_14d"] == 0
    assert res["last_5_assessments"] == []
    # L1-L5 透传
    assert res["l1_output"]["regime"] == "trend_up"
    assert res["l3_output"]["opportunity_grade"] == "A"


def test_active_thesis_fields_populated(conn):
    ThesesDAO.create(
        conn, thesis_id="th_active", created_at_run_id="r1",
        created_at_utc="2026-04-25T08:00:00Z",
        direction="long", core_logic="test thesis",
        confidence_score=72,
        break_conditions=["1D 跌破 70000", "DXY 突破 110", "L5 极端"],
        lifecycle_stage="opened",
    )
    conn.commit()
    res = build_master_input(
        conn, layer_outputs=_layer_outs(),
        current_btc_price=80000.0, now_utc="2026-05-03T08:00:00Z",
    )
    th = res["active_thesis"]
    assert th is not None
    assert th["thesis_id"] == "th_active"
    assert th["direction"] == "long"
    assert th["confidence_score"] == 72
    assert th["core_logic"] == "test thesis"
    assert len(th["break_conditions"]) == 3
    assert th["created_days_ago"] == 8.0  # 4-25 → 5-3
    assert th["lifecycle_stage"] == "opened"
    assert th["is_60d_capped"] is False


def test_current_position_long_pnl_positive(conn):
    """long 持仓 + price 涨 → long_pnl_pct > 0。"""
    VirtualAccountDAO.insert_snapshot(
        conn, snapshot_id="snap1", run_id="r1",
        snapshot_at_utc="2026-05-03T08:00:00Z",
        btc_price_at_snapshot=80000.0,
        initial_capital=100000.0, available_cash=80000.0,
        long_position_usdt=20000.0, long_avg_price=80000.0,
        long_btc_amount=0.25, total_equity=100000.0,
    )
    conn.commit()
    res = build_master_input(
        conn, layer_outputs=_layer_outs(),
        current_btc_price=82000.0, now_utc="2026-05-04T08:00:00Z",
    )
    pos = res["current_position"]
    assert pos is not None
    assert pos["long_position_usdt"] == 20000.0
    assert pos["long_avg_price"] == 80000.0
    assert pos["long_btc_amount"] == 0.25
    assert pos["long_pnl_pct"] == 2.5  # (82000-80000)/80000 * 100
    assert "short_position_usdt" not in pos


def test_current_position_short_pnl(conn):
    """short 持仓 + price 跌 → short_pnl_pct > 0。"""
    VirtualAccountDAO.insert_snapshot(
        conn, snapshot_id="snap1", run_id="r1",
        snapshot_at_utc="2026-05-03T08:00:00Z",
        btc_price_at_snapshot=80000.0,
        initial_capital=100000.0, available_cash=80000.0,
        short_position_usdt=20000.0, short_avg_price=80000.0,
        short_btc_amount=0.25, total_equity=100000.0,
    )
    conn.commit()
    res = build_master_input(
        conn, layer_outputs=_layer_outs(),
        current_btc_price=78000.0, now_utc="2026-05-04T08:00:00Z",
    )
    pos = res["current_position"]
    assert pos["short_pnl_pct"] == 2.5  # (80000-78000)/80000 * 100


def test_no_position_when_zero(conn):
    """全 cash 状态(long_btc=0 short_btc=0)→ current_position=None。"""
    VirtualAccountDAO.insert_snapshot(
        conn, snapshot_id="snap1", run_id="r1",
        snapshot_at_utc="2026-05-03T08:00:00Z",
        btc_price_at_snapshot=80000.0,
        initial_capital=100000.0, available_cash=100000.0,
        total_equity=100000.0,
    )
    conn.commit()
    res = build_master_input(
        conn, layer_outputs=_layer_outs(),
        current_btc_price=80000.0, now_utc="2026-05-03T08:00:00Z",
    )
    assert res["current_position"] is None


def test_pending_orders_for_active_thesis(conn):
    ThesesDAO.create(
        conn, thesis_id="th_active", created_at_run_id="r1",
        created_at_utc="2026-05-01T08:00:00Z",
        direction="long", core_logic="test",
        confidence_score=70,
        break_conditions=["c1", "c2", "c3"],
    )
    VirtualOrdersDAO.create_order(
        conn, order_id="o1", thesis_id="th_active",
        direction="long", order_type="entry",
        price=74000.0, size_pct=0.20, size_usdt=20000.0,
        created_at_utc="2026-05-01T08:00:00Z",
        expires_at_utc="2026-12-01T00:00:00Z",
    )
    VirtualOrdersDAO.create_order(
        conn, order_id="o2", thesis_id="th_active",
        direction="long", order_type="stop_loss",
        price=67000.0, size_pct=1.00, size_usdt=20000.0,
        created_at_utc="2026-05-01T08:00:00Z",
        expires_at_utc="2026-12-01T00:00:00Z",
    )
    # 另一 thesis 的挂单不应出现
    ThesesDAO.create(
        conn, thesis_id="th_other", created_at_run_id="r0",
        created_at_utc="2026-04-01T08:00:00Z",
        direction="short", core_logic="other",
        confidence_score=60, break_conditions=["x", "y", "z"],
        status="closed_loss",
    )
    VirtualOrdersDAO.create_order(
        conn, order_id="o_other", thesis_id="th_other",
        direction="short", order_type="entry",
        price=85000.0, size_pct=0.20, size_usdt=20000.0,
        created_at_utc="2026-04-01T08:00:00Z",
        expires_at_utc="2026-04-08T00:00:00Z",
    )
    conn.commit()

    res = build_master_input(
        conn, layer_outputs=_layer_outs(),
        current_btc_price=74000.0, now_utc="2026-05-03T08:00:00Z",
    )
    pending = res["pending_orders"]
    assert len(pending) == 2  # only th_active 的
    ids = {p["order_id"] for p in pending}
    assert ids == {"o1", "o2"}
    types = {p["type"] for p in pending}
    assert types == {"entry", "stop_loss"}


def test_cooldown_state_in_cooldown_after_recent_close(conn):
    """closed thesis < 72h ago + channel A → in_cooldown=True。"""
    ThesesDAO.create(
        conn, thesis_id="th_closed", created_at_run_id="r1",
        created_at_utc="2026-04-25T08:00:00Z",
        direction="long", core_logic="x",
        confidence_score=70, break_conditions=["c1", "c2", "c3"],
    )
    ThesesDAO.close(
        conn, thesis_id="th_closed", status="closed_profit",
        closed_at_utc="2026-05-01T08:00:00Z",
        close_channel="A", final_outcome="profit",
    )
    conn.commit()
    # 5-1 + 72h = 5-4 08:00。now=5-3 08:00 → 24h remaining
    res = build_master_input(
        conn, layer_outputs=_layer_outs(),
        current_btc_price=80000.0, now_utc="2026-05-03T08:00:00Z",
    )
    cd = res["cooldown_state"]
    assert cd["in_cooldown"] is True
    assert abs(cd["cooldown_remaining_hours"] - 24.0) < 0.01
    assert cd["cooldown_reason"] == "channel_A"


def test_fuse_state_two_thesis_cycles_triggers(conn):
    """14d 内 2 thesis_cycle → in_14d_fuse=True。"""
    record_thesis_cycle(conn, "th1", "2026-05-01T08:00:00Z")
    record_thesis_cycle(conn, "th2", "2026-05-08T08:00:00Z")
    conn.commit()
    res = build_master_input(
        conn, layer_outputs=_layer_outs(),
        current_btc_price=80000.0, now_utc="2026-05-10T08:00:00Z",
    )
    fs = res["fuse_state"]
    assert fs["thesis_cycles_in_14d"] == 2
    assert fs["in_14d_fuse"] is True


def test_fuse_state_two_channel_c_uses_disables_c(conn):
    record_channel_c_use(conn, "th1", "2026-05-01T08:00:00Z")
    record_channel_c_use(conn, "th2", "2026-05-08T08:00:00Z")
    conn.commit()
    res = build_master_input(
        conn, layer_outputs=_layer_outs(),
        current_btc_price=80000.0, now_utc="2026-05-10T08:00:00Z",
    )
    fs = res["fuse_state"]
    assert fs["channel_c_uses_in_14d"] == 2
    assert fs["channel_c_disabled"] is True


def test_last_5_assessments_returns_existing(conn):
    """3 个历史 thesis 都有 last_assessment → 返 3 个。"""
    for i in range(3):
        ThesesDAO.create(
            conn, thesis_id=f"th_hist_{i}", created_at_run_id=f"r_{i}",
            created_at_utc=f"2026-04-0{i+1}T08:00:00Z",
            direction="long", core_logic=f"hist {i}",
            confidence_score=60 + i*5,
            break_conditions=["c1", "c2", "c3"],
        )
        ThesesDAO.update_assessment(
            conn, thesis_id=f"th_hist_{i}",
            last_assessment="mostly",
            last_assessment_note=f"评估 {i}",
            last_assessment_at_run=f"r_{i}",
        )
    conn.commit()

    res = build_master_input(
        conn, layer_outputs=_layer_outs(),
        current_btc_price=80000.0, now_utc="2026-05-03T08:00:00Z",
    )
    assert len(res["last_5_assessments"]) == 3
    # 默认 limit=5 但只有 3 个有 assessment


def test_60d_capped_field_propagates(conn):
    """thesis is_60d_capped=1 → active_thesis.is_60d_capped=True。"""
    ThesesDAO.create(
        conn, thesis_id="th_capped", created_at_run_id="r1",
        created_at_utc="2026-03-01T08:00:00Z",
        direction="long", core_logic="capped",
        confidence_score=70, break_conditions=["c1", "c2", "c3"],
    )
    conn.execute("UPDATE theses SET is_60d_capped=1 WHERE thesis_id='th_capped'")
    conn.commit()
    res = build_master_input(
        conn, layer_outputs=_layer_outs(),
        current_btc_price=80000.0, now_utc="2026-05-03T08:00:00Z",
    )
    assert res["active_thesis"]["is_60d_capped"] is True
