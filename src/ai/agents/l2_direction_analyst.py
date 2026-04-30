"""L2 Direction Analyst — 建模 v1.3 §3.3.2 方向结构层。

输入(context):
  - L1 输出(regime / volatility 等)
  - 衍生品因子(funding_rate / OI / LSR / liquidation 等)
  - 链上结构因子(LTH-MVRV / STH-MVRV / SOPR-aSOPR / HODL Waves 等)
  - 价格结构(EMA 排列 / 支撑阻力)

输出 schema:
  {
    "agent": "l2_direction",
    "stance": "bullish" | "bearish" | "neutral" | "transitioning",
    "stance_confidence": 0.0-1.0,
    "phase": "early" | "mid" | "late" | "chaotic" | "n_a",
    "key_signals": [{"name": str, "value": Any, "interpretation": str}, ...],
    "contradicting_signals": [{"name": str, "interpretation": str}, ...],
    "narrative": str,
    "structured_macro": dict,    # 可选传递给 L4
    "confidence_breakdown": {
        "evidence_agreement": 0.0-1.0,
        "data_completeness": 0.0-1.0
    },
    "notes": [str, ...],
    "status": "success" | "degraded_*"
  }
"""

from __future__ import annotations

import json
from typing import Any

from ._base import BaseAgent


class L2DirectionAnalyst(BaseAgent):
    AGENT_NAME = "l2_direction"
    PROMPT_FILE = "l2_direction.txt"

    def _build_user_prompt(self, context: dict[str, Any]) -> str:
        snapshot = {
            "previous_l1_output": context.get("l1_output"),
            "derivatives_snapshot": context.get("derivatives_snapshot"),
            "onchain_structure_snapshot": context.get("onchain_structure"),
            "price_structure": context.get("price_structure"),
        }
        snapshot = {k: v for k, v in snapshot.items() if v is not None}
        return (
            "===== L2 输入数据 =====\n"
            f"{json.dumps(snapshot, ensure_ascii=False, indent=2, default=str)}\n"
        )

    def _fallback_output(self) -> dict[str, Any]:
        return {
            "agent": self.AGENT_NAME,
            "stance": "neutral",
            "stance_confidence": 0.0,
            "phase": "n_a",
            "key_signals": [],
            "contradicting_signals": [],
            "narrative": "L2 AI 失败,fallback 到中性档位。",
            "structured_macro": {},
            "confidence_breakdown": {
                "evidence_agreement": 0.0,
                "data_completeness": 0.0,
            },
            "notes": ["fallback_l2_ai_failed"],
            "status": "degraded",
        }
