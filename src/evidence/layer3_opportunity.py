"""
layer3_opportunity.py — L3 机会与执行层(建模 §4.4,M16 纯规则判档)

核心原则:
  1. 无加权,纯硬规则:每个 grade 有硬条件清单,全满足才能达到该等级。
  2. 任一反模式触发 → 强制降级(严格遵循 §7.9)。
  3. grade 决定 observation_mode,不是反过来。

消费:
  * context['layer_1_output']    L1 regime
  * context['layer_2_output']    L2 stance/phase/stance_confidence
  * context['composite_factors'] 全部 6 个 factor 的 output
  * context['klines_1d']         反模式检测需要
  * context['events_upcoming_48h'] 事件窗口检测需要

输出(schemas.yaml layer_3_opportunity_schema + 扩展):
  * opportunity_grade (=grade) / execution_permission / observation_mode
  * anti_pattern_flags + anti_pattern_details
  * base_grade_before_anti_patterns
  * hard_rule_check_results / thresholds_applied / diagnostics / notes
"""

from __future__ import annotations

from typing import Any, Optional

from ._anti_patterns import (
    apply_anti_pattern_impacts,
    scan_anti_patterns,
)
from ._base import EvidenceLayerBase


# ============================================================
# 映射表
# ============================================================

# TruthTrend band → "strength" 概念
_TT_BAND_TO_STRENGTH: dict[str, str] = {
    "true_trend": "strong",
    "weak_trend": "moderate",
    "no_trend":   "weak",
}

# cycle_position.cycle_position 九档 → phase(与 L2 一致)
_CYCLE_TO_PHASE: dict[str, str] = {
    "accumulation": "early", "early_bull": "early",
    "mid_bull": "mid",
    "late_bull": "late", "distribution": "late",
    "early_bear": "early", "mid_bear": "mid", "late_bear": "late",
    "unclear": "unclear",
}

# grade 到 observation_mode 映射
_GRADE_TO_OBS_MODE: dict[str, str] = {
    "A": "disciplined_validation",
    "B": "disciplined_validation",
    "C": "kpi_validation",
    "none": "kpi_validation",
}

# 冷启动期 grade 天花板
_COLD_START_GRADE_CEILING: str = "B"

# Grade 严格度(用于冷启动天花板 clamp 和聚合 override)
_GRADE_SEVERITY: list[str] = ["A", "B", "C", "none"]


# ============================================================
# Layer3Opportunity
# ============================================================

