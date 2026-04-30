"""tests/test_event_factor_neutralized.py — Sprint 1.5q §X 反退化。

EventRisk 软删除(中长期波段哲学):
- 因子永远 band='none' / cap_multiplier=1.0 / permission_adjustment=None
- L4 risk 删除 step 5(× event_risk)+ permission 不再含 l4_event_risk 建议
- 事件卡 impact_direction='neutral',strategy_impact='参考信息'
- 网页 "影响:偏空" 老文案不在事件卡渲染路径

§Z 反退化锁:确保未来不被恢复。
"""

from __future__ import annotations

from pathlib import Path

from src.composite.event_risk import EventRiskFactor
from src.evidence.layer4_risk import _compose_position_cap, _merge_permissions
from src.strategy.factor_card_emitter import _emit_events_reference


# ============================================================
# A. EventRiskFactor 永远 neutral
# ============================================================

def test_event_risk_factor_band_always_none():
    """无论 events 多多少 / hours_to 多近,band 永远 'none'。"""
    high_pressure = [
        {"name": "FOMC", "event_type": "fomc", "hours_to": 1},
        {"name": "CPI", "event_type": "cpi", "hours_to": 6},
        {"name": "NFP", "event_type": "nfp", "hours_to": 12},
    ]
    out = EventRiskFactor().compute({
        "events_upcoming_48h": high_pressure,
        "is_volatility_extreme": True,
        "btc_nasdaq_correlated": True,
    })
    assert out["band"] == "none"


def test_event_risk_factor_cap_multiplier_always_1():
    out = EventRiskFactor().compute({
        "events_upcoming_48h": [
            {"name": "FOMC", "event_type": "fomc", "hours_to": 2},
        ],
    })
    assert out["position_cap_multiplier"] == 1.0


def test_event_risk_factor_permission_adjustment_always_none():
    """老实现 score >= 8 触发 ambush_only,新实现永远 None。"""
    out = EventRiskFactor().compute({
        "events_upcoming_48h": [
            {"name": "FOMC", "event_type": "fomc", "hours_to": 1},
            {"name": "CPI", "event_type": "cpi", "hours_to": 5},
        ],
    })
    assert out["score"] >= 8.0  # 分数仍计算
    assert out["permission_adjustment"] is None


# ============================================================
# B. L4 删除 step 5 (× event_risk)
# ============================================================

def test_position_cap_composition_no_after_l4_event():
    """_compose_position_cap 输出 composition dict 不再含 after_l4_event /
    l4_event_risk_multiplier。"""
    final, comp = _compose_position_cap(
        base_pct=70.0,
        overall_risk_level="moderate",
        crowding_score=2,
        macro_headwind_score=0.0,
        event_risk_score=8.0,  # 即使传入也不应影响
        hard_floor_pct=15.0,
    )
    assert "after_l4_event" not in comp
    assert "l4_event_risk_multiplier" not in comp


def test_position_cap_composition_has_4_steps():
    """1.5q:剩 4 步乘数(base + l4_risk + l4_crowding + l5_macro_headwind)。"""
    final, comp = _compose_position_cap(
        base_pct=70.0,
        overall_risk_level="moderate",
        crowding_score=2,
        macro_headwind_score=0.0,
        event_risk_score=8.0,
        hard_floor_pct=15.0,
    )
    assert "l4_risk_multiplier" in comp
    assert "l4_crowding_multiplier" in comp
    assert "l5_macro_headwind_multiplier" in comp
    # 但没有 event_risk multiplier
    assert "l4_event_risk_multiplier" not in comp


# ============================================================
# C. 事件卡 impact_direction always neutral
# ============================================================

def test_event_card_impact_direction_always_neutral():
    """1.5q:事件卡 impact_direction 永远 neutral,不再"< 48h 标 bearish"。"""
    cards = _emit_events_reference(
        events=[],
        today="20260430",
        next_by_type={
            "fomc": {"hours_to": 1.0, "event_type": "fomc"},     # 极近
            "cpi":  {"hours_to": 6.0, "event_type": "cpi"},      # < 48h
            "nfp":  {"hours_to": 100.0, "event_type": "nfp"},    # > 72h
        },
    )
    for c in cards:
        assert c["impact_direction"] == "neutral", (
            f"event card {c.get('card_id')} impact_direction={c['impact_direction']},"
            "应永远 neutral(1.5q 中长期波段哲学)"
        )


def test_event_card_strategy_impact_says_reference_only():
    cards = _emit_events_reference(
        events=[], today="20260430",
        next_by_type={"fomc": {"hours_to": 11.5, "event_type": "fomc"}},
    )
    fomc_card = next(c for c in cards if "fomc" in c["card_id"])
    assert "参考信息" in fomc_card["strategy_impact"]
    assert "不参与策略评分" in fomc_card["strategy_impact"]


def test_event_card_plain_interpretation_no_high_risk_label():
    """1.5q 反退化:plain_interpretation 不含 "< 24h = 高风险窗口" 老标签。"""
    cards = _emit_events_reference(
        events=[], today="20260430",
        next_by_type={"fomc": {"hours_to": 5.0, "event_type": "fomc"}},
    )
    for c in cards:
        assert "高风险窗口" not in c["plain_interpretation"]
        assert "系统降档" not in c["plain_interpretation"]


# ============================================================
# D. 前端 HTML 没有"影响:偏空"等老文案
# ============================================================

_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_html_has_no_event_impact_label_text():
    """1.5q 反退化:web/index.html 不应含静态"影响:偏空"标签。
    (impact_direction 现在永远 neutral,即使老 directionLabel 渲染也是"中性"。)"""
    html = (_REPO_ROOT / "web" / "index.html").read_text(encoding="utf-8")
    # 静态字面量 "偏空" / "偏多" 不应作为 strategy_impact 老文案出现
    # (允许出现在 directionLabel 函数定义里,作为 lookup 值)
    # 这里反退化主要确保不出现 hardcoded "影响:偏空" 这种事件硬编码
    assert "事件影响:偏空" not in html
    assert "事件影响:偏多" not in html
