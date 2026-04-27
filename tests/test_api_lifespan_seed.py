"""tests/test_api_lifespan_seed.py — Sprint 2.6-D.1。

证明 FastAPI startup 真的会调 seed_events,且失败时不让 app 起不来。
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.data.storage.connection import get_connection, init_db


@pytest.fixture
def db_path():
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    init_db(db_path=tmp, verbose=False)
    return tmp


def test_fastapi_startup_calls_seed_events(db_path):
    """app 启动时 seed_events 被调一次。"""
    seed_calls: list = []

    def fake_seed(conn):
        seed_calls.append(conn)
        return {"valid": 10, "skipped": 0, "total_rows_affected": 10}

    def _factory():
        return get_connection(db_path)

    with patch(
        "src.data.collectors.events_seeder.seed_events",
        new=fake_seed,
    ), patch.dict("os.environ", {"SCHEDULER_ENABLED": "false"}):
        app = create_app(conn_factory=_factory)
        with TestClient(app):
            pass  # 进入 + 退出 context 触发 startup

    assert len(seed_calls) >= 1, (
        "seed_events should be invoked on FastAPI startup"
    )


def test_fastapi_startup_swallows_seed_failure(db_path):
    """seed_events 抛异常 → app 仍能 startup,不 crash。"""
    def boom(conn):
        raise RuntimeError("seed file missing")

    def _factory():
        return get_connection(db_path)

    with patch(
        "src.data.collectors.events_seeder.seed_events",
        new=boom,
    ), patch.dict("os.environ", {"SCHEDULER_ENABLED": "false"}):
        app = create_app(conn_factory=_factory)
        # 进入 context 不应抛
        with TestClient(app) as client:
            r = client.get("/api/health")
            # health endpoint 应响应(不强求 200,只看 app 还活着)
            assert r.status_code in (200, 404)
