"""
scripts/run_pipeline_once.py — 手动触发 Pipeline 一次(Sprint 1.12)。

用法:
    cd ~/Projects/btc_swing_system
    unset VIRTUAL_ENV
    uv run python scripts/run_pipeline_once.py
    # 或者不持久化,仅打印结果:
    uv run python scripts/run_pipeline_once.py --dry-run
    # 覆盖触发类型:
    uv run python scripts/run_pipeline_once.py --trigger manual

前置:
  * config/base.yaml 的 DB 路径已存在(init_db 已跑过)
  * 数据已回填(否则很多 factor / layer 会走 insufficient_data)

退出码:
  0 → persisted=True 且 failures=[]
  1 → persisted=True 但有 degraded / failure(fallback 级别)
  2 → persisted=False
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# 保证直接 python 运行也能 import src.*
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import _env_loader  # noqa: F401
from src.ai.context_builder import ContextBuilder
from src.ai.spot_cycle_context_builder import SpotCycleContextBuilder
from src.data.freshness import compute_stale_state
from src.data.storage.connection import get_connection, init_db
from src.pipeline import StrategyStateBuilder
from src.utils.pipeline_progress import (
    init_pipeline_logging,
    pipeline_stage,
    record_instant_stage,
    record_pipeline_result,
)


_AI_STAGE_NAMES = (
    "run Layer B L1",
    "run Layer B L2",
    "run Layer B L3",
    "run Layer B L4",
    "run Layer B L5",
    "run Layer B Master",
    "validators",
    "run Layer A spot strategy",
    "run Layer A A1",
    "run Layer A A2",
    "run Layer A A3",
    "run Layer A A4",
    "run Layer A A5",
    "thesis persistence check",
    "persist strategy_run",
)


def _summarize(state: dict[str, Any]) -> dict[str, Any]:
    """挑 state 的关键字段打印,避免一屏 JSON 吓到人。

    Sprint 1.9-A.5.3:加 v13 检测 — 若 state 含 v13_orchestrator=True 和
    state["summary"](由 _build_summary_v13 在 state_builder._run_v13_orchestrator
    内填),直接返回那份 summary;否则走 v12 evidence_reports 路径(原代码)。
    """
    if state.get("v13_orchestrator") is True and isinstance(
        state.get("summary"), dict,
    ):
        return state["summary"]

    l1 = (state.get("evidence_reports") or {}).get("layer_1") or {}
    l2 = (state.get("evidence_reports") or {}).get("layer_2") or {}
    l3 = (state.get("evidence_reports") or {}).get("layer_3") or {}
    l4 = (state.get("evidence_reports") or {}).get("layer_4") or {}
    l5 = (state.get("evidence_reports") or {}).get("layer_5") or {}
    ctx = state.get("context_summary") or {}
    pm = state.get("pipeline_meta") or {}
    sm = state.get("state_machine") or {}
    adj = state.get("adjudicator") or {}
    life = state.get("lifecycle") or {}
    return {
        "run_id": state.get("run_id"),
        "reference_ts": state.get("reference_timestamp_utc"),
        "cold_start": state.get("cold_start"),
        "L1.regime": l1.get("regime") or l1.get("regime_primary"),
        "L1.volatility": l1.get("volatility_regime")
                         or l1.get("volatility_level"),
        "L2.stance": l2.get("stance"),
        "L2.phase": l2.get("phase"),
        "L2.stance_confidence": l2.get("stance_confidence"),
        "L3.opportunity_grade": l3.get("opportunity_grade"),
        "L3.execution_permission": l3.get("execution_permission"),
        "L3.anti_pattern_flags": l3.get("anti_pattern_flags"),
        "L4.position_cap": l4.get("position_cap"),
        "L4.risk_permission": l4.get("risk_permission"),
        "L4.rr_pass_level": l4.get("rr_pass_level"),
        "L5.macro_environment": l5.get("macro_environment"),
        "L5.macro_headwind_vs_btc": l5.get("macro_headwind_vs_btc"),
        "ai.status": ctx.get("status"),
        "ai.tokens_in": ctx.get("tokens_in"),
        "ai.tokens_out": ctx.get("tokens_out"),
        "ai.summary_preview": (ctx.get("summary_text") or "")[:200],
        "state_machine.previous": sm.get("previous_state"),
        "state_machine.current": sm.get("current_state"),
        "state_machine.transition_reason": sm.get("transition_reason"),
        "state_machine.stable_in_state": sm.get("stable_in_state"),
        "adjudicator.action": adj.get("action"),
        "adjudicator.direction": adj.get("direction"),
        "adjudicator.confidence": adj.get("confidence"),
        "adjudicator.status": adj.get("status"),
        "adjudicator.rationale_preview": (adj.get("rationale") or "")[:160],
        "lifecycle.previous": life.get("previous_lifecycle"),
        "lifecycle.current": life.get("current_lifecycle"),
        "lifecycle.triggered_by": life.get("transition_triggered_by"),
        "lifecycle.conflict_detected": life.get("conflict_detected"),
        "pipeline.degraded_stages": pm.get("degraded_stages"),
        "pipeline.failure_count": len(pm.get("failures") or []),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trigger", default="manual",
                        help="run_trigger 值(默认 manual)")
    parser.add_argument("--dry-run", action="store_true",
                        help="跑完不写入 strategy_state_history")
    parser.add_argument("--validate-stages", action="store_true",
                        help="只验证初始化/context 日志,跳过完整 AI 和持久化")
    parser.add_argument("--rules-version", default=None,
                        help="覆盖 DEFAULT_RULES_VERSION")
    parser.add_argument("--klines-lookback", type=int, default=600)
    parser.add_argument("--json", action="store_true",
                        help="打印完整 state JSON 而非摘要")
    args = parser.parse_args()

    log_path = init_pipeline_logging(
        run_label=args.trigger,
        validation=bool(args.validate_stages),
    )
    record_instant_stage("load env", status="success")

    if args.validate_stages:
        return _validate_stages(args, log_path)

    with pipeline_stage("init_db"):
        init_db(verbose=False)
    with pipeline_stage("open_db_connection"):
        conn = get_connection()

    try:
        builder_kwargs: dict[str, Any] = {
            "klines_lookback": args.klines_lookback,
        }
        if args.rules_version:
            builder_kwargs["rules_version"] = args.rules_version

        with pipeline_stage("build StrategyStateBuilder"):
            builder = StrategyStateBuilder(conn, **builder_kwargs)
        with pipeline_stage("run StrategyStateBuilder") as span:
            result = builder.run(
                run_trigger=args.trigger,
                persist=not args.dry_run,
            )
            if result.failures or result.degraded_stages:
                span.mark_degraded("result contains failures/degraded stages")

        out = {
            "run_id": result.run_id,
            "reference_timestamp_utc": result.run_timestamp_utc,
            "persisted": result.persisted,
            "ai_status": result.ai_status,
            "duration_ms": result.duration_ms,
            "degraded_stages": result.degraded_stages,
            "failures": result.failures,
            "pipeline_status": _pipeline_status(result),
            "pipeline_log_path": str(log_path),
        }
        if args.json:
            out["state"] = result.state
        else:
            out["summary"] = _summarize(result.state)

        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))

        final_status = _pipeline_status(result)
        record_pipeline_result(final_status, extra=out)

        if not result.persisted:
            return 2
        if result.failures or result.degraded_stages:
            return 1
        return 0
    finally:
        conn.close()


def _pipeline_status(result: Any) -> str:
    if not getattr(result, "persisted", False):
        return "partial"
    if getattr(result, "failures", None) or getattr(result, "degraded_stages", None):
        return "degraded"
    ai_status = str(getattr(result, "ai_status", "") or "")
    if ai_status and ai_status != "ok":
        return "degraded"
    return "success"


def _validate_stages(args: argparse.Namespace, log_path: Path) -> int:
    """Short validation: build contexts and logs, skip full AI/persist."""
    with pipeline_stage("init_db") as span:
        span.mark_skipped("--validate-stages does not initialize/migrate DB")
    with pipeline_stage("open_db_connection"):
        conn = get_connection()
    try:
        with pipeline_stage("build StrategyStateBuilder"):
            StrategyStateBuilder(conn, klines_lookback=args.klines_lookback)
        with pipeline_stage("build data context"):
            context = ContextBuilder(conn, klines_lookback=args.klines_lookback).build_full_context()
        with pipeline_stage("compute data freshness"):
            stale_map, hours_map = compute_stale_state(conn)
            context["_source_stale_map"] = stale_map
            context["_source_hours_map"] = hours_map
        with pipeline_stage("build Layer A context"):
            context["layer_a_spot_context"] = (
                SpotCycleContextBuilder(conn)
                .build_spot_cycle_context(existing_context=context)
            )
        for stage in _AI_STAGE_NAMES:
            record_instant_stage(
                stage,
                status="skipped",
                message="--validate-stages skips full AI, validators, thesis, and persist",
            )
        out = {
            "pipeline_status": "success",
            "validation": True,
            "pipeline_log_path": str(log_path),
            "checked": [
                "env",
                "db_connection",
                "Layer B context",
                "data freshness",
                "Layer A context",
            ],
        }
        record_pipeline_result("success", extra=out)
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return 0
    except Exception as exc:
        out = {
            "pipeline_status": "partial",
            "validation": True,
            "pipeline_log_path": str(log_path),
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:300],
        }
        record_pipeline_result("partial", extra=out)
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return 2
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
