"""Pipeline stage progress logging.

This module is intentionally small: it only records stage start/end/failure
timing to stdout and to `/private/tmp/pipeline_debug_logs/`. It does not
change any trading decision.
"""

from __future__ import annotations

import atexit
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import os
import time
from typing import Any, Iterator


LOG_DIR = Path("/private/tmp/pipeline_debug_logs")
_LOG_PATH: Path | None = None
_RUN_LABEL: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_pipeline_logging(
    *,
    run_label: str = "manual",
    validation: bool = False,
) -> Path:
    """Initialize a per-run log file and return its path."""
    global _LOG_PATH, _RUN_LABEL
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    _RUN_LABEL = run_label
    if validation:
        path = LOG_DIR / "validation_run.log"
        path.write_text("", encoding="utf-8")
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = LOG_DIR / (
            f"pipeline_{stamp}_{os.getpid()}_{time.time_ns()}_{run_label}.jsonl"
        )
    _LOG_PATH = path
    _write_json({
        "event": "pipeline_log_started",
        "run_label": run_label,
        "validation": validation,
        "timestamp_utc": utc_now(),
        "log_path": str(path),
    })
    return path


def current_log_path() -> Path:
    if _LOG_PATH is None:
        return init_pipeline_logging(run_label="auto")
    return _LOG_PATH


def _safe_message(value: Any, *, max_chars: int = 300) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\n", "\\n")
    return text[:max_chars]


def _write_json(payload: dict[str, Any]) -> None:
    path = current_log_path() if _LOG_PATH is None else _LOG_PATH
    record = {"run_label": _RUN_LABEL, **payload}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def _print_line(line: str) -> None:
    print(line, flush=True)


class StageSpan:
    def __init__(self, name: str) -> None:
        self.name = name
        self.started_at = utc_now()
        self.ended_at: str | None = None
        self.elapsed_sec: float | None = None
        self.status = "success"
        self.error_type: str | None = None
        self.error_message: str | None = None
        self._t0 = time.perf_counter()

    def set_status(self, status: str, *, message: Any = None) -> None:
        if status in {"success", "failure", "degraded", "skipped", "partial"}:
            self.status = status
        if message is not None:
            self.error_message = _safe_message(message)

    def mark_degraded(self, message: Any = None) -> None:
        self.set_status("degraded", message=message)

    def mark_skipped(self, message: Any = None) -> None:
        self.set_status("skipped", message=message)

    def fail(self, exc: BaseException) -> None:
        self.status = "failure"
        self.error_type = type(exc).__name__
        self.error_message = _safe_message(exc)

    def finish(self) -> None:
        self.ended_at = utc_now()
        self.elapsed_sec = round(time.perf_counter() - self._t0, 3)
        line = (
            f"[pipeline] END {self.name} status={self.status} "
            f"elapsed={self.elapsed_sec:.2f}s"
        )
        if self.error_type:
            line += f" error_type={self.error_type}"
        _print_line(line)
        _write_json({
            "event": "stage_finished",
            "stage_name": self.name,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "elapsed_sec": self.elapsed_sec,
            "status": self.status,
            "error_type": self.error_type,
            "error_message": self.error_message,
        })


def record_instant_stage(
    name: str,
    *,
    status: str = "success",
    message: Any = None,
) -> None:
    span = StageSpan(name)
    _print_line(f"[pipeline] START {name} started_at={span.started_at}")
    _write_json({
        "event": "stage_started",
        "stage_name": name,
        "started_at": span.started_at,
        "status": "started",
    })
    span.set_status(status, message=message)
    span.finish()


def record_pipeline_result(status: str, *, extra: dict[str, Any] | None = None) -> None:
    _write_json({
        "event": "pipeline_result",
        "timestamp_utc": utc_now(),
        "status": status,
        "extra": extra or {},
    })


@contextmanager
def pipeline_stage(name: str) -> Iterator[StageSpan]:
    """Record a stage start/end pair to stdout and the per-run JSONL log."""
    span = StageSpan(name)
    _print_line(f"[pipeline] START {name} started_at={span.started_at}")
    _write_json({
        "event": "stage_started",
        "stage_name": name,
        "started_at": span.started_at,
        "status": "started",
    })
    try:
        yield span
    except Exception as exc:
        span.fail(exc)
        span.finish()
        raise
    else:
        span.finish()


def _close_unfinished_log() -> None:
    if _LOG_PATH is not None:
        _write_json({
            "event": "pipeline_process_exit",
            "timestamp_utc": utc_now(),
        })


atexit.register(_close_unfinished_log)
