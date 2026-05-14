"""Sprint I — BaseAgent retry 升级单测。

§Z 验证:
- 3 次重试(原 2 次)— 第 1+2 失败、第 3 成功 → status='success'
- 重试间 sleep _RETRY_SLEEP_SEC(让中转站 channel 重路由)
- 触发 fallback 的条件不变:3 次都失败才 degraded_ai_failed

Sprint H Part B + Sprint I 联合保证 weekly_review 不再因单次中转站坏 channel 失败:
  - inner-level: 3 次重试(本 sprint)
  - job-level: 30/60/60 min retry(Sprint H Part A)
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.ai.agents import L1RegimeAnalyst
from src.ai.agents._base import _RETRY_SLEEP_SEC


def _mock_response(text: str) -> MagicMock:
    text_block = MagicMock()
    text_block.text = text
    response = MagicMock()
    response.content = [text_block]
    response.usage = MagicMock()
    response.usage.input_tokens = 100
    response.usage.output_tokens = 200
    response.model = "claude-sonnet-4-5-20250929"
    return response


_VALID_L1_JSON = json.dumps({
    "regime": "trend_up",
    "regime_stability": "stable",
    "volatility_regime": "normal",
    "confidence": 0.90,
    "key_observations": [],
    "contradicting_signals": [],
    "narrative": "ok",
    "data_completeness_pct": 100,
    "notes": [],
})


def test_third_attempt_recovers_from_two_failures():
    """前 2 次抛 'Model not supported',第 3 次成功 → status='success'。

    模拟中转站 channel 连续 2 次坏 channel,第 3 次重路由到正常 channel。
    Sprint H 时只有 2 次重试,这种场景必 fallback;Sprint I 之后能恢复。
    """
    client = MagicMock()
    err = Exception(
        "Error code: 400 - Provider API error: "
        "Model 'claude-sonnet-4-5-20250929' is not supported."
    )
    client.messages.create.side_effect = [
        err,                          # attempt 1 fail
        err,                          # attempt 2 fail
        _mock_response(_VALID_L1_JSON),  # attempt 3 success
    ]
    agent = L1RegimeAnalyst(client=client)
    with patch("src.ai.agents._base.time.sleep") as fake_sleep:
        out = agent.analyze({"indicators": {}})
    assert out["status"] == "success"
    assert out["regime"] == "trend_up"
    assert client.messages.create.call_count == 3
    # Sprint I:重试间 sleep _RETRY_SLEEP_SEC(让中转站 channel 切换)
    sleep_calls = [c.args[0] for c in fake_sleep.call_args_list]
    assert sleep_calls == [_RETRY_SLEEP_SEC, _RETRY_SLEEP_SEC]


def test_three_failures_then_fallback():
    """3 次都失败 → degraded_ai_failed(原 2 次都失败也 fallback,边界变 3)。"""
    client = MagicMock()
    err = Exception("middleware 死了")
    client.messages.create.side_effect = [err, err, err, err]  # 多余的不应被取
    agent = L1RegimeAnalyst(client=client)
    with patch("src.ai.agents._base.time.sleep"):
        out = agent.analyze({"indicators": {}})
    assert out["status"] == "degraded_ai_failed"
    assert client.messages.create.call_count == 3   # 3 次,不是 4 次


def test_first_attempt_success_no_sleep():
    """第 1 次就成功 → 不 sleep,call_count=1(回归测,确保 happy path 0 延迟)。"""
    client = MagicMock()
    client.messages.create.return_value = _mock_response(_VALID_L1_JSON)
    agent = L1RegimeAnalyst(client=client)
    with patch("src.ai.agents._base.time.sleep") as fake_sleep:
        out = agent.analyze({"indicators": {}})
    assert out["status"] == "success"
    assert client.messages.create.call_count == 1
    fake_sleep.assert_not_called()


def test_temperature_progression_on_retries():
    """温度进程:0.2 → 0.4 → 0.4(第 2/3 次同温度,只为 channel rebalance)。"""
    client = MagicMock()
    err = Exception("transient")
    client.messages.create.side_effect = [
        err, err,
        _mock_response(_VALID_L1_JSON),
    ]
    agent = L1RegimeAnalyst(client=client)
    with patch("src.ai.agents._base.time.sleep"):
        agent.analyze({"indicators": {}})
    temps_used = [
        c.kwargs["temperature"] for c in client.messages.create.call_args_list
    ]
    assert temps_used == [0.2, 0.4, 0.4]


def test_second_attempt_recovers():
    """常见场景:第 2 次成功(原 2-attempt 行为也覆盖 → 回归测)。"""
    client = MagicMock()
    client.messages.create.side_effect = [
        Exception("transient"),
        _mock_response(_VALID_L1_JSON),
    ]
    agent = L1RegimeAnalyst(client=client)
    with patch("src.ai.agents._base.time.sleep") as fake_sleep:
        out = agent.analyze({"indicators": {}})
    assert out["status"] == "success"
    assert client.messages.create.call_count == 2
    assert len(fake_sleep.call_args_list) == 1   # 仅第 2 次前 sleep


def test_restricted_model_error_is_terminal_no_retry():
    """403 Claude Code 专用模型限制 → 不是网络抖动,不应重试。"""
    client = MagicMock()
    err = Exception(
        "Error code: 403 - This model is restricted to Claude Code clients "
        "only and cannot be accessed through other API clients."
    )
    client.messages.create.side_effect = [err, _mock_response(_VALID_L1_JSON)]
    agent = L1RegimeAnalyst(client=client)
    with patch("src.ai.agents._base.time.sleep") as fake_sleep:
        out = agent.analyze({"indicators": {}})
    assert out["status"] == "degraded_ai_terminal_error"
    assert client.messages.create.call_count == 1
    fake_sleep.assert_not_called()


def test_restricted_model_error_uses_configured_fallback():
    """403 primary 失败时,若有 fallback model,立即切 fallback。"""
    client = MagicMock()
    err = Exception(
        "Error code: 403 - This model is restricted to Claude Code clients "
        "only and cannot be accessed through other API clients."
    )
    client.messages.create.side_effect = [err, _mock_response(_VALID_L1_JSON)]
    agent = L1RegimeAnalyst(client=client)
    with (
        patch("src.ai.agents._base.effective_fallback_models",
              return_value=["claude-fallback-api-model"]),
        patch("src.ai.agents._base.time.sleep") as fake_sleep,
    ):
        out = agent.analyze({"indicators": {}})
    assert out["status"] == "success"
    assert out["fallback_model_used"] is True
    assert client.messages.create.call_count == 2
    assert client.messages.create.call_args_list[0].kwargs["model"] == "claude-sonnet-4-5-20250929"
    assert client.messages.create.call_args_list[1].kwargs["model"] == "claude-fallback-api-model"
    fake_sleep.assert_not_called()


def test_overloaded_error_stops_after_short_retry():
    """模型过载最多短重试一次,避免单层拖到数百秒。"""
    client = MagicMock()
    err = Exception(
        "Error code: 500 - Provider API error: 当前模型过载，请稍后重试 "
        "(That model is currently overloaded.)"
    )
    client.messages.create.side_effect = [err, err, _mock_response(_VALID_L1_JSON)]
    agent = L1RegimeAnalyst(client=client)
    with patch("src.ai.agents._base.time.sleep") as fake_sleep:
        out = agent.analyze({"indicators": {}})
    assert out["status"] == "degraded_ai_failed"
    assert client.messages.create.call_count == 2
    assert len(fake_sleep.call_args_list) == 1


def test_overloaded_error_uses_fallback_after_short_retry():
    """overloaded primary 两次失败后切 fallback,不再试第 3 次 primary。"""
    client = MagicMock()
    err = Exception(
        "Error code: 500 - Provider API error: 当前模型过载，请稍后重试 "
        "(That model is currently overloaded.)"
    )
    client.messages.create.side_effect = [err, err, _mock_response(_VALID_L1_JSON)]
    agent = L1RegimeAnalyst(client=client)
    with (
        patch("src.ai.agents._base.effective_fallback_models",
              return_value=["claude-fallback-api-model"]),
        patch("src.ai.agents._base.time.sleep") as fake_sleep,
    ):
        out = agent.analyze({"indicators": {}})
    assert out["status"] == "success"
    assert out["fallback_model_used"] is True
    assert client.messages.create.call_count == 3
    models = [c.kwargs["model"] for c in client.messages.create.call_args_list]
    assert models == [
        "claude-sonnet-4-5-20250929",
        "claude-sonnet-4-5-20250929",
        "claude-fallback-api-model",
    ]
    assert len(fake_sleep.call_args_list) == 1
