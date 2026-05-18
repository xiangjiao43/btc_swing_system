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

def test_onchain_partial_today_keeps_other_fetchers_running(db_path):
    """Sprint 1.6.2 关键反退化:推翻旧 Sprint C "任一一手 source 有行就全 job
    skip" 设计。新行为:每个 fetcher 独立检查代表 metric 今天有无行;只要
    任一 fetcher 缺失 → job 继续跑,缺失的 fetcher 才被实际抓。

    模拟场景:08:30 主档已写 mvrv_z_score 一行(代表 fetch_mvrv_z_score
    今天完成),其他 21 个 fetcher 全部缺失(模拟 puell 等失败 + 别的 fetcher
    本档还没跑到)。09:30 补救档应该:
      - 不整 job skip(关键!)
      - mvrv_z_score fetcher 内部 skip(per-fetcher,不浪费 HTTP)
      - 其他 fetcher 该 fetch 还 fetch
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_captured = f"{today}T08:00:00Z"
    conn = _conn(db_path)
    conn.execute(
        "INSERT INTO onchain_metrics "
        "(metric_name, captured_at_utc, value, source, inserted_at_utc) "
        "VALUES (?, ?, ?, ?, ?)",
        ("mvrv_z_score", today_captured, 1.5, "glassnode_primary",
         _today_iso()),
    )
    conn.commit()
    conn.close()

    # mock GlassnodeCollector,每个 fetch_xxx 返回空 list(避免真实 HTTP)
    gn_instance = MagicMock()
    gn_instance.fetch_mvrv_z_score = MagicMock(return_value=[])
    for fn in jobs_mod._GLASSNODE_FETCHERS:
        setattr(gn_instance, fn, MagicMock(return_value=[]))
    with patch(
        "src.data.collectors.glassnode.GlassnodeCollector",
        return_value=gn_instance,
    ):
        with patch(
            "src.data.collectors.derived_onchain.compute_and_save_derived_mvrv",
            return_value={},
        ):
            result = jobs_mod.job_collect_onchain(
                conn_factory=lambda: _conn(db_path),
            )

    # 关键:整 job 不 skip,GlassnodeCollector 被实例化
    assert result["status"] != "skipped"
    # mvrv_z_score 命中 per-fetcher skip,所以它的 fetch_xxx 不被调
    assert gn_instance.fetch_mvrv_z_score.call_count == 0
    # 其他 21 个 fetcher 都被调过(代表 metric 今天没行 → fetch)
    fetched_count = result.get("fetcher_fetched_count", -1)
    skipped_count = result.get("fetcher_skipped_count", -1)
    assert skipped_count == 1, f"expected exactly mvrv_z_score skipped, got {skipped_count}"
    assert fetched_count == len(jobs_mod._GLASSNODE_FETCHERS) - 1, \
        f"expected 21 fetched, got {fetched_count}"


def test_onchain_skip_when_all_fetchers_completed_today(db_path):
    """Sprint 1.6.2 新场景:22 个 fetcher 代表 metric 今天全部已有行 →
    整 job skip,GlassnodeCollector 0 次实例化、0 HTTP 浪费。
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_captured = f"{today}T08:00:00Z"
    conn = _conn(db_path)
    # 给每个 fetcher 的代表 metric 都种一行
    for fn_name, metric_name in jobs_mod._FETCHER_TO_REPRESENTATIVE_METRIC.items():
        conn.execute(
            "INSERT INTO onchain_metrics "
            "(metric_name, captured_at_utc, value, source, inserted_at_utc) "
            "VALUES (?, ?, ?, ?, ?)",
            (metric_name, today_captured, 1.0, "glassnode_primary",
             _today_iso()),
        )
    conn.commit()
    conn.close()

    gn_cls = MagicMock()
    with patch("src.data.collectors.glassnode.GlassnodeCollector", gn_cls):
        result = jobs_mod.job_collect_onchain(
            conn_factory=lambda: _conn(db_path),
        )
    assert result["status"] == "skipped"
    assert "today" in result["reason"]
    assert gn_cls.call_count == 0, "GlassnodeCollector 不应被实例化 — 0 HTTP 浪费"
    assert result.get("events_triggered") in (None, [],)


