"""Layer A spot cycle AI agents."""

from __future__ import annotations

import json
from typing import Any

from ._base import BaseAgent
from ..spot_cycle_context_builder import build_layer_a_cycle_adjudicator_context
from ...utils.pipeline_progress import record_instant_stage


def _compact_prompt_payload(context: dict[str, Any]) -> str:
    return json.dumps(
        context or {},
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


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
