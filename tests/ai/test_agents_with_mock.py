"""tests/ai/test_agents_with_mock.py — Sprint 1.8 Task E 单 agent 测试。

每个 agent 用 mock anthropic client 测试:
- 正常返回(parse 成功的 JSON)
- 超时(raise TimeoutError)
- 返回非 JSON 错乱内容(测 BaseAgent fallback)
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.ai.agents import (
    L1RegimeAnalyst,
    L2DirectionAnalyst,
    L3OpportunityAnalyst,
    L4RiskAnalyst,
    L5MacroAnalyst,
    MasterAdjudicator,
)


def _make_mock_client(response_text: str, raises: Exception | None = None) -> Any:
    """构造 mock anthropic client。

    response_text 是 AI 应该返回的文本(通常是 JSON 字符串)。
    raises 不为 None 时,messages.create() 抛该异常。
    """
    client = MagicMock()
    if raises is not None:
        client.messages.create.side_effect = raises
        return client

    # 模拟 anthropic Messages API 响应结构
    text_block = MagicMock()
    text_block.text = response_text
    response = MagicMock()
    response.content = [text_block]
    response.usage = MagicMock()
    response.usage.input_tokens = 100
    response.usage.output_tokens = 200
    response.model = "claude-sonnet-4-5-20250929"
    client.messages.create.return_value = response
    return client


# ============================================================
# L1 Regime Analyst
# ============================================================

def test_l1_success_parse():
    """L1 正常 JSON 返回 → status=success + 含 regime / confidence。"""
    expected_json = {
        "regime": "trend_up",
        "regime_stability": "stable",
        "volatility_regime": "normal",
        "confidence": 0.90,
        "key_observations": ["观察1"],
        "contradicting_signals": [],
        "narrative": "BTC 趋势向上",
        "data_completeness_pct": 100,
        "notes": [],
    }
    client = _make_mock_client(json.dumps(expected_json))
    agent = L1RegimeAnalyst(client=client)
    out = agent.analyze({"indicators": {"adx_14": 30}})
    assert out["regime"] == "trend_up"
    assert out["confidence"] == 0.90
    assert out["status"] == "success"
    assert out["agent"] == "l1_regime"


def test_l1_api_error_fallback():
    """L1 API 抛异常 → fallback 到 unclear_insufficient。"""
    client = _make_mock_client("", raises=TimeoutError("API timeout"))
    agent = L1RegimeAnalyst(client=client)
    out = agent.analyze({"indicators": {}})
    assert out["regime"] == "unclear_insufficient"
    assert out["status"].startswith("degraded")


def test_l1_invalid_json_fallback():
    """L1 返回非 JSON → fallback。"""
    client = _make_mock_client("这不是 JSON,只是中文胡言")
    agent = L1RegimeAnalyst(client=client)
    out = agent.analyze({"indicators": {}})
    assert out["regime"] == "unclear_insufficient"
    assert out["status"].startswith("degraded")


def test_l1_json_with_codeblock_wrapper():
    """L1 返回 ```json {} ``` 包裹 → loose parser 也能解析。"""
    expected = {
        "regime": "range_mid", "regime_stability": "stable",
        "volatility_regime": "low", "confidence": 0.7,
        "narrative": "震荡",
    }
    text = "```json\n" + json.dumps(expected) + "\n```"
    client = _make_mock_client(text)
    agent = L1RegimeAnalyst(client=client)
    out = agent.analyze({"indicators": {}})
    assert out["regime"] == "range_mid"
    assert out["status"] == "success"


# ============================================================
# L2 Direction Analyst
# ============================================================

def test_l2_success_parse():
    expected = {
        "stance": "bullish",
        "stance_confidence_tier": "high",
        "phase": "early",
        "key_levels": {"nearest_support": 75320, "major_support": 71420},
        "narrative": "看多结构",
        "confidence": 0.85,
    }
    client = _make_mock_client(json.dumps(expected))
    agent = L2DirectionAnalyst(client=client)
    out = agent.analyze({"l1_output": {"regime": "trend_up"}})
    assert out["stance"] == "bullish"
    assert out["status"] == "success"


def test_l2_fallback_on_error():
    client = _make_mock_client("", raises=ValueError("oops"))
    agent = L2DirectionAnalyst(client=client)
    out = agent.analyze({})
    assert out["stance"] == "neutral"


# ============================================================
# L3 Opportunity Analyst
# ============================================================

def test_l3_success_parse():
    expected = {
        "opportunity_grade": "A",
        "execution_permission": "active_open",
        "anti_pattern_flags": [],
        "rule_trace": ["..."],
        "narrative": "高质量机会",
        "confidence": 0.85,
    }
    client = _make_mock_client(json.dumps(expected))
    agent = L3OpportunityAnalyst(client=client)
    out = agent.analyze({"l1_output": {}, "l2_output": {}})
    assert out["opportunity_grade"] == "A"
    assert out["status"] == "success"


def test_l3_fallback_on_error():
    client = _make_mock_client("", raises=RuntimeError("boom"))
    agent = L3OpportunityAnalyst(client=client)
    out = agent.analyze({})
    assert out["opportunity_grade"] == "none"


# ============================================================
# L4 Risk Analyst
# ============================================================

def test_l4_success_parse():
    expected = {
        "risk_score": 38,
        "risk_tier": "moderate",
        "hard_invalidation_levels": [
            {"price": 73200, "type": "swing_low",
             "description": "短线结构破坏",
             "distance_from_current_pct": -3.36},
        ],
        "position_cap_multiplier": 0.78,
        "risk_breakdown": {"crowding_risk": 45, "structure_risk": 25,
                           "liquidity_risk": 18, "event_risk": 10},
        "narrative": "moderate 风险",
        "confidence": 0.85,
    }
    client = _make_mock_client(json.dumps(expected))
    agent = L4RiskAnalyst(client=client)
    out = agent.analyze({"l1_output": {}, "l2_output": {}})
    assert out["risk_tier"] == "moderate"
    assert out["status"] == "success"
    assert len(out["hard_invalidation_levels"]) == 1


def test_l4_fallback_on_error():
    client = _make_mock_client("", raises=Exception("boom"))
    agent = L4RiskAnalyst(client=client)
    out = agent.analyze({})
    # fallback 给 high risk + 15% 硬下限
    assert out["overall_risk_level"] == "high"
    assert out["position_cap_pct"] == 15.0


# ============================================================
# L5 Macro Analyst
# ============================================================

def test_l5_success_parse():
    expected = {
        "macro_stance": "supportive",
        "headwind_score": 18,
        "extreme_event_detected": False,
        "extreme_event_type": None,
        "macro_warnings": [],
        "position_cap_macro_multiplier": 1.0,
        "narrative": "宏观助推",
        "confidence": 0.90,
    }
    client = _make_mock_client(json.dumps(expected))
    agent = L5MacroAnalyst(client=client)
    out = agent.analyze({"macro_factors": {"dxy_current": 102.0}})
    assert out["macro_stance"] == "supportive"
    assert out["extreme_event_detected"] is False
    assert out["status"] == "success"


def test_l5_fallback_on_error():
    client = _make_mock_client("", raises=TimeoutError("oops"))
    agent = L5MacroAnalyst(client=client)
    out = agent.analyze({})
    assert out["macro_stance"] == "unclear"


# ============================================================
# Master Adjudicator
# ============================================================

def test_master_success_parse():
    expected = {
        "state_transition": {
            "from_state": "FLAT",
            "to_state": "LONG_PLANNED",
            "transition_reasoning": "5 层齐心",
        },
        "trade_plan": {
            "action": "open",
            "direction": "long",
            "stop_loss": 73200,
            "position_size_pct": 0.40,
        },
        "position_cap_final": {
            "value": 0.4409,
            "composition": {"base": 0.70, "raw_product": 0.4409,
                            "after_hard_floor": 0.4409},
        },
        "counter_arguments": ["若 swing_high 失败"],
        "narrative": "BTC 多头机会",
        "confidence": 0.80,
        "data_completeness_pct": 100,
    }
    client = _make_mock_client(json.dumps(expected))
    agent = MasterAdjudicator(client=client)
    out = agent.analyze({
        "l1_output": {}, "l2_output": {}, "l3_output": {},
        "l4_output": {}, "l5_output": {},
        "state_machine_current": "FLAT",
    })
    assert out["state_transition"]["to_state"] == "LONG_PLANNED"
    assert out["status"] == "success"


def test_master_fallback_on_error():
    client = _make_mock_client("", raises=Exception("boom"))
    agent = MasterAdjudicator(client=client)
    out = agent.analyze({})
    # fallback 给 watch
    assert out["action"] == "watch"
    assert out["opportunity_grade"] == "none"
