#!/usr/bin/env python3
"""Run Layer A spot-cycle strategy once.

This entrypoint only runs Layer A A1-A5 + Spot Validator and persists the
latest Layer A result. It does not run Layer B, does not create thesis, and
does not touch virtual account.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import _env_loader  # noqa: F401
from src.data.storage.connection import get_connection, init_db
from src.pipeline.layer_a_spot_runner import LayerASpotStrategyRunner
from src.utils.pipeline_progress import (
    init_pipeline_logging,
    pipeline_stage,
    record_instant_stage,
)


def _summary(result: Any, log_path: Path) -> dict[str, Any]:
    layer_a = result.layer_a_spot_strategy or {}
    a1 = layer_a.get("a1_cycle_stage") or {}
    a5 = layer_a.get("a5_spot_adjudicator") or {}
    validator = layer_a.get("validator") or {}
    return {
        "run_id": result.run_id,
        "generated_at_utc": result.generated_at_utc,
        "generated_at_bjt": result.generated_at_bjt,
        "persisted": result.persisted,
        "status": result.status,
        "duration_ms": result.duration_ms,
        "pipeline_log_path": str(log_path),
        "a1_cycle_stage": a1.get("cycle_stage"),
        "a5_spot_action": a5.get("spot_action"),
        "validator_passed": validator.get("passed"),
        "violations": validator.get("violations") or [],
        "warnings": validator.get("warnings") or [],
        "degraded_stages": result.degraded_stages,
        "failures": result.failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trigger", default="manual")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--validate-stages", action="store_true")
    parser.add_argument("--klines-lookback", type=int, default=600)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    log_path = init_pipeline_logging(
        run_label=f"layer_a_{args.trigger}",
        validation=bool(args.validate_stages),
    )
    record_instant_stage("load env", status="success")
    with_args = {
        "run_trigger": args.trigger,
        "persist": not args.dry_run,
        "validate_stages": bool(args.validate_stages),
    }

    with pipeline_stage("init_db") as span:
        if args.validate_stages:
            span.mark_skipped("--validate-stages does not initialize/migrate DB")
        else:
            init_db(verbose=False)
    conn = get_connection()
    try:
        runner = LayerASpotStrategyRunner(conn, klines_lookback=args.klines_lookback)
        result = runner.run(**with_args)
    finally:
        conn.close()

    out = _summary(result, log_path)
    if args.json:
        out["layer_a_spot_strategy"] = result.layer_a_spot_strategy
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))

    if result.failures:
        return 2
    if result.degraded_stages:
        return 1
    if not result.persisted and not (args.dry_run or args.validate_stages):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
