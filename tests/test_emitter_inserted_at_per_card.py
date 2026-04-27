"""tests/test_emitter_inserted_at_per_card.py — Sprint 2.6-J Commit 3。

§Z 端到端:emit_factor_cards 后,每张卡的 fetched_at_bjt 真实反映该 metric
最近一次系统侧 wall clock 写入时间(秒级精度),而不是 group 级别共享。

用真 SQLite + 真 OnchainDAO + 真 emitter,断言 fetched_at_bjt 字段:
  1. 不同 onchain metric 对应不同的 inserted_at(微秒精度可区分)
  2. legacy 行 inserted_at_utc=NULL → 仍可降级(category-level max)
  3. composite 卡 fetched_at_bjt = max(所有 metric inserted_at)
  4. derivatives 用 snapshot 级单值
  5. price_structure 用 klines 1d
"""

from __future__ import annotations

import sqlite3
import tempfile
import time
from pathlib import Path

import pandas as pd
import pytest

from src.data.storage.connection import init_db
from src.data.storage.dao import (
    BTCKlinesDAO, DerivativeMetric, DerivativesDAO,
    KlineRow, MacroDAO, MacroMetric,
    OnchainDAO, OnchainMetric,
)
from src.strategy.factor_card_emitter import (
    _parse_metric_name_from_card_id,
    _stamp_fetched_at,
    _utc_iso_to_bjt_pretty,
)


@pytest.fixture
def db():
    tmp = Path(tempfile.mkdtemp()) / "j.db"
    init_db(db_path=tmp, verbose=False)
    conn = sqlite3.connect(tmp)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


# ============================================================
# _parse_metric_name_from_card_id
# ============================================================

def test_parse_card_id_direct_match():
    lookup = {"mvrv_z_score": "ts1", "nupl": "ts2"}
    assert _parse_metric_name_from_card_id(
        "onchain_mvrv_z_score_20260427",
        prefix="onchain_", today="20260427", lookup=lookup,
    ) == "mvrv_z_score"


def test_parse_card_id_with_derived_suffix():
    lookup = {"us10y": "ts1", "dxy": "ts2"}
    assert _parse_metric_name_from_card_id(
        "macro_us10y_30d_change_20260427",
        prefix="macro_", today="20260427", lookup=lookup,
    ) == "us10y"
    assert _parse_metric_name_from_card_id(
        "macro_dxy_20d_change_20260427",
        prefix="macro_", today="20260427", lookup=lookup,
    ) == "dxy"


def test_parse_card_id_no_match_returns_none():
    lookup = {"mvrv_z_score": "ts1"}
    assert _parse_metric_name_from_card_id(
        "onchain_btc_drawdown_from_ath_20260427",
        prefix="onchain_", today="20260427", lookup=lookup,
    ) is None


# ============================================================
# Per-category stamping
# ============================================================

def _card(card_id: str, category: str, **extra) -> dict:
    return {
        "card_id": card_id, "category": category,
        "fetched_at_bjt": None, **extra,
    }


def test_onchain_card_gets_per_metric_inserted_at():
    cards = [
        _card("onchain_mvrv_z_score_20260427", "onchain"),
        _card("onchain_nupl_20260427", "onchain"),
    ]
    metric_inserted_at = {
        "onchain": {
            "mvrv_z_score": "2026-04-27T14:06:23.111111Z",
            "nupl":         "2026-04-27T14:06:24.555555Z",
        },
        "macro": {}, "klines_by_tf": {}, "derivatives_snapshot": None,
    }
    _stamp_fetched_at(cards, metric_inserted_at, today="20260427")

    # 两张卡的时间不同(per-metric 精度生效)
    assert cards[0]["fetched_at_bjt"] != cards[1]["fetched_at_bjt"]
    # 14:06:23 UTC = 22:06:23 BJT;14:06:24 UTC = 22:06:24 BJT
    assert "22:06:23" in cards[0]["fetched_at_bjt"]
    assert "22:06:24" in cards[1]["fetched_at_bjt"]


def test_macro_card_gets_per_metric_inserted_at():
    cards = [_card("macro_us10y_30d_change_20260427", "macro")]
    metric_inserted_at = {
        "onchain": {}, "klines_by_tf": {}, "derivatives_snapshot": None,
        "macro": {"us10y": "2026-04-27T14:06:23Z", "dxy": "2026-04-27T14:06:25Z"},
    }
    _stamp_fetched_at(cards, metric_inserted_at, today="20260427")
    # 解析 "macro_us10y_30d_change_TODAY" → strip prefix/today → "us10y_30d_change"
    # → strip "_30d_change" 后缀 → "us10y" → 命中 lookup
    # 14:06:23 UTC = 22:06:23 BJT
    assert "22:06:23" in cards[0]["fetched_at_bjt"]


def test_derivatives_card_uses_snapshot_level():
    cards = [
        _card("derivatives_funding_rate_24h_20260427", "derivatives"),
        _card("derivatives_oi_current_20260427", "derivatives"),
    ]
    metric_inserted_at = {
        "onchain": {}, "macro": {}, "klines_by_tf": {},
        "derivatives_snapshot": "2026-04-27T15:00:00Z",
    }
    _stamp_fetched_at(cards, metric_inserted_at, today="20260427")
    # snapshot 级共享(wide 表固有限制)
    assert cards[0]["fetched_at_bjt"] == cards[1]["fetched_at_bjt"]
    assert "23:00:00" in cards[0]["fetched_at_bjt"]  # 15 UTC = 23 BJT


