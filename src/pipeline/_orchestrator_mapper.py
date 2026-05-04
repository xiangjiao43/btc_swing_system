"""src/pipeline/_orchestrator_mapper.py — Sprint 1.9-A.5.1。

把 AIOrchestrator.run_full_a() 输出 + ContextBuilder context map 成
strategy_runs INSERT 用的 19 列 dict。

设计决策(已锁定,见 docs/cc_reports/sprint_1_9_a_step5_0_*.md):
- cold_start:调 src/utils/cold_start::is_cold_start(state),写 1/0
- previous_l*-l5 已在 ContextBuilder.build_full_context 内填(从
  strategy_runs.full_state_json 解析)
- full_state_json 必须含 layers 子结构(下次 parse_previous 依赖)

Sprint 1.10-J commit 5 §X:删 observation_classifier 调用
(v1.4 §11.2 删 "observation_category / observation_classifier 整套机制");
strategy_runs.observation_category 列写 NULL,DB 列保留(留 1.10-K migration 删列)
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from ..data.storage.dao import StrategyStateDAO
from ..utils.cold_start import DEFAULT_COLD_START_RUNS, is_cold_start


logger = logging.getLogger(__name__)
_BJT = ZoneInfo("Asia/Shanghai")


# ============================================================
# 主映射函数
# ============================================================

def _map_orchestrator_result_to_state(
    result: dict[str, Any],
    context: dict[str, Any],
    conn: sqlite3.Connection,
    *,
    run_trigger: str = "scheduled",
    rules_version: str = "v1.3.0",
    system_version: str = "1.9-A",
    previous_run: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """把 orchestrator 输出映射成 strategy_runs INSERT 用 19 列 dict。

    Args:
        result: AIOrchestrator.run_full_a() 返回 {layers, validator, status, ...}
        context: ContextBuilder.build_full_context() 返回(per-agent 嵌套)
        conn: SQLite 连接(给 cold_start tracker 用)
        run_trigger: "scheduled" / "scheduled_8h_onchain" / "manual" / "event_*"
        rules_version: 默认 "v1.3.0"
        system_version: 默认 "1.9-A"
        previous_run: StrategyStateDAO.get_latest_state() 返回(用于派生
            previous_run_id + state_transitioned)

    Returns:
        dict 含 19 个 key,key 名与 strategy_runs 列名一一对应。
    """
    layers = result.get("layers") or {}
    shared = context.get("_shared") or {}
    master = layers.get("master") or {}

    # ---- 1. run_id ----
    run_id = uuid.uuid4().hex

    # ---- 2-3. 时间戳 ----
    now_utc = datetime.now(timezone.utc)
    generated_at_utc = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    generated_at_bjt = now_utc.astimezone(_BJT).strftime(
        "%Y-%m-%dT%H:%M:%S+08:00"
    )

    # ---- 4. reference_timestamp_utc ----
    reference_timestamp_utc = (
        shared.get("reference_timestamp_utc") or generated_at_utc
    )

    # ---- 5. previous_run_id ----
    previous_run_id = (
        previous_run.get("run_id") if isinstance(previous_run, dict) else None
    )

    # ---- 6. action_state(14 档,从 master.state_transition.to_state)----
    state_trans = master.get("state_transition") or {}
    action_state = state_trans.get("to_state") or "FLAT"

    # ---- 7. stance(3 档,从 l2.stance)----
    l2 = layers.get("l2") or {}
    stance = l2.get("stance")

    # ---- 8. btc_price_usd ----
    btc_price_usd = shared.get("current_close")

    # ---- 9. state_transitioned ----
    if previous_run and isinstance(previous_run, dict):
        prev_action = previous_run.get("action_state")
        state_transitioned = 1 if prev_action and prev_action != action_state else 0
    else:
        state_transitioned = 0

    # ---- 10. run_trigger(参数)----
    # ---- 11. run_mode ----
    run_mode = "ai_orchestrator"

    # ---- 12. fallback_level ----
    fallback_level = _derive_fallback_level(result.get("status", "ok"))

    # ---- 13. system_version(参数)----
    # ---- 14. rules_version(参数)----
    # ---- 15. strategy_flavor ----
    strategy_flavor = "v1.3_ai_majority"

    # ---- 16. observation_category(Sprint 1.10-J commit 5 §X 删 classify;
    #          v1.4 §11.2 删整套机制;DAO 写 NULL,DB 列保留留 1.10-K 删列)----
    cold_start_dict = _build_cold_start_state(conn)
    observation_category = None

    # ---- 17. cold_start(0/1,从 cold_start_dict)----
    cold_start_int = 1 if is_cold_start(
        {"cold_start": cold_start_dict},
        threshold_runs=DEFAULT_COLD_START_RUNS,
    ) else 0

    # ---- 18. ai_model_actual ----
    ai_model_actual = _derive_ai_model(layers)

    # ---- 19. full_state_json ----
    full_state_json = _build_full_state_json(result, context)

    return {
        "run_id": run_id,
        "generated_at_utc": generated_at_utc,
        "generated_at_bjt": generated_at_bjt,
        "reference_timestamp_utc": reference_timestamp_utc,
        "previous_run_id": previous_run_id,
        "action_state": action_state,
        "stance": stance,
        "btc_price_usd": btc_price_usd,
        "state_transitioned": state_transitioned,
        "run_trigger": run_trigger,
        "run_mode": run_mode,
        "fallback_level": fallback_level,
        "system_version": system_version,
        "rules_version": rules_version,
        "strategy_flavor": strategy_flavor,
        "observation_category": observation_category,
        "cold_start": cold_start_int,
        "ai_model_actual": ai_model_actual,
        "full_state_json": full_state_json,
    }


# ============================================================
# 辅助函数
# ============================================================

def _derive_fallback_level(status: str) -> Optional[str]:
    """orchestrator status → strategy_runs.fallback_level。

    "ok"            → None
    "degraded_l1_*" → "level_1"
    "degraded_master_*" → "level_2"
    其他 degraded   → "level_3"
    """
    s = str(status or "").lower()
    if s == "ok":
        return None
    if "degraded_l1" in s or "degraded_l2" in s:
        return "level_1"
    if "degraded_l3" in s or "degraded_l4" in s or "degraded_l5" in s:
        return "level_2"
    if "degraded_master" in s:
        return "level_2"
    return "level_3"


def _build_cold_start_state(conn: sqlite3.Connection) -> dict[str, Any]:
    """构造 is_cold_start() 需要的 cold_start dict(复用 v1.2 逻辑)。"""
    try:
        runs = int(StrategyStateDAO.get_count(conn))
    except Exception as e:
        logger.warning("StrategyStateDAO.get_count failed: %s", e)
        runs = 0
    return {
        "warming_up": runs < DEFAULT_COLD_START_RUNS,
        "runs_completed": runs,
        "threshold": DEFAULT_COLD_START_RUNS,
    }


# Sprint 1.10-J commit 5 §X:_build_classifier_state 整删
# (observation_classifier 已删,本 helper 无 caller)
# v1.4 §11.2 删 "observation_category / observation_classifier 整套机制"


def _derive_ai_model(layers: dict[str, Any]) -> Optional[str]:
    """取第一个有 model_used 字段的层(BaseAgent 在 success 时填入)。"""
    for name in ("l1", "l2", "l3", "l4", "l5", "master"):
        layer = layers.get(name) or {}
        m = layer.get("model_used")
        if m:
            return str(m)
    return None


def _build_summary_v13(
    result: dict[str, Any],
    mapped: dict[str, Any],
) -> dict[str, Any]:
    """Sprint 1.9-A.5.3:从 orchestrator result + mapped state 提取 summary,
    给 scripts/run_pipeline_once.py 的 _summarize() 用。

    解决 bug:v13 路径 BuildResult.state 不含 evidence_reports/state_machine
    /adjudicator 等 v12 字段,导致 _summarize() 全 None。本函数把 result
    各 layer 真值映射到 v12 同名 key,scripts/run_pipeline_once.py 优先读。
    """
    layers = result.get("layers") or {}
    l1 = layers.get("l1") or {}
    l2 = layers.get("l2") or {}
    l3 = layers.get("l3") or {}
    l4 = layers.get("l4") or {}
    l5 = layers.get("l5") or {}
    master = layers.get("master") or {}
    state_trans = master.get("state_transition") or {}
    trade_plan = master.get("trade_plan") or {}

    # 累计 token 用量
    tokens_in = sum(
        (layer.get("tokens_in") or 0)
        for layer in layers.values() if isinstance(layer, dict)
    )
    tokens_out = sum(
        (layer.get("tokens_out") or 0)
        for layer in layers.values() if isinstance(layer, dict)
    )

    return {
        # metadata
        "run_id": mapped.get("run_id"),
        "reference_ts": mapped.get("reference_timestamp_utc"),
        "cold_start": {"warming_up": mapped.get("cold_start") == 1},
        # L1
        "L1.regime": l1.get("regime"),
        "L1.volatility": l1.get("volatility_regime"),
        # L2
        "L2.stance": l2.get("stance"),
        "L2.phase": l2.get("phase"),
        "L2.stance_confidence": l2.get("stance_confidence_tier"),
        # L3
        "L3.opportunity_grade": l3.get("opportunity_grade"),
        "L3.execution_permission": l3.get("execution_permission"),
        "L3.anti_pattern_flags": l3.get("anti_pattern_flags"),
        # L4
        "L4.position_cap": l4.get("position_cap_multiplier"),
        "L4.risk_permission": l4.get("risk_permission"),
        "L4.rr_pass_level": l4.get("rr_pass_level"),
        # L5
        "L5.macro_environment": l5.get("macro_stance"),
        "L5.macro_headwind_vs_btc": l5.get("headwind_score"),
        # AI ops
        "ai.status": result.get("status"),
        "ai.tokens_in": tokens_in,
        "ai.tokens_out": tokens_out,
        "ai.summary_preview": (master.get("narrative") or "")[:200],
        # state machine(从 master.state_transition 取)
        "state_machine.previous": state_trans.get("from_state"),
        "state_machine.current": state_trans.get("to_state"),
        "state_machine.transition_reason":
            state_trans.get("transition_reasoning"),
        "state_machine.stable_in_state": (
            state_trans.get("from_state") == state_trans.get("to_state")
        ),
        # adjudicator(master 输出 = 主裁)
        "adjudicator.action": trade_plan.get("action"),
        "adjudicator.direction": trade_plan.get("direction"),
        "adjudicator.confidence": master.get("confidence"),
        "adjudicator.status": master.get("status"),
        "adjudicator.rationale_preview":
            (master.get("narrative") or master.get("rationale") or "")[:200],
        # lifecycle(v13 暂未接入 lifecycle_manager,占位 None)
        "lifecycle.previous": None,
        "lifecycle.current": None,
        "lifecycle.triggered_by": None,
        "lifecycle.conflict_detected": None,
        # pipeline meta
        "pipeline.degraded_stages": [
            name for name, layer in layers.items()
            if isinstance(layer, dict)
            and not str(layer.get("status", "")).startswith("success")
        ],
        "pipeline.failure_count": sum(
            1 for layer in layers.values()
            if isinstance(layer, dict)
            and not str(layer.get("status", "")).startswith("success")
        ),
    }


def _build_full_state_json(
    result: dict[str, Any],
    context: dict[str, Any],
) -> str:
    """JSON dump orchestrator 完整结果 + context summary。

    必须含 'layers' 子键(下次 parse_previous_layer_outputs 依赖)。
    不 dump pandas 对象(too big + 不可 JSON 序列化)。
    """
    shared = context.get("_shared") or {}
    l5 = context.get("l5") or {}
    l2 = context.get("l2") or {}

    payload = {
        # Sprint 1.10-I commit 7:schema_version 标记(v1.4)— 与 state_builder
        # _assemble_state 的同名字段对齐;前端 schema gate 兼容。
        "schema_version": "v14",
        "layers": result.get("layers") or {},
        "validator": result.get("validator"),
        "status": result.get("status"),
        "latency_ms": result.get("latency_ms") or {},
        "system_provided": result.get("_system_provided", {}),
        "context_summary": {
            "reference_timestamp_utc":
                shared.get("reference_timestamp_utc"),
            "current_close": shared.get("current_close"),
            "events_count_72h": shared.get("events_count_72h"),
            "btc_macro_corr_60d": shared.get("btc_macro_corr_60d"),
            "extreme_event_flags": l5.get("extreme_event_flags"),
            "rule_cycle_position": l2.get("rule_cycle_position"),
        },
    }
    return json.dumps(payload, ensure_ascii=False, default=str)
