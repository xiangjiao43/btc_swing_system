"""tests/test_factor_picker.py — Sprint 1.5m Task A。

factor_picker.pick_key_factors 必须:
- 从 factor_cards / composite_factors 中按规则化打分挑出 top-N
- 极端分位 / 触发阈值 / 大幅 24h 变动得高分
- 全部中性时仍给 3 个基础市场快照(不返回空)
- scenario hint 调整排序但不强行覆盖
"""

from __future__ import annotations

from src.strategy.factor_picker import pick_key_factors


def _state_with_extreme_funding() -> dict:
    return {
        "factor_cards": [
            {
                "card_id": "derivatives_funding_30d_pct",
                "category": "derivatives",
                "name": "资金费率 · 30 日分位",
                "current_value": 11.0,
                "value_unit": "",
            },
            {
                "card_id": "derivatives_funding_now",
                "category": "derivatives",
                "name": "Binance 资金费率 · 当前",
                "current_value": -0.4085,
                "value_unit": "%",
            },
            {
                "card_id": "structure_btc_price",
                "category": "price_structure",
                "name": "BTC 现价",
                "current_value": 75700.0,
                "value_unit": "USDT",
            },
        ],
    }


def _state_with_lsr_24h_change() -> dict:
    return {
        "factor_cards": [
            {
                "card_id": "deriv_lsr_24h",
                "category": "derivatives",
                "name": "Binance 多空比 24h 变化",
                "current_value": 13.68,
                "value_unit": "%",
            },
            {
                "card_id": "deriv_lsr_now",
                "category": "derivatives",
                "name": "Binance 大户多空比",
                "current_value": 1.08,
                "value_unit": "",
            },
        ],
    }


def _state_all_neutral() -> dict:
    """全部因子中性,picker 应仍返回 baseline 市场快照。"""
    return {
        "factor_cards": [
            {
                "card_id": "structure_btc_price",
                "category": "price_structure",
                "name": "BTC 现价",
                "current_value": 75700.0,
                "value_unit": "USDT",
            },
            {
                "card_id": "deriv_funding_now",
                "category": "derivatives",
                "name": "Binance 资金费率 · 当前",
                "current_value": 0.01,  # 中性
                "value_unit": "%",
            },
        ],
        "composite_factors": {
            "cycle_position": {"cycle_position": "mid_bull",
                               "cycle_confidence": 0.5},
            "crowding": {"crowding_level": "normal", "crowding_score": 4},
            "macro_headwind": {"macro_headwind_level": "neutral",
                               "headwind_score": 0},
        },
    }


def _state_with_high_crowding() -> dict:
    return {
        "factor_cards": [],
        "composite_factors": {
            "crowding": {"crowding_level": "high", "crowding_score": 11},
            "event_risk": {"event_risk_level": "high",
                           "event_risk_score": 11.5},
            "macro_headwind": {"macro_headwind_level": "mild",
                               "headwind_score": -2},
            "cycle_position": {"cycle_position": "mid_bull"},
        },
    }


# ============================================================
# 极端因子
# ============================================================

def test_picks_extreme_funding_30d_percentile():
    """funding 30d 分位 11 → signal ≥ 80,排第 1 或 2(BTC 现价是 baseline)。"""
    out = pick_key_factors(_state_with_extreme_funding(), n=5)
    names = [c["name"] for c in out]
    assert "资金费率 · 30 日分位" in names
    funding_pct = next(c for c in out if c["name"] == "资金费率 · 30 日分位")
    assert funding_pct["signal_strength"] >= 80
    assert "11" in funding_pct["interpretation"]


def test_picks_extreme_funding_current():
    """Binance 资金费率 · 当前 -0.4085% → signal ≥ 80。"""
    out = pick_key_factors(_state_with_extreme_funding(), n=5)
    names = [c["name"] for c in out]
    assert "Binance 资金费率 · 当前" in names
    fnow = next(c for c in out if c["name"] == "Binance 资金费率 · 当前")
    assert fnow["signal_strength"] >= 80


