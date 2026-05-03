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
    L1RegimeAnalyst,
    L2DirectionAnalyst,
    L3OpportunityAnalyst,
    L4RiskAnalyst,
    L5MacroAnalyst,
    MasterAdjudicator,
)
from .agents.chart_renderer import ChartRenderer
from .anti_pattern_signals import compute_anti_pattern_signals
from .client import build_anthropic_client
from .validator import validate_master_output


logger = logging.getLogger(__name__)


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
            }
        self._agents = agents

        # Sprint 1.10-E:旧 AdjudicatorValidator(v1.3 H1-H10)删除,改用 v1.4 24 条
        # 模块级函数 validate_master_output;orchestrator 调用见 run_full_a 末尾

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run_full_a(self, context: dict[str, Any]) -> dict[str, Any]:
        """完整 A 流程(每日 16:00 用)。

        context 必含(Sprint 1.9-A.4 起,per-agent 嵌套结构):
          - "_shared":  {klines_1d, klines_4h, ema_*, adx, atr, swing_points,
                          funding_rate_series, open_interest_series,
                          exchange_net_flow_series, current_close, ...}
          - "l1":       {klines_1d_30d_close, computed_indicators, previous_l1}
          - "l2":       {klines_1d_30d_close, computed_indicators,
                          rule_cycle_position, previous_l2}
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
        l1_out = self._run_l1(context, shared, result)
        result["layers"]["l1"] = l1_out

        # ---- 2. L2(注入 l1_output)----
        l2_out = self._run_l2(context, shared, l1_out, result)
        result["layers"]["l2"] = l2_out

        # ---- 5. L5(独立,无依赖)— 提前跑,L3 anti_pattern 需 extreme_event_flags ----
        l5_out = self._run_l5(context, result)
        result["layers"]["l5"] = l5_out

        # ---- 3. L3(注入 l1+l2 output + anti_pattern_signals)----
        l3_out = self._run_l3(
            context, shared, l1_out, l2_out, l5_out, result,
        )
        result["layers"]["l3"] = l3_out

        # ---- 4. L4(注入 l1+l2+l3 output)----
        l4_out = self._run_l4(
            context, shared, l1_out, l2_out, l3_out, result,
        )
        result["layers"]["l4"] = l4_out

        # ---- 计算 _system_provided multipliers ----
        crowding_mult = self._compute_crowding_multiplier(l4_out)
        events_72h = (context.get("l5") or {}).get("events_calendar_72h") or []
        event_mult = self._compute_event_multiplier(events_72h)

        # ---- 6. 主裁(注入 l1-l5 output + _system_provided)----
        master_out = self._run_master(
            context, shared, l1_out, l2_out, l3_out, l4_out, l5_out,
            crowding_mult, event_mult, result,
        )
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
            "current_btc_price": master_ctx.get("current_btc_price"),
            "stop_tightening_count_so_far": master_ctx.get("stop_tightening_count_so_far", 0),
            "initial_stop_loss_price": master_ctx.get("initial_stop_loss_price"),
            "active_thesis_avg_price": master_ctx.get("active_thesis_avg_price"),
        }
        validated_output, constraint_activations = validate_master_output(
            master_out, validator_ctx,
        )
        result["layers"]["master"] = validated_output
        result["constraint_activations"] = constraint_activations

        return result

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
        try:
            # Sprint 1.9-A.5.2 fix:每层新建 client 避中转站连接复用限流
            out = self._agents["l1"].analyze(
                l1_input, client=build_anthropic_client(),
            )
        except Exception as e:
            logger.warning("orchestrator: L1 analyze raised: %s", e)
            out = self._agents["l1"]._fallback_output()
            out["status"] = "degraded_l1_failed"

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
        try:
            out = self._agents["l2"].analyze(
                l2_input, client=build_anthropic_client(),
            )
        except Exception as e:
            logger.warning("orchestrator: L2 analyze raised: %s", e)
            out = self._agents["l2"]._fallback_output()
            out["status"] = "degraded_l2_failed"

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
        try:
            out = self._agents["l3"].analyze(
                l3_input, client=build_anthropic_client(),
            )
        except Exception as e:
            logger.warning("orchestrator: L3 analyze raised: %s", e)
            out = self._agents["l3"]._fallback_output()
            out["status"] = "degraded_l3_failed"

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
        try:
            out = self._agents["l4"].analyze(
                l4_input, client=build_anthropic_client(),
            )
        except Exception as e:
            logger.warning("orchestrator: L4 analyze raised: %s", e)
            out = self._agents["l4"]._fallback_output()
            out["status"] = "degraded_l4_failed"

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
        t0 = time.time()
        # L5 独立做宏观判断,不消费 L1-L4 输出
        l5_input = dict(context.get("l5") or {})
        try:
            out = self._agents["l5"].analyze(
                l5_input, client=build_anthropic_client(),
            )
        except Exception as e:
            logger.warning("orchestrator: L5 analyze raised: %s", e)
            out = self._agents["l5"]._fallback_output()
            out["status"] = "degraded_l5_failed"

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
            out = self._agents["master"]._fallback_output()
            out["status"] = "degraded_master_failed"

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
