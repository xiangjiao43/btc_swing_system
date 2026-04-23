"""
tests/test_ai_summary_smoke.py — 真实 AI 调用 smoke test(默认不跑)。

触发方式:
    cd ~/Projects/btc_swing_system
    unset VIRTUAL_ENV
    RUN_AI_SMOKE=1 uv run pytest tests/test_ai_summary_smoke.py -v

需要 .env 里有 OPENAI_API_KEY(novaiapi.com 的 key)。
会真实消耗 token,每次约几百 token。
"""

from __future__ import annotations

import os

import pytest

from src import _env_loader  # noqa: F401
from src.ai.summary import call_ai_summary


pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_AI_SMOKE"),
    reason="真实 AI 调用,默认 skip;用 RUN_AI_SMOKE=1 触发",
)


def test_real_call_returns_summary():
    evidence = {
        "layer_1": {
            "regime": "trend_up", "volatility_regime": "normal",
            "regime_stability": "stable", "health_status": "healthy",
            "confidence_tier": "high",
        },
        "layer_2": {
            "stance": "bullish", "phase": "early",
            "stance_confidence": 0.72,
            "thresholds_applied": {"long": 0.55, "short": 0.75},
            "health_status": "healthy", "confidence_tier": "medium",
        },
        "layer_3": {
            "opportunity_grade": "A",
            "execution_permission": "can_open",
            "anti_pattern_flags": [],
            "observation_mode": "disciplined_validation",
            "health_status": "healthy", "confidence_tier": "high",
        },
        "layer_4": {
            "position_cap": 0.12,
            "stop_loss_reference": {"price": 48000},
            "risk_reward_ratio": 2.3, "rr_pass_level": "full",
            "risk_permission": "can_open", "health_status": "healthy",
        },
        "layer_5": {
            "macro_environment": "risk_on",
            "macro_headwind_vs_btc": "tailwind",
            "data_completeness_pct": 60.0,
            "health_status": "healthy",
        },
    }

    assert os.getenv("OPENAI_API_KEY"), "OPENAI_API_KEY 未设置,无法跑真实 smoke"

    result = call_ai_summary(evidence)

    assert result["status"] == "success", f"AI 调用失败:{result['error']}"
    assert result["summary_text"] is not None
    assert len(result["summary_text"]) > 50, "summary_text 太短"
    assert result["tokens_in"] > 100
    assert result["tokens_out"] > 20
    assert result["latency_ms"] > 0

    print()
    print("=== 真实 AI 响应 ===")
    print(result["summary_text"])
    print(f"\ntokens: in={result['tokens_in']}, out={result['tokens_out']}")
    print(f"latency: {result['latency_ms']} ms")
    print(f"model: {result['model_used']}")
