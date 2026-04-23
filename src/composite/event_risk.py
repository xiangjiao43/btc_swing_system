"""
event_risk.py — EventRisk 组合因子(建模 §3.8.6)

评分规则(thresholds.yaml event_risk_scoring):
  event_type_weights:  fomc=4 / cpi=3 / nfp=3 / options_expiry_major=2 / other=1
  distance_multipliers(hours_to_event):
    [0, 24]   × 1.5
    [24, 48]  × 1.0
    [48, 72]  × 0.5
  volatility_extreme_bonus:  当前波动率 extreme 时所有事件 +1
  us_macro_bonus_when_correlated:  BTC-纳指相关性 > 0.7 时 US 宏观事件 +1

output(对齐 schemas.yaml event_risk_output):
  score, band, position_cap_multiplier, permission_adjustment, contributing_events
  + upcoming_events(事件清单的数量)
"""

from __future__ import annotations

from typing import Any, Optional

from ._base import CompositeFactorBase, reduce_metadata


# 被视为"美国宏观事件"的 event_type 集合(相关性加权目标)
_US_MACRO_TYPES: set[str] = {"fomc", "cpi", "nfp"}


class EventRiskFactor(CompositeFactorBase):
    name = "event_risk"
    thresholds_key = "event_risk_scoring"

    def compute(self, context: dict[str, Any]) -> dict[str, Any]:
        events: list[dict[str, Any]] = context.get("events_upcoming_48h") or []

        weights_cfg = self.scoring_config.get("event_type_weights") or {}
        distance_cfg = self.scoring_config.get("distance_multipliers") or []
        vol_bonus = float(self.scoring_config.get("volatility_extreme_bonus", 0))
        us_corr_bonus = float(self.scoring_config.get("us_macro_bonus_when_correlated", 0))
        bands = self.scoring_config.get("output_bands") or {}

        # 上下文信息:波动率是否 extreme(由 L1 传入或用户 context 注入)
        is_vol_extreme: bool = bool(context.get("is_volatility_extreme", False))
        # 相关性是否 > 0.7(由 MacroHeadwind 先跑或调用方注入)
        btc_nasdaq_correlated: bool = bool(context.get("btc_nasdaq_correlated", False))

        contributing: list[dict[str, Any]] = []
        total_score = 0.0

        for ev in events:
            event_type_raw = (ev.get("event_type") or "other").lower()
            base_weight = float(weights_cfg.get(event_type_raw, weights_cfg.get("other", 1)))

            hours_to = ev.get("hours_to", ev.get("hours_to_event"))
            if hours_to is None:
                # 无距离信息则按中档 1.0
                distance_mult = 1.0
            else:
                distance_mult = _distance_multiplier(float(hours_to), distance_cfg)

            # 基础 + 加权
            event_score = base_weight * distance_mult

            # 波动率加成
            if is_vol_extreme:
                event_score += vol_bonus

            # 美国宏观事件 + 相关性强:额外加 +1
            if btc_nasdaq_correlated and event_type_raw in _US_MACRO_TYPES:
                event_score += us_corr_bonus

            total_score += event_score
            contributing.append({
                "name": ev.get("name", "unknown"),
                "type": event_type_raw,
                "hours_to": hours_to,
                "base_weight": base_weight,
                "distance_multiplier": distance_mult,
                "vol_bonus_applied": is_vol_extreme,
                "us_corr_bonus_applied": (
                    btc_nasdaq_correlated and event_type_raw in _US_MACRO_TYPES
                ),
                "effective_score": round(event_score, 3),
            })

        # ---- 输出 band ----
        high_th = float(bands.get("high_at_or_above", 8))
        medium_th = float(bands.get("medium_at_or_above", 4))

        permission_adjustment: Optional[str] = None
        if total_score >= high_th:
            band = "high"
            cap_multiplier = 0.7
            permission_adjustment = "ambush_only"
        elif total_score >= medium_th:
            band = "medium"
            cap_multiplier = 0.85
        else:
            band = "low"
            cap_multiplier = 1.0

        return {
            "factor": self.name,
            "score": round(total_score, 3),
            "band": band,
            "position_cap_multiplier": cap_multiplier,
            "permission_adjustment": permission_adjustment,
            "contributing_events": contributing,
            "upcoming_events_count": len(events),
            **reduce_metadata(
                health_status="healthy" if events else "healthy",  # 空也不是错
                notes=(
                    ["no events in 72h window"] if not events else []
                ),
            ),
        }


# ============================================================
# 辅助
# ============================================================

def _distance_multiplier(hours_to: float, distance_cfg: list[dict[str, Any]]) -> float:
    """
    hours_to ∈ [lo, hi] 查 multiplier;超出最大 hi 返回 0(事件已过 72h,不贡献)。
    """
    if hours_to < 0:
        # 事件已发生:按 0h 处理
        hours_to = 0.0
    for row in distance_cfg:
        lo, hi = row.get("hours_range", [0, 999])
        if lo <= hours_to <= hi:
            return float(row.get("multiplier", 1.0))
    return 0.0  # 超出 72h 窗口
