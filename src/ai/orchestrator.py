"""src/ai/orchestrator.py — Sprint 1.8 Task D 编排 6 个 AI 角色 + Validator。

执行顺序(对齐建模 §3.2.1):
  1. L1 AI(看 1d K 线图 + 客观指标)
  2. L2 AI(看 1d+4h 双周期图 + 客观指标 + L1)
  3. L3 AI(消费 L1+L2,无图)
  4. L4 AI(看 1d 风险图 + 衍生品 + L1+L2)
  5. L5 AI(看宏观因子,无图,独立判断)
  6. 主裁 AI(消费 L1-L5)
  7. Validator 校验主裁输出

任一层失败:
- 标记 status='degraded_<layer>_failed'
- 后续层接收 fallback 输入(每个 agent 自带 _fallback_output)
- 主裁可能 fallback 到 watch/hold

本阶段不接入 jobs.py 主流程(留 Sprint 1.9 频率重构时做)。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from .agents import (
    LayerACycleAdjudicator,
    L1RegimeAnalyst,
    L2DirectionAnalyst,
    L3OpportunityAnalyst,
    L4RiskAnalyst,
    L5MacroAnalyst,
    MasterAdjudicator,
)
from .agents.chart_renderer import ChartRenderer
from .agents.emergency_simplified_a import EmergencySimplifiedA
from .anti_pattern_signals import compute_anti_pattern_signals
from .circuit_breaker import CircuitBreaker
from .client import build_anthropic_client
from .spot_cycle_context_builder import build_layer_a_cycle_adjudicator_context
from .spot_strategy_normalizer import fallback_layer_a_output, normalize_layer_a_output
from .spot_validator import validate_spot_strategy_output
from .validator import validate_master_output
from ..strategy.factor_dependencies import fresh_ratio_for_layer
from ..utils.pipeline_progress import pipeline_stage


logger = logging.getLogger(__name__)


# ============================================================
# Sprint E Step 3:因子粒度 stale 降级 helpers
# ============================================================

def _stale_state_from_context(
    context: dict[str, Any],
) -> tuple[dict[str, bool], dict[str, float]]:
    """从 run_full_a context 取 source_stale_map + source_hours_map(由
    state_builder 注入)。无则返空 dict(向后兼容,无 stale 守卫)。"""
    return (
        dict(context.get("_source_stale_map") or {}),
        dict(context.get("_source_hours_map") or {}),
    )


def _progress_status_from_output(output: dict[str, Any] | None) -> str:
    status = str((output or {}).get("status") or "")
    if not status:
        return "success"
    if status.startswith("success") or status == "ok":
        return "success"
    if status.startswith("degraded") or status.startswith("fallback"):
        return "degraded"
    if status.startswith("skipped"):
        return "skipped"
    if status.startswith("failed") or status.startswith("error"):
        return "failure"
    return "success"


def _build_data_missing_stub(
    layer_id: int, agent: Any, fresh_ratio: float,
) -> dict[str, Any]:
    """Sprint E Step 3:某层 fresh_ratio == 0 时不调 AI,直接构造 stub。
    省 token + AI 不会瞎编 stale 数据具体值。"""
    stub = agent._fallback_output()
    stub["status"] = "degraded_data_missing"
    stub["narrative"] = (
        f"L{layer_id} 依赖数据全部过期(fresh_ratio=0),orchestrator 跳过 "
        f"AI 调用直接 fallback。本层不参与决策。"
    )
    if "confidence" in stub:
        stub["confidence"] = 0.0
    if "stance_confidence" in stub:
        stub["stance_confidence"] = 0.0
    notes = list(stub.get("notes") or [])
    notes.append("factor_grain_data_missing_ai_skipped")
    stub["notes"] = notes
    stub["_factor_grain"] = {
        "fresh_ratio": 0.0, "data_missing": True, "ai_skipped": True,
        "layer_id": layer_id,
    }
    return stub


def _apply_factor_grain_override(
    layer_id: int,
    layer_output: dict[str, Any],
    fresh_ratio: float,
) -> dict[str, Any]:
    """Sprint E Step 3:AI 跑完后,按 fresh_ratio 调 confidence + status。
      fresh_ratio == 1   → 不动
      0.5 <= ratio < 1   → confidence × 0.6,status=degraded_factor_grain(若原是 ok)
      0 < ratio < 0.5    → confidence × 0.3,status=degraded_factor_grain
      ratio == 0         → 应已被 _build_data_missing_stub 拦截,这里防御性走
                            data_missing 路径
    """
    out = dict(layer_output)
    notes_extra: list[str] = []
    if fresh_ratio >= 1.0:
        out["_factor_grain"] = {
            "fresh_ratio": 1.0, "data_missing": False, "ai_skipped": False,
            "layer_id": layer_id,
        }
        return out

    if fresh_ratio <= 0.0:
        out["status"] = "degraded_data_missing"
        if "confidence" in out:
            out["confidence"] = 0.0
        if "stance_confidence" in out:
            out["stance_confidence"] = 0.0
        multiplier = 0.0
    elif fresh_ratio < 0.5:
        if not str(out.get("status", "")).startswith("degraded"):
            out["status"] = "degraded_factor_grain"
        multiplier = 0.3
        for k in ("confidence", "stance_confidence"):
            if k in out and isinstance(out[k], (int, float)):
                out[k] = round(float(out[k]) * multiplier, 4)
    else:
        if not str(out.get("status", "")).startswith("degraded"):
            out["status"] = "degraded_factor_grain"
        multiplier = 0.6
        for k in ("confidence", "stance_confidence"):
            if k in out and isinstance(out[k], (int, float)):
                out[k] = round(float(out[k]) * multiplier, 4)

    notes_extra.append(
        f"factor_grain: fresh_ratio={fresh_ratio:.2f} → confidence × {multiplier}"
    )
    notes = list(out.get("notes") or [])
    notes.extend(notes_extra)
    out["notes"] = notes

    out["_factor_grain"] = {
        "fresh_ratio": round(fresh_ratio, 2),
        "data_missing": fresh_ratio == 0.0,
        "ai_skipped": False,
        "layer_id": layer_id,
        "confidence_multiplier": multiplier,
    }
    return out


class AIOrchestrator:
    """完整 6 AI + Validator pipeline。

    用法:
        orch = AIOrchestrator()
        result = orch.run_full_a(context)
        # result['layers'] = {l1, l2, l3, l4, l5, master}
        # result['validator'] = {violations, passed}
        # result['status'] = 'ok' | 'degraded_*' | 'failed'
    """

    def __init__(
        self,
        anthropic_client: Any = None,
        chart_renderer: Optional[ChartRenderer] = None,
        agents: Optional[dict[str, Any]] = None,
    ) -> None:
        """允许测试时注入 mock client / 预制 agents。

        agents 形如 {'l1': L1RegimeAnalyst(...), ...}。如不传则用默认。
        """
        self._client = anthropic_client
        self._chart = chart_renderer or ChartRenderer()

        # agents 默认全用同一个 client(测试时可注入 mock)
        if agents is None:
            agents = {
                "l1": L1RegimeAnalyst(client=anthropic_client),
                "l2": L2DirectionAnalyst(client=anthropic_client),
                "l3": L3OpportunityAnalyst(client=anthropic_client),
                "l4": L4RiskAnalyst(client=anthropic_client),
                "l5": L5MacroAnalyst(client=anthropic_client),
                "master": MasterAdjudicator(client=anthropic_client),
                "layer_a_cycle": LayerACycleAdjudicator(client=anthropic_client),
                # Sprint 1.10-G:简化 A 应急 AI(event_price 触发时走它,不跑完整 6 AI)
                "emergency_simplified_a": EmergencySimplifiedA(
                    client=anthropic_client,
                ),
            }
        self._agents = agents

        # Sprint 1.10-E:旧 AdjudicatorValidator(v1.3 H1-H10)删除,改用 v1.4 24 条
        # 模块级函数 validate_master_output;orchestrator 调用见 run_full_a 末尾

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run_full_a(
        self,
        context: dict[str, Any],
        *,
        include_layer_a: bool = True,
    ) -> dict[str, Any]:
        """完整 A 流程(每日 16:00 用)。

        context 必含(Sprint 1.9-A.4 起,per-agent 嵌套结构):
          - "_shared":  {klines_1d, klines_4h, ema_*, adx, atr, swing_points,
                          funding_rate_series, open_interest_series,
                          exchange_net_flow_series, current_close, ...}
          - "l1":       {klines_1d_30d_close, computed_indicators, previous_l1}
          - "l2":       {klines_1d_30d_close, computed_indicators, previous_l2}
          - "l3":       {risk_preview, current_state, previous_l3}
          - "l4":       {computed_indicators, current_state, previous_l4}
          - "l5":       {computed_macro_indicators, events_calendar_72h,
                          extreme_event_flags, previous_l5}
          - "master":   {current_state, previous_strategy_run}

        Orchestrator 在运行时注入:
          - chart_b64 (L1/L2/L4)
          - 上游 layer outputs(l1_output → l2,l1+l2 → l3+l4,l1-l5 → master)
          - anti_pattern_signals(L3,基于 l1_out + l2_out)
          - _system_provided(master,基于 L4 + events_calendar)
        """
        shared = context.get("_shared") or {}
        result: dict[str, Any] = {
            "layers": {},
            "validator": None,
            "status": "ok",
            "latency_ms": {},
            "tokens": {},
        }

        # ---- 1. L1 ----
        with pipeline_stage("run Layer B L1") as span:
            l1_out = self._run_l1(context, shared, result)
            span.set_status(_progress_status_from_output(l1_out))
        result["layers"]["l1"] = l1_out

        # ---- 2. L2(注入 l1_output)----
        with pipeline_stage("run Layer B L2") as span:
            l2_out = self._run_l2(context, shared, l1_out, result)
            span.set_status(_progress_status_from_output(l2_out))
        result["layers"]["l2"] = l2_out

        # ---- 5. L5(独立,无依赖)— 提前跑,L3 anti_pattern 需 extreme_event_flags ----
        with pipeline_stage("run Layer B L5") as span:
            l5_out = self._run_l5(context, result)
            span.set_status(_progress_status_from_output(l5_out))
        result["layers"]["l5"] = l5_out

        # ---- 3. L3(注入 l1+l2 output + anti_pattern_signals)----
        with pipeline_stage("run Layer B L3") as span:
            l3_out = self._run_l3(
                context, shared, l1_out, l2_out, l5_out, result,
            )
            span.set_status(_progress_status_from_output(l3_out))
        result["layers"]["l3"] = l3_out

        # ---- 4. L4(注入 l1+l2+l3 output)----
        with pipeline_stage("run Layer B L4") as span:
            l4_out = self._run_l4(
                context, shared, l1_out, l2_out, l3_out, result,
            )
            span.set_status(_progress_status_from_output(l4_out))
        result["layers"]["l4"] = l4_out

        # ---- 计算 _system_provided multipliers ----
        crowding_mult = self._compute_crowding_multiplier(l4_out)
        events_72h = (context.get("l5") or {}).get("events_calendar_72h") or []
        event_mult = self._compute_event_multiplier(events_72h)

        # ---- 6. 主裁(注入 l1-l5 output + _system_provided)----
        with pipeline_stage("run Layer B Master") as span:
            master_out = self._run_master(
                context, shared, l1_out, l2_out, l3_out, l4_out, l5_out,
                crowding_mult, event_mult, result,
            )
            span.set_status(_progress_status_from_output(master_out))
        result["layers"]["master"] = master_out

        # ---- 7. Validator(v1.4 24 条,Sprint 1.10-E)----
        # 装配 validator context — orchestrator 现有数据 + 业务态(cooldown/fuse/active_thesis)
        # 由 1.10-D master_input_builder 装配;若 caller 未传 master_input,则用最小 context
        master_ctx = context.get("master") or {}
        validator_ctx = {
            "l1_output": l1_out, "l2_output": l2_out, "l3_output": l3_out,
            "l4_output": l4_out, "l5_output": l5_out,
            "l3_grade": (l3_out or {}).get("opportunity_grade"),
            "l4_hard_invalidation_levels": (
                (l4_out or {}).get("hard_invalidation_levels") or []
            ),
            "l4_position_cap_base": (
                (l4_out or {}).get("position_cap_base")
                or (l4_out or {}).get("position_cap_pct")
            ),
            "in_protection": (l5_out or {}).get("extreme_event_detected") or False,
            # 业务态字段:由 caller 装配后传入(1.10-D master_input_builder 已实施)
            "active_thesis": master_ctx.get("active_thesis"),
            "current_position": master_ctx.get("current_position"),
            "cooldown_state": master_ctx.get("cooldown_state") or {},
            "fuse_state": master_ctx.get("fuse_state") or {},
            "consecutive_fuse_triggered": master_ctx.get("consecutive_fuse_triggered", False),
            "data_completeness": master_ctx.get("data_completeness", 1.0),
            "historical_precedent_match": master_ctx.get("historical_precedent_match", 1.0),
            "fallback_level": master_ctx.get("fallback_level"),
            "master_consecutive_failures": master_ctx.get("master_consecutive_failures", 0),
            # Sprint 1.10-F D2=a:V22 滑动 72h 检测 — caller 装入(无则 None,V22 fallback 老字段)
            "master_failures_in_72h": master_ctx.get("master_failures_in_72h"),
            "current_btc_price": master_ctx.get("current_btc_price"),
            "stop_tightening_count_so_far": master_ctx.get("stop_tightening_count_so_far", 0),
            "initial_stop_loss_price": master_ctx.get("initial_stop_loss_price"),
            "active_thesis_avg_price": master_ctx.get("active_thesis_avg_price"),
        }
        with pipeline_stage("validators") as span:
            validated_output, constraint_activations = validate_master_output(
                master_out, validator_ctx,
            )
            if constraint_activations.get("validator_needs_retry"):
                span.mark_degraded("validator requested master retry")

        # Sprint 1.10-F:Validator 触发同 run 重试(V8/V9/V11/V21)
        # D3=b:V21 retry hint 塞入 master input 的 _v21_retry_hint 字段
        # 失败的 master 已走 fallback,此处不重试 fallback 路径
        if (
            constraint_activations.get("validator_needs_retry")
            and str(master_out.get("status", "")).startswith("success")
        ):
            hints = constraint_activations.get("validator_retry_hints") or []
            retry_master_input = dict(context.get("master") or {})
            retry_master_input["l1_output"] = l1_out
            retry_master_input["l2_output"] = l2_out
            retry_master_input["l3_output"] = l3_out
            retry_master_input["l4_output"] = l4_out
            retry_master_input["l5_output"] = l5_out
            retry_master_input["_system_provided"] = {
                "crowding_multiplier": crowding_mult,
                "event_multiplier": event_mult,
                "current_close": shared.get("current_close"),
            }
            if hints:
                retry_master_input["_v21_retry_hint"] = " ".join(hints)
            retry_master_input["_validator_retry_attempt"] = 2
            try:
                retry_out = self._agents["master"].analyze(
                    retry_master_input, client=build_anthropic_client(),
                )
                # 第二次也校验
                retry_validated, retry_activations = validate_master_output(
                    retry_out, validator_ctx,
                )
                # 若第二次没触发 needs_retry → 接受新输出
                if not retry_activations.get("validator_needs_retry"):
                    validated_output = retry_validated
                    constraint_activations = retry_activations
                    result.setdefault("retry_log", {}).update({
                        "validator_triggered_retry_applied": True,
                        "validator_triggered_retry_succeeded": True,
                    })
                else:
                    # 第二次也不通过 → 保留第一次输出 + 标记
                    result.setdefault("retry_log", {}).update({
                        "validator_triggered_retry_applied": True,
                        "validator_triggered_retry_succeeded": False,
                    })
            except Exception as e:
                logger.warning(
                    "orchestrator: validator-triggered retry raised: %s", e,
                )
                result.setdefault("retry_log", {}).update({
                    "validator_triggered_retry_applied": True,
                    "validator_triggered_retry_succeeded": False,
                    "validator_triggered_retry_error": str(e)[:200],
                })

        result["layers"]["master"] = validated_output
        result["constraint_activations"] = constraint_activations

        # Layer A 现货大周期策略已拆成 10:00 独立任务。
        # 11:35 Layer B 主 pipeline 默认不运行 Layer A,避免连续 AI 调用互相拖慢。
        if include_layer_a:
            with pipeline_stage("run Layer A spot strategy") as span:
                result["layer_a_spot_strategy"] = self.run_layer_a_spot_only(
                    context,
                )
                validator = result["layer_a_spot_strategy"].get("validator") or {}
                if not validator.get("passed", True):
                    span.mark_degraded("Layer A spot validator reported warnings/violations")

        return result

    # ------------------------------------------------------------------
    # Sprint 1.10-G:简化 A 应急 AI 入口(event_price 触发用)
    # ------------------------------------------------------------------

    def _run_layer_a_spot_strategy(
        self,
        context: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        """Run Layer A single spot-cycle adjudicator if context is provided.

        Existing tests and legacy callers do not pass layer_a_spot_context; in
        that case we return a displayable fallback and never call AI.  This keeps
        Layer B behavior unchanged.
        """
        spot_ctx = context.get("layer_a_spot_context")
        if not isinstance(spot_ctx, dict) or not spot_ctx:
            return fallback_layer_a_output(
                "暂无大周期策略，本 run 尚未记录 Layer A 输出。"
            )
        adjudicator_context = build_layer_a_cycle_adjudicator_context({
            "spot_cycle_context": spot_ctx,
        })
        data_packets = adjudicator_context.get("data_packets") or {}
        spot_ctx = dict(spot_ctx)
        spot_ctx["data_packets"] = data_packets

        t0 = time.time()
        try:
            with pipeline_stage("run Layer A cycle adjudicator") as span:
                adjudicator = self._agents.get(
                    "layer_a_cycle",
                    LayerACycleAdjudicator(),
                ).analyze(
                    {"spot_cycle_context": spot_ctx},
                    client=build_anthropic_client(),
                )
                span.set_status(_progress_status_from_output(adjudicator))
        except Exception as e:
            logger.warning("orchestrator: Layer A cycle adjudicator raised: %s", e)
            adjudicator = LayerACycleAdjudicator()._fallback_output()

        merged = normalize_layer_a_output({
            "enabled": True,
            "cycle_adjudicator": adjudicator,
            "data_packets": data_packets,
            "unavailable_factors": spot_ctx.get("unavailable_factors") or [],
            "factor_coverage": spot_ctx.get("factor_coverage") or {},
            "previous_layer_a_state": spot_ctx.get("previous_layer_a_state") or {},
            "input_context_snapshot": {
                "schema_version": spot_ctx.get("schema_version"),
                "built_at_utc": spot_ctx.get("built_at_utc"),
                "data_quality_notes": spot_ctx.get("data_quality_notes") or [],
                "factor_coverage": spot_ctx.get("factor_coverage") or {},
                "available_factors": spot_ctx.get("available_factors") or {},
                "factor_role_classification": spot_ctx.get(
                    "factor_role_classification"
                ) or {},
                "data_packets": spot_ctx.get("data_packets") or {},
                "unavailable_factors": spot_ctx.get("unavailable_factors") or [],
                "previous_layer_a_state": spot_ctx.get("previous_layer_a_state") or {},
                "series_samples": spot_ctx.get("series_samples") or {},
            },
            "model_notes": [
                "Layer A 单一大周期裁决:三个 deterministic 数据包(price_structure / onchain / macro_flow)+ 一次 AI 调用。",
                "Layer A 独立于 Layer B:不创建 thesis,不进入虚拟账户,不影响开平仓。"
            ],
        })
        merged["ai_call_count"] = 1
        merged["legacy_a1_a5_flow"] = False
        guard = validate_spot_strategy_output(merged, context=spot_ctx)
        existing_validator = merged.get("validator") or {}
        guard["violations"] = list(existing_validator.get("violations") or []) + list(
            guard.get("violations") or []
        )
        guard["warnings"] = list(existing_validator.get("warnings") or []) + list(
            guard.get("warnings") or []
        )
        guard["passed"] = len(guard["violations"]) == 0
        merged["validator"] = guard
        merged["latency_ms"] = int((time.time() - t0) * 1000)
        result.setdefault("latency_ms", {})["layer_a_spot_strategy"] = merged["latency_ms"]
        return merged

    def run_layer_a_spot_only(self, context: dict[str, Any]) -> dict[str, Any]:
        """Run only the Layer A single spot-cycle adjudicator.

        This public wrapper is used by the standalone 10:00 Layer A job.  It
        does not run Layer B L1-L5 / Master / Validator, does not create thesis,
        and does not touch virtual account.
        """
        temp_result: dict[str, Any] = {"latency_ms": {}}
        return self._run_layer_a_spot_strategy(context, temp_result)

    def run_event_a(
        self,
        *,
        event_type: str,
        triggered_at_price: float,
        baseline_price: float,
        current_strategy_state: str,
        key_factors: Optional[dict[str, Any]] = None,
        active_thesis: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """v1.4 §3.3.8 简化 A 应急 AI 入口。

        触发场景:event_price(±5% 空仓 / ±3% 持仓)异动。
        本入口走单 AI(EmergencySimplifiedA),不跑完整 6 AI pipeline。

        Args:
            event_type: 'event_price' / 'event_invalidation'(后者由 caller 区分;
                event_invalidation 实际不应走本入口 — 走 HardInvalidationMonitor 规则平仓)
            triggered_at_price: 异动后 BTC 价格
            baseline_price: 上次 strategy_run BTC 价格(D1=b)
            current_strategy_state: 14 档当前状态
            key_factors: 关键因子最新快照(funding / OI / lsr 等)
            active_thesis: 当前 active thesis dict(可空)

        Returns:
            {layers: {emergency_simplified_a: {...}},
             status: 'ok' | 'degraded',
             run_trigger: event_type,
             pct_change: float}
        """
        agent = self._agents.get("emergency_simplified_a")
        if agent is None:
            agent = EmergencySimplifiedA(client=self._client)
        pct = (
            (triggered_at_price - baseline_price) / baseline_price
            if baseline_price else 0.0
        )
        ctx = {
            "current_strategy_state": current_strategy_state,
            "triggered_at_price": triggered_at_price,
            "baseline_price": baseline_price,
            "pct_change": pct,
            "key_factors": key_factors or {},
            "active_thesis": active_thesis,
        }
        try:
            out = agent.analyze(ctx, client=build_anthropic_client())
        except Exception as e:
            logger.warning("orchestrator.run_event_a: agent raised: %s", e)
            out = agent._fallback_output()

        # 轻量 normalize(非法 immediate_action 改 maintain)
        out = EmergencySimplifiedA.normalize_output(out)

        status = (
            "ok" if str(out.get("status", "")).startswith("success") else "degraded"
        )
        return {
            "layers": {"emergency_simplified_a": out},
            "status": status,
            "run_trigger": event_type,
            "pct_change": pct,
            "current_strategy_state": current_strategy_state,
        }

    # ------------------------------------------------------------------
    # _system_provided 计算函数
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_crowding_multiplier(l4_output: dict[str, Any]) -> float:
        """从 L4.risk_breakdown.crowding_risk(0-100)推导 multiplier。

        - 0-25 → 1.0
        - 25-50 → 0.85
        - 50-75 → 0.65
        - 75-100 → 0.50
        """
        breakdown = (l4_output or {}).get("risk_breakdown") or {}
        try:
            crowding = float(breakdown.get("crowding_risk", 0))
        except (TypeError, ValueError):
            return 1.0
        if crowding < 25:
            return 1.0
        if crowding < 50:
            return 0.85
        if crowding < 75:
            return 0.65
        return 0.50

    @staticmethod
    def _compute_event_multiplier(events_72h: list[dict[str, Any]]) -> float:
        """从 events_calendar 推导 multiplier。

        根据 72h 内最高 impact_level:
        - critical → 0.5
        - high → 0.7
        - medium → 0.85
        - low / 无事件 → 0.95
        """
        if not events_72h:
            return 0.95
        impact_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        max_impact = 0
        for ev in events_72h:
            if not isinstance(ev, dict):
                continue
            level = str(ev.get("impact_level", "")).lower()
            max_impact = max(max_impact, impact_order.get(level, 0))
        return {4: 0.5, 3: 0.7, 2: 0.85, 1: 0.95}.get(max_impact, 0.95)

    # ------------------------------------------------------------------
    # 内部:单层执行(失败不抛异常,记 degraded)
    # ------------------------------------------------------------------

    def _run_l1(
        self,
        context: dict[str, Any],
        shared: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        t0 = time.time()
        # Sprint E Step 3:从 context 取 stale_map / hours_map(state_builder 注入)
        stale_map, hours_map = _stale_state_from_context(context)
        fresh_ratio = fresh_ratio_for_layer(1, stale_map) if stale_map else 1.0
        # 全 stale → 不调 AI
        if stale_map and fresh_ratio == 0.0:
            out = _build_data_missing_stub(1, self._agents["l1"], fresh_ratio)
            result["latency_ms"]["l1"] = int((time.time() - t0) * 1000)
            if result["status"] == "ok":
                result["status"] = "degraded_l1_data_missing"
            return out

        try:
            chart_b64 = self._chart.render_l1_chart(
                shared["klines_1d"],
                ema_20=shared.get("ema_20_1d"),
                ema_50=shared.get("ema_50_1d"),
                ema_200=shared.get("ema_200_1d"),
                adx=shared.get("adx_14_1d"),
                atr_180d_pct=shared.get("atr_180d_pct_1d"),
                swing_points=shared.get("swing_points_1d"),
            )
        except Exception as e:
            logger.warning("orchestrator: L1 chart render failed: %s", e)
            chart_b64 = None

        l1_input = dict(context.get("l1") or {})
        l1_input["chart_b64"] = chart_b64
        # Sprint E Step 2:让 sub-agent prompt 看到 stale 状态
        if stale_map:
            l1_input["source_stale_map"] = stale_map
            l1_input["source_hours_map"] = hours_map
        try:
            # Sprint 1.9-A.5.2 fix:每层新建 client 避中转站连接复用限流
            out = self._agents["l1"].analyze(
                l1_input, client=build_anthropic_client(),
            )
        except Exception as e:
            logger.warning("orchestrator: L1 analyze raised: %s", e)
            out = self._agents["l1"]._fallback_output()
            out["status"] = "degraded_l1_failed"

        # Sprint E Step 3:fresh_ratio < 1 → 调整 confidence + status
        if stale_map and fresh_ratio < 1.0:
            out = _apply_factor_grain_override(1, out, fresh_ratio)

        result["latency_ms"]["l1"] = int((time.time() - t0) * 1000)
        if not str(out.get("status", "")).startswith("success"):
            if result["status"] == "ok":
                result["status"] = f"degraded_l1_{out.get('status', 'failed')}"
        return out

    def _run_l2(
        self,
        context: dict[str, Any],
        shared: dict[str, Any],
        l1_out: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        t0 = time.time()
        # Sprint E Step 3
        stale_map, hours_map = _stale_state_from_context(context)
        fresh_ratio = fresh_ratio_for_layer(2, stale_map) if stale_map else 1.0
        if stale_map and fresh_ratio == 0.0:
            out = _build_data_missing_stub(2, self._agents["l2"], fresh_ratio)
            result["latency_ms"]["l2"] = int((time.time() - t0) * 1000)
            if result["status"] == "ok":
                result["status"] = "degraded_l2_data_missing"
            return out

        try:
            chart_b64 = self._chart.render_l2_chart(
                shared["klines_1d"],
                klines_4h=shared.get("klines_4h"),
                ema_20_1d=shared.get("ema_20_1d"),
                ema_50_1d=shared.get("ema_50_1d"),
                ema_20_4h=shared.get("ema_20_4h"),
                ema_50_4h=shared.get("ema_50_4h"),
                swing_points_1d=shared.get("swing_points_1d"),
                # 不传 key_levels:L2 自己看图判断(铁律 1)
            )
        except Exception as e:
            logger.warning("orchestrator: L2 chart render failed: %s", e)
            chart_b64 = None

        l2_input = dict(context.get("l2") or {})
        l2_input["l1_output"] = l1_out
        l2_input["chart_b64"] = chart_b64
        if stale_map:
            l2_input["source_stale_map"] = stale_map
            l2_input["source_hours_map"] = hours_map
        try:
            out = self._agents["l2"].analyze(
                l2_input, client=build_anthropic_client(),
            )
        except Exception as e:
            logger.warning("orchestrator: L2 analyze raised: %s", e)
            out = self._agents["l2"]._fallback_output()
            out["status"] = "degraded_l2_failed"

        if stale_map and fresh_ratio < 1.0:
            out = _apply_factor_grain_override(2, out, fresh_ratio)

        result["latency_ms"]["l2"] = int((time.time() - t0) * 1000)
        if not str(out.get("status", "")).startswith("success"):
            if result["status"] == "ok":
                result["status"] = f"degraded_l2_{out.get('status', 'failed')}"
        return out

    def _run_l3(
        self,
        context: dict[str, Any],
        shared: dict[str, Any],
        l1_out: dict[str, Any],
        l2_out: dict[str, Any],
        l5_out: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        t0 = time.time()
        # Sprint E Step 3:L3 衍生层无直接 indicator,但若 L1 或 L2 上游已经
        # data_missing → L3 也直接 data_missing(避免基于 stale 上游胡说)
        l1_dm = (l1_out or {}).get("status") == "degraded_data_missing"
        l2_dm = (l2_out or {}).get("status") == "degraded_data_missing"
        if l1_dm or l2_dm:
            out = _build_data_missing_stub(3, self._agents["l3"], 0.0)
            out["narrative"] = (
                "L3 上游 L1/L2 数据全部过期,衍生层无法判断,"
                "opportunity_grade=none,跳过 AI 调用"
            )
            if "opportunity_grade" in out:
                out["opportunity_grade"] = "none"
            result["latency_ms"]["l3"] = int((time.time() - t0) * 1000)
            if result["status"] == "ok":
                result["status"] = "degraded_l3_data_missing"
            return out

        # L3 不需要图;计算 anti_pattern_signals(需 l1+l2 输出)
        extreme_event_flags = (context.get("l5") or {}).get(
            "extreme_event_flags") or {}
        anti_pattern_signals = compute_anti_pattern_signals(
            l1_output=l1_out, l2_output=l2_out,
            current_close=shared.get("current_close"),
            extreme_event_flags=extreme_event_flags,
        )

        l3_input = dict(context.get("l3") or {})
        l3_input["l1_output"] = l1_out
        l3_input["l2_output"] = l2_out
        l3_input["anti_pattern_signals"] = anti_pattern_signals
        # Sprint E Step 2:L3 prompt 没直接 indicator,但仍透传 stale_map 让 AI
        # 看到上游 source 状态(L3 prompt 段空但纪律段在,引导 AI 据 L1/L2 status
        # 联动)
        stale_map, hours_map = _stale_state_from_context(context)
        if stale_map:
            l3_input["source_stale_map"] = stale_map
            l3_input["source_hours_map"] = hours_map
        try:
            out = self._agents["l3"].analyze(
                l3_input, client=build_anthropic_client(),
            )
        except Exception as e:
            logger.warning("orchestrator: L3 analyze raised: %s", e)
            out = self._agents["l3"]._fallback_output()
            out["status"] = "degraded_l3_failed"

        # Sprint E Step 3:L3 fresh_ratio 永远 = 1.0(LAYER_RELEVANT_INDICATORS[3]=()),
        # 但 L1 / L2 是 degraded_factor_grain 时,L3 也降一档
        l1_status = str((l1_out or {}).get("status") or "")
        l2_status = str((l2_out or {}).get("status") or "")
        if l1_status.startswith("degraded") or l2_status.startswith("degraded"):
            # L3 fresh_ratio 用 0.6(轻度 degraded,沿用 0.5 <= ratio < 1 段)
            out = _apply_factor_grain_override(3, out, 0.6)

        result["latency_ms"]["l3"] = int((time.time() - t0) * 1000)
        if not str(out.get("status", "")).startswith("success"):
            if result["status"] == "ok":
                result["status"] = f"degraded_l3_{out.get('status', 'failed')}"
        return out

    def _run_l4(
        self,
        context: dict[str, Any],
        shared: dict[str, Any],
        l1_out: dict[str, Any],
        l2_out: dict[str, Any],
        l3_out: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        t0 = time.time()
        # Sprint E Step 3
        stale_map, hours_map = _stale_state_from_context(context)
        fresh_ratio = fresh_ratio_for_layer(4, stale_map) if stale_map else 1.0
        if stale_map and fresh_ratio == 0.0:
            out = _build_data_missing_stub(4, self._agents["l4"], fresh_ratio)
            result["latency_ms"]["l4"] = int((time.time() - t0) * 1000)
            if result["status"] == "ok":
                result["status"] = "degraded_l4_data_missing"
            return out

        try:
            chart_b64 = self._chart.render_l4_chart(
                shared["klines_1d"],
                ema_50=shared.get("ema_50_1d"),
                ema_200=shared.get("ema_200_1d"),
                key_levels=(l2_out or {}).get("key_levels"),
                atr_14=shared.get("atr_14_1d"),
                funding_rate=shared.get("funding_rate_series"),
                open_interest=shared.get("open_interest_series"),
                exchange_net_flow=shared.get("exchange_net_flow_series"),
            )
        except Exception as e:
            logger.warning("orchestrator: L4 chart render failed: %s", e)
            chart_b64 = None

        l4_input = dict(context.get("l4") or {})
        l4_input["l1_output"] = l1_out
        l4_input["l2_output"] = l2_out
        l4_input["l3_output"] = l3_out
        l4_input["chart_b64"] = chart_b64
        if stale_map:
            l4_input["source_stale_map"] = stale_map
            l4_input["source_hours_map"] = hours_map
        try:
            out = self._agents["l4"].analyze(
                l4_input, client=build_anthropic_client(),
            )
        except Exception as e:
            logger.warning("orchestrator: L4 analyze raised: %s", e)
            out = self._agents["l4"]._fallback_output()
            out["status"] = "degraded_l4_failed"

        if stale_map and fresh_ratio < 1.0:
            out = _apply_factor_grain_override(4, out, fresh_ratio)

        result["latency_ms"]["l4"] = int((time.time() - t0) * 1000)
        if not str(out.get("status", "")).startswith("success"):
            if result["status"] == "ok":
                result["status"] = f"degraded_l4_{out.get('status', 'failed')}"
        return out

    def _run_l5(
        self,
        context: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        """L5 独立做宏观判断。Sprint 1.10-F:失败时用 CircuitBreaker.apply_macro_fallback()
        硬编码兜底(D4=a),master 仍跑(§6.4.2)。"""
        t0 = time.time()
        # Sprint E Step 3:L5 是非关键层,即使全 stale 仍跑 AI(events_calendar
        # 是本地数据,L5 还能输出基础 stance);只调 confidence 不跳 AI
        stale_map, hours_map = _stale_state_from_context(context)
        fresh_ratio = fresh_ratio_for_layer(5, stale_map) if stale_map else 1.0

        l5_input = dict(context.get("l5") or {})
        if stale_map:
            l5_input["source_stale_map"] = stale_map
            l5_input["source_hours_map"] = hours_map
        try:
            out = self._agents["l5"].analyze(
                l5_input, client=build_anthropic_client(),
            )
        except Exception as e:
            logger.warning("orchestrator: L5 analyze raised: %s", e)
            out = self._agents["l5"]._fallback_output()
            out["status"] = "degraded_l5_failed"

        if stale_map and fresh_ratio < 1.0:
            out = _apply_factor_grain_override(5, out, fresh_ratio)

        # Sprint 1.10-F:L5 失败时,用 CircuitBreaker.apply_macro_fallback() 硬编码 macro 替代
        # master 仍跑,但用此硬编码 macro 而非 _fallback_output(后者无 macro 字段)
        if not str(out.get("status", "")).startswith("success"):
            macro_fb = CircuitBreaker.apply_macro_fallback()
            # 保留原 status 字段(降级标记)+ 注入硬编码 macro 关键字段
            macro_fb["status"] = out.get("status", "degraded_l5_failed_macro_fallback")
            out = macro_fb
            # retry_log 标记
            result.setdefault("retry_log", {}).update({
                "macro_fallback_applied": True,
                "macro_fallback_reason": "l5_failed_apply_hardcoded_macro_d4_a",
            })

        result["latency_ms"]["l5"] = int((time.time() - t0) * 1000)
        if not str(out.get("status", "")).startswith("success"):
            if result["status"] == "ok":
                result["status"] = f"degraded_l5_{out.get('status', 'failed')}"
        return out

    def _run_master(
        self,
        context: dict[str, Any],
        shared: dict[str, Any],
        l1_out: dict[str, Any],
        l2_out: dict[str, Any],
        l3_out: dict[str, Any],
        l4_out: dict[str, Any],
        l5_out: dict[str, Any],
        crowding_mult: float,
        event_mult: float,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        t0 = time.time()
        master_input = dict(context.get("master") or {})
        master_input["l1_output"] = l1_out
        master_input["l2_output"] = l2_out
        master_input["l3_output"] = l3_out
        master_input["l4_output"] = l4_out
        master_input["l5_output"] = l5_out
        master_input["_system_provided"] = {
            "crowding_multiplier": crowding_mult,
            "event_multiplier": event_mult,
            "current_close": shared.get("current_close"),
        }
        try:
            out = self._agents["master"].analyze(
                master_input, client=build_anthropic_client(),
            )
        except Exception as e:
            logger.warning("orchestrator: master analyze raised: %s", e)
            # Sprint 1.10-F:接通 1.10-D 的 thesis_aware_fallback(D2 = silent / evaluate_existing)
            # has_active_thesis 从 master_ctx 读(由 master_input_builder 装配)
            master_ctx = context.get("master") or {}
            has_active = bool(master_ctx.get("active_thesis"))
            out = MasterAdjudicator.thesis_aware_fallback(
                has_active_thesis=has_active,
            )
            # retry_log 标记 fallback 接通
            result.setdefault("retry_log", {}).update({
                "thesis_aware_fallback_applied": True,
                "thesis_aware_fallback_reason": (
                    "master_failed_keep_thesis" if has_active
                    else "master_failed_silent"
                ),
            })

        result["latency_ms"]["master"] = int((time.time() - t0) * 1000)
        if not str(out.get("status", "")).startswith("success"):
            if result["status"] == "ok":
                result["status"] = (
                    f"degraded_master_{out.get('status', 'failed')}"
                )
        return out


# ============================================================
# 内部 helper
# ============================================================

def _kline_summary(klines: Any) -> Optional[dict[str, Any]]:
    """K 线 DataFrame → 简短 summary dict(给 AI prompt 的文本部分)。"""
    if klines is None:
        return None
    try:
        n = len(klines)
        if n == 0:
            return None
        first = klines.index[0]
        last = klines.index[-1]
        last_close = float(klines["close"].iloc[-1]) if "close" in klines \
            else (float(klines["Close"].iloc[-1]) if "Close" in klines else None)
        return {
            "rows": int(n),
            "first_ts": str(first),
            "last_ts": str(last),
            "last_close": last_close,
        }
    except Exception:
        return None


# ============================================================
# 入口函数(手动测试 / 后续 Sprint 1.9 接入 jobs.py)
# ============================================================

def run_ai_pipeline_v13(context: dict[str, Any]) -> dict[str, Any]:
    """v1.3 AI 主导 pipeline 入口。手动测试用。

    返回 {layers, validator, status, latency_ms, tokens}。
    """
    return AIOrchestrator().run_full_a(context)
