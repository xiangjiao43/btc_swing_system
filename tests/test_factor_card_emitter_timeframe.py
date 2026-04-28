"""tests/test_factor_card_emitter_timeframe.py — Sprint 2.8-E。

§Z 端到端:
- _resolve_price_structure_timeframe 把 8 个 price_structure 卡映射到对的 tf
- _stamp_fetched_at 用真实的 1h vs 1d inserted_at 给同一批卡盖不同 fetched_at_bjt
- 用户验收的语义:
    1h 衍生卡(drawdown / tf_alignment) → fetched_at_bjt = 1h inserted_at(BJT)
    1d 衍生卡(MA / ADX / ATR-180d)    → fetched_at_bjt = 1d inserted_at(BJT)
"""

from __future__ import annotations

import pytest

from src.strategy.factor_card_emitter import (
    _resolve_price_structure_timeframe,
    _stamp_fetched_at,
)


# ============================================================
# resolver 直测:每张 price_structure 卡都能命中正确 tf
# ============================================================

@pytest.mark.parametrize("card_id, expected_tf", [
    # 1h 衍生
    ("price_drawdown_from_ath_20260428",       "1h"),
    ("price_tf_alignment_4h_1d_1w_20260428",   "1h"),
    # 1d 衍生
    ("price_adx_14_1d_20260428",               "1d"),
    ("price_atr_percentile_180d_20260428",     "1d"),
    ("price_ma_20_20260428",                   "1d"),
    ("price_ma_60_20260428",                   "1d"),
    ("price_ma_120_20260428",                  "1d"),
    ("price_ma_200_20260428",                  "1d"),
])
def test_resolver_maps_known_price_cards(card_id, expected_tf):
    assert _resolve_price_structure_timeframe(card_id) == expected_tf


def test_resolver_default_falls_to_1d_for_unknown():
    """未知 card_id → 默认 1d(legacy fallback 在 stamp 层兜底)。"""
    assert _resolve_price_structure_timeframe("price_unknown_thing_20260428") == "1d"
    assert _resolve_price_structure_timeframe("") == "1d"


# ============================================================
# _stamp_fetched_at:1h 卡和 1d 卡时间不再共用
# ============================================================

@pytest.fixture
def two_tf_inserted_at():
    """构造一份 metric_inserted_at:1h 是新数据,1d 是 4 天前的旧数据。"""
    return {
        "klines_by_tf": {
            "1h": "2026-04-28T09:00:01Z",   # 17:00:01 BJT
            "1d": "2026-04-24T05:38:33Z",   # 4-24 13:38:33 BJT(stale)
        },
        "onchain": {}, "macro": {},
        "derivatives_snapshot": None,
    }


def _make_price_card(card_id: str) -> dict:
    return {
        "card_id": card_id,
        "category": "price_structure",
        "fetched_at_bjt": None,
    }


def test_drawdown_from_ath_uses_1h(two_tf_inserted_at):
    cards = [_make_price_card("price_drawdown_from_ath_20260428")]
    _stamp_fetched_at(cards, two_tf_inserted_at, today="20260428")
    assert cards[0]["fetched_at_bjt"] == "2026-04-28 17:00:01 (BJT)"


def test_tf_alignment_uses_1h(two_tf_inserted_at):
    cards = [_make_price_card("price_tf_alignment_4h_1d_1w_20260428")]
    _stamp_fetched_at(cards, two_tf_inserted_at, today="20260428")
    assert cards[0]["fetched_at_bjt"] == "2026-04-28 17:00:01 (BJT)"


def test_ma_20_uses_1d(two_tf_inserted_at):
    cards = [_make_price_card("price_ma_20_20260428")]
    _stamp_fetched_at(cards, two_tf_inserted_at, today="20260428")
    assert cards[0]["fetched_at_bjt"] == "2026-04-24 13:38:33 (BJT)"


