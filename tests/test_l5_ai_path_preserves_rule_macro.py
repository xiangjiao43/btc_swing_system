"""tests/test_l5_ai_path_preserves_rule_macro.py — Sprint 1.5c.6 反退化。

§Z 真跑 Layer5Macro.compute + mock _try_call_l5_ai 各种返回:
- AI 返回空 structured_macro → 规则路径填的 DXY/US10Y/VIX/btc_nasdaq_corr 保留
- AI 返回非空 → merge(规则路径基础 + AI 字段;AI 覆盖同名 key)
- AI 不可用(client=None)→ 走规则路径,structured_macro 真有数

老 bug:`rule_output.update({"structured_macro": ai_out["structured_macro"]})`
无条件覆盖,AI v0 阶段 prompt 没要求填 sm 时返回 {} → 把规则路径产物清空。
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from src.evidence import Layer5Macro


def _make_full_ctx() -> dict:
    rng = pd.date_range("2024-01-01", periods=120, freq="D", tz="UTC")
    dxy = pd.Series([102.0 + 0.05 * i for i in range(120)], index=rng)
    us10y = pd.Series([4.0 + 0.005 * i for i in range(120)], index=rng)
    nasdaq = pd.Series([15_000.0 + 5 * i for i in range(120)], index=rng)
    vix = pd.Series([18.0] * 120, index=rng)
    sp500 = pd.Series([5_000.0] * 120, index=rng)
    klines_1d = pd.DataFrame({
        "open": [50_000] * 120, "high": [50_500] * 120,
        "low": [49_500] * 120, "close": [50_000 + 10 * i for i in range(120)],
        "volume": [1.0] * 120,
    }, index=rng)
    return {
        "macro": {"dxy": dxy, "us10y": us10y, "nasdaq": nasdaq,
                  "vix": vix, "sp500": sp500},
        "klines_1d": klines_1d,
    }


def _ai_response_with_empty_sm() -> dict:
    """模拟生产实测:AI v0 阶段 prompt 没要求 structured_macro,返回 {}。"""
    return {
        "macro_stance": "risk_neutral",
        "macro_trend": "volatile",
        "structured_macro": {},     # ← 关键:空 dict
        "active_macro_tags": [],
        "active_event_summaries": [],
        "extreme_event_detected": False,
        "extreme_event_details": None,
        "adjustment_guidance": {
            "stance_modifier": "neutral",
            "position_cap_multiplier": 1.0,
            "permission_adjustment": "neutral",
            "note": "",
        },
        "macro_headwind_score": 0.0,
        "_meta": {"model": "test", "tokens_in": 100, "tokens_out": 50,
                  "latency_ms": 200},
    }


def _ai_response_with_partial_sm() -> dict:
    """AI 真返回部分 structured_macro 字段,应 merge 到规则路径基础上。"""
    base = _ai_response_with_empty_sm()
    base["structured_macro"] = {
        "AI_only_key": "ai_view",
        "DXY": "ai_overrides_rule",   # AI 覆盖规则路径的 DXY
    }
    return base


# ============================================================
# 任务 B.1:AI 空 sm → 规则路径保留
# ============================================================

def test_ai_empty_structured_macro_preserves_rule_path():
    """AI 返回 sm={} 时,规则路径填的 DXY/US10Y/VIX/btc_nasdaq_corr 保留。
    防 1.5c.6 之前的 bug 退化:AI 无条件覆盖把规则路径清空。"""
    with patch(
        "src.evidence.layer5_macro._try_call_l5_ai",
        return_value=_ai_response_with_empty_sm(),
    ):
        out = Layer5Macro().compute(_make_full_ctx())

    assert out["computation_method"] == "ai_assisted"
    sm = out.get("structured_macro") or {}
    keys = sorted(k for k in sm if k != "data_completeness_pct")
    # 关键反退化:规则路径填的 4 类必须保留
    assert "DXY" in keys, sm
    assert "US10Y" in keys, sm
    assert "VIX" in keys, sm
    assert "btc_nasdaq_corr" in keys, sm
    # AI 字段也应到位(stance/trend/score)
    assert out["macro_stance"] == "risk_neutral"
    assert out["macro_trend"] == "volatile"


# ============================================================
# 任务 B.2:AI 非空 sm → merge
# ============================================================

def test_ai_with_structured_macro_merges():
    """AI 返回 sm={AI_only_key, DXY=ai_overrides} → merge 后:
    规则路径填的 US10Y/VIX 仍在,DXY 被 AI 覆盖,新增 AI_only_key。"""
    with patch(
        "src.evidence.layer5_macro._try_call_l5_ai",
        return_value=_ai_response_with_partial_sm(),
    ):
        out = Layer5Macro().compute(_make_full_ctx())

    sm = out.get("structured_macro") or {}
    # 规则路径基础保留(US10Y/VIX/btc_nasdaq_corr)
    assert "US10Y" in sm
    assert "VIX" in sm
    assert "btc_nasdaq_corr" in sm
    # AI 新增字段
    assert sm.get("AI_only_key") == "ai_view"
    # AI 覆盖同名 key
    assert sm.get("DXY") == "ai_overrides_rule"


# ============================================================
# 任务 B.3:AI 不可用 → 走规则路径
# ============================================================

def test_rule_path_alone_when_ai_disabled():
    """_try_call_l5_ai 返回 None(client unavailable / 异常)→
    走规则路径,structured_macro 仍含 DXY/US10Y/VIX/btc_nasdaq_corr。"""
    with patch(
        "src.evidence.layer5_macro._try_call_l5_ai", return_value=None,
    ):
        out = Layer5Macro().compute(_make_full_ctx())

    assert out["computation_method"] == "rule_based"
    sm = out.get("structured_macro") or {}
    keys = sorted(k for k in sm if k != "data_completeness_pct")
    assert "DXY" in keys
    assert "US10Y" in keys
    assert "VIX" in keys
    assert "btc_nasdaq_corr" in keys


# ============================================================
# 端到端:_pillars_l5 应 ok
# ============================================================

def test_pillars_l5_ok_after_ai_empty_sm_path():
    """合二为一:AI 返回空 sm + Layer5Macro 走 ai_assisted →
    _pillars_l5 仍 ok(因为 sm 不再被清空)。"""
    from src.evidence.pillars import _pillars_l5

    with patch(
        "src.evidence.layer5_macro._try_call_l5_ai",
        return_value=_ai_response_with_empty_sm(),
    ):
        out = Layer5Macro().compute(_make_full_ctx())
    pillars = _pillars_l5(out)
    sm_pillar = next(p for p in pillars["pillars"] if p["id"] == "structured_macro")
    assert sm_pillar["status"] == "ok"
    assert "DXY=" in sm_pillar["interpretation"]
