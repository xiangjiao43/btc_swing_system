"""
_classify_failure.py — Sprint A(数据真实性透明化底座)

把 collector 抛出的异常 / 错误响应分类成一个 `failure_reason` 标签 +
一段 ≤ 200 字符的脱敏 short_message,用来写 fetch_attempts 表。

failure_reason 桶:
  quota_exceeded     HTTP 429 + 中转站配额话术(quota / rate limit / 配额)
  auth_error         HTTP 401,API key 无效 / 未授权
  permission_denied  HTTP 403,套餐不支持 / endpoint 权限不足
  endpoint_not_found HTTP 404,endpoint 不存在 / 配置错误
  provider_error     HTTP 5xx,上游或中转站服务异常
  timeout            requests.Timeout
  network_error      requests.ConnectionError / DNS / 其他网络层
  api_error          其他 HTTP 4xx
  parse_error        JSONDecodeError / 应答 schema 不匹配
  unknown            以上都不命中
"""
from __future__ import annotations

import json
import re
from typing import Tuple

import requests


_MAX_MESSAGE_LEN = 200

_QUOTA_KEYWORDS = ("quota", "rate limit", "rate-limit", "配额", "ratelimit")
_HTTP_PATTERN = re.compile(r"\bHTTP\s+(\d{3})\b", re.IGNORECASE)

_REDACT_PATTERNS = (
    re.compile(r"(api[-_]?key)\s*[=:]\s*\S+", re.IGNORECASE),
    re.compile(r"\bBearer\s+\S+", re.IGNORECASE),
    re.compile(r"\b(x-key)\s*:\s*\S+", re.IGNORECASE),
    re.compile(r"\b(authorization)\s*:\s*\S+", re.IGNORECASE),
)


def _scrub(message: str) -> str:
    out = message
    for pat in _REDACT_PATTERNS:
        out = pat.sub(lambda m: f"{m.group(1) if m.lastindex else 'auth'}=<redacted>", out)
    return out


def _truncate(message: str) -> str:
    if len(message) <= _MAX_MESSAGE_LEN:
        return message
    return message[: _MAX_MESSAGE_LEN - 1] + "…"


def _has_quota_keyword(message: str) -> bool:
    low = message.lower()
    return any(kw in low for kw in _QUOTA_KEYWORDS) or "配额" in message


def classify_fetch_failure(exc: BaseException) -> Tuple[str, str]:
    """异常 → (failure_reason, short_message)。

    顺序:timeout / network_error → quota_exceeded(429 或 quota 话术)→
    401/403/404 精确分类 → provider_error(5xx) → api_error(其他 4xx)
    → parse_error(JSON / schema)→ unknown。
    """
    raw = str(exc) if str(exc) else type(exc).__name__
    msg = _truncate(_scrub(raw))

    if isinstance(exc, requests.exceptions.Timeout):
        return "timeout", msg

    if isinstance(exc, requests.exceptions.RequestException) and not isinstance(
        exc, requests.exceptions.HTTPError
    ):
        return "network_error", msg

    http_match = _HTTP_PATTERN.search(raw)
    status: int = int(http_match.group(1)) if http_match else 0

    if status == 429 or _has_quota_keyword(raw):
        return "quota_exceeded", msg

    if status == 401:
        return "auth_error", msg

    if status == 403:
        return "permission_denied", msg

    if status == 404:
        return "endpoint_not_found", msg

    if 500 <= status < 600:
        return "provider_error", msg

    if 400 <= status < 500:
        return "api_error", msg

    if isinstance(exc, json.JSONDecodeError) or isinstance(exc, ValueError):
        return "parse_error", msg

    type_name = type(exc).__name__
    if "Schema" in type_name or "Parse" in type_name or "Decode" in type_name:
        return "parse_error", msg

    if isinstance(exc, requests.exceptions.HTTPError):
        return "api_error", msg

    return "unknown", msg
