"""
tests/test_api_routes.py — Sprint 1.15a FastAPI routes 单测

用 TestClient + 临时 SQLite DB。Pipeline trigger 路径需要 mock StrategyStateBuilder。
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.data.storage.connection import get_connection, init_db
from src.data.storage.dao import StrategyStateDAO, FallbackLogDAO


# ==================================================================
# Fixtures
# ==================================================================

@pytest.fixture
def db_path():
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    init_db(db_path=tmp, verbose=False)
    return tmp


@pytest.fixture
def client(db_path):
    def _factory():
        return get_connection(db_path)
    app = create_app(
        conn_factory=_factory,
        pipeline_trigger_cooldown_sec=60.0,
    )
    return TestClient(app)


def _insert_state(
    db_path: Path,
    *,
    run_id: str = "run-abc",
    run_ts: str = "2026-04-24T10:00:00Z",
    ai_model: str | None = "mock-model",
    state: dict[str, Any] | None = None,
) -> None:
    conn = get_connection(db_path)
    try:
        StrategyStateDAO.insert_state(
            conn,
            run_timestamp_utc=run_ts,
            run_id=run_id,
            run_trigger="manual",
            rules_version="v1.2.0",
            ai_model_actual=ai_model,
            state=state or {
                "run_id": run_id,
                "evidence_reports": {},
                "state_machine": {"current_state": "neutral_observation"},
            },
        )
        conn.commit()
    finally:
        conn.close()


# ==================================================================
# 1. /api/health
# ==================================================================

def test_health_returns_200(client: TestClient):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["db_accessible"] is True
    assert body["uptime_seconds"] >= 0


# ==================================================================
# 2. /api/strategy/latest — 空库 404
# ==================================================================

def test_latest_empty_returns_404(client: TestClient):
    r = client.get("/api/strategy/latest")
    assert r.status_code == 404


# ==================================================================
# 3. /api/strategy/latest — 有数据
# ==================================================================

def test_latest_with_data_returns_200(client: TestClient, db_path: Path):
    _insert_state(db_path)
    r = client.get("/api/strategy/latest")
    assert r.status_code == 200
    body = r.json()
    assert body["run_id"] == "run-abc"
    assert body["run_timestamp_utc"] == "2026-04-24T10:00:00Z"


# ==================================================================
# 4. /api/strategy/history 分页
# ==================================================================

def test_history_pagination(client: TestClient, db_path: Path):
    for i in range(5):
        _insert_state(
            db_path,
            run_id=f"run-{i}",
            run_ts=f"2026-04-24T10:0{i}:00Z",
        )
    r = client.get("/api/strategy/history?limit=2&offset=0")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert len(body["items"]) == 2
    # 倒序:最新的在前
    assert body["items"][0]["run_id"] == "run-4"

    r2 = client.get("/api/strategy/history?limit=2&offset=2")
    body2 = r2.json()
    assert len(body2["items"]) == 2
    assert body2["items"][0]["run_id"] == "run-2"


# ==================================================================
# 5. /api/strategy/history/{run_id} 存在 → 200
# ==================================================================

def test_history_by_id_ok(client: TestClient, db_path: Path):
    _insert_state(db_path, run_id="unique-run-xyz")
    r = client.get("/api/strategy/history/unique-run-xyz")
    assert r.status_code == 200
    assert r.json()["run_id"] == "unique-run-xyz"


# ==================================================================
# 6. /api/strategy/history/{run_id} 不存在 → 404
# ==================================================================

def test_history_by_id_not_found(client: TestClient):
    r = client.get("/api/strategy/history/nonexistent-id")
    assert r.status_code == 404


# ==================================================================
# 7. POST /api/pipeline/trigger — 成功返回 state
# ==================================================================

def test_pipeline_trigger_success(client: TestClient, db_path: Path):
    fake_result = MagicMock(
        run_id="triggered-1",
        run_timestamp_utc="2026-04-24T12:00:00Z",
        persisted=True,
        ai_status="success",
        duration_ms=123,
        degraded_stages=[],
        failures=[],
    )
    with patch("src.api.routes.pipeline.StrategyStateBuilder") as MB:
        MB.return_value.run.return_value = fake_result
        r = client.post("/api/pipeline/trigger")
    assert r.status_code == 200
    body = r.json()
    assert body["run_id"] == "triggered-1"
    assert body["persisted"] is True
    assert body["status"] == "success"


# ==================================================================
# 8. POST /api/pipeline/trigger — 60 秒内再次 → 429
# ==================================================================

def test_pipeline_trigger_rate_limited(client: TestClient, db_path: Path):
    fake_result = MagicMock(
        run_id="triggered-2",
        run_timestamp_utc="2026-04-24T12:05:00Z",
        persisted=True,
        ai_status="success",
        duration_ms=100,
        degraded_stages=[],
        failures=[],
    )
    with patch("src.api.routes.pipeline.StrategyStateBuilder") as MB:
        MB.return_value.run.return_value = fake_result
        r1 = client.post("/api/pipeline/trigger")
        assert r1.status_code == 200
        r2 = client.post("/api/pipeline/trigger")
    assert r2.status_code == 429
    assert "rate-limited" in r2.json()["detail"]


# ==================================================================
# 9. /api/fallback_log
# ==================================================================

def test_fallback_log_list(client: TestClient, db_path: Path):
    conn = get_connection(db_path)
    try:
        FallbackLogDAO.log_stage_error(
            conn,
            run_timestamp_utc="2026-04-24T09:00:00Z",
            stage="ai_summary",
            error="boom",
            fallback_applied="context=None",
        )
        conn.commit()
    finally:
        conn.close()

    r = client.get("/api/fallback_log?limit=10")
    assert r.status_code == 200
    body = r.json()
    assert body["limit"] == 10
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["triggered_by"] == "pipeline.ai_summary"
    assert item["fallback_level"] == "level_1"
    assert item["details"]["stage"] == "ai_summary"


# ==================================================================
# 10. /api/data/summary
# ==================================================================

def test_data_summary(client: TestClient, db_path: Path):
    _insert_state(db_path)
    r = client.get("/api/data/summary")
    assert r.status_code == 200
    body = r.json()
    sources = {s["name"]: s for s in body["sources"]}
    assert "strategy_runs" in sources
    assert sources["strategy_runs"]["row_count"] == 1
    assert sources["strategy_runs"]["latest_timestamp_utc"] \
        == "2026-04-24T10:00:00Z"