def test_ma_200_uses_1d(two_tf_inserted_at):
    cards = [_make_price_card("price_ma_200_20260428")]
    _stamp_fetched_at(cards, two_tf_inserted_at, today="20260428")
    assert cards[0]["fetched_at_bjt"] == "2026-04-24 13:38:33 (BJT)"


def test_adx_14_uses_1d(two_tf_inserted_at):
    cards = [_make_price_card("price_adx_14_1d_20260428")]
    _stamp_fetched_at(cards, two_tf_inserted_at, today="20260428")
    assert cards[0]["fetched_at_bjt"] == "2026-04-24 13:38:33 (BJT)"


def test_atr_180_uses_1d(two_tf_inserted_at):
    cards = [_make_price_card("price_atr_percentile_180d_20260428")]
    _stamp_fetched_at(cards, two_tf_inserted_at, today="20260428")
    assert cards[0]["fetched_at_bjt"] == "2026-04-24 13:38:33 (BJT)"


def test_full_set_distinguishes_1h_vs_1d(two_tf_inserted_at):
    """一次性 8 张原始 price 卡:1h 组和 1d 组得到不同 fetched_at_bjt。"""
    one_hour_cards = [
        _make_price_card("price_drawdown_from_ath_20260428"),
        _make_price_card("price_tf_alignment_4h_1d_1w_20260428"),
    ]
    one_day_cards = [
        _make_price_card("price_adx_14_1d_20260428"),
        _make_price_card("price_atr_percentile_180d_20260428"),
        _make_price_card("price_ma_20_20260428"),
        _make_price_card("price_ma_60_20260428"),
        _make_price_card("price_ma_120_20260428"),
        _make_price_card("price_ma_200_20260428"),
    ]
    cards = one_hour_cards + one_day_cards
    _stamp_fetched_at(cards, two_tf_inserted_at, today="20260428")
    for c in one_hour_cards:
        assert c["fetched_at_bjt"] == "2026-04-28 17:00:01 (BJT)", c
    for c in one_day_cards:
        assert c["fetched_at_bjt"] == "2026-04-24 13:38:33 (BJT)", c


# ============================================================
# Legacy fallback:某 tf 缺失时退回 1d→4h→1h→1w
# ============================================================

def test_falls_back_to_1d_when_target_tf_missing():
    """1h cron 还没跑(klines_by_tf['1h'] = None)→ drawdown 卡退回 1d。"""
    inserted = {
        "klines_by_tf": {
            "1h": None,
            "1d": "2026-04-28T00:01:00Z",  # 08:01 BJT
        },
        "onchain": {}, "macro": {}, "derivatives_snapshot": None,
    }
    cards = [_make_price_card("price_drawdown_from_ath_20260428")]
    _stamp_fetched_at(cards, inserted, today="20260428")
    assert cards[0]["fetched_at_bjt"] == "2026-04-28 08:01:00 (BJT)"


def test_falls_back_to_1h_when_1d_4h_missing():
    """1d / 4h 都没,只剩 1h → MA 卡退到 1h。"""
    inserted = {
        "klines_by_tf": {
            "1h": "2026-04-28T09:00:00Z",
            "1d": None, "4h": None,
        },
        "onchain": {}, "macro": {}, "derivatives_snapshot": None,
    }
    cards = [_make_price_card("price_ma_20_20260428")]
    _stamp_fetched_at(cards, inserted, today="20260428")
    assert cards[0]["fetched_at_bjt"] == "2026-04-28 17:00:00 (BJT)"


def test_no_klines_at_all_keeps_fetched_at_none():
    """完全没数据 → fetched_at_bjt 保留 None,前端走 captured_at fallback。"""
    inserted = {
        "klines_by_tf": {}, "onchain": {}, "macro": {},
        "derivatives_snapshot": None,
    }
    cards = [_make_price_card("price_ma_20_20260428")]
    _stamp_fetched_at(cards, inserted, today="20260428")
    assert cards[0].get("fetched_at_bjt") is None
