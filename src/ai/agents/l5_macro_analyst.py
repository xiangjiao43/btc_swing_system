"""L5 Macro Analyst — 建模 v1.3 §3.3.5 背景事件层。

输入(context):
  - 宏观因子(DXY / VIX / SP500 / Nasdaq / DGS10 等 FRED 数据)
  - 事件日历(72h 内 FOMC/CPI/NFP/PCE)
  - BTC vs 宏观相关性(60d corr)

输出 schema:
  {
    "agent": "l5_macro",
    "macro_stance": "risk_on" | "risk_neutral" | "risk_off" |
                    "extreme_risk_off" | "unclear",
    "macro_headwind_score": -10.0 to +10.0,
    "extreme_event_detected": bool,
    "extreme_event_details": dict | None,
    "structured_macro": dict,
    "active_macro_tags": [str, ...],
    "narrative": str,
    "data_completeness_pct": 0-100,
    "adjustment_guidance": {
        "stance_modifier": "support" | "neutral" | "challenge",
        "position_cap_multiplier_hint": float,
        "permission_adjustment": "tighten" | "neutral" | "loosen"
    },
    "notes": [str, ...],
    "status": "success" | "degraded_*"
  }
"""

from __future__ import annotations

import json
from typing import Any

from ._base import BaseAgent


class L5MacroAnalyst(BaseAgent):
    AGENT_NAME = "l5_macro"
    PROMPT_FILE = "l5_macro.txt"

    def _build_user_prompt(self, context: dict[str, Any]) -> str:
        """v3 prompt 期望:computed_macro_indicators + events_calendar_72h
        + extreme_event_flags + previous_l5。"""
        snapshot = {
            "computed_macro_indicators": context.get("computed_macro_indicators"),
            "events_calendar_72h": context.get("events_calendar_72h"),
            "extreme_event_flags": context.get("extreme_event_flags"),
            "previous_l5": context.get("previous_l5"),
        }
        snapshot = {k: v for k, v in snapshot.items() if v is not None}
        return (
            "===== L5 输入数据 =====\n"
            f"{json.dumps(snapshot, ensure_ascii=False, indent=2, default=str)}\n"
        )

    def _fallback_output(self) -> dict[str, Any]:
        return {
            "agent": self.AGENT_NAME,
            "macro_stance": "unclear",
            "macro_headwind_score": 0.0,
            "extreme_event_detected": False,
            "extreme_event_details": None,
            "structured_macro": {},
            "active_macro_tags": [],
            "narrative": "L5 AI 失败,fallback 到 unclear。",
            "data_completeness_pct": 0,
            "adjustment_guidance": {
                "stance_modifier": "neutral",
                "position_cap_multiplier_hint": 1.0,
                "permission_adjustment": "neutral",
            },
            "notes": ["fallback_l5_ai_failed"],
            "status": "degraded",
        }
