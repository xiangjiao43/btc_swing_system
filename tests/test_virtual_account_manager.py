"""Sprint 1.10-B 单测:VirtualAccountManager(v1.4 §5.1.5)。"""
from __future__ import annotations

import pytest

from src.strategy.virtual_account import compute_snapshot, compute_returns_history


# ============================================================
# compute_snapshot — happy path
# ============================================================

def test_cold_start_no_prev_no_fills():
    """无前置快照 + 无 fills → 全部 cash,无持仓。"""
    snap = compute_snapshot(
        prev_snapshot=None,
        current_btc_price=80000.0,
        fills_since_last=[],
        initial_capital=100000.0,
        snapshot_id="snap_init",
        run_id="run_init",
        snapshot_at_utc="2026-05-03T08:00:00Z",
    )
    assert snap["available_cash"] == 100000.0
    assert snap["long_position_usdt"] == 0.0
    assert snap["long_btc_amount"] == 0.0
    assert snap["long_avg_price"] is None
    assert snap["short_position_usdt"] == 0.0
    assert snap["unrealized_pnl"] == 0.0
    assert snap["total_equity"] == 100000.0
    assert snap["total_return_pct"] == 0.0
    assert snap["btc_price_at_snapshot"] == 80000.0
    assert snap["snapshot_id"] == "snap_init"


def test_long_entry_fill_unrealized_zero_at_entry_price():
    """单 long entry,current_price = filled_price → unrealized_pnl = 0。"""
    snap = compute_snapshot(
        prev_snapshot=None,
        current_btc_price=74568.0,
        fills_since_last=[{
            "direction": "long", "order_type": "entry",
            "size_usdt": 20000.0,
            "filled_price": 74568.0,
            "filled_btc_amount": 20000.0 / 74568.0,
        }],
        initial_capital=100000.0,
        snapshot_id="s1", run_id="r1",
        snapshot_at_utc="2026-05-03T08:00:00Z",
    )
    assert snap["available_cash"] == 80000.0  # 100000 - 20000
    assert snap["long_position_usdt"] == 20000.0
    assert abs(snap["long_btc_amount"] - 0.26821157) < 1e-6
    assert snap["long_avg_price"] == 74568.0
    assert abs(snap["unrealized_pnl"]) < 1e-6  # 0
    assert snap["total_equity"] == 100000.0
    assert snap["total_return_pct"] == 0.0


def test_long_unrealized_pnl_when_price_rises():
    """price > entry → 多头浮盈正。"""
    snap = compute_snapshot(
        prev_snapshot=None,
        current_btc_price=82000.0,  # +2.5% from 80000
        fills_since_last=[{
            "direction": "long", "order_type": "entry",
            "size_usdt": 20000.0,
            "filled_price": 80000.0,
            "filled_btc_amount": 0.25,
        }],
        initial_capital=100000.0,
        snapshot_id="s2", run_id="r2",
        snapshot_at_utc="2026-05-04T08:00:00Z",
    )
    # 0.25 BTC * (82000 - 80000) = 500
    assert snap["unrealized_pnl"] == 500.0
    # equity = 80000 cash + 20000 cost + 0 short + 500 pnl = 100500
    assert snap["total_equity"] == 100500.0
    assert snap["total_return_pct"] == 0.5


def test_short_unrealized_pnl_when_price_drops():
    """short:price 跌 → 浮盈正。"""
    snap = compute_snapshot(
        prev_snapshot=None,
        current_btc_price=78000.0,  # -2.5% from 80000
        fills_since_last=[{
            "direction": "short", "order_type": "entry",
            "size_usdt": 20000.0,
            "filled_price": 80000.0,
            "filled_btc_amount": 0.25,
        }],
        initial_capital=100000.0,
        snapshot_id="s3", run_id="r3",
        snapshot_at_utc="2026-05-04T08:00:00Z",
    )
    # 0.25 * (80000 - 78000) = 500
    assert snap["unrealized_pnl"] == 500.0
    assert snap["total_equity"] == 100500.0


def test_multi_fill_weighted_avg_price():
    """§5.2.5 同 1H 多挂单全触发 → 加权均价。"""
    snap = compute_snapshot(
        prev_snapshot=None,
        current_btc_price=72000.0,
        fills_since_last=[
            {"direction": "long", "order_type": "entry",
             "size_usdt": 20000.0, "filled_price": 74568.0,
             "filled_btc_amount": 20000.0 / 74568.0},
            {"direction": "long", "order_type": "entry",
             "size_usdt": 30000.0, "filled_price": 70666.0,
             "filled_btc_amount": 30000.0 / 70666.0},
        ],
        initial_capital=100000.0,
        snapshot_id="s4", run_id="r4",
        snapshot_at_utc="2026-05-03T08:00:00Z",
    )
    # 加权:total_usdt = 50000 / total_btc = 0.26821 + 0.42454 = 0.69275
    expected_avg = 50000.0 / (20000.0 / 74568.0 + 30000.0 / 70666.0)
    assert snap["long_position_usdt"] == 50000.0
    assert abs(snap["long_avg_price"] - expected_avg) < 0.01
    assert snap["available_cash"] == 50000.0


