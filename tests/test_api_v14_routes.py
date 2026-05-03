"""tests/test_api_v14_routes.py — Sprint 1.10-I commit 2 单测。

覆盖 v1.4 §9.5 #8-#18 11 个新 API + ThesesDAO.get_by_id + HealthResponse.review_pending。
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.data.storage.connection import get_connection, init_db


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def db_path():
    tmp = Path(tempfile.mkdtemp()) / "test_v14_api.db"
    init_db(db_path=tmp, verbose=False)
    # 应用 1.10-A → H 全套 v1.4 migration
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


def _seed_va_snapshot(db_path, *, snapshot_id, snapshot_at_utc, total_equity,
                       initial_capital=100000.0, available_cash=50000.0):
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO virtual_account "
        "(snapshot_id, run_id, snapshot_at_utc, btc_price_at_snapshot, "
        " initial_capital, available_cash, total_equity) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (snapshot_id, snapshot_id, snapshot_at_utc, 75000.0,
         initial_capital, available_cash, total_equity),
    )
    conn.commit()
    conn.close()


def _seed_thesis(db_path, *, thesis_id, direction="long",
                  status="active", created_at_utc="2026-05-04T12:00:00Z",
                  closed_at_utc=None, close_channel=None,
                  final_realized_pnl_pct=None):
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO theses (thesis_id, created_at_run_id, created_at_utc, "
        "direction, core_logic, confidence_score, break_conditions, "
        "lifecycle_stage, status, closed_at_utc, close_channel, "
        "final_realized_pnl_pct) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (thesis_id, "r_test", created_at_utc, direction,
         "test logic", 70, '["a","b","c"]',
         "closed" if status != "active" else "planned",
         status, closed_at_utc, close_channel,
         final_realized_pnl_pct),
    )
    conn.commit()
    conn.close()


def _seed_pending_order(db_path, *, order_id, thesis_id, order_type="entry",
                        price=75000.0, size_usdt=30000.0):
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO virtual_orders (order_id, thesis_id, direction, "
        "order_type, price, size_pct, size_usdt, status, "
        "created_at_utc, expires_at_utc) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (order_id, thesis_id, "long", order_type, price, 0.30,
         size_usdt, "pending", "2026-05-04T12:00:00Z",
         "2099-05-10T12:00:00Z"),
    )
    conn.commit()
    conn.close()


def _seed_weekly_review(db_path, *, week_start_utc, output, critical_count=0):
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO weekly_reviews "
        "(week_start_utc, triggered_at_utc, output_json, critical_count) "
        "VALUES (?, ?, ?, ?)",
        (week_start_utc, week_start_utc + "T22:00:00Z",
         json.dumps(output, ensure_ascii=False), critical_count),
    )
    conn.commit()
    conn.close()


# ============================================================
# 1. GET /api/account/current + history + returns
# ============================================================

def test_account_current_empty(client):
    r = client.get("/api/account/current")
    assert r.status_code == 200
    assert r.json() == {}


def test_account_current_returns_latest(client, db_path):
    _seed_va_snapshot(db_path, snapshot_id="s1",
                       snapshot_at_utc="2026-05-01T00:00:00Z",
                       total_equity=100500.0)
    _seed_va_snapshot(db_path, snapshot_id="s2",
                       snapshot_at_utc="2026-05-04T00:00:00Z",
                       total_equity=102000.0)
    r = client.get("/api/account/current")
    assert r.status_code == 200
    body = r.json()
    assert body["snapshot_id"] == "s2"
    assert body["total_equity"] == 102000.0


def test_account_history_returns_window(client, db_path):
    """30 天窗口 — 30 天内 snapshots ASC。"""
    _seed_va_snapshot(db_path, snapshot_id="s_old",
                       snapshot_at_utc="2025-01-01T00:00:00Z",
                       total_equity=100000.0)
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    _seed_va_snapshot(db_path, snapshot_id="s_recent",
                       snapshot_at_utc=(now - timedelta(days=5)).strftime(
                           "%Y-%m-%dT%H:%M:%SZ"),
                       total_equity=105000.0)
    r = client.get("/api/account/history?days=30")
    assert r.status_code == 200
    body = r.json()
    assert body["days"] == 30
    snap_ids = [s["snapshot_id"] for s in body["snapshots"]]
    assert "s_recent" in snap_ids
    assert "s_old" not in snap_ids  # 超 30 天


def test_account_history_validates_days_param(client):
    r = client.get("/api/account/history?days=0")
    assert r.status_code == 422  # ge=1
    r2 = client.get("/api/account/history?days=999")
    assert r2.status_code == 422  # le=365


def test_account_returns_empty_when_no_snapshots(client):
    r = client.get("/api/account/returns")
    assert r.status_code == 200
    body = r.json()
    assert body["snapshots_count"] == 0
    assert body["daily_pct"] is None


def test_account_returns_with_snapshots(client, db_path):
    _seed_va_snapshot(db_path, snapshot_id="s1",
                       snapshot_at_utc="2026-04-01T00:00:00Z",
                       total_equity=100000.0)
    _seed_va_snapshot(db_path, snapshot_id="s2",
                       snapshot_at_utc="2026-05-04T00:00:00Z",
                       total_equity=105000.0)
    r = client.get("/api/account/returns")
    assert r.status_code == 200
    body = r.json()
    assert body["snapshots_count"] == 2


# ============================================================
# 2. GET /api/theses/active + history + {thesis_id}
# ============================================================

def test_theses_active_empty(client):
    r = client.get("/api/theses/active")
    assert r.status_code == 200
    assert r.json() == {}


def test_theses_active_returns_active(client, db_path):
    _seed_thesis(db_path, thesis_id="t_act", direction="long",
                  status="active",
                  created_at_utc="2026-05-04T10:00:00Z")
    r = client.get("/api/theses/active")
    assert r.status_code == 200
    body = r.json()
    assert body["thesis_id"] == "t_act"
    assert body["direction"] == "long"
    assert body["break_conditions"] == ["a", "b", "c"]  # JSON 还原


def test_theses_history_returns_list(client, db_path):
    _seed_thesis(db_path, thesis_id="t1",
                  created_at_utc="2026-05-01T10:00:00Z",
                  status="closed_loss",
                  closed_at_utc="2026-05-03T10:00:00Z",
                  close_channel="A")
    _seed_thesis(db_path, thesis_id="t2",
                  created_at_utc="2026-05-04T10:00:00Z",
                  status="active")
    r = client.get("/api/theses/history?limit=10")
    assert r.status_code == 200
    body = r.json()
    assert body["limit"] == 10
    ids = [it["thesis_id"] for it in body["items"]]
    # DESC 排序:t2(更新) 在前
    assert ids == ["t2", "t1"]


def test_theses_get_by_id_found(client, db_path):
    _seed_thesis(db_path, thesis_id="t_specific", direction="short",
                  created_at_utc="2026-05-04T10:00:00Z")
    r = client.get("/api/theses/t_specific")
    assert r.status_code == 200
    body = r.json()
    assert body["thesis_id"] == "t_specific"
    assert body["direction"] == "short"


def test_theses_get_by_id_404(client):
    r = client.get("/api/theses/no_such_id")
    assert r.status_code == 404


# ============================================================
# 3. GET /api/orders/pending + history
# ============================================================

def test_orders_pending_no_active_thesis(client):
    r = client.get("/api/orders/pending")
    assert r.status_code == 200
    body = r.json()
    assert body["active_thesis_id"] is None
    assert body["items"] == []


def test_orders_pending_with_active_thesis(client, db_path):
    _seed_thesis(db_path, thesis_id="t_p", status="active",
                  created_at_utc="2026-05-04T10:00:00Z")
    _seed_pending_order(db_path, order_id="o_entry_1",
                         thesis_id="t_p", order_type="entry", price=75000.0)
    _seed_pending_order(db_path, order_id="o_sl_1",
                         thesis_id="t_p", order_type="stop_loss", price=72000.0)
    r = client.get("/api/orders/pending")
    assert r.status_code == 200
    body = r.json()
    assert body["active_thesis_id"] == "t_p"
    assert len(body["items"]) == 2
    types = {o["order_type"] for o in body["items"]}
    assert types == {"entry", "stop_loss"}


def test_orders_history_filters_by_days(client, db_path):
    _seed_thesis(db_path, thesis_id="t_h", status="active",
                  created_at_utc="2025-01-01T10:00:00Z")
    # 老的 cancelled 挂单(超 30d 窗口外)
    _seed_pending_order(db_path, order_id="o_old", thesis_id="t_h")
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "UPDATE virtual_orders SET status='cancelled', "
        "cancelled_reason='test', created_at_utc='2025-01-01T10:00:00Z' "
        "WHERE order_id='o_old'",
    )
    conn.commit()
    conn.close()
    r = client.get("/api/orders/history?days=30")
    assert r.status_code == 200
    body = r.json()
    assert body["days"] == 30
    ids = [it["order_id"] for it in body["items"]]
    assert "o_old" not in ids


# ============================================================
# 4. GET /api/review/weekly/latest + history
# ============================================================

def test_weekly_review_latest_empty(client):
    r = client.get("/api/review/weekly/latest")
    assert r.status_code == 200
    assert r.json() == {}


def test_weekly_review_latest_returns_parsed_output(client, db_path):
    _seed_weekly_review(
        db_path, week_start_utc="2026-04-27",
        output={"performance_summary": {"weekly_pnl_pct": 1.5}},
        critical_count=2,
    )
    r = client.get("/api/review/weekly/latest")
    assert r.status_code == 200
    body = r.json()
    assert body["week_start_utc"] == "2026-04-27"
    assert body["critical_count"] == 2
    # output_json 已 parse
    assert body["output"]["performance_summary"]["weekly_pnl_pct"] == 1.5


def test_weekly_review_history_returns_list(client, db_path):
    _seed_weekly_review(db_path, week_start_utc="2026-04-20",
                        output={"x": 1})
    _seed_weekly_review(db_path, week_start_utc="2026-04-27",
                        output={"x": 2})
    r = client.get("/api/review/weekly/history?limit=12")
    assert r.status_code == 200
    body = r.json()
    assert body["limit"] == 12
    assert len(body["items"]) == 2
    # 默认 DESC,最新周在前
    assert body["items"][0]["week_start_utc"] == "2026-04-27"


# ============================================================
# 5. POST /api/review_pending/resolve(D4=b+c)
# ============================================================

def _enter_rp(db_path, *, reason, related_thesis_id=None):
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    from src.strategy.review_pending import enter_review_pending
    enter_review_pending(
        conn, reason=reason, related_thesis_id=related_thesis_id,
        entered_at_utc="2026-05-04T10:00:00Z",
    )
    conn.commit()
    conn.close()


def test_resolve_validates_exit_type_enum(client):
    r = client.post(
        "/api/review_pending/resolve",
        json={"exit_type": "x", "reason": "1234567890"},
    )
    assert r.status_code == 422  # 'x' 不是 enum


def test_resolve_validates_reason_min_length(client):
    r = client.post(
        "/api/review_pending/resolve",
        json={"exit_type": "a", "reason": "short"},
    )
    assert r.status_code == 422  # < 10 chars


def test_resolve_exit_a_success(client, db_path):
    _enter_rp(db_path, reason="60d_cap")
    r = client.post(
        "/api/review_pending/resolve",
        json={"exit_type": "a", "reason": "用户调阈值,降 grade B 门槛"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["exited"] is True
    assert body["exit_type"] == "a"


def test_resolve_exit_d_only_for_overly_conservative(client, db_path):
    """EXIT_D 拒绝非 overly_conservative reason → 400。"""
    _enter_rp(db_path, reason="60d_cap")  # 非 overly_conservative
    r = client.post(
        "/api/review_pending/resolve",
        json={"exit_type": "d",
              "reason": "用户尝试自然恢复 EXIT_D 但当前 reason=60d_cap"},
    )
    assert r.status_code == 400
    body = r.json()
    detail = body.get("detail") or {}
    assert detail.get("exited") is False


def test_resolve_no_active_rp_returns_400(client):
    r = client.post(
        "/api/review_pending/resolve",
        json={"exit_type": "a", "reason": "无 active RP 但用户尝试解除"},
    )
    assert r.status_code == 400


# ============================================================
# 6. GET /api/health 加 review_pending 字段(D2=a)
# ============================================================

def test_health_no_active_rp(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    # 向后兼容:原字段都在
    assert "status" in body
    assert "version" in body
    assert "db_accessible" in body
    # 新字段:无 active RP → null
    assert body["review_pending"] is None


def test_health_active_rp_populated(client, db_path):
    _enter_rp(db_path, reason="overly_conservative",
              related_thesis_id="t_xyz")
    r = client.get("/api/health")
    assert r.status_code == 200
    rp = r.json()["review_pending"]
    assert rp is not None
    assert rp["active"] is True
    assert rp["reason"] == "overly_conservative"
    assert rp["related_thesis_id"] == "t_xyz"


# ============================================================
# 7. ThesesDAO.get_by_id 单测(commit 2 新加)
# ============================================================

def test_theses_dao_get_by_id_found(db_path):
    _seed_thesis(db_path, thesis_id="t_unit_get",
                  created_at_utc="2026-05-04T10:00:00Z")
    import sqlite3
    from src.data.storage.dao import ThesesDAO
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    res = ThesesDAO.get_by_id(conn, thesis_id="t_unit_get")
    conn.close()
    assert res is not None
    assert res["thesis_id"] == "t_unit_get"
    assert res["break_conditions"] == ["a", "b", "c"]


def test_theses_dao_get_by_id_not_found(db_path):
    import sqlite3
    from src.data.storage.dao import ThesesDAO
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    res = ThesesDAO.get_by_id(conn, thesis_id="bogus")
    conn.close()
    assert res is None
