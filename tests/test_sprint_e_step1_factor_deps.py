"""Sprint E Step 1 — factor_dependencies 单测。"""
from __future__ import annotations

import pytest

from src.data.freshness import EXPECTED_SOURCES
from src.strategy.factor_dependencies import (
    CARD_PREFIX_DEPENDENCIES,
    COMPOSITE_FACTOR_DEPENDENCIES,
    INDICATOR_DEPENDENCIES,
    LAYER_RELEVANT_INDICATORS,
    SRC_BINANCE_KLINE,
    SRC_COINGLASS_DERIV,
    SRC_FRED_MACRO,
    SRC_GLASSNODE_ONCHAIN,
    card_id_to_sources,
    factor_is_stale,
    fresh_ratio_for_layer,
    get_factor_freshness,
    get_layer_factor_freshness,
)


# ============================================================
# 1. 4 个 source 常量 = freshness EXPECTED_SOURCES 一致
# ============================================================

def test_source_constants_match_freshness_module():
    expected = {s for s, _ in EXPECTED_SOURCES}
    actual = {SRC_BINANCE_KLINE, SRC_COINGLASS_DERIV,
              SRC_GLASSNODE_ONCHAIN, SRC_FRED_MACRO}
    assert actual == expected, "factor_dependencies 的 4 个 source 必须与 freshness 模块对齐"


# ============================================================
# 2. 每个 indicator key 至少 1 个 source(不能空)
# ============================================================

def test_every_indicator_has_at_least_one_source():
    for key, sources in INDICATOR_DEPENDENCIES.items():
        assert len(sources) >= 1, f"{key} 无 source 依赖"
        for s in sources:
            assert s in (SRC_BINANCE_KLINE, SRC_COINGLASS_DERIV,
                         SRC_GLASSNODE_ONCHAIN, SRC_FRED_MACRO), (
                f"{key} 引用了未知 source {s}"
            )


# ============================================================
# 3. 5 个 composite factor 显式列出
# ============================================================

def test_all_5_composite_factors_present():
    """state_builder 跑的 5 个 composite + event_risk = 6 个。"""
    expected = {"truth_trend", "band_position", "cycle_position",
                "crowding", "macro_headwind", "event_risk"}
    assert set(COMPOSITE_FACTOR_DEPENDENCIES.keys()) == expected


def test_composite_cycle_position_depends_glassnode():
    assert COMPOSITE_FACTOR_DEPENDENCIES["cycle_position"] == (SRC_GLASSNODE_ONCHAIN,)


def test_composite_truth_trend_depends_binance_kline():
    assert COMPOSITE_FACTOR_DEPENDENCIES["truth_trend"] == (SRC_BINANCE_KLINE,)


# ============================================================
# 4. card_id_to_sources 前缀匹配
# ============================================================

@pytest.mark.parametrize("card_id, expected_src", [
    ("onchain_mvrv_z_20260508", (SRC_GLASSNODE_ONCHAIN,)),
    ("onchain_lth_supply_90d_change_20260508", (SRC_GLASSNODE_ONCHAIN,)),
    ("derivatives_funding_rate_z_20260508", (SRC_COINGLASS_DERIV,)),
    ("price_tech_ema_alignment_20260508", (SRC_BINANCE_KLINE,)),
    ("price_breakout_20260508", (SRC_BINANCE_KLINE,)),
    ("kline_1d_close_20260508", (SRC_BINANCE_KLINE,)),
    ("macro_dxy_20260508", (SRC_FRED_MACRO,)),
    ("events_calendar_72h", ()),
])
def test_card_id_to_sources_prefix(card_id, expected_src):
    assert card_id_to_sources(card_id) == expected_src


def test_composite_card_id_strips_date_suffix():
    """composite_truth_trend_20260508 → truth_trend → binance_kline。"""
    assert card_id_to_sources("composite_truth_trend_20260508") == (SRC_BINANCE_KLINE,)
    assert card_id_to_sources("composite_cycle_position_20260508") == (SRC_GLASSNODE_ONCHAIN,)
    assert card_id_to_sources("composite_event_risk_20260508") == ()


def test_card_id_to_sources_unknown_returns_empty():
    """未知前缀 / 未知 key 返 ()(默认 fresh,留下次手动补)。"""
    assert card_id_to_sources("unknown_zzz_20260508") == ()
    assert card_id_to_sources("") == ()


def test_card_id_to_sources_falls_back_to_indicator_keys():
    """裸 indicator key 也能解析(无前缀,直接表 lookup)。"""
    assert card_id_to_sources("adx_14_1d_current") == (SRC_BINANCE_KLINE,)
    assert card_id_to_sources("funding_rate_current") == (SRC_COINGLASS_DERIV,)
    assert card_id_to_sources("lth_mvrv") == (SRC_GLASSNODE_ONCHAIN,)


# ============================================================
# 5. factor_is_stale 逻辑
# ============================================================

def test_factor_is_stale_when_any_dep_stale():
    stale_map = {SRC_GLASSNODE_ONCHAIN: True, SRC_BINANCE_KLINE: False,
                 SRC_COINGLASS_DERIV: False, SRC_FRED_MACRO: False}
    assert factor_is_stale("onchain_mvrv_z_20260508", stale_map) is True
    assert factor_is_stale("kline_1d_close_20260508", stale_map) is False
    # composite cycle_position 依赖 glassnode → stale
    assert factor_is_stale("composite_cycle_position_20260508", stale_map) is True
    # composite truth_trend 依赖 binance_kline → fresh
    assert factor_is_stale("composite_truth_trend_20260508", stale_map) is False


