"""Layer A spot-only guardrail.

This validator is intentionally separate from the Layer B 24-rule validator.
It prevents AI output from crossing Layer A boundaries, but it does not make
the spot strategy decision for the AI.
"""

from __future__ import annotations

import json
from typing import Any

from .spot_strategy_normalizer import SPOT_ACTIONS


_HARD_FORBIDDEN_TERMS = (
    "short", "做空", "空单", "trend_short", "hedge", "对冲",
    "opportunity_grade", "execution_permission", "a/b/c", "A/B/C", "NONE",
    "leverage", "杠杆",
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

    text = _blob(output)
    for term in _HARD_FORBIDDEN_TERMS:
        if term in text:
            violations.append(f"forbidden_layer_b_or_short_term:{term}")
            break
    forbidden_field = _contains_forbidden_field(output)
    if forbidden_field:
        violations.append(f"forbidden_layer_b_field:{forbidden_field}")

    if not a5.get("human_summary"):
        violations.append("missing_a5_human_summary")
    if not a5.get("what_would_change_mind"):
        violations.append("missing_what_would_change_mind")

    if action in ("aggressive_buy", "aggressive_sell"):
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

    if action == "aggressive_buy" and risk in ("high", "critical"):
        warnings.append("aggressive_buy_with_high_or_critical_risk")
    if action == "aggressive_sell" and stage in ("bear_bottom", "accumulation"):
        warnings.append("aggressive_sell_in_bottom_or_accumulation_stage")
    if action == "dca_buy" and risk == "critical":
        warnings.append("dca_buy_with_critical_risk")
    if action == "scale_out":
        combined = _blob(a4.get("overheat_signals")) + _blob(a5.get("supporting_evidence"))
        if not any(k in combined for k in ("过热", "派发", "宏观", "overheat", "distribution", "risk")):
            warnings.append("scale_out_without_overheat_distribution_or_macro_evidence")
    if not _as_list(a5.get("opposing_evidence")):
        warnings.append("missing_opposing_evidence")

    confidence = a5.get("confidence")
    if unavailable and confidence == "high":
        warnings.append("high_confidence_with_many_missing_factors")

    if any(k in text for k in ("entry_orders", "trade_plan", "virtual_account")):
        warnings.append("layer_a_output_looks_like_layer_b_trade_plan")

    return {
        "passed": len(violations) == 0,
        "violations": violations,
        "warnings": warnings,
    }
