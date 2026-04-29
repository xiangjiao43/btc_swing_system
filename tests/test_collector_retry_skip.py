"""tests/test_collector_retry_skip.py — Sprint 2.8-F 多档 cron + 入口 skip 检查。

§Z 端到端:
- 真 SQLite + 真 schema
- macro / onchain / klines_daily / klines_weekly:今天/本周已存在 → 入口 skip
- 同上:数据缺失 → 走真实 collector body(mock 出 fetcher 验真实写入)
- scheduler.yaml 多档 cron 通过 OrTrigger 注册:trigger 是 OrTrigger 且
  sub-trigger 数量 == yaml cron list 长度
"""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger

from src.data.storage.connection import init_db
from src.scheduler import jobs as jobs_mod


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def db_path():
    tmp = Path(tempfile.mkdtemp()) / "rs.db"
    init_db(db_path=tmp, verbose=False)
    return tmp


def _conn(p: Path) -> sqlite3.Connection:
    return sqlite3.connect(p)


def _today_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _yesterday_iso() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=1)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _seed_metric(
    db_path: Path, table: str, *, metric_name: str,
    captured_at_utc: str, value: float, inserted_at_utc: str | None,
) -> None:
    conn = _conn(db_path)
    conn.execute(
        f"INSERT INTO {table} "
        "(metric_name, captured_at_utc, value, source, inserted_at_utc) "
        "VALUES (?, ?, ?, ?, ?)",
        (metric_name, captured_at_utc, value, "test", inserted_at_utc),
    )
    conn.commit()
    conn.close()


def _seed_kline(
    db_path: Path, *, timeframe: str, open_time_utc: str,
    inserted_at_utc: str | None,
) -> None:
    conn = _conn(db_path)
    conn.execute(
        "INSERT INTO price_candles "
        "(symbol, timeframe, open_time_utc, open, high, low, close, volume, "
        " inserted_at_utc) VALUES ('BTCUSDT', ?, ?, 1, 1, 1, 1, 1, ?)",
        (timeframe, open_time_utc, inserted_at_utc),
    )
    conn.commit()
    conn.close()


# ============================================================
# Helper unit tests
# ============================================================

def test_has_today_inserted_metric_true_when_today_exists(db_path):
    _seed_metric(
        db_path, "macro_metrics", metric_name="dxy",
        captured_at_utc=_yesterday_iso(),
        value=100.0,
        inserted_at_utc=_today_iso(),  # 今天写入
    )
    conn = _conn(db_path)
    try:
        assert jobs_mod._has_today_inserted_in_metric_table(
            conn, "macro_metrics") is True
    finally:
        conn.close()


def test_has_today_inserted_metric_false_when_only_yesterday(db_path):
    _seed_metric(
        db_path, "macro_metrics", metric_name="dxy",
        captured_at_utc=_yesterday_iso(),
        value=100.0,
        inserted_at_utc=_yesterday_iso(),  # 昨天写入
    )
    conn = _conn(db_path)
    try:
        assert jobs_mod._has_today_inserted_in_metric_table(
            conn, "macro_metrics") is False
    finally:
        conn.close()


def test_has_today_inserted_metric_ignores_null_inserted_at(db_path):
    """legacy 数据 inserted_at_utc=NULL → 不算"今天有数据"。"""
    _seed_metric(
        db_path, "macro_metrics", metric_name="dxy",
        captured_at_utc=_today_iso(), value=100.0, inserted_at_utc=None,
    )
    conn = _conn(db_path)
    try:
        assert jobs_mod._has_today_inserted_in_metric_table(
            conn, "macro_metrics") is False
    finally:
        conn.close()


def test_has_today_kline_1d_true(db_path):
    today_midnight = (
        datetime.now(timezone.utc).date().isoformat() + "T00:00:00Z"
    )
    _seed_kline(db_path, timeframe="1d", open_time_utc=today_midnight,
                inserted_at_utc=_today_iso())
    conn = _conn(db_path)
    try:
        assert jobs_mod._has_today_kline_1d(conn) is True
    finally:
        conn.close()


def test_has_today_kline_1d_false_for_4h(db_path):
    """4h 候不算 1d。"""
    today_midnight = (
        datetime.now(timezone.utc).date().isoformat() + "T00:00:00Z"
    )
    _seed_kline(db_path, timeframe="4h", open_time_utc=today_midnight,
                inserted_at_utc=_today_iso())
    conn = _conn(db_path)
    try:
        assert jobs_mod._has_today_kline_1d(conn) is False
    finally:
        conn.close()


