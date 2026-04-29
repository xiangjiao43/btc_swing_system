"""tests/test_pillars_status_classification.py — Sprint 1.5c.3 pillar 状态分类。

§Z 真实数据 + 真 _pillars_*:
- L2 phase=unclear 但 trend_position 已算 → status="ok"(不是 missing)
- L4 hard_invalidation_levels=[] + l2_stance="neutral" → status="ok"(设计行为)
- L4 hard_invalidation_levels=[] + l2_stance="bullish" → status="missing"(真问题)
- L5 structured_macro 规则路径填(DXY / US10Y / VIX / btc_nasdaq_corr)
- L5 qualitative_events v0.5 不产出 → status="ok"(设计行为)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.evidence.pillars import _pillars_l2, _pillars_l4, _pillars_l5


# ============================================================
# Task A:L2 相对位置 phase=unclear → ok
# ============================================================

def test_l2_relative_position_unclear_is_ok_status():
    """phase=unclear + trend_position.estimated_pct_of_move=1.026 →
    status="ok",interpretation 含"扩展 103%"。"""
    l2 = {
        "stance": "neutral", "phase": "unclear",
        "trend_position": {"estimated_pct_of_move": 1.026,
                           "basis": "impulse_extension_ratio",
                           "reliability": 0.5},
        "structure_features": {"hh_count": 9, "hl_count": 11,
                               "lh_count": 6, "ll_count": 4,
                               "latest_structure": "HH"},
        "long_cycle_context": {"cycle_position": "mid_bull",
                               "cycle_confidence": 0.6},
    }
    out = _pillars_l2(l2)
    pillars = out["pillars"]
    rel_pos = next(p for p in pillars if p["id"] == "relative_position")
    assert rel_pos["status"] == "ok", (
        f"phase=unclear 但已算扩展应是 ok,实际 {rel_pos}"
    )
    assert "扩展 103%" in rel_pos["interpretation"], rel_pos["interpretation"]


def test_l2_relative_position_n_a_is_missing():
    """phase=n_a(L2 stance=neutral 时)→ status=missing(真没算波段)。"""
    l2 = {"stance": "neutral", "phase": "n_a",
          "trend_position": None}
    out = _pillars_l2(l2)
    rel_pos = next(p for p in out["pillars"] if p["id"] == "relative_position")
    assert rel_pos["status"] == "missing"


def test_l2_relative_position_ok_with_clear_phase():
    """phase=mid + extension 0.7 → status=ok,扩展 70%。"""
    l2 = {"stance": "bullish", "phase": "mid",
          "trend_position": {"estimated_pct_of_move": 0.7}}
    out = _pillars_l2(l2)
    rel_pos = next(p for p in out["pillars"] if p["id"] == "relative_position")
    assert rel_pos["status"] == "ok"
    assert "扩展 70%" in rel_pos["interpretation"]


# ============================================================
# Task B:L4 结构性失效位 stance=neutral → ok
# ============================================================

def test_l4_invalidation_neutral_stance_is_ok_status():
    """hard_invalidation_levels=[] + l2_stance="neutral" → status="ok"
    (建模 §4.5.4 设计:neutral 时不挂硬止损)。"""
    l4 = {"hard_invalidation_levels": []}
    out = _pillars_l4(l4, composite={}, l2_stance="neutral")
    inv = next(p for p in out["pillars"] if p["id"] == "structural_invalidation")
    assert inv["status"] == "ok"
    assert "方向中性" in inv["interpretation"]


def test_l4_invalidation_no_stance_is_ok_status():
    """l2_stance=None → 当作中性,status=ok。"""
    l4 = {"hard_invalidation_levels": []}
    out = _pillars_l4(l4, composite={})  # 不传 l2_stance
    inv = next(p for p in out["pillars"] if p["id"] == "structural_invalidation")
    assert inv["status"] == "ok"


def test_l4_invalidation_bullish_no_levels_is_missing():
    """stance=bullish 但失效位空 → status=missing(真有问题:swing 不足)。"""
    l4 = {"hard_invalidation_levels": []}
    out = _pillars_l4(l4, composite={}, l2_stance="bullish")
    inv = next(p for p in out["pillars"] if p["id"] == "structural_invalidation")
    assert inv["status"] == "missing"
    assert "bullish" in inv["interpretation"]


def test_l4_invalidation_with_levels_is_ok():
    """有 P1 失效位 → status=ok + 显示价格。"""
    l4 = {"hard_invalidation_levels": [
        {"price": 65000, "priority": 1, "basis": "structural_HL"},
    ]}
    out = _pillars_l4(l4, composite={}, l2_stance="bullish")
    inv = next(p for p in out["pillars"] if p["id"] == "structural_invalidation")
    assert inv["status"] == "ok"
    assert "65000" in inv["interpretation"]


# ============================================================
# Task C:L5 structured_macro 规则路径填基础数据
# ============================================================

def test_l5_structured_macro_filled_in_rule_path():
    """真跑 Layer5Macro.compute(macro={dxy/us10y/vix/nasdaq series}) →
    structured_macro 不空,含 DXY/US10Y/VIX/btc_nasdaq_corr。"""
    from src.evidence import Layer5Macro

    rng = pd.date_range("2024-01-01", periods=120, freq="D", tz="UTC")
    dxy = pd.Series([102.0 + 0.05 * i for i in range(120)], index=rng)
    us10y = pd.Series([4.0 + 0.005 * i for i in range(120)], index=rng)
    nasdaq = pd.Series([15_000.0 * (1 + 0.001 * i) for i in range(120)], index=rng)
    vix = pd.Series([18.0] * 120, index=rng)
    sp500 = pd.Series([5_000.0] * 120, index=rng)
    klines_1d = pd.DataFrame({
        "open": [50_000] * 120, "high": [50_500] * 120,
        "low": [49_500] * 120, "close": [50_000] * 120, "volume": [1.0] * 120,
    }, index=rng)
    out = Layer5Macro().compute({
        "macro": {"dxy": dxy, "us10y": us10y, "nasdaq": nasdaq,
                  "vix": vix, "sp500": sp500},
        "klines_1d": klines_1d,
    })
    sm = out.get("structured_macro") or {}
    # 规则路径(无 AI)填充字段
    assert "DXY" in sm, sm
    assert "US10Y" in sm, sm
    assert "VIX" in sm, sm
    # 必有 latest 数值
    assert sm["DXY"].get("latest") is not None
    assert sm["US10Y"].get("latest") is not None
    assert sm["VIX"].get("latest") is not None


def test_l5_pillars_structured_macro_ok_when_filled():
    """rule_output 已填 structured_macro → _pillars_l5 status=ok。"""
    l5 = {
        "macro_environment": "risk_neutral",
        "macro_stance": "risk_neutral",
        "structured_macro": {
            "DXY": {"trend": "rising", "latest": 105.5},
            "US10Y": {"latest": 4.3},
        },
    }
    out = _pillars_l5(l5)
    sm = next(p for p in out["pillars"] if p["id"] == "structured_macro")
    assert sm["status"] == "ok"


# ============================================================
# Task D:L5 定性事件摘要 v0.5 → ok
# ============================================================

def test_l5_qualitative_summary_v05_is_ok():
    """active_event_summaries=[] → status=ok(按设计不产出),
    interpretation 含 v0.5 字眼。"""
    l5 = {"active_event_summaries": [], "structured_macro": {}}
    out = _pillars_l5(l5)
    qual = next(p for p in out["pillars"] if p["id"] == "qualitative_events")
    assert qual["status"] == "ok"
    assert "v0.5" in qual["interpretation"]


def test_l5_qualitative_summary_with_ai_summaries():
    """active_event_summaries 非空 → status=ok + 显示数量。"""
    l5 = {
        "active_event_summaries": ["FOMC dovish", "CPI cool"],
        "structured_macro": {"DXY": {"latest": 100}},
    }
    out = _pillars_l5(l5)
    qual = next(p for p in out["pillars"] if p["id"] == "qualitative_events")
    assert qual["status"] == "ok"
    assert "2 条" in qual["interpretation"]


# ============================================================
# 端到端反退化:inject_pillars 后 4 项 missing 全消失
# ============================================================

def test_inject_pillars_clears_four_missing_when_data_sufficient():
    """模拟当前生产状态(stance=neutral, phase=unclear, hard_inv 空, structured 已填),
    inject_pillars 后 L2 相对位置 / L4 失效位 / L5 结构化 / L5 定性 全 ok。"""
    from src.evidence.pillars import inject_pillars
    state = {
        "evidence_reports": {
            "layer_1": {"regime": "range_mid"},
            "layer_2": {
                "stance": "neutral", "phase": "unclear",
                "stance_confidence": 0.55,
                "trend_position": {"estimated_pct_of_move": 1.026},
                "structure_features": {"hh_count": 9, "hl_count": 11,
                                       "lh_count": 6, "ll_count": 4,
                                       "latest_structure": "HH"},
                "long_cycle_context": {"cycle_position": "mid_bull",
                                       "cycle_confidence": 0.6},
            },
            "layer_3": {"opportunity_grade": "C"},
            "layer_4": {"hard_invalidation_levels": []},
            "layer_5": {
                "macro_environment": "risk_neutral",
                "macro_stance": "risk_neutral",
                "structured_macro": {
                    "DXY": {"latest": 105.5},
                    "US10Y": {"latest": 4.3},
                },
                "active_event_summaries": [],
            },
        },
        "composite_factors": {
            "crowding": {"score": 2},
            "event_risk": {"score": 1},
        },
    }
    inject_pillars(state)
    er = state["evidence_reports"]

    def _status(layer_id: int, pid: str) -> str:
        for p in (er[f"layer_{layer_id}"].get("pillars") or []):
            if p.get("id") == pid:
                return p.get("status")
        return "NOT FOUND"

    # 4 项原 missing 现应全为 ok
    assert _status(2, "relative_position") == "ok"
    assert _status(4, "structural_invalidation") == "ok"
    assert _status(5, "structured_macro") == "ok"
    assert _status(5, "qualitative_events") == "ok"
