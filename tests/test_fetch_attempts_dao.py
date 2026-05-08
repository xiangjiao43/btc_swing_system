"""Sprint A — FetchAttemptsDAO 单测(写 / 读 / 时间过滤)。"""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest

from src.data.storage.dao import FetchAttemptsDAO


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    with open("src/data/storage/schema.sql", encoding="utf-8") as f:
        c.executescript(f.read())
    yield c
    c.close()


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_record_attempt_success_returns_id(conn):
    rid = FetchAttemptsDAO.record_attempt(
        conn, source="binance_kline", status="success",
        rows_upserted=24, duration_ms=320,
    )
    conn.commit()
    assert rid > 0


def test_record_attempt_writes_all_fields_for_success(conn):
    FetchAttemptsDAO.record_attempt(
        conn, source="fred_macro", status="success",
        rows_upserted=9, duration_ms=1200,
    )
    conn.commit()
    row = conn.execute(
        "SELECT source, status, failure_reason, error_message, "
        "       rows_upserted, duration_ms "
        "FROM fetch_attempts ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row["source"] == "fred_macro"
    assert row["status"] == "success"
    assert row["failure_reason"] is None
    assert row["error_message"] is None
    assert row["rows_upserted"] == 9
    assert row["duration_ms"] == 1200


def test_record_attempt_writes_all_fields_for_failure(conn):
    FetchAttemptsDAO.record_attempt(
        conn, source="glassnode_onchain", status="failure",
        failure_reason="quota_exceeded",
        error_message="HTTP 403 quota exhausted",
        rows_upserted=0, duration_ms=88,
    )
    conn.commit()
    row = conn.execute(
        "SELECT source, status, failure_reason, error_message, rows_upserted "
        "FROM fetch_attempts ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row["source"] == "glassnode_onchain"
    assert row["status"] == "failure"
    assert row["failure_reason"] == "quota_exceeded"
    assert "HTTP 403" in row["error_message"]
    assert row["rows_upserted"] == 0


def test_get_latest_attempt_none_when_empty(conn):
    assert FetchAttemptsDAO.get_latest_attempt(conn, "binance_kline") is None


def test_get_latest_attempt_picks_newest_for_source(conn):
    base = datetime(2026, 5, 8, 0, 0, 0, tzinfo=timezone.utc)
    FetchAttemptsDAO.record_attempt(
        conn, source="binance_kline", status="success",
        rows_upserted=10, attempted_at_utc=_iso(base),
    )
    FetchAttemptsDAO.record_attempt(
        conn, source="binance_kline", status="failure",
        failure_reason="network_error",
        attempted_at_utc=_iso(base + timedelta(hours=2)),
    )
    FetchAttemptsDAO.record_attempt(
        conn, source="fred_macro", status="success",
        rows_upserted=99, attempted_at_utc=_iso(base + timedelta(hours=3)),
    )
    conn.commit()

    latest = FetchAttemptsDAO.get_latest_attempt(conn, "binance_kline")
    assert latest is not None
    assert latest["status"] == "failure"
    assert latest["failure_reason"] == "network_error"

    other = FetchAttemptsDAO.get_latest_attempt(conn, "fred_macro")
    assert other is not None
    assert other["rows_upserted"] == 99


def test_get_recent_attempts_filters_by_window_and_source(conn):
    now = datetime.now(timezone.utc)
    FetchAttemptsDAO.record_attempt(
        conn, source="glassnode_onchain", status="failure",
        failure_reason="quota_exceeded",
        attempted_at_utc=_iso(now - timedelta(minutes=30)),
    )
    FetchAttemptsDAO.record_attempt(
        conn, source="glassnode_onchain", status="failure",
        failure_reason="quota_exceeded",
        attempted_at_utc=_iso(now - timedelta(hours=5)),
    )
    FetchAttemptsDAO.record_attempt(
        conn, source="glassnode_onchain", status="success",
        rows_upserted=130,
        attempted_at_utc=_iso(now - timedelta(hours=48)),
    )
    FetchAttemptsDAO.record_attempt(
        conn, source="binance_kline", status="success",
        rows_upserted=24,
        attempted_at_utc=_iso(now - timedelta(minutes=15)),
    )
    conn.commit()

    recent_glassnode = FetchAttemptsDAO.get_recent_attempts(
        conn, "glassnode_onchain", since_hours=2,
    )
    assert len(recent_glassnode) == 1
    assert recent_glassnode[0]["failure_reason"] == "quota_exceeded"

    recent_glassnode_24h = FetchAttemptsDAO.get_recent_attempts(
        conn, "glassnode_onchain", since_hours=24,
    )
    assert len(recent_glassnode_24h) == 2

    recent_binance = FetchAttemptsDAO.get_recent_attempts(
        conn, "binance_kline", since_hours=1,
    )
    assert len(recent_binance) == 1
    assert recent_binance[0]["rows_upserted"] == 24


def test_record_attempt_default_timestamp_uses_now(conn):
    before = datetime.now(timezone.utc) - timedelta(seconds=5)
    FetchAttemptsDAO.record_attempt(
        conn, source="coinglass_derivatives", status="success",
    )
    after = datetime.now(timezone.utc) + timedelta(seconds=5)
    conn.commit()
    row = conn.execute(
        "SELECT attempted_at_utc FROM fetch_attempts ORDER BY id DESC LIMIT 1"
    ).fetchone()
    ts_str = row["attempted_at_utc"]
    parsed = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    assert before <= parsed <= after
