"""tests/test_emergency_simplified_a.py — Sprint 1.10-G commit 4 单测。

覆盖 v1.4 §3.3.8 简化 A 应急 AI(全 mock,真 API 留 1.10-L)。
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.ai.agents.emergency_simplified_a import (
    VALID_ACTIONS,
    EmergencySimplifiedA,
)


# ============================================================
# helpers — mock anthropic client(沿用 1.8 / 1.9 模式)
# ============================================================

def _mock_client_returning_json(payload: dict[str, Any]) -> Any:
    """构造 anthropic client.messages.create 返回 stub。"""
    client = MagicMock()
    response = MagicMock()
    # anthropic SDK shape: response.content[0].text(JSON 字符串)
    block = MagicMock()
    block.text = json.dumps(payload, ensure_ascii=False)
    block.type = "text"
    response.content = [block]
    response.model = "claude-test"
    response.usage = MagicMock(input_tokens=100, output_tokens=80)
    response.stop_reason = "end_turn"
    client.messages.create.return_value = response
    return client


def _mock_client_raising(exc: Exception) -> Any:
    client = MagicMock()
    client.messages.create.side_effect = exc
    return client


# ============================================================
# AGENT_NAME / PROMPT_FILE 基础
# ============================================================

def test_agent_name_and_prompt_file():
    assert EmergencySimplifiedA.AGENT_NAME == "emergency_simplified_a"
    assert EmergencySimplifiedA.PROMPT_FILE == "emergency_simplified_a.txt"


def test_prompt_file_exists():
    """system prompt 文件真实存在。"""
    from pathlib import Path
    p = (
        Path(__file__).resolve().parent.parent
        / "src" / "ai" / "agents" / "prompts"
        / EmergencySimplifiedA.PROMPT_FILE
    )
    assert p.exists()
    txt = p.read_text(encoding="utf-8")
    # 4 取值枚举都在 prompt
    for v in VALID_ACTIONS:
        assert v in txt, f"prompt 缺 immediate_action 取值: {v}"


# ============================================================
# happy path:4 个 immediate_action 取值
# ============================================================

@pytest.mark.parametrize("action", list(VALID_ACTIONS))
def test_happy_path_each_action(action):
    """mock AI 返回 4 个 immediate_action 取值,analyze 都能正常返回。"""
    payload = {
        "thesis_still_valid": True,
        "immediate_action": action,
        "reasoning": f"模拟决策 {action}",
    }
    client = _mock_client_returning_json(payload)
    agent = EmergencySimplifiedA()
    out = agent.analyze({
        "current_strategy_state": "LONG_HOLD",
        "triggered_at_price": 78500.0,
        "baseline_price": 75000.0,
        "pct_change": 0.0467,
        "key_factors": {"funding_rate": 0.0001, "open_interest": 1.2e9},
        "active_thesis": {
            "direction": "long",
            "lifecycle_stage": "open",
            "confidence_score": 70,
            "stop_loss_price": 72000.0,
            "break_conditions": ["BTC < 72000", "BTC < 70000", "BTC < 68000"],
        },
    }, client=client)
    assert out["status"] == "success"
    assert out["immediate_action"] == action
    assert out["thesis_still_valid"] is True
    assert "agent" in out and out["agent"] == "emergency_simplified_a"


def test_happy_path_no_active_thesis():
    """无 active_thesis(空仓)→ thesis_still_valid 应为 None。"""
    payload = {
        "thesis_still_valid": None,
        "immediate_action": "wait_next_full",
        "reasoning": "空仓 + 价格异动后回稳,等下次 run",
    }
    client = _mock_client_returning_json(payload)
    agent = EmergencySimplifiedA()
    out = agent.analyze({
        "current_strategy_state": "FLAT",
        "triggered_at_price": 78500.0,
        "baseline_price": 75000.0,
        "pct_change": 0.0467,
        "key_factors": {"funding_rate": 0.0001},
        "active_thesis": None,
    }, client=client)
    assert out["status"] == "success"
    assert out["thesis_still_valid"] is None
    assert out["immediate_action"] == "wait_next_full"


# ============================================================
# fallback:AI 失败
# ============================================================

def test_api_failure_falls_back_to_maintain():
    """anthropic client 抛异常 → _fallback_output: maintain + thesis_still_valid=None。"""
    client = _mock_client_raising(RuntimeError("simulated API error"))
    agent = EmergencySimplifiedA()
    out = agent.analyze({
        "current_strategy_state": "LONG_HOLD",
        "triggered_at_price": 78500.0,
        "baseline_price": 75000.0,
        "pct_change": 0.0467,
        "key_factors": {},
        "active_thesis": None,
    }, client=client)
    assert out["status"] == "degraded" or out["status"].startswith("degraded")
    assert out["immediate_action"] == "maintain"
    assert out["thesis_still_valid"] is None
    assert "fallback" in out["reasoning"]


def test_json_parse_failure_falls_back():
    """AI 返回非 JSON 文本 → BaseAgent 2 attempt 重试后 fallback。"""
    client = MagicMock()
    response = MagicMock()
    block = MagicMock()
    block.text = "not a JSON, just text"
    block.type = "text"
    response.content = [block]
    response.model = "claude-test"
    response.usage = MagicMock(input_tokens=50, output_tokens=10)
    response.stop_reason = "end_turn"
    client.messages.create.return_value = response

    agent = EmergencySimplifiedA()
    out = agent.analyze({
        "current_strategy_state": "FLAT",
        "triggered_at_price": 75000.0, "baseline_price": 75000.0,
        "pct_change": 0.0,
        "key_factors": {}, "active_thesis": None,
    }, client=client)
    assert "degraded" in out["status"]
    assert out["immediate_action"] == "maintain"


# ============================================================
# normalize_output 校验
# ============================================================

def test_normalize_output_valid_passthrough():
    out = {"immediate_action": "maintain",
           "thesis_still_valid": True, "reasoning": "x"}
    normed = EmergencySimplifiedA.normalize_output(out)
    assert normed is out  # 不改


def test_normalize_output_invalid_action_normalizes_to_maintain():
    """非法 action(typo)→ 自动改 maintain + notes 标记。"""
    out = {"immediate_action": "invalid_value",
           "thesis_still_valid": True, "reasoning": "x"}
    normed = EmergencySimplifiedA.normalize_output(out)
    assert normed["immediate_action"] == "maintain"
    assert any("invalid_action_normalized" in n for n in (normed.get("notes") or []))


def test_normalize_output_non_dict():
    """AI 返回非 dict(如 list)→ 完全 fallback。"""
    normed = EmergencySimplifiedA.normalize_output(["not", "a", "dict"])
    assert normed["immediate_action"] == "maintain"
    assert "degraded" in normed["status"]


# ============================================================
# is_valid_action
# ============================================================

@pytest.mark.parametrize("action,expected", [
    ("maintain", True), ("emergency_exit", True),
    ("tighten_stop", True), ("wait_next_full", True),
    ("invalid", False), ("", False), (None, False),
    ("MAINTAIN", False),  # case-sensitive
])
def test_is_valid_action(action, expected):
    assert EmergencySimplifiedA.is_valid_action(action) is expected


# ============================================================
# _build_user_prompt 包含关键字段
# ============================================================

def test_build_user_prompt_includes_active_thesis():
    agent = EmergencySimplifiedA()
    prompt = agent._build_user_prompt({
        "current_strategy_state": "LONG_HOLD",
        "triggered_at_price": 78500.0,
        "baseline_price": 75000.0,
        "pct_change": 0.0467,
        "key_factors": {"funding_rate": 0.0001},
        "active_thesis": {
            "direction": "long", "lifecycle_stage": "open",
            "confidence_score": 70, "stop_loss_price": 72000.0,
            "break_conditions": ["BTC < 72000"],
        },
    })
    assert "LONG_HOLD" in prompt
    assert "78500" in prompt
    assert "75000" in prompt
    assert "long" in prompt
    assert "72000" in prompt
    assert "BTC < 72000" in prompt


def test_build_user_prompt_no_active_thesis():
    agent = EmergencySimplifiedA()
    prompt = agent._build_user_prompt({
        "current_strategy_state": "FLAT",
        "triggered_at_price": 78500.0,
        "baseline_price": 75000.0,
        "pct_change": -0.05,
        "key_factors": {},
        "active_thesis": None,
    })
    assert "FLAT" in prompt
    assert "无(空仓状态)" in prompt
