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
    # Sprint Layer-B Cleanup:cycle_position composite 卡删除,composite 5 个
    # (truth_trend / band_position / crowding / macro_headwind / event_risk)
    assert by_tier["composite"] == 5, "5 大组合因子(cycle_position 已删,Layer A 6 阶段替代)"
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


def test_composite_cards_all_five(minimal_state, minimal_context):
    """Sprint Layer-B Cleanup:composite 卡 6 个 → 5 个(删 cycle_position)。"""
    cards = emit_factor_cards(minimal_state, minimal_context)
    composite_ids = {c["card_id"] for c in cards if c["tier"] == "composite"}
    expected_suffixes = {
        "truth_trend", "band_position",
        "crowding", "macro_headwind", "event_risk",
    }
    # 每个 composite 卡的 id 形如 composite_{suffix}_{date}
    found = {
        s for s in expected_suffixes
        if any(f"composite_{s}_" in cid for cid in composite_ids)
    }
    assert found == expected_suffixes
    # cycle_position 卡必须不存在
    assert not any("composite_cycle_position" in cid for cid in composite_ids), \
        "cycle_position composite 卡应已删除(Sprint Layer-B Cleanup)"


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


# ============================================================
# Sprint Web Transparency: consumed_by_layers + linked_layer_simplified + advanced
# ============================================================

def test_consumed_by_layers_derive_layer_a_only():
    """consumed_by_layers=['Layer A'] → simplified='Layer A'"""
    from src.strategy.factor_card_emitter import _derive_simplified_label
    assert _derive_simplified_label(["Layer A"]) == "Layer A"


def test_consumed_by_layers_derive_layer_b_only():
    """consumed_by_layers 只含 L1-L5 → simplified='Layer B'"""
    from src.strategy.factor_card_emitter import _derive_simplified_label
    assert _derive_simplified_label(["L2"]) == "Layer B"
    assert _derive_simplified_label(["L4"]) == "Layer B"
    assert _derive_simplified_label(["L1", "L2", "L4"]) == "Layer B"


def test_consumed_by_layers_derive_both():
    """consumed_by_layers 含 Layer A + 任一 L1-L5 → simplified='Layer A / B'"""
    from src.strategy.factor_card_emitter import _derive_simplified_label
    assert _derive_simplified_label(["Layer A", "L2"]) == "Layer A / B"
    assert _derive_simplified_label(["Layer A", "L1", "L4"]) == "Layer A / B"


def test_consumed_by_layers_derive_empty():
    """空 list → '未使用'(死卡防御性 fallback)"""
    from src.strategy.factor_card_emitter import _derive_simplified_label
    assert _derive_simplified_label([]) == "未使用"


def test_make_card_with_consumed_by_layers():
    """_make_card 显式传 consumed_by_layers,output 含全部新字段。"""
    from src.strategy.factor_card_emitter import _make_card
    card = _make_card(
        card_id="test_x_20260519",
        category="onchain",
        tier="primary",
        name="测试卡",
        name_en="Test",
        linked_layer="Layer A",  # legacy field 仍存在
        source="test",
        consumed_by_layers=["Layer A", "L2"],
        advanced=True,
    )
    assert card["consumed_by_layers"] == ["Layer A", "L2"]
    assert card["linked_layer_simplified"] == "Layer A / B"
    assert card["advanced"] is True
    assert card["linked_layer"] == "Layer A"  # legacy 保留


def test_make_card_legacy_fallback_layer_a():
    """旧调用方不传 consumed_by_layers + linked_layer='Layer A' → 自动 ['Layer A']"""
    from src.strategy.factor_card_emitter import _make_card
    card = _make_card(
        card_id="test_y_20260519",
        category="onchain",
        tier="primary",
        name="Legacy",
        name_en="Legacy",
        linked_layer="Layer A",
        source="test",
    )
    assert card["consumed_by_layers"] == ["Layer A"]
    assert card["linked_layer_simplified"] == "Layer A"
    assert card["advanced"] is False


def test_make_card_legacy_fallback_layer_b():
    """旧调用方不传 consumed_by_layers + linked_layer='L2' → 自动 ['L2']"""
    from src.strategy.factor_card_emitter import _make_card
    card = _make_card(
        card_id="test_z_20260519",
        category="derivatives",
        tier="primary",
        name="Legacy B",
        name_en="LegacyB",
        linked_layer="L2",
        source="test",
    )
    assert card["consumed_by_layers"] == ["L2"]
    assert card["linked_layer_simplified"] == "Layer B"


def test_make_card_advanced_default_false():
    from src.strategy.factor_card_emitter import _make_card
    card = _make_card(
        card_id="test_default_20260519",
        category="onchain",
        tier="primary",
        name="DefaultAdv",
        name_en="DefaultAdv",
        linked_layer="L2",
        source="test",
    )
    assert card["advanced"] is False


# ============================================================
# Sprint Web Transparency Commit 2: override dict 生效验证
# ============================================================

def test_override_dict_mvrv_z_layer_a_only():
    """onchain_mvrv_z 在 override dict 中应映射 Layer A only。"""
    from src.strategy.factor_card_emitter import _consumed_by_layers_from_card_id
    assert _consumed_by_layers_from_card_id("onchain_mvrv_z_20260519") == ["Layer A"]


