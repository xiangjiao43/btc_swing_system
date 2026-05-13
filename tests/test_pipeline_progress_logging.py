from __future__ import annotations

import json
from pathlib import Path

from src.ai.client import DEFAULT_TIMEOUT_SEC
from src.utils.pipeline_progress import (
    init_pipeline_logging,
    pipeline_stage,
    record_instant_stage,
    record_pipeline_result,
)


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_pipeline_progress_writes_validation_log():
    path = init_pipeline_logging(run_label="pytest", validation=True)
    assert str(path) == "/private/tmp/pipeline_debug_logs/validation_run.log"

    with pipeline_stage("pytest success stage") as span:
        span.set_status("degraded", message="synthetic degraded")
    record_instant_stage("pytest skipped stage", status="skipped", message="skip")
    record_pipeline_result("degraded", extra={"run_id": "pytest"})

    records = _read_jsonl(path)
    finished = [r for r in records if r.get("event") == "stage_finished"]
    assert any(r["stage_name"] == "pytest success stage" for r in finished)
    assert any(r["status"] == "degraded" for r in finished)
    assert any(r["status"] == "skipped" for r in finished)
    assert records[-1]["event"] == "pipeline_result"
    assert records[-1]["status"] == "degraded"


def test_pipeline_progress_unique_logs_do_not_overwrite_history():
    first = init_pipeline_logging(run_label="pytest", validation=False)
    second = init_pipeline_logging(run_label="pytest", validation=False)
    assert first.parent == Path("/private/tmp/pipeline_debug_logs")
    assert second.parent == Path("/private/tmp/pipeline_debug_logs")
    assert first != second


def test_ai_client_default_timeout_is_120_seconds():
    assert DEFAULT_TIMEOUT_SEC == 120.0
