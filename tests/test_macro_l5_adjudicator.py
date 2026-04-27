"""tests/test_macro_l5_adjudicator.py — Sprint 2.6-E Commit 1。

Mock 的 anthropic client → 验证:
- 解析 §6.8 schema 合法 JSON
- 关键字段越界 → 拒绝
- JSON 解析失败 / schema 失败 → 重试 1 次
- 客户端不可用 → 直接返回 None
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from src.ai.macro_l5_adjudicator import (
    MacroL5Adjudicator,
    _parse_json_loose,
    _validate_layer5_output,
)


def _make_response(text: str) -> MagicMock:
    block = MagicMock()
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    resp.usage = MagicMock(input_tokens=100, output_tokens=200)
    resp.model = "claude-sonnet-4-5-mock"
    return resp


def _make_client(responses: list[str]) -> MagicMock:
    client = MagicMock()
    client.messages.create.side_effect = [_make_response(r) for r in responses]
    return client


_VALID_PAYLOAD = {
    "macro_stance": "risk_off",
    "macro_trend": "deteriorating",
    "structured_macro": {"dxy": 105.5, "vix": 28.0},
    "active_macro_tags": ["dxy_strengthening", "vix_elevated"],
    "active_event_summaries": [
        {"name": "FOMC Rate Decision", "type": "fomc", "severity": 5,
         "btc_impact": "bearish", "duration": "1-3 days", "confidence": 0.8},
    ],
    "extreme_event_detected": False,
    "extreme_event_details": None,
    "adjustment_guidance": {
        "stance_modifier": "challenge",
        "position_cap_multiplier": 0.85,
        "permission_adjustment": "tighten",
        "note": "FOMC < 24h + DXY 走强 → 缩仓位防尾部",
    },
    "macro_headwind_score": -3.5,
}


# ============================================================
# Schema validation
# ============================================================

def test_validate_accepts_full_valid_payload():
    out = _validate_layer5_output(_VALID_PAYLOAD)
    assert out is not None
    assert out["macro_stance"] == "risk_off"
    assert out["macro_trend"] == "deteriorating"
    assert out["macro_headwind_score"] == -3.5
    assert out["adjustment_guidance"]["position_cap_multiplier"] == 0.85
    assert out["adjustment_guidance"]["stance_modifier"] == "challenge"


def test_validate_rejects_invalid_macro_stance():
    bad = dict(_VALID_PAYLOAD, macro_stance="risk_super_off")
    assert _validate_layer5_output(bad) is None


def test_validate_rejects_invalid_macro_trend():
    bad = dict(_VALID_PAYLOAD, macro_trend="exploding")
    assert _validate_layer5_output(bad) is None


def test_validate_rejects_score_out_of_range():
    bad = dict(_VALID_PAYLOAD, macro_headwind_score=-15.0)
    assert _validate_layer5_output(bad) is None
    bad2 = dict(_VALID_PAYLOAD, macro_headwind_score=99.0)
    assert _validate_layer5_output(bad2) is None


def test_validate_rejects_position_cap_multiplier_out_of_range():
    bad = dict(_VALID_PAYLOAD)
    bad["adjustment_guidance"] = dict(
        bad["adjustment_guidance"], position_cap_multiplier=0.3,
    )
    assert _validate_layer5_output(bad) is None
    bad["adjustment_guidance"]["position_cap_multiplier"] = 1.5
    assert _validate_layer5_output(bad) is None


def test_validate_rejects_invalid_stance_modifier():
    bad = dict(_VALID_PAYLOAD)
    bad["adjustment_guidance"] = dict(
        bad["adjustment_guidance"], stance_modifier="extreme_unicorn",
    )
    assert _validate_layer5_output(bad) is None


def test_validate_rejects_invalid_permission_adjustment():
    bad = dict(_VALID_PAYLOAD)
    bad["adjustment_guidance"] = dict(
        bad["adjustment_guidance"], permission_adjustment="loosen_a_bit",
    )
    assert _validate_layer5_output(bad) is None


# ============================================================
# JSON parser
# ============================================================

def test_parse_json_loose_handles_markdown_fence():
    text = "```json\n" + json.dumps(_VALID_PAYLOAD) + "\n```"
    parsed = _parse_json_loose(text)
    assert parsed is not None
    assert parsed["macro_stance"] == "risk_off"


def test_parse_json_loose_handles_wrapped_text():
    text = "thinking...\n" + json.dumps(_VALID_PAYLOAD) + "\nend."
    parsed = _parse_json_loose(text)
    assert parsed is not None


def test_parse_json_loose_returns_none_on_garbage():
    assert _parse_json_loose("not even close to json") is None
    assert _parse_json_loose("") is None
    assert _parse_json_loose(None) is None


# ============================================================
# Adjudicator end-to-end (with injected mock client)
# ============================================================

def test_adjudicator_returns_normalized_output_on_success():
    client = _make_client([json.dumps(_VALID_PAYLOAD)])
    adj = MacroL5Adjudicator(client=client)
    out = adj.adjudicate({"data_completeness_pct": 75})
    assert out is not None
    assert out["macro_stance"] == "risk_off"
    assert out["macro_headwind_score"] == -3.5
    assert "_meta" in out
    assert out["_meta"]["attempts"] == 1


def test_adjudicator_retries_once_on_bad_json_then_succeeds():
    client = _make_client(["malformed { not json", json.dumps(_VALID_PAYLOAD)])
    adj = MacroL5Adjudicator(client=client)
    out = adj.adjudicate({"data_completeness_pct": 75})
    assert out is not None
    assert out["_meta"]["attempts"] == 2


def test_adjudicator_returns_none_when_both_attempts_fail():
    client = _make_client(["garbage 1", "garbage 2"])
    adj = MacroL5Adjudicator(client=client)
    out = adj.adjudicate({"data_completeness_pct": 75})
    assert out is None


def test_adjudicator_returns_none_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(
        "src.ai.macro_l5_adjudicator.build_anthropic_client",
        lambda **_: None,
    )
    adj = MacroL5Adjudicator()
    assert adj.adjudicate({"data_completeness_pct": 75}) is None


def test_adjudicator_returns_none_when_schema_invalid_both_times():
    bad = dict(_VALID_PAYLOAD, macro_stance="totally_made_up")
    client = _make_client([json.dumps(bad), json.dumps(bad)])
    adj = MacroL5Adjudicator(client=client)
    assert adj.adjudicate({"data_completeness_pct": 75}) is None


def test_adjudicator_handles_exception_then_succeeds():
    client = MagicMock()
    client.messages.create.side_effect = [
        RuntimeError("network blip"),
        _make_response(json.dumps(_VALID_PAYLOAD)),
    ]
    adj = MacroL5Adjudicator(client=client)
    out = adj.adjudicate({"data_completeness_pct": 75})
    assert out is not None
    assert out["_meta"]["attempts"] == 2