def test_factor_is_stale_no_deps_returns_false():
    """events_calendar / unknown 因子无 deps → 默认 fresh。"""
    stale_map = {SRC_GLASSNODE_ONCHAIN: True}
    assert factor_is_stale("events_calendar_72h", stale_map) is False
    assert factor_is_stale("unknown_factor_xx", stale_map) is False


def test_factor_is_stale_indicator_key_path():
    """裸 indicator key 也能算 stale。"""
    stale_map = {SRC_FRED_MACRO: True}
    assert factor_is_stale("dxy_current", stale_map) is True
    assert factor_is_stale("adx_14_1d_current", stale_map) is False


# ============================================================
# 6. get_factor_freshness 批量
# ============================================================

def test_get_factor_freshness_batch():
    stale_map = {SRC_GLASSNODE_ONCHAIN: True, SRC_BINANCE_KLINE: False}
    out = get_factor_freshness([
        "onchain_mvrv_z_20260508",
        "kline_1d_close_20260508",
        "composite_cycle_position_20260508",
    ], stale_map)
    assert out == {
        "onchain_mvrv_z_20260508": True,
        "kline_1d_close_20260508": False,
        "composite_cycle_position_20260508": True,
    }


# ============================================================
# 7. LAYER_RELEVANT_INDICATORS 5 层(L3 留空 OK)
# ============================================================

def test_layer_relevant_indicators_covers_l1_l2_l4_l5():
    for lid in (1, 2, 4, 5):
        keys = LAYER_RELEVANT_INDICATORS[lid]
        assert len(keys) >= 1, f"L{lid} 无关心 indicator"
        for k in keys:
            assert k in INDICATOR_DEPENDENCIES, (
                f"L{lid} 引用了 INDICATOR_DEPENDENCIES 不存在的 key: {k}"
            )


def test_layer3_is_derivative_no_direct_indicators():
    """L3 机会执行衍生于 L1+L2,直接 indicators 列表为空(orchestrator
    依赖上游联动判定 health,不依赖本表)。"""
    assert LAYER_RELEVANT_INDICATORS[3] == ()


# ============================================================
# 8. get_layer_factor_freshness + fresh_ratio_for_layer
# ============================================================

def test_get_layer_factor_freshness_returns_per_indicator_status():
    stale_map = {SRC_GLASSNODE_ONCHAIN: True, SRC_BINANCE_KLINE: False,
                 SRC_COINGLASS_DERIV: False, SRC_FRED_MACRO: False}
    rows = get_layer_factor_freshness(2, stale_map)
    # L2 部分 indicator(LTH/STH/exchange_net_flow)依赖 glassnode → stale
    glassnode_keys = [r for r in rows if SRC_GLASSNODE_ONCHAIN in r[2]]
    binance_keys = [r for r in rows if SRC_BINANCE_KLINE in r[2]]
    assert len(glassnode_keys) >= 1
    assert all(r[1] is True for r in glassnode_keys)  # all stale
    assert len(binance_keys) >= 1
    assert all(r[1] is False for r in binance_keys)   # all fresh


def test_fresh_ratio_l2_partial_stale():
    """L2 = K线 indicators (fresh) + Glassnode indicators (stale)。"""
    stale_map = {SRC_GLASSNODE_ONCHAIN: True, SRC_BINANCE_KLINE: False,
                 SRC_COINGLASS_DERIV: False, SRC_FRED_MACRO: False}
    ratio = fresh_ratio_for_layer(2, stale_map)
    assert 0.0 < ratio < 1.0


def test_fresh_ratio_l1_all_binance_kline_fresh():
    stale_map = {SRC_BINANCE_KLINE: False, SRC_GLASSNODE_ONCHAIN: True,
                 SRC_COINGLASS_DERIV: False, SRC_FRED_MACRO: False}
    assert fresh_ratio_for_layer(1, stale_map) == 1.0


def test_fresh_ratio_l1_all_stale_when_kline_stale():
    stale_map = {SRC_BINANCE_KLINE: True, SRC_GLASSNODE_ONCHAIN: False,
                 SRC_COINGLASS_DERIV: False, SRC_FRED_MACRO: False}
    assert fresh_ratio_for_layer(1, stale_map) == 0.0


def test_fresh_ratio_l3_returns_1_no_direct_deps():
    """L3 衍生层无直接 indicator → fresh_ratio 默认 1.0(由 orchestrator
    据 L1/L2 health 联动)。"""
    stale_map = {s: True for s in (SRC_BINANCE_KLINE, SRC_COINGLASS_DERIV,
                                    SRC_GLASSNODE_ONCHAIN, SRC_FRED_MACRO)}
    assert fresh_ratio_for_layer(3, stale_map) == 1.0


def test_fresh_ratio_l4_glassnode_stale():
    """L4 部分 indicator 依赖 glassnode(exchange_net_flow_30d_sum 等)。"""
    stale_map = {SRC_COINGLASS_DERIV: False, SRC_GLASSNODE_ONCHAIN: True,
                 SRC_BINANCE_KLINE: False, SRC_FRED_MACRO: False}
    ratio = fresh_ratio_for_layer(4, stale_map)
    assert 0.0 < ratio < 1.0


def test_fresh_ratio_l5_all_fred_stale():
    stale_map = {SRC_FRED_MACRO: True, SRC_BINANCE_KLINE: False,
                 SRC_COINGLASS_DERIV: False, SRC_GLASSNODE_ONCHAIN: False}
    assert fresh_ratio_for_layer(5, stale_map) == 0.0
