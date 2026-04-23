"""
tests/test_ai_summary.py — AI 摘要模块单测(mock OpenAI,不真实打 API)。

真实 smoke test 在 test_ai_summary_smoke.py,用 RUN_AI_SMOKE=1 手工触发。
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.ai.summary import (
    _DEFAULT_MODEL,
    build_evidence_summary_prompt,
    call_ai_summary,
)


# ==================================================================
# Mock response factory
# ==================================================================

def _mock_response(text: str = "段 1...\n\n段 2...\n\n段 3...",
                   model: str = "claude-sonnet-4-5-20250929",
                   tokens_in: int = 120, tokens_out: int = 180) -> MagicMock:
    r = MagicMock()
    r.model = model
    r.choices = [MagicMock()]
    r.choices[0].message.content = text
    r.usage = MagicMock(prompt_tokens=tokens_in, completion_tokens=tokens_out)
    return r


def _mock_evidence() -> dict[str, Any]:
    """构造典型五层输出的简化版(用于 prompt)。"""
    return {
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
            "position_cap": 0.15,
            "stop_loss_reference": {"price": 48000},
            "risk_reward_ratio": 2.3,
            "rr_pass_level": "full",
            "risk_permission": "can_open",
            "health_status": "healthy",
        },
        "layer_5": {
            "macro_environment": "risk_on",
            "macro_headwind_vs_btc": "tailwind",
            "data_completeness_pct": 60.0,
            "health_status": "healthy",
        },
    }


# ==================================================================
# Prompt building
# ==================================================================

class TestBuildPrompt:
    def test_includes_key_fields(self):
        evid = _mock_evidence()
        prompt = build_evidence_summary_prompt(evid)

        # L1 关键词
        assert "trend_up" in prompt
        assert "L1 市场形态" in prompt
        # L2
        assert "bullish" in prompt
        assert "stance_confidence=0.72" in prompt
        # L3
        assert "grade=A" in prompt
        assert "can_open" in prompt
        # L4
        assert "0.15" in prompt
        # L5
        assert "risk_on" in prompt

    def test_structured_output_requirement(self):
        prompt = build_evidence_summary_prompt(_mock_evidence())
        assert "段 1" in prompt
        assert "段 2" in prompt
        assert "段 3" in prompt
        # 必须含"输出要求"指令
        assert "输出要求" in prompt

    def test_handles_missing_layer(self):
        """L5 缺失 → prompt 不抛错,含 '数据缺失' 提示。"""
        evid = _mock_evidence()
        del evid["layer_5"]
        prompt = build_evidence_summary_prompt(evid)
        assert "数据缺失" in prompt


# ==================================================================
# Successful AI call
# ==================================================================

class TestCallAISuccess:
    def test_normal_response(self):
        """Mock 正常响应 → status='success',summary_text 返回。"""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_response(
            text="段 1:市场上升。\n\n段 2:A 级机会。\n\n段 3:宏观顺风。",
            tokens_in=150, tokens_out=90,
        )

        result = call_ai_summary(_mock_evidence(), openai_client=mock_client)

        assert result["status"] == "success"
        assert result["summary_text"].startswith("段 1")
        assert result["tokens_in"] == 150
        assert result["tokens_out"] == 90
        assert result["model_used"] == "claude-sonnet-4-5-20250929"
        assert result["error"] is None
        # 验证 create 被调了(仅 1 次,无重试)
        assert mock_client.chat.completions.create.call_count == 1

    def test_model_override(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_response(
            model="claude-sonnet-4-5-20250929"
        )
        call_ai_summary(_mock_evidence(), openai_client=mock_client,
                        model="my-custom-model")
        # 验证 model 参数传入
        call_args = mock_client.chat.completions.create.call_args
        assert call_args.kwargs["model"] == "my-custom-model"

    def test_system_prompt_override(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_response()
        call_ai_summary(_mock_evidence(), system_prompt="custom sys",
                        openai_client=mock_client)
        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "custom sys"


# ==================================================================
# Retry + degraded
# ==================================================================

class TestCallAIRetry:
    @patch("src.ai.summary.time.sleep", return_value=None)  # skip actual sleep
    def test_all_attempts_fail_returns_degraded(self, mock_sleep):
        """3 次尝试全部失败 → status='degraded_error',不抛异常。"""
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = RuntimeError("API fail")

        result = call_ai_summary(_mock_evidence(), openai_client=mock_client)

        assert result["status"] == "degraded_error"
        assert result["summary_text"] is None
        assert "API fail" in (result["error"] or "")
        # 共 3 次尝试(初始 + 2 次重试)
        assert mock_client.chat.completions.create.call_count == 3

    @patch("src.ai.summary.time.sleep", return_value=None)
    def test_first_fails_second_succeeds(self, mock_sleep):
        """第一次失败,第二次成功 → status='success',调用 2 次。"""
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [
            RuntimeError("flaky"),
            _mock_response(text="recovered segment"),
        ]
        result = call_ai_summary(_mock_evidence(), openai_client=mock_client)
        assert result["status"] == "success"
        assert "recovered" in result["summary_text"]
        assert mock_client.chat.completions.create.call_count == 2

    @patch("src.ai.summary.time.sleep", return_value=None)
    def test_timeout_marked_as_degraded_timeout(self, mock_sleep):
        """Timeout 异常 → status='degraded_timeout'。"""
        # 构造带 Timeout 名字的异常
        class APITimeoutError(Exception):
            pass

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = APITimeoutError("timed out")

        result = call_ai_summary(_mock_evidence(), openai_client=mock_client)
        assert result["status"] == "degraded_timeout"
        assert result["summary_text"] is None


# ==================================================================
# Env-missing fallback(无 api_key 且未注入 client)
# ==================================================================

class TestEnvMissing:
    @patch.dict("os.environ", {}, clear=True)
    def test_no_api_key_graceful(self):
        """OPENAI_API_KEY 未设置时,不真实构造 OpenAI 客户端 → degraded。"""
        result = call_ai_summary(_mock_evidence())
        assert result["status"] == "degraded_error"
        assert result["summary_text"] is None
        assert "OPENAI_API_KEY" in (result["error"] or "")
