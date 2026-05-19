"""tests/ai/test_orchestrator.py — Sprint 1.8 Task E 端到端测试。

用 mock anthropic client 模拟 6 AI 返回,验证完整 pipeline 行为:
- 5 层齐心 → 主裁 LONG_PLANNED + active_open
- L5=extreme_event=true → Validator 强制 PROTECTION (H4)
- L1=chaos → action 强制 watch / hold (H5)
- L3=none → action 强制 watch / hold (H6)
- 主裁 stop_loss 不在 L4 列表 → Validator 强制覆盖 (H2)
- 串行合成 multipliers 由 Orchestrator 计算
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from src.ai.orchestrator import AIOrchestrator


def _build_mock_klines_1d(days: int = 200) -> pd.DataFrame:
    idx = pd.date_range("2025-10-01", periods=days, freq="1D", tz="UTC")
    np.random.seed(42)
    close = 70000 + np.cumsum(np.random.randn(days) * 500)
    return pd.DataFrame({
        "open": close - 100, "high": close + 200,
        "low": close - 200, "close": close,
    }, index=idx)


def _build_mock_klines_4h(days: int = 30) -> pd.DataFrame:
    bars = days * 6
    idx = pd.date_range("2026-04-01", periods=bars, freq="4h", tz="UTC")
    np.random.seed(43)
    close = 75000 + np.cumsum(np.random.randn(bars) * 200)
    return pd.DataFrame({
        "open": close - 50, "high": close + 100,
        "low": close - 100, "close": close,
    }, index=idx)


def _make_layered_mock_agents(
    l1_output: dict[str, Any],
    l2_output: dict[str, Any],
    l3_output: dict[str, Any],
    l4_output: dict[str, Any],
    l5_output: dict[str, Any],
    master_output: dict[str, Any],
) -> dict[str, Any]:
    """构造每层 agent 的 mock。每个 agent 的 analyze() 直接返回预设 JSON。

    返回 {l1, l2, l3, l4, l5, master} dict 给 AIOrchestrator(agents=...)。
    """
    def _mock_agent(out: dict[str, Any], name: str) -> Any:
        a = MagicMock()
        out_with_status = {**out}
        out_with_status.setdefault("status", "success")
        a.analyze.return_value = out_with_status
        a._fallback_output.return_value = {**out, "status": "degraded"}
        return a

    return {
        "l1": _mock_agent(l1_output, "l1"),
        "l2": _mock_agent(l2_output, "l2"),
        "l3": _mock_agent(l3_output, "l3"),
        "l4": _mock_agent(l4_output, "l4"),
        "l5": _mock_agent(l5_output, "l5"),
        "master": _mock_agent(master_output, "master"),
    }


def _build_context(current_state: str = "FLAT", **overrides) -> dict[str, Any]:
    """Sprint 1.9-A.4 起 ctx 是 per-agent 嵌套结构。"""
    klines_1d = _build_mock_klines_1d()
    extreme_flags = {
        "geopolitical_conflict_active": False,
        "major_bank_crisis_signal": False,
        "regulatory_crackdown_recent": False,
        "flash_crash_detected_24h": False,
        "stablecoin_depeg_active": False,
    }
    base = {
        "_shared": {
            "klines_1d": klines_1d,
            "klines_4h": _build_mock_klines_4h(),
            "current_close": 75749,
            "events_count_72h": 0,
        },
        "l1": {
            "klines_1d_30d_close": klines_1d["close"].iloc[-30:].tolist(),
            "computed_indicators": {"adx_14_1d_current": 30,
                                    "ema_20_current": 75320},
            "previous_l1": None,
        },
        "l2": {
            "klines_1d_30d_close": klines_1d["close"].iloc[-30:].tolist(),
            "computed_indicators": {"ema_20_current": 75320},
            "previous_l2": None,
        },
        "l3": {
            "risk_preview": {"funding_rate_z_score_90d": 0.5,
                             "open_interest_z_score_90d": 0.3,
                             "events_count_72h": 0},
            "current_state": current_state,
            "previous_l3": None,
        },
        "l4": {
            "computed_indicators": {"current_close": 75749},
            "current_state": current_state,
            "previous_l4": None,
        },
        "l5": {
            "computed_macro_indicators": {"dxy_current": 102.0,
                                          "vix_current": 14.5},
            "events_calendar_72h": [],
            "extreme_event_flags": extreme_flags,
            "previous_l5": None,
        },
        "master": {
            "current_state": current_state,
            "previous_strategy_run": None,
        },
    }
    base.update(overrides)
    return base


# ============================================================
# 端到端场景测试
# ============================================================

def test_compute_crowding_multiplier_buckets():
    o = AIOrchestrator()
    assert o._compute_crowding_multiplier(
        {"risk_breakdown": {"crowding_risk": 10}}) == 1.0
    assert o._compute_crowding_multiplier(
        {"risk_breakdown": {"crowding_risk": 30}}) == 0.85
    assert o._compute_crowding_multiplier(
        {"risk_breakdown": {"crowding_risk": 60}}) == 0.65
    assert o._compute_crowding_multiplier(
        {"risk_breakdown": {"crowding_risk": 90}}) == 0.50


def test_compute_crowding_multiplier_missing_field():
    """缺 risk_breakdown → 默认 1.0(crowding 0)。"""
    o = AIOrchestrator()
    assert o._compute_crowding_multiplier({}) == 1.0
    assert o._compute_crowding_multiplier({"risk_breakdown": {}}) == 1.0


def test_compute_event_multiplier_levels():
    o = AIOrchestrator()
    assert o._compute_event_multiplier([]) == 0.95
    assert o._compute_event_multiplier(
        [{"impact_level": "low"}]) == 0.95
    assert o._compute_event_multiplier(
        [{"impact_level": "medium"}]) == 0.85
    assert o._compute_event_multiplier(
        [{"impact_level": "high"}]) == 0.70
    assert o._compute_event_multiplier(
        [{"impact_level": "critical"}]) == 0.50


def test_compute_event_multiplier_takes_max_impact():
    """混合事件 → 取最高 impact。"""
    o = AIOrchestrator()
    assert o._compute_event_multiplier([
        {"impact_level": "low"},
        {"impact_level": "high"},
        {"impact_level": "medium"},
    ]) == 0.70


# ============================================================
# 退化场景:层失败时 fallback 链
# ============================================================

def test_l1_failure_does_not_crash_pipeline():
    """L1 fallback 但其他层正常 → 整个 pipeline 仍出 result + degraded 状态。"""
    l1 = {"regime": "unclear_insufficient", "status": "degraded_l1_failed",
          "confidence": 0.0}
    l2 = {"stance": "neutral", "phase": "n_a", "confidence": 0.5}
    l3 = {"opportunity_grade": "none", "confidence": 0.5}
    l4 = {"risk_tier": "high",
          "hard_invalidation_levels": [], "confidence": 0.5}
    l5 = {"macro_stance": "neutral", "extreme_event_detected": False,
          "position_cap_macro_multiplier": 1.0, "confidence": 0.5}
    master = {
        "state_transition": {"from_state": "FLAT", "to_state": "FLAT",
                             "transition_reasoning": "数据降级"},
        "trade_plan": {"action": "watch", "direction": None,
                       "stop_loss": None, "position_size_pct": None},
        "position_cap_final": {"value": 0.30,
                               "composition": {"base": 0.70,
                                               "raw_product": 0.30}},
        "counter_arguments": ["数据缺失,谨慎"],
        "narrative": "...",
        "confidence": 0.30,
        "data_completeness_pct": 50,
    }
    agents = _make_layered_mock_agents(l1, l2, l3, l4, l5, master)
    orch = AIOrchestrator(agents=agents)
    result = orch.run_full_a(_build_context())

    assert "degraded_l1" in result["status"]
    assert result["layers"]["l1"]["status"].startswith("degraded")
    # 其他层仍能跑
    assert "master" in result["layers"]


def test_orchestrator_result_structure():
    """结果含 layers / validator / status / latency_ms / tokens。"""
    l1 = {"regime": "trend_up", "confidence": 0.9}
    l2 = {"stance": "bullish", "phase": "early",
          "stance_confidence_tier": "high", "confidence": 0.85}
    l3 = {"opportunity_grade": "A", "confidence": 0.85}
    l4 = {"risk_tier": "moderate",
          "hard_invalidation_levels": [{"price": 73200, "type": "swing_low",
                                        "distance_from_current_pct": -3.36}],
          "risk_breakdown": {"crowding_risk": 30}, "confidence": 0.85}
    l5 = {"macro_stance": "supportive", "extreme_event_detected": False,
          "position_cap_macro_multiplier": 1.0, "confidence": 0.90}
    master = {
        "state_transition": {"from_state": "FLAT",
                             "to_state": "LONG_PLANNED",
                             "transition_reasoning": "..."},
        "trade_plan": {"action": "open", "direction": "long",
                       "stop_loss": 73200, "position_size_pct": 0.40},
        "position_cap_final": {"value": 0.4409,
                               "composition": {"base": 0.70,
                                               "raw_product": 0.4409}},
        "counter_arguments": ["..."],
        "narrative": "...",
        "confidence": 0.80,
        "data_completeness_pct": 100,
    }
    agents = _make_layered_mock_agents(l1, l2, l3, l4, l5, master)
    orch = AIOrchestrator(agents=agents)
    result = orch.run_full_a(_build_context())

    assert "layers" in result
    assert "validator" in result
    assert "status" in result
    assert "latency_ms" in result
    assert set(result["layers"].keys()) == {
        "l1", "l2", "l3", "l4", "l5", "master",
    }
    # 每层都有 latency 记录
    for layer in ("l1", "l2", "l3", "l4", "l5", "master"):
        assert layer in result["latency_ms"]
