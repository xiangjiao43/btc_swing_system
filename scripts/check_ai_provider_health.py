#!/usr/bin/env python3
"""Minimal AI provider health check.

This script loads the same AI provider configuration used by the pipeline and
sends one tiny "ping" request. It never prints API keys, tokens, or raw .env
contents.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ai.client import (  # noqa: E402
    build_anthropic_client,
    effective_fallback_models,
    effective_model,
    normalize_base_url,
)


def _host_only(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return parsed.netloc or parsed.path or None


def _status_from_exception(exc: BaseException) -> str:
    status_code = getattr(exc, "status_code", None)
    if status_code:
        return str(status_code)
    msg = str(exc).lower()
    if "restricted to claude code clients" in msg or "cannot be accessed through other api clients" in msg:
        return "403"
    if "overloaded" in msg or "当前模型过载" in msg:
        return "500"
    if "timeout" in msg or "timed out" in msg:
        return "timeout"
    return "other"


def _summarize_error(exc: BaseException) -> str:
    text = str(exc).replace("\n", " ")
    return text[:500]


def _run_ping(model: str, *, timeout: float) -> dict[str, Any]:
    base = normalize_base_url(os.getenv("OPENAI_API_BASE"))
    out: dict[str, Any] = {
        "provider": "anthropic_sdk_via_configured_base_url",
        "base_url_host": _host_only(base),
        "model": model,
        "timeout_sec": timeout,
        "status": "unknown",
        "elapsed_seconds": None,
        "error_type": None,
        "error_message_summary": None,
        "response_model": None,
    }
    client = build_anthropic_client(timeout=timeout)
    if client is None:
        out["status"] = "client_unavailable"
        return out

    t0 = time.time()
    try:
        resp = client.messages.create(
            model=model,
            system="Return plain text only.",
            messages=[{"role": "user", "content": "ping, respond with ok"}],
            max_tokens=8,
            temperature=0.0,
        )
        out["status"] = "ok"
        out["response_model"] = str(getattr(resp, "model", None) or "")
    except Exception as exc:
        out["status"] = _status_from_exception(exc)
        out["error_type"] = type(exc).__name__
        out["error_message_summary"] = _summarize_error(exc)
    finally:
        out["elapsed_seconds"] = round(time.time() - t0, 2)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    model = args.model or effective_model()
    result = {
        "openai_api_key": "exists_hidden" if os.getenv("OPENAI_API_KEY") else "missing",
        "anthropic_api_key": "exists_hidden" if os.getenv("ANTHROPIC_API_KEY") else "missing",
        "primary": _run_ping(model, timeout=args.timeout),
        "fallback": None,
    }
    fallback_models = effective_fallback_models(model)
    if fallback_models:
        result["fallback"] = [
            _run_ping(fallback_model, timeout=args.timeout)
            for fallback_model in fallback_models
        ]
    else:
        result["fallback"] = "no_fallback_model_configured"

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
