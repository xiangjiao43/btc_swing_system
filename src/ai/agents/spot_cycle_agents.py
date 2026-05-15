"""Layer A spot cycle AI agents."""

from __future__ import annotations

import json
from typing import Any

from ._base import BaseAgent
from ..spot_cycle_context_builder import (
    build_a1_cycle_stage_context,
    build_layer_a_cycle_adjudicator_context,
)
from ..spot_strategy_normalizer import (
    normalize_a1,
    normalize_a2,
    normalize_a3,
    normalize_a4,
    normalize_a5,
)
from ...utils.pipeline_progress import record_instant_stage


def _prompt_payload(context: dict[str, Any]) -> str:
    return json.dumps(context or {}, ensure_ascii=False, indent=2, default=str)


def _compact_prompt_payload(context: dict[str, Any]) -> str:
    return json.dumps(
        context or {},
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


class A1SpotCycleAnalyst(BaseAgent):
    AGENT_NAME = "a1_spot_cycle"
    PROMPT_FILE = "a1_spot_cycle.txt"

    def _build_user_prompt(self, context: dict[str, Any]) -> str:
        a1_context = build_a1_cycle_stage_context(context)
        payload = _compact_prompt_payload(a1_context)
        diagnostics = {
            "a1_prompt_context_chars": len(payload),
            "a1_estimated_context_tokens": max(1, len(payload) // 4),
            "a1_context_top_keys": list(a1_context.keys()),
            "a1_history_count": len(a1_context.get("recent_stage_history") or []),
            "timeout_sec": 120,
        }
        record_instant_stage(
            "Layer A A1 input size",
            status="success",
            message=diagnostics,
        )
        return "===== Layer A A1 精简输入 =====\n" + payload

    def _fallback_output(self) -> dict[str, Any]:
        return normalize_a1({
            "raw_stage_assessment": "mid_bull",
            "cycle_stage": "mid_bull",
            "confidence": "low",
            "headline": "大周期阶段不明确",
            "human_summary": "A1 AI 失败或数据不足，暂不判断大周期阶段。",
            "data_quality_notes": ["fallback_a1_ai_failed"],
        }, [])


class A2OnchainMacroAnalyst(BaseAgent):
    AGENT_NAME = "a2_onchain_macro"
    PROMPT_FILE = "a2_onchain_macro.txt"

    def _build_user_prompt(self, context: dict[str, Any]) -> str:
        return "===== Layer A A2 输入 =====\n" + _prompt_payload(context)

    def _fallback_output(self) -> dict[str, Any]:
        return normalize_a2({
            "onchain_macro_stance": "unclear",
            "confidence": "low",
            "human_summary": "A2 AI 失败或链上/宏观证据不足。",
            "data_quality_notes": ["fallback_a2_ai_failed"],
        })


class A3SpotOpportunityAnalyst(BaseAgent):
    AGENT_NAME = "a3_spot_opportunity"
    PROMPT_FILE = "a3_spot_opportunity.txt"

    def _build_user_prompt(self, context: dict[str, Any]) -> str:
        return "===== Layer A A3 输入 =====\n" + _prompt_payload(context)

    def _fallback_output(self) -> dict[str, Any]:
        return normalize_a3({
            "preferred_action_candidate": "hold",
            "confidence": "low",
            "human_summary": "A3 AI 失败或现货策略机会证据不足。",
            "suggested_plan": ["暂时保持观察"],
            "do_not_do": ["不要把 fallback 当成买卖信号"],
            "data_quality_notes": ["fallback_a3_ai_failed"],
        }, [])


class A4SpotRiskAnalyst(BaseAgent):
    AGENT_NAME = "a4_spot_risk"
    PROMPT_FILE = "a4_spot_risk.txt"

    def _build_user_prompt(self, context: dict[str, Any]) -> str:
        return "===== Layer A A4 输入 =====\n" + _prompt_payload(context)

    def _fallback_output(self) -> dict[str, Any]:
        return normalize_a4({
            "spot_risk_level": "elevated",
            "confidence": "low",
            "human_summary": "A4 AI 失败或风险证据不足，默认按偏高风险展示。",
            "data_quality_notes": ["fallback_a4_ai_failed"],
        })


class A5SpotAdjudicator(BaseAgent):
    AGENT_NAME = "a5_spot_adjudicator"
    PROMPT_FILE = "a5_spot_adjudicator.txt"

    def _build_user_prompt(self, context: dict[str, Any]) -> str:
        return "===== Layer A A5 输入 =====\n" + _prompt_payload(context)

    def _fallback_output(self) -> dict[str, Any]:
        return normalize_a5({
            "spot_action": "hold",
            "cycle_stage": "mid_bull",
            "confidence": "low",
            "headline": "暂无大周期策略",
            "human_summary": "A5 AI 失败或证据不足，默认现货策略为持有/观察。",
            "suggested_plan": ["等待下一次有效 Layer A 输出"],
            "do_not_do": ["不要自动应用现货买卖动作"],
            "what_would_change_mind": ["数据恢复完整并出现多维证据"],
            "next_review_focus": ["检查链上估值、ETF flow、宏观风险"],
            "data_quality_notes": ["fallback_a5_ai_failed"],
        }, [], [])


class LayerACycleAdjudicator(BaseAgent):
    """Single AI adjudicator for Layer A spot-cycle strategy.

    The four data packets are deterministic.  This agent only performs the one
    high-level trader adjudication before the deterministic state machine and
    validator finalize the official stage/action.
    """

    AGENT_NAME = "layer_a_cycle_adjudicator"
    PROMPT_FILE = "layer_a_cycle_adjudicator.txt"

    def _build_user_prompt(self, context: dict[str, Any]) -> str:
        adjudicator_context = build_layer_a_cycle_adjudicator_context(context)
        payload = _compact_prompt_payload(adjudicator_context)
        diagnostics = {
            "layer_a_adjudicator_context_chars": len(payload),
            "layer_a_adjudicator_estimated_context_tokens": max(1, len(payload) // 4),
            "layer_a_packet_keys": list((adjudicator_context.get("data_packets") or {}).keys()),
            "layer_a_history_count": len(adjudicator_context.get("recent_stage_history") or []),
            "timeout_sec": 120,
            "ai_call_count_target": 1,
        }
        record_instant_stage(
            "Layer A single adjudicator input size",
            status="success",
            message=diagnostics,
        )
        return "===== Layer A 单一大周期裁决输入 =====\n" + payload

    def _fallback_output(self) -> dict[str, Any]:
        return {
            "raw_stage_assessment": "bull_bear_transition",
            "official_stage_recommendation": "bull_bear_transition",
            "transition_status_recommendation": "pending",
            "cycle_stage_confidence": "low",
            "spot_action_recommendation": "hold",
            "risk_level": "elevated",
            "headline": "Layer A 大周期裁决降级",
            "trader_summary": "单一大周期裁决 AI 失败或证据不足，默认保持观察。",
            "supporting_evidence": [],
            "opposing_evidence": ["AI 裁决未成功返回"],
            "data_quality_notes": ["fallback_layer_a_cycle_adjudicator_failed"],
            "stage_change_reason": "AI 裁决失败，正式阶段交由状态机按上一轮和 fallback 处理。",
            "what_would_confirm_next_stage": ["下一次 Layer A 裁决恢复成功"],
            "what_would_invalidate_current_stage": ["关键数据继续缺失或 AI 连续失败"],
        }
