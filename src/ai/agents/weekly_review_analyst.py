"""src/ai/agents/weekly_review_analyst.py — Sprint 1.10-H 周复盘 AI(第 7 个 agent)。

对齐 docs/modeling.md b25cfe6(v1.4)§3.3.9 + §8.1:
- 触发:每周日 22:00 BJT 自动跑(scheduler.yaml::weekly_review)
- 输入:7 类聚合 dict(由 weekly_review_input_builder.build_weekly_review_input 给)
- 输出:4 段 JSON(performance_summary / system_health_diagnosis /
  strategy_quality / hard_constraint_activation_review / adjustment_recommendations)
- ~$0.15 / 次,token ~5000 input + ~3000 output

设计纪律:
- 继承 BaseAgent(prompt 加载 + 2-attempt 重试 + JSON 解析 + fallback 全继承)
- _fallback_output 返最小合法 4 段 JSON(空 review,系统不崩)
- normalize_output 校验 hard_constraint_activation_review 必须含 23 条 V
  (缺失自动补 0/0 days + evaluation="数据缺失")
"""
from __future__ import annotations

from typing import Any

from ._base import BaseAgent
from ..weekly_review_input_builder import VALIDATOR_KEYS


VALID_PRIORITIES = ("high", "medium", "low")
VALID_SEVERITIES = ("critical", "warning", "info")
VALID_THESIS_QUALITY = ("good", "acceptable", "poor")