def test_price_structure_card_uses_klines_1d():
    cards = [_card("price_adx_14_1d_20260427", "price_structure")]
    metric_inserted_at = {
        "onchain": {}, "macro": {}, "derivatives_snapshot": None,
        "klines_by_tf": {
            "1d": "2026-04-27T16:00:00Z",
            "1h": "2026-04-27T17:00:00Z",  # 即便 1h 更新但 ADX 是 1d 卡,用 1d 时间
        },
    }
    _stamp_fetched_at(cards, metric_inserted_at, today="20260427")
    assert "00:00:00" in cards[0]["fetched_at_bjt"]  # 16 UTC = 24:00 BJT(00:00 次日)


def test_composite_card_uses_max_of_all():
    cards = [_card("composite_macro_headwind_20260427", "composite")]
    metric_inserted_at = {
        "onchain": {"a": "2026-04-27T10:00:00Z"},
        "macro":   {"b": "2026-04-27T15:30:00Z"},  # 最大
        "klines_by_tf": {"1d": "2026-04-27T11:00:00Z"},
        "derivatives_snapshot": "2026-04-27T12:00:00Z",
    }
    _stamp_fetched_at(cards, metric_inserted_at, today="20260427")
    # max = 15:30 UTC = 23:30 BJT
    assert "23:30:00" in cards[0]["fetched_at_bjt"]


def test_legacy_null_inserted_at_falls_back_to_none():
    """所有 metric 的 inserted_at 都是 None(legacy 行)→ fetched_at_bjt 保留 None,
    前端会降级到 captured_at_bjt 显示。"""
    cards = [_card("onchain_mvrv_z_score_20260427", "onchain")]
    metric_inserted_at = {
        "onchain": {"mvrv_z_score": None},
        "macro": {}, "klines_by_tf": {}, "derivatives_snapshot": None,
    }
    _stamp_fetched_at(cards, metric_inserted_at, today="20260427")
    assert cards[0]["fetched_at_bjt"] is None


def test_events_card_not_stamped():
    cards = [_card("event_fomc_next_20260427", "events")]
    metric_inserted_at = {
        "onchain": {"a": "2026-04-27T10:00:00Z"},
        "macro": {}, "klines_by_tf": {}, "derivatives_snapshot": None,
    }
    _stamp_fetched_at(cards, metric_inserted_at, today="20260427")
    assert cards[0]["fetched_at_bjt"] is None  # events 不盖


# ============================================================
# Format precision (秒级)
# ============================================================

def test_utc_iso_to_bjt_pretty_includes_seconds():
    out = _utc_iso_to_bjt_pretty("2026-04-27T14:06:23.456789Z")
    assert out is not None
    # 必须含 ":SS" 而不是仅 "HH:MM"
    assert "14:06:23" in out or "22:06:23" in out  # depends on TZ math
    # BJT = UTC+8 → 14:06:23 UTC = 22:06:23 BJT
    assert "22:06:23" in out
    assert "(BJT)" in out


def test_utc_iso_to_bjt_pretty_handles_no_microseconds():
    out = _utc_iso_to_bjt_pretty("2026-04-27T14:06:23Z")
    assert "22:06:23" in out


def test_utc_iso_to_bjt_pretty_handles_garbage():
    assert _utc_iso_to_bjt_pretty("not a date") is None


# ============================================================
# End-to-end: real DAO + microsecond-precision distinction
# ============================================================

def test_e2e_two_onchain_metrics_fetched_seconds_apart_show_distinct_times(db):
    OnchainDAO.upsert_batch(db, [
        OnchainMetric(timestamp="2026-04-27T00:00:00Z",
                      metric_name="metric_a", metric_value=1.0,
                      source="glassnode_primary"),
    ])
    db.commit()
    # >= 1 秒的差距以保证秒级显示也能区分(用户实际场景:几秒/几分钟差异)
    time.sleep(1.05)
    OnchainDAO.upsert_batch(db, [
        OnchainMetric(timestamp="2026-04-27T00:00:00Z",
                      metric_name="metric_b", metric_value=2.0,
                      source="glassnode_primary"),
    ])
    db.commit()

    onchain_map = OnchainDAO.get_metric_inserted_at_map(db)
    assert onchain_map["metric_a"] is not None
    assert onchain_map["metric_b"] is not None
    assert onchain_map["metric_a"] < onchain_map["metric_b"]

    # 通过 emitter 走一遍
    cards = [
        _card("onchain_metric_a_20260427", "onchain"),
        _card("onchain_metric_b_20260427", "onchain"),
    ]
    _stamp_fetched_at(
        cards,
        {"onchain": onchain_map, "macro": {},
         "klines_by_tf": {}, "derivatives_snapshot": None},
        today="20260427",
    )
    assert cards[0]["fetched_at_bjt"] != cards[1]["fetched_at_bjt"], (
        f"两张卡显示一致时间(per-metric 精度失效):\n"
        f"  card_a={cards[0]['fetched_at_bjt']}\n"
        f"  card_b={cards[1]['fetched_at_bjt']}"
    )
