"""tests/ai/test_context_builder_integration.py — Sprint 1.9-A 集成测试。

ContextBuilder.build_full_context 在真 SQLite + 种入数据后,断言
返回的 context dict 含所有 6 agent 期望的关键字段。

不只断言 .called=True;断言字段值的 schema(类型 / 必有键)。
"""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.ai.context_builder import ContextBuilder
from src.data.storage.connection import init_db


@pytest.fixture
def db_path() -> Path:
    tmp = Path(tempfile.mkdtemp()) / "ctx.db"
    init_db(db_path=tmp, verbose=False)
    return tmp


def _seed_full_db(db_path: Path) -> None:
    """种入 K 线 / 衍生品 / 链上 / 宏观 / 事件全集合。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # 200 天 1d K 线
    np.random.seed(42)
    base_date = datetime(2025, 10, 1, tzinfo=timezone.utc)
    klines_rows = []
    klines_4h_rows = []
    close = 70000.0
    for i in range(200):
        d = base_date + timedelta(days=i)
        close += np.random.randn() * 500
        klines_rows.append((
            "BTCUSDT", "1d", d.strftime("%Y-%m-%dT%H:%M:%SZ"),
            close, close + 200, close - 200, close, 100.0,
            "2026-05-01T08:00:00Z",
        ))
    # 4h:30 天 × 6 bar
    for i in range(180):
        d = base_date + timedelta(hours=4 * i)
        close_4h = 75000 + np.random.randn() * 200
        klines_4h_rows.append((
            "BTCUSDT", "4h", d.strftime("%Y-%m-%dT%H:%M:%SZ"),
            close_4h, close_4h + 100, close_4h - 100, close_4h, 50.0,
            "2026-05-01T08:00:00Z",
        ))
    conn.executemany(
        "INSERT INTO price_candles "
        "(symbol, timeframe, open_time_utc, open, high, low, close, "
        " volume, inserted_at_utc) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        klines_rows + klines_4h_rows,
    )

    # 100 天 derivatives 宽表(funding + OI)
    for i in range(100):
        d = base_date + timedelta(days=i)
        funding = 0.0001 + np.random.randn() * 0.0002
        oi = 30e9 + np.random.randn() * 1e9
        conn.execute(
            "INSERT INTO derivatives_snapshots "
            "(captured_at_utc, funding_rate, open_interest, "
            " inserted_at_utc) VALUES (?, ?, ?, ?)",
            (d.strftime("%Y-%m-%dT%H:%M:%SZ"), funding, oi,
             "2026-05-01T08:00:00Z"),
        )

    # 100 天 onchain
    for i in range(100):
        d = base_date + timedelta(days=i)
        for metric, base in (("lth_supply", 14e6), ("sth_supply", 5e6),
                             ("exchange_net_flow", -500.0),
                             ("lth_realized_price", 44000),
                             ("sth_realized_price", 71000)):
            conn.execute(
                "INSERT INTO onchain_metrics "
                "(metric_name, captured_at_utc, value, source, "
                " inserted_at_utc) VALUES (?, ?, ?, 'glassnode', ?)",
                (metric, d.strftime("%Y-%m-%dT%H:%M:%SZ"),
                 base + np.random.randn() * 0.001 * base,
                 "2026-05-01T08:00:00Z"),
            )

    # 100 天 macro(dxy + vix + nasdaq + dgs10)
    for i in range(100):
        d = base_date + timedelta(days=i)
        for metric, base, sigma in (
            ("dxy", 103.0, 0.5),
            ("vix", 18.0, 1.0),
            ("nasdaq", 18000.0, 100.0),
            ("dgs10", 4.3, 0.05),
            ("us2y", 4.6, 0.05),
            ("etf_flow", 1e7, 1e7),
        ):
            conn.execute(
                "INSERT INTO macro_metrics "
                "(metric_name, captured_at_utc, value, source, "
                " inserted_at_utc) VALUES (?, ?, ?, 'fred', ?)",
                (metric, d.strftime("%Y-%m-%dT%H:%M:%SZ"),
                 base + np.random.randn() * sigma,
                 "2026-05-01T08:00:00Z"),
            )

    conn.commit()
    conn.close()


# ============================================================
# build_full_context 集成测试
# ============================================================

def test_build_full_context_returns_all_required_top_level_keys(db_path):
    """断言所有 orchestrator + 6 agents 期望的 top-level key 都存在。"""
    _seed_full_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    ctx = ContextBuilder(conn).build_full_context()

    # 原始 series + DAO dump
    for k in ("klines_1d", "klines_4h", "derivatives", "onchain", "macro"):
        assert k in ctx, f"missing key: {k}"

    # 类型 A 派生 series + dict
    for k in ("ema_20_1d", "ema_50_1d", "ema_200_1d",
              "ema_20_4h", "ema_50_4h",
              "adx_14_1d", "atr_14_1d", "atr_180d_pct_1d",
              "swing_points_1d",
              "funding_rate_series", "open_interest_series",
              "exchange_net_flow_series",
              "computed_indicators", "computed_macro_indicators",
              "btc_macro_corr_60d", "current_close"):
        assert k in ctx, f"missing key: {k}"

    # 类型 B + 状态机 + 历史
    for k in ("events_calendar_72h", "events_count_72h", "risk_preview",
              "current_state", "previous_strategy_run",
              "previous_l1", "previous_l2", "previous_l3",
              "previous_l4", "previous_l5"):
        assert k in ctx, f"missing key: {k}"


def test_build_full_context_computed_indicators_has_required_subfields(db_path):
    """L1+L2+L4 prompt 期望的 computed_indicators 子字段。"""
    _seed_full_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    ctx = ContextBuilder(conn).build_full_context()
    ci = ctx["computed_indicators"]

    # L1 必有
    assert "adx_14_1d_current" in ci
    assert "adx_14_1d_5d_avg" in ci
    assert "atr_14_1d_current" in ci
    assert "atr_180d_percentile" in ci
    assert "ema_20_current" in ci
    assert "ema_50_current" in ci
    assert "ema_200_current" in ci
    assert "ema_50_slope_30d" in ci
    assert "swing_5_recent" in ci

    # L2 必有
    assert "ema_20_4h_current" in ci
    assert "ema_50_4h_current" in ci
    assert "swing_high_3_recent" in ci
    assert "swing_low_3_recent" in ci
    assert "lth_supply_90d_pct_change" in ci
    assert "sth_supply_90d_pct_change" in ci
    assert "exchange_net_flow_30d_sum" in ci
    assert "lth_realized_price_current" in ci

    # L4 必有
    assert "current_close" in ci
    assert "max_drawdown_60d_pct" in ci
    assert "funding_rate_current" in ci
    assert "funding_rate_z_score_90d" in ci
    assert "funding_rate_30d_max" in ci
    assert "open_interest_current" in ci
    assert "open_interest_z_score_90d" in ci


def test_build_full_context_computed_macro_indicators_subfields(db_path):
    """L5 prompt 期望的 computed_macro_indicators 子字段。"""
    _seed_full_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    ctx = ContextBuilder(conn).build_full_context()
    cm = ctx["computed_macro_indicators"]

    # L5 必有(种入了 dxy/vix/nasdaq/dgs10/us2y/etf_flow)
    for k in ("dxy_current", "dxy_30d_change_pct", "dxy_90d_change_pct",
              "vix_current", "vix_30d_avg",
              "nasdaq_current", "nasdaq_30d_change_pct",
              "us10y_current",  # dgs10 → us10y alias
              "us10y_30d_change_bps",
              "yield_curve_2_10_spread_bps",
              "etf_flow_30d_sum_usd", "etf_flow_7d_sum_usd"):
        assert k in cm, f"missing macro key: {k}"


def test_build_full_context_risk_preview_only_3_keys(db_path):
    """risk_preview L3 prompt v3 — 只允许 3 个客观字段(铁律 1)。"""
    _seed_full_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    ctx = ContextBuilder(conn).build_full_context()
    rp = ctx["risk_preview"]
    assert set(rp.keys()) == {
        "funding_rate_z_score_90d",
        "open_interest_z_score_90d",
        "events_count_72h",
    }
    assert "crowding_level" not in rp
    assert "event_risk_active" not in rp
    assert "macro_warning_count" not in rp


def test_build_full_context_handles_empty_db():
    """空 DB → context 返回完整结构,但大多数字段为 None / [] / 0。"""
    tmp = Path(tempfile.mkdtemp()) / "empty.db"
    init_db(db_path=tmp, verbose=False)
    conn = sqlite3.connect(tmp)
    conn.row_factory = sqlite3.Row
    ctx = ContextBuilder(conn).build_full_context()

    # 必有的 key 仍存在(降级不缺 key)
    assert "computed_indicators" in ctx
    assert "computed_macro_indicators" in ctx
    assert "risk_preview" in ctx
    # 值为空集合或 None
    assert ctx["events_count_72h"] == 0
    assert ctx["computed_indicators"]["adx_14_1d_current"] is None
    assert ctx["risk_preview"]["funding_rate_z_score_90d"] is None
    # current_state 默认 FLAT
    assert ctx["current_state"] == "FLAT"


def test_build_full_context_current_state_from_strategy_runs(db_path):
    """如 DB 中有 strategy_runs 行,current_state = 最新 action_state。"""
    _seed_full_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # 种一行 strategy_runs(LONG_HOLD)
    conn.execute(
        "INSERT INTO strategy_runs "
        "(run_id, generated_at_utc, generated_at_bjt, action_state, "
        " full_state_json) "
        "VALUES (?, ?, ?, 'LONG_HOLD', '{}')",
        ("test-run-1", "2026-05-01T08:00:00Z", "2026-05-01 16:00:00"),
    )
    conn.commit()
    ctx = ContextBuilder(conn).build_full_context()
    assert ctx["current_state"] == "LONG_HOLD"
    assert ctx["previous_strategy_run"] is not None
