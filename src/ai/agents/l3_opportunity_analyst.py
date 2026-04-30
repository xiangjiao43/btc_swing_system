"""L3 Opportunity Analyst — 建模 v1.3 §3.3.3 机会执行层。

输入(context):
  - L1 / L2 输出
  - aSOPR / CDD / cycle_position 规则计算结果
  - 衍生品 funding / 拥挤度信号

输出 schema:
  {
    "agent": "l3_opportunity",
    "opportunity_grade": "A" | "B" | "C" | "none",
    "execution_permission": "can_open" | "cautious_open" | "ambush_only" |
                            "no_chase" | "watch" | "hold_only" | "protective",
    "grade_reasoning": str,
    "permission_reasoning": str,
    "anti_pattern_flags": [str, ...],
    "rule_trace": {
        "matched_rule": str,
        "upgrade_conditions": [str, ...]
    },
    "narrative": str,
    "notes": [str, ...],
    "status": "success" | "degraded_*"
  }
"""

from __future__ import annotations

import json
from typing import Any

from ._base import BaseAgent


class L3OpportunityAnalyst(BaseAgent):
    AGENT_NAME = "l3_opportunity"
    PROMPT_FILE = "l3_opportunity.txt"

    def _build_user_prompt(self, context: dict[str, Any]) -> str:
        snapshot = {
            "previous_l1": context.get("l1_output"),
            "previous_l2": context.get("l2_output"),
            "asopr": context.get("asopr_value"),
            "cdd": context.get("cdd_value"),
            "cycle_position_rule": context.get("cycle_position_rule"),
            "funding_pressure": context.get("funding_pressure"),
        }
        snapshot = {k: v for k, v in snapshot.items() if v is not None}
        return (
            "===== L3 输入数据 =====\n"
            f"{json.dumps(snapshot, ensure_ascii=False, indent=2, default=str)}\n"
        )

    def _fallback_output(self) -> dict[str, Any]:
        return {
            "agent": self.AGENT_NAME,
            "opportunity_grade": "none",
            "execution_permission": "watch",
            "grade_reasoning": "L3 AI 失败,fallback 到 grade=none + watch。",
            "permission_reasoning": "fallback path",
            "anti_pattern_flags": [],
            "rule_trace": {"matched_rule": "fallback", "upgrade_conditions": []},
            "narrative": "L3 AI 失败,无机会判断。",
            "notes": ["fallback_l3_ai_failed"],
            "status": "degraded",
        }
