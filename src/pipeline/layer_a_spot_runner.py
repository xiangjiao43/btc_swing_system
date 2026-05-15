"""Standalone Layer A spot-cycle runner.

This module runs only the Layer A A1-A5 spot strategy track. It does not run
Layer B L1-L5 / Master / Validator, does not create thesis, and does not touch
virtual account state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import time
import uuid
from typing import Any
from zoneinfo import ZoneInfo

from ..ai.context_builder import ContextBuilder
from ..ai.orchestrator import AIOrchestrator
from ..ai.spot_cycle_context_builder import SpotCycleContextBuilder
from ..data.freshness import compute_stale_state
from ..data.storage.dao import LatestLayerASpotStrategyDAO
from ..utils.pipeline_progress import (
    pipeline_stage,
    record_instant_stage,
    record_pipeline_result,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _bjt_iso_from_utc(utc_iso: str) -> str:
    dt = datetime.fromisoformat(utc_iso.replace("Z", "+00:00"))
    return dt.astimezone(ZoneInfo("Asia/Shanghai")).isoformat()


def _bjt_display_from_utc(utc_iso: str) -> str:
    dt = datetime.fromisoformat(utc_iso.replace("Z", "+00:00"))
    return dt.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S BJT")


@dataclass
class LayerASpotRunResult:
    run_id: str
    generated_at_utc: str
    generated_at_bjt: str
    run_trigger: str
    persisted: bool
    status: str
    duration_ms: int
    layer_a_spot_strategy: dict[str, Any] = field(default_factory=dict)
    failures: list[dict[str, Any]] = field(default_factory=list)
    degraded_stages: list[str] = field(default_factory=list)


class LayerASpotStrategyRunner:
    def __init__(self, conn: Any, *, klines_lookback: int = 600) -> None:
        self.conn = conn
        self.klines_lookback = klines_lookback

    def run(
        self,
        *,
        run_trigger: str = "manual",
        persist: bool = True,
        validate_stages: bool = False,
    ) -> LayerASpotRunResult:
        started = time.time()
        run_id = uuid.uuid4().hex
        generated_at_utc = _utc_now_iso()
        generated_at_bjt = _bjt_display_from_utc(generated_at_utc)
        failures: list[dict[str, Any]] = []
        degraded: list[str] = []
        layer_a: dict[str, Any] = {}
        persisted = False
        status = "success"

        try:
            previous_layer_a = None
            if not validate_stages:
                latest = LatestLayerASpotStrategyDAO.get_latest(self.conn)
                previous_layer_a = (latest or {}).get("layer_a") if latest else None
            with pipeline_stage("build data context"):
                context = ContextBuilder(
                    self.conn,
                    klines_lookback=self.klines_lookback,
                ).build_full_context()
            with pipeline_stage("compute data freshness"):
                stale_map, hours_map = compute_stale_state(self.conn)
                context["_source_stale_map"] = stale_map
                context["_source_hours_map"] = hours_map
            with pipeline_stage("build Layer A context"):
                context["layer_a_spot_context"] = (
                    SpotCycleContextBuilder(self.conn)
                    .build_spot_cycle_context(existing_context=context)
                )
                if previous_layer_a:
                    context["layer_a_spot_context"]["previous_layer_a_state"] = {
                        "run_id": previous_layer_a.get("run_id"),
                        "generated_at_bjt": previous_layer_a.get("generated_at_bjt"),
                        "cycle_stage_model_version": previous_layer_a.get(
                            "cycle_stage_model_version"
                        ),
                        "a1_cycle_stage": previous_layer_a.get("a1_cycle_stage") or {},
                        "a5_spot_adjudicator": previous_layer_a.get(
                            "a5_spot_adjudicator"
                        ) or {},
                        "stage_transition": previous_layer_a.get("stage_transition") or {},
                    }

            if validate_stages:
                for name in (
                    "run Layer A spot strategy",
                    "run Layer A A1",
                    "run Layer A A2",
                    "run Layer A A3",
                    "run Layer A A4",
                    "run Layer A A5",
                    "spot validator",
                    "persist Layer A",
                ):
                    record_instant_stage(
                        name,
                        status="skipped",
                        message="--validate-stages skips Layer A AI and persist",
                    )
                status = "success"
            else:
                with pipeline_stage("run Layer A spot strategy") as span:
                    layer_a = AIOrchestrator().run_layer_a_spot_only(context)
                    validator = layer_a.get("validator") or {}
                    if not validator.get("passed", True):
                        span.mark_degraded("Layer A spot validator reported warnings/violations")
                        degraded.append("layer_a_spot_validator")
                with pipeline_stage("spot validator") as span:
                    validator = layer_a.get("validator") or {}
                    if not validator.get("passed", True):
                        span.mark_degraded("Layer A validator did not pass")
                        degraded.append("spot_validator")

                layer_a.update({
                    "run_id": run_id,
                    "generated_at_utc": generated_at_utc,
                    "generated_at_bjt": generated_at_bjt,
                    "run_trigger": run_trigger,
                    "source": "latest_layer_a_spot_strategy",
                })
                status = "degraded" if degraded else "success"
                if persist:
                    with pipeline_stage("persist Layer A"):
                        LatestLayerASpotStrategyDAO.upsert(
                            self.conn,
                            run_id=run_id,
                            generated_at_utc=generated_at_utc,
                            generated_at_bjt=generated_at_bjt,
                            run_trigger=run_trigger,
                            status=status,
                            ai_model_actual=None,
                            layer_a=layer_a,
                        )
                        self.conn.commit()
                    persisted = True
                else:
                    with pipeline_stage("persist Layer A") as span:
                        span.mark_skipped("persist=false")
        except Exception as exc:
            status = "partial"
            failures.append({
                "stage": "layer_a_spot_runner",
                "error_type": type(exc).__name__,
                "error_message": str(exc)[:300],
            })
            record_pipeline_result("partial", extra={"failures": failures})

        duration_ms = int((time.time() - started) * 1000)
        result = LayerASpotRunResult(
            run_id=run_id,
            generated_at_utc=generated_at_utc,
            generated_at_bjt=generated_at_bjt,
            run_trigger=run_trigger,
            persisted=persisted,
            status=status,
            duration_ms=duration_ms,
            layer_a_spot_strategy=layer_a,
            failures=failures,
            degraded_stages=degraded,
        )
        record_pipeline_result(status, extra={
            "run_id": run_id,
            "persisted": persisted,
            "duration_ms": duration_ms,
            "degraded_stages": degraded,
            "failure_count": len(failures),
            "validate_stages": validate_stages,
        })
        return result
