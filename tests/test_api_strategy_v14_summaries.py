"""tests/test_api_strategy_v14_summaries.py — Sprint 1.10-I commit 3 单测。

覆盖 v1.4 §9.5:GET /api/strategy/current 加 4 字段(向后兼容追加)。
- account_summary
- active_thesis
- position_summary
- pending_orders_summary
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.data.storage.connection import get_connection, init_db


@pytest.fixture
def db_path():
    tmp = Path(tempfile.mkdtemp()) / "test_strategy_v14.db"
    init_db(db_path=tmp, verbose=False)
    import sqlite3
    conn = sqlite3.connect(str(tmp))
    from scripts.init_v14_tables import apply_migration
    apply_migration(conn)
    conn.commit()
    conn.close()
    return tmp


@pytest.fixture
def client(db_path):
    def _factory():
        return get_connection(db_path)
    app = create_app(
        conn_factory=_factory, pipeline_trigger_cooldown_sec=60.0,
    )
    return TestClient(app)


def _seed_strategy_run(db_path, *, run_id="r_test"):
    """写一条 strategy_runs 让 GET /current 不返 404。"""
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO strategy_runs (run_id, generated_at_utc, generated_at_bjt, "
        "reference_timestamp_utc, action_state, run_trigger, "
        "rules_version, full_state_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, "2026-05-04T08:00:00Z", "2026-05-04T16:00:00+08:00",
         "2026-05-04T08:00:00Z", "FLAT", "scheduled", "v1.4",
         json.dumps({"some": "state"})),
    )
    conn.commit()
    conn.close()


def _seed_va_snapshot(db_path, total_equity=102000.0,
                       initial_capital=100000.0, available_cash=50000.0):
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO virtual_account "
        "(snapshot_id, run_id, snapshot_at_utc, btc_price_at_snapshot, "
        " initial_capital, available_cash, total_equity) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("s_curr", "s_curr", "2026-05-04T08:00:00Z", 75000.0,
         initial_capital, available_cash, total_equity),
    )
    conn.commit()
    conn.close()


def _seed_active_thesis(db_path, thesis_id="t_active",
                         direction="long", lifecycle_stage="opened"):
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO theses (thesis_id, created_at_run_id, created_at_utc, "
        "direction, core_logic, confidence_score, break_conditions, "
        "lifecycle_stage, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (thesis_id, "r_test", "2026-05-04T08:00:00Z", direction,
         "test", 70, '["a","b","c"]', lifecycle_stage, "active"),
    )
    conn.commit()
    conn.close()


def _seed_filled_entry(db_path, *, order_id, thesis_id, btc_amount=0.4,
                       filled_price=75000.0):
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO virtual_orders (order_id, thesis_id, direction, "
        "order_type, price, size_pct, size_usdt, status, "
        "created_at_utc, expires_at_utc, filled_at_utc, "
        "filled_price, filled_btc_amount) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (order_id, thesis_id, "long", "entry", filled_price, 0.30,
         btc_amount * filled_price, "filled",
         "2026-05-04T08:00:00Z", "2099-05-10T08:00:00Z",
         "2026-05-04T08:30:00Z", filled_price, btc_amount),
    )
    conn.commit()
    conn.close()


def _seed_pending_order(db_path, *, order_id, thesis_id, order_type="entry",
                         price=75000.0):
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO virtual_orders (order_id, thesis_id, direction, "
        "order_type, price, size_pct, size_usdt, status, "
        "created_at_utc, expires_at_utc) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (order_id, thesis_id, "long", order_type, price, 0.30,
         price * 0.4, "pending",
         "2026-05-04T08:00:00Z", "2099-05-10T08:00:00Z"),
    )
    conn.commit()
    conn.close()


# ============================================================
# 1. 向后兼容:无 v1.4 数据时 4 字段为 null
# ============================================================

def test_current_backward_compat_all_4_fields_null(client, db_path):
    """无 va / 无 thesis / 无 orders → 4 字段都 null,原字段不变。"""
    _seed_strategy_run(db_path)
    r = client.get("/api/strategy/current")
    assert r.status_code == 200
    body = r.json()
    # 原字段都在
    assert body["run_id"] == "r_test"
    assert body["run_trigger"] == "scheduled"
    assert body["rules_version"] == "v1.4"
    # state 是 dict
    assert isinstance(body["state"], dict)
    # 4 新字段都 null
    state = body["state"]
    assert state["account_summary"] is None
    assert state["active_thesis"] is None
    assert state["position_summary"] is None
    assert state["pending_orders_summary"] is None


# ============================================================
# 2. account_summary 字段
# ============================================================

def test_account_summary_populated(client, db_path):
    _seed_strategy_run(db_path)
    _seed_va_snapshot(db_path, total_equity=105000.0)
    r = client.get("/api/strategy/current")
    body = r.json()
    acc = body["state"]["account_summary"]
    assert acc is not None
    assert acc["snapshot_id"] == "s_curr"
    assert acc["total_equity"] == 105000.0
    assert acc["initial_capital"] == 100000.0
    # PnL 5%
    assert abs(acc["total_pnl_pct"] - 5.0) < 0.001
    assert acc["available_cash"] == 50000.0


# ============================================================
# 3. active_thesis 字段
# ============================================================

def test_active_thesis_summary_populated(client, db_path):
    _seed_strategy_run(db_path)
    _seed_active_thesis(db_path, thesis_id="t_summary",
                         direction="short", lifecycle_stage="holding")
    r = client.get("/api/strategy/current")
    at = r.json()["state"]["active_thesis"]
    assert at is not None
    assert at["thesis_id"] == "t_summary"
    assert at["direction"] == "short"
    assert at["lifecycle_stage"] == "holding"
    assert at["confidence_score"] == 70
    assert at["is_60d_capped"] is False


def test_active_thesis_null_when_no_active(client, db_path):
    _seed_strategy_run(db_path)
    # 写一个 closed thesis(非 active)
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO theses (thesis_id, created_at_run_id, created_at_utc, "
        "direction, core_logic, confidence_score, break_conditions, "
        "lifecycle_stage, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("t_closed", "r", "2026-04-01T00:00:00Z", "long",
         "x", 70, "[]", "closed", "closed_loss"),
    )
    conn.commit()
    conn.close()

    r = client.get("/api/strategy/current")
    assert r.json()["state"]["active_thesis"] is None


# ============================================================
# 4. position_summary 字段
# ============================================================

def test_position_summary_aggregates_filled_entries(client, db_path):
    _seed_strategy_run(db_path)
    _seed_active_thesis(db_path, thesis_id="t_pos")
    _seed_filled_entry(db_path, order_id="o_e1", thesis_id="t_pos",
                        btc_amount=0.3, filled_price=75000.0)
    _seed_filled_entry(db_path, order_id="o_e2", thesis_id="t_pos",
                        btc_amount=0.2, filled_price=78000.0)
    r = client.get("/api/strategy/current")
    pos = r.json()["state"]["position_summary"]
    assert pos is not None
    assert pos["thesis_id"] == "t_pos"
    assert pos["direction"] == "long"
    assert abs(pos["btc_amount"] - 0.5) < 1e-9
    assert pos["entry_orders_filled"] == 2
    # 加权平均价 = (0.3*75000 + 0.2*78000) / 0.5 = 76200
    assert abs(pos["avg_entry_price"] - 76200.0) < 0.5


def test_position_summary_null_when_no_active(client, db_path):
    _seed_strategy_run(db_path)
    r = client.get("/api/strategy/current")
    assert r.json()["state"]["position_summary"] is None


# ============================================================
# 5. pending_orders_summary 字段
# ============================================================

def test_pending_orders_summary_by_type(client, db_path):
    _seed_strategy_run(db_path)
    _seed_active_thesis(db_path, thesis_id="t_pend")
    _seed_pending_order(db_path, order_id="o_e1", thesis_id="t_pend",
                         order_type="entry")
    _seed_pending_order(db_path, order_id="o_e2", thesis_id="t_pend",
                         order_type="entry")
    _seed_pending_order(db_path, order_id="o_sl", thesis_id="t_pend",
                         order_type="stop_loss")
    _seed_pending_order(db_path, order_id="o_tp", thesis_id="t_pend",
                         order_type="take_profit")
    r = client.get("/api/strategy/current")
    p = r.json()["state"]["pending_orders_summary"]
    assert p is not None
    assert p["thesis_id"] == "t_pend"
    assert p["total"] == 4
    assert p["by_type"] == {"entry": 2, "stop_loss": 1, "take_profit": 1}


# ============================================================
# 6. 既有字段顺序与值不变(向后兼容)
# ============================================================

def test_current_does_not_break_existing_state_fields(client, db_path):
    """现有 normalize_state 输出的 schema_version / summary_card 等仍在。"""
    _seed_strategy_run(db_path)
    _seed_va_snapshot(db_path)
    r = client.get("/api/strategy/current")
    state = r.json()["state"]
    # normalize_state 输出的固有字段
    assert "schema_version" in state
    assert "summary_card" in state
    assert "layer_cards" in state
    assert "raw" in state
    # 4 新字段是追加,不替换
    assert "account_summary" in state
