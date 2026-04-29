"""tests/test_lifecycle_dao_and_review.py — Sprint 1.5b-C 集成 + API + 复盘触发。

§Z 真实 DB 断言:
- LifecyclesDAO upsert / get / list 真行数变化
- /api/lifecycle/history 真启 FastAPI + 真 DAO 写入 → JSON 返回
- /api/lifecycle/current legacy 占位 → null
- generate_for_lifecycle 写 review_reports 表
- 自动触发:LifecycleManager 归档 → review_reports 表新增
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.data.storage.connection import init_db
from src.data.storage.dao import LifecyclesDAO, ReviewReportsDAO
from src.review.generator import ReviewReportGenerator
from src.strategy.lifecycle_manager import LifecycleManager


def _row_conn(p: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture
def db_path():
    tmp = Path(tempfile.mkdtemp()) / "lc_dao.db"
    init_db(db_path=tmp, verbose=False)
    return tmp


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ============================================================
# LifecyclesDAO
# ============================================================

def test_lifecycles_dao_upsert_active(db_path):
    conn = _row_conn(db_path)
    try:
        n = LifecyclesDAO.upsert_lifecycle(conn, {
            "lifecycle_id": "lc-1",
            "direction": "long",
            "status": "active",
            "origin_time_utc": _now(),
            "origin_thesis": "test thesis",
            "ai_models_used_in_lifecycle": ["claude-opus-4-7"],
            "rules_versions_used": ["v1.2.0"],
        })
        conn.commit()
        assert n == 1
        out = LifecyclesDAO.get_lifecycle(conn, "lc-1")
        assert out is not None
        assert out["direction"] == "long"
        assert out["status"] == "active"
        assert out["full_data"]["origin_thesis"] == "test thesis"
        assert "claude-opus-4-7" in out["ai_models_used"]
    finally:
        conn.close()


def test_lifecycles_dao_upsert_then_close_keeps_single_row(db_path):
    conn = _row_conn(db_path)
    try:
        LifecyclesDAO.upsert_lifecycle(conn, {
            "lifecycle_id": "lc-2",
            "direction": "long", "status": "active",
            "origin_time_utc": _now(),
        })
        LifecyclesDAO.upsert_lifecycle(conn, {
            "lifecycle_id": "lc-2",
            "direction": "long", "status": "closed",
            "origin_time_utc": _now(),
            "exit_time_utc": _now(),
            "final_outcome_type": "B_good_suboptimal",
            "realized_pnl_pct": 2.5,
        })
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM lifecycles").fetchone()[0]
        assert n == 1
        out = LifecyclesDAO.get_lifecycle(conn, "lc-2")
        assert out["status"] == "closed"
        assert out["exit_time_utc"]
        assert out["full_data"]["final_outcome_type"] == "B_good_suboptimal"
    finally:
        conn.close()


def test_list_lifecycles_by_status(db_path):
    conn = _row_conn(db_path)
    try:
        for i, st in enumerate(("active", "active", "closed")):
            LifecyclesDAO.upsert_lifecycle(conn, {
                "lifecycle_id": f"lc-{i}",
                "direction": "long", "status": st,
                "origin_time_utc": _now(),
            })
        conn.commit()
        actives = LifecyclesDAO.list_lifecycles(conn, status="active")
        assert len(actives) == 2
        closed = LifecyclesDAO.list_lifecycles(conn, status="closed")
        assert len(closed) == 1
        all_lc = LifecyclesDAO.list_lifecycles(conn)
        assert len(all_lc) == 3
    finally:
        conn.close()


# ============================================================
# /api/lifecycle/* 接通
# ============================================================

def test_api_lifecycle_history_returns_real_data(db_path):
    conn = _row_conn(db_path)
    try:
        for i, st in enumerate(("active", "closed")):
            LifecyclesDAO.upsert_lifecycle(conn, {
                "lifecycle_id": f"api-lc-{i}",
                "direction": "long", "status": st,
                "origin_time_utc": _now(),
                "origin_thesis": f"thesis-{i}",
            })
        conn.commit()
    finally:
        conn.close()

    app = create_app(conn_factory=lambda: _row_conn(db_path))
    with TestClient(app) as client:
        resp = client.get("/api/lifecycle/history")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    ids = {item["lifecycle_id"] for item in body["items"]}
    assert ids == {"api-lc-0", "api-lc-1"}

    # ?status=closed 过滤
    with TestClient(app) as client:
        resp_closed = client.get("/api/lifecycle/history?status=closed")
    assert resp_closed.json()["count"] == 1


def test_api_lifecycle_current_filters_legacy_placeholder(db_path):
    """模拟 1.5b-B 部署前的 legacy run:
    full_state_json.lifecycle = {managed_by: 'sprint_1_5b_pending', ...}
    /api/lifecycle/current 应返回 null,而不是把占位透出来。"""
    conn = _row_conn(db_path)
    try:
        legacy_state = {
            "lifecycle": {
                "current_lifecycle": "pending_lifecycle_manager",
                "managed_by": "sprint_1_5b_pending",
            },
            "state_machine": {"current_state": "FLAT"},
        }
        conn.execute(
            "INSERT INTO strategy_runs "
            "(run_id, generated_at_utc, generated_at_bjt, "
            " action_state, full_state_json, run_trigger, rules_version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("legacy-r1", _now(), "2026-04-29 12:00 (BJT)", "FLAT",
             json.dumps(legacy_state), "manual", "v1.2.0"),
        )
        conn.commit()
    finally:
        conn.close()

    app = create_app(conn_factory=lambda: _row_conn(db_path))
    with TestClient(app) as client:
        resp = client.get("/api/lifecycle/current")
    assert resp.status_code == 200
    body = resp.json()
    assert body["lifecycle"] is None
    assert "Legacy placeholder filtered" in (body.get("message") or "")


# ============================================================
# ReviewReportGenerator.generate_for_lifecycle
# ============================================================

def test_review_generate_for_lifecycle_writes_review_reports_row(db_path):
    conn = _row_conn(db_path)
    try:
        # Seed:1 个 closed lifecycle
        closed_lc = {
            "lifecycle_id": "rev-lc-1",
            "direction": "long",
            "status": "closed",
            "origin_time_utc": "2026-04-25T08:00:00Z",
            "origin_time_bjt": "2026-04-25 16:00 (BJT)",
            "exit_time_utc": "2026-04-28T08:00:00Z",
            "exit_time_bjt": "2026-04-28 16:00 (BJT)",
            "average_entry_price": 68000,
            "max_favorable_pct": 3.5,
            "max_adverse_pct": -0.8,
            "realized_pnl_pct": 3.2,
            "final_outcome_type": "B_good_suboptimal",
            "position_adjustments": [
                {"adjustment_type": "open", "size_pct_of_total": 100,
                 "price": 68000, "at_bjt": "2026-04-25 16:00 (BJT)",
                 "reason": "open", "related_run_id": "r1"},
                {"adjustment_type": "exit", "size_pct_of_total": 100,
                 "price": 70180, "at_bjt": "2026-04-28 16:00 (BJT)",
                 "reason": "exit", "related_run_id": "rN"},
            ],
            "ai_models_used_in_lifecycle": ["claude-opus-4-7"],
            "rules_versions_used": ["v1.2.0"],
        }
        LifecyclesDAO.upsert_lifecycle(conn, closed_lc)
        conn.commit()

        gen = ReviewReportGenerator(conn=conn)
        report = gen.generate_for_lifecycle("rev-lc-1", lifecycle_dict=closed_lc)
        # report 字段
        assert report["lifecycle_id"] == "rev-lc-1"
        assert report["outcome_type"] == "B_good_suboptimal"
        assert report["realized_pnl_pct"] == 3.2
        assert len(report["key_moments_replay"]) == 2
        assert "复盘结果不自动反哺" in report["feedback_to_system"]

        # review_reports 表真行数 +1
        cnt = conn.execute(
            "SELECT COUNT(*) FROM review_reports WHERE lifecycle_id=?",
            ("rev-lc-1",),
        ).fetchone()[0]
        assert cnt == 1
        # 真能用 DAO 读回
        rows = ReviewReportsDAO.get_reports_for_lifecycle(conn, "rev-lc-1")
        assert len(rows) == 1
        assert rows[0]["outcome_type"] == "B_good_suboptimal"
    finally:
        conn.close()


def test_maybe_generate_skips_when_prev_not_active(db_path):
    """prev_lifecycle.status != "active" → 返回 None,不生成报告。"""
    conn = _row_conn(db_path)
    try:
        gen = ReviewReportGenerator(conn=conn)
        out = gen.maybe_generate_for_closed_lifecycle(
            prev_lifecycle={"status": "pending_open", "lifecycle_id": "x"},
            current_lifecycle=None,
        )
        assert out is None
        cnt = conn.execute("SELECT COUNT(*) FROM review_reports").fetchone()[0]
        assert cnt == 0
    finally:
        conn.close()


def test_maybe_generate_triggers_when_active_to_closed(db_path):
    """prev.active → curr.closed(同 lifecycle_id)→ 自动生成。"""
    conn = _row_conn(db_path)
    try:
        prev = {
            "status": "active", "lifecycle_id": "auto-lc-1",
            "direction": "long",
            "origin_time_utc": "2026-04-25T08:00:00Z",
            "average_entry_price": 68000,
        }
        curr = {
            "status": "closed", "lifecycle_id": "auto-lc-1",
            "direction": "long",
            "origin_time_utc": "2026-04-25T08:00:00Z",
            "exit_time_utc": "2026-04-28T08:00:00Z",
            "average_entry_price": 68000,
            "realized_pnl_pct": 6.5,
            "final_outcome_type": "A_perfect",
        }
        gen = ReviewReportGenerator(conn=conn)
        out = gen.maybe_generate_for_closed_lifecycle(prev, curr)
        assert out is not None
        assert out["outcome_type"] == "A_perfect"
        cnt = conn.execute(
            "SELECT COUNT(*) FROM review_reports WHERE lifecycle_id=?",
            ("auto-lc-1",),
        ).fetchone()[0]
        assert cnt == 1
    finally:
        conn.close()


# ============================================================
# LifecycleManager 接通 LifecyclesDAO(集成)
# ============================================================

def test_lifecycle_manager_writes_to_lifecycles_table_on_planned(db_path):
    """post_sm 创建 pending_open → LifecyclesDAO 真写入。"""
    conn = _row_conn(db_path)
    try:
        mgr = LifecycleManager(conn=conn)
        out = mgr.compute_post_sm(
            prev_state="FLAT", current_state="LONG_PLANNED",
            lifecycle=None,
            strategy_state={"adjudicator": {"narrative": "test"}},
            context={}, run_id="run-1", now_utc=_now(),
        )
        conn.commit()
        assert out is not None
        # lifecycles 表有 1 行
        n = conn.execute("SELECT COUNT(*) FROM lifecycles").fetchone()[0]
        assert n == 1
        row = LifecyclesDAO.get_lifecycle(conn, out["lifecycle_id"])
        assert row["status"] == "pending_open"
        assert row["direction"] == "long"
    finally:
        conn.close()


def test_lifecycle_manager_archive_writes_closed_status(db_path):
    """LONG_EXIT → FLAT 时,LifecyclesDAO 反映 status='closed' + exit_time_utc。"""
    conn = _row_conn(db_path)
    try:
        mgr = LifecycleManager(conn=conn)
        # 先创建 pending,再激活,再归档(三次 upsert,同 lifecycle_id)
        plan = mgr.compute_post_sm(
            prev_state="FLAT", current_state="LONG_PLANNED",
            lifecycle=None,
            strategy_state={"adjudicator": {"narrative": "test"}},
            context={}, run_id="r1", now_utc=_now(),
        )
        conn.commit()

        # 模拟 active(直接模拟 lifecycle dict 进归档)
        active_lc = dict(plan)
        active_lc["status"] = "active"
        active_lc["origin_time_utc"] = _now()
        active_lc["average_entry_price"] = 68000
        active_lc["current_floating_pnl_pct"] = 5.5

        archived = mgr.compute_post_sm(
            prev_state="LONG_EXIT", current_state="FLAT",
            lifecycle=active_lc,
            strategy_state={}, context={}, run_id="rN",
            now_utc=_now(),
        )
        conn.commit()
        assert archived["status"] == "closed"
        assert archived["final_outcome_type"] == "A_perfect"

        row = LifecyclesDAO.get_lifecycle(conn, plan["lifecycle_id"])
        assert row["status"] == "closed"
        assert row["exit_time_utc"]
    finally:
        conn.close()
