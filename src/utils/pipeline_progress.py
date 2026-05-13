"""Small stdout progress logs for manual pipeline runs.

This module is intentionally tiny and side-effect free: it only prints stage
start/end/failure timing so a manual `run_pipeline_once.py` no longer looks
stuck after env loading. It does not change any trading decision.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import time
from typing import Iterator


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def pipeline_stage(name: str) -> Iterator[None]:
    """Print a stage start/end pair to stdout with elapsed seconds."""
    started_at = _utc_now()
    t0 = time.perf_counter()
    print(f"[pipeline] START {name} started_at={started_at}", flush=True)
    try:
        yield
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        print(
            "[pipeline] FAIL "
            f"{name} elapsed={elapsed:.2f}s error_type={type(exc).__name__}",
            flush=True,
        )
        raise
    else:
        elapsed = time.perf_counter() - t0
        print(f"[pipeline] END {name} elapsed={elapsed:.2f}s success=true", flush=True)
