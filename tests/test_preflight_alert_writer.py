"""tests/test_preflight_alert_writer.py — Sprint 2.8-B 监控告警。

§Z 端到端:
- 真 SQLite + alerts 表
- 调 _write_preflight_degraded_alert,断言 alerts 表 SELECT COUNT 真增
- /api/system/health 字段 preflight_alerts_24h 反映真实计数
- show_preflight_alerts.py 默认查 7 天
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.data.storage.connection import init_db
from src.pipeline.state_builder import _write_preflight_degraded_alert


def _row_conn(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture
def db_path():
    tmp = Path(tempfile.mkdtemp()) / "preflight.db"
    init_db(db_path=tmp, verbose=False)
    return tmp


# ============================================================
# _write_preflight_degraded_alert 直测
# ============================================================

def test_writer_inserts_row_when_pre_flight_degraded(db_path):
    conn = _row_conn(db_path)
    try:
        wrote = _write_preflight_degraded_alert(
            conn,
            run_id="run-1",
            run_ts_utc="2026-04-28T08:05:00Z",
            degraded_stages=["pre_flight.onchain", "pre_flight.macro"],
            metric_inserted_at={
                "onchain": {"sopr": "2026-04-28T07:50:00Z"},
                "macro":   {"dxy":  "2026-04-27T20:00:00Z"},
                "klines_by_tf": {}, "derivatives_snapshot": None,
            },
        )
        assert wrote is True
        rows = conn.execute(
            "SELECT alert_type, severity, message, raised_at_utc, "
            "       related_run_id "
            "FROM alerts WHERE alert_type='pre_flight_degraded'"
        ).fetchall()
        assert len(rows) == 1
        r = rows[0]
        assert r["alert_type"] == "pre_flight_degraded"
        assert r["severity"] == "warning"
        assert r["raised_at_utc"] == "2026-04-28T08:05:00Z"
        assert r["related_run_id"] == "run-1"
        # message 含两个 group
        assert "onchain" in r["message"]
        assert "macro" in r["message"]
        # message 含每个 group 的 inserted_at(从 metric_inserted_at 解析)
        assert "2026-04-28T07:50:00Z" in r["message"]
        assert "2026-04-27T20:00:00Z" in r["message"]
    finally:
        conn.close()


def test_writer_returns_false_when_no_pre_flight_degraded(db_path):
    """degraded_stages 没有 pre_flight.* → 不写 alert,返回 False。"""
    conn = _row_conn(db_path)
    try:
        wrote = _write_preflight_degraded_alert(
            conn,
            run_id="run-2",
            run_ts_utc="2026-04-28T08:05:00Z",
            degraded_stages=["adjudicator", "ai_summary"],
            metric_inserted_at={},
        )
        assert wrote is False
        cnt = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
        assert cnt == 0
    finally:
        conn.close()


def test_writer_handles_pre_flight_exception(db_path):
    """pre_flight.exception 这种伪 group → inserted_at 写 None,但仍记录 alert。"""
    conn = _row_conn(db_path)
    try:
        wrote = _write_preflight_degraded_alert(
            conn,
            run_id="run-3",
            run_ts_utc="2026-04-28T08:05:00Z",
            degraded_stages=["pre_flight.exception"],
            metric_inserted_at={},
        )
        assert wrote is True
        row = conn.execute(
            "SELECT message FROM alerts"
        ).fetchone()
        assert "exception" in row["message"]
        assert "None" in row["message"]
    finally:
        conn.close()


# ============================================================
# /api/system/health preflight_alerts_24h
# ============================================================

def _seed_alert(db_path: Path, raised_at_utc: str, alert_type: str = "pre_flight_degraded") -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO alerts (alert_type, severity, message, raised_at_utc) "
        "VALUES (?, 'warning', 'seed', ?)",
        (alert_type, raised_at_utc),
    )
    conn.commit()
    conn.close()


def test_health_preflight_alerts_24h_reflects_count(db_path):
    now = datetime.now(timezone.utc)
    # 24h 内 2 条;25h 前 1 条(应不计)
    _seed_alert(db_path, (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    _seed_alert(db_path, (now - timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    _seed_alert(db_path, (now - timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    # 不同 type 的 alert(不该被计)
    _seed_alert(db_path, (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                alert_type="other_type")

    app = create_app(conn_factory=lambda: _row_conn(db_path))
    with TestClient(app) as client:
        resp = client.get("/api/system/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["db_accessible"] is True
    assert body["preflight_alerts_24h"] == 2


def test_health_preflight_alerts_24h_zero_when_no_alerts(db_path):
    app = create_app(conn_factory=lambda: _row_conn(db_path))
    with TestClient(app) as client:
        resp = client.get("/api/system/health")
    assert resp.status_code == 200
    assert resp.json()["preflight_alerts_24h"] == 0


# ============================================================
# show_preflight_alerts.py
# ============================================================

def test_show_preflight_alerts_script_default_7days(db_path):
    """默认 7 天 → 5 天前的 alert 出现,8 天前的不出现。"""
    now = datetime.now(timezone.utc)
    _seed_alert(db_path, (now - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    _seed_alert(db_path, (now - timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%SZ"))

    proc = subprocess.run(
        [sys.executable, "scripts/show_preflight_alerts.py",
         "--db", str(db_path)],
        capture_output=True, text=True,
        cwd=str(Path(__file__).resolve().parent.parent),
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    # 第一行 "[1] alerts since ..."(5 天前的入,8 天前的出)
    assert proc.stdout.startswith("[1] alerts since"), proc.stdout


def test_show_preflight_alerts_script_with_days_arg(db_path):
    now = datetime.now(timezone.utc)
    _seed_alert(db_path, (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    _seed_alert(db_path, (now - timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%SZ"))

    proc = subprocess.run(
        [sys.executable, "scripts/show_preflight_alerts.py",
         "--days", "1", "--db", str(db_path)],
        capture_output=True, text=True,
        cwd=str(Path(__file__).resolve().parent.parent),
        timeout=30,
    )
    assert proc.returncode == 0
    # 1 天内只 1 条
    assert proc.stdout.startswith("[1] alerts since")


def test_show_preflight_alerts_script_no_alerts(db_path):
    proc = subprocess.run(
        [sys.executable, "scripts/show_preflight_alerts.py",
         "--db", str(db_path)],
        capture_output=True, text=True,
        cwd=str(Path(__file__).resolve().parent.parent),
        timeout=30,
    )
    assert proc.returncode == 0
    assert proc.stdout.startswith("[0] alerts since")