def test_picks_lsr_24h_change():
    """LSR 24h +13.68% → signal ≥ 85(剧烈变化)。"""
    out = pick_key_factors(_state_with_lsr_24h_change(), n=5)
    names = [c["name"] for c in out]
    assert "Binance 多空比 24h 变化" in names
    lsr = next(c for c in out if c["name"] == "Binance 多空比 24h 变化")
    assert lsr["signal_strength"] >= 85
    assert "13" in lsr["interpretation"] or "+13" in lsr["interpretation"]


# ============================================================
# 兜底:全中性时仍返回 baseline
# ============================================================

def test_no_extreme_returns_baseline():
    out = pick_key_factors(_state_all_neutral(), n=5)
    assert len(out) >= 3
    names = [c["name"] for c in out]
    # baseline 包含 BTC 现价 + 至少 1-2 个 composite
    assert "BTC 现价" in names
    # cycle_position / crowding / macro_headwind 至少一个出现
    assert any(n in ("cycle_position", "crowding", "macro_headwind")
               for n in names)


def test_empty_state_returns_empty_list():
    """没有任何 factor_cards / composite_factors → 不抛错,返回空。"""
    out = pick_key_factors({}, n=5)
    assert out == []


# ============================================================
# 数量
# ============================================================

def test_returns_n_items_when_enough():
    out = pick_key_factors(_state_with_extreme_funding(), n=2)
    assert len(out) == 2


def test_returns_all_when_fewer_than_n():
    out = pick_key_factors(_state_with_lsr_24h_change(), n=10)
    # state 里只有 2 个 cards,即使 n=10 也最多 2 个
    assert len(out) <= 2


def test_sorted_by_signal_strength_desc():
    """返回必须按 signal_strength 降序。"""
    out = pick_key_factors(_state_with_extreme_funding(), n=5)
    sigs = [c["signal_strength"] for c in out]
    assert sigs == sorted(sigs, reverse=True)


# ============================================================
# 组合因子
# ============================================================

def test_picks_high_crowding_composite():
    out = pick_key_factors(_state_with_high_crowding(), n=5)
    names = [c["name"] for c in out]
    assert "crowding" in names
    crowding = next(c for c in out if c["name"] == "crowding")
    assert crowding["signal_strength"] >= 80
    assert "high" in crowding["current_value"]


def test_picks_high_event_risk_composite():
    out = pick_key_factors(_state_with_high_crowding(), n=5)
    names = [c["name"] for c in out]
    assert "event_risk" in names


# ============================================================
# Scenario hint 偏好
# ============================================================

def test_scenario_permission_restricted_boosts_crowding():
    """scenario=permission_restricted 让 crowding/macro/event 加 15 分。"""
    state = _state_with_high_crowding()
    base = pick_key_factors(state, n=5)
    boosted = pick_key_factors(state, n=5, scenario="permission_restricted")
    base_crowding = next(c for c in base if c["name"] == "crowding")
    boost_crowding = next(c for c in boosted if c["name"] == "crowding")
    assert boost_crowding["signal_strength"] >= base_crowding["signal_strength"]


def test_scenario_fallback_degraded_lowers_signals():
    """fallback_degraded 时 picker 全部降权(数据不可信)。"""
    state = _state_with_extreme_funding()
    base = pick_key_factors(state, n=5)
    degraded = pick_key_factors(state, n=5, scenario="fallback_degraded")
    # 同名因子在 degraded 下 signal 应 ≤ base
    for d in degraded:
        same = next((b for b in base if b["name"] == d["name"]), None)
        if same:
            assert d["signal_strength"] <= same["signal_strength"]


# ============================================================
# 输出字段完整性
# ============================================================

def test_output_has_required_fields():
    out = pick_key_factors(_state_with_extreme_funding(), n=3)
    required = {
        "category", "name", "current_value", "context",
        "signal_strength", "interpretation", "evidence_ref",
    }
    for c in out:
        assert required.issubset(c.keys()), f"missing keys in {c}"
        assert 0 <= c["signal_strength"] <= 100
