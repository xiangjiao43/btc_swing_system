"""Sprint A — collector job 端到端集成测试,确认 fetch_attempts 真写入。

§Z 端到端断言:每个 case 用真 SQLite + 真 DAO,跑完 job 后 SELECT
fetch_attempts 验真行数 + 字段值。不能只 mock .called=True。
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.data.storage.connection import init_db
from src.scheduler import jobs as jobs_mod


@pytest.fixture
def db_path():
    tmp = Path(tempfile.mkdtemp()) / "fetch_attempts_it.db"
    init_db(db_path=tmp, verbose=False)
    return tmp


@pytest.fixture
def conn_factory(db_path):
    return lambda: sqlite3.connect(db_path)


def _attempts(db_path: Path, source: str | None = None) -> list[sqlite3.Row]:
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    try:
        if source is None:
            rows = c.execute(
                "SELECT * FROM fetch_attempts ORDER BY id ASC"
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM fetch_attempts WHERE source = ? "
                "ORDER BY id ASC",
                (source,),
            ).fetchall()
        return rows
    finally:
        c.close()


# ============================================================
# Glassnode 全部 quota_exceeded(对应当前生产 bug 现象)
# ============================================================

def test_collect_onchain_all_403_writes_failure_row_with_quota_reason(
    db_path, conn_factory,
):
    """13 个 fetcher 全 raise HTTP 403 → 1 行 fetch_attempts:
    source=glassnode_onchain, status=failure, failure_reason=quota_exceeded。"""
    gn_inst = MagicMock()
    for fn in jobs_mod._GLASSNODE_FETCHERS:
        getattr(gn_inst, fn).side_effect = RuntimeError(
            "HTTP 403 (non-retry) on /v1/metrics/x: "
            '{"error":{"code":"HTTP_ERROR","message":"您的 glassnode 周期内配额已用尽"}}'
        )

    with patch("src.data.collectors.glassnode.GlassnodeCollector",
               return_value=gn_inst):
        jobs_mod.job_collect_onchain(conn_factory=conn_factory)

    rows = _attempts(db_path, "glassnode_onchain")
    assert len(rows) == 1, "13 fetcher 必须聚合成 1 行,不是 13 行"
    row = rows[0]
    assert row["status"] == "failure"
    assert row["failure_reason"] == "quota_exceeded"
    assert row["rows_upserted"] == 0
    assert row["error_message"] is not None
    assert "HTTP 403" in row["error_message"]
    assert row["duration_ms"] is not None
    assert row["duration_ms"] >= 0


# ============================================================
# Glassnode 全部成功
# ============================================================

def test_collect_onchain_all_success_writes_success_row(db_path, conn_factory):
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
        jobs_mod.job_collect_onchain(conn_factory=conn_factory)

    rows = _attempts(db_path, "glassnode_onchain")
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "success"
    assert row["failure_reason"] is None
    assert row["rows_upserted"] >= len(jobs_mod._GLASSNODE_FETCHERS)


# ============================================================
# klines_1h 写两行(binance_kline + coinglass_derivatives),分别记录
# ============================================================

def test_collect_klines_1h_writes_two_source_rows(db_path, conn_factory):
    cg_inst = MagicMock()
    cg_inst.fetch_klines.return_value = [
        {"timestamp": f"2026-04-27T{h:02d}:00:00Z",
         "open": 50000, "high": 50100, "low": 49900, "close": 50050,
         "volume": 100.0}
        for h in range(24)
    ]
    for fn in jobs_mod._DERIVATIVES_FETCHERS_1H:
        getattr(cg_inst, fn).return_value = [
            {"timestamp": "2026-04-27T00:00:00Z",
             "metric_name": fn.replace("fetch_", ""),
             "metric_value": 0.0001}
        ]

    with patch("src.data.collectors.coinglass.CoinglassCollector",
               return_value=cg_inst):
        jobs_mod.job_collect_klines_1h(conn_factory=conn_factory)

    all_rows = _attempts(db_path)
    sources = {r["source"] for r in all_rows}
    assert sources == {"binance_kline", "coinglass_derivatives"}, (
        f"expected exactly 2 source labels, got {sources}"
    )
    for r in all_rows:
        assert r["status"] == "success"
        assert r["rows_upserted"] is not None and r["rows_upserted"] > 0


def test_collect_klines_1h_kline_succeeds_derivatives_fail(db_path, conn_factory):
    """K 线 OK + 衍生品所有 fn 报 500 → binance_kline=success,
    coinglass_derivatives=failure(api_error)。"""
    cg_inst = MagicMock()
    cg_inst.fetch_klines.return_value = [
        {"timestamp": "2026-04-27T00:00:00Z",
         "open": 50000, "high": 50100, "low": 49900, "close": 50050,
         "volume": 100.0}
    ]
    for fn in jobs_mod._DERIVATIVES_FETCHERS_1H:
        getattr(cg_inst, fn).side_effect = RuntimeError(
            "HTTP 500 internal server error on /api/foo"
        )

    with patch("src.data.collectors.coinglass.CoinglassCollector",
               return_value=cg_inst):
        jobs_mod.job_collect_klines_1h(conn_factory=conn_factory)

    rows_kl = _attempts(db_path, "binance_kline")
    rows_dv = _attempts(db_path, "coinglass_derivatives")
    assert len(rows_kl) == 1
    assert rows_kl[0]["status"] == "success"
    assert len(rows_dv) == 1
    assert rows_dv[0]["status"] == "failure"
    assert rows_dv[0]["failure_reason"] == "api_error"


# ============================================================
# fred_macro 失败路径
# ============================================================

def test_collect_macro_failure_writes_failure_row(db_path, conn_factory):
    fred_inst = MagicMock()
    fred_inst.enabled = True
    fred_inst.collect_and_save_all.side_effect = RuntimeError(
        "HTTP 429 rate limit exceeded for FRED API"
    )

    with patch("src.data.collectors.fred.FredCollector", return_value=fred_inst):
        jobs_mod.job_collect_macro(conn_factory=conn_factory)

    rows = _attempts(db_path, "fred_macro")
    assert len(rows) == 1
    assert rows[0]["status"] == "failure"
    assert rows[0]["failure_reason"] == "quota_exceeded"


def test_collect_macro_disabled_writes_no_row(db_path, conn_factory):
    """fc.enabled=False 路径不发 fetch → 不应写 fetch_attempts(skip)。"""
    fred_inst = MagicMock()
    fred_inst.enabled = False
    with patch("src.data.collectors.fred.FredCollector", return_value=fred_inst):
        jobs_mod.job_collect_macro(conn_factory=conn_factory)
    assert _attempts(db_path, "fred_macro") == []


# ============================================================
# 今日已写过的 skip 路径不写 fetch_attempts
# ============================================================

def test_collect_onchain_skipped_today_writes_no_row(db_path, conn_factory):
    """_onchain_today_complete=True 时直接 skip,fetch 没发生 → 不写 fetch_attempts。"""
    with patch.object(jobs_mod, "_onchain_today_complete", return_value=True):
        result = jobs_mod.job_collect_onchain(conn_factory=conn_factory)
    assert result["status"] == "skipped"
    assert _attempts(db_path, "glassnode_onchain") == []


# ============================================================
# Sprint B 副作用 bug 反退化:Glassnode 全 fail 时不应 enqueue pipeline_run
# ============================================================

def test_collect_onchain_all_fail_does_not_enqueue_pipeline_run(
    db_path, conn_factory,
):
    """13 个 fetcher 全 403 → derived_mvrv 仍可能本地写若干行,但 Sprint B
    修后不应 enqueue event_onchain pipeline_run(上游 fail 状态)。
    反退化:Sprint A 之前的 `if total > 0` 让 derived 写行也触发 enqueue。"""
    gn_inst = MagicMock()
    for fn in jobs_mod._GLASSNODE_FETCHERS:
        getattr(gn_inst, fn).side_effect = RuntimeError("HTTP 403 quota")

    # 模拟 derived_mvrv 写了几行(模拟历史 realized_price 还在 DB 的副作用)
    def _fake_compute_derived(_conn):
        return {"lth_mvrv": 5, "sth_mvrv": 5}

    with patch("src.data.collectors.glassnode.GlassnodeCollector",
               return_value=gn_inst), \
         patch("src.data.collectors.derived_onchain.compute_and_save_derived_mvrv",
               side_effect=_fake_compute_derived), \
         patch.object(jobs_mod, "_enqueue_pipeline_run") as enqueue:
        result = jobs_mod.job_collect_onchain(conn_factory=conn_factory)

    enqueue.assert_not_called()
    assert result["events_triggered"] == []
    # fetch_attempts 仍应记 1 行 failure
    rows = _attempts(db_path, "glassnode_onchain")
    assert len(rows) == 1
    assert rows[0]["status"] == "failure"


def test_collect_onchain_real_success_does_NOT_enqueue_pipeline_run(
    db_path, conn_factory,
):
    """Sprint F.1(2026-05-09)反退化:13 fetcher 全 success + 入库 > 0,
    但 collect_onchain 不再 enqueue pipeline_run(用户决策严守"一天 1 次"
    原则,完整版见 tests/test_event_onchain_chain.py)。"""
    gn_inst = MagicMock()
    for fn in jobs_mod._GLASSNODE_FETCHERS:
        getattr(gn_inst, fn).return_value = [
            {"timestamp": "2026-04-27T00:00:00Z",
             "metric_name": fn.replace("fetch_", ""),
             "metric_value": 1.0,
             "source": "glassnode_primary"}
        ]

    with patch("src.data.collectors.glassnode.GlassnodeCollector",
               return_value=gn_inst), \
         patch.object(jobs_mod, "_enqueue_pipeline_run") as enqueue:
        result = jobs_mod.job_collect_onchain(conn_factory=conn_factory)

    enqueue.assert_not_called()
    assert result["events_triggered"] == []
    # 诊断字段:fetch 真成功仍可被读出(便于 KPI / 排查)
    assert result.get("glassnode_fetch_success") is True
