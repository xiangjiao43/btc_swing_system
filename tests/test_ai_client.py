"""
tests/test_ai_client.py — Sprint 1.5c C6:anthropic client helpers.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from src.ai.client import (
    DEFAULT_MODEL, effective_model, extract_model, extract_text,
    extract_usage, normalize_base_url,
)


def test_normalize_base_url_strips_v1_suffix():
    assert normalize_base_url("https://us.novaiapi.com/v1") == "https://us.novaiapi.com"
    assert normalize_base_url("https://us.novaiapi.com/v1/") == "https://us.novaiapi.com"
    assert normalize_base_url("https://host.com/") == "https://host.com"
    assert normalize_base_url(None) is None
    assert normalize_base_url("") is None


def test_effective_model_defaults():
    import os
    os.environ.pop("OPENAI_MODEL", None)
    assert effective_model() == DEFAULT_MODEL
    assert effective_model("my-custom") == "my-custom"


def test_extract_text_anthropic_shape():
    resp = MagicMock()
    block = MagicMock()
    block.text = "hello from anthropic"
    resp.content = [block]
    assert extract_text(resp) == "hello from anthropic"


def test_extract_text_empty_content_returns_empty():
    resp = MagicMock()
    resp.content = []
    # empty list → ""
    assert extract_text(resp) == ""


def test_extract_usage_input_output_tokens():
    resp = MagicMock()
    resp.usage = MagicMock(input_tokens=150, output_tokens=75)
    assert extract_usage(resp, "input_tokens") == 150
    assert extract_usage(resp, "output_tokens") == 75
    # 别名支持
    assert extract_usage(resp, "prompt_tokens") == 150
    assert extract_usage(resp, "completion_tokens") == 75


def test_extract_model_with_fallback():
    resp = MagicMock()
    resp.model = "claude-sonnet-4-5-20250929"
    assert extract_model(resp, "fallback") == "claude-sonnet-4-5-20250929"
    resp2 = MagicMock(spec=[])  # no model attribute
    assert extract_model(resp2, "fallback-model") == "fallback-model"
