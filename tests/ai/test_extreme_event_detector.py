"""tests/ai/test_extreme_event_detector.py — Sprint 1.9-A.3 极端事件 5 类 bool。

真实现 2 类(flash_crash + stablecoin_depeg)需触发 / 不触发场景;
stub 3 类必须返回 False 且代码含 TODO 注释。
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from src.ai.extreme_event_detector import (
    detect_extreme_events,
    detect_flash_crash_24h,
    detect_geopolitical_conflict,
    detect_major_bank_crisis,
    detect_regulatory_crackdown,
    detect_stablecoin_depeg,
)
from src.data.storage.connection import init_db


# ============================================================
# detect_flash_crash_24h
# ============================================================

def test_flash_crash_triggers_when_today_drops_10pct():
    """今天最低价比开盘跌 10% → True。"""
    idx = pd.date_range("2026-04-30", periods=2, freq="1D", tz="UTC")
    df = pd.DataFrame({
        "open": [70000.0, 70000.0],
        "high": [71000.0, 71000.0],
        "low": [69500.0, 63000.0],   # 今天 low 比 open 跌 10%
        "close": [70500.0, 65000.0],
    }, index=idx)
    assert detect_flash_crash_24h(df, threshold_pct=-8.0) is True


def test_flash_crash_no_trigger_for_normal_day():
    """正常 ±2% 波动 → False。"""
    idx = pd.date_range("2026-04-30", periods=2, freq="1D", tz="UTC")
    df = pd.DataFrame({
        "open": [70000.0, 70000.0],
        "high": [70500.0, 70500.0],
        "low": [69500.0, 69500.0],
        "close": [70200.0, 70300.0],
    }, index=idx)
    assert detect_flash_crash_24h(df, threshold_pct=-8.0) is False


def test_flash_crash_triggers_from_prev_close():
    """今天 low 比昨收跌 9%(从 high 还看不出极端,但参考点是昨收)→ True。"""
    idx = pd.date_range("2026-04-30", periods=2, freq="1D", tz="UTC")
    df = pd.DataFrame({
        "open": [70000.0, 67000.0],
        "high": [71000.0, 67500.0],
        "low": [69500.0, 63500.0],   # 比昨收 70500 跌 ~10%
        "close": [70500.0, 64000.0],
    }, index=idx)
    assert detect_flash_crash_24h(df, threshold_pct=-8.0) is True


def test_flash_crash_handles_empty_or_short_df():
    assert detect_flash_crash_24h(None) is False
    assert detect_flash_crash_24h(pd.DataFrame()) is False


# ============================================================
# detect_stablecoin_depeg
# ============================================================

def test_stablecoin_depeg_triggers_when_usdt_below_0_985():
    idx = pd.date_range("2026-04-30", periods=5, freq="1D", tz="UTC")
    macro = {
        "usdt_price": pd.Series([1.0, 1.0, 0.999, 0.99, 0.97], index=idx),
    }
    assert detect_stablecoin_depeg(macro) is True


def test_stablecoin_depeg_no_trigger_when_usdt_above_threshold():
    idx = pd.date_range("2026-04-30", periods=5, freq="1D", tz="UTC")
    macro = {
        "usdt_price": pd.Series([1.0, 1.0, 1.0, 0.999, 0.998], index=idx),
    }
    assert detect_stablecoin_depeg(macro) is False


def test_stablecoin_depeg_no_data_returns_false():
    """DB 没有 usdt_price 时 → False(数据缺失不视为脱锚)。"""
    assert detect_stablecoin_depeg({}) is False
    assert detect_stablecoin_depeg({"vix": pd.Series([20.0])}) is False


def test_stablecoin_depeg_usdc_also_triggers():
    idx = pd.date_range("2026-04-30", periods=3, freq="1D", tz="UTC")
    macro = {
        "usdc_price": pd.Series([1.0, 0.99, 0.98], index=idx),
    }
    assert detect_stablecoin_depeg(macro) is True


# ============================================================
# stub 3 类(必须返回 False)
# ============================================================

def test_geopolitical_stub_always_false():
    conn = sqlite3.connect(":memory:")
    assert detect_geopolitical_conflict(conn) is False


def test_banking_crisis_stub_always_false():
    conn = sqlite3.connect(":memory:")
    assert detect_major_bank_crisis(conn) is False


def test_regulatory_stub_always_false():
    conn = sqlite3.connect(":memory:")
    assert detect_regulatory_crackdown(conn) is False


def test_stub_functions_have_todo_comments():
    """3 个 stub 函数源码必须含 'TODO Sprint 1.10' 注释(防止伪造)。"""
    import inspect
    from src.ai import extreme_event_detector as m
    for fn in (m.detect_geopolitical_conflict,
               m.detect_major_bank_crisis,
               m.detect_regulatory_crackdown):
        src = inspect.getsource(fn)
        assert "TODO Sprint 1.10" in src, (
            f"{fn.__name__} missing TODO comment — stub 须明示待实施"
        )


# ============================================================
# 主入口 detect_extreme_events
# ============================================================

@pytest.fixture
def db_path() -> Path:
    tmp = Path(tempfile.mkdtemp()) / "ext.db"
    init_db(db_path=tmp, verbose=False)
    return tmp


def test_detect_extreme_events_returns_5_keys_all_false(db_path):
    """空 DB → 5 类全 False(无 K 线 + 无 stablecoin)。"""
    conn = sqlite3.connect(db_path)
    flags = detect_extreme_events(conn)
    assert set(flags.keys()) == {
        "flash_crash_detected_24h",
        "stablecoin_depeg_active",
        "geopolitical_conflict_active",
        "major_bank_crisis_signal",
        "regulatory_crackdown_recent",
    }
    assert all(v is False for v in flags.values())


def test_detect_extreme_events_flash_crash_triggered(db_path):
    """种入暴跌 K 线 → flash_crash_detected_24h=True。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row     # DAO 需要 Row factory 才能解析
    # 种 2 行 1d K 线(yesterday + today),今天 low 比 open 跌 10%
    yesterday_iso = "2026-04-30T00:00:00Z"
    today_iso = "2026-05-01T00:00:00Z"
    conn.executemany(
        "INSERT INTO price_candles "
        "(symbol, timeframe, open_time_utc, open, high, low, close, "
        " volume, inserted_at_utc) VALUES "
        "('BTCUSDT', '1d', ?, ?, ?, ?, ?, 1.0, '2026-05-01T08:00:00Z')",
        [
            (yesterday_iso, 70000, 71000, 69500, 70500),
            (today_iso, 70000, 71000, 63000, 65000),  # low 跌 10%
        ],
    )
    conn.commit()
    flags = detect_extreme_events(conn)
    assert flags["flash_crash_detected_24h"] is True
    # stub 3 类仍 False
    assert flags["geopolitical_conflict_active"] is False
    assert flags["major_bank_crisis_signal"] is False
    assert flags["regulatory_crackdown_recent"] is False
