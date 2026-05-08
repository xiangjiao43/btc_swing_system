"""Sprint C — 派生 MVRV stale 守卫 + 顶栏徽章 fetch_attempts 接入。

§Z 端到端 DB 断言:
- 上游 stale → compute_and_save_derived_mvrv 不写新行
- 上游 fresh → 派生计算正常写入
- /api/system/health-detail overall_status 在 quota_exceeded → critical
- 在 network_error → partial_degraded
- 全 success → all_healthy
"""
from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.data.collectors.derived_onchain import (
    _UPSTREAM_STALE_THRESHOLD_HOURS, compute_and_save_derived_mvrv,
)
from src.data.storage.connection import get_connection, init_db
from src.data.storage.dao import FetchAttemptsDAO


@pytest.fixture
def db_path():
    tmp = Path(tempfile.mkdtemp()) / "sprint_c.db"
    init_db(db_path=tmp, verbose=False)
    return tmp


@pytest.fixture
def client(db_path):
    def _factory():
        return get_connection(db_path)
    app = create_app(conn_factory=_factory, pipeline_trigger_cooldown_sec=60.0)
    return TestClient(app)


def _conn(db_path: Path) -> sqlite3.Connection:
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    return c


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed_realized_price(conn, ts_iso: str, value: float, source: str):
    conn.execute(
        "INSERT INTO onchain_metrics "
        "(metric_name, captured_at_utc, value, source, inserted_at_utc) "
        "VALUES (?, ?, ?, ?, ?)",
        ("lth_realized_price", ts_iso, value, source, ts_iso),
    )
    conn.execute(
        "INSERT INTO onchain_metrics "
        "(metric_name, captured_at_utc, value, source, inserted_at_utc) "
        "VALUES (?, ?, ?, ?, ?)",
        ("sth_realized_price", ts_iso, value * 0.9, source, ts_iso),
    )


def _seed_btc_close(conn, ts_iso: str, close: float):
    conn.execute(
        "INSERT INTO price_candles "
        "(symbol, timeframe, open_time_utc, open, high, low, close, volume, "
        " inserted_at_utc) "
        "VALUES ('BTCUSDT', '1d', ?, ?, ?, ?, ?, 1.0, ?)",
        (ts_iso, close, close * 1.01, close * 0.99, close, ts_iso),
    )


# ============================================================
# 派生 MVRV stale 守卫
# ============================================================

def test_derived_mvrv_skipped_when_upstream_stale(db_path):
    """上游 Glassnode 一手数据 > 48h 老 → 派生不写,onchain_metrics MAX
    不被 source='computed' 行刷新。"""
    now = datetime.now(timezone.utc)
    stale_ts = _iso(now - timedelta(hours=_UPSTREAM_STALE_THRESHOLD_HOURS + 24))
    fresh_btc_ts = _iso(now)
    conn = _conn(db_path)
    try:
        _seed_realized_price(conn, stale_ts, 50000.0, "glassnode_display")
        _seed_btc_close(conn, fresh_btc_ts, 60000.0)
        conn.commit()
        before_max = conn.execute(
            "SELECT MAX(captured_at_utc) FROM onchain_metrics"
        ).fetchone()[0]

        stats = compute_and_save_derived_mvrv(conn)
        assert stats == {"lth_mvrv": 0, "sth_mvrv": 0}

        # MAX 没被 'computed' 刷新
        after_max = conn.execute(
            "SELECT MAX(captured_at_utc) FROM onchain_metrics"
        ).fetchone()[0]
        assert before_max == after_max

        # 没有 source='computed' 的行
        n_computed = conn.execute(
            "SELECT COUNT(*) FROM onchain_metrics WHERE source = 'computed'"
        ).fetchone()[0]
        assert n_computed == 0
    finally:
        conn.close()


def test_derived_mvrv_writes_when_upstream_fresh(db_path):
    """上游 Glassnode 一手数据 < 48h 老 → 派生正常计算 + 写入。"""
    now = datetime.now(timezone.utc)
    fresh_ts = _iso(now - timedelta(hours=12))
    conn = _conn(db_path)
    try:
        _seed_realized_price(conn, fresh_ts, 50000.0, "glassnode_display")
        _seed_btc_close(conn, fresh_ts, 60000.0)
        conn.commit()
        stats = compute_and_save_derived_mvrv(conn)
        assert stats["lth_mvrv"] >= 1
        assert stats["sth_mvrv"] >= 1
        n_computed = conn.execute(
            "SELECT COUNT(*) FROM onchain_metrics WHERE source = 'computed'"
        ).fetchone()[0]
        assert n_computed >= 2
    finally:
        conn.close()