class Layer3Opportunity(EvidenceLayerBase):
    layer_id = 3
    layer_name = "opportunity"
    thresholds_key = "layer_3_opportunity"

    def _compute_specific(self, context: dict[str, Any]) -> dict[str, Any]:
        l1: dict[str, Any] = context.get("layer_1_output") or {}
        l2: dict[str, Any] = context.get("layer_2_output") or {}
        composites: dict[str, Any] = context.get("composite_factors") or {}

        # ---- 读 thresholds 块 ----
        a_cfg: dict[str, Any] = self.scoring_config.get("grade_a_floors", {})
        b_cfg: dict[str, Any] = self.scoring_config.get("grade_b_floors", {})
        c_cfg: dict[str, Any] = self.scoring_config.get("grade_c_floors", {})
        ap_cfg: dict[str, Any] = self.scoring_config.get("anti_patterns", {})

        # ---- Step 0: 基础门槛 ----
        l2_health = l2.get("health_status")
        l2_tier = l2.get("confidence_tier")
        stance = l2.get("stance", "neutral")
        stance_confidence: float = float(l2.get("stance_confidence", 0.0))
        candidate = stance  # L3 候选方向 = L2 stance

        # neutral / insufficient → 直接 grade=none + watch
        if stance == "neutral" or l2_health == "insufficient_data" \
                or l2_tier == "very_low":
            return self._emit_none(
                reason=(
                    "stance=neutral" if stance == "neutral"
                    else f"L2 unhealthy: health={l2_health}, tier={l2_tier}"
                ),
                candidate=candidate,
                l2_stance_confidence=stance_confidence,
                a_cfg=a_cfg, b_cfg=b_cfg, c_cfg=c_cfg,
                cold_start=context.get("cold_start") or {},
                l1=l1, l2=l2, composites=composites,
            )

        # ---- 提取 composite outputs ----
        tt = composites.get("truth_trend") or {}
        bp = composites.get("band_position") or {}
        cp = composites.get("cycle_position") or {}
        crowd = composites.get("crowding") or {}
        er = composites.get("event_risk") or {}
        mh = composites.get("macro_headwind") or {}

        tt_band = tt.get("band", "no_trend")
        tt_strength = _TT_BAND_TO_STRENGTH.get(tt_band, "weak")
        cp_band = cp.get("cycle_position", "unclear")
        cp_confidence: float = float(cp.get("cycle_confidence", 0.0))
        bp_phase = bp.get("phase", "unclear")
        crowd_band = crowd.get("band", "normal")
        er_band = er.get("band", "low")
        mh_band = mh.get("band") if mh else None

        regime = l1.get("regime") or l1.get("regime_primary") or "unknown"

        # ---- Step 1: Grade A 硬规则检查 ----
        a_checks, a_pass = _check_grade_a(
            a_cfg, stance=stance, stance_confidence=stance_confidence,
            cp_confidence=cp_confidence, tt_band=tt_band,
            bp_phase=bp_phase, crowd_band=crowd_band,
            regime=regime, er_band=er_band, mh_band=mh_band,
        )

        # ---- Step 2: Grade B 硬规则检查 ----
        b_checks, b_pass = _check_grade_b(
            b_cfg, stance=stance, stance_confidence=stance_confidence,
            cp_confidence=cp_confidence, cp_band=cp_band,
            tt_band=tt_band, bp_phase=bp_phase,
            crowd_band=crowd_band, regime=regime, er_band=er_band,
        )

        # ---- Step 3: Grade C 硬规则检查 ----
        c_pass = stance_confidence >= float(c_cfg.get("stance_confidence", 0.55))

        # cycle unclear / tt weak → 最多 C(强制上限)
        cycle_unclear = cp_band == "unclear"
        tt_weak = tt_band == "no_trend"

        # ---- 基础 grade ----
        if a_pass and not cycle_unclear and not tt_weak:
            base_grade = "A"
        elif b_pass and not cycle_unclear and not tt_weak:
            base_grade = "B"
        elif c_pass:
            base_grade = "C"
        else:
            base_grade = "none"

        # ---- Step 4: 反模式扫描 ----
        candidate_dir_for_scan = candidate  # bullish/bearish
        flags, details = scan_anti_patterns(
            context, candidate_dir_for_scan, ap_cfg
        )

        # ---- Step 5: 反模式应用(降级 + permission cap)----
        base_permission = _grade_to_base_permission(base_grade)
        final_grade, final_permission = apply_anti_pattern_impacts(
            base_grade, base_permission, flags, details,
        )

        # ---- Step 6: 冷启动降级(grade 天花板 B)----
        cold_start = context.get("cold_start") or {}
        if cold_start.get("warming_up"):
            final_grade = _cap_grade(final_grade, _COLD_START_GRADE_CEILING)
            # 如果被 cap,permission 也要跟随降级
            final_permission = _grade_to_base_permission(final_grade)
            # 但反模式的 permission_cap 仍优先(保持严格度)
            for flag in flags:
                cap = (details.get(flag) or {}).get("permission_cap")
                if cap:
                    from ._anti_patterns import _stricter
                    final_permission = _stricter(final_permission, cap)

        # ---- Observation mode ----
        observation_mode = _GRADE_TO_OBS_MODE[final_grade]

        # ---- 组装输出 ----
        opportunity_reason = _build_reason(
            final_grade, base_grade, flags, stance_confidence, cp_confidence,
        )

        hard_rule_check_results = {
            "grade_a": a_checks,
            "grade_b": b_checks,
            "grade_c_stance_confidence": c_pass,
            "cycle_not_unclear": not cycle_unclear,
            "truth_trend_not_weak": not tt_weak,
        }

        thresholds_applied = {
            "grade_a_stance_confidence_floor": a_cfg.get("stance_confidence"),
            "grade_b_stance_confidence_floor": b_cfg.get("stance_confidence"),
            "grade_c_stance_confidence_floor": c_cfg.get("stance_confidence"),
            "grade_a_cycle_confidence_floor": a_cfg.get("cycle_confidence"),
            "grade_b_cycle_confidence_floor": b_cfg.get("cycle_confidence"),
        }

        diagnostics = {
            "inputs": {
                "stance": stance,
                "stance_confidence": stance_confidence,
                "regime": regime,
                "cycle_position": cp_band,
                "cycle_confidence": cp_confidence,
                "tt_band": tt_band, "tt_strength": tt_strength,
                "bp_phase": bp_phase,
                "crowd_band": crowd_band,
                "event_risk_band": er_band,
                "macro_headwind_band": mh_band,
            },
            "grade_evaluation": {
                "a_pass": a_pass, "b_pass": b_pass, "c_pass": c_pass,
                "cycle_unclear_cap": cycle_unclear,
                "tt_weak_cap": tt_weak,
            },
            "anti_patterns_applied": flags,
            "base_before_cold_start": base_grade,
            "cold_start_active": bool(cold_start.get("warming_up")),
        }

        notes: list[str] = []
        if cycle_unclear:
            notes.append("cycle=unclear → grade capped at C")
        if tt_weak:
            notes.append("truth_trend=weak(no_trend)→ grade capped at C")
        if flags:
            notes.append(f"anti-patterns triggered: {', '.join(flags)}")
        if cold_start.get("warming_up"):
            notes.append(f"cold_start warming_up → grade ceiling={_COLD_START_GRADE_CEILING}")
            notes.append(
                "awaiting L4 cold_start sample-count check integration in Sprint 1.12"
            )
        if not mh:
            notes.append("macro_headwind missing → macro_misalignment not checked")

        return {
            "opportunity_grade": final_grade,
            "grade": final_grade,                 # alias
            "execution_permission": final_permission,
            "observation_mode": observation_mode,
            "opportunity_reason": opportunity_reason,
            "base_grade_before_anti_patterns": base_grade,
            "anti_pattern_flags": flags,
            "anti_pattern_details": details,
            "thresholds_applied": thresholds_applied,
            "hard_rule_check_results": hard_rule_check_results,
            "suggested_entry_plan": None,         # Sprint 1.10+ 的 pipeline 负责填
            "risk_reward": None,
            "timing_assessment": {
                "momentum_phase": bp_phase,
                "candidate_direction": candidate,
                "stance_confidence": stance_confidence,
            },
            "liquidity_context": None,
            "entry_confirmation_timeframe": self.scoring_config.get(
                "entry_confirmation_timeframe", "1h"
            ),
            "diagnostics": diagnostics,
            "notes": notes,
            "health_status": "healthy",
            "confidence_tier": _grade_to_tier(final_grade),
            "computation_method": "rule_based",
        }

    def _emit_none(
        self, *, reason: str, candidate: str, l2_stance_confidence: float,
        a_cfg: dict, b_cfg: dict, c_cfg: dict, cold_start: dict,
        l1: dict, l2: dict, composites: dict,
    ) -> dict[str, Any]:
        """统一的"直接 grade=none + watch"出口。"""
        return {
            "opportunity_grade": "none",
            "grade": "none",
            "execution_permission": "watch",
            "observation_mode": "kpi_validation",
            "opportunity_reason": reason,
            "base_grade_before_anti_patterns": "none",
            "anti_pattern_flags": [],
            "anti_pattern_details": {},
            "thresholds_applied": {
                "grade_a_stance_confidence_floor": a_cfg.get("stance_confidence"),
                "grade_b_stance_confidence_floor": b_cfg.get("stance_confidence"),
                "grade_c_stance_confidence_floor": c_cfg.get("stance_confidence"),
            },
            "hard_rule_check_results": {"early_exit": True},
            "suggested_entry_plan": None,
            "risk_reward": None,
            "timing_assessment": {
                "candidate_direction": candidate,
                "stance_confidence": l2_stance_confidence,
            },
            "liquidity_context": None,
            "entry_confirmation_timeframe": "1h",
            "diagnostics": {
                "early_exit_reason": reason,
                "l2_stance": l2.get("stance"),
                "l2_health": l2.get("health_status"),
                "l1_regime": l1.get("regime"),
            },
            "notes": [reason],
            "health_status": (
                "insufficient_data" if l2.get("health_status") == "insufficient_data"
                else "healthy"
            ),
            "confidence_tier": "very_low",
            "computation_method": "rule_based",
        }


