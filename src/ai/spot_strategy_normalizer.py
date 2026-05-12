"""Layer A spot cycle strategy normalize helpers.

Layer A is a separate long-cycle spot-only strategy track.  It never creates
theses, never emits Layer B grades, and never participates in the virtual
account.
"""

from __future__ import annotations

import json
import re
from typing import Any


SPOT_ACTIONS = ("dca_buy", "aggressive_buy", "hold", "scale_out", "aggressive_sell")
CYCLE_STAGES = (
    "bear_bottom", "accumulation", "early_bull", "mid_bull", "late_bull",
    "distribution", "bear_transition", "deep_bear", "unclear",
)
CONFIDENCE_LEVELS = ("low", "medium", "high")
ONCHAIN_MACRO_STANCES = (
    "strongly_bullish", "bullish", "neutral", "cautious", "bearish", "unclear",
)
SPOT_RISK_LEVELS = ("low", "moderate", "elevated", "high", "critical")


def _as_dict(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _as_list(v: Any) -> list[Any]:
    if isinstance(v, list):
        return v
    if v in (None, ""):
        return []
    return [v]


def _as_str(v: Any, default: str = "") -> str:
    return str(v).strip() if v not in (None, "") else default


def _enum(v: Any, allowed: tuple[str, ...], default: str) -> str:
    s = str(v or "").strip().lower()
    return s if s in allowed else default


def _blob(v: Any) -> str:
    try:
        return json.dumps(v, ensure_ascii=False, default=str)
    except Exception:
        return str(v)


def _is_negated_boundary_statement(text: str, start: int) -> bool:
    prefix = text[max(0, start - 18):start].lower()
    return any(
        neg in prefix
        for neg in (
            "不", "不要", "不得", "不能", "不允许", "禁止", "避免",
            "no ", "not ", "never ", "do not ", "don't ", "cannot ",
            "does not ", "is not ", "should not ", "must not ",
        )
    )


def _contains_forbidden_text(v: Any) -> bool:
    text = _blob(v)
    patterns = (
        re.compile(r"\btrend_short\b", re.I),
        re.compile(r"\bhedge[_\s-]*short\b", re.I),
        re.compile(r"\b(open|go|enter|take|recommend|suggest|建议|执行)\s+(a\s+)?short\b", re.I),
        re.compile(r"(建议|执行|考虑|可以|应该|尝试)?\s*(开空|做空|空单)"),
        re.compile(r"(创建|新建|生成|开启)\s*thesis", re.I),
        re.compile(r"(设置|给出|生成|输出|使用)\s*(entry|entry_zone|entry_orders|stop_loss|take_profit|position_size|leverage)", re.I),
        re.compile(r"(使用|输出|采用)\s*(A/B/C|a/b/c|NONE)\s*(机会等级|grade|评级)?", re.I),
        re.compile(r"\b(opportunity_grade|execution_permission)\b", re.I),
    )
    for pattern in patterns:
        for match in pattern.finditer(text):
            if not _is_negated_boundary_statement(text, match.start()):
                return True
    return False


def fallback_layer_a_output(reason: str = "Layer A AI 输出失败或证据不足") -> dict[str, Any]:
    return normalize_layer_a_output(
        {
            "enabled": True,
            "a1_cycle_stage": {
                "cycle_stage": "unclear",
                "confidence": "low",
                "headline": "暂无大周期阶段判断",
                "human_summary": reason,
                "data_quality_notes": [reason],
            },
            "a2_onchain_macro": {
                "onchain_macro_stance": "unclear",
                "confidence": "low",
                "human_summary": reason,
                "data_quality_notes": [reason],
            },
            "a3_spot_opportunity": {
                "preferred_action_candidate": "hold",
                "confidence": "low",
                "human_summary": reason,
                "suggested_plan": ["暂不根据 Layer A 做现货动作"],
                "do_not_do": ["不要把本次 fallback 当成买卖信号"],
                "data_quality_notes": [reason],
            },
            "a4_spot_risk": {
                "spot_risk_level": "elevated",
                "confidence": "low",
                "human_summary": reason,
                "data_quality_notes": [reason],
            },
            "a5_spot_adjudicator": {
                "spot_action": "hold",
                "cycle_stage": "unclear",
                "confidence": "low",
                "headline": "暂无大周期策略",
                "human_summary": reason,
                "suggested_plan": ["保持观察，等待下一次有效 Layer A 输出"],
                "do_not_do": ["不要自动买入、卖出或影响 Layer B"],
                "what_would_change_mind": ["恢复有效数据和 AI 输出"],
                "next_review_focus": ["检查 Layer A 输入数据质量"],
                "data_quality_notes": [reason],
            },
            "model_notes": [reason],
        }
    )


def normalize_a1(raw: Any, warnings: list[str]) -> dict[str, Any]:
    d = _as_dict(raw)
    stage = _enum(d.get("cycle_stage"), CYCLE_STAGES, "unclear")
    if d.get("cycle_stage") and stage == "unclear" and d.get("cycle_stage") != "unclear":
        warnings.append("a1_invalid_cycle_stage_normalized_to_unclear")
    return {
        "cycle_stage": stage,
        "confidence": _enum(d.get("confidence"), CONFIDENCE_LEVELS, "low"),
        "headline": _as_str(d.get("headline"), "大周期阶段不明确"),
        "human_summary": _as_str(d.get("human_summary"), "证据不足，暂不做阶段定性。"),
        "bullish_evidence": _as_list(d.get("bullish_evidence")),
        "bearish_evidence": _as_list(d.get("bearish_evidence")),
        "conflicting_evidence": _as_list(d.get("conflicting_evidence")),
        "data_quality_notes": _as_list(d.get("data_quality_notes")),
    }


def normalize_a2(raw: Any) -> dict[str, Any]:
    d = _as_dict(raw)
    return {
        "onchain_macro_stance": _enum(
            d.get("onchain_macro_stance"), ONCHAIN_MACRO_STANCES, "unclear",
        ),
        "confidence": _enum(d.get("confidence"), CONFIDENCE_LEVELS, "low"),
        "valuation_reading": _as_str(d.get("valuation_reading")),
        "holder_behavior": _as_str(d.get("holder_behavior")),
        "macro_reading": _as_str(d.get("macro_reading")),
        "liquidity_reading": _as_str(d.get("liquidity_reading")),
        "human_summary": _as_str(d.get("human_summary"), "链上和宏观证据不足。"),
        "supporting_evidence": _as_list(d.get("supporting_evidence")),
        "opposing_evidence": _as_list(d.get("opposing_evidence")),
        "data_quality_notes": _as_list(d.get("data_quality_notes")),
    }


def normalize_a3(raw: Any, violations: list[str]) -> dict[str, Any]:
    d = _as_dict(raw)
    action = _enum(d.get("preferred_action_candidate"), SPOT_ACTIONS, "hold")
    if d.get("preferred_action_candidate") and action == "hold" and d.get("preferred_action_candidate") != "hold":
        violations.append("a3_invalid_preferred_action_candidate_normalized_to_hold")
    why = d.get("why_not_other_actions")
    return {
        "preferred_action_candidate": action,
        "confidence": _enum(d.get("confidence"), CONFIDENCE_LEVELS, "low"),
        "human_summary": _as_str(d.get("human_summary"), "现货策略机会证据不足。"),
        "buy_logic": _as_str(d.get("buy_logic")),
        "sell_logic": _as_str(d.get("sell_logic")),
        "why_not_other_actions": why if isinstance(why, dict) else {},
        "suggested_plan": _as_list(d.get("suggested_plan")),
        "do_not_do": _as_list(d.get("do_not_do")),
        "data_quality_notes": _as_list(d.get("data_quality_notes")),
    }


def normalize_a4(raw: Any) -> dict[str, Any]:
    d = _as_dict(raw)
    return {
        "spot_risk_level": _enum(d.get("spot_risk_level"), SPOT_RISK_LEVELS, "elevated"),
        "confidence": _enum(d.get("confidence"), CONFIDENCE_LEVELS, "low"),
        "human_summary": _as_str(d.get("human_summary"), "现货风险证据不足。"),
        "main_risks": _as_list(d.get("main_risks")),
        "risk_controls": _as_list(d.get("risk_controls")),
        "overheat_signals": _as_list(d.get("overheat_signals")),
        "downside_risks": _as_list(d.get("downside_risks")),
        "invalidation_watch": _as_list(d.get("invalidation_watch")),
        "data_quality_notes": _as_list(d.get("data_quality_notes")),
    }


def normalize_a5(raw: Any, violations: list[str], warnings: list[str]) -> dict[str, Any]:
    d = _as_dict(raw)
    action_raw = d.get("spot_action")
    action = _enum(action_raw, SPOT_ACTIONS, "hold")
    if action_raw and action == "hold" and action_raw != "hold":
        violations.append("a5_invalid_spot_action_normalized_to_hold")
    stage_raw = d.get("cycle_stage")
    stage = _enum(stage_raw, CYCLE_STAGES, "unclear")
    if stage_raw and stage == "unclear" and stage_raw != "unclear":
        warnings.append("a5_invalid_cycle_stage_normalized_to_unclear")
    return {
        "spot_action": action,
        "cycle_stage": stage,
        "confidence": _enum(d.get("confidence"), CONFIDENCE_LEVELS, "low"),
        "headline": _as_str(d.get("headline"), "大周期策略保持观察"),
        "human_summary": _as_str(d.get("human_summary"), "证据不足，默认持有/观察。"),
        "suggested_plan": _as_list(d.get("suggested_plan")),
        "do_not_do": _as_list(d.get("do_not_do")),
        "supporting_evidence": _as_list(d.get("supporting_evidence")),
        "opposing_evidence": _as_list(d.get("opposing_evidence")),
        "what_would_change_mind": _as_list(d.get("what_would_change_mind")),
        "next_review_focus": _as_list(d.get("next_review_focus")),
        "data_quality_notes": _as_list(d.get("data_quality_notes")),
    }


def normalize_layer_a_output(raw: Any) -> dict[str, Any]:
    d = _as_dict(raw)
    violations = list(_as_list((_as_dict(d.get("validator")).get("violations"))))
    warnings = list(_as_list((_as_dict(d.get("validator")).get("warnings"))))

    out = {
        "enabled": bool(d.get("enabled", True)),
        "a1_cycle_stage": normalize_a1(d.get("a1_cycle_stage"), warnings),
        "a2_onchain_macro": normalize_a2(d.get("a2_onchain_macro")),
        "a3_spot_opportunity": normalize_a3(d.get("a3_spot_opportunity"), violations),
        "a4_spot_risk": normalize_a4(d.get("a4_spot_risk")),
        "a5_spot_adjudicator": normalize_a5(
            d.get("a5_spot_adjudicator"), violations, warnings,
        ),
        "validator": {
            "passed": True,
            "violations": violations,
            "warnings": warnings,
        },
        "unavailable_factors": _as_list(d.get("unavailable_factors")),
        "model_notes": _as_list(d.get("model_notes")),
    }
    # Cheap structural warning for obviously forbidden vocabulary.  The
    # dedicated validator performs the full check after all A1-A5 are merged.
    if _contains_forbidden_text(d):
        out["validator"]["warnings"].append("layer_a_output_contains_layer_b_like_terms")
    out["validator"]["passed"] = len(out["validator"]["violations"]) == 0
    return out
