"""tests/test_factor_cards_refresher.py — Sprint 2.8-A 实时刷新 factor_cards。

§Z 端到端:
- 真 SQLite + 真 emit_factor_cards
- 断言 latest_factor_cards 表行数 == 1,cards_json 含若干卡片,refreshed_at_utc 在 now ± 5s
- collector 失败时 refresh 也不让 collector job 崩溃
- API /api/strategy/current 把 latest_factor_cards 内容覆盖到 state.factor_cards
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.data.storage.connection import init_db
from src.data.storage.dao import LatestFactorCardsDAO
from src.scheduler import jobs as jobs_mod
from src.strategy.factor_cards_refresher import refresh_factor_cards


def _row_conn(path: Path) -> sqlite3.Connection:
    """Helper:模拟 production get_connection 的 row_factory=Row 设定。"""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture
def db_path():
    tmp = Path(tempfile.mkdtemp()) / "fcr.db"
    init_db(db_path=tmp, verbose=False)
    # Apply 2.7-D + 2.8-A migrations(latest_factor_cards 表)
    from scripts.migrate_2_7_d import apply_migration
    conn = sqlite3.connect(tmp)
    apply_migration(conn)
    conn.close()
    return tmp


@pytest.fixture
def db_conn(db_path):
    conn = _row_conn(db_path)
    yield conn
    conn.close()


# ============================================================
# DAO basic
# ============================================================

def test_latest_factor_cards_dao_upsert_then_read(db_conn):
    cards = [{"card_id": "test_1", "current_value": 42}]
    LatestFactorCardsDAO.upsert(db_conn, cards, refreshed_at_utc="2026-04-28T10:00:00Z")
    db_conn.commit()
    out = LatestFactorCardsDAO.get_latest(db_conn)
    assert out is not None
    assert out["cards"] == cards
    assert out["refreshed_at_utc"] == "2026-04-28T10:00:00Z"


def test_latest_factor_cards_dao_upsert_overwrites_single_row(db_conn):
    LatestFactorCardsDAO.upsert(db_conn, [{"v": 1}],
                                  refreshed_at_utc="2026-04-28T10:00:00Z")
    LatestFactorCardsDAO.upsert(db_conn, [{"v": 2}],
                                  refreshed_at_utc="2026-04-28T11:00:00Z")
    db_conn.commit()
    cnt = db_conn.execute("SELECT COUNT(*) FROM latest_factor_cards").fetchone()[0]
    assert cnt == 1
    out = LatestFactorCardsDAO.get_latest(db_conn)
    assert out["cards"] == [{"v": 2}]
    assert out["refreshed_at_utc"] == "2026-04-28T11:00:00Z"


def test_latest_factor_cards_dao_get_empty(db_conn):
    assert LatestFactorCardsDAO.get_latest(db_conn) is None


# ============================================================
# refresh_factor_cards e2e
# ============================================================

def test_refresh_writes_latest_factor_cards_table(db_conn):
    """端到端:真 emit + 真 DAO + 真 SQLite。"""
    from datetime import timedelta as _td
    before = datetime.now(timezone.utc)
    result = refresh_factor_cards(db_conn)
    after = datetime.now(timezone.utc)

    assert result["refreshed"] is True
    assert result["card_count"] > 0  # 即便 DB 空,emitter 仍生成占位卡

    out = LatestFactorCardsDAO.get_latest(db_conn)
    assert out is not None
    assert isinstance(out["cards"], list)
    assert len(out["cards"]) == result["card_count"]

    # refreshed_at_utc 在 [before - 1s, after + 1s] 内(秒级精度容差)
    refreshed = datetime.fromisoformat(
        out["refreshed_at_utc"].replace("Z", "+00:00")
    )
    assert before - _td(seconds=1) <= refreshed <= after + _td(seconds=1)


def test_refresh_handles_emit_failure_returns_error_dict(db_conn):
    """emit 抛错 → refresh 不让 collector 崩,返回 error dict。"""
    with patch(
        "src.strategy.factor_card_emitter.emit_factor_cards",
        side_effect=RuntimeError("synthetic emit fail"),
    ):
        result = refresh_factor_cards(db_conn)
    assert result["refreshed"] is False
    assert "synthetic emit fail" in result["error"]


# ============================================================
# Collector wrap_job integration
# ============================================================

def test_collect_klines_1h_triggers_refresh_on_success(db_path):
    """collect_klines_1h 成功后,result 含 factor_cards_refresh + DB 表有行。"""
    cg_inst = MagicMock()
    cg_inst.fetch_klines.return_value = [
        {"timestamp": "2026-04-28T10:00:00Z",
         "open": 50000, "high": 50100, "low": 49900, "close": 50050,
         "volume": 100.0}
    ]
    for fn in jobs_mod._DERIVATIVES_FETCHERS_1H:
        getattr(cg_inst, fn).return_value = []

    with patch("src.data.collectors.coinglass.CoinglassCollector",
               return_value=cg_inst):
        result = jobs_mod.job_collect_klines_1h(
            conn_factory=lambda: _row_conn(db_path),
        )

    assert result["status"] == "ok"
    assert "factor_cards_refresh" in result
    assert result["factor_cards_refresh"]["refreshed"] is True
    # DB row exists
    conn = sqlite3.connect(db_path)
    try:
        cnt = conn.execute(
            "SELECT COUNT(*) FROM latest_factor_cards"
        ).fetchone()[0]
        assert cnt == 1
    finally:
        conn.close()


def test_collect_macro_triggers_refresh_on_success(db_path):
    fred_inst = MagicMock()
    fred_inst.enabled = True
    fred_inst.collect_and_save_all.return_value = {"dxy": 5}
    with patch("src.data.collectors.fred.FredCollector", return_value=fred_inst):
        result = jobs_mod.job_collect_macro(
            conn_factory=lambda: _row_conn(db_path),
        )
    assert result["status"] == "ok"
    assert result.get("factor_cards_refresh", {}).get("refreshed") is True


def test_collect_macro_skipped_does_not_trigger_refresh(db_path):
    """status=skipped(无 FRED key)→ 不调 refresh。"""
    fred_inst = MagicMock()
    fred_inst.enabled = False
    with patch("src.data.collectors.fred.FredCollector", return_value=fred_inst):
        result = jobs_mod.job_collect_macro(
            conn_factory=lambda: _row_conn(db_path),
        )
    assert result["status"] == "skipped"
    # refresh 不在 status='ok' 时执行
    assert "factor_cards_refresh" not in result


def test_refresh_failure_does_not_crash_collector(db_path):
    """refresh 抛错 → collector 仍返回成功 + factor_cards_refresh 含 error。"""
    cg_inst = MagicMock()
    cg_inst.fetch_klines.return_value = []
    for fn in jobs_mod._DERIVATIVES_FETCHERS_1H:
        getattr(cg_inst, fn).return_value = []

    with patch("src.data.collectors.coinglass.CoinglassCollector",
               return_value=cg_inst), \
         patch("src.strategy.factor_cards_refresher.refresh_factor_cards",
               side_effect=RuntimeError("refresh boom")):
        result = jobs_mod.job_collect_klines_1h(
            conn_factory=lambda: _row_conn(db_path),
        )

    assert result["status"] == "ok"  # collector 不被 refresh 错误拖累
    assert result["factor_cards_refresh"]["refreshed"] is False
    assert "refresh boom" in result["factor_cards_refresh"]["error"]


# ============================================================
# API /strategy/current swap behavior
# ============================================================

def _seed_strategy_run(db_path: Path, run_ts: str = "2026-04-28T08:00:00Z",
                        old_factor_cards: list = None) -> None:
    cards = old_factor_cards or [{"card_id": "OLD", "current_value": 0}]
    state = {"factor_cards": cards, "meta": {"strategy_flavor": "swing"}}
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO strategy_runs "
        "(run_id, generated_at_utc, generated_at_bjt, action_state, "
        " full_state_json, run_trigger, rules_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("test-run", run_ts, "2026-04-28 16:00 (BJT)",
         "FLAT", json.dumps(state), "scheduled", "v1.2.0"),
    )
    conn.commit()
    conn.close()


def test_api_strategy_current_reads_from_latest_factor_cards(db_path):
    """API 把 latest_factor_cards 覆盖到 state.factor_cards;老的 4h 快照不再渲染。"""
    from fastapi.testclient import TestClient
    from src.api.app import create_app

    # Seed strategy_runs with OLD factor_cards
    _seed_strategy_run(db_path, old_factor_cards=[{"card_id": "OLD"}])

    # Seed latest_factor_cards with NEW factor_cards
    fresh_cards = [
        {"card_id": "FRESH_1", "current_value": 50000},
        {"card_id": "FRESH_2", "current_value": 0.001},
    ]
    conn = sqlite3.connect(db_path)
    LatestFactorCardsDAO.upsert(conn, fresh_cards,
                                  refreshed_at_utc="2026-04-28T16:00:30Z")
    conn.commit()
    conn.close()

    app = create_app(conn_factory=lambda: _row_conn(db_path))
    with TestClient(app) as client:
        resp = client.get("/api/strategy/current")
    assert resp.status_code == 200
    body = resp.json()
    cards = body["state"]["factor_cards"]
    card_ids = {c["card_id"] for c in cards}
    assert "FRESH_1" in card_ids
    assert "FRESH_2" in card_ids
    assert "OLD" not in card_ids  # 老的 4h 快照已被覆盖
    # meta 含 factor_cards_refreshed_at_utc(诊断字段)
    assert body["state"]["meta"].get("factor_cards_refreshed_at_utc") == \
        "2026-04-28T16:00:30Z"


def test_api_strategy_current_falls_back_when_latest_empty(db_path):
    """latest_factor_cards 表为空(冷启动)→ 退回 state.factor_cards。"""
    from fastapi.testclient import TestClient
    from src.api.app import create_app

    _seed_strategy_run(db_path, old_factor_cards=[{"card_id": "FALLBACK"}])
    # Don't seed latest_factor_cards

    app = create_app(conn_factory=lambda: _row_conn(db_path))
    with TestClient(app) as client:
        resp = client.get("/api/strategy/current")
    assert resp.status_code == 200
    cards = resp.json()["state"]["factor_cards"]
    assert any(c["card_id"] == "FALLBACK" for c in cards)
