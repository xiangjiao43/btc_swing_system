"""tests/test_yahoo_collector_batch.py — Sprint 2.6-A.3:Yahoo 批量路径覆盖。

验证:
  - fetch_all_symbols_batch 解析 yf.download 的 MultiIndex DataFrame
  - 批量空 → 抛 YahooCollectorError
  - collect_and_save_all 批量成功时不走 fallback
  - collect_and_save_all 批量失败时落 per-symbol fallback
  - 两路径都失败 → 抛 YahooCollectorError
"""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.data.collectors.yahoo_finance import (
    SYMBOL_TO_METRIC,
    YahooCollectorError,
    YahooFinanceCollector,
)


def _make_mock_batch_df(symbols: list[str], rows: int = 10) -> pd.DataFrame:
    """yf.download(group_by='ticker') 风格的 MultiIndex DataFrame。"""
    dates = pd.date_range("2026-04-01", periods=rows, freq="D", tz="UTC")
    cols = pd.MultiIndex.from_product(
        [symbols, ["Open", "High", "Low", "Close", "Adj Close", "Volume"]]
    )
    data = {
        (s, f): [100.0 + i for i in range(rows)]
        for s in symbols for f in cols.get_level_values(1).unique()
    }
    return pd.DataFrame(data, index=dates)


def _build_test_db(tmp_path) -> sqlite3.Connection:
    """对齐 src/data/storage/schema.sql 的真实 macro_metrics 表结构。"""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE macro_metrics (
            metric_name     TEXT NOT NULL,
            captured_at_utc TEXT NOT NULL,
            value           REAL,
            source          TEXT,
            PRIMARY KEY (metric_name, captured_at_utc)
        )
    """)
    conn.commit()
    return conn


# ============================================================
# fetch_all_symbols_batch
# ============================================================

def test_fetch_all_symbols_batch_success():
    coll = YahooFinanceCollector()
    symbols = list(coll.symbol_map.keys())

    with patch("yfinance.download") as mock_dl:
        mock_dl.return_value = _make_mock_batch_df(symbols, rows=10)
        result = coll.fetch_all_symbols_batch(since_days=10)

    assert len(result) == len(symbols)
    for symbol, metric in coll.symbol_map.items():
        assert metric in result
        assert len(result[metric]) == 10
        assert result[metric][0]["metric_name"] == metric
        assert result[metric][0]["timestamp"].endswith("Z")


def test_fetch_all_symbols_batch_empty_raises():
    coll = YahooFinanceCollector()
    with patch("yfinance.download") as mock_dl:
        mock_dl.return_value = pd.DataFrame()
        with pytest.raises(YahooCollectorError, match="empty"):
            coll.fetch_all_symbols_batch(since_days=10)


def test_fetch_all_symbols_batch_yfinance_exception_wrapped():
    coll = YahooFinanceCollector()
    with patch("yfinance.download") as mock_dl:
        mock_dl.side_effect = RuntimeError("yfinance exploded")
        with pytest.raises(YahooCollectorError, match="batch failed"):
            coll.fetch_all_symbols_batch(since_days=10)


# ============================================================
# collect_and_save_all 批量主路径
# ============================================================

def test_collect_and_save_all_uses_batch_path_when_succeeds(tmp_path):
    """batch 成功 → 不走 fallback。"""
    conn = _build_test_db(tmp_path)
    coll = YahooFinanceCollector()
    symbols = list(coll.symbol_map.keys())

    with patch("yfinance.download") as mock_dl, \
         patch.object(coll, "fetch_symbol") as mock_fetch_symbol:
        mock_dl.return_value = _make_mock_batch_df(symbols, rows=10)
        result = coll.collect_and_save_all(conn, since_days=10)

    assert mock_fetch_symbol.call_count == 0
    assert all(v > 0 for v in result.values()), result
    conn.close()


def test_collect_and_save_all_falls_back_when_batch_fails(tmp_path):
    """batch 整体失败 → 对每个 symbol per-symbol fallback。"""
    conn = _build_test_db(tmp_path)
    coll = YahooFinanceCollector()

    with patch("yfinance.download") as mock_dl, \
         patch.object(coll, "fetch_symbol") as mock_fetch_symbol:
        mock_dl.side_effect = Exception("simulated batch fail")
        mock_fetch_symbol.return_value = [
            {"timestamp": "2026-04-01T00:00:00Z",
             "metric_name": "dxy", "metric_value": 104.5},
        ]
        result = coll.collect_and_save_all(conn, since_days=10)

    assert mock_fetch_symbol.call_count == len(coll.symbol_map)
    # 至少所有 metric 都有 stats key,值 ≥ 1
    assert len(result) == len(coll.symbol_map)
    conn.close()


def test_collect_and_save_all_partial_batch_falls_back_for_missing(tmp_path):
    """batch 拿到部分 → 缺的 symbol 单独 per-symbol fetch。"""
    conn = _build_test_db(tmp_path)
    coll = YahooFinanceCollector()
    symbols = list(coll.symbol_map.keys())
    # 只让前 4 个 symbol 在 batch 中有数据
    partial_df = _make_mock_batch_df(symbols[:4], rows=10)

    with patch("yfinance.download") as mock_dl, \
         patch.object(coll, "fetch_symbol") as mock_fetch_symbol:
        mock_dl.return_value = partial_df
        mock_fetch_symbol.return_value = [
            {"timestamp": "2026-04-01T00:00:00Z",
             "metric_name": "x", "metric_value": 1.0},
        ]
        coll.collect_and_save_all(conn, since_days=10)

    # 只剩 2 个 symbol 走 fallback
    assert mock_fetch_symbol.call_count == 2
    conn.close()


def test_collect_and_save_all_raises_when_both_paths_fail(tmp_path):
    """batch + fallback 都全失败 → raise YahooCollectorError。"""
    conn = _build_test_db(tmp_path)
    coll = YahooFinanceCollector()

    with patch("yfinance.download") as mock_dl, \
         patch.object(coll, "fetch_symbol") as mock_fetch_symbol:
        mock_dl.side_effect = Exception("batch fail")
        mock_fetch_symbol.side_effect = Exception("symbol fail")
        with pytest.raises(YahooCollectorError, match="All"):
            coll.collect_and_save_all(conn, since_days=10)
    conn.close()
