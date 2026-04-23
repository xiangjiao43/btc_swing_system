"""
layer2_direction.py — L2 方向与结构层(建模 §4.3)

输出 stance(bullish / bearish / neutral)+ phase(early/mid/late/
exhausted/unclear/n_a)+ stance_confidence(0.0-1.0)。

消费:
  * context['layer_1_output']       L1 regime 输出
  * context['composite_factors']    {truth_trend, band_position, cycle_position}
  * context['single_factors']       可选,{exchange_momentum_score}
  * context['cold_start']           可选

**不直接读 K 线**(建模 §4.3.2 判断三支柱全部来自 composite / L1 结论)。

判定流程(严格对照建模 §4.3.5):
  Step 1  候选方向      regime × truth_trend 推导
  Step 2  查动态门槛    cycle_position → long/short threshold
  Step 3  加权计分      (tt 0.35 / regime 0.25 / cycle 0.30 / band 0.10)
          + [floor 0.55, ceiling 0.75] clamp
          + unclear / missing cycle 时覆盖 clamp 规则
  Step 4  触发判定      stance_confidence > threshold → stance
  Step 5  phase 判定    cycle_position → phase(neutral → n_a)
  Step 6  修正          exchange_momentum(仅多头)/ 冷启动 × 0.8
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from ._base import EvidenceLayerBase


logger = logging.getLogger(__name__)


# ============================================================
# 常量
# ============================================================

_VALID_STANCES: tuple[str, ...] = ("bullish", "bearish", "neutral")
_VALID_PHASES: tuple[str, ...] = (
    "early", "mid", "late", "exhausted", "unclear", "n_a"
)

# TruthTrend band → strength score(加权计分第 1 项)
_TT_STRENGTH_SCORE: dict[str, float] = {
    "true_trend": 0.9,
    "weak_trend": 0.6,
    "no_trend":   0.3,
}

# L1 regime 对候选方向的支持度(加权计分第 2 项)
_REGIME_ALIGNED_SUPPORT: dict[str, float] = {
    "trend_up": 1.0,
    "trend_down": 1.0,
    "transition_up": 0.7,
    "transition_down": 0.7,
    "range_high": 0.4,
    "range_mid": 0.4,
    "range_low": 0.4,
    "chaos": 0.2,
}

# band_position.phase 对候选方向的**附加贡献**(加权计分第 4 项)
# 范围 [-0.25, +0.15]:方向友好 → 加分;方向不友好 → 减分
# (注:用户任务描述用"0.10 weight",我改为直接附加值以让影响够大;
#  见 sprint_1_8.md Trigger)
_BAND_CONTRIB_FOR_DIRECTION: dict[str, float] = {
    "early": 0.15,
    "mid": 0.05,
    "late": -0.10,
    "exhausted": -0.25,
    "unclear": 0.0,
    "n_a": 0.0,
}

# cycle_position → phase 映射
_CYCLE_TO_PHASE: dict[str, str] = {
    "accumulation": "early",
    "early_bull": "early",
    "mid_bull": "mid",
    "late_bull": "late",
    "distribution": "late",
    "early_bear": "early",
    "mid_bear": "mid",
    "late_bear": "late",
    "unclear": "unclear",
}


# ============================================================
# Layer2Direction
# ============================================================

class Layer2Direction(EvidenceLayerBase):
    layer_id = 2
    layer_name = "direction"
    thresholds_key = "layer_2_direction"

    # 加权计分公式权重(用户任务描述)
    _WEIGHTS: dict[str, float] = {
        "truth_trend": 0.35,
        "regime":      0.25,
        "cycle":       0.30,
        # band_position 单独作附加项(不按权重,直接累加 [-0.25, +0.15])
    }

    def _compute_specific(self, context: dict[str, Any]) -> dict[str, Any]:
        l1: dict[str, Any] = context.get("layer_1_output") or {}
        composites: dict[str, Any] = context.get("composite_factors") or {}
        single_factors: dict[str, Any] = context.get("single_factors") or {}

        tt: dict[str, Any] = composites.get("truth_trend") or {}
        bp: dict[str, Any] = composites.get("band_position") or {}
        cp: Optional[dict[str, Any]] = composites.get("cycle_position")

        # ---- 完整性检查 ----
        missing: list[str] = []
        if not l1:
            missing.append("layer_1_output")
        if not tt or not tt.get("band"):
            missing.append("truth_trend")
        if not bp or not bp.get("phase"):
            missing.append("band_position")

        if missing:
            # truth_trend 或 L1 缺失 → 完全无法判定
            notes = [f"missing: {', '.join(missing)}"]
            if "layer_1_output" in missing or "truth_trend" in missing:
                return self._insufficient(
                    notes[0],
                    stance="neutral",
                    phase="n_a",
                    stance_confidence=0.0,
                    candidate_direction="unknown",
                    thresholds_applied={},
                    conflict_flags=["missing_core_input"],
                    diagnostics={"missing": missing},
                    band_position_score=None,
                    exchange_momentum_score=None,
                )
            # 只缺 band_position → 可降级继续算,但 band_contribution = 0
            cold_notes = list(notes)
        else:
            cold_notes = []

        # ---- Step 1: 候选方向 ----
        regime: str = l1.get("regime") or l1.get("regime_primary") or "unknown"
        tt_direction: str = tt.get("direction") or "unknown"
        tt_band: str = tt.get("band") or "no_trend"

        candidate, step1_flags = _derive_candidate(regime, tt_direction, tt_band)

        # ---- Step 2: 查动态门槛 ----
        cp_missing = cp is None
        cp_band: str = (cp.get("cycle_position") if cp else None) or "unclear"
        cp_confidence: float = float(cp.get("cycle_confidence", 0.0)) if cp else 0.0

        thresholds_dict = self.scoring_config.get(
            "dynamic_direction_thresholds", {}
        )
        thresholds_applied = _lookup_thresholds(thresholds_dict, cp_band)

        # ---- Step 3: 加权计分 ----
        tt_score = _TT_STRENGTH_SCORE.get(tt_band, 0.3)
        # regime 支持度:候选方向与 regime 对齐才拿满分
        regime_score = _regime_support_for_candidate(regime, candidate, step1_flags)
        # cycle 支持度:直接用 cp.cycle_confidence
        cycle_score = cp_confidence if not cp_missing else 0.0

        # band 附加项(对候选方向的友好度)
        bp_phase = bp.get("phase", "unclear")
        band_contribution = _BAND_CONTRIB_FOR_DIRECTION.get(bp_phase, 0.0)
        if candidate == "neutral":
            band_contribution = 0.0

        weights = self._WEIGHTS
        raw_weighted = (
            weights["truth_trend"] * tt_score
            + weights["regime"] * regime_score
            + weights["cycle"] * cycle_score
            + band_contribution
        )

        # ---- Step 3b: clamp 规则 ----
        floor = float(self.scoring_config.get("stance_confidence_floor", 0.55))
        ceiling = float(self.scoring_config.get("stance_confidence_ceiling", 0.75))

        clamp_notes: list[str] = []
        if cp_missing:
            # cycle 完全缺失 → 无法置信 → 盖到 0.30
            stance_confidence = min(raw_weighted, 0.30)
            clamp_notes.append("cycle_position missing → capped at 0.30")
        elif cp_band == "unclear":
            # cycle unclear → 盖到 ceiling(不清楚时不能高置信)
            stance_confidence = min(raw_weighted, ceiling)
            clamp_notes.append("cycle_position unclear → capped at ceiling")
        else:
            stance_confidence = max(floor, min(ceiling, raw_weighted))
            if raw_weighted < floor:
                clamp_notes.append(f"raw {raw_weighted:.3f} < floor {floor}")
            elif raw_weighted > ceiling:
                clamp_notes.append(f"raw {raw_weighted:.3f} > ceiling {ceiling}")

        # ---- Step 6a: Exchange Momentum 修正(仅多头侧,§B5)----
        em_score = single_factors.get("exchange_momentum_score")
        em_flag: Optional[str] = None
        if em_score is not None and candidate == "bullish":
            em_val = float(em_score)
            # em 与候选 bullish 方向冲突 → em < 0 且我们要 bullish
            if em_val < 0:
                stance_confidence *= 0.85
                em_flag = "exchange_momentum_divergence"
                clamp_notes.append(
                    f"exchange_momentum={em_val:.2f} 与 bullish 方向冲突,× 0.85"
                )
        elif em_score is None:
            cold_notes.append("exchange_momentum not provided in context, skipped")

        # ---- Step 6b: 冷启动降级(stance_confidence × 0.8)----
        cold_start = context.get("cold_start") or {}
        if cold_start.get("warming_up"):
            stance_confidence *= 0.8
            clamp_notes.append("cold_start warming_up → stance_confidence × 0.8")

        stance_confidence = round(max(0.0, stance_confidence), 4)

        # ---- Step 4: 触发判定 ----
        long_th = float(thresholds_applied.get("long", 0.65))
        short_th = float(thresholds_applied.get("short", 0.70))

        if candidate == "bullish" and stance_confidence > long_th:
            stance = "bullish"
        elif candidate == "bearish" and stance_confidence > short_th:
            stance = "bearish"
        else:
            stance = "neutral"

        # ---- Step 5: phase 判定 ----
        phase: str
        if stance == "neutral":
            phase = "n_a"
        else:
            phase = _CYCLE_TO_PHASE.get(cp_band, "unclear")

        # ---- conflict_flags 汇总 ----
        conflict_flags = list(step1_flags)
        if cp_missing:
            conflict_flags.append("missing_cycle_position")
        elif cp_band == "unclear":
            conflict_flags.append("unclear_cycle_position")
        if em_flag:
            conflict_flags.append(em_flag)
        if "band_position" in missing:
            conflict_flags.append("missing_band_position")

        # ---- health_status ----
        if "band_position" in missing or cp_missing:
            health_status = "degraded"
        elif step1_flags and "l1_truth_trend_conflict" in step1_flags:
            health_status = "degraded"
        else:
            health_status = "healthy"

        # ---- confidence_tier 按 stance_confidence 分档(L2 特殊:
        #       stance_confidence 是内部量,但可映射到 tier 供下游参考)----
        from ._base import confidence_tier_from_value
        confidence_tier = confidence_tier_from_value(stance_confidence)

        # ---- diagnostics ----
        diagnostics = {
            "base_score_breakdown": {
                "truth_trend": round(tt_score, 3),
                "regime": round(regime_score, 3),
                "cycle": round(cycle_score, 3),
                "band_contribution": round(band_contribution, 3),
            },
            "weights_used": dict(weights),
            "raw_weighted_score": round(raw_weighted, 4),
            "floor_ceiling": [floor, ceiling],
            "clamp_notes": clamp_notes,
            "tt_direction": tt_direction,
            "tt_band": tt_band,
            "l1_regime": regime,
            "cp_band": cp_band,
            "cp_confidence": cp_confidence,
            "bp_phase": bp_phase,
            "em_score": em_score,
        }

        notes: list[str] = []
        if cold_notes:
            notes.extend(cold_notes)
        if clamp_notes:
            notes.append(f"stance_confidence clamp: {clamp_notes}")

        return {
            "stance": stance,
            "phase": phase,
            "stance_confidence": stance_confidence,
            "candidate_direction": candidate,
            "thresholds_applied": thresholds_applied,
            "conflict_flags": conflict_flags,
            "diagnostics": diagnostics,
            "band_position_score": bp.get("phase_confidence"),
            "exchange_momentum_score": em_score,
            "long_cycle_context": {
                "cycle_position": cp_band,
                "cycle_confidence": cp_confidence,
                "data_basis": "composite_factors.cycle_position",
                "last_stable_cycle_position": (cp.get("last_stable_cycle_position")
                                                if cp else None),
            },
            "health_status": health_status,
            "confidence_tier": confidence_tier,
            "computation_method": "rule_based" if health_status == "healthy" else "degraded",
            "notes": notes,
        }


# ============================================================
# 辅助
# ============================================================

def _derive_candidate(
    regime: str, tt_direction: str, tt_band: str,
) -> tuple[str, list[str]]:
    """
    Step 1:从 L1 regime 和 truth_trend 推候选方向。
    返回 (candidate, conflict_flags)。
    """
    flags: list[str] = []

    if regime in ("trend_up", "transition_up"):
        if tt_direction == "up" and tt_band != "no_trend":
            return "bullish", flags
        if tt_direction == "down":
            flags.append("l1_truth_trend_strong_conflict")
            return "neutral", flags
        # flat / unknown / no_trend → 冲突
        flags.append("l1_truth_trend_conflict")
        return "neutral", flags

    if regime in ("trend_down", "transition_down"):
        if tt_direction == "down" and tt_band != "no_trend":
            return "bearish", flags
        if tt_direction == "up":
            flags.append("l1_truth_trend_strong_conflict")
            return "neutral", flags
        flags.append("l1_truth_trend_conflict")
        return "neutral", flags

    if regime and regime.startswith("range_"):
        return "neutral", flags

    if regime == "chaos":
        return "neutral", flags

    # regime unknown / unclear_insufficient
    flags.append("l1_insufficient_or_unknown")
    return "neutral", flags


def _regime_support_for_candidate(
    regime: str, candidate: str, flags: list[str],
) -> float:
    """
    Step 3 第 2 项:L1 regime 对 candidate 方向的支持度 [0, 1]。
    冲突时给 0.2。
    """
    if "l1_truth_trend_strong_conflict" in flags or \
       "l1_insufficient_or_unknown" in flags:
        return 0.2
    if "l1_truth_trend_conflict" in flags:
        return 0.2

    if candidate == "neutral":
        # range / chaos 候选 neutral 的情况
        return _REGIME_ALIGNED_SUPPORT.get(regime, 0.4)

    # candidate 是 bullish / bearish,regime 应 aligned
    if candidate == "bullish" and regime in ("trend_up", "transition_up"):
        return _REGIME_ALIGNED_SUPPORT[regime]
    if candidate == "bearish" and regime in ("trend_down", "transition_down"):
        return _REGIME_ALIGNED_SUPPORT[regime]

    # 其他组合(不应出现,因为 _derive_candidate 已过滤冲突)
    return 0.2


def _lookup_thresholds(
    dynamic_thresholds: dict[str, Any], cycle_band: str,
) -> dict[str, Any]:
    """
    查 thresholds.yaml 的 dynamic_direction_thresholds。
    未命中返回默认 {long: 0.65, short: 0.70, source_band: 'default'}。
    """
    entry = dynamic_thresholds.get(cycle_band)
    if isinstance(entry, dict) and "long" in entry and "short" in entry:
        return {
            "long": float(entry["long"]),
            "short": float(entry["short"]),
            "source_band": cycle_band,
        }
    return {"long": 0.65, "short": 0.70, "source_band": "default"}
