"""tests/test_narrative_human_quality.py — Sprint 1.5m Task C2。

§Z 反退化:1.5m 把 no_opportunity_narrator 8 场景重写为 4 段交易员叙事
(【结构】【解读】【关键】【结论】+ 具体数值)。本测试用真值 mock state
注入 factor_cards,断言生成的 narrative 含数值 + 不含老机器化模板词。
"""

from __future__ import annotations

import re

from src.strategy.no_opportunity_narrator import generate_no_opportunity_narrative


# ============================================================
# 反退化:老模板词不应出现在新 narrative 里
# ============================================================

_OLD_TEMPLATE_PHRASES = (
    "执行许可被收紧到",
    "系统不允许新开仓",
    "鉴于以上因素",
    "综上所述",
    "本系统建议",
)


def _has_old_template(text: str) -> bool:
    return any(p in text for p in _OLD_TEMPLATE_PHRASES)


def _count_concrete_values(text: str) -> int:
    """% 号 / 价格 / 大数。"""
    pct = re.findall(r"-?\d+\.?\d*\s*%", text)
    big = re.findall(r"\b\d{2,}(?:[,\.]\d+)*\b", text)
    return len(pct) + len(big)


# ============================================================
# Mock state with rich factor data
# ============================================================

def _state_with_funding_lsr_data() -> tuple[dict, dict]:
    """生产典型场景:FLAT + grade=none + 衍生品有 extreme funding + LSR 24h 大变。"""
    facts = {
        "l3_grade": "none",
        "l3_permission": "watch",
        "state_machine_current": "FLAT",
        "cold_start_warming_up": False,
        "fallback_level": None,
    }
    state = {
        "factor_cards": [
            {
                "card_id": "deriv_funding_30d",
                "category": "derivatives",
                "name": "资金费率 · 30 日分位",
                "current_value": 11.0,
                "value_unit": "",
            },
            {
                "card_id": "deriv_funding_now",
                "category": "derivatives",
                "name": "Binance 资金费率 · 当前",
                "current_value": -0.4085,
                "value_unit": "%",
            },
            {
                "card_id": "deriv_oi_24h",
                "category": "derivatives",
                "name": "未平仓合约 24h 变化",
                "current_value": 1.52,
                "value_unit": "%",
            },
            {
                "card_id": "deriv_lsr_24h",
                "category": "derivatives",
                "name": "Binance 多空比 24h 变化",
                "current_value": 13.68,
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
        "composite_factors": {
            "crowding": {"crowding_level": "high", "crowding_score": 11},
            "macro_headwind": {"macro_headwind_level": "mild",
                               "headwind_score": -2},
            "event_risk": {"event_risk_level": "high",
                           "event_risk_score": 11.5},
        },
    }
    return facts, state


# ============================================================
# 4 段结构存在
# ============================================================

def test_grade_none_narrative_has_4_sections():
    """narrative 必须含【结构】【解读】【关键】【结论】4 个段标记。"""
    facts, state = _state_with_funding_lsr_data()
    out = generate_no_opportunity_narrative(facts, state)
    n = out["narrative"]
    for tag in ("【结构】", "【解读】", "【关键】", "【结论】"):
        assert tag in n, f"narrative 缺段:{tag} | actual={n!r}"


# ============================================================
# narrative 数值密度
# ============================================================

def test_grade_none_narrative_contains_factor_values():
    """narrative 必须含 ≥ 3 个具体数值。"""
    facts, state = _state_with_funding_lsr_data()
    out = generate_no_opportunity_narrative(facts, state)
    n = out["narrative"]
    cnt = _count_concrete_values(n)
    assert cnt >= 3, f"narrative 数值数 {cnt} < 3:{n!r}"


def test_grade_none_narrative_no_status_repetition():
    """narrative 不应含老机器化模板词。"""
    facts, state = _state_with_funding_lsr_data()
    out = generate_no_opportunity_narrative(facts, state)
    n = out["narrative"]
    assert not _has_old_template(n), \
        f"narrative 含老模板词:{n!r}"


# ============================================================
# permission_restricted 场景偏好
# ============================================================

def test_permission_restricted_focuses_on_tightening_factors():
    """mock crowding=high → primary_drivers 至少含 crowding 相关条目。"""
    facts = {
        "l3_grade": "none",
        "l3_permission": "watch",
        "state_machine_current": "FLAT",
    }
    state = {
        "composite_factors": {
            "crowding": {"crowding_level": "high", "crowding_score": 11},
            "event_risk": {"event_risk_level": "high",
                           "event_risk_score": 11.5},
            "macro_headwind": {"macro_headwind_level": "strong",
                               "headwind_score": -6},
        },
    }
    out = generate_no_opportunity_narrative(facts, state)
    drivers_text = " ".join(d.get("text", "") for d in out["primary_drivers"])
    # crowding / macro_headwind / event_risk 至少一个出现在 drivers
    assert any(kw in drivers_text for kw in (
        "crowding", "拥挤度", "macro_headwind", "宏观逆风",
        "event_risk", "事件风险",
    )), f"drivers 未提及触发收紧的 composite:{drivers_text}"


# ============================================================
# primary_drivers 含具体数值或事实
# ============================================================

def test_primary_drivers_concrete():
    """每条 driver text 含具体数值(% / 大数 / 因子名)。"""
    facts, state = _state_with_funding_lsr_data()
    out = generate_no_opportunity_narrative(facts, state)
    drivers = out["primary_drivers"]
    assert len(drivers) >= 3
    # 至少 2 条含具体数值
    concrete = sum(
        1 for d in drivers if _count_concrete_values(d.get("text", "")) >= 1
    )
    assert concrete >= 2, (
        f"应至少 2 条 driver 含数值,实际 {concrete}\ndrivers={drivers}"
    )


# ============================================================
# what_would_change_mind 含可观测条件
# ============================================================

def test_change_conditions_have_thresholds():
    """改变判断的条件至少 1 条含数值阈值(% / 数字 / 区间)。"""
    facts, state = _state_with_funding_lsr_data()
    out = generate_no_opportunity_narrative(facts, state)
    conds = out["what_would_change_mind"]
    assert len(conds) >= 3
    has_number = sum(
        1 for c in conds if _count_concrete_values(c) >= 1
    )
    assert has_number >= 1, (
        f"应至少 1 条改变条件含数值,实际 {has_number}\nconds={conds}"
    )


# ============================================================
# counter_arguments 是反向论据,不是免责声明
# ============================================================

def test_counter_arguments_are_real_signals():
    """counter_arguments 应给"挑战当前判断的真实信号",至少 1 条含因子相关词。"""
    facts, state = _state_with_funding_lsr_data()
    out = generate_no_opportunity_narrative(facts, state)
    counters = out["counter_arguments"]
    assert len(counters) >= 2
    # picker 选了 LSR 24h +13.68% → counter_arguments 应识别这是潜在反转
    counter_texts = " ".join(c.get("text", "") for c in counters)
    # 至少识别到 LSR / OI / SOPR 等因子级反转信号(picker 选了这些)
    has_real_signal = any(kw in counter_texts for kw in (
        "LSR", "OI", "SOPR", "funding", "多空比", "未平仓",
    ))
    assert has_real_signal, (
        f"counter_arguments 应含因子级反转信号,实际:{counter_texts}"
    )
