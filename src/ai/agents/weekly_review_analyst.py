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

import re
from typing import Any

from ._base import BaseAgent
from ..weekly_review_input_builder import VALIDATOR_KEYS


VALID_PRIORITIES = ("high", "medium", "low")
VALID_SEVERITIES = ("critical", "warning", "info")
VALID_THESIS_QUALITY = ("good", "acceptable", "poor")
VALID_EVIDENCE_CONFIDENCE = ("low", "medium", "high")
VALID_OBSERVED_OUTCOMES = ("positive", "neutral", "negative", "unknown")
VALID_CONFIDENCE_ACCURACY = ("low", "medium", "high")
VALID_RECOMMENDATION_CATEGORIES = (
    "l3_behavior",
    "l4_risk",
    "master_trade_plan",
    "validator_output_quality",
    "weekly_review_observability",
    "data_quality",
    "system_health",
    "web_ui",
    "other",
)
VALID_RECOMMENDATION_ACTION_TYPES = (
    "observe",
    "audit",
    "improve_prompt",
    "improve_schema",
    "improve_ui",
    "improve_diagnostics",
    "change_threshold",
    "fix_bug",
    "other",
)


def _recommendation_text(rec: dict[str, Any]) -> str:
    text = " ".join(
        str(rec.get(k) or "")
        for k in ("目标", "具体调整路径", "建议", "suggested_action")
    ).lower()
    return "".join(ch for ch in text if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def _looks_observation_only(rec: dict[str, Any]) -> bool:
    text = (
        str(rec.get("具体调整路径") or "")
        + str(rec.get("建议") or "")
        + str(rec.get("suggested_action") or "")
    )
    return any(token in text for token in ("观察", "补诊断", "审计", "不在本周做"))


def _snake_case(value: Any) -> str:
    text = str(value or "").lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def _recommendation_blob(rec: dict[str, Any]) -> str:
    return " ".join(
        str(rec.get(k) or "")
        for k in (
            "recommendation_id",
            "normalized_recommendation_id",
            "recommendation_category",
            "recommendation_target",
            "recommendation_action_type",
            "目标",
            "具体调整路径",
            "建议",
            "suggested_action",
        )
    ).lower()


def _infer_recommendation_category(rec: dict[str, Any]) -> str:
    raw = str(rec.get("recommendation_category") or rec.get("category") or "").lower()
    if raw in VALID_RECOMMENDATION_CATEGORIES:
        return raw
    blob = _recommendation_blob(rec)
    if "l3" in blob or "extending_late_phase" in blob or "反模式" in blob:
        return "l3_behavior"
    if "l4" in blob or "elevated" in blob or "risk_tier" in blob:
        return "l4_risk"
    if "master" in blob or "entry_zone" in blob or "stop_loss" in blob:
        return "master_trade_plan"
    if "validator" in blob or "v16" in blob or "v23" in blob or "change_mind" in blob:
        return "validator_output_quality"
    if "weekly_review" in blob or "周复盘" in blob or "diagnostics" in blob:
        return "weekly_review_observability"
    if "data" in blob or "数据" in blob or "fetch" in blob:
        return "data_quality"
    if "ai 失败" in blob or "fallback" in blob or "系统" in blob:
        return "system_health"
    if "web" in blob or "网页" in blob or "ui" in blob:
        return "web_ui"
    return "other"


def _infer_recommendation_action_type(rec: dict[str, Any]) -> str:
    raw = str(
        rec.get("recommendation_action_type") or rec.get("action_type") or "",
    ).lower()
    if raw in VALID_RECOMMENDATION_ACTION_TYPES:
        return raw
    blob = _recommendation_blob(rec)
    if "观察" in blob or "observe" in blob:
        return "observe"
    if "审计" in blob or "audit" in blob:
        return "audit"
    if "schema" in blob or "结构化" in blob:
        return "improve_schema"
    if "ui" in blob or "网页" in blob or "展示" in blob:
        return "improve_ui"
    if "diagnostic" in blob or "诊断" in blob:
        return "improve_diagnostics"
    if "prompt" in blob:
        return "improve_prompt"
    if "阈值" in blob or "threshold" in blob:
        return "change_threshold"
    if "修复" in blob or "fix" in blob or "bug" in blob:
        return "fix_bug"
    return "other"


def _infer_recommendation_target(rec: dict[str, Any], category: str) -> str:
    raw = rec.get("recommendation_target") or rec.get("target")
    if raw:
        return _snake_case(raw)
    blob = _recommendation_blob(rec)
    if "extending_late_phase" in blob:
        return "l3_extending_late_phase"
    if "risk_breakdown" in blob and ("elevated" in blob or "l4" in blob):
        return "l4_elevated_risk_breakdown"
    if "elevated" in blob or "risk_tier" in blob:
        return "l4_elevated"
    if "v16" in blob or "validator_16" in blob or "change_mind" in blob:
        return "v16_change_mind_structure"
    if "v23" in blob or "validator_23" in blob or "conflict_missing" in blob:
        return "v23_conflict_resolution"
    if "conflict_resolution" in blob:
        return "master_conflict_resolution_schema"
    if "evidence" in blob and "diagnostic" in blob:
        return "weekly_review_evidence_diagnostics"
    if "ai" in blob and ("失败" in blob or "fallback" in blob):
        return "weekly_review_ai_failure"
    title = _snake_case(rec.get("目标") or "")
    if title:
        return title[:80].strip("_")
    return category


def _build_stable_recommendation_id(rec: dict[str, Any]) -> str:
    category = _infer_recommendation_category(rec)
    action_type = _infer_recommendation_action_type(rec)
    if _looks_observation_only(rec) and action_type == "change_threshold":
        action_type = "audit"
    target = _infer_recommendation_target(rec, category)
    prefix = {
        "observe": "observe",
        "audit": "audit",
        "improve_prompt": "improve",
        "improve_schema": "improve",
        "improve_ui": "improve",
        "improve_diagnostics": "improve",
        "change_threshold": "change",
        "fix_bug": "fix",
        "other": "review",
    }.get(action_type, "review")
    return _snake_case(f"{prefix}_{target}") or "review_other"


def _is_unstable_recommendation_id(value: Any) -> bool:
    rid = str(value or "")
    if not rid:
        return False
    lowered = rid.lower()
    patterns = (
        r"20\d{2}[_-]?\d{2}[_-]?\d{2}",
        r"\d+(_pct|pct|%)",
        r"run[_-]?[a-z0-9]+",
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        r"[0-9a-f]{16,}",
        r"[a-z0-9]{24,}",
    )
    return any(re.search(p, lowered) for p in patterns)


def _normalize_outcome_tracking(rec: dict[str, Any]) -> dict[str, Any]:
    raw = rec.get("outcome_tracking")
    if not isinstance(raw, dict):
        raw = {}
    implemented_raw = raw.get("implemented", rec.get("implemented"))
    implemented = implemented_raw if isinstance(implemented_raw, bool) else False
    observed = str(
        raw.get("observed_outcome")
        or rec.get("observed_outcome")
        or "unknown",
    ).lower()
    if observed not in VALID_OBSERVED_OUTCOMES:
        observed = "unknown"
    accuracy = str(
        raw.get("confidence_accuracy")
        or rec.get("confidence_accuracy")
        or "low",
    ).lower()
    if accuracy not in VALID_CONFIDENCE_ACCURACY:
        accuracy = "low"
    return {
        "recommendation_id": (
            rec.get("normalized_recommendation_id")
            or rec.get("recommendation_id")
            or ""
        ),
        "implemented": implemented,
        "observed_outcome": observed,
        "confidence_accuracy": accuracy,
        "evaluation_notes": str(
            raw.get("evaluation_notes")
            or rec.get("evaluation_notes")
            or "",
        ),
        "week_of_outcome": str(
            raw.get("week_of_outcome")
            or rec.get("week_of_outcome")
            or "",
        ),
    }


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
        l3_diag = context.get("l3_diagnostics") or {}
        l4_diag = context.get("l4_diagnostics") or {}
        validator_diag = context.get("validator_diagnostics") or {}
        temporal_diag = context.get("temporal_consistency_diagnostics") or {}

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
            "# 13. L3 诊断证据(只读,不改 L3 schema)",
            "用于解释 L3 异常的原因:先看 phase_distribution,再看 "
            "anti_pattern_signal_distribution 与 anti_pattern_by_grade。"
            "若 diagnostics 为空,必须写“证据不足,建议补诊断”,不能直接调 L3 prompt。",
            json.dumps(l3_diag, ensure_ascii=False, indent=2, default=str),
            "",
            "# 14. L4 诊断证据(只读,不改 L4 schema/阈值)",
            "用于解释 L4 elevated:先看 risk_score_summary / risk_breakdown_top_reasons "
            "/ position_cap_multiplier_summary,不能单凭 elevated 比例建议放宽 L4。",
            "若 diagnostics 为空,必须写“证据不足,建议补诊断”。",
            json.dumps(l4_diag, ensure_ascii=False, indent=2, default=str),
            "",
            "# 15. Validator 诊断证据(只读,不改 Validator 判定)",
            "用于解释 V16/V23:先判断是输出字段缺失、Validator 文案误报,"
            "还是 Master 结构化不足;不能直接修改 Validator 交易约束。",
            "若 diagnostics 为空,必须写“证据不足,建议补诊断”。",
            json.dumps(validator_diag, ensure_ascii=False, indent=2, default=str),
            "",
            "# 16. 时间连续性诊断(只读,用于区分单周异常 vs 连续系统性异常)",
            "用于判断异常是否连续出现:单周异常默认 low confidence;连续 2-3 周 "
            "可 medium;长期持续且 L3/L4/Validator diagnostics 支撑才可 high。",
            "如果 temporal_consistency_diagnostics 为空,所有调参建议只能 low confidence。",
            "观察/审计/补诊断建议不是参数调整建议,证据置信度不应 high。",
            json.dumps(temporal_diag, ensure_ascii=False, indent=2, default=str),
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
            "同时在顶层输出 l3_diagnostics / l4_diagnostics / "
            "validator_diagnostics / temporal_consistency_diagnostics,"
            "原样转述第 13-16 段字段,供网页展示。",
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
            "默认不得 high/critical 调参,也不得给 high evidence_confidence。",
            "- 对 L3 extending_late_phase,先解释是 phase 分布导致,"
            "还是 anti_pattern 组合导致;不允许单凭比例建议改 L3 prompt。",
            "- 对 L4 elevated,先解释 risk_score / risk_breakdown / "
            "position_cap_multiplier;不允许单凭 elevated 比例建议放宽 L4。",
            "- 对 V16/V23,先解释是输出字段缺失、Validator 文案误报,"
            "还是 Master 结构化不足;不允许直接修改 Validator 交易约束。",
            "- 不要因为单周比例异常就建议调整 L3/L4/Master prompt;连续异常"
            "才说明可能存在系统性问题。",
            "- 若建议放宽 late phase / 放宽 elevated / 修改 Validator,必须引用"
            "temporal + diagnostics 双重证据。",
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
            "4. adjustment_recommendations 每条必须含 evidence_confidence "
            "(low / medium / high) 和 confidence_reason:",
            "   - 单周异常 → low",
            "   - 2-3 周重复 → medium",
            "   - 长期持续 + diagnostics 支撑 → high",
            "   - thesis_created <= 1、total_trades/orders_filled = 0、"
            "diagnostics 缺失、或只是观察建议时,不得 high confidence。",
            "   - high priority 不等于 high evidence_confidence。",
            "5. adjustment_recommendations 每条必须含 canonical 字段:",
            "   - recommendation_id:跨周稳定 snake_case ID,不得含日期/百分比/run_id/"
            "随机字符串。",
            "   - recommendation_category:l3_behavior / l4_risk / "
            "master_trade_plan / validator_output_quality / "
            "weekly_review_observability / data_quality / system_health / "
            "web_ui / other。",
            "   - recommendation_target:稳定对象,如 l3_extending_late_phase。",
            "   - recommendation_action_type:observe / audit / improve_prompt / "
            "improve_schema / improve_ui / improve_diagnostics / "
            "change_threshold / fix_bug / other。",
            "   - observe/audit 类建议不要伪装成 change_threshold;证据不足时"
            "action_type 应为 observe 或 audit。",
            "6. adjustment_recommendations 每条必须含 outcome_tracking:",
            "   - implemented:boolean,只记录是否已人工实施,不得自动应用建议。",
            "   - observed_outcome:positive / neutral / negative / unknown。",
            "   - confidence_accuracy:low / medium / high,用于长期校准"
            " evidence_confidence 是否靠谱。",
            "   - evaluation_notes:简短说明证据。",
            "   - week_of_outcome:ISO week;没有可评估结果时留空字符串。",
            "   - outcome 只能支持复盘可信度,不能触发交易参数自动变更。",
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
            "l3_diagnostics": {
                "phase_distribution": {},
                "anti_pattern_signal_distribution": {},
                "opportunity_grade_distribution": {},
                "execution_permission_distribution": {},
                "anti_pattern_by_grade": {},
                "extending_late_phase_samples": [],
            },
            "l4_diagnostics": {
                "risk_tier_distribution": {},
                "risk_score_summary": {"count": 0, "min": None, "max": None, "avg": None},
                "position_cap_multiplier_summary": {
                    "count": 0, "min": None, "max": None, "avg": None,
                },
                "risk_breakdown_top_reasons": [],
                "elevated_samples": [],
            },
            "validator_diagnostics": {
                "top_triggered_validators": [],
                "v16_samples": [],
                "v23_samples": [],
                "validator_sample_base": {
                    "total_strategy_runs": 0,
                    "valid_constraint_runs": 0,
                    "missing_constraint_runs": 0,
                },
            },
            "temporal_consistency_diagnostics": {
                "l3_extending_late_phase_trend": [],
                "l4_elevated_trend": [],
                "validator_v16_trend": [],
                "validator_v23_trend": [],
                "thesis_creation_trend": [],
                "trade_execution_trend": [],
                "recommendation_recurrence": [],
                "anomaly_streaks": {},
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
                    "recommendation_id": "fix_weekly_review_ai_failure",
                    "normalized_recommendation_id": "fix_weekly_review_ai_failure",
                    "recommendation_category": "system_health",
                    "recommendation_target": "weekly_review_ai_failure",
                    "recommendation_action_type": "fix_bug",
                    "evidence_confidence": "low",
                    "confidence_reason": "fallback 输出,没有时间连续性诊断证据",
                    "outcome_tracking": {
                        "recommendation_id": "fix_weekly_review_ai_failure",
                        "implemented": False,
                        "observed_outcome": "unknown",
                        "confidence_accuracy": "low",
                        "evaluation_notes": "fallback 输出,尚无实施记录和后续效果",
                        "week_of_outcome": "",
                    },
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
        out.setdefault("l3_diagnostics", {})
        out.setdefault("l4_diagnostics", {})
        out.setdefault("validator_diagnostics", {})
        out.setdefault("temporal_consistency_diagnostics", {})
        sq = out.get("strategy_quality")
        if isinstance(sq, dict) and "ai_vs_actual_comparison" not in sq:
            sq["ai_vs_actual_comparison"] = []

        recs = out.get("adjustment_recommendations")
        if isinstance(recs, list):
            temporal = out.get("temporal_consistency_diagnostics") or {}
            recurrence = (
                temporal.get("recommendation_recurrence")
                if isinstance(temporal, dict) else []
            ) or []
            recurrent_texts = {
                _recommendation_text({
                    "目标": item.get("target") or item.get("目标") or "",
                    "具体调整路径": item.get("action") or item.get("具体调整路径") or "",
                })
                for item in recurrence
                if isinstance(item, dict) and item.get("weeks_seen", 0) >= 2
            }
            recurrent_ids = {
                str(item.get("recommendation_id") or "").strip()
                for item in recurrence
                if isinstance(item, dict) and item.get("weeks_seen", 0) >= 2
            }
            id_counts: dict[str, int] = {}
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
                existing_id = (
                    r.get("recommendation_id")
                    or r.get("id")
                    or r.get("canonical_id")
                    or r.get("issue_id")
                )
                stable_id = _build_stable_recommendation_id(r)
                if existing_id:
                    r["recommendation_id"] = _snake_case(existing_id) or stable_id
                    if _is_unstable_recommendation_id(existing_id):
                        r["unstable_recommendation_id"] = True
                        r["normalized_recommendation_id"] = stable_id
                    else:
                        r["normalized_recommendation_id"] = r["recommendation_id"]
                else:
                    r["recommendation_id"] = stable_id
                    r["normalized_recommendation_id"] = stable_id
                category = _infer_recommendation_category(r)
                action_type = _infer_recommendation_action_type(r)
                if _looks_observation_only(r) and action_type == "change_threshold":
                    action_type = "audit"
                target = _infer_recommendation_target(r, category)
                r["recommendation_category"] = category
                r["recommendation_action_type"] = action_type
                r["recommendation_target"] = target
                normalized_id = r["normalized_recommendation_id"]
                id_counts[normalized_id] = id_counts.get(normalized_id, 0) + 1
                confidence = (
                    r.get("evidence_confidence")
                    or r.get("confidence")
                    or r.get("confidence_level")
                    or "low"
                )
                confidence = str(confidence).lower()
                if confidence not in VALID_EVIDENCE_CONFIDENCE:
                    confidence = "low"
                if confidence == "high" and _looks_observation_only(r):
                    confidence = "medium"
                r["evidence_confidence"] = confidence
                if not r.get("confidence_reason"):
                    r["confidence_reason"] = (
                        "AI 未提供置信度原因,normalize 默认按低证据处理"
                        if confidence == "low"
                        else "AI 未提供置信度原因,请结合时间连续性诊断人工复核"
                    )
                rec_text = _recommendation_text(r)
                repeated = any(
                    old and (
                        old in rec_text
                        or rec_text in old
                        or old == _recommendation_text({
                            "目标": r.get("目标") or "",
                            "具体调整路径": r.get("具体调整路径") or "",
                        })
                    )
                    for old in recurrent_texts
                ) or normalized_id in recurrent_ids
                if confidence == "low" and repeated:
                    r["possible_repetition_without_confirmation"] = True
                r["outcome_tracking"] = _normalize_outcome_tracking(r)
            for r in recs:
                if not isinstance(r, dict):
                    continue
                normalized_id = r.get("normalized_recommendation_id")
                if normalized_id and id_counts.get(normalized_id, 0) > 1:
                    r["duplicate_recommendation_id"] = True

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
                rate = hc[k].get("rate")
                if isinstance(rate, str):
                    bad_suffix = "/valid_runs " + "valid_runs"
                    hc[k]["rate"] = rate.replace(bad_suffix, "/0 valid_runs")
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
