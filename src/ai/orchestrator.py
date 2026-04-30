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
from .validator import AdjudicatorValidator


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

        self._validator = AdjudicatorValidator()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run_full_a(self, context: dict[str, Any]) -> dict[str, Any]:
        """完整 A 流程(每日 16:00 用)。

        context 必含:
          - klines_1d: pd.DataFrame (≥180 天,做 L1/L2/L4 主图)
          - klines_4h: pd.DataFrame (≥30 天,做 L2 副图)
          - computed_indicators: dict (各种数值,EMA/ADX/ATR/funding/OI 等)
          - macro_indicators: dict (DXY/VIX/M2 等)
          - events_calendar_72h: list
          - extreme_event_flags: dict
          - current_state: str
          - current_close: float
          - previous_strategy_run: dict (可选)
          - previous_l1, l2, l3, l4, l5, master: dict (可选)
        """
        result: dict[str, Any] = {
            "layers": {},
            "validator": None,
            "status": "ok",
            "latency_ms": {},
            "tokens": {},
        }

        # ---- 1. L1 AI ----
        l1_out = self._run_l1(context, result)
        result["layers"]["l1"] = l1_out

        # ---- 2. L2 AI ----
        l2_out = self._run_l2(context, l1_out, result)
        result["layers"]["l2"] = l2_out

        # ---- 3. L3 AI ----
        l3_out = self._run_l3(context, l1_out, l2_out, result)
        result["layers"]["l3"] = l3_out

        # ---- 4. L4 AI ----
        l4_out = self._run_l4(context, l1_out, l2_out, l3_out, result)
        result["layers"]["l4"] = l4_out

        # ---- 5. L5 AI ----
        l5_out = self._run_l5(context, result)
        result["layers"]["l5"] = l5_out

        # ---- 计算 _system_provided multipliers ----
        crowding_mult = self._compute_crowding_multiplier(l4_out)
        event_mult = self._compute_event_multiplier(
            context.get("events_calendar_72h") or []
        )

        # ---- 6. 主裁 AI ----
        master_out = self._run_master(
            context, l1_out, l2_out, l3_out, l4_out, l5_out,
            crowding_mult, event_mult, result,
        )
        result["layers"]["master"] = master_out

        # ---- 7. Validator ----
        v_result = self._validator.validate(
            master_output=master_out,
            l1_output=l1_out, l2_output=l2_out, l3_output=l3_out,
            l4_output=l4_out, l5_output=l5_out,
            current_state=context.get("current_state", "FLAT"),
        )
        result["layers"]["master"] = v_result["validated_output"]
        result["validator"] = {
            "violations": v_result["violations"],
            "passed": v_result["passed"],
        }

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
        result: dict[str, Any],
    ) -> dict[str, Any]:
        t0 = time.time()
        try:
            chart_b64 = self._chart.render_l1_chart(
                context["klines_1d"],
                ema_20=context.get("ema_20_1d"),
                ema_50=context.get("ema_50_1d"),
                ema_200=context.get("ema_200_1d"),
                adx=context.get("adx_14_1d"),
                atr_180d_pct=context.get("atr_180d_pct_1d"),
                swing_points=context.get("swing_points_1d"),
            )
        except Exception as e:
            logger.warning("orchestrator: L1 chart render failed: %s", e)
            chart_b64 = None

        l1_input = {
            "indicators": context.get("computed_indicators"),
            "klines_1d_summary": _kline_summary(context.get("klines_1d")),
            "klines_4h_summary": _kline_summary(context.get("klines_4h")),
            "previous_l1": context.get("previous_l1"),
            "chart_b64": chart_b64,
        }
        try:
            out = self._agents["l1"].analyze(l1_input)
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
        l1_out: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        t0 = time.time()
        try:
            chart_b64 = self._chart.render_l2_chart(
                context["klines_1d"],
                klines_4h=context.get("klines_4h"),
                ema_20_1d=context.get("ema_20_1d"),
                ema_50_1d=context.get("ema_50_1d"),
                ema_20_4h=context.get("ema_20_4h"),
                ema_50_4h=context.get("ema_50_4h"),
                swing_points_1d=context.get("swing_points_1d"),
                key_levels=context.get("key_levels_rule_estimate"),
            )
        except Exception as e:
            logger.warning("orchestrator: L2 chart render failed: %s", e)
            chart_b64 = None

        l2_input = {
            "l1_output": l1_out,
            "derivatives_snapshot": context.get("derivatives_snapshot"),
            "onchain_structure": context.get("onchain_structure"),
            "price_structure": context.get("computed_indicators"),
            "rule_cycle_position": context.get("rule_cycle_position"),
            "previous_l2": context.get("previous_l2"),
            "chart_b64": chart_b64,
        }
        try:
            out = self._agents["l2"].analyze(l2_input)
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
        l1_out: dict[str, Any],
        l2_out: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        t0 = time.time()
        # L3 不需要图
        l3_input = {
            "l1_output": l1_out,
            "l2_output": l2_out,
            "asopr_value": (context.get("computed_indicators") or {}
                            ).get("asopr_value"),
            "cdd_value": (context.get("computed_indicators") or {}
                          ).get("cdd_value"),
            "cycle_position_rule": context.get("rule_cycle_position"),
            "funding_pressure": (context.get("computed_indicators") or {}
                                 ).get("funding_pressure"),
            "risk_preview": context.get("risk_preview"),
            "anti_pattern_signals": context.get("anti_pattern_signals"),
            "current_state": context.get("current_state", "FLAT"),
            "previous_l3": context.get("previous_l3"),
        }
        try:
            out = self._agents["l3"].analyze(l3_input)
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
        l1_out: dict[str, Any],
        l2_out: dict[str, Any],
        l3_out: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        t0 = time.time()
        try:
            chart_b64 = self._chart.render_l4_chart(
                context["klines_1d"],
                ema_50=context.get("ema_50_1d"),
                ema_200=context.get("ema_200_1d"),
                key_levels=(l2_out or {}).get("key_levels"),
                atr_14=context.get("atr_14_1d"),
                funding_rate=context.get("funding_rate_series"),
                open_interest=context.get("open_interest_series"),
                exchange_net_flow=context.get("exchange_net_flow_series"),
            )
        except Exception as e:
            logger.warning("orchestrator: L4 chart render failed: %s", e)
            chart_b64 = None

        l4_input = {
            "l1_output": l1_out,
            "l2_output": l2_out,
            "l3_output": l3_out,
            "current_price": context.get("current_close"),
            "crowding_signals": context.get("crowding_signals"),
            "account_state": context.get("account_state"),
            "previous_l4": context.get("previous_l4"),
            "chart_b64": chart_b64,
        }
        try:
            out = self._agents["l4"].analyze(l4_input)
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
        l5_input = {
            "macro_factors": context.get("macro_indicators"),
            "events_72h": context.get("events_calendar_72h"),
            "extreme_event_flags": context.get("extreme_event_flags"),
            "btc_corr_60d": context.get("btc_macro_corr_60d"),
            "previous_l5": context.get("previous_l5"),
        }
        try:
            out = self._agents["l5"].analyze(l5_input)
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
        master_input = {
            "l1_output": l1_out,
            "l2_output": l2_out,
            "l3_output": l3_out,
            "l4_output": l4_out,
            "l5_output": l5_out,
            "current_state": context.get("current_state", "FLAT"),
            "previous_strategy_run": context.get("previous_strategy_run"),
            "_system_provided": {
                "crowding_multiplier": crowding_mult,
                "event_multiplier": event_mult,
                "current_close": context.get("current_close"),
            },
            # 主裁需要的额外 keys 给原 master_adjudicator.py 用:
            "state_machine_current": context.get("current_state", "FLAT"),
            "allowed_transitions": context.get("allowed_transitions"),
            "account_state": context.get("account_state"),
            "hard_invalidation_levels": (l4_out or {}
                                         ).get("hard_invalidation_levels"),
        }
        try:
            out = self._agents["master"].analyze(master_input)
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