# ============================================================
# Grade 硬规则检查
# ============================================================

def _check_grade_a(
    cfg: dict[str, Any],
    *, stance: str, stance_confidence: float, cp_confidence: float,
    tt_band: str, bp_phase: str, crowd_band: str,
    regime: str, er_band: str, mh_band: Optional[str],
) -> tuple[dict[str, bool], bool]:
    """Grade A 硬规则检查。返回 (每项结果 dict, 全通过 bool)。"""
    allowed_tt = set(cfg.get("truth_trend_allowed_bands") or [])
    allowed_phase = set(cfg.get("band_position_allowed_phases") or [])
    disallowed_crowd = set(cfg.get("crowding_disallowed_bands") or [])
    allowed_regime = set(cfg.get("regime_allowed") or [])
    disallowed_er = set(cfg.get("event_risk_disallowed_bands") or [])
    disallowed_mh_bull = set(cfg.get("macro_disallowed_bands_bullish") or [])

    sc_floor = float(cfg.get("stance_confidence", 0.70))
    cc_floor = float(cfg.get("cycle_confidence", 0.85))

    checks = {
        "stance_confidence_ge_floor": stance_confidence >= sc_floor,
        "cycle_confidence_ge_floor": cp_confidence >= cc_floor,
        "truth_trend_in_allowed": tt_band in allowed_tt,
        "band_phase_supportive": bp_phase in allowed_phase,
        "crowding_not_extreme": crowd_band not in disallowed_crowd,
        "regime_is_trend": regime in allowed_regime,
        "event_risk_not_high": er_band not in disallowed_er,
        "macro_not_against_bullish": (
            stance != "bullish"
            or mh_band is None
            or mh_band not in disallowed_mh_bull
        ),
    }
    return checks, all(checks.values())


