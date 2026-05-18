"""Layer A six-stage cycle state helper.

This helper keeps Layer A as a slow spot-cycle model.  AI may describe the
current raw features, but the official stage changes only after confirmation.
It does not touch Layer B, theses, virtual account, or trading rules.
"""

from __future__ import annotations

from typing import Any


OFFICIAL_CYCLE_STAGES = (
    "bear_bottom",
    "recovery",
    "bull_main",
    "bull_late",
    "top_distribution",
    "bear_decline",
)

CURRENT_STAGE_MODEL_VERSION = "layer_a_six_stage_v2"

STAGE_DEFAULT_ACTION = {
    "bear_bottom": "strong_buy",
    "recovery": "dca_buy",
    "bull_main": "hold",
    "bull_late": "scale_sell",
    "top_distribution": "strong_sell",
    "bear_decline": "exit_all",
}

LEGACY_STAGE_MAP = {
    "bear_bottom": "bear_bottom",
    "recovery": "recovery",
    "bull_main": "bull_main",
    "bull_late": "bull_late",
    "top_distribution": "top_distribution",
    "bear_decline": "bear_decline",
}

ACTION_ALIASES = {
    "aggressive_buy": "strong_buy",
    "scale_out": "scale_sell",
    "aggressive_sell": "strong_sell",
}

ACTION_RANK = {
    "strong_buy": 0,
    "dca_buy": 1,
    "hold": 2,
    "scale_sell": 3,
    "strong_sell": 4,
    "exit_all": 5,
}


