#!/usr/bin/env python3
"""Minimal Glassnode health check.

Runs only a few low-cost requests using the project Glassnode configuration.
Never prints API keys, tokens, or raw sensitive URLs.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import _env_loader  # noqa: F401,E402
from src.data.collectors._config_loader import load_source_config  # noqa: E402


CHECKS = [
    {
        "metric": "mvrv",
        "endpoint": "/v1/metrics/market/mvrv",
        "note": "baseline existing Glassnode metric",
    },
    {
        "metric": "lth_sopr",
        "endpoint": "/v1/metrics/indicators/sopr_more_155",
        "note": "Layer A holder behavior endpoint",
    },
    {
        "metric": "reserve_risk",
        "endpoint": "/v1/metrics/indicators/reserve_risk",
        "note": "Layer A cycle valuation endpoint",
    },
]


def _host_only(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return "<invalid-url>"
    return f"{parsed.scheme}://{parsed.netloc}"


def _status_from_http(status_code: int) -> str:
    if status_code == 401:
        return "401"
    if status_code == 403:
        return "403"
    if status_code == 404:
        return "404"
    if status_code == 429:
        return "429"
    if 500 <= status_code < 600:
        return "5xx"
    if 400 <= status_code < 500:
        return "4xx"
    return "other"


def _summarize_error(text: str) -> str:
    cleaned = " ".join((text or "").split())
    return cleaned[:180] if cleaned else ""


def _check_one(
    session: requests.Session,
    base_url: str,
    item: dict[str, str],
    *,
    timeout: int,
    since_unix: int,
) -> dict[str, object]:
    endpoint = item["endpoint"]
    url = f"{base_url.rstrip('/')}{endpoint}"
    started = time.monotonic()
    result: dict[str, object] = {
        "metric": item["metric"],
        "endpoint": endpoint,
        "note": item.get("note", ""),
        "status": "unknown",
        "elapsed_seconds": None,
        "error_type": None,
        "error_summary": None,
        "latest_value_present": False,
    }
    try:
        resp = session.get(
            url,
            params={"a": "BTC", "i": "24h", "s": since_unix},
            timeout=timeout,
        )
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        if resp.status_code != 200:
            result["status"] = _status_from_http(resp.status_code)
            result["error_type"] = f"http_{resp.status_code}"
            result["error_summary"] = _summarize_error(resp.text)
            return result
        try:
            body = resp.json()
        except Exception as exc:
            result["status"] = "parse_error"
            result["error_type"] = type(exc).__name__
            result["error_summary"] = "JSON parse failed"
            return result
        rows = body.get("data") if isinstance(body, dict) else body
        if isinstance(rows, list):
            result["status"] = "ok"
            result["latest_value_present"] = any(
                isinstance(row, dict) and row.get("v") is not None
                for row in rows[-5:]
            )
            return result
        result["status"] = "parse_error"
        result["error_type"] = "unexpected_shape"
        result["error_summary"] = f"Unexpected response shape: {type(body).__name__}"
        return result
    except requests.exceptions.Timeout as exc:
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        result["status"] = "timeout"
        result["error_type"] = type(exc).__name__
        result["error_summary"] = "Request timed out"
        return result
    except requests.exceptions.RequestException as exc:
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        result["status"] = "network_error"
        result["error_type"] = type(exc).__name__
        result["error_summary"] = _summarize_error(str(exc))
        return result


def main() -> int:
    cfg = load_source_config("glassnode")
    base_url = cfg.get("base_url") or ""
    timeout = int(cfg.get("timeout_sec") or 15)
    header_name = cfg.get("api_key_header_name") or "x-key"
    api_key = cfg.get("api_key") or ""

    session = requests.Session()
    session.headers.update({
        "accept": "application/json",
        "User-Agent": "btc_swing_system/glassnode-health-check",
    })
    if api_key:
        session.headers[header_name] = api_key

    since = int((datetime.now(timezone.utc) - timedelta(days=7)).timestamp())
    out = {
        "provider": "glassnode",
        "base_url_host": _host_only(base_url),
        "api_key": "exists, hidden" if api_key else "missing",
        "timeout_seconds": timeout,
        "checks": [
            _check_one(session, base_url, item, timeout=timeout, since_unix=since)
            for item in CHECKS
        ],
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
