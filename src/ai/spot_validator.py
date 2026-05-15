"""Layer A spot-only guardrail.

This validator is intentionally separate from the Layer B 24-rule validator.
It prevents AI output from crossing Layer A boundaries, but it does not make
the spot strategy decision for the AI.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .spot_strategy_normalizer import SPOT_ACTIONS

_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


_ACTION_FORBIDDEN_PATTERNS = (
    (re.compile(r"\btrend_short\b", re.I), "trend_short"),
    (re.compile(r"\bhedge[_\s-]*short\b", re.I), "hedge_short"),
    (re.compile(r"\b(open|go|enter|take|recommend|suggest|建议|执行)\s+(a\s+)?short\b", re.I), "short"),
    (re.compile(r"(开空|建立空单|加空单|空单入场)"), "做空"),
    (re.compile(r"(建议|执行|考虑|可以|应该|尝试|转为|改为|切换为)\s*做空"), "做空"),
    (re.compile(r"(创建|新建|生成|开启)\s*thesis", re.I), "thesis"),
    (re.compile(r"(设置|给出|生成|输出|使用)\s*(entry|entry_zone|entry_orders|stop_loss|take_profit|position_size|leverage)", re.I), "trade_plan_field"),
    (re.compile(r"(使用|输出|采用)\s*(A/B/C|a/b/c|NONE)\s*(机会等级|grade|评级)?", re.I), "layer_b_grade"),
    (re.compile(r"\b(opportunity_grade|execution_permission)\b", re.I), "layer_b_grade_field"),
)

_FORBIDDEN_FIELD_NAMES = (
    "thesis", "new_thesis", "active_thesis", "entry", "entry_zone",
    "entry_orders", "stop_loss", "take_profit", "position_size",
    "position_size_pct", "trade_plan", "virtual_account",
)


def _as_dict(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _as_list(v: Any) -> list[Any]:
    if isinstance(v, list):
        return v
    if v in (None, ""):
        return []
    return [v]


def _blob(v: Any) -> str:
    try:
        return json.dumps(v, ensure_ascii=False, default=str)
    except Exception:
        return str(v)


def _is_negated_boundary_statement(text: str, start: int) -> bool:
    """Allow boundary notes such as "不做空" while still catching actions."""
    prefix = text[max(0, start - 18):start].lower()
    negators = (
        "不", "不要", "不得", "不能", "不允许", "禁止", "避免",
        "no ", "not ", "never ", "do not ", "don't ", "cannot ",
        "does not ", "is not ", "should not ", "must not ",
    )
    return any(neg in prefix for neg in negators)


def _find_actionable_forbidden_text(v: Any) -> str | None:
    text = _blob(v)
    for pattern, label in _ACTION_FORBIDDEN_PATTERNS:
        for match in pattern.finditer(text):
            if not _is_negated_boundary_statement(text, match.start()):
                return label
    return None


def _contains_forbidden_field(v: Any) -> str | None:
    if isinstance(v, dict):
        for k, child in v.items():
            if str(k) in _FORBIDDEN_FIELD_NAMES:
                return str(k)
            found = _contains_forbidden_field(child)
            if found:
                return found
    elif isinstance(v, list):
        for child in v:
            found = _contains_forbidden_field(child)
            if found:
                return found
    return None


def validate_spot_strategy_output(
    output: dict[str, Any],
    *,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    violations: list[str] = []
    warnings: list[str] = []

    a5 = _as_dict(output.get("a5_spot_adjudicator"))
    a4 = _as_dict(output.get("a4_spot_risk"))
    action = a5.get("spot_action")
    risk = a4.get("spot_risk_level")
    stage = a5.get("cycle_stage") or _as_dict(output.get("a1_cycle_stage")).get("cycle_stage")

    if action not in SPOT_ACTIONS:
        violations.append("invalid_spot_action")

    forbidden_text = _find_actionable_forbidden_text(output)
    if forbidden_text:
        violations.append(f"forbidden_layer_b_or_short_term:{forbidden_text}")
    forbidden_field = _contains_forbidden_field(output)
    if forbidden_field:
        violations.append(f"forbidden_layer_b_field:{forbidden_field}")

    if not a5.get("human_summary"):
        violations.append("missing_a5_human_summary")
    if not a5.get("what_would_change_mind"):
        violations.append("missing_what_would_change_mind")

    if action in ("strong_buy", "strong_sell"):
        if not _as_list(a5.get("supporting_evidence")):
            violations.append(f"{action}_missing_supporting_evidence")
        if not _as_list(a5.get("opposing_evidence")):
            violations.append(f"{action}_missing_opposing_evidence")

    unavailable = _as_list((context or {}).get("unavailable_factors"))
    dq_notes = []
    for section in (
        "a1_cycle_stage", "a2_onchain_macro", "a3_spot_opportunity",
        "a4_spot_risk", "a5_spot_adjudicator",
    ):
        dq_notes.extend(_as_list(_as_dict(output.get(section)).get("data_quality_notes")))
    if unavailable and not dq_notes:
        violations.append("missing_data_quality_notes_for_unavailable_factors")

    if action == "strong_buy" and risk in ("high", "critical"):
        warnings.append("strong_buy_with_high_or_critical_risk")
    if action == "strong_sell" and stage in ("bear_bottom", "accumulation"):
        warnings.append("strong_sell_in_value_or_accumulation_stage")
    if action == "dca_buy" and risk == "critical":
        warnings.append("dca_buy_with_critical_risk")
    if action == "scale_sell":
        combined = _blob(a4.get("overheat_signals")) + _blob(a5.get("supporting_evidence"))
        if not any(k in combined for k in ("过热", "派发", "牛市后期", "宏观", "overheat", "late_bull", "risk")):
            warnings.append("scale_sell_without_overheat_distribution_or_macro_evidence")
    if not _as_list(a5.get("opposing_evidence")):
        warnings.append("missing_opposing_evidence")

    confidence = a5.get("confidence")
    if unavailable and confidence == "high":
        warnings.append("high_confidence_with_many_missing_factors")
    coverage_cap = (
        _as_dict((context or {}).get("factor_coverage")).get("confidence_cap")
    )
    if (
        confidence in _CONFIDENCE_RANK
        and coverage_cap in _CONFIDENCE_RANK
        and _CONFIDENCE_RANK[confidence] > _CONFIDENCE_RANK[coverage_cap]
    ):
        warnings.append("confidence_exceeds_factor_coverage_cap")

    forbidden_text = _find_actionable_forbidden_text(output)
    if forbidden_text or _contains_forbidden_field(output):
        warnings.append("layer_a_output_looks_like_layer_b_trade_plan")

    return {
        "passed": len(violations) == 0,
        "violations": violations,
        "warnings": warnings,
    }
