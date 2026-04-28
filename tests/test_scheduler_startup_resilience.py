"""tests/test_scheduler_startup_resilience.py — Sprint 2.8-D。

§Z 端到端 + race 模拟:
- _log_scheduler_jobs:job.next_run_time 抛 AttributeError → 不传播,只 log
- _start_scheduler:scheduler.start() 成功后,即便 next_run_time race 抛错,
  app.state.scheduler 必须**保留**(不被清成 None)
- /api/system/health 含 scheduler_running + scheduler_jobs_count 字段
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.app import _log_scheduler_jobs, create_app


# ============================================================
# _log_scheduler_jobs:race 不传播
# ============================================================

class _FakeJobAttrErr:
    def __init__(self, jid: str) -> None:
        self.id = jid

    @property
    def next_run_time(self):
        raise AttributeError("APScheduler race: not yet scheduled")


class _FakeJobOk:
    def __init__(self, jid: str, nrt) -> None:
        self.id = jid
        self.next_run_time = nrt


class _FakeSched:
    def __init__(self, jobs) -> None:
        self._jobs = jobs
        self.running = True

    def get_jobs(self):
        return self._jobs


def test_log_scheduler_jobs_swallows_attributeerror(caplog):
    """job.next_run_time 抛 AttributeError → log "registered (next_run_time pending)",
    不向上传播。"""
    sched = _FakeSched([_FakeJobAttrErr("j1"), _FakeJobAttrErr("j2")])
    with caplog.at_level(logging.INFO, logger="src.api.app"):
        _log_scheduler_jobs(sched)  # 不该 raise
    msgs = [r.message for r in caplog.records]
    assert any("j1 registered (next_run_time pending)" in m for m in msgs)
    assert any("j2 registered (next_run_time pending)" in m for m in msgs)


def test_log_scheduler_jobs_logs_bjt_when_set(caplog):
    from datetime import datetime, timezone
    nrt = datetime(2026, 4, 28, 12, 5, tzinfo=timezone.utc)  # 20:05 BJT
    sched = _FakeSched([_FakeJobOk("pipeline_run", nrt)])
    with caplog.at_level(logging.INFO, logger="src.api.app"):
        _log_scheduler_jobs(sched)
    msgs = " ".join(r.message for r in caplog.records)
    assert "pipeline_run" in msgs
    assert "20:05 BJT" in msgs


def test_log_scheduler_jobs_logs_no_next_run_time(caplog):
    sched = _FakeSched([_FakeJobOk("job_x", None)])
    with caplog.at_level(logging.INFO, logger="src.api.app"):
        _log_scheduler_jobs(sched)
    msgs = " ".join(r.message for r in caplog.records)
    assert "job_x registered (no next_run_time)" in msgs


# ============================================================
# _start_scheduler:race 不丢 scheduler 引用
# ============================================================

def test_start_scheduler_preserves_ref_when_race_in_log(monkeypatch):
    """scheduler.start() 成功 → next_run_time race 抛错 → app.state.scheduler
    仍是真实 scheduler 实例,不被清成 None。"""
    fake_scheduler = MagicMock()
    fake_scheduler.running = True
    fake_scheduler.start.return_value = None
    fake_scheduler.get_jobs.return_value = [
        _FakeJobAttrErr("pipeline_run"),
        _FakeJobAttrErr("collector_klines_1h"),
    ]

    monkeypatch.setenv("SCHEDULER_ENABLED", "true")

    timer_called = {"flag": False}

    class _ImmediateTimer:
        """模拟 threading.Timer:立即同步调 fn(args=...),不延迟。"""
        def __init__(self, delay, fn, args=()):
            self._fn = fn
            self._args = args

        def start(self):
            timer_called["flag"] = True
            # 同步运行 _log_scheduler_jobs(它内部会触发 AttributeError)
            self._fn(*self._args)

    with patch("src.scheduler.build_scheduler", return_value=fake_scheduler), \
         patch("threading.Timer", _ImmediateTimer):
        app = create_app()
        with TestClient(app) as client:
            # 走完 startup 事件
            assert client.get("/api/system/health").status_code == 200

    # KEY 断言:scheduler 引用没被清成 None,
    # 即便 _log_scheduler_jobs 在 startup 内同步抛了 AttributeError(已被吃掉)
    assert app.state.scheduler is fake_scheduler
    assert timer_called["flag"] is True


def test_start_scheduler_clears_ref_on_real_start_failure(monkeypatch):
    """scheduler.start() 抛错 → app.state.scheduler 应被清成 None。"""
    monkeypatch.setenv("SCHEDULER_ENABLED", "true")

    def _boom(*a, **kw):
        raise RuntimeError("synthetic build_scheduler failure")

    with patch("src.scheduler.build_scheduler", side_effect=_boom):
        app = create_app()
        with TestClient(app) as client:
            assert client.get("/api/system/health").status_code == 200

    assert app.state.scheduler is None


def test_start_scheduler_disabled_via_env(monkeypatch):
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/api/system/health").status_code == 200
    assert app.state.scheduler is None


# ============================================================
# /api/system/health 新字段
# ============================================================

def test_health_reports_scheduler_running_true(monkeypatch):
    fake_scheduler = MagicMock()
    fake_scheduler.running = True
    fake_scheduler.start.return_value = None
    fake_scheduler.get_jobs.return_value = [
        _FakeJobOk(f"j{i}", None) for i in range(8)
    ]
    monkeypatch.setenv("SCHEDULER_ENABLED", "true")

    class _ImmediateTimer:
        def __init__(self, delay, fn, args=()):
            self._fn, self._args = fn, args
        def start(self):
            self._fn(*self._args)

    with patch("src.scheduler.build_scheduler", return_value=fake_scheduler), \
         patch("threading.Timer", _ImmediateTimer):
        app = create_app()
        with TestClient(app) as client:
            resp = client.get("/api/system/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["scheduler_running"] is True
    assert body["scheduler_jobs_count"] == 8


def test_health_reports_scheduler_off_when_disabled(monkeypatch):
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/api/system/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["scheduler_running"] is False
    assert body["scheduler_jobs_count"] == 0


def test_health_reports_scheduler_off_when_start_failed(monkeypatch):
    monkeypatch.setenv("SCHEDULER_ENABLED", "true")
    with patch("src.scheduler.build_scheduler",
               side_effect=RuntimeError("boom")):
        app = create_app()
        with TestClient(app) as client:
            resp = client.get("/api/system/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["scheduler_running"] is False
    assert body["scheduler_jobs_count"] == 0
