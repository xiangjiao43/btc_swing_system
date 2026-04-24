"""
tests/test_factor_card_emitter.py — Sprint 2.2 Task B:
全量数据因子 emitter 产出 ≥ 35 张卡 + tier 分档 + 容错。
"""

from __future__ import annotations

from collections import Counter

import pandas as pd
import pytest

from src.strategy.factor_card_emitter import emit_factor_cards


@pytest.fixture
def minimal_state() -> dict:
    return {
        "composite_factors": {
            "truth_trend": {"score": 5, "band": "weak"},
            "band_position": {"phase": "mid", "phase_confidence": 0.6},
            "cycle_position": {"cycle_position": "mid_bull"},
            "crowding": {"score": 3, "band": "normal"},
            "macro_headwind": {"score": -1, "band": "neutral"},
            "event_risk": {"score": 2, "band": "low"},
        },
        "evidence_reports": {"layer_1": {}},
    }


@pytest.fixture
def minimal_context() -> dict:
    return {"onchain": {}, "derivatives": {}, "macro": {}}


def test_emits_at_least_35_cards(minimal_state, minimal_context):
    cards = emit_factor_cards(minimal_state, minimal_context)
    assert len(cards) >= 35, f"expected ≥ 35 cards, got {len(cards)}"


def test_tier_breakdown(minimal_state, minimal_context):
    cards = emit_factor_cards(minimal_state, minimal_context)
    by_tier = Counter(c["tier"] for c in cards)
    assert by_tier["composite"] == 6, "六大组合因子必须齐全"
    assert by_tier["primary"] >= 13, "主裁决因子 ≥ 13(含 5 链上 + 4 衍生品 + 3 技术 + 2 宏观)"
    assert by_tier["reference"] >= 15, "参考因子 ≥ 15"


def test_all_categories_present(minimal_state, minimal_context):
    cards = emit_factor_cards(minimal_state, minimal_context)
    categories = {c["category"] for c in cards}
    assert {"price_structure", "onchain", "derivatives",
            "macro", "events"} <= categories


def test_cards_have_required_fields(minimal_state, minimal_context):
    cards = emit_factor_cards(minimal_state, minimal_context)
    required = {
        "card_id", "category", "tier", "name", "name_en",
        "current_value", "captured_at_bjt", "data_fresh",
        "plain_interpretation", "strategy_impact",
        "impact_direction", "linked_layer", "source",
    }
    for c in cards:
        missing = required - c.keys()
        assert not missing, f"{c['card_id']} missing: {missing}"


def test_card_id_naming_pattern(minimal_state, minimal_context):
    """§6.7:{category}_{metric_name}_{bjt_date};metric_name 可含数字。"""
    cards = emit_factor_cards(minimal_state, minimal_context)
    import re
    pat = re.compile(r"^[a-z][a-z0-9_]+_\d{8}$")
    for c in cards:
        assert pat.match(c["card_id"]), f"bad card_id: {c['card_id']}"


def test_missing_data_graceful(minimal_state, minimal_context):
    """空 context → 每卡产出,值为 None,plain_interpretation 提示数据不足。"""
    cards = emit_factor_cards(minimal_state, minimal_context)
    reference_cards = [c for c in cards if c["tier"] == "reference"]
    # reference 卡中大部分数据源为空时应给出"数据不足"提示
    insufficient = [c for c in reference_cards if "数据不足" in c["plain_interpretation"]]
    assert len(insufficient) >= 5


def test_composite_cards_all_six(minimal_state, minimal_context):
    cards = emit_factor_cards(minimal_state, minimal_context)
    composite_ids = {c["card_id"] for c in cards if c["tier"] == "composite"}
    expected_suffixes = {
        "truth_trend", "band_position", "cycle_position",
        "crowding", "macro_headwind", "event_risk",
    }
    # 每个 composite 卡的 id 形如 composite_{suffix}_{date}
    found = {
        s for s in expected_suffixes
        if any(f"composite_{s}_" in cid for cid in composite_ids)
    }
    assert found == expected_suffixes


def test_with_real_onchain_series():
    """给一个 10 天 mvrv_z 时间序列,能正确抽最新值 + 分位。"""
    idx = pd.date_range("2026-04-10", periods=10, freq="D", tz="UTC")
    mvrv = pd.Series([1.0, 1.2, 1.5, 1.8, 2.0, 2.1, 2.3, 2.4, 2.5, 2.5], index=idx)
    state = {
        "composite_factors": {"cycle_position": {"cycle_position": "mid_bull"}},
        "evidence_reports": {"layer_1": {}},
    }
    context = {"onchain": {"mvrv_z_score": mvrv}, "derivatives": {}, "macro": {}}
    cards = emit_factor_cards(state, context)
    mvrv_card = next(c for c in cards if c["card_id"].startswith("onchain_mvrv_z_"))
    assert mvrv_card["current_value"] == 2.5
    # 最新值 2.5 = 全序列最大 → 分位 100
    assert mvrv_card["historical_percentile"] == 100.0
    # 2.5 > 2 → 偏分发期,方向 bearish
    assert mvrv_card["impact_direction"] == "bearish"


def test_drawdown_from_ath_computed():
    idx = pd.date_range("2026-04-01", periods=30, freq="D", tz="UTC")
    closes = [100_000] * 10 + [80_000] * 20  # ATH=100k, current=80k → -20%
    highs = [c * 1.01 for c in closes]
    lows = [c * 0.99 for c in closes]
    df = pd.DataFrame({
        "open": closes, "high": highs, "low": lows, "close": closes,
        "volume_btc": [1.0] * 30,
    }, index=idx)
    state = {
        "composite_factors": {"cycle_position": {"cycle_position": "late_bull"}},
        "evidence_reports": {"layer_1": {}},
    }
    context = {"onchain": {}, "derivatives": {}, "macro": {}, "klines_1d": df}
    cards = emit_factor_cards(state, context)
    dd_card = next(c for c in cards if c["card_id"].startswith("price_drawdown_from_ath_"))
    assert dd_card["current_value"] is not None
    assert dd_card["current_value"] < -15
