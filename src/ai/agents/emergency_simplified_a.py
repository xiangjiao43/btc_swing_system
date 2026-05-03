"""src/ai/agents/emergency_simplified_a.py — Sprint 1.10-G 简化 A 应急 AI。

对齐 docs/modeling.md b25cfe6(v1.4)§3.3.8:
- **触发**:价格 ±5%(空仓)或 ±3%(持仓)异动
- **输入**:current strategy_state + 异动价 + 关键因子 + active_thesis(若有)
- **输出**:`{thesis_still_valid, immediate_action, reasoning}`
- **immediate_action 4 取值**:maintain / emergency_exit / tighten_stop / wait_next_full
- **成本**:~$0.10 / 次,单 AI(简化版,非完整 6 AI)

设计纪律:
- 继承 BaseAgent(prompt 加载 + AI 调用 + JSON 解析 + fallback 全继承)
- prompt 文件:src/ai/agents/prompts/emergency_simplified_a.txt
- _fallback_output:thesis_still_valid=null + immediate_action=maintain
  + reasoning="AI 失败,fallback 保守保持现状"
- **本 sprint 全 mock 测试**(留 1.10-L 真 API 验证)
"""
from __future__ import annotations

from typing import Any

from ._base import BaseAgent


VALID_ACTIONS = ("maintain", "emergency_exit", "tighten_stop", "wait_next_full")


class EmergencySimplifiedA(BaseAgent):
    """v1.4 §3.3.8 简化 A 应急 AI。"""

    AGENT_NAME = "emergency_simplified_a"
    PROMPT_FILE = "emergency_simplified_a.txt"

    def _build_user_prompt(self, context: dict[str, Any]) -> str:
        """把 context dict 拍平成 user prompt 字符串。

        context 字段:
          - current_strategy_state: str(14 档)
          - triggered_at_price: float
          - baseline_price: float
          - pct_change: float (带符号)
          - key_factors: dict(funding_rate / open_interest / lsr 等最新快照)
          - active_thesis: dict | None(direction / break_conditions /
                                        stop_loss_price / lifecycle_stage)
        """
        state = context.get("current_strategy_state", "FLAT")
        trig_px = context.get("triggered_at_price")
        base_px = context.get("baseline_price")
        pct = context.get("pct_change", 0.0)
        kf = context.get("key_factors") or {}
        active = context.get("active_thesis")

        lines: list[str] = [
            f"当前状态:{state}",
            f"异动后价格:{trig_px}",
            f"上次 run 价格(baseline):{base_px}",
            f"涨跌幅:{pct:+.4%}" if isinstance(pct, (int, float)) else f"涨跌幅:{pct}",
            "",
            "关键因子最新快照:",
        ]
        if kf:
            for k, v in kf.items():
                lines.append(f"  - {k}: {v}")
        else:
            lines.append("  - (无快照数据)")

        lines.append("")
        if active:
            lines.append("active thesis:")
            lines.append(f"  - direction: {active.get('direction')}")
            lines.append(f"  - lifecycle_stage: {active.get('lifecycle_stage')}")
            lines.append(f"  - confidence_score: {active.get('confidence_score')}")
            sl = active.get("stop_loss_price")
            if sl is not None:
                lines.append(f"  - stop_loss_price: {sl}")
            breaks = active.get("break_conditions") or []
            if breaks:
                lines.append(f"  - break_conditions:")
                for b in breaks:
                    lines.append(f"      * {b}")
        else:
            lines.append("active thesis:无(空仓状态)")

        lines.append("")
        lines.append("请输出 JSON,严格按 system prompt 字段约束。")
        return "\n".join(lines)

    def _fallback_output(self) -> dict[str, Any]:
        """AI 失败时保守 fallback:维持现状,thesis 状态未知。

        v1.4 §3.3.8 隐式约定:简化 A 失败时不应做激进决策(不该 emergency_exit
        也不该 tighten_stop,这两个会改持仓 / 改 stop 价位)。maintain 最安全:
        等下次 16:00 完整 6 AI run 重新评估。
        """
        return {
            "agent": self.AGENT_NAME,
            "status": "degraded",
            "thesis_still_valid": None,
            "immediate_action": "maintain",
            "reasoning": "应急 AI 失败,fallback 保守保持现状,等下次完整 run 重新评估",
        }

    # ------------------------------------------------------------------
    # 输出校验(D1=a 决策 — 1.10-L 留严校验,本 sprint 简化)
    # ------------------------------------------------------------------

    @staticmethod
    def is_valid_action(action: str | None) -> bool:
        """immediate_action 是否在 4 取值枚举内。"""
        return action in VALID_ACTIONS

    @staticmethod
    def normalize_output(out: dict[str, Any]) -> dict[str, Any]:
        """轻量校验:若 immediate_action 非法,改为 maintain + notes 标记。

        本 sprint 简化版;严校验(thesis_still_valid 与 active_thesis 一致性 /
        reasoning 长度等)留 1.10-L。
        """
        if not isinstance(out, dict):
            return {
                "agent": EmergencySimplifiedA.AGENT_NAME,
                "status": "degraded_invalid_output_type",
                "thesis_still_valid": None,
                "immediate_action": "maintain",
                "reasoning": "AI 输出非 dict,fallback 保守 maintain",
            }
        action = out.get("immediate_action")
        if not EmergencySimplifiedA.is_valid_action(action):
            normed = dict(out)
            normed["immediate_action"] = "maintain"
            notes = list(normed.get("notes") or [])
            notes.append(
                f"invalid_action_normalized_to_maintain (raw={action!r})"
            )
            normed["notes"] = notes
            return normed
        return out