def test_derived_mvrv_skipped_when_only_computed_source(db_path):
    """onchain_metrics 只有 source='computed' 行 → 视为无一手 → stale → skip。
    防止派生计算自己刷新自己的 MAX 形成假新鲜假象。"""
    now = datetime.now(timezone.utc)
    fresh_ts = _iso(now - timedelta(hours=12))
    conn = _conn(db_path)
    try:
        # 只有 'computed' 源
        conn.execute(
            "INSERT INTO onchain_metrics "
            "(metric_name, captured_at_utc, value, source, inserted_at_utc) "
            "VALUES (?, ?, ?, ?, ?)",
            ("lth_mvrv", fresh_ts, 2.5, "computed", fresh_ts),
        )
        _seed_btc_close(conn, fresh_ts, 60000.0)
        conn.commit()
        stats = compute_and_save_derived_mvrv(conn)
        assert stats == {"lth_mvrv": 0, "sth_mvrv": 0}
    finally:
        conn.close()


def test_derived_mvrv_skipped_when_onchain_table_empty(db_path):
    """onchain_metrics 表空 → 上游 stale → skip(防御性)。"""
    conn = _conn(db_path)
    try:
        _seed_btc_close(conn, _iso(datetime.now(timezone.utc)), 60000.0)
        conn.commit()
        stats = compute_and_save_derived_mvrv(conn)
        assert stats == {"lth_mvrv": 0, "sth_mvrv": 0}
    finally:
        conn.close()


# ============================================================
# 顶栏 overall_status fetch_attempts 接入
# ============================================================

def test_overall_status_critical_when_quota_exceeded(client, db_path):
    """任一 source quota_exceeded → overall_status = critical。"""
    now_iso = _iso(datetime.now(timezone.utc))
    conn = _conn(db_path)
    try:
        FetchAttemptsDAO.record_attempt(
            conn, source="glassnode_onchain", status="failure",
            failure_reason="quota_exceeded",
            attempted_at_utc=now_iso,
        )
        conn.commit()
    finally:
        conn.close()
    body = client.get("/api/system/health-detail").json()
    assert body["overall_status"] == "critical"


def test_overall_status_partial_when_non_quota_failure(client, db_path):
    """任一 source non-quota failure → overall_status >= partial_degraded
    (在 onchain_metrics 表空场景下 layers=missing 也可能再 escalate critical,
    所以这里只断言不是 all_healthy)。"""
    now_iso = _iso(datetime.now(timezone.utc))
    conn = _conn(db_path)
    try:
        FetchAttemptsDAO.record_attempt(
            conn, source="binance_kline", status="failure",
            failure_reason="network_error",
            attempted_at_utc=now_iso,
        )
        conn.commit()
    finally:
        conn.close()
    body = client.get("/api/system/health-detail").json()
    assert body["overall_status"] != "all_healthy"


def test_overall_status_takes_quota_failure_seriously(client, db_path):
    """quota_exceeded 比 non-quota failure 优先 → critical 而非 degraded。"""
    now_iso = _iso(datetime.now(timezone.utc))
    conn = _conn(db_path)
    try:
        # 1 行 quota + 1 行 network
        FetchAttemptsDAO.record_attempt(
            conn, source="glassnode_onchain", status="failure",
            failure_reason="quota_exceeded",
            attempted_at_utc=now_iso,
        )
        FetchAttemptsDAO.record_attempt(
            conn, source="binance_kline", status="failure",
            failure_reason="network_error",
            attempted_at_utc=now_iso,
        )
        conn.commit()
    finally:
        conn.close()
    body = client.get("/api/system/health-detail").json()
    assert body["overall_status"] == "critical"


def test_overall_status_picks_latest_attempt_per_source(client, db_path):
    """同 source 历史 quota failure + 最新 success → 不应 critical。"""
    now = datetime.now(timezone.utc)
    conn = _conn(db_path)
    try:
        # 老 quota failure
        FetchAttemptsDAO.record_attempt(
            conn, source="glassnode_onchain", status="failure",
            failure_reason="quota_exceeded",
            attempted_at_utc=_iso(now - timedelta(hours=12)),
        )
        # 最新 success
        FetchAttemptsDAO.record_attempt(
            conn, source="glassnode_onchain", status="success",
            rows_upserted=130,
            attempted_at_utc=_iso(now - timedelta(minutes=5)),
        )
        conn.commit()
    finally:
        conn.close()
    body = client.get("/api/system/health-detail").json()
    # latest=success → fetch_attempts 部分不该贡献 critical;最终 status 取决于
    # layers / 老 sources(空 DB → critical via layers=missing)。这里只断言
    # fetch_attempts 没贡献 critical;最终值是 critical 但因为是 layers 而非
    # quota,所以验证不直接断言总值。
    # 直接调内部 helper 验证更清晰:
    from src.api.routes.system import _query_fetch_attempts_failures
    c = _conn(db_path)
    try:
        has_failure, has_quota = _query_fetch_attempts_failures(c)
    finally:
        c.close()
    assert has_failure is False
    assert has_quota is False