def as_dict(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def as_list(v: Any) -> list[Any]:
    if isinstance(v, list):
        return v
    if v in (None, ""):
        return []
    return [v]


def normalize_stage(v: Any, default: str = "bear_bottom") -> str:
    key = str(v or "").strip().lower()
    return LEGACY_STAGE_MAP.get(key, default)


def is_known_stage(v: Any) -> bool:
    return str(v or "").strip().lower() in LEGACY_STAGE_MAP


def normalize_action(v: Any, default: str = "hold") -> str:
    key = str(v or "").strip().lower()
    key = ACTION_ALIASES.get(key, key)
    return key if key in ACTION_RANK else default


def stage_distance(a: str, b: str) -> int:
    try:
        return abs(OFFICIAL_CYCLE_STAGES.index(a) - OFFICIAL_CYCLE_STAGES.index(b))
    except ValueError:
        return 0


def transition_direction(previous: str, raw: str) -> str:
    try:
        prev_i = OFFICIAL_CYCLE_STAGES.index(previous)
        raw_i = OFFICIAL_CYCLE_STAGES.index(raw)
    except ValueError:
        return "unchanged"
    if raw_i > prev_i:
        return "upgrade"
    if raw_i < prev_i:
        return "downgrade"
    return "unchanged"


def _previous_transition(previous: dict[str, Any]) -> dict[str, Any]:
    a1 = as_dict(previous.get("a1_cycle_stage"))
    return as_dict(
        previous.get("stage_transition")
        or previous.get("cycle_stage_transition")
        or a1.get("stage_transition")
    )


def previous_official_stage(previous: dict[str, Any] | None) -> str | None:
    previous = as_dict(previous)
    if not previous:
        return None
    a1 = as_dict(previous.get("a1_cycle_stage"))
    stage = (
        a1.get("official_cycle_stage")
        or a1.get("cycle_stage")
        or as_dict(previous.get("a5_spot_adjudicator")).get("cycle_stage")
    )
    if not stage:
        return None
    return normalize_stage(stage, default="")


def has_current_model(previous: dict[str, Any] | None) -> bool:
    previous = as_dict(previous)
    if not previous:
        return False
    if previous.get("cycle_stage_model_version") == CURRENT_STAGE_MODEL_VERSION:
        return True
    a1 = as_dict(previous.get("a1_cycle_stage"))
    return a1.get("cycle_stage_model_version") == CURRENT_STAGE_MODEL_VERSION


def data_quality_blocks_confirmation(
    *,
    factor_coverage: dict[str, Any],
    validator: dict[str, Any] | None = None,
    risk_level: str | None = None,
) -> tuple[bool, str]:
    validator = as_dict(validator)
    if validator.get("violations"):
        return True, "Layer A validator 存在 hard violation"
    try:
        stale_count = int(factor_coverage.get("stale_factor_count") or 0)
    except (TypeError, ValueError):
        stale_count = 0
    try:
        critical_count = int(factor_coverage.get("critical_unavailable_count") or 0)
    except (TypeError, ValueError):
        critical_count = 0
    cap = str(factor_coverage.get("confidence_cap") or "high").lower()
    if stale_count > 0:
        return True, f"{stale_count} 个已接入因子过期"
    if critical_count > 0:
        return True, f"{critical_count} 个关键因子未稳定接入"
    if cap in {"low", "medium"}:
        return True, f"factor_coverage confidence_cap={cap}"
    if str(risk_level or "").lower() in {"high", "critical"}:
        return True, f"A4 风险等级为 {risk_level}"
    return False, ""


def evaluate_stage_transition(
    *,
    raw_stage: str,
    previous_layer_a: dict[str, Any] | None = None,
    factor_coverage: dict[str, Any] | None = None,
    risk_level: str | None = None,
    validator: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw = normalize_stage(raw_stage)
    previous = previous_official_stage(previous_layer_a)
    coverage = as_dict(factor_coverage)
    blocks_confirmation, block_reason = data_quality_blocks_confirmation(
        factor_coverage=coverage,
        validator=validator,
        risk_level=risk_level,
    )

    if not previous:
        return {
            "raw_stage_assessment": raw,
            "official_cycle_stage": raw,
            "previous_official_stage": None,
            "transition_status": "confirmed",
            "transition_direction": "unchanged",
            "confirmation_count": 1,
            "confirmation_required": 1,
            "stage_change_reason": "首次 Layer A 六阶段输出，直接作为正式阶段。",
            "evidence_for_change": [],
            "evidence_against_change": [],
            "confidence_cap_reason": block_reason,
        }

    direction = transition_direction(previous, raw)
    distance = stage_distance(previous, raw)
    if distance == 0:
        return {
            "raw_stage_assessment": raw,
            "official_cycle_stage": previous,
            "previous_official_stage": previous,
            "transition_status": "confirmed",
            "transition_direction": "unchanged",
            "confirmation_count": 1,
            "confirmation_required": 1,
            "stage_change_reason": "raw_stage 与上一轮正式阶段一致。",
            "evidence_for_change": [],
            "evidence_against_change": [],
            "confidence_cap_reason": block_reason,
        }

    required = 2 if distance == 1 else 3
    prev_transition = _previous_transition(as_dict(previous_layer_a))
    prev_count = 0
    if (
        prev_transition.get("transition_status") in {"pending", "recalibration"}
        and normalize_stage(prev_transition.get("raw_stage_assessment"), default="")
        == raw
        and normalize_stage(prev_transition.get("previous_official_stage"), default="")
        == previous
    ):
        try:
            prev_count = int(prev_transition.get("confirmation_count") or 0)
        except (TypeError, ValueError):
            prev_count = 0
    count = max(1, prev_count + 1)

    if not has_current_model(previous_layer_a):
        status = "recalibration"
        official = previous
        reason = "上一轮不是六阶段模型输出，本轮视为模型重校准，先不确认阶段跳变。"
    elif blocks_confirmation:
        status = "pending"
        official = previous
        reason = f"阶段变化待确认；当前数据质量不支持确认：{block_reason}。"
    elif count >= required:
        status = "confirmed"
        official = raw
        reason = f"raw_stage 连续 {count}/{required} 次指向新阶段，阶段变化已确认。"
    else:
        status = "pending"
        official = previous
        reason = f"raw_stage 指向新阶段，但仅确认 {count}/{required} 次，正式阶段暂不变化。"

    return {
        "raw_stage_assessment": raw,
        "official_cycle_stage": official,
        "previous_official_stage": previous,
        "transition_status": status,
        "transition_direction": direction,
        "confirmation_count": min(count, required),
        "confirmation_required": required,
        "stage_change_reason": reason,
        "evidence_for_change": [],
        "evidence_against_change": [],
        "confidence_cap_reason": block_reason,
    }


def conservative_action_for_official_stage(
    *,
    official_stage: str,
    proposed_action: str,
    risk_level: str | None = None,
) -> str:
    """Conservatize the AI-proposed spot action against the official stage.

    Critical rule: ``exit_all`` is EXEMPT from any conservatization downgrade.
    Liquidation in high-risk conditions is supposed to fire — we must never
    weaken it to ``hold`` or any other action.  The risk-driven downgrade
    only touches buy-side actions (``strong_buy`` / ``dca_buy``).
    """
    official = normalize_stage(official_stage)
    proposed = normalize_action(proposed_action)
    default = STAGE_DEFAULT_ACTION.get(official, "hold")
    risk = str(risk_level or "").lower()

    if proposed == "exit_all":
        return "exit_all"

    if risk in {"high", "critical"} and proposed in {"strong_buy", "dca_buy"}:
        return "hold"
    if official == "bear_bottom" and proposed == "strong_buy":
        return proposed
    if official == "recovery" and proposed == "strong_buy":
        return "dca_buy"
    if official == "bull_main" and proposed in {"strong_buy", "dca_buy"}:
        return "hold"
    if official == "bull_late" and proposed == "strong_sell":
        return "scale_sell"
    if official == "top_distribution" and proposed in {"strong_buy", "dca_buy", "hold"}:
        return default
    if official == "bear_decline" and proposed in {"strong_buy", "dca_buy", "hold", "scale_sell", "strong_sell"}:
        return default
    return proposed