def test_has_this_week_kline_1w_true_when_monday_exists(db_path):
    today = datetime.now(timezone.utc).date()
    monday = today - timedelta(days=today.weekday())
    monday_iso = monday.isoformat() + "T00:00:00Z"
    _seed_kline(db_path, timeframe="1w", open_time_utc=monday_iso,
                inserted_at_utc=_today_iso())
    conn = _conn(db_path)
    try:
        assert jobs_mod._has_this_week_kline_1w(conn) is True
    finally:
        conn.close()


def test_has_this_week_kline_1w_false_when_only_last_week(db_path):
    today = datetime.now(timezone.utc).date()
    monday = today - timedelta(days=today.weekday())
    last_monday = (monday - timedelta(days=7)).isoformat() + "T00:00:00Z"
    _seed_kline(db_path, timeframe="1w", open_time_utc=last_monday,
                inserted_at_utc=_yesterday_iso())
    conn = _conn(db_path)
    try:
        assert jobs_mod._has_this_week_kline_1w(conn) is False
    finally:
        conn.close()


# ============================================================
# job_collect_macro skip + run
# ============================================================

def test_macro_skip_when_today_already_inserted(db_path):
    _seed_metric(
        db_path, "macro_metrics", metric_name="dxy",
        captured_at_utc=_yesterday_iso(), value=100.0,
        inserted_at_utc=_today_iso(),
    )
    # FredCollector 不该被实例化:patch 它,断言未 call
    fred_cls = MagicMock()
    with patch("src.data.collectors.fred.FredCollector", fred_cls):
        result = jobs_mod.job_collect_macro(conn_factory=lambda: _conn(db_path))
    assert result["status"] == "skipped"
    assert "today" in result["reason"]
    assert fred_cls.call_count == 0  # 没实例化 → 没浪费 API quota
    # skip 不调 refresh_factor_cards
    assert "factor_cards_refresh" not in result


def test_macro_runs_when_today_missing(db_path):
    _seed_metric(
        db_path, "macro_metrics", metric_name="dxy",
        captured_at_utc=_yesterday_iso(), value=100.0,
        inserted_at_utc=_yesterday_iso(),  # 昨天写入,今天还没跑
    )
    fred_inst = MagicMock()
    fred_inst.enabled = True
    fred_inst.collect_and_save_all.return_value = {"dxy": 5}
    with patch("src.data.collectors.fred.FredCollector", return_value=fred_inst):
        result = jobs_mod.job_collect_macro(conn_factory=lambda: _conn(db_path))
    assert result["status"] == "ok"
    assert fred_inst.collect_and_save_all.called


# ============================================================
# job_collect_onchain skip + run
# ============================================================

def test_onchain_skip_when_today_already_inserted(db_path):
    _seed_metric(
        db_path, "onchain_metrics", metric_name="mvrv_z_score",
        captured_at_utc=_yesterday_iso(), value=2.0,
        inserted_at_utc=_today_iso(),
    )
    gn_cls = MagicMock()
    with patch("src.data.collectors.glassnode.GlassnodeCollector", gn_cls):
        result = jobs_mod.job_collect_onchain(conn_factory=lambda: _conn(db_path))
    assert result["status"] == "skipped"
    assert "today" in result["reason"]
    assert gn_cls.call_count == 0
    # skip 不该 enqueue pipeline_run(没有新数据)
    assert result.get("events_triggered") in (None, [], )


def test_onchain_runs_when_today_missing(db_path):
    gn_inst = MagicMock()
    for fn_name in jobs_mod._GLASSNODE_FETCHERS:
        getattr(gn_inst, fn_name).return_value = [
            {"timestamp": _today_iso(),
             "metric_name": fn_name.replace("fetch_", ""),
             "metric_value": 1.0, "source": "test"}
        ]
    with patch("src.data.collectors.glassnode.GlassnodeCollector",
               return_value=gn_inst):
        result = jobs_mod.job_collect_onchain(conn_factory=lambda: _conn(db_path))
    assert result["status"] == "ok"
    assert result["total_upserted"] >= 1


# ============================================================
# job_collect_klines_daily skip + run
# ============================================================

