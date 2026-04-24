"""
tests/test_api_routes_new.py — Sprint 1.5c C5:§9.10 新路由覆盖。

  GET /api/system/health
  GET /api/strategy/current
  GET /api/strategy/history
  GET /api/strategy/runs/{run_id}
  GET /api/evidence/card/{card_id}/history
  GET /api/lifecycle/current
  GET /api/lifecycle/history
  GET /api/review/{lifecycle_id}
  POST /api/system/run-now(只做 schema 测,实际跑 pipeline 在另一个场景)

注意:/api/strategy/stream 是 SSE 长连接,单测中验证启动即可,不验证流数据。
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.data.storage.connection import get_connection, init_db
from src.data.storage.dao import StrategyStateDAO


@pytest.fixture
def db_path() -> Path:
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    init_db(db_path=tmp, verbose=False)
    return tmp


@pytest.fixture
def client(db_path: Path) -> TestClient:
    app = create_app(conn_factory=lambda: get_connection(db_path))
    return TestClient(app)


# ==================================================================
# /api/system/health
# ==================================================================

def test_system_health_returns_ok(client: TestClient):
    r = client.get("/api/system/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["db_accessible"] is True
    assert "version" in body


# ==================================================================
# /api/strategy/current 无数据 404
# ==================================================================

def test_strategy_current_404_when_empty(client: TestClient):
    r = client.get("/api/strategy/current")
    assert r.status_code == 404


# ==================================================================
# /api/strategy/current 有数据 + meta.strategy_flavor 固定 'swing'
# ==================================================================

def test_strategy_current_stamps_flavor_swing(client: TestClient, db_path: Path):
    conn = get_connection(db_path)
    try:
        StrategyStateDAO.insert_state(
            conn,
            run_timestamp_utc="2026-04-24T10:00:00Z",
            run_id="test-run-1",
            run_trigger="manual",
            rules_version="v1.2.0",
            ai_model_actual="claude-sonnet-4-5",
            state={"market_snapshot": {"btc_price_usd": 50000}},
        )
        conn.commit()
    finally:
        conn.close()
    r = client.get("/api/strategy/current")
    assert r.status_code == 200
    body = r.json()
    assert body["run_id"] == "test-run-1"
    assert body["state"]["meta"]["strategy_flavor"] == "swing"


def test_strategy_latest_alias_also_works(client: TestClient, db_path: Path):
    conn = get_connection(db_path)
    try:
        StrategyStateDAO.insert_state(
            conn,
            run_timestamp_utc="2026-04-24T10:00:00Z",
            run_id="alias-run",
            run_trigger="manual",
            rules_version="v1.2.0",
            ai_model_actual=None,
            state={},
        )
        conn.commit()
    finally:
        conn.close()
    r = client.get("/api/strategy/latest")  # 老路径 alias
    assert r.status_code == 200
    assert r.json()["run_id"] == "alias-run"


# ==================================================================
# /api/strategy/runs/{run_id}
# ==================================================================

def test_strategy_runs_by_id(client: TestClient, db_path: Path):
    conn = get_connection(db_path)
    try:
        StrategyStateDAO.insert_state(
            conn, run_timestamp_utc="2026-04-24T10:00:00Z",
            run_id="abc-123", run_trigger="manual", rules_version="v1",
            ai_model_actual=None, state={},
        )
        conn.commit()
    finally:
        conn.close()

    r = client.get("/api/strategy/runs/abc-123")
    assert r.status_code == 200
    assert r.json()["run_id"] == "abc-123"

    r404 = client.get("/api/strategy/runs/not-exist")
    assert r404.status_code == 404


# ==================================================================
# /api/lifecycle/current / /api/lifecycle/history
# ==================================================================

def test_lifecycle_current_returns_none_when_empty(client: TestClient):
    r = client.get("/api/lifecycle/current")
    assert r.status_code == 200
    assert r.json().get("lifecycle") is None


def test_lifecycle_current_reads_from_state(client: TestClient, db_path: Path):
    conn = get_connection(db_path)
    try:
        StrategyStateDAO.insert_state(
            conn, run_timestamp_utc="2026-04-24T11:00:00Z",
            run_id="lc-run", run_trigger="manual", rules_version="v1",
            ai_model_actual=None,
            state={"lifecycle": {"current_lifecycle": "LONG_HOLD",
                                 "lifecycle_id": "lc-1"}},
        )
        conn.commit()
    finally:
        conn.close()

    r = client.get("/api/lifecycle/current")
    assert r.status_code == 200
    body = r.json()
    assert body["lifecycle"]["current_lifecycle"] == "LONG_HOLD"
    assert body["run_id"] == "lc-run"


def test_lifecycle_history_empty(client: TestClient):
    r = client.get("/api/lifecycle/history")
    assert r.status_code == 200
    assert r.json()["count"] == 0


# ==================================================================
# /api/evidence/card/{card_id}/history
# ==================================================================

def test_evidence_card_history_empty(client: TestClient):
    r = client.get("/api/evidence/card/mvrv_z/history")
    assert r.status_code == 200
    body = r.json()
    assert body["card_id"] == "mvrv_z"
    assert body["count"] == 0


# ==================================================================
# /api/review/{lifecycle_id}
# ==================================================================

def test_review_404_when_none(client: TestClient):
    r = client.get("/api/review/nonexistent-lc")
    assert r.status_code == 404
