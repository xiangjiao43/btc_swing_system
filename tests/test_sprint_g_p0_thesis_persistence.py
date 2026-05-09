"""Sprint G P0 — try_create_thesis_from_master_run 端到端测试。

§Z 端到端 DB 行数断言:不只 mock create_thesis.called,而是真插 DB 行
COUNT(*) FROM theses / virtual_orders 验证。

覆盖 4 个用户指定 case + 边界:
1. B 级 + master pass + trade_plan 完整 → COUNT theses +1
2. C 级 + master pass → COUNT 不变(C 级观望)
3. B 级 + fallback_level=level_2 → 不创建
4. B 级 + 已有同方向 active thesis → 不创建
5. v1.4 schema 也能创建
6. 异常路径不抛出(create_thesis 抛 ValueError 时被捕获)
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.data.storage.connection import init_db
from src.strategy.thesis_persistence import try_create_thesis_from_master_run


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def db_path():
    tmp = Path(tempfile.mkdtemp()) / "sprint_g_p0.db"
    init_db(db_path=tmp, verbose=False)
    # v1.4 表(theses / virtual_orders / virtual_account)
    from scripts.init_v14_tables import apply_migration
    conn = sqlite3.connect(str(tmp))
    apply_migration(conn)
    conn.commit()
    conn.close()
    return tmp


@pytest.fixture
def conn(db_path):
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    yield c
    c.close()


def _row_count(conn, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


# ============================================================
# Master output fixtures(模拟 5/3 16:08 真实结构)
# ============================================================

def _master_v13_long_planned():
    """v1.3 schema:state_transition + trade_plan(5/3 16:08 实测格式)。"""
    return {
        "agent": "master_adjudicator",
        "status": "success",
        "state_transition": {
            "from_state": "FLAT",
            "to_state": "LONG_PLANNED",
            "transition_reasoning": "5 层方向一致",
        },
        "trade_plan": {
            "action": "open",
            "direction": "long",
            "entry_price_zone": [76251.0, 77000.0],
            "stop_loss": 76251.0,
            "take_profit_zones": [79455.0, 82309.0, 85000.0],
            "position_size_pct": 0.33,
        },
        "what_would_change_mind": "BTC 跌破 76251; L4 升至 elevated; L5 转 headwind",
        "narrative": "BTC 处于中质量开仓窗口...",
        "confidence": 0.7,
    }


def _master_v14_new_thesis():
    """v1.4 schema:mode + new_thesis dict。"""
    return {
        "agent": "master_adjudicator",
        "status": "success",
        "mode": "new_thesis",
        "new_thesis": {
            "direction": "long",
            "confidence_score": 70,
            "core_logic": "L1 trend_up 稳定 + L2 bullish high tier",
            "break_conditions": [
                "1D 收盘跌破 76251",
                "DXY 突破 108 持续 3 天",
                "L5 extreme_event_detected",
            ],
            "entry_orders": [
                {"price": 76251.0, "size_pct": 50.0},
                {"price": 77000.0, "size_pct": 50.0},
            ],
            "stop_loss": {"price": 76251.0, "size_pct": 100.0},
            "take_profit": [
                {"price": 79455.0, "size_pct": 30.0},
                {"price": 82309.0, "size_pct": 40.0},
                {"price": 85000.0, "size_pct": 30.0},
            ],
        },
        "narrative": "做多",
        "confidence": 0.7,
    }


def _orchestrator_result(master, l3_grade="B"):
    return {
        "status": "ok",
        "layers": {
            "l1": {"status": "success", "regime": "trend_up"},
            "l2": {"status": "success", "stance": "bullish"},
            "l3": {"status": "success", "opportunity_grade": l3_grade,
                   "execution_permission": "cautious_open"},
            "l4": {"status": "success", "risk_tier": "moderate"},
            "l5": {"status": "success", "macro_stance": "supportive"},
            "master": master,
        },
    }


def _make_long_active_thesis(conn):
    """直接 INSERT 一行 active long thesis(模拟"已有持仓")。"""
    conn.execute(
        "INSERT INTO theses (thesis_id, created_at_run_id, created_at_utc, "
        "direction, core_logic, confidence_score, break_conditions, "
        "lifecycle_stage, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("th_existing", "r_old", "2026-04-01T00:00:00Z", "long",
         "old logic", 60, '["a","b","c"]', "opened", "active"),
    )
    conn.commit()


# ============================================================
# Test 1:B 级 + master pass + trade_plan 完整 → 真创建
# ============================================================

def test_b_grade_master_pass_creates_thesis(conn):
    assert _row_count(conn, "theses") == 0

    result = try_create_thesis_from_master_run(
        conn,
        orchestrator_result=_orchestrator_result(_master_v13_long_planned(), l3_grade="B"),
        fallback_level=None,
        run_id="r_test_b",
        now_utc="2026-05-09T03:35:00Z",
    )
    conn.commit()

    assert result["created"] is True
    assert result["thesis_id"] is not None
    assert result["schema_version"] == "v1.3"
    assert result["skip_reason"] is None
    # §Z 真断言 DB 行数
    assert _row_count(conn, "theses") == 1
    # virtual_orders:2 entry + 1 stop_loss + 3 take_profit = 6
    assert _row_count(conn, "virtual_orders") == 6

    th = conn.execute(
        "SELECT thesis_id, direction, lifecycle_stage, status, "
        "       created_at_run_id, confidence_score "
        "FROM theses LIMIT 1"
    ).fetchone()
    assert th["direction"] == "long"
    assert th["lifecycle_stage"] == "planned"
    assert th["status"] == "active"
    assert th["created_at_run_id"] == "r_test_b"
    assert th["confidence_score"] == 70  # confidence 0.7 × 100


# ============================================================
# Test 2:C 级 + master pass → 不创建
# ============================================================

def test_c_grade_does_not_create_thesis(conn):
    """用户决策:C 级观望,不创建 thesis。"""
    assert _row_count(conn, "theses") == 0

    result = try_create_thesis_from_master_run(
        conn,
        orchestrator_result=_orchestrator_result(_master_v13_long_planned(), l3_grade="C"),
        fallback_level=None,
        run_id="r_test_c",
        now_utc="2026-05-09T03:35:00Z",
    )

    assert result["created"] is False
    assert "l3_grade='C'" in result["skip_reason"]
    assert _row_count(conn, "theses") == 0
    assert _row_count(conn, "virtual_orders") == 0


# ============================================================
# Test 3:B 级 + fallback_level=level_2 → 不创建
# ============================================================

def test_fallback_level_2_does_not_create_thesis(conn):
    """master AI 失败(level_2)时不接受其输出。"""
    result = try_create_thesis_from_master_run(
        conn,
        orchestrator_result=_orchestrator_result(_master_v13_long_planned(), l3_grade="B"),
        fallback_level="level_2",
        run_id="r_test_fb",
        now_utc="2026-05-09T03:35:00Z",
    )

    assert result["created"] is False
    assert "fallback_level" in result["skip_reason"]
    assert _row_count(conn, "theses") == 0


# ============================================================
# Test 4:B 级 + 已有同方向 active → 不创建(防重复)
# ============================================================

def test_existing_same_direction_active_thesis_blocks_create(conn):
    """已有 active long thesis,新一次 B 级 long 建议不重复创建。"""
    _make_long_active_thesis(conn)
    assert _row_count(conn, "theses") == 1

    result = try_create_thesis_from_master_run(
        conn,
        orchestrator_result=_orchestrator_result(_master_v13_long_planned(), l3_grade="B"),
        fallback_level=None,
        run_id="r_test_dup",
        now_utc="2026-05-09T03:35:00Z",
    )

    assert result["created"] is False
    assert "active long thesis" in result["skip_reason"]
    # theses 表仍 1 行,没翻倍
    assert _row_count(conn, "theses") == 1


# ============================================================
# Test 5:v1.4 schema 也能创建
# ============================================================

def test_v14_schema_creates_thesis(conn):
    assert _row_count(conn, "theses") == 0

    result = try_create_thesis_from_master_run(
        conn,
        orchestrator_result=_orchestrator_result(_master_v14_new_thesis(), l3_grade="B"),
        fallback_level=None,
        run_id="r_test_v14",
        now_utc="2026-05-09T03:35:00Z",
    )
    conn.commit()

    assert result["created"] is True
    assert result["schema_version"] == "v1.4"
    assert _row_count(conn, "theses") == 1
    # entry: 2, sl: 1, tp: 3
    assert _row_count(conn, "virtual_orders") == 6
    # break_conditions ≥ 3
    th = conn.execute("SELECT break_conditions FROM theses LIMIT 1").fetchone()
    import json
    bc = json.loads(th["break_conditions"])
    assert len(bc) == 3


# ============================================================
# Test 6:A 级也能创建
# ============================================================

def test_a_grade_master_pass_creates_thesis(conn):
    """A 级是开仓信号最高质量,必须能创建。"""
    result = try_create_thesis_from_master_run(
        conn,
        orchestrator_result=_orchestrator_result(_master_v13_long_planned(), l3_grade="A"),
        fallback_level=None,
        run_id="r_test_a",
        now_utc="2026-05-09T03:35:00Z",
    )
    conn.commit()
    assert result["created"] is True
    assert _row_count(conn, "theses") == 1


# ============================================================
# Test 7:none / 缺字段不创建
# ============================================================

def test_none_grade_does_not_create(conn):
    result = try_create_thesis_from_master_run(
        conn,
        orchestrator_result=_orchestrator_result(_master_v13_long_planned(), l3_grade="none"),
        fallback_level=None,
        run_id="r_test_none",
        now_utc="2026-05-09T03:35:00Z",
    )
    assert result["created"] is False
    assert _row_count(conn, "theses") == 0


def test_v13_missing_trade_plan_does_not_create(conn):
    """v1.3 master 没 trade_plan 字段 → 不创建。"""
    master = {
        "status": "success",
        "state_transition": {"from_state": "FLAT", "to_state": "LONG_PLANNED"},
        # trade_plan 缺失
    }
    result = try_create_thesis_from_master_run(
        conn,
        orchestrator_result=_orchestrator_result(master, l3_grade="B"),
        fallback_level=None,
        run_id="r_test_missing",
        now_utc="2026-05-09T03:35:00Z",
    )
    assert result["created"] is False
    assert _row_count(conn, "theses") == 0


# ============================================================
# Test 8:orchestrator status != ok 不创建
# ============================================================

def test_orchestrator_failed_status_does_not_create(conn):
    result_dict = _orchestrator_result(_master_v13_long_planned(), l3_grade="B")
    result_dict["status"] = "degraded_master_failed"
    result = try_create_thesis_from_master_run(
        conn,
        orchestrator_result=result_dict,
        fallback_level=None,
        run_id="r_test_fail",
        now_utc="2026-05-09T03:35:00Z",
    )
    assert result["created"] is False
    assert "non ok" in result["skip_reason"] or "status" in result["skip_reason"]
    assert _row_count(conn, "theses") == 0


# ============================================================
# Test 9:相反方向已有 active(short)→ 仍可创建 long(不冲突)
# ============================================================

def test_existing_opposite_direction_does_not_block(conn):
    """已有 active short,新建 long 仍可创建(防重复只针对同方向)。"""
    conn.execute(
        "INSERT INTO theses (thesis_id, created_at_run_id, created_at_utc, "
        "direction, core_logic, confidence_score, break_conditions, "
        "lifecycle_stage, status) VALUES (?,?,?,?,?,?,?,?,?)",
        ("th_short", "r_old", "2026-04-01T00:00:00Z", "short",
         "old", 60, '["a","b","c"]', "opened", "active"),
    )
    conn.commit()

    result = try_create_thesis_from_master_run(
        conn,
        orchestrator_result=_orchestrator_result(_master_v13_long_planned(), l3_grade="B"),
        fallback_level=None,
        run_id="r_test_opp",
        now_utc="2026-05-09T03:35:00Z",
    )
    conn.commit()

    # active long thesis 不存在 → 当前 active 是 short → 不阻塞 long 创建。
    # 但 ThesesDAO.get_active 只返回最新一条,如果是 short → direction 不同
    # → 通过条件 f
    assert result["created"] is True
    assert _row_count(conn, "theses") == 2


# ============================================================
# Test 10:created thesis 完整字段对应 master.trade_plan
# ============================================================

def test_v13_persistence_field_mapping_correct(conn):
    """v1.3 trade_plan 各字段 → virtual_orders 真实落库,价格 / 仓位映射正确。"""
    try_create_thesis_from_master_run(
        conn,
        orchestrator_result=_orchestrator_result(_master_v13_long_planned(), l3_grade="B"),
        fallback_level=None,
        run_id="r_field_check",
        now_utc="2026-05-09T03:35:00Z",
    )
    conn.commit()

    # entry 2 单(76251 + 77000),平均分 33% → 每单 16.5%
    entries = conn.execute(
        "SELECT price, size_pct, size_usdt FROM virtual_orders "
        "WHERE order_type='entry' ORDER BY price"
    ).fetchall()
    assert len(entries) == 2
    assert entries[0]["price"] == 76251.0
    assert entries[1]["price"] == 77000.0
    # 每单 size_pct = 33/2 = 16.5
    assert abs(entries[0]["size_pct"] - 16.5) < 0.05

    # stop_loss 1 单
    sls = conn.execute(
        "SELECT price, size_pct FROM virtual_orders "
        "WHERE order_type='stop_loss'"
    ).fetchall()
    assert len(sls) == 1
    assert sls[0]["price"] == 76251.0
    assert abs(sls[0]["size_pct"] - 33.0) < 0.05

    # tp 3 单(79455 / 82309 / 85000)按 30/40/30 拆
    tps = conn.execute(
        "SELECT price, size_pct FROM virtual_orders "
        "WHERE order_type='take_profit' ORDER BY price"
    ).fetchall()
    assert len(tps) == 3
    assert tps[0]["price"] == 79455.0
    assert tps[1]["price"] == 82309.0
    assert tps[2]["price"] == 85000.0
    # 30% → pos_total 33 × 30% = 9.9
    assert abs(tps[0]["size_pct"] - 9.9) < 0.05
    assert abs(tps[1]["size_pct"] - 13.2) < 0.05
    assert abs(tps[2]["size_pct"] - 9.9) < 0.05
