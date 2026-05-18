"""Sprint A — classify_fetch_failure 单测,覆盖 5 个 reason 桶 + 脱敏 + 截断。"""
from __future__ import annotations

import json

import pytest
import requests

from src.data.collectors._classify_failure import classify_fetch_failure


# ---------------- 精确 HTTP 分类 ----------------

def test_http_401_classified_as_auth_error():
    exc = RuntimeError("HTTP 401 unauthorized on /v1/metrics/x: invalid key")
    reason, msg = classify_fetch_failure(exc)
    assert reason == "auth_error"
    assert "HTTP 401" in msg


def test_http_403_classified_as_permission_denied():
    exc = RuntimeError("HTTP 403 (non-retry) on /v1/metrics/x: body")
    reason, msg = classify_fetch_failure(exc)
    assert reason == "permission_denied"
    assert "HTTP 403" in msg


def test_http_404_classified_as_endpoint_not_found():
    exc = RuntimeError("HTTP 404 not found on /v1/metrics/missing")
    reason, _ = classify_fetch_failure(exc)
    assert reason == "endpoint_not_found"


# ---------------- quota_exceeded vs rate_limited(Sprint 1.6.2 拆分)----------------

def test_http_429_bare_classified_as_rate_limited():
    """裸 429(无 quota 关键字)→ rate_limited(瞬时限流,可重试)。
    Sprint 1.6.2 之前所有 429 被一刀切归 quota_exceeded,误触发 today_complete
    全 job 短路;新逻辑只有正文含 quota/配额/rate limit 才算真 quota。"""
    exc = RuntimeError("HTTP 429 too many requests on /api/v3/foo")
    reason, _ = classify_fetch_failure(exc)
    assert reason == "rate_limited"


def test_alphanode_chinese_quota_message_classified_as_quota():
    body = {"error": {"code": "HTTP_ERROR",
                      "message": "您的 glassnode 周期内配额已用尽"}}
    exc = RuntimeError(
        f"HTTP 200 (non-retry) on /v1/metrics/market/mvrv: {json.dumps(body, ensure_ascii=False)}"
    )
    reason, _ = classify_fetch_failure(exc)
    assert reason == "quota_exceeded"


def test_english_rate_limit_message_classified_as_quota():
    """正文含 'rate limit' 关键字 → quota_exceeded(虽然字面是 rate limit,
    但行业惯例下 'rate limit exceeded' 实际指向月度配额或长期限流,
    与瞬时滑窗限流的裸 429 不同)。"""
    exc = RuntimeError("API responded with: rate limit exceeded, retry after 60s")
    reason, _ = classify_fetch_failure(exc)
    assert reason == "quota_exceeded"


def test_http_429_with_quota_keyword_in_body_classified_as_quota():
    """429 + 正文含 quota 关键字 → 仍归 quota_exceeded(真配额,触发短路)。"""
    exc = RuntimeError("HTTP 429: {\"error\": \"monthly quota exhausted\"}")
    reason, _ = classify_fetch_failure(exc)
    assert reason == "quota_exceeded"


# ---------------- network_error ----------------

def test_connection_error_classified_as_network():
    exc = requests.exceptions.ConnectionError("DNS lookup failed")
    reason, msg = classify_fetch_failure(exc)
    assert reason == "network_error"
    assert "DNS" in msg


def test_timeout_classified_as_timeout():
    exc = requests.exceptions.Timeout("Request timed out")
    reason, _ = classify_fetch_failure(exc)
    assert reason == "timeout"


# ---------------- api_error ----------------

def test_http_500_classified_as_provider_error():
    exc = RuntimeError("HTTP 500 internal server error on /api/foo")
    reason, _ = classify_fetch_failure(exc)
    assert reason == "provider_error"


# ---------------- parse_error ----------------

def test_json_decode_error_classified_as_parse():
    try:
        json.loads("not-json")
    except json.JSONDecodeError as e:
        reason, _ = classify_fetch_failure(e)
        assert reason == "parse_error"


def test_value_error_classified_as_parse():
    exc = ValueError("Unexpected schema: missing field 'timestamp'")
    reason, _ = classify_fetch_failure(exc)
    assert reason == "parse_error"


# ---------------- unknown ----------------

def test_arbitrary_exception_classified_as_unknown():
    class WeirdError(Exception):
        pass

    reason, _ = classify_fetch_failure(WeirdError("something odd happened"))
    assert reason == "unknown"


# ---------------- 脱敏 + 截断 ----------------

def test_message_redacts_api_key_token():
    exc = RuntimeError(
        "HTTP 403 on /v1/data: api_key=test-secret-value"
    )
    _, msg = classify_fetch_failure(exc)
    assert "test-secret-value" not in msg
    assert "<redacted>" in msg


def test_message_redacts_bearer_token():
    exc = RuntimeError(
        "401 unauthorized: header Bearer abc.def.GHI789xyz"
    )
    _, msg = classify_fetch_failure(exc)
    assert "abc.def.GHI789xyz" not in msg
    assert "<redacted>" in msg


def test_message_redacts_x_key_header():
    exc = RuntimeError(
        "Request failed with x-key: alphanode-private-token-XYZ"
    )
    _, msg = classify_fetch_failure(exc)
    assert "alphanode-private-token-XYZ" not in msg


def test_message_truncated_to_200_chars():
    long = "x" * 500
    exc = RuntimeError(long)
    _, msg = classify_fetch_failure(exc)
    assert len(msg) <= 200


# ---------------- 优先级 ----------------

def test_403_with_quota_keyword_still_quota_not_api():
    exc = RuntimeError("HTTP 403: rate limit on this key (api_key=x)")
    reason, _ = classify_fetch_failure(exc)
    assert reason == "quota_exceeded"


def test_network_error_takes_precedence_over_status_in_message():
    # ConnectionError 即使 message 里有 HTTP 也归 network_error
    exc = requests.exceptions.ConnectionError(
        "Failed to establish connection (would-be HTTP 502)"
    )
    reason, _ = classify_fetch_failure(exc)
    assert reason == "network_error"
