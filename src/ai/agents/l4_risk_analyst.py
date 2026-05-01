"""L4 Risk Analyst — 建模 v1.3 §3.3.4 风险失效层。

输入(context):
  - L1-L3 输出
  - 当前 BTC 价格(实时)
  - 拥挤度信号(funding 极端 / OI 集中度等)
  - account_state(若有持仓)

输出 schema:
  {
    "agent": "l4_risk",
    "position_cap_pct": 0.0-100.0,    # 0-100 浮点数(如 70.0 = 70%)
    "overall_risk_level": "low" | "moderate" | "elevated" | "high" | "critical",
    "hard_invalidation_levels": [
        {"price": float, "direction": "below"|"above", "basis": str,
         "priority": int, "confirmation_timeframe": str},
        ...
    ],
    "risk_reward_ratio": float,
    "active_risk_tags": [str, ...],
    "narrative": str,
    "position_cap_composition": dict,    # 审计:base × 各乘数
    "permission_chain": dict,            # 审计:permission 推导链
    "notes": [str, ...],
    "status": "success" | "degraded_*"
  }
"""

from __future__ import annotations

import json
from typing import Any

from ._base import BaseAgent


class L4RiskAnalyst(BaseAgent):
    AGENT_NAME = "l4_risk"
    PROMPT_FILE = "l4_risk.txt"

    def _build_user_prompt(self, context: dict[str, Any]) -> str:
        """v2 prompt 期望:computed_indicators + l1/l2/l3_output + current_state
        + previous_l4。注:不传 crowding_signals(违反铁律 1)。"""
        snapshot = {
            "computed_indicators": context.get("computed_indicators"),
            "l1_output": context.get("l1_output"),
            "l2_output": context.get("l2_output"),
            "l3_output": context.get("l3_output"),
            "current_state": context.get("current_state"),
            "previous_l4": context.get("previous_l4"),
        }
        snapshot = {k: v for k, v in snapshot.items() if v is not None}
        return (
            "===== L4 输入数据 =====\n"
            f"{json.dumps(snapshot, ensure_ascii=False, indent=2, default=str)}\n"
        )

    def _fallback_output(self) -> dict[str, Any]:
        return {
            "agent": self.AGENT_NAME,
            "position_cap_pct": 15.0,    # 硬下限
            "overall_risk_level": "high",
            "hard_invalidation_levels": [],
            "risk_reward_ratio": None,
            "active_risk_tags": ["l4_ai_failed"],
            "narrative": "L4 AI 失败,fallback 到 high risk + 15% 硬下限。",
            "position_cap_composition": {},
            "permission_chain": {},
            "notes": ["fallback_l4_ai_failed"],
            "status": "degraded",
        }
