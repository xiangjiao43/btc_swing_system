"""
layer4_risk.py — L4 风险证据层(建模 §4.5 + §M17)

输出:
  * position_cap            该笔交易的仓位上限(绝对百分比,如 0.08 = 8% 净值)
  * position_cap_breakdown  base_cap 和每个衰减因子的审计
  * stop_loss_reference     建议止损价格 + 距离 + 方法(atr / swing / combined)
  * risk_reward_ratio       target1 / stop 的比值
  * rr_pass_level           full / reduced / fail
  * scale_in_plan           加仓分层(按 grade)
  * risk_permission         L3.execution_permission 与 L4 内部评估的 stricter merge

核心原则:
  1. L4 与 L3 串联取更严(L3=watch → L4 不能升到 can_open)
  2. position_cap 多因素乘法衰减,不加法
  3. stop_loss 必须有参考,否则 risk_permission=watch
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import pandas as pd

from ..indicators.structure import swing_points
from ..indicators.volatility import atr
from ..utils.permission import get_permission_order, merge_permissions
from ._base import EvidenceLayerBase


logger = logging.getLogger(__name__)


# ============================================================
# Layer4Risk
# ============================================================

class Layer4Risk(EvidenceLayerBase):
    layer_id = 4
    layer_name = "risk"
    thresholds_key = "layer_4_risk"

    def _compute_specific(self, context: dict[str, Any]) -> dict[str, Any]:
        l1: dict[str, Any] = context.get("layer_1_output") or {}
        l2: dict[str, Any] = context.get("layer_2_output") or {}
        l3: dict[str, Any] = context.get("layer_3_output") or {}
        composites: dict[str, Any] = context.get("composite_factors") or {}
        klines_1d: Optional[pd.DataFrame] = context.get("klines_1d")

        # ---- 读阈值 ----
        grade_to_base = self.scoring_config.get("grade_to_base_cap", {}) or {}
        decay = self.scoring_config.get("per_trade_decay", {}) or {}
        cap_min = float(self.scoring_config.get("position_cap_min", 0.015))
        stop_cfg = self.scoring_config.get("stop_loss", {}) or {}
        rr_cfg = self.scoring_config.get("risk_reward", {}) or {}
        scale_plans = self.scoring_config.get("scale_in_plans", {}) or {}
        strictness = get_permission_order()

        # ---- 基础字段提取 ----
        grade = l3.get("opportunity_grade", l3.get("grade", "none"))
        stance = l2.get("stance", "neutral")
        stance_confidence = float(l2.get("stance_confidence", 0.0))
        vol_regime = (
            l1.get("volatility_regime") or l1.get("volatility_level") or "normal"
        )
        l3_permission = l3.get("execution_permission", "watch")
        anti_patterns = l3.get("anti_pattern_flags") or []

        crowd_band = (composites.get("crowding") or {}).get("band", "normal")
        er_band = (composites.get("event_risk") or {}).get("band", "low")
        bp_phase = (composites.get("band_position") or {}).get("phase", "unclear")
        cold_start = context.get("cold_start") or {}
        is_cold = bool(cold_start.get("warming_up"))

        # ---- Step 1: 基础 cap ----
        base_cap = float(grade_to_base.get(grade, 0.0))

        # Grade=none 或 stance=neutral:cap=0 直接出口
        if grade == "none" or stance == "neutral" or base_cap <= 0:
            return self._emit_no_open(
                reason=(
                    f"grade={grade}, stance={stance} → no open"
                ),
                base_cap=base_cap,
                l3_permission=l3_permission,
                strictness=strictness,
                scale_plans=scale_plans,
                grade=grade,
            )

        # ---- Step 2: 逐项衰减因子(乘法累乘)----
        applied_factors: dict[str, float] = {}

        # crowding 衰减
        crowd_mul = float(
            (decay.get("crowding") or {}).get(crowd_band, 1.0)
        )
        applied_factors["crowding"] = crowd_mul

        # event_risk 衰减
        er_mul = float(
            (decay.get("event_risk") or {}).get(er_band, 1.0)
        )
        applied_factors["event_risk"] = er_mul

        # volatility 衰减
        vol_mul = float(
            (decay.get("volatility") or {}).get(vol_regime, 1.0)
        )
        applied_factors["volatility"] = vol_mul

        # stance_confidence 分档
        sc_mul = _resolve_stance_confidence_multiplier(
            stance_confidence, decay.get("stance_confidence") or []
        )
        applied_factors["stance_confidence"] = sc_mul

        # anti_pattern_count 衰减
        ap_count = len(anti_patterns)
        ap_cfg = decay.get("anti_pattern_count") or {}
        if ap_count == 0:
            ap_mul = float(ap_cfg.get("zero", 1.0))
        elif ap_count == 1:
            ap_mul = float(ap_cfg.get("one", 0.85))
        else:
            ap_mul = float(ap_cfg.get("two_or_more", 0.70))
        applied_factors["anti_pattern_count"] = ap_mul

        # 冷启动
        if is_cold:
            cold_mul = float(decay.get("cold_start_multiplier", 0.5))
        else:
            cold_mul = 1.0
        applied_factors["cold_start"] = cold_mul

        raw_cap_before_clamp = base_cap
        for mul in applied_factors.values():
            raw_cap_before_clamp *= mul

        # ---- Step 3: clamp 到 grade ceiling + 最小保护 ----
        # stance_confidence 1.05 加成让 raw 可能超过 base;clamp 回 base
        clamped_to_ceiling = raw_cap_before_clamp > base_cap
        after_ceiling = min(raw_cap_before_clamp, base_cap)

        if after_ceiling < cap_min:
            final_cap = 0.0
            cap_min_hit = True
        else:
            final_cap = after_ceiling
            cap_min_hit = False

        # ---- Step 4: Stop Loss 计算 ----
        stop_loss_ref = _compute_stop_loss(
            klines_1d, stance, vol_regime, stop_cfg,
        )

        # ---- Step 5: Risk-Reward Ratio ----
        rr_result = _compute_rr(
            klines_1d, stance, stop_loss_ref, composites,
            rr_cfg,
        )
        # rr_result: {"ratio": float|None, "target1_pct": float|None,
        #             "target_source": str, "pass_level": "full"|"reduced"|"fail"}

        # RR 修正:reduced 档额外 cap × 0.8
        if rr_result["pass_level"] == "reduced":
            final_cap *= float(rr_cfg.get("reduced_cap_multiplier", 0.8))

        # RR fail 或 stop 缺失 → permission 强制 watch + cap 清零
        if rr_result["pass_level"] == "fail" or stop_loss_ref is None:
            final_cap = 0.0

        # ---- Step 6: Scale-In Plan ----
        plan_key = grade
        if is_cold:
            # 冷启动期强制 1 层
            scale_in_plan = {
                "layers": 1,
                "allocations": [1.0],
                "trigger_conditions": ["冷启动期:不加仓,仅初始进场"],
            }
        else:
            plan_cfg = scale_plans.get(plan_key, scale_plans.get("none", {}))
            scale_in_plan = {
                "layers": int(plan_cfg.get("layers", 0)),
                "allocations": list(plan_cfg.get("allocations") or []),
                "trigger_conditions": list(plan_cfg.get("trigger_conditions") or []),
            }

        # ---- Step 7: Permission 合并 ----
        # L4 内部 permission 规则
        l4_internal_permission = _l4_internal_permission(
            final_cap, stop_loss_ref, rr_result
        )

        risk_permission = merge_permissions(l3_permission, l4_internal_permission)

        rationale_parts = [f"L3 gave {l3_permission}"]
        if l4_internal_permission != l3_permission:
            rationale_parts.append(f"L4 internal={l4_internal_permission}")
        if risk_permission != l3_permission:
            rationale_parts.append(f"merged stricter → {risk_permission}")
        rationale = " | ".join(rationale_parts)

        # ---- 组装输出 ----
        notes: list[str] = []
        if cap_min_hit:
            notes.append(f"final cap {after_ceiling:.4f} < min {cap_min} → cap=0")
        if stop_loss_ref is None:
            notes.append("stop_loss unavailable → risk_permission=watch")
        if rr_result["pass_level"] == "fail":
            notes.append(f"RR {rr_result.get('ratio')} < 1.5 → cap=0 + watch")
        if is_cold:
            notes.append("cold_start: cap × 0.5 and scale-in forced to 1 layer")
        if risk_permission in ("hold_only", "watch", "protective") and final_cap > 0:
            notes.append(
                f"permission={risk_permission} blocks new opens despite cap={final_cap:.4f}"
            )

        diagnostics = {
            "inputs": {
                "grade": grade,
                "stance": stance,
                "stance_confidence": stance_confidence,
                "vol_regime": vol_regime,
                "crowd_band": crowd_band,
                "event_risk_band": er_band,
                "bp_phase": bp_phase,
                "anti_patterns": anti_patterns,
                "l3_permission": l3_permission,
                "cold_start": is_cold,
            },
            "cap_chain": {
                "base": base_cap,
                "factors": {k: round(v, 4) for k, v in applied_factors.items()},
                "raw_product": round(raw_cap_before_clamp, 5),
                "after_ceiling_clamp": round(after_ceiling, 5),
                "min_hit": cap_min_hit,
                "final": round(final_cap, 5),
            },
            "stop_loss_details": stop_loss_ref,
            "rr_details": rr_result,
            "permission_strictness_used": strictness,
        }

        return {
            "position_cap": round(final_cap, 5),
            "position_cap_breakdown": {
                "base_cap_from_grade": base_cap,
                "applied_factors": {k: round(v, 4) for k, v in applied_factors.items()},
                "raw_cap_before_clamp": round(raw_cap_before_clamp, 5),
                "clamped_to_grade_ceiling": clamped_to_ceiling,
                "min_floor_applied": cap_min_hit,
            },
            "stop_loss_reference": stop_loss_ref,
            "risk_reward_ratio": rr_result.get("ratio"),
            "rr_pass_level": rr_result.get("pass_level"),
            "scale_in_plan": scale_in_plan,
            "risk_permission": risk_permission,
            "risk_permission_rationale": rationale,
            "diagnostics": diagnostics,
            "notes": notes,
            "health_status": "healthy",
            "confidence_tier": _grade_to_tier(grade),
            "computation_method": "rule_based",
        }

    def _emit_no_open(
        self, *, reason: str, base_cap: float, l3_permission: str,
        strictness: list[str], scale_plans: dict, grade: str,
    ) -> dict[str, Any]:
        """grade=none / stance=neutral 的统一出口。"""
        risk_permission = merge_permissions(l3_permission, "watch")
        return {
            "position_cap": 0.0,
            "position_cap_breakdown": {
                "base_cap_from_grade": base_cap,
                "applied_factors": {},
                "raw_cap_before_clamp": 0.0,
                "clamped_to_grade_ceiling": False,
                "min_floor_applied": False,
            },
            "stop_loss_reference": None,
            "risk_reward_ratio": None,
            "rr_pass_level": "n_a",
            "scale_in_plan": {
                "layers": 0, "allocations": [], "trigger_conditions": [],
            },
            "risk_permission": risk_permission,
            "risk_permission_rationale": f"no-open: {reason}",
            "diagnostics": {"early_exit_reason": reason, "grade": grade},
            "notes": [reason],
            "health_status": "healthy",
            "confidence_tier": "very_low",
            "computation_method": "rule_based",
        }


# ============================================================
# 辅助:stance_confidence 分档
# ============================================================

def _resolve_stance_confidence_multiplier(
    stance_confidence: float, tiers: list[dict[str, Any]],
) -> float:
    """按 tiers 列表(有序,min 高到低)查找命中 tier。"""
    if not tiers:
        return 1.0
    # 按 min 降序匹配(首个 stance_confidence >= min 命中)
    sorted_tiers = sorted(tiers, key=lambda t: float(t.get("min", 0)), reverse=True)
    for tier in sorted_tiers:
        if stance_confidence >= float(tier.get("min", 0)):
            return float(tier.get("multiplier", 1.0))
    return 1.0


# ============================================================
# 辅助:Stop Loss 计算
# ============================================================

def _compute_stop_loss(
    klines_1d: Optional[pd.DataFrame],
    stance: str, vol_regime: str,
    stop_cfg: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """
    返回 {price, distance_pct, method_used, atr_stop, swing_stop} 或 None。
    method_used ∈ {atr, swing, combined}。
    """
    if klines_1d is None or not isinstance(klines_1d, pd.DataFrame) \
            or len(klines_1d) < 20:
        return None

    current = float(klines_1d["close"].iloc[-1])
    if current <= 0:
        return None

    # ---- ATR 逻辑 ----
    atr_series = atr(
        klines_1d["high"], klines_1d["low"], klines_1d["close"], period=14
    )
    atr_val = atr_series.dropna().iloc[-1] if not atr_series.dropna().empty else None

    atr_mul_cfg = stop_cfg.get("atr_multipliers") or {}
    atr_mul = float(atr_mul_cfg.get(vol_regime, 2.0))

    atr_stop_price: Optional[float] = None
    if atr_val is not None and atr_val > 0:
        if stance == "bullish":
            atr_stop_price = current - atr_mul * float(atr_val)
        elif stance == "bearish":
            atr_stop_price = current + atr_mul * float(atr_val)

    # ---- Swing 逻辑 ----
    swing_stop_price: Optional[float] = None
    buffer_pct = float(stop_cfg.get("swing_buffer_pct", 0.015))
    swing_max_dist = float(stop_cfg.get("swing_max_distance_pct", 0.10))

    # 最近 60 根做 swing 分析
    recent = klines_1d.tail(60)
    events = swing_points(recent["high"], recent["low"], lookback=5)

    if stance == "bullish":
        # 从最近的 swing_low 中找离现价最近的
        lows = [e["price"] for e in events if e["type"] == "low"]
        # 取最近 3 个
        lows = lows[-3:] if len(lows) >= 3 else lows
        valid_lows = [p for p in lows if 0 < p < current]
        if valid_lows:
            best = max(valid_lows)  # 离现价最近的低点(最高的低点)
            dist = (current - best) / current
            if dist <= swing_max_dist:
                swing_stop_price = best * (1 - buffer_pct)
    elif stance == "bearish":
        highs = [e["price"] for e in events if e["type"] == "high"]
        highs = highs[-3:] if len(highs) >= 3 else highs
        valid_highs = [p for p in highs if p > current > 0]
        if valid_highs:
            best = min(valid_highs)  # 离现价最近的高点(最低的高点)
            dist = (best - current) / current
            if dist <= swing_max_dist:
                swing_stop_price = best * (1 + buffer_pct)

    # ---- 合并:取"止损更近"者 ----
    if atr_stop_price is None and swing_stop_price is None:
        return None

    if stance == "bullish":
        # 止损更近 = stop 价格更高(离现价更近的下方)
        if atr_stop_price is not None and swing_stop_price is not None:
            chosen_price = max(atr_stop_price, swing_stop_price)
            method = "combined"
        elif atr_stop_price is not None:
            chosen_price = atr_stop_price
            method = "atr"
        else:
            chosen_price = swing_stop_price  # type: ignore[assignment]
            method = "swing"
        distance_pct = (current - chosen_price) / current
    elif stance == "bearish":
        if atr_stop_price is not None and swing_stop_price is not None:
            chosen_price = min(atr_stop_price, swing_stop_price)
            method = "combined"
        elif atr_stop_price is not None:
            chosen_price = atr_stop_price
            method = "atr"
        else:
            chosen_price = swing_stop_price  # type: ignore[assignment]
            method = "swing"
        distance_pct = (chosen_price - current) / current
    else:
        return None

    # 止损距离必须 > 0(否则表示入场即打止损)
    if distance_pct <= 0:
        return None

    return {
        "price": round(float(chosen_price), 4),
        "distance_pct": round(float(distance_pct), 5),
        "method_used": method,
        "atr_stop": (round(float(atr_stop_price), 4)
                     if atr_stop_price is not None else None),
        "swing_stop": (round(float(swing_stop_price), 4)
                       if swing_stop_price is not None else None),
        "atr_multiplier_used": atr_mul,
    }


# ============================================================
# 辅助:Risk-Reward
# ============================================================

def _compute_rr(
    klines_1d: Optional[pd.DataFrame],
    stance: str,
    stop_loss_ref: Optional[dict[str, Any]],
    composites: dict[str, Any],
    rr_cfg: dict[str, Any],
) -> dict[str, Any]:
    """
    返回 {ratio, target1_pct, target_source, pass_level}。
    stop 缺失 → fail。
    """
    full_th = float(rr_cfg.get("full_threshold", 2.0))
    reduced_th = float(rr_cfg.get("reduced_threshold", 1.5))
    fallback_atr_mul = float(rr_cfg.get("fallback_target_atr_multiplier", 3.0))

    if stop_loss_ref is None or klines_1d is None:
        return {"ratio": None, "target1_pct": None,
                "target_source": "n_a", "pass_level": "fail"}

    stop_dist = float(stop_loss_ref.get("distance_pct", 0))
    if stop_dist <= 0:
        return {"ratio": None, "target1_pct": None,
                "target_source": "n_a", "pass_level": "fail"}

    current = float(klines_1d["close"].iloc[-1])
    target1_pct: Optional[float] = None
    source = "unknown"

    # 优先:swing 结构给目标
    recent = klines_1d.tail(60)
    events = swing_points(recent["high"], recent["low"], lookback=5)

    if stance == "bullish":
        highs = [e["price"] for e in events if e["type"] == "high"]
        # 取高于现价的最低 swing_high
        above = [p for p in highs if p > current]
        if above:
            target1_pct = (min(above) - current) / current
            source = "swing_high"
    elif stance == "bearish":
        lows = [e["price"] for e in events if e["type"] == "low"]
        below = [p for p in lows if 0 < p < current]
        if below:
            target1_pct = (current - max(below)) / current
            source = "swing_low"

    # 回退:ATR × multiplier
    if target1_pct is None or target1_pct <= 0:
        atr_series = atr(
            klines_1d["high"], klines_1d["low"], klines_1d["close"], period=14
        )
        atr_val = atr_series.dropna().iloc[-1] if not atr_series.dropna().empty else None
        if atr_val is not None and atr_val > 0 and current > 0:
            target1_pct = float(atr_val) * fallback_atr_mul / current
            source = "atr_fallback"
        else:
            return {"ratio": None, "target1_pct": None,
                    "target_source": "no_target", "pass_level": "fail"}

    ratio = target1_pct / stop_dist if stop_dist > 0 else None

    if ratio is None:
        pass_level = "fail"
    elif ratio >= full_th:
        pass_level = "full"
    elif ratio >= reduced_th:
        pass_level = "reduced"
    else:
        pass_level = "fail"

    return {
        "ratio": round(float(ratio), 3) if ratio is not None else None,
        "target1_pct": round(float(target1_pct), 5),
        "stop_distance_pct": round(stop_dist, 5),
        "target_source": source,
        "pass_level": pass_level,
    }


# ============================================================
# 辅助:Permission 合并(Sprint 1.11 统一使用 src.utils.permission)
# ============================================================

def _l4_internal_permission(
    final_cap: float,
    stop_loss_ref: Optional[dict[str, Any]],
    rr_result: dict[str, Any],
) -> str:
    """L4 内部根据 cap / stop / RR 计算 permission。"""
    if final_cap <= 0:
        return "watch"
    if stop_loss_ref is None:
        return "watch"
    pass_level = rr_result.get("pass_level")
    if pass_level == "fail":
        return "watch"
    if pass_level == "reduced":
        return "cautious_open"
    # full pass + 有 cap + 有 stop → L4 不额外收紧,保留 L3
    return "can_open"  # 最宽松档(实际会被 L3 限制)


def _grade_to_tier(grade: str) -> str:
    return {
        "A": "high", "B": "medium", "C": "low", "none": "very_low",
    }.get(grade, "very_low")
