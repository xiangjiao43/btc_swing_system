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
from src.data.storage.connection import get_connection, init_db
from src.pipeline import StrategyStateBuilder


def _summarize(state: dict[str, Any]) -> dict[str, Any]:
    """挑 state 的关键字段打印,避免一屏 JSON 吓到人。"""
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
    parser.add_argument("--rules-version", default=None,
                        help="覆盖 DEFAULT_RULES_VERSION")
    parser.add_argument("--klines-lookback", type=int, default=600)
    parser.add_argument("--json", action="store_true",
                        help="打印完整 state JSON 而非摘要")
    args = parser.parse_args()

    init_db(verbose=False)
    conn = get_connection()

    try:
        builder_kwargs: dict[str, Any] = {
            "klines_lookback": args.klines_lookback,
        }
        if args.rules_version:
            builder_kwargs["rules_version"] = args.rules_version

        builder = StrategyStateBuilder(conn, **builder_kwargs)
        result = builder.run(
            run_trigger=args.trigger,
            persist=not args.dry_run,
        )

        out = {
            "run_id": result.run_id,
            "reference_timestamp_utc": result.run_timestamp_utc,
            "persisted": result.persisted,
            "ai_status": result.ai_status,
            "duration_ms": result.duration_ms,
            "degraded_stages": result.degraded_stages,
            "failures": result.failures,
        }
        if args.json:
            out["state"] = result.state
        else:
            out["summary"] = _summarize(result.state)

        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))

        if not result.persisted:
            return 2
        if result.failures or result.degraded_stages:
            return 1
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
