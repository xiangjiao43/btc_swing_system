"""Master Adjudicator — 建模 v1.3 §3.3.6 主裁层。

输入(context):
  - L1-L5 输出(完整)
  - 14 档状态机当前状态 + 合法迁移集合
  - account_state(若有持仓)
  - hard_invalidation_levels(L4 已给定,主裁只能选不能改)

输出 schema:
  {
    "agent": "master_adjudicator",
    "action": str,                       # 必须在 allowed_transitions
    "direction": "long" | "short" | None,
    "confidence": 0.0-1.0,
    "rationale": str,
    "narrative": str,
    "one_line_summary": str,
    "opportunity_grade": str,            # 必须 = L3 输出(Validator 强制)
    "trade_plan": {
        "direction": str,
        "confidence_tier": "high" | "medium" | "low",
        "max_position_size_pct": float,
        "entry_zones": [...],
        "stop_loss": float,              # 必须从 L4.hard_invalidation_levels 选
        "take_profit_plan": [...],
        "dynamic_notes": str
    } | None,                            # grade=none 时为 None
    "primary_drivers": [...],
    "counter_arguments": [...],          # ≥1 条(Validator 强制)
    "what_would_change_mind": [...],
    "confidence_breakdown": dict,
    "transition_reason": str,
    "conflict_resolution": str,          # 5 层冲突时如何裁决(必填)
    "evidence_gaps": [...],
    "notes": [...],
    "status": "success" | "degraded_*"
  }
"""

from __future__ import annotations

import json
from typing import Any

from ._base import BaseAgent


class MasterAdjudicator(BaseAgent):
    AGENT_NAME = "master_adjudicator"
    PROMPT_FILE = "master_adjudicator.txt"

    def _build_user_prompt(self, context: dict[str, Any]) -> str:
        """v2 prompt 期望:l1-l5_output + current_state + previous_strategy_run
        + _system_provided(crowding_multiplier / event_multiplier / current_close)。
        hard_invalidation_levels 已嵌在 l4_output 内,master 自己取。"""
        snapshot = {
            "l1_output": context.get("l1_output"),
            "l2_output": context.get("l2_output"),
            "l3_output": context.get("l3_output"),
            "l4_output": context.get("l4_output"),
            "l5_output": context.get("l5_output"),
            "current_state": context.get("current_state"),
            "previous_strategy_run": context.get("previous_strategy_run"),
            "_system_provided": context.get("_system_provided"),
        }
        snapshot = {k: v for k, v in snapshot.items() if v is not None}
        return (
            "===== 主裁输入(L1-L5 + 状态机 + 历史 + system_provided)=====\n"
            f"{json.dumps(snapshot, ensure_ascii=False, indent=2, default=str)}\n"
        )

    def _fallback_output(self) -> dict[str, Any]:
        return {
            "agent": self.AGENT_NAME,
            "action": "watch",
            "direction": None,
            "confidence": 0.0,
            "rationale": "主裁 AI 失败,fallback 到 watch。",
            "narrative": "主裁 AI 失败,fallback 路径。",
            "one_line_summary": "主裁 AI 失败,保守观察。",
            "opportunity_grade": "none",
            "trade_plan": None,
            "primary_drivers": [],
            "counter_arguments": [
                {"text": "主裁 AI 失败,系统进入 fallback,人工复核必要"},
            ],
            "what_would_change_mind": [
                "主裁 AI 恢复正常",
                "5 层证据齐备且健康",
                "L3 grade ∈ {A, B, C}",
            ],
            "confidence_breakdown": {"trade_plan_confidence_tier": "none"},
            "transition_reason": "fallback path",
            "conflict_resolution": "fallback to watch (no AI judgment)",
            "evidence_gaps": ["master_ai_failed"],
            "notes": ["fallback_master_ai_failed"],
            "status": "degraded",
        }