def test_add_to_existing_long_from_prev_snapshot():
    """已有持仓 → 加仓 → avg_price 重算。"""
    prev = {
        "long_position_usdt": 20000.0,
        "long_avg_price": 80000.0,
        "long_btc_amount": 0.25,
        "short_position_usdt": 0.0,
        "short_avg_price": None,
        "short_btc_amount": 0.0,
        "available_cash": 80000.0,
        "realized_pnl_total": 0.0,
    }
    snap = compute_snapshot(
        prev_snapshot=prev,
        current_btc_price=75000.0,  # 跌了
        fills_since_last=[{
            "direction": "long", "order_type": "entry",
            "size_usdt": 20000.0, "filled_price": 75000.0,
            "filled_btc_amount": 20000.0 / 75000.0,
        }],
        initial_capital=100000.0,
        snapshot_id="s5", run_id="r5",
        snapshot_at_utc="2026-05-04T08:00:00Z",
    )
    expected_btc = 0.25 + 20000.0 / 75000.0
    expected_avg = 40000.0 / expected_btc  # ≈ 77419
    assert snap["long_position_usdt"] == 40000.0
    assert abs(snap["long_btc_amount"] - expected_btc) < 1e-6
    assert abs(snap["long_avg_price"] - expected_avg) < 0.01
    # 浮亏 = 0.51666 BTC * (75000 - 77419) = -1250
    assert snap["unrealized_pnl"] < 0


# ============================================================
# compute_snapshot — edge
# ============================================================

def test_non_entry_fill_skipped():
    """stop_loss / take_profit fill 应被跳过(留 1.10-C 处理)。"""
    snap = compute_snapshot(
        prev_snapshot=None,
        current_btc_price=80000.0,
        fills_since_last=[
            {"direction": "long", "order_type": "stop_loss",
             "size_usdt": 20000.0, "filled_price": 75000.0,
             "filled_btc_amount": 0.27},
            {"direction": "long", "order_type": "take_profit",
             "size_usdt": 10000.0, "filled_price": 85000.0,
             "filled_btc_amount": 0.12},
        ],
        initial_capital=100000.0,
        snapshot_id="s6", run_id="r6",
        snapshot_at_utc="2026-05-04T08:00:00Z",
    )
    assert snap["long_position_usdt"] == 0.0  # 没加仓
    assert snap["available_cash"] == 100000.0  # cash 没变


def test_invalid_direction_silently_ignored():
    """异常 direction(非 long/short)静默跳过。"""
    snap = compute_snapshot(
        prev_snapshot=None,
        current_btc_price=80000.0,
        fills_since_last=[{
            "direction": "neutral", "order_type": "entry",
            "size_usdt": 20000.0, "filled_price": 80000.0,
            "filled_btc_amount": 0.25,
        }],
        initial_capital=100000.0,
        snapshot_id="s7", run_id="r7",
        snapshot_at_utc="2026-05-04T08:00:00Z",
    )
    assert snap["long_position_usdt"] == 0.0
    assert snap["short_position_usdt"] == 0.0


# ============================================================
# compute_returns_history
# ============================================================

def test_returns_empty_history():
    """空 list → 全 None。"""
    r = compute_returns_history([])
    assert all(v is None for v in r.values())


def test_returns_total_pct_two_snapshots():
    """两条快照 → total_pct 算出来。"""
    snaps = [
        # latest first
        {"snapshot_at_utc": "2026-05-10T08:00:00Z", "total_equity": 105000.0},
        {"snapshot_at_utc": "2026-05-03T08:00:00Z", "total_equity": 100000.0},
    ]
    r = compute_returns_history(snaps)
    assert r["total_pct"] == 5.0
    # 7 天前 = 2026-05-03 → 找到一条等于此的快照 → +5%
    assert r["weekly_pct"] == 5.0
    # 1 天前 = 2026-05-09 → 无 ≤ 5-09 的快照(5-03 是 ≤,但 5-03 是最早的)
    # 实际 closest_at_or_before(2026-05-09) = 5-03 那条 → daily = 5%
    assert r["daily_pct"] == 5.0


def test_returns_with_full_history():
    """完整 7+ 天快照 → daily / weekly 准确。"""
    snaps = []
    # 生成 14 天每天 1 条,equity 线性增长
    base_dt_iso = ["2026-05-{:02d}T08:00:00Z".format(d) for d in range(1, 15)]
    base_eq = [100000.0 + i * 500 for i in range(14)]
    # 倒序:最新在 [0]
    for ts, eq in reversed(list(zip(base_dt_iso, base_eq))):
        snaps.append({"snapshot_at_utc": ts, "total_equity": eq})
    # latest = 5-14 equity=106500
    # 1 天前 = 5-13 equity=106000 → daily = (106500/106000-1)*100 ≈ 0.4717
    # 7 天前 = 5-07 equity=103000 → weekly = (106500/103000-1)*100 ≈ 3.3981
    r = compute_returns_history(snaps)
    assert abs(r["daily_pct"] - 0.4717) < 0.001
    assert abs(r["weekly_pct"] - 3.3981) < 0.001
    assert r["monthly_pct"] is None  # 无 30 天前数据 (closest 在 5-01,但距 5-14 = 13 天)
    # 实际 monthly target = 5-14 - 30 days = 4-14 → snapshots 中无 ≤ 4-14 的 → None
    assert r["yearly_pct"] is None
    # total_pct = (106500/100000-1)*100 = 6.5
    assert r["total_pct"] == 6.5


def test_returns_zero_equity_returns_none():
    """latest equity = 0 → 全 None(避免除 0)。"""
    snaps = [{"snapshot_at_utc": "2026-05-03T08:00:00Z", "total_equity": 0.0}]
    r = compute_returns_history(snaps)
    assert all(v is None for v in r.values())