def _check_grade_b(
    cfg: dict[str, Any],
    *, stance: str, stance_confidence: float, cp_confidence: float,
    cp_band: str, tt_band: str, bp_phase: str,
    crowd_band: str, regime: str, er_band: str,
) -> tuple[dict[str, bool], bool]:
    """Grade B 硬规则检查。"""
    allowed_tt = set(cfg.get("truth_trend_allowed_bands") or [])
    disallowed_phase_bull = set(cfg.get("band_position_disallowed_phases_bullish") or [])
    disallowed_phase_bear = set(cfg.get("band_position_disallowed_phases_bearish") or [])
    allowed_regime = set(cfg.get("regime_allowed") or [])

    sc_floor = float(cfg.get("stance_confidence", 0.62))
    cc_floor = float(cfg.get("cycle_confidence", 0.60))

    if stance == "bullish":
        bp_ok = bp_phase not in disallowed_phase_bull
    elif stance == "bearish":
        bp_ok = bp_phase not in disallowed_phase_bear
    else:
        bp_ok = True

    checks = {
        "stance_confidence_ge_floor": stance_confidence >= sc_floor,
        "cycle_confidence_ge_floor": cp_confidence >= cc_floor,
        "truth_trend_in_allowed": tt_band in allowed_tt,
        "band_phase_not_disallowed": bp_ok,
        "regime_allowed": regime in allowed_regime,
        "cycle_not_unclear": cp_band != "unclear",
    }
    # crowding / event_risk 对 B 级允许 flag 但不阻断
    return checks, all(checks.values())


# ============================================================
# Grade → permission / tier
# ============================================================

def _grade_to_base_permission(grade: str) -> str:
    return {
        "A": "can_open",
        "B": "cautious_open",
        "C": "hold_only",
        "none": "watch",
    }.get(grade, "watch")


def _grade_to_tier(grade: str) -> str:
    return {
        "A": "high",
        "B": "medium",
        "C": "low",
        "none": "very_low",
    }.get(grade, "very_low")


def _cap_grade(grade: str, ceiling: str) -> str:
    """把 grade 向下 clamp 到 ceiling 不高于 ceiling 的严格度。"""
    idx_g = _GRADE_SEVERITY.index(grade) if grade in _GRADE_SEVERITY else len(_GRADE_SEVERITY) - 1
    idx_c = _GRADE_SEVERITY.index(ceiling) if ceiling in _GRADE_SEVERITY else 0
    if idx_g < idx_c:
        return ceiling
    return grade


def _build_reason(
    final_grade: str, base_grade: str, flags: list[str],
    stance_confidence: float, cycle_confidence: float,
) -> str:
    parts = [f"grade={final_grade}"]
    if final_grade != base_grade:
        parts.append(f"(downgraded from {base_grade})")
    parts.append(f"stance_conf={stance_confidence:.3f}")
    parts.append(f"cycle_conf={cycle_confidence:.3f}")
    if flags:
        parts.append(f"anti-patterns={','.join(flags)}")
    return " | ".join(parts)