class WeeklyReviewAnalyst(BaseAgent):
    """v1.4 §3.3.9 周复盘分析师。"""

    AGENT_NAME = "weekly_review_analyst"
    PROMPT_FILE = "weekly_review_analyst.txt"

    def _build_user_prompt(self, context: dict[str, Any]) -> str:
        """把 build_weekly_review_input 的输出装成 user prompt。

        context 是 build_weekly_review_input 返的 dict,直接 json 化给 AI。
        """
        import json

        window = context.get("window") or {}
        perf_raw = context.get("performance_summary_raw") or {}
        thesis_lc = context.get("thesis_lifecycle") or {}
        orders = context.get("virtual_orders_aggregate") or {}
        retry = context.get("retry_log_aggregate") or {}
        va = context.get("virtual_account_window") or {}
        fuse_states = context.get("fuse_and_states") or {}
        hc_raw = context.get("hard_constraint_activation_raw") or {}
        ctx_meta = context.get("context") or {}

        lines: list[str] = [
            f"# 周复盘窗口",
            f"  start_utc: {window.get('start_utc')}",
            f"  end_utc:   {window.get('end_utc')}",
            f"  days:      {window.get('days')}",
            "",
            f"# 1. 运行 + thesis 概览(performance_summary 7 字段)",
            json.dumps(perf_raw, ensure_ascii=False, indent=2),
            "",
            f"# 2. thesis 生命周期详情(创建/关闭列表)",
            json.dumps(thesis_lc, ensure_ascii=False, indent=2),
            "",
            f"# 3. virtual_orders 触发分布",
            json.dumps(orders, ensure_ascii=False, indent=2),
            "",
            f"# 4. retry_log 聚合(fallback / event_invalidation 计数)",
            json.dumps(retry, ensure_ascii=False, indent=2),
            "",
            f"# 5. virtual_account 窗口内 PnL + drawdown",
            json.dumps(va, ensure_ascii=False, indent=2),
            "",
            f"# 6. fuse_events + system_states(熔断 + review_pending 触发)",
            json.dumps(fuse_states, ensure_ascii=False, indent=2),
            "",
            f"# 7. hard_constraint_activation 23 V 激活率(原始数据)",
            json.dumps(hc_raw, ensure_ascii=False, indent=2),
            "",
            f"# 当前 virtual_account snapshot",
            json.dumps(
                ctx_meta.get("current_virtual_account") or {},
                ensure_ascii=False, indent=2,
            ),
            "",
            "# 输出要求",
            "请输出 4 段 JSON:performance_summary / system_health_diagnosis / "
            "strategy_quality / hard_constraint_activation_review / "
            "adjustment_recommendations。",
            "",
            "**hard_constraint_activation_review 必须列全 23 条 V Validator**,"
            "每条含 activations / rate / evaluation 三个字段。",
            "",
            "若数据全 0(冷启动):仍要输出 4 段 + 23 V dict,"
            "evaluation 写 '数据不足,无法评估'。",
        ]
        return "\n".join(lines)

    def _fallback_output(self) -> dict[str, Any]:
        """AI 失败时返最小合法 4 段 JSON(空 review,系统不崩)。"""
        v_review = {
            k: {"activations": 0, "rate": "0/0 days",
                 "evaluation": "AI 失败,无法评估"}
            for k in VALIDATOR_KEYS
        }
        return {
            "agent": self.AGENT_NAME,
            "status": "degraded",
            "performance_summary": {
                "total_runs": 0, "successful_runs": 0, "ai_failures": 0,
                "thesis_created": 0, "thesis_closed_profit": 0,
                "thesis_closed_loss": 0,
                "weekly_pnl_pct": 0.0, "max_drawdown_pct": 0.0,
            },
            "system_health_diagnosis": [
                {
                    "issue": "weekly_review_analyst AI 失败",
                    "evidence": "本次复盘 fallback,无 AI 输出",
                    "severity": "warning",
                    "suggested_action": "检查 AI 中转站延迟 / 等下周复盘重试",
                },
            ],
            "strategy_quality": {
                "thesis_quality": "acceptable",
                "break_conditions_calibration": "适中",
                "false_signals": [],
                "missed_opportunities": [],
            },
            "hard_constraint_activation_review": {
                **v_review,
                "position_cap_compressed_avg": None,
                "thesis_lock_blocks_count": 0,
                "channel_c_uses_count": 0,
                "review_pending_triggers": 0,
                "overall_evaluation": "AI 失败,无法评估硬约束健康度",
                "suggested_actions": ["人工查看 retry_log_json 排查 AI 失败原因"],
            },
            "adjustment_recommendations": [
                {
                    "目标": "恢复周复盘 AI 正常运行",
                    "建议": "检查 anthropic API key + 中转站状态",
                    "优先级": "high",
                    "影响": "周复盘缺失,无法发现硬约束阈值过严/过松问题",
                },
            ],
        }

    # ------------------------------------------------------------------
    # 输出校验:23 V 完整性 + critical_count 计算(D1=a 写 alerts 用)
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_output(out: dict[str, Any]) -> dict[str, Any]:
        """v1.4 §3.3.9 硬约束:hard_constraint_activation_review 必须含 23 条 V。

        若 AI 漏字段 → 自动补 {activations: 0, rate: '0/? days',
        evaluation: '数据缺失'},notes 标记。

        本 sprint 简化版;严校验(rate 字符串格式 / evaluation 长度 / priority 枚举)
        留 1.10-L。
        """
        if not isinstance(out, dict):
            return out  # caller 已 fallback
        hc = out.get("hard_constraint_activation_review")
        if not isinstance(hc, dict):
            return out  # 整段缺失,caller 走 _fallback_output 链路
        missing: list[str] = []
        for k in VALIDATOR_KEYS:
            if k not in hc:
                hc[k] = {
                    "activations": 0, "rate": "0/? days",
                    "evaluation": "AI 输出漏字段,自动补默认",
                }
                missing.append(k)
        if missing:
            notes = list(out.get("notes") or [])
            notes.append(
                f"hard_constraint_review_missing_{len(missing)}_V_normalized"
            )
            out["notes"] = notes
        return out

    @staticmethod
    def count_critical_recommendations(out: dict[str, Any]) -> int:
        """计 adjustment_recommendations.priority='high' 的条数(D1=a 写 alerts 用)。"""
        if not isinstance(out, dict):
            return 0
        recs = out.get("adjustment_recommendations") or []
        if not isinstance(recs, list):
            return 0
        return sum(
            1 for r in recs
            if isinstance(r, dict) and r.get("优先级") == "high"
        )
