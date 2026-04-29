"""tests/test_scheduler_2_7_b_collectors.py — Sprint 2.7-B 5 个独立 collector job。

§X 验证:job_data_collection 已删除。
§Z 端到端:每个 job 用 mock collector + 真 SQLite + 真 DAO,断言 DB 行数变化。
关键变更:衍生品改 1h interval limit=168(原本 1d limit=7)。
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.data.storage.connection import init_db
from src.scheduler import jobs as jobs_mod


# ============================================================
# §X 验证
# ============================================================

def test_job_data_collection_function_removed():
    """Sprint 2.7-B §X:老的统合函数 job_data_collection 已删除。"""
    assert not hasattr(jobs_mod, "job_data_collection")


def test_data_collection_not_in_job_functions_registry():
    assert "data_collection" not in jobs_mod._JOB_FUNCTIONS


def test_5_new_collector_jobs_registered():
    expected = {
        "collect_klines_1h", "collect_klines_daily", "collect_klines_weekly",
        "collect_macro", "collect_onchain",
    }
    assert expected.issubset(set(jobs_mod._JOB_FUNCTIONS.keys()))


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def db_path():
    tmp = Path(tempfile.mkdtemp()) / "j7b.db"
    init_db(db_path=tmp, verbose=False)
    return tmp


@pytest.fixture
def conn_factory(db_path):
    return lambda: sqlite3.connect(db_path)


def _row_count(db_path: Path, table: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


# ============================================================
# job_collect_klines_1h:K 线 1h + 衍生品 5 端点 1h interval
# ============================================================

def test_collect_klines_1h_writes_klines_and_derivatives(db_path, conn_factory):
    """端到端:mock CoinGlass → 真 DB → 断言 price_candles + derivatives 行数 > 0。"""
    cg_inst = MagicMock()
    # 24 行 1h K 线
    cg_inst.fetch_klines.return_value = [
        {"timestamp": f"2026-04-27T{h:02d}:00:00Z",
         "open": 50000+h, "high": 50100+h, "low": 49900+h, "close": 50050+h,
         "volume": 100.0}
        for h in range(24)
    ]
    # 衍生品 5 端点,每个 168 行
    for fn in ("fetch_funding_rate_history", "fetch_funding_rate_aggregated",
               "fetch_open_interest_history", "fetch_long_short_ratio_history",
               "fetch_liquidation_history"):
        getattr(cg_inst, fn).return_value = [
            {"timestamp": f"2026-04-2{(20 + h//24) % 10}T{h%24:02d}:00:00Z",
             "metric_name": fn.replace("fetch_", "").replace("_history", ""),
             "metric_value": 0.0001 + h*0.00001}
            for h in range(168)
        ]

    with patch("src.data.collectors.coinglass.CoinglassCollector",
               return_value=cg_inst):
        result = jobs_mod.job_collect_klines_1h(conn_factory=conn_factory)

    assert result["status"] == "ok"
    assert result["by_collector"]["klines_1h"] >= 24
    assert result["by_collector"]["derivatives_1h"] > 0
    # §Z DB 行数断言
    assert _row_count(db_path, "price_candles") >= 24
    assert _row_count(db_path, "derivatives_snapshots") >= 1


def test_collect_klines_1h_uses_1d_interval_for_derivatives(db_path, conn_factory):
    """Sprint 1.5f-revised:衍生品反转回 daily(interval='1d', limit=7)。
    Sprint 2.7-B 一度改 1h limit=168 是误判,SSH 真 DB 复检后定位 hourly 入库
    导致 series 平均间隔混乱、派生 tail(N) 行数语义全错(详见 sprint_1_5f_revised.md)。"""
    cg_inst = MagicMock()
    cg_inst.fetch_klines.return_value = []
    for fn in ("fetch_funding_rate_history", "fetch_funding_rate_aggregated",
               "fetch_open_interest_history", "fetch_long_short_ratio_history",
               "fetch_liquidation_history"):
        getattr(cg_inst, fn).return_value = []

    with patch("src.data.collectors.coinglass.CoinglassCollector",
               return_value=cg_inst):
        jobs_mod.job_collect_klines_1h(conn_factory=conn_factory)

    # 验证每个衍生品 fn 都被以 (interval='1d', limit=7) 调用
    for fn in ("fetch_funding_rate_history", "fetch_funding_rate_aggregated",
               "fetch_open_interest_history", "fetch_long_short_ratio_history",
               "fetch_liquidation_history"):
        m = getattr(cg_inst, fn)
        assert m.called, f"{fn} not called"
        kw = m.call_args.kwargs
        assert kw.get("interval") == "1d", f"{fn} interval={kw.get('interval')}"
        assert kw.get("limit") == 7, f"{fn} limit={kw.get('limit')}"


def test_collect_klines_1h_handles_partial_failure(db_path, conn_factory):
    """单个 derivative 失败不让其他失败也不让 job 崩溃。"""
    cg_inst = MagicMock()
    cg_inst.fetch_klines.return_value = []
    cg_inst.fetch_funding_rate_history.side_effect = RuntimeError("upstream 500")
    for fn in ("fetch_funding_rate_aggregated",
               "fetch_open_interest_history", "fetch_long_short_ratio_history",
               "fetch_liquidation_history"):
        getattr(cg_inst, fn).return_value = []

    with patch("src.data.collectors.coinglass.CoinglassCollector",
               return_value=cg_inst):
        result = jobs_mod.job_collect_klines_1h(conn_factory=conn_factory)

    assert result["status"] == "ok"
    assert "fetch_funding_rate_history" in result["errors"]


# ============================================================
# job_collect_klines_daily / weekly
# ============================================================

def test_collect_klines_daily_fetches_1d_and_4h(db_path, conn_factory):
    cg_inst = MagicMock()
    cg_inst.fetch_klines.return_value = [
        {"timestamp": "2026-04-27T00:00:00Z",
         "open": 50000, "high": 51000, "low": 49500, "close": 50500,
         "volume": 1234.5}
    ]
    with patch("src.data.collectors.coinglass.CoinglassCollector",
               return_value=cg_inst):
        result = jobs_mod.job_collect_klines_daily(conn_factory=conn_factory)
    assert result["status"] == "ok"
    # fetch_klines 调了 2 次(1d 和 4h)
    assert cg_inst.fetch_klines.call_count == 2
    intervals = [c.kwargs.get("interval") for c in cg_inst.fetch_klines.call_args_list]
    assert set(intervals) == {"1d", "4h"}
    assert _row_count(db_path, "price_candles") >= 1


def test_collect_klines_weekly_fetches_1w(db_path, conn_factory):
    cg_inst = MagicMock()
    cg_inst.fetch_klines.return_value = [
        {"timestamp": "2026-04-20T00:00:00Z",
         "open": 50000, "high": 51000, "low": 49500, "close": 50500,
         "volume": 5000.0}
    ]
    with patch("src.data.collectors.coinglass.CoinglassCollector",
               return_value=cg_inst):
        result = jobs_mod.job_collect_klines_weekly(conn_factory=conn_factory)
    assert result["status"] == "ok"
    assert cg_inst.fetch_klines.call_count == 1
    assert cg_inst.fetch_klines.call_args.kwargs.get("interval") == "1w"


# ============================================================
# job_collect_macro
# ============================================================

def test_collect_macro_calls_fred(db_path, conn_factory):
    fred_inst = MagicMock()
    fred_inst.enabled = True
    fred_inst.collect_and_save_all.return_value = {"dxy": 30, "us10y": 30}
    with patch("src.data.collectors.fred.FredCollector", return_value=fred_inst):
        result = jobs_mod.job_collect_macro(conn_factory=conn_factory)
    assert result["status"] == "ok"
    assert result["by_collector"]["fred"] == 60
    fred_inst.collect_and_save_all.assert_called_once()


def test_collect_macro_skips_when_no_key(db_path, conn_factory):
    fred_inst = MagicMock()
    fred_inst.enabled = False
    with patch("src.data.collectors.fred.FredCollector", return_value=fred_inst):
        result = jobs_mod.job_collect_macro(conn_factory=conn_factory)
    assert result["status"] == "skipped"
    assert "fred" in result["errors"]


# ============================================================
# job_collect_onchain
# ============================================================

def test_collect_onchain_iterates_glassnode_fetchers(db_path, conn_factory):
    gn_inst = MagicMock()
    for fn in jobs_mod._GLASSNODE_FETCHERS:
        getattr(gn_inst, fn).return_value = [
            {"timestamp": "2026-04-27T00:00:00Z",
             "metric_name": fn.replace("fetch_", ""),
             "metric_value": 1.0,
             "source": "glassnode_primary"}
        ]
    with patch("src.data.collectors.glassnode.GlassnodeCollector",
               return_value=gn_inst):
        result = jobs_mod.job_collect_onchain(conn_factory=conn_factory)
    assert result["status"] == "ok"
    assert result["by_collector"]["glassnode"] >= len(jobs_mod._GLASSNODE_FETCHERS)
    assert _row_count(db_path, "onchain_metrics") >= len(jobs_mod._GLASSNODE_FETCHERS)


# ============================================================
# fatal_error path
# ============================================================

def test_collect_klines_1h_fatal_error_when_conn_factory_throws():
    def bad_factory():
        raise RuntimeError("DB unreachable")
    result = jobs_mod.job_collect_klines_1h(conn_factory=bad_factory)
    assert result["status"] == "fatal_error"
    assert "DB unreachable" in result["error_message"]
