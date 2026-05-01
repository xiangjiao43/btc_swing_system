"""L1 Regime Analyst — 建模 v1.3 §3.3.1 市场状态层。

输入(context):
  - klines_1d: pd.DataFrame(最近 ~365 天 1d K 线)
  - klines_4h: pd.DataFrame(最近 ~180 天 4h K 线)
  - 关键技术指标(ADX-14 / ATR 180d 分位 / Swing 序列等)
  - 历史 L1 报告(可选,做"对比上次"判断用)

输出 schema:
  {
    "agent": "l1_regime",
    "regime": "trend_up" | "trend_down" | "transition_up" | "transition_down" |
              "range_high" | "range_mid" | "range_low" | "chaos" |
              "unclear_insufficient",
    "regime_stability": "stable" | "shifting" | "uncertain",
    "volatility_regime": "low" | "normal" | "elevated" | "extreme",
    "confidence": 0.0-1.0,
    "key_signals": [str, ...],
    "contradicting_signals": [str, ...],
    "narrative": str,
    "data_completeness_pct": 0-100,
    "notes": [str, ...],
    "status": "success" | "degraded_*"
  }
"""

from __future__ import annotations

import json
from typing import Any

from ._base import BaseAgent


class L1RegimeAnalyst(BaseAgent):
    AGENT_NAME = "l1_regime"
    PROMPT_FILE = "l1_regime.txt"

    def _build_user_prompt(self, context: dict[str, Any]) -> str:
        """v3 prompt 期望字段:klines_1d_30d_close + computed_indicators + previous_l1。"""
        snapshot = {
            "klines_1d_30d_close": context.get("klines_1d_30d_close"),
            "computed_indicators": context.get("computed_indicators"),
            "previous_l1": context.get("previous_l1"),
        }
        snapshot = {k: v for k, v in snapshot.items() if v is not None}
        return (
            "===== L1 输入数据 =====\n"
            f"{json.dumps(snapshot, ensure_ascii=False, indent=2, default=str)}\n"
        )

    def _fallback_output(self) -> dict[str, Any]:
        return {
            "agent": self.AGENT_NAME,
            "regime": "unclear_insufficient",
            "regime_stability": "uncertain",
            "volatility_regime": "normal",
            "confidence": 0.0,
            "key_signals": [],
            "contradicting_signals": [],
            "narrative": "L1 AI 失败,fallback 到不明确档位。",
            "data_completeness_pct": 0,
            "notes": ["fallback_l1_ai_failed"],
            "status": "degraded",
        }
