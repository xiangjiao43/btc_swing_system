"""tests/test_event_onchain_chain.py — Sprint F.1(2026-05-09)反退化。

Sprint F.1 用户决策删除 collect_onchain 末尾 _enqueue_pipeline_run("event_onchain")
逻辑,严守"一天 1 次 master"原则。本文件原 Sprint 2.7-D 的"成功 → enqueue"
端到端测试已**反向**:断言成功也**不**触发 enqueue,避免后续 sprint 不小心
把链路加回来。
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


def test_collect_onchain_success_does_not_enqueue_anymore(db_path):
    """Sprint F.1 关键反退化:即使 Glassnode 返回数据 + 入库 > 0,也不 enqueue
    pipeline_run。事件触发的 master 只来自 event_listener(event_price /
    event_macro),不再来自 collect_onchain。"""
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
    assert result["by_collector"]["glassnode"] > 0  # fetch 真成功
    assert enqueue_calls == [], (
        f"Sprint F.1:成功也不 enqueue,但抓到 {enqueue_calls}"
    )
    assert result["events_triggered"] == []
    # 诊断字段保留:fetch 真成功在 events_triggered 之外可见
    assert result.get("glassnode_fetch_success") is True


def test_collect_onchain_empty_does_not_enqueue(db_path):
    """0 rows 也不 enqueue(行为与 Sprint F.1 之前一致)。"""
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
    assert result.get("glassnode_fetch_success") is False
