"""tests/test_data_freshness_stamping.py — Sprint 2.6-G。

覆盖:
1. DataFetchLogDAO upsert + get_all 行为
2. state_builder._assemble_context 注入 data_freshness
3. emitter._stamp_fetched_at 按 group 把 fetched_at_bjt 写到每张卡
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from src.data.storage.dao import DataFetchLogDAO


@pytest.fixture
def in_memory_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE data_fetch_log (
            source             TEXT PRIMARY KEY,
            last_fetched_utc   TEXT NOT NULL,
            rows_upserted      INTEGER,
            notes              TEXT
        )
    """)
    conn.commit()
    yield conn
    conn.close()


# ============================================================
# DAO behavior
# ============================================================

def test_record_fetch_inserts_then_updates(in_memory_db):
    DataFetchLogDAO.record_fetch(
        in_memory_db, source="macro", rows_upserted=42,
        now_utc="2026-04-27T10:00:00Z",
    )
    out = DataFetchLogDAO.get_all(in_memory_db)
    assert out == {"macro": "2026-04-27T10:00:00Z"}

    DataFetchLogDAO.record_fetch(
        in_memory_db, source="macro", rows_upserted=50,
        now_utc="2026-04-27T11:00:00Z",
    )
    out = DataFetchLogDAO.get_all(in_memory_db)
    assert out == {"macro": "2026-04-27T11:00:00Z"}

    DataFetchLogDAO.record_fetch(
        in_memory_db, source="onchain", rows_upserted=9,
        now_utc="2026-04-27T11:05:00Z",
    )
    out = DataFetchLogDAO.get_all(in_memory_db)
    assert set(out) == {"macro", "onchain"}


def test_get_all_returns_empty_dict_when_table_empty(in_memory_db):
    assert DataFetchLogDAO.get_all(in_memory_db) == {}


def test_record_fetch_default_now_utc(in_memory_db):
    """不传 now_utc 时使用 _utc_now_iso (当下时间)。"""
    DataFetchLogDAO.record_fetch(in_memory_db, source="klines", rows_upserted=1)
    out = DataFetchLogDAO.get_all(in_memory_db)
    assert "klines" in out
    # ISO format check
    ts = out["klines"]
    parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None


# ============================================================
# Emitter stamping
# ============================================================

def _card(card_id: str, group: str, **extra) -> dict:
    return {
        "card_id": card_id, "group": group,
        "fetched_at_bjt": None, **extra,
    }


def test_stamp_fetched_at_maps_groups_to_sources():
    from src.strategy.factor_card_emitter import _stamp_fetched_at

    cards = [
        _card("a", "onchain"),
        _card("b", "derivatives"),
        _card("c", "price_technical"),
        _card("d", "macro"),
        _card("e", "events"),
        _card("f", "composite"),
    ]
    freshness = {
        "onchain":     "2026-04-27T10:00:00Z",
        "derivatives": "2026-04-27T10:01:00Z",
        "klines":      "2026-04-27T10:02:00Z",
        "macro":       "2026-04-27T10:03:00Z",
    }

    _stamp_fetched_at(cards, freshness)

    # 4 个 group 各自对应 source
    assert "BJT" in cards[0]["fetched_at_bjt"]    # onchain → onchain
    assert "BJT" in cards[1]["fetched_at_bjt"]    # derivatives → derivatives
    assert "BJT" in cards[2]["fetched_at_bjt"]    # price_technical → klines
    assert "BJT" in cards[3]["fetched_at_bjt"]    # macro → macro

    # events / composite 用 min(all 时间) = onchain 的 10:00:00Z = BJT 18:00
    assert "18:00" in cards[4]["fetched_at_bjt"]
    assert "18:00" in cards[5]["fetched_at_bjt"]


def test_stamp_fetched_at_empty_freshness_noop():
    from src.strategy.factor_card_emitter import _stamp_fetched_at

    cards = [_card("x", "onchain")]
    _stamp_fetched_at(cards, {})
    assert cards[0]["fetched_at_bjt"] is None


def test_stamp_fetched_at_skips_already_set():
    from src.strategy.factor_card_emitter import _stamp_fetched_at

    cards = [_card("x", "onchain", fetched_at_bjt="2026-04-27 12:00 (BJT)")]
    _stamp_fetched_at(cards, {"onchain": "2026-04-27T15:00:00Z"})
    # 已显式设过的不被覆盖
    assert cards[0]["fetched_at_bjt"] == "2026-04-27 12:00 (BJT)"


def test_stamp_fetched_at_unknown_group_falls_back_to_min():
    from src.strategy.factor_card_emitter import _stamp_fetched_at

    cards = [_card("x", "weirdgroup")]
    _stamp_fetched_at(cards, {"macro": "2026-04-27T10:00:00Z"})
    assert "BJT" in (cards[0]["fetched_at_bjt"] or "")


# ============================================================
# Make_card includes fetched_at_bjt field
# ============================================================

def test_make_card_includes_fetched_at_bjt_field():
    from src.strategy.factor_card_emitter import _make_card

    card = _make_card(
        card_id="t", category="onchain", tier="primary",
        name="X", name_en="X", linked_layer="L1", source="test",
    )
    assert "fetched_at_bjt" in card
    assert card["fetched_at_bjt"] is None