def test_klines_daily_skip_when_today_1d_exists(db_path):
    today_midnight = (
        datetime.now(timezone.utc).date().isoformat() + "T00:00:00Z"
    )
    _seed_kline(db_path, timeframe="1d", open_time_utc=today_midnight,
                inserted_at_utc=_today_iso())
    cg_cls = MagicMock()
    with patch("src.data.collectors.coinglass.CoinglassCollector", cg_cls):
        result = jobs_mod.job_collect_klines_daily(
            conn_factory=lambda: _conn(db_path))
    assert result["status"] == "skipped"
    assert cg_cls.call_count == 0


def test_klines_daily_runs_when_only_4h_exists(db_path):
    """只有 4h 候,1d 还没 → 应该跑(防止 4h 误判为 1d 已有)。"""
    today_midnight = (
        datetime.now(timezone.utc).date().isoformat() + "T00:00:00Z"
    )
    _seed_kline(db_path, timeframe="4h", open_time_utc=today_midnight,
                inserted_at_utc=_today_iso())

    cg_inst = MagicMock()
    cg_inst.fetch_klines.return_value = [
        {"timestamp": today_midnight, "open": 1, "high": 2,
         "low": 0.5, "close": 1.5, "volume": 100},
    ]
    with patch("src.data.collectors.coinglass.CoinglassCollector",
               return_value=cg_inst):
        result = jobs_mod.job_collect_klines_daily(
            conn_factory=lambda: _conn(db_path))
    assert result["status"] == "ok"
    assert cg_inst.fetch_klines.called


# ============================================================
# job_collect_klines_weekly skip + run
# ============================================================

def test_klines_weekly_skip_when_this_week_1w_exists(db_path):
    today = datetime.now(timezone.utc).date()
    monday = today - timedelta(days=today.weekday())
    monday_iso = monday.isoformat() + "T00:00:00Z"
    _seed_kline(db_path, timeframe="1w", open_time_utc=monday_iso,
                inserted_at_utc=_today_iso())
    cg_cls = MagicMock()
    with patch("src.data.collectors.coinglass.CoinglassCollector", cg_cls):
        result = jobs_mod.job_collect_klines_weekly(
            conn_factory=lambda: _conn(db_path))
    assert result["status"] == "skipped"
    assert cg_cls.call_count == 0


def test_klines_weekly_runs_when_only_last_week_exists(db_path):
    today = datetime.now(timezone.utc).date()
    monday = today - timedelta(days=today.weekday())
    last_monday = (monday - timedelta(days=7)).isoformat() + "T00:00:00Z"
    _seed_kline(db_path, timeframe="1w", open_time_utc=last_monday,
                inserted_at_utc=_yesterday_iso())

    cg_inst = MagicMock()
    cg_inst.fetch_klines.return_value = [
        {"timestamp": monday.isoformat() + "T00:00:00Z",
         "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 100},
    ]
    with patch("src.data.collectors.coinglass.CoinglassCollector",
               return_value=cg_inst):
        result = jobs_mod.job_collect_klines_weekly(
            conn_factory=lambda: _conn(db_path))
    assert result["status"] == "ok"
    assert cg_inst.fetch_klines.called


# ============================================================
# scheduler.yaml multi-cron registers as OrTrigger
# ============================================================

def test_or_trigger_registers_all_cron_times():
    """build_scheduler 后,collect_onchain / collect_macro / klines_daily /
    klines_weekly 的 trigger 都是 OrTrigger,sub-trigger 数 == yaml list 长度。"""
    from src.scheduler.main import build_scheduler

    sched = build_scheduler(blocking=False)
    try:
        jobs_by_id = {j.id: j for j in sched.get_jobs()}

        # 4 个低频 job 都用 OrTrigger
        expected = {
            "collect_onchain":     10,
            "collect_macro":        7,
            "collect_klines_daily": 9,
            "collect_klines_weekly": 7,
        }
        for jid, n in expected.items():
            assert jid in jobs_by_id, f"{jid} missing"
            trig = jobs_by_id[jid].trigger
            assert isinstance(trig, OrTrigger), \
                f"{jid} trigger is {type(trig).__name__}, expected OrTrigger"
            assert len(trig.triggers) == n, \
                f"{jid}: expected {n} sub-triggers, got {len(trig.triggers)}"
            for sub in trig.triggers:
                assert isinstance(sub, CronTrigger)

        # collect_klines_1h 仍是单 CronTrigger(高频不用补救)
        assert isinstance(jobs_by_id["collect_klines_1h"].trigger, CronTrigger)
    finally:
        # 不 start;build_scheduler 只是构造未启动
        pass
