"""src/ai/agents/weekly_review_analyst.py — Sprint 1.10-H 周复盘 AI(第 7 个 agent)。

对齐 docs/modeling.md b25cfe6(v1.4)§3.3.9 + §8.1:
- 触发:每周日 22:00 BJT 自动跑(scheduler.yaml::weekly_review)
- 输入:7 类聚合 dict(由 weekly_review_input_builder.build_weekly_review_input 给)
- 输出:5 段 JSON(performance_summary / system_health_diagnosis /
  strategy_quality / hard_constraint_activation_review / adjustment_recommendations)
- ~$0.15 / 次,token ~5000 input + ~3000 output

设计纪律:
- 继承 BaseAgent(prompt 加载 + 2-attempt 重试 + JSON 解析 + fallback 全继承)
- _fallback_output 返最小合法 5 段 JSON(空 review,系统不崩)
- normalize_output 校验 hard_constraint_activation_review 必须含 23 条 V
  (缺失自动补 0/0 valid_runs + evaluation="数据缺失")
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
        sample_base = context.get("sample_base") or hc_raw.get("sample_base") or {}
        # Sprint H Part B 新加 5 个字段
        anti_pat = context.get("anti_pattern_signals") or {}
        l3_dist = context.get("l3_grade_distribution") or {}
        l4_dist = context.get("l4_risk_tier_distribution") or {}
        price_action = context.get("weekly_price_action") or {}
        master_runs = context.get("master_runs_with_trade_plan") or []

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
            "rate 分母是 valid_runs(有效 Validator 决策样本),不是 days。",
            json.dumps(hc_raw, ensure_ascii=False, indent=2),
            "",
            "# 7a. 样本口径(sample_base)",
            json.dumps(sample_base, ensure_ascii=False, indent=2),
            "",
            "# 8. 反模式触发率(Sprint H Part B 新加)",
            "L3 anti_pattern_signals 5 类(extending_late_phase / against_long_cycle "
            "/ chasing_breakout_no_pullback / failing_at_resistance / "
            "after_extreme_event_no_reset)在过去 7 天的触发次数 + 占比。",
            "单周某条触发率 > 40% 时,默认只能给 warning 级别的审计/观察/"
            "补诊断建议;只有连续多周异常,或 ai_vs_actual_comparison 证明"
            "错过大量真实机会时,才建议具体改 L3 阈值。",
            json.dumps(anti_pat, ensure_ascii=False, indent=2),
            "",
            "# 9. L3 opportunity_grade 分布(Sprint H Part B 新加)",
            "用于评估 L3 prompt §四 4 档定义是否合理:期望分布(中长线策略):"
            "A 1-2/年、B 1-2/月、C 3-4/月、none 其余。"
            "若实际 B + C 周率 > 5 → L3 prompt §四 'B/C 级' 定义可能偏松。",
            json.dumps(l3_dist, ensure_ascii=False, indent=2),
            "",
            "# 10. L4 risk_tier 分布(Sprint H Part B 新加)",
            "用于评估 L4 prompt §四 4 档定义是否合理:期望分布(健康市场):"
            "low + moderate 占多数,elevated < 30%,extreme 罕见。"
            "单周 elevated > 50% 不得直接建议降低阈值;必须先结合"
            "risk_score / risk_breakdown / position_cap_multiplier / 实际走势。"
            "如果输入缺 risk_breakdown,建议补诊断,不要直接改 L4 prompt。",
            json.dumps(l4_dist, ensure_ascii=False, indent=2),
            "",
            "# 11. BTC 实际走势(Sprint H Part B 新加,price_candles 1d)",
            "用于第 12 段 master 决策对比;不要因为系统判断 long 而 BTC 涨就"
            "事后赞美,也不要因为判断 long 而 BTC 跌就事后批判 — 中长线 1 周"
            "样本不足以评估方向准确度,主要看关键位(止损/止盈)是否合理。",
            json.dumps(price_action, ensure_ascii=False, indent=2),
            "",
            "# 12. master 真跑通且给 trade_plan 的 run 列表(Sprint H Part B 新加)",
            "对比 AI 当时给的 entry_zone / stop_loss / take_profit_zones vs "
            "后续实际走势(用第 11 段 daily K 线)。",
            "格式化输出每个 master run 的「方向 ✓/✗ + 关键位 ✓/✗」对比,"
            "存入 strategy_quality.ai_vs_actual_comparison 子段。",
            "**中立性纪律**:中长线 1 周样本不足以判定 AI 准确度,"
            "评估只针对关键位(止损/止盈/入场区)合理性,不下\"AI 准/错\"结论。",
            json.dumps(master_runs, ensure_ascii=False, indent=2, default=str),
            "",
            f"# 当前 virtual_account snapshot",
            json.dumps(
                ctx_meta.get("current_virtual_account") or {},
                ensure_ascii=False, indent=2,
            ),
            "",
            "# 输出要求",
            "请输出 5 段 JSON:performance_summary / system_health_diagnosis / "
            "strategy_quality / hard_constraint_activation_review / "
            "adjustment_recommendations。",
            "同时在顶层输出 sample_base,原样转述第 7a 段字段。",
            "",
            "**hard_constraint_activation_review 必须列全 23 条 V Validator**,"
            "每条含 activations / rate / evaluation 三个字段。",
            "",
            "**severity 与 priority 分离**:",
            "- severity=critical 只用于系统级故障、DB/订单/止损/失效位异常、"
            "Validator 安全层失效、连续多周严重异常。",
            "- severity=warning 用于单周策略分布异常、L3/L4 分布明显偏移、"
            "V16/V23 偏高等需要审计的问题。",
            "- severity=info 用于冷启动、0 成交、样本不足、正常观察项。",
            "- 优先级 high 只表示先处理,不等于 critical,不会自动触发 critical 告警。",
            "",
            "**归因纪律**:",
            "- entry_zone / stop_loss / take_profit 属于 Master trade_plan / "
            "thesis lifecycle,不要归因给 L3。",
            "- L3 只负责 opportunity_grade / execution_permission / anti_pattern。",
            "- 本周 0 成交或只有 1 个 thesis 属于样本不足/早期观察,"
            "默认不得 high/critical 调参。",
            "",
            "**Sprint H Part B 新增约束**:",
            "1. strategy_quality 必须含 ai_vs_actual_comparison 子段 — 若本周",
            "   有 master_runs_with_trade_plan 数据,**逐条**对比方向 ✓/✗ + 关键位",
            "   ✓/✗ + 中立评估;无数据则 ai_vs_actual_comparison: []。",
            "2. adjustment_recommendations 每条必须含「具体调整路径」字段:",
            "   - 阈值改动:'<文件>:<行号> 的 X 阈值从 Y 改为 Z' 格式",
            "   - 或观察期:'建议先观察 N 周后调整,理由 ...' 格式",
            "   - 不许给 '降低 AI 失败率' 这种空泛建议(必须指明改哪个文件 / 哪个",
            "     阈值 / 改成多少;若数据不足无法决定具体值,优先级 low + 写明",
            "     '建议先观察 N 周')",
            "3. adjustment_recommendations 每条建议可含 severity 或 严重级别,"
            "但 high priority 不自动等于 critical severity。",
            "",
            "若数据全 0(冷启动):仍要输出 5 段 + 23 V dict,"
            "evaluation 写 '数据不足,无法评估';adjustment_recommendations 至少",
            "1 条 'low' 优先级 '建议先观察 N 周再评估'。",
        ]
        return "\n".join(lines)

    def _fallback_output(self) -> dict[str, Any]:
        """AI 失败时返最小合法 5 段 JSON(空 review,系统不崩)。"""
        v_review = {
            k: {"activations": 0, "rate": "0/0 valid_runs",
                 "evaluation": "AI 失败,无法评估"}
            for k in VALIDATOR_KEYS
        }
        return {
            "agent": self.AGENT_NAME,
            "status": "degraded",
            "sample_base": {
                "total_strategy_runs": 0,
                "valid_constraint_runs": 0,
                "missing_constraint_runs": 0,
                "window_days": 7,
            },
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
                "ai_vs_actual_comparison": [],
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
                    "具体调整路径": "检查 <env: OPENAI_API_KEY> / 中转站可用性;仅修复复盘 AI 运行,不改交易参数",
                    "建议": "检查 anthropic API key + 中转站状态",
                    "优先级": "high",
                    "severity": "warning",
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

        若 AI 漏字段 → 自动补 {activations: 0, rate: '0/0 valid_runs',
        evaluation: '数据缺失'},notes 标记。

        本 sprint 简化版;严校验(rate 字符串格式 / evaluation 长度 / priority 枚举)
        留 1.10-L。
        """
        if not isinstance(out, dict):
            return out  # caller 已 fallback
        sq = out.get("strategy_quality")
        if isinstance(sq, dict) and "ai_vs_actual_comparison" not in sq:
            sq["ai_vs_actual_comparison"] = []

        recs = out.get("adjustment_recommendations")
        if isinstance(recs, list):
            for r in recs:
                if not isinstance(r, dict):
                    continue
                if not r.get("具体调整路径"):
                    fallback_action = r.get("建议") or r.get("suggested_action") or ""
                    if fallback_action:
                        r["具体调整路径"] = fallback_action
                if "severity" not in r and "严重级别" not in r:
                    r["severity"] = (
                        "warning" if r.get("优先级") == "high" else "info"
                    )

        hc = out.get("hard_constraint_activation_review")
        if not isinstance(hc, dict):
            return out  # 整段缺失,caller 走 _fallback_output 链路
        missing: list[str] = []
        for k in VALIDATOR_KEYS:
            if k not in hc:
                hc[k] = {
                    "activations": 0, "rate": "0/0 valid_runs",
                    "evaluation": "AI 输出漏字段,自动补默认",
                }
                missing.append(k)
            elif isinstance(hc.get(k), dict):
                rate = hc[k].get("rate")
                if isinstance(rate, str) and "days" in rate:
                    hc[k]["rate"] = rate.replace(" days", " valid_runs")
        if missing:
            notes = list(out.get("notes") or [])
            notes.append(
                f"hard_constraint_review_missing_{len(missing)}_V_normalized"
            )
            out["notes"] = notes
        return out

    @staticmethod
    def count_critical_recommendations(out: dict[str, Any]) -> int:
        """计真正 critical severity 条数(D1=a 写 alerts 用)。

        注意:优先级 high 表示优先处理,不等于 critical 告警。
        """
        if not isinstance(out, dict):
            return 0
        count = 0
        diagnosis = out.get("system_health_diagnosis") or []
        if isinstance(diagnosis, list):
            count += sum(
                1 for d in diagnosis
                if isinstance(d, dict)
                and str(d.get("severity") or d.get("严重级别") or "").lower()
                == "critical"
            )
        recs = out.get("adjustment_recommendations") or []
        if not isinstance(recs, list):
            return count
        count += sum(
            1 for r in recs
            if isinstance(r, dict)
            and str(r.get("severity") or r.get("严重级别") or "").lower()
            == "critical"
        )
        return count

    @staticmethod
    def count_high_priority_recommendations(out: dict[str, Any]) -> int:
        """计 high priority 建议条数,仅用于文案展示,不作为 critical 告警。"""
        if not isinstance(out, dict):
            return 0
        recs = out.get("adjustment_recommendations") or []
        if not isinstance(recs, list):
            return 0
        return sum(
            1 for r in recs
            if isinstance(r, dict) and r.get("优先级") == "high"
        )
