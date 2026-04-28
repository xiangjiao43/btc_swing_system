"""tests/test_event_onchain_chain.py — Sprint 2.7-D event_onchain 链路。

§Z 验证:job_collect_onchain 成功(收到非空 rows)→ _enqueue_pipeline_run
被以 run_trigger='event_onchain' 调用。
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
    tmp = Path(tempfile.mkdtemp()) / "ev_onchain.db"
    init_db(db_path=tmp, verbose=False)
    return tmp


def test_collect_onchain_success_enqueues_pipeline_run(db_path):
    """端到端:mock Glassnode 返回数据 → DB upsert > 0 → enqueue called。"""
    gn_inst = MagicMock()
    for fn in jobs_mod._GLASSNODE_FETCHERS:
        getattr(gn_inst, fn).return_value = [
            {"timestamp": "2026-04-28T00:00:00Z",
             "metric_name": fn.replace("fetch_", ""),
             "metric_value": 1.0,
             "source": "glassnode_primary"}
        ]

    enqueue_calls: list = []

    def fake_enqueue(run_trigger, **kw):
        enqueue_calls.append(run_trigger)
        return True

    with patch("src.data.collectors.glassnode.GlassnodeCollector",
               return_value=gn_inst), \
         patch("src.scheduler.jobs._enqueue_pipeline_run", side_effect=fake_enqueue):
        result = jobs_mod.job_collect_onchain(
            conn_factory=lambda: sqlite3.connect(db_path),
        )

    assert result["status"] == "ok"
    assert result["by_collector"]["glassnode"] > 0
    assert enqueue_calls == ["event_onchain"], (
        f"expected one event_onchain enqueue, got {enqueue_calls}"
    )
    assert result["events_triggered"] == ["event_onchain"]


def test_collect_onchain_empty_does_not_enqueue(db_path):
    """0 rows → 不 enqueue(避免空 fetch 还触发 pipeline)。"""
    gn_inst = MagicMock()
    for fn in jobs_mod._GLASSNODE_FETCHERS:
        getattr(gn_inst, fn).return_value = []

    enqueue_calls: list = []

    def fake_enqueue(run_trigger, **kw):
        enqueue_calls.append(run_trigger)
        return True

    with patch("src.data.collectors.glassnode.GlassnodeCollector",
               return_value=gn_inst), \
         patch("src.scheduler.jobs._enqueue_pipeline_run", side_effect=fake_enqueue):
        result = jobs_mod.job_collect_onchain(
            conn_factory=lambda: sqlite3.connect(db_path),
        )

    assert result["by_collector"]["glassnode"] == 0
    assert enqueue_calls == []
    assert result["events_triggered"] == []


def test_enqueue_pipeline_run_no_scheduler_returns_false():
    """无 active_scheduler(单测路径)→ _enqueue_pipeline_run 返回 False,不抛错。"""
    # 确保没有全局 scheduler
    jobs_mod._active_scheduler = None
    ok = jobs_mod._enqueue_pipeline_run("event_onchain")
    assert ok is False


def test_enqueue_pipeline_run_with_scheduler_calls_add_job():
    """有 active_scheduler → 调 add_job。"""
    sched = MagicMock()
    jobs_mod.set_active_scheduler(sched)
    try:
        ok = jobs_mod._enqueue_pipeline_run("event_macro", delay_sec=5)
        assert ok is True
        sched.add_job.assert_called_once()
        kw = sched.add_job.call_args.kwargs
        assert kw["kwargs"]["run_trigger"] == "event_macro"
        assert kw["trigger"] == "date"
    finally:
        jobs_mod._active_scheduler = None
