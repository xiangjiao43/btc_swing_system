"""Layer A spot cycle strategy normalize helpers.

Layer A is a separate long-cycle spot-only strategy track.  It never creates
theses, never emits Layer B grades, and never participates in the virtual
account.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .spot_cycle_stage_state import (
    OFFICIAL_CYCLE_STAGES,
    STAGE_DEFAULT_ACTION,
    conservative_action_for_official_stage,
    evaluate_stage_transition,
    is_known_stage,
    normalize_action,
    normalize_stage,
)

SPOT_ACTIONS = ("strong_buy", "dca_buy", "hold", "scale_sell", "strong_sell")
CYCLE_STAGES = (*OFFICIAL_CYCLE_STAGES, "unclear")
CONFIDENCE_LEVELS = ("low", "medium", "high")
ONCHAIN_MACRO_STANCES = (
    "strongly_bullish", "bullish", "neutral", "cautious", "bearish", "unclear",
)
SPOT_RISK_LEVELS = ("low", "moderate", "elevated", "high", "critical")

_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}
_CRITICAL_COVERAGE_FACTORS: set[str] = {
    "mvrv_z_score", "mvrv", "nupl", "rhodl_ratio", "reserve_risk",
    "puell_multiple", "lth_sopr", "sth_sopr", "lth_net_position_change",
    "hodl_waves", "cdd", "exchange_balance",
}


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


def _min_confidence(level: str, cap: str) -> str:
    level = _enum(level, CONFIDENCE_LEVELS, "low")
    cap = _enum(cap, CONFIDENCE_LEVELS, "low")
    return level if _CONFIDENCE_RANK[level] <= _CONFIDENCE_RANK[cap] else cap


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
        re.compile(r"(开空|建立空单|加空单|空单入场)"),
        re.compile(r"(建议|执行|考虑|可以|应该|尝试|转为|改为|切换为)\s*做空"),
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


def _factor_name(v: Any) -> str:
    if isinstance(v, dict):
        return _as_str(v.get("factor") or v.get("name"))
    return _as_str(v)


def _build_factor_coverage(d: dict[str, Any]) -> dict[str, Any]:
    supplied = _as_dict(d.get("factor_coverage"))
    unavailable = _as_list(d.get("unavailable_factors"))
    unavailable_names = [_factor_name(x) for x in unavailable]
    unavailable_names = [x for x in unavailable_names if x]
    critical_missing = [
        x for x in unavailable_names if x in _CRITICAL_COVERAGE_FACTORS
    ]
    total_unavailable = len(unavailable_names)
    critical_count = len(critical_missing)
    coverage_ratio_raw = supplied.get("coverage_ratio")
    try:
        coverage_ratio = float(coverage_ratio_raw)
    except (TypeError, ValueError):
        coverage_ratio = None
    try:
        stale_count = int(supplied.get("stale_factor_count") or 0)
    except (TypeError, ValueError):
        stale_count = 0
    try:
        missing_count = int(supplied.get("missing_integrated_factor_count") or 0)
    except (TypeError, ValueError):
        missing_count = 0

    if coverage_ratio is not None and coverage_ratio < 0.5:
        confidence_cap = "low"
        cap_reason = "Layer A 已接入因子可用率低于 50%"
    elif stale_count >= 5:
        confidence_cap = "medium"
        cap_reason = "5 个以上已接入 Layer A 因子过期"
    elif missing_count >= 5:
        confidence_cap = "medium"
        cap_reason = "5 个以上已接入 Layer A 因子当前缺值"
    elif critical_count >= 10:
        confidence_cap = "medium"
        cap_reason = "10 个以上关键 Layer A 因子未稳定接入"
    elif critical_count >= 5:
        confidence_cap = "medium"
        cap_reason = "5 个以上关键 Layer A 因子未稳定接入"
    else:
        confidence_cap = "high"
        cap_reason = ""

    out = {
        "total_unavailable_factors": total_unavailable,
        "critical_unavailable_count": critical_count,
        "critical_unavailable_factors": critical_missing,
        "confidence_cap": confidence_cap,
        "confidence_cap_reason": cap_reason,
        "missing_integrated_factor_count": missing_count,
        "stale_factor_count": stale_count,
    }
    for key in (
        "available_factor_count",
        "coverage_ratio",
        "coverage_notes",
    ):
        if key in supplied:
            out[key] = supplied[key]
    return out


def _apply_confidence_cap(out: dict[str, Any]) -> None:
    coverage = _as_dict(out.get("factor_coverage"))
    cap = _enum(coverage.get("confidence_cap"), CONFIDENCE_LEVELS, "high")
    if cap == "high":
        return
    adjusted: list[dict[str, str]] = []
    for section in (
        "a1_cycle_stage",
        "a2_onchain_macro",
        "a3_spot_opportunity",
        "a4_spot_risk",
        "a5_spot_adjudicator",
    ):
        obj = _as_dict(out.get(section))
        before = _enum(obj.get("confidence"), CONFIDENCE_LEVELS, "low")
        after = _min_confidence(before, cap)
        if after != before:
            obj["confidence"] = after
            adjusted.append({
                "section": section,
                "from": before,
                "to": after,
                "reason": _as_str(
                    coverage.get("confidence_cap_reason"),
                    "Layer A 因子覆盖不足",
                ),
            })
    if adjusted:
        out["confidence_adjustments"] = adjusted
        out["validator"]["warnings"].append("confidence_capped_by_factor_coverage")


def fallback_layer_a_output(reason: str = "Layer A AI 输出失败或证据不足") -> dict[str, Any]:
    return normalize_layer_a_output(
        {
            "enabled": True,
            "a1_cycle_stage": {
                "cycle_stage": "trend_hold",
                "raw_stage_assessment": "trend_hold",
                "official_cycle_stage": "trend_hold",
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
                "cycle_stage": "trend_hold",
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
            "factor_coverage": {
                "confidence_cap": "low",
                "confidence_cap_reason": reason,
            },
        }
    )


def normalize_a1(raw: Any, warnings: list[str]) -> dict[str, Any]:
    d = _as_dict(raw)
    stage_raw = d.get("official_cycle_stage") or d.get("cycle_stage")
    stage = normalize_stage(stage_raw, default="trend_hold")
    if stage_raw and not is_known_stage(stage_raw):
        warnings.append("a1_invalid_cycle_stage_normalized_to_trend_hold")
    raw_stage = normalize_stage(
        d.get("raw_stage_assessment") or d.get("cycle_stage"),
        default=stage,
    )
    transition = _as_dict(d.get("stage_transition"))
    return {
        "cycle_stage": stage,
        "raw_stage_assessment": raw_stage,
        "official_cycle_stage": stage,
        "previous_official_stage": _as_str(d.get("previous_official_stage")),
        "transition_status": _as_str(d.get("transition_status"), "confirmed"),
        "transition_direction": _as_str(d.get("transition_direction"), "unchanged"),
        "confirmation_count": d.get("confirmation_count") or 1,
        "confirmation_required": d.get("confirmation_required") or 1,
        "stage_change_reason": _as_str(d.get("stage_change_reason")),
        "stage_transition": transition,
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
    action = normalize_action(d.get("preferred_action_candidate"), default="hold")
    if d.get("preferred_action_candidate") and action == "hold" and str(d.get("preferred_action_candidate")).strip().lower() not in ("hold",):
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
    action = normalize_action(action_raw, default="hold")
    if action_raw and action == "hold" and str(action_raw).strip().lower() not in ("hold",):
        violations.append("a5_invalid_spot_action_normalized_to_hold")
    stage_raw = d.get("cycle_stage")
    stage = normalize_stage(stage_raw, default="trend_hold")
    if stage_raw and not is_known_stage(stage_raw):
        warnings.append("a5_invalid_cycle_stage_normalized_to_trend_hold")
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
        "factor_coverage": _build_factor_coverage(d),
        "confidence_adjustments": _as_list(d.get("confidence_adjustments")),
        "input_context_snapshot": _as_dict(d.get("input_context_snapshot")),
        "model_notes": _as_list(d.get("model_notes")),
        "previous_layer_a_state": _as_dict(d.get("previous_layer_a_state")),
        "cycle_stage_model_version": "layer_a_five_stage_v1",
    }
    transition = evaluate_stage_transition(
        raw_stage=out["a1_cycle_stage"].get("raw_stage_assessment")
        or out["a1_cycle_stage"].get("cycle_stage"),
        previous_layer_a=out.get("previous_layer_a_state"),
        factor_coverage=out.get("factor_coverage"),
        risk_level=out["a4_spot_risk"].get("spot_risk_level"),
        validator=out.get("validator"),
    )
    official = transition["official_cycle_stage"]
    out["stage_transition"] = transition
    out["a1_cycle_stage"].update(transition)
    out["a1_cycle_stage"]["cycle_stage"] = official
    out["a5_spot_adjudicator"]["cycle_stage"] = official
    out["a5_spot_adjudicator"]["official_stage_default_action"] = (
        STAGE_DEFAULT_ACTION.get(official, "hold")
    )
    before_action = out["a5_spot_adjudicator"].get("spot_action")
    after_action = conservative_action_for_official_stage(
        official_stage=official,
        proposed_action=before_action,
        risk_level=out["a4_spot_risk"].get("spot_risk_level"),
    )
    if after_action != before_action:
        out["a5_spot_adjudicator"]["spot_action"] = after_action
        out["confidence_adjustments"].append({
            "section": "a5_spot_adjudicator",
            "from": str(before_action),
            "to": after_action,
            "reason": "A5 动作按 official_cycle_stage 和风险做保守归一",
        })
        out["validator"]["warnings"].append("spot_action_aligned_to_official_stage")
    if transition.get("transition_status") in {"pending", "recalibration"}:
        for section in ("a1_cycle_stage", "a5_spot_adjudicator"):
            obj = _as_dict(out.get(section))
            before = _enum(obj.get("confidence"), CONFIDENCE_LEVELS, "low")
            after = _min_confidence(before, "medium")
            if after != before:
                obj["confidence"] = after
                out["confidence_adjustments"].append({
                    "section": section,
                    "from": before,
                    "to": after,
                    "reason": "阶段变化未确认，置信度最高 medium",
                })
        out["validator"]["warnings"].append(
            f"cycle_stage_transition_{transition.get('transition_status')}"
        )
    _apply_confidence_cap(out)
    # Cheap structural warning for obviously forbidden vocabulary.  The
    # dedicated validator performs the full check after all A1-A5 are merged.
    if _contains_forbidden_text(d):
        out["validator"]["warnings"].append("layer_a_output_contains_layer_b_like_terms")
    out["validator"]["passed"] = len(out["validator"]["violations"]) == 0
    return out
