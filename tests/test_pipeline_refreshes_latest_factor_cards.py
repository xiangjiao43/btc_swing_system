"""tests/test_pipeline_refreshes_latest_factor_cards.py — Sprint 1.5e.1。

§Z 真跑 builder.run + 真 SQLite + 真 LatestFactorCardsDAO,
断言每次 manual run 后 latest_factor_cards 单行表的 refreshed_at_utc / cards_json
反映本次 run 的真值(不是上次 cron 的旧快照)。
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.data.storage.connection import init_db
from src.data.storage.dao import LatestFactorCardsDAO
from src.pipeline import StrategyStateBuilder


def _row_conn(p: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture
def db_path():
    tmp = Path(tempfile.mkdtemp()) / "lfc_refresh.db"
    init_db(db_path=tmp, verbose=False)
    return tmp


def _ai_ok(*a, **kw):
    return {"status": "ok", "summary_text": "ok",
            "model_used": "test", "tokens_in": 10, "tokens_out": 10,
            "latency_ms": 1}


def test_pipeline_run_updates_latest_factor_cards(db_path):
    """跑一次 builder.run → latest_factor_cards 表应有数据(refreshed_at_utc 是 run_ts)。"""
    conn = _row_conn(db_path)
    try:
        builder = StrategyStateBuilder(
            conn, ai_caller=_ai_ok,
            preflight_sleep_fn=lambda s: None,
            preflight_retry_after_sec=0.0,
        )
        result = builder.run(run_trigger="manual")
        assert result.persisted is True

        out = LatestFactorCardsDAO.get_latest(conn)
        assert out is not None
        assert isinstance(out.get("cards"), list)
        # refreshed_at_utc 应是本次 run_timestamp_utc
        assert out["refreshed_at_utc"] == result.run_timestamp_utc
    finally:
        conn.close()


def test_two_runs_update_refreshed_at(db_path):
    """连跑两次 manual run → refreshed_at_utc 应该是第二次的 run_ts。"""
    import time
    conn = _row_conn(db_path)
    try:
        builder = StrategyStateBuilder(
            conn, ai_caller=_ai_ok,
            preflight_sleep_fn=lambda s: None,
            preflight_retry_after_sec=0.0,
        )
        r1 = builder.run(run_trigger="manual")
        time.sleep(1.1)  # 保证第二次 run_ts 与第一次不同(秒级精度)
        r2 = builder.run(run_trigger="manual")

        out = LatestFactorCardsDAO.get_latest(conn)
        # 应反映第二次 run 的时间
        assert out["refreshed_at_utc"] == r2.run_timestamp_utc
        assert out["refreshed_at_utc"] != r1.run_timestamp_utc
    finally:
        conn.close()