def test_onchain_today_complete_false_when_any_fetcher_missing(db_path):
    """Sprint 1.6.2:_onchain_today_complete 现在要求 22 个 fetcher 代表
    metric 全部今天有行才返 True。种 21 个 → 仍 False(puell 缺)。"""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_captured = f"{today}T08:00:00Z"
    conn = _conn(db_path)
    # 种 21 个代表 metric(故意漏 puell_multiple)
    for fn_name, metric_name in jobs_mod._FETCHER_TO_REPRESENTATIVE_METRIC.items():
        if metric_name == "puell_multiple":
            continue
        conn.execute(
            "INSERT INTO onchain_metrics "
            "(metric_name, captured_at_utc, value, source, inserted_at_utc) "
            "VALUES (?, ?, ?, ?, ?)",
            (metric_name, today_captured, 1.0, "glassnode_primary", _today_iso()),
        )
    conn.commit()
    conn.close()

    from src.scheduler.jobs import _onchain_today_complete, _fetcher_completed_today
    c = _conn(db_path)
    c.row_factory = sqlite3.Row
    try:
        # puell 没行 → 整体不算 complete
        assert _onchain_today_complete(c) is False
        # 单 fetcher 粒度验证
        assert _fetcher_completed_today(c, "fetch_mvrv_z_score") is True
        assert _fetcher_completed_today(c, "fetch_puell_multiple") is False
    finally:
        c.close()


def test_onchain_skip_when_today_quota_exceeded(db_path):
    """Sprint C 新增:今天 fetch_attempts 撞 quota → skip 后续档。"""
    from src.data.storage.dao import FetchAttemptsDAO
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = _conn(db_path)
    try:
        FetchAttemptsDAO.record_attempt(
            conn, source="glassnode_onchain", status="failure",
            failure_reason="quota_exceeded",
            error_message="HTTP 403 quota stub",
            attempted_at_utc=today_iso,
        )
        conn.commit()
    finally:
        conn.close()

    gn_cls = MagicMock()
    with patch("src.data.collectors.glassnode.GlassnodeCollector", gn_cls):
        result = jobs_mod.job_collect_onchain(conn_factory=lambda: _conn(db_path))
    assert result["status"] == "skipped"
    assert gn_cls.call_count == 0


def test_onchain_no_skip_when_today_quota_failure_wrote_rows(db_path):
    """部分成功的 Glassnode quota 失败不能阻止后续重试。"""
    from src.data.storage.dao import FetchAttemptsDAO
    from src.scheduler.jobs import _onchain_today_complete
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = _conn(db_path)
    try:
        FetchAttemptsDAO.record_attempt(
            conn, source="glassnode_onchain", status="failure",
            failure_reason="quota_exceeded",
            error_message="HTTP 429 on one endpoint",
            rows_upserted=869,
            attempted_at_utc=today_iso,
        )
        conn.commit()
        assert _onchain_today_complete(conn) is False
    finally:
        conn.close()


def test_onchain_no_skip_when_today_only_has_non_quota_failure(db_path):
    """Sprint C 关键反退化:network_error / api_error / parse_error 等非 quota
    失败不能短路 → 后续档应继续重试。"""
    from src.data.storage.dao import FetchAttemptsDAO
    from src.scheduler.jobs import _onchain_today_complete
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = _conn(db_path)
    try:
        FetchAttemptsDAO.record_attempt(
            conn, source="glassnode_onchain", status="failure",
            failure_reason="network_error",
            error_message="ConnectionError stub",
            attempted_at_utc=today_iso,
        )
        conn.commit()
    finally:
        conn.close()
    c = _conn(db_path)
    c.row_factory = sqlite3.Row
    try:
        assert _onchain_today_complete(c) is False
    finally:
        c.close()


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
    # Sprint 1.6.1 起 klines_daily skip gate 改细粒度:1d 候 + btc_dominance/etf_flow
    # 必须都今天已写过才 skip。本测试种 1d K 线 + derivatives_snapshots 行
    # 含 btc_dominance,验细粒度 skip。
    today_midnight = (
        datetime.now(timezone.utc).date().isoformat() + "T00:00:00Z"
    )
    _seed_kline(db_path, timeframe="1d", open_time_utc=today_midnight,
                inserted_at_utc=_today_iso())
    # 种 derivatives_snapshots 一行,full_data_json 含 btc_dominance
    conn = _conn(db_path)
    conn.execute(
        "INSERT INTO derivatives_snapshots "
        "(captured_at_utc, full_data_json, inserted_at_utc) "
        "VALUES (?, ?, ?)",
        (
            f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}T08:00:00Z",
            '{"btc_dominance": 0.55}',
            _today_iso(),
        ),
    )
    conn.commit()
    conn.close()
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
        # Sprint 1.6.2(2026-05-17):collect_onchain 3 → 2 档错峰
        # (09:30 主 + 10:30 补救;per-fetcher skip 让 2 档够用)。
        expected = {
            "collect_onchain":      2,
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
