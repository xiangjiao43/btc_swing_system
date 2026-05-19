"""tests/test_factor_card_naming_binance.py — Sprint 1.5e 卡名诚实标注 Binance。

§Z 4 张单交易所卡(funding / LSR / 24h liquidation / lsr 24h change)
name 含 "Binance",source = "CoinGlass (Binance)"。
聚合卡(funding_aggregated)source 仍 "CoinGlass" 不变。
"""

from __future__ import annotations

import pandas as pd
import pytest


def _make_derivatives() -> dict:
    rng = pd.date_range("2026-04-25", periods=60, freq="h", tz="UTC")
    return {
        "funding_rate": pd.Series([0.0001] * 60, index=rng),
        "long_short_ratio": pd.Series([1.5] * 60, index=rng),
        "liquidation_total": pd.Series([2_000_000.0] * 60, index=rng),
        "open_interest": pd.Series([5e10] * 60, index=rng),
        "funding_rate_aggregated": pd.Series([0.0001] * 60, index=rng),
    }


def _make_state() -> dict:
    return {
        "evidence_reports": {
            "layer_1": {"regime": "range_mid"},
            "layer_2": {"stance": "neutral", "phase": "n_a"},
        },
    }


def _emit_all_cards():
    from src.strategy.factor_card_emitter import emit_factor_cards
    return emit_factor_cards(
        _make_state(),
        {"derivatives": _make_derivatives(),
         "macro": {}, "onchain": {}},
    )


@pytest.fixture
def cards():
    return _emit_all_cards()


def _find(cards: list, fid_substr: str) -> dict | None:
    for c in cards:
        if fid_substr in (c.get("card_id") or ""):
            return c
    return None


# ============================================================
# 4 张单交易所卡:name 含 Binance,source 标 (Binance)
# ============================================================

def test_funding_rate_current_card_named_binance(cards):
    c = _find(cards, "derivatives_funding_rate_current")
    assert c is not None
    assert "Binance" in c["name"]
    assert "(Binance)" in c.get("source") or "Binance" in (c.get("source") or "")


# Sprint Web Transparency Commit 3 删除以下 3 个测试:
#   test_top_long_short_ratio_card_named_binance
#   test_liquidation_24h_card_named_binance
#   test_lsr_change_24h_card_named_binance
# 原因:对应 3 张卡是死卡(Layer A 排除衍生品,Layer B L4 prompt 不消费 LSR /
# liquidation),已从 emitter 删除。coinglass.py 数据采集保留。


# ============================================================
# 聚合卡:不带 Binance(全市场聚合,语义不同)
# ============================================================

def test_funding_aggregated_card_not_binance(cards):
    """全交易所加权 funding 是聚合端点,不应标 Binance。"""
    # card_id 大致是 derivatives_funding_rate_aggregated_{today}
    c = _find(cards, "derivatives_funding_rate_aggregated")
    if c is None:
        pytest.skip("aggregated funding card not present in this scenario")
    # source 不应该带 (Binance)
    assert "(Binance)" not in (c.get("source") or "")
    # name 也不应该带 Binance
    assert "Binance" not in (c.get("name") or "")
