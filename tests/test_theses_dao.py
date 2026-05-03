"""Sprint 1.10-A 单测:ThesesDAO(v1.4 §5.3)。"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.data.storage.dao import ThesesDAO


_MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "migrations" / "009_v14_virtual_account_thesis.sql"
)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE strategy_runs (run_id TEXT PRIMARY KEY)")
    c.executescript(_MIGRATION.read_text(encoding="utf-8"))
    yield c
    c.close()


def _make_thesis(conn, **overrides):
    defaults = dict(
        thesis_id="th1",
        created_at_run_id="run_001",
        created_at_utc="2026-05-03T08:00:00Z",
        direction="long",
        core_logic="趋势上行,EMA 多周期共振 + 拥挤度健康",
        confidence_score=72,
        break_conditions=[
            "1D 收盘跌破 70000",
            "DXY 突破 110 持续 3 天",
            "L5 extreme_event_detected=true",
        ],
    )
    defaults.update(overrides)
    ThesesDAO.create(conn, **defaults)


# ============================================================
# happy path
# ============================================================

def test_create_and_get_active(conn):
    _make_thesis(conn)
    conn.commit()
    active = ThesesDAO.get_active(conn)
    assert active is not None
    assert active["thesis_id"] == "th1"
    assert active["direction"] == "long"
    assert active["confidence_score"] == 72
    # break_conditions 已 json.loads 还原 list
    assert isinstance(active["break_conditions"], list)
    assert len(active["break_conditions"]) == 3
    assert active["break_conditions"][0] == "1D 收盘跌破 70000"
    assert active["lifecycle_stage"] == "planned"
    assert active["status"] == "active"


def test_break_conditions_json_roundtrip(conn):
    """v1.4 §5.3.2 + 用户补充 B:DAO json.dumps 写,json.loads 读。"""
    custom = ["条件 A 含中文", "条件 B with special chars: '单引号' & \"双引号\""]
    _make_thesis(conn, thesis_id="th_json", break_conditions=custom)
    conn.commit()
    active = ThesesDAO.get_active(conn)
    assert active["break_conditions"] == custom
    # 同时验证 raw TEXT 是 JSON 字符串
    raw = conn.execute("SELECT break_conditions FROM theses WHERE thesis_id='th_json'").fetchone()[0]
    assert isinstance(raw, str)
    assert json.loads(raw) == custom


def test_update_assessment(conn):
    _make_thesis(conn)
    n = ThesesDAO.update_assessment(
        conn,
        thesis_id="th1",
        last_assessment="mostly",
        last_assessment_note="上行势头略弱,但核心逻辑不变",
        last_assessment_at_run="run_002",
    )
    conn.commit()
    assert n == 1
    active = ThesesDAO.get_active(conn)
    assert active["last_assessment"] == "mostly"
    assert active["last_assessment_at_run"] == "run_002"


def test_close_with_profit(conn):
    _make_thesis(conn)
    n = ThesesDAO.close(
        conn,
        thesis_id="th1",
        status="closed_profit",
        closed_at_utc="2026-05-15T16:00:00Z",
        close_channel="A",
        final_realized_pnl=2500.0,
        final_realized_pnl_pct=2.5,
        final_outcome="profit",
    )
    conn.commit()
    assert n == 1
    # 关闭后 get_active 返 None(不再 active)
    assert ThesesDAO.get_active(conn) is None
    # 但能在 history 看到
    hist = ThesesDAO.get_history(conn)
    assert len(hist) == 1
    assert hist[0]["status"] == "closed_profit"
    assert hist[0]["close_channel"] == "A"
    assert hist[0]["final_realized_pnl_pct"] == 2.5
    assert hist[0]["lifecycle_stage"] == "closed"


def test_close_with_invalidation(conn):
    _make_thesis(conn)
    n = ThesesDAO.close(
        conn,
        thesis_id="th1",
        status="invalidated",
        closed_at_utc="2026-05-10T08:00:00Z",
        invalidated_reason="1D 跌破 70000 已触发",
        close_channel="B",
        final_realized_pnl=-1500.0,
        final_realized_pnl_pct=-1.5,
        final_outcome="loss",
    )
    conn.commit()
    assert n == 1
    hist = ThesesDAO.get_history(conn)
    assert hist[0]["status"] == "invalidated"
    assert hist[0]["invalidated_reason"] == "1D 跌破 70000 已触发"
    assert hist[0]["close_channel"] == "B"


def test_get_history_desc_order(conn):
    for i in range(3):
        _make_thesis(
            conn, thesis_id=f"th_{i}",
            created_at_utc=f"2026-05-0{i+1}T08:00:00Z",
        )
    conn.commit()
    hist = ThesesDAO.get_history(conn, limit=10)
    assert len(hist) == 3
    assert hist[0]["thesis_id"] == "th_2"  # 最新在前
    assert hist[2]["thesis_id"] == "th_0"


# ============================================================
# edge cases
# ============================================================

def test_get_active_empty_returns_none(conn):
    assert ThesesDAO.get_active(conn) is None


def test_get_history_empty_returns_empty(conn):
    assert ThesesDAO.get_history(conn) == []


def test_duplicate_thesis_id_raises(conn):
    _make_thesis(conn)
    with pytest.raises(sqlite3.IntegrityError):
        _make_thesis(conn)  # PK 重复


def test_update_nonexistent_returns_zero(conn):
    n = ThesesDAO.update_assessment(
        conn, thesis_id="missing",
        last_assessment="mostly", last_assessment_note="x",
        last_assessment_at_run="run_x",
    )
    assert n == 0


def test_close_nonexistent_returns_zero(conn):
    n = ThesesDAO.close(
        conn, thesis_id="missing",
        status="closed_profit", closed_at_utc="2026-05-15T16:00:00Z",
    )
    assert n == 0


def test_only_one_active_at_a_time(conn):
    """v1.4 §5.3.1 主线锁:虽 DAO 不强制(由 Validator 6 在业务层强制),
    但 get_active 即使有多 active 也只返最新 1 条(LIMIT 1)。"""
    _make_thesis(conn, thesis_id="th_old", created_at_utc="2026-05-01T08:00:00Z")
    _make_thesis(conn, thesis_id="th_new", created_at_utc="2026-05-03T08:00:00Z")
    conn.commit()
    active = ThesesDAO.get_active(conn)
    assert active["thesis_id"] == "th_new"


def test_get_active_skips_closed(conn):
    _make_thesis(conn, thesis_id="th_active")
    _make_thesis(conn, thesis_id="th_closed", created_at_utc="2026-05-01T08:00:00Z")
    ThesesDAO.close(
        conn, thesis_id="th_closed",
        status="closed_loss", closed_at_utc="2026-05-02T16:00:00Z",
        final_outcome="loss",
    )
    conn.commit()
    active = ThesesDAO.get_active(conn)
    assert active["thesis_id"] == "th_active"
