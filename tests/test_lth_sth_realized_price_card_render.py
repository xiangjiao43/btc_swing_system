"""tests/test_lth_sth_realized_price_card_render.py — Sprint 2.6-I Commit 3.

Verify the existing factor_card_emitter cards (which were never deleted —
Sprint 2.6-F.3 only removed the collector + wiring) auto-revive once
OnchainDAO has lth_realized_price / sth_realized_price rows.

End-to-end: real SQLite + real OnchainDAO + real factor_card_emitter,
no mocks. Inserts metric rows, runs DAO + emitter pipeline, asserts:
  - card_id ∈ generated card list
  - current_value not None
  - linked_layer = L2 (cohort cost basis is a L2 directional input)
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.data.storage.connection import get_connection, init_db
from src.data.storage.dao import OnchainDAO, OnchainMetric
from src.strategy.factor_card_emitter import _emit_onchain_reference


@pytest.fixture
def db_with_lth_sth_rows():
    tmp = Path(tempfile.mkdtemp()) / "card.db"
    init_db(db_path=tmp, verbose=False)
    conn = get_connection(tmp)
    # Seed 30 days of synthetic rows
    rows = []
    for d in range(30):
        ts = f"2026-04-{d+1:02d}T00:00:00Z" if d < 30 else None
        # mar 30+1 wraps via simple ISO; just use Apr / 30 days
        ts = f"2026-04-{(d % 30) + 1:02d}T00:00:00Z"
        rows.append(OnchainMetric(
            timestamp=ts, metric_name="lth_realized_price",
            metric_value=42000.0 + d * 50,
            source="glassnode_derived_breakdown_by_age",
        ))
        rows.append(OnchainMetric(
            timestamp=ts, metric_name="sth_realized_price",
            metric_value=78000.0 + d * 80,
            source="glassnode_derived_breakdown_by_age",
        ))
    OnchainDAO.upsert_batch(conn, rows)
    conn.commit()
    yield conn
    conn.close()


def test_lth_sth_cards_render_when_data_present(db_with_lth_sth_rows):
    onchain = OnchainDAO.get_all_metrics(db_with_lth_sth_rows)
    assert "lth_realized_price" in onchain
    assert "sth_realized_price" in onchain

    today = "20260427"
    cards = _emit_onchain_reference(onchain, today)
    by_id = {c["card_id"]: c for c in cards}

    lth = by_id.get(f"onchain_lth_realized_price_{today}")
    sth = by_id.get(f"onchain_sth_realized_price_{today}")
    assert lth is not None, "LTH realized price card missing from emitter output"
    assert sth is not None, "STH realized price card missing from emitter output"

    # current_value must be non-None and equal latest seeded value
    assert lth["current_value"] is not None
    assert sth["current_value"] is not None
    # Latest seeded ts is 2026-04-30 → d = 29 → lth = 42000 + 29*50 = 43450
    assert lth["current_value"] == pytest.approx(43450.0)
    assert sth["current_value"] == pytest.approx(80320.0)

    # Card schema sanity
    assert lth["category"] == "onchain"
    assert lth["tier"] == "reference"
    assert lth["linked_layer"] == "L2"
    assert "LTH" in (lth.get("name") or "")
    assert "STH" in (sth.get("name") or "")


def test_lth_sth_cards_render_with_none_when_data_missing():
    """无数据时卡仍生成,只是 current_value=None(冷启动期友好)。"""
    cards = _emit_onchain_reference({}, "20260427")
    by_id = {c["card_id"]: c for c in cards}
    lth = by_id.get("onchain_lth_realized_price_20260427")
    sth = by_id.get("onchain_sth_realized_price_20260427")
    assert lth is not None
    assert sth is not None
    assert lth["current_value"] is None
    assert sth["current_value"] is None
