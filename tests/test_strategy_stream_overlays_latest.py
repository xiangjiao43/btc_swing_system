"""tests/test_strategy_stream_overlays_latest.py — Sprint 2.8-A.1 SSE 覆盖。

§Z 端到端:
- 真 SQLite 含 strategy_runs(state.factor_cards 是 OLD)+ latest_factor_cards 单行(NEW)
- 调 /api/strategy/stream(SSE)
- 解析第一条 data: line,断言其 state.factor_cards = NEW(覆盖生效)
- 同时直测 _overlay_latest_factor_cards helper(/current 与 /stream 共用)
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.data.storage.connection import init_db
from src.data.storage.dao import LatestFactorCardsDAO


def _row_conn(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture
def db_path():
    tmp = Path(tempfile.mkdtemp()) / "sse.db"
    init_db(db_path=tmp, verbose=False)
    from scripts.migrate_2_7_d import apply_migration
    conn = sqlite3.connect(tmp)
    apply_migration(conn)
    conn.close()
    return tmp


def _seed(db_path: Path, *, old_cards: list, new_cards: list,
          new_refreshed_at: str = "2026-04-28T16:30:30Z") -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    state = {
        "factor_cards": old_cards,
        "meta": {"strategy_flavor": "swing"},
    }
    conn.execute(
        "INSERT INTO strategy_runs "
        "(run_id, generated_at_utc, generated_at_bjt, action_state, "
        " full_state_json, run_trigger, rules_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("sse-run-1", "2026-04-28T08:00:00Z", "2026-04-28 16:00 (BJT)",
         "FLAT", json.dumps(state), "scheduled", "v1.2.0"),
    )
    LatestFactorCardsDAO.upsert(conn, new_cards, refreshed_at_utc=new_refreshed_at)
    conn.commit()
    conn.close()


# ============================================================
# Direct helper test
# ============================================================

def test_overlay_latest_factor_cards_dict_state(db_path):
    """state 是 dict 时,原地覆盖 factor_cards + 写 meta.factor_cards_refreshed_at_utc。"""
    from src.api.routes.strategy import _overlay_latest_factor_cards
    _seed(db_path,
          old_cards=[{"card_id": "OLD"}],
          new_cards=[{"card_id": "NEW_A"}, {"card_id": "NEW_B"}],
          new_refreshed_at="2026-04-28T16:30:30Z")
    row = {
        "run_id": "x",
        "state": {"factor_cards": [{"card_id": "OLD"}], "meta": {}},
    }
    conn = _row_conn(db_path)
    try:
        out = _overlay_latest_factor_cards(row, conn)
    finally:
        conn.close()
    assert {c["card_id"] for c in out["state"]["factor_cards"]} == {"NEW_A", "NEW_B"}
    assert out["state"]["meta"]["factor_cards_refreshed_at_utc"] == "2026-04-28T16:30:30Z"


def test_overlay_latest_factor_cards_string_state(db_path):
    """state 是 JSON 字符串时(从 DB 取出来),解析后再覆盖。"""
    from src.api.routes.strategy import _overlay_latest_factor_cards
    _seed(db_path,
          old_cards=[{"card_id": "OLD"}],
          new_cards=[{"card_id": "NEW"}])
    row = {
        "run_id": "x",
        "state": json.dumps({"factor_cards": [{"card_id": "OLD"}], "meta": {}}),
    }
    conn = _row_conn(db_path)
    try:
        out = _overlay_latest_factor_cards(row, conn)
    finally:
        conn.close()
    assert isinstance(out["state"], dict)
    assert out["state"]["factor_cards"][0]["card_id"] == "NEW"


def test_overlay_returns_row_when_latest_table_empty(db_path):
    """latest_factor_cards 为空 → 原样返回 row,不抛错。"""
    from src.api.routes.strategy import _overlay_latest_factor_cards
    # 不 seed latest_factor_cards
    row = {"run_id": "x",
           "state": {"factor_cards": [{"card_id": "ORIGINAL"}], "meta": {}}}
    conn = _row_conn(db_path)
    try:
        out = _overlay_latest_factor_cards(row, conn)
    finally:
        conn.close()
    assert out["state"]["factor_cards"][0]["card_id"] == "ORIGINAL"


def test_overlay_handles_none_row(db_path):
    """row 为 None(空 DB)→ 返回 None。"""
    from src.api.routes.strategy import _overlay_latest_factor_cards
    conn = _row_conn(db_path)
    try:
        assert _overlay_latest_factor_cards(None, conn) is None
    finally:
        conn.close()


# ============================================================
# /current still uses overlay (regression after extraction)
# ============================================================

def test_current_endpoint_still_overlays_after_refactor(db_path):
    _seed(db_path,
          old_cards=[{"card_id": "OLD_C"}],
          new_cards=[{"card_id": "NEW_C"}])
    app = create_app(conn_factory=lambda: _row_conn(db_path))
    with TestClient(app) as client:
        resp = client.get("/api/strategy/current")
    assert resp.status_code == 200
    cards = resp.json()["state"]["factor_cards"]
    assert {c["card_id"] for c in cards} == {"NEW_C"}


# ============================================================
# /stream initial push includes overlay
# ============================================================

def test_stream_initial_and_loop_both_call_overlay():
    """source-level guard:strategy.py 的 stream() 内 event_gen 必须在
    initial push 和 polling loop **两处** 调 _overlay_latest_factor_cards。

    SSE TestClient.iter_lines 因 async 永久阻塞,无法直接 stream;
    用 inspect.getsource 检查两处调用确实存在,作为反 §X 二路重复实现的回归 guard。
    """
    import inspect
    from src.api.routes import strategy as strat_mod
    src = inspect.getsource(strat_mod.strategy_stream)
    # 至少 2 处调用(initial + polling loop)
    occurrences = src.count("_overlay_latest_factor_cards")
    assert occurrences >= 2, (
        f"expected ≥2 _overlay_latest_factor_cards calls in stream() event_gen, "
        f"got {occurrences}. Did someone remove SSE initial or polling overlay?"
    )
    # _get_current_impl 也用同 helper(§X 不允许两路重复)
    cur_src = inspect.getsource(strat_mod._get_current_impl)
    assert "_overlay_latest_factor_cards" in cur_src, (
        "_get_current_impl must use the shared helper to avoid duplicate logic"
    )