def test_override_dict_sth_realized_price_both_layers():
    """sth_realized_price 是 Layer A + Layer B L2 共用。"""
    from src.strategy.factor_card_emitter import _consumed_by_layers_from_card_id
    assert _consumed_by_layers_from_card_id("onchain_sth_realized_price_20260519") == ["Layer A", "L2"]


def test_override_dict_funding_rate_layer_b_only():
    """funding_rate 系列只在 Layer B L2/L4 消费。"""
    from src.strategy.factor_card_emitter import _consumed_by_layers_from_card_id
    assert _consumed_by_layers_from_card_id("derivatives_funding_rate_current_20260519") == ["L2", "L4"]
    assert _consumed_by_layers_from_card_id("derivatives_funding_rate_aggregated_20260519") == ["L4"]


def test_override_dict_events_layer_b_l5():
    """events_* 5 卡都是 L5 only(Layer A 不消费 events)。"""
    from src.strategy.factor_card_emitter import _consumed_by_layers_from_card_id
    assert _consumed_by_layers_from_card_id("event_cpi_next_20260519") == ["L5"]
    assert _consumed_by_layers_from_card_id("event_fomc_next_20260519") == ["L5"]


def test_override_dict_price_ma_200_layer_a_d4_correction():
    """D4 修正:price_ma_200 是 SMA-200d,映射 Layer A(不是 plan 里的 Layer B)。"""
    from src.strategy.factor_card_emitter import _consumed_by_layers_from_card_id
    assert _consumed_by_layers_from_card_id("price_ma_200_20260519") == ["Layer A"]


def test_override_dict_etf_flow_merged_both_layers():
    """derivatives_etf_flow 合并 7d/30d 显示,Layer A macro_flow_packet + Layer B L5 共用。"""
    from src.strategy.factor_card_emitter import _consumed_by_layers_from_card_id
    assert _consumed_by_layers_from_card_id("derivatives_etf_flow_20260519") == ["Layer A", "L5"]


def test_override_dict_dead_cards_not_in_dict():
    """死卡(Commit 3 将删 emit)不应在 override dict 中,返回 None → legacy fallback → 未使用。"""
    from src.strategy.factor_card_emitter import _consumed_by_layers_from_card_id
    for dead_base in [
        "derivatives_liquidation_24h", "derivatives_lsr_change_24h",
        "derivatives_top_long_short_ratio", "onchain_lth_mvrv",
        "onchain_sth_mvrv", "onchain_ssr",
        "price_ma_20", "price_ma_60", "price_ma_120",
        "price_tf_alignment_4h_1d_1w",
    ]:
        assert _consumed_by_layers_from_card_id(f"{dead_base}_20260519") is None


def test_emitter_makes_card_with_dict_override(minimal_state, minimal_context):
    """端到端:emit_factor_cards 产 mvrv_z 卡,通过 dict 自动注入 consumed_by_layers。"""
    cards = emit_factor_cards(minimal_state, minimal_context)
    mvrv_card = next((c for c in cards if c["card_id"].startswith("onchain_mvrv_z_")), None)
    assert mvrv_card is not None
    assert mvrv_card["consumed_by_layers"] == ["Layer A"]
    assert mvrv_card["linked_layer_simplified"] == "Layer A"


# ============================================================
# Sprint Web Transparency Commit 3: 10 张死卡删除验证
# ============================================================

def test_dead_cards_not_emitted(minimal_state, minimal_context):
    """删除的 10 张死卡不应再出现在 emit_factor_cards 输出。"""
    cards = emit_factor_cards(minimal_state, minimal_context)
    card_id_prefixes = {c["card_id"].rsplit("_", 1)[0] for c in cards}

    dead_prefixes = {
        "derivatives_liquidation_24h",
        "derivatives_lsr_change_24h",
        "derivatives_top_long_short_ratio",
        "onchain_lth_mvrv",
        "onchain_sth_mvrv",
        "onchain_ssr",
        "price_ma_20",
        "price_ma_60",
        "price_ma_120",
        "price_tf_alignment_4h_1d_1w",
    }
    leaked = card_id_prefixes & dead_prefixes
    assert not leaked, f"dead cards leaked into emit output: {leaked}"


def test_ma_200_card_still_emitted_and_layer_a(minimal_state, minimal_context):
    """price_ma_200 卡仍 emit,且 D4 修正后标 Layer A。"""
    import pandas as pd
    idx = pd.date_range("2024-01-01", periods=210, freq="D", tz="UTC")
    closes = [50000 + i * 100 for i in range(210)]
    df = pd.DataFrame({
        "open": closes, "high": closes, "low": closes, "close": closes,
        "volume_btc": [1.0] * 210,
    }, index=idx)
    ctx = {"onchain": {}, "derivatives": {}, "macro": {}, "klines_1d": df}
    cards = emit_factor_cards(minimal_state, ctx)
    ma200 = next((c for c in cards if c["card_id"].startswith("price_ma_200_")), None)
    assert ma200 is not None
    assert ma200["consumed_by_layers"] == ["Layer A"]
    assert ma200["linked_layer_simplified"] == "Layer A"
