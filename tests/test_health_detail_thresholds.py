"""tests/test_health_detail_thresholds.py — Sprint 1.5p Task C。

FRED 阈值修正:1.5n 写的是 "宏观 2h warn / 24h critical"(对 yfinance 高频源
合理,但 FRED 是 daily cadence)。本 sprint 改为 30h warn / 72h critical,
跟 Glassnode 链上 daily 同档。

§Z 真值断言:
- FRED 28h 前 → ok
- FRED 32h 前 → warn
- FRED 75h 前 → critical
- 反退化:阈值不能回到 2h
"""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.routes.system import _SOURCE_CADENCE
from src.data.storage.connection import get_connection, init_db


@pytest.fixture
def db_path() -> Path:
    tmp = Path(tempfile.mkdtemp()) / "fred_threshold.db"
    init_db(db_path=tmp, verbose=False)
    return tmp


@pytest.fixture
def client(db_path: Path) -> TestClient:
    app = create_app(conn_factory=lambda: get_connection(db_path))
    return TestClient(app)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed_fred_metric(db_path: Path, hours_ago: float) -> None:
    conn = sqlite3.connect(db_path)
    try:
        ts = _iso(datetime.now(timezone.utc) - timedelta(hours=hours_ago))
        conn.execute(
            "INSERT INTO macro_metrics "
            "(captured_at_utc, metric_name, value, source, inserted_at_utc) "
            "VALUES (?, ?, ?, ?, ?)",
            (ts, "dxy", 104.5, "fred", ts),
        )
        conn.commit()
    finally:
        conn.close()


# ============================================================
# 阈值表自检
# ============================================================

def test_fred_threshold_30h_warn_72h_critical():
    """1.5p 反退化:FRED warn=30h,critical=72h(daily cadence)。"""
    cfg = _SOURCE_CADENCE["fred_macro"]
    assert cfg["warn"] == 30 * 60, f"warn 应 30h,实际 {cfg['warn']/60}h"
    assert cfg["critical"] == 72 * 60, (
        f"critical 应 72h,实际 {cfg['critical']/60}h"
    )


def test_fred_old_2h_threshold_no_longer_in_table():
    """反退化:FRED 阈值不能回到 2h(误判 daily 为高频)。"""
    cfg = _SOURCE_CADENCE["fred_macro"]
    assert cfg["warn"] > 2 * 60, "FRED warn 阈值不该 ≤ 2h"


def test_yahoo_macro_removed_from_cadence():
    """Sprint 2.6-A.3 STOPPED Yahoo,1.5p 删除 panel entry。"""
    assert "yahoo_macro" not in _SOURCE_CADENCE


def test_cadence_table_has_4_sources():
    assert len(_SOURCE_CADENCE) == 4
    expected = {"binance_kline_1h", "coinglass_derivatives",
                "glassnode_onchain", "fred_macro"}
    assert set(_SOURCE_CADENCE.keys()) == expected


# ============================================================
# 端到端 endpoint:FRED status 真值断言
# ============================================================

def test_fred_28h_old_is_ok(client: TestClient, db_path: Path):
    """28h 前 → status=ok(< 30h warn 阈值)。"""
    _seed_fred_metric(db_path, hours_ago=28)
    r = client.get("/api/system/health-detail")
    body = r.json()
    fred = next(s for s in body["data_sources"] if "FRED" in s["name"])
    assert fred["status"] == "ok"
    assert fred["age_minutes"] is not None


def test_fred_32h_old_is_warn(client: TestClient, db_path: Path):
    """32h 前 → status=warn(>30h,<72h)。1.5p 之前会被判 critical(>24h)。"""
    _seed_fred_metric(db_path, hours_ago=32)
    r = client.get("/api/system/health-detail")
    body = r.json()
    fred = next(s for s in body["data_sources"] if "FRED" in s["name"])
    assert fred["status"] == "warn"


def test_fred_75h_old_is_critical(client: TestClient, db_path: Path):
    """75h 前 → status=critical(>72h)。"""
    _seed_fred_metric(db_path, hours_ago=75)
    r = client.get("/api/system/health-detail")
    body = r.json()
    fred = next(s for s in body["data_sources"] if "FRED" in s["name"])
    assert fred["status"] == "critical"


def test_fred_5h_old_is_ok_not_warn(client: TestClient, db_path: Path):
    """关键反退化:5 小时前是正常 daily cadence,1.5n 误判 warn,1.5p 应 ok。"""
    _seed_fred_metric(db_path, hours_ago=5)
    r = client.get("/api/system/health-detail")
    body = r.json()
    fred = next(s for s in body["data_sources"] if "FRED" in s["name"])
    assert fred["status"] == "ok", (
        f"FRED 5 小时前应 ok(daily cadence),实际 {fred['status']} — "
        "1.5p 阈值修复回退?"
    )
