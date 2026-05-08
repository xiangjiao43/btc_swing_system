"""Master Adjudicator — Sprint 1.10-D thesis-aware 改造(v1.4 §3.3.6)。

v1.4 关键变化(对比 v1.3):
  - input 加 active_thesis / current_position / pending_orders / cooldown_state /
    fuse_state / last_5_assessments(由 master_input_builder.build_master_input 装配)
  - output 强制 mode 字段(evaluate_existing / new_thesis / silent_cooldown)
  - 14 档枚举全删(state_machine / action_state 不再用)
  - fallback thesis-aware:有 active_thesis → 保留 thesis 不评估;
                            无 → silent_cooldown(等下次重试)

设计纪律(本 sprint 1.10-D):
  - D2=a 不调真 AI:全部 mock,留 1.10-L 端到端真 API
  - D4=a 轻量验证:只校验 mode 字段存在 + 枚举合法,其他字段验证留 1.10-E Validator 24 条
  - 不动 BaseAgent 重试逻辑(留 1.10-F 重试机制 sprint)
  - 不动 orchestrator hook(本 commit 仅改 agent 子类)

输出 schema 对齐 v1.4 §3.3.6 三 mode:
  evaluate_existing → thesis_assessment + 通用 narrative/counter/what_change/evidence_ref
  new_thesis       → new_thesis(direction/break_conditions/entry_orders 等)+ 通用
  silent_cooldown  → silent_reason + 通用
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from ._base import BaseAgent


logger = logging.getLogger(__name__)


# Master AI v1.4 mode 枚举(D4=a 轻量验证用)
VALID_MODES = ("evaluate_existing", "new_thesis", "silent_cooldown")


class MasterAdjudicator(BaseAgent):
    AGENT_NAME = "master_adjudicator"
    PROMPT_FILE = "master_adjudicator.txt"

    # ------------------------------------------------------------------
    # BaseAgent hooks
    # ------------------------------------------------------------------

    def _build_user_prompt(self, context: dict[str, Any]) -> str:
        """v1.4 thesis-aware:把 master_input dict(由 master_input_builder 给)
        序列化为 user prompt。

        Sprint D Item 3:加 [数据新鲜度] 段。AI 必须看到每源 stale 状态。

        预期 context 结构(由 src/ai/master_input_builder.build_master_input 给):
          - l1_output / l2_output / l3_output / l4_output / l5_output
          - active_thesis (None 或 dict)
          - current_position (None 或 dict)
          - pending_orders (list)
          - cooldown_state (dict)
          - fuse_state (dict)
          - last_5_assessments (list)
          - data_freshness_summary (list[dict],Sprint D 新加)
        """
        snapshot = {
            # L1-L5 outputs
            "l1_output": context.get("l1_output"),
            "l2_output": context.get("l2_output"),
            "l3_output": context.get("l3_output"),
            "l4_output": context.get("l4_output"),
            "l5_output": context.get("l5_output"),
            # v1.4 thesis-aware 字段
            "active_thesis": context.get("active_thesis"),
            "current_position": context.get("current_position"),
            "pending_orders": context.get("pending_orders") or [],
            "cooldown_state": context.get("cooldown_state"),
            "fuse_state": context.get("fuse_state"),
            "last_5_assessments": context.get("last_5_assessments") or [],
        }
        # 删除 None 顶层(避免 prompt 里出现 "key": null 噪音)
        snapshot = {k: v for k, v in snapshot.items() if v is not None}

        freshness_block = self._format_freshness_block(
            context.get("data_freshness_summary") or [],
        )

        return (
            "===== Master AI v1.4 输入(thesis-aware,§3.3.6)=====\n"
            f"{freshness_block}"
            f"{json.dumps(snapshot, ensure_ascii=False, indent=2, default=str)}\n"
        )

    @staticmethod
    def _format_freshness_block(rows: list[dict[str, Any]]) -> str:
        """Sprint D Item 3:把 4 源 freshness 转成人读 [数据新鲜度] 段。
        任一源 is_stale=true → 明显标 ⚠️ + 「过期 N 小时」+ 「沿用 X 月 X 日数据」。
        """
        if not rows:
            return ""
        lines: list[str] = ["===== [数据新鲜度] Sprint D Item 3 ====="]
        any_stale = False
        for r in rows:
            name = r.get("display_name") or r.get("source") or "?"
            status = r.get("status")
            is_stale = bool(r.get("is_stale"))
            hours = r.get("hours_since_last_success")
            last_succ_bjt = (r.get("last_success_at_utc") or "")[:10]
            reason_label = r.get("failure_reason_label")

            if is_stale:
                any_stale = True
                age_str = (
                    f"已过期 {hours:.1f} 小时" if isinstance(hours, (int, float))
                    else "无可用历史成功记录"
                )
                if reason_label:
                    age_str += f"({reason_label})"
                fallback = (
                    f",沿用 {last_succ_bjt} 数据" if last_succ_bjt else ""
                )
                lines.append(f"  ⚠️ {name}:{age_str}{fallback}")
            else:
                age_str = (
                    f"{hours:.1f} 小时前成功"
                    if isinstance(hours, (int, float)) else "新鲜"
                )
                lines.append(f"  🟢 {name}:{age_str}")

        if any_stale:
            lines.append(
                "🛑 纪律(system prompt §过期数据):任一源 is_stale=true 时,"
                "narrative **必须**明确写"
                "\"X 数据已过期 N 小时,本判断可信度相应降级\","
                "且不得给 high 置信度结论;违反则 validator 拒绝,走 fallback。"
            )
        lines.append("")  # 空行分隔
        return "\n".join(lines) + "\n"

    def _fallback_output(self) -> dict[str, Any]:
        """基础 fallback(BaseAgent.analyze 在无 context 信息时调用)。

        v1.4 §6.4:无 active_thesis 时 → silent_cooldown(最保守)。
        有 active_thesis 时,调用方应改用 thesis_aware_fallback(has_active_thesis=True)。
        """
        return {
            "agent": self.AGENT_NAME,
            "status": "degraded",
            "mode": "silent_cooldown",
            "silent_reason": "master AI 失败,fallback silent(等下次重试)",
            "narrative": "主裁 AI 失败,系统进入 fallback。等下一档定时运行重试。",
            "one_line_summary": "主裁 AI 失败,保守观察。",
            "counter_arguments": [
                "主裁 AI 失败,系统进入 fallback,人工复核必要",
            ],
            "what_would_change_mind": [
                "主裁 AI 恢复正常",
                "5 层证据齐备且健康",
                "L3 grade ∈ {A, B, C}",
            ],
            "evidence_ref": [],
            "notes": ["fallback_master_ai_failed"],
        }

    # ------------------------------------------------------------------
    # v1.4 thesis-aware helpers(供调用方在 has_active_thesis 已知时使用)
    # ------------------------------------------------------------------

    @staticmethod
    def thesis_aware_fallback(has_active_thesis: bool) -> dict[str, Any]:
        """v1.4 §6.4 真表 fallback:

        - 有 active_thesis + master 失败 → mode=evaluate_existing 保留 thesis,
          assessment=mostly(保守评估,等下次重试)。挂单仍按计划触发。
        - 无 active_thesis + master 失败 → mode=silent_cooldown,等下次重试。

        **绝对不允许 fallback 创建 / 关闭 thesis**(避免规则错误关键决策)。
        """
        common = {
            "agent": MasterAdjudicator.AGENT_NAME,
            "narrative": "主裁 AI 失败,fallback 路径(等下次重试,1.10-F retry 机制)",
            "one_line_summary": "主裁 AI 失败,保守 fallback。",
            "counter_arguments": [
                "主裁 AI 失败,系统进入 fallback,人工复核必要",
            ],
            "what_would_change_mind": [
                "主裁 AI 恢复正常",
                "5 层证据齐备且健康",
                "L3 grade ∈ {A, B, C}",
            ],
            "evidence_ref": [],
            "notes": ["fallback_master_ai_failed"],
        }
        if has_active_thesis:
            return {
                **common,
                "status": "degraded_master_failed_keep_thesis",
                "mode": "evaluate_existing",
                "thesis_assessment": {
                    "still_valid": "mostly",
                    "which_break_triggered": None,
                    "reasoning": (
                        "master AI 失败,fallback 保守评估为 mostly_valid,"
                        "保留 thesis 不评估,挂单仍按计划触发,等下次重试"
                    ),
                    "stop_loss_adjustment": None,
                    "objective_evidence": ["master_ai_failed"],
                },
            }
        else:
            return {
                **common,
                "status": "degraded_master_failed_silent",
                "mode": "silent_cooldown",
                "silent_reason": "master AI 失败,fallback silent(等下次重试)",
            }

    @staticmethod
    def validate_mode(
        result: dict[str, Any], has_active_thesis: bool,
    ) -> tuple[bool, Optional[str]]:
        """D4=a 轻量验证:mode 字段存在 + 枚举合法 + 与 active_thesis 状态对齐。

        其他字段验证(direction / confidence_score 范围 / break_conditions ≥ 3 等)
        留 1.10-E Validator 24 条统一覆盖。

        Returns:
            (is_valid, error_message);is_valid=False 时调用方应触发 fallback。
        """
        if not isinstance(result, dict):
            return False, f"result not a dict: {type(result).__name__}"
        mode = result.get("mode")
        if mode not in VALID_MODES:
            return False, f"missing or invalid mode: {mode!r} (must be {VALID_MODES})"
        # active_thesis 与 mode 一致性(对应 Validator 6,本 sprint 只检测,真覆盖留 1.10-E)
        if has_active_thesis and mode == "new_thesis":
            return False, (
                "active_thesis exists but mode='new_thesis' "
                "(Validator 6 thesis_lock — 详细覆盖留 1.10-E)"
            )
        return True, None
