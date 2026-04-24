"""
layer4_risk.py — L4 风险证据层(建模 §4.5)

Sprint 1.5b 重写:按建模 §4.5.5 五步串行合成 position_cap + §4.5.6
execution_permission 归并(含 A 级缓冲 + 4 例外)。
Sprint 1.10 的"grade_to_base_cap + per_trade_decay 多因素衰减"作废。

输出字段(§4.5.7):
  * overall_risk_level        low / moderate / elevated / high / critical
  * position_cap              最终仓位上限(分数,0.0-1.0)
  * position_cap_composition  5 步审计
  * execution_permission      归并后的最终权限(保留字段名 risk_permission 兼容)
  * permission_composition    各来源建议 + 归并过程审计
  * stop_loss_reference       Sprint 1.10 逻辑保留(供 trade_plan 参考)
  * risk_reward_ratio / rr_pass_level
  * scale_in_plan             分层加仓计划(按 grade)
  * hard_invalidation_levels  §4.5.4 唯一权威(Sprint 1.5b v1:暂等于 stop_loss_reference 升格)

核心纪律:
  1. observation_category 只读,不进本层任何判定
  2. hard_floor 15% 仅在 final_permission ∈ {can_open, cautious_open, ambush_only}
     时生效,critical 时可低于 15%
  3. A 级缓冲 4 例外:PROTECTION / extreme_event / critical / chaos 硬压
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import pandas as pd

from ..indicators.structure import swing_points
from ..indicators.volatility import atr
from ..utils.permission import merge_permissions
from ._base import EvidenceLayerBase


logger = logging.getLogger(__name__)


# ============================================================
# 5 步合成:默认阈值(可被 thresholds.yaml 覆盖)
# ============================================================

_DEFAULT_BASE_CAP_PCT: float = 70.0   # §4.5.8 初始值
_DEFAULT_HARD_FLOOR_PCT: float = 15.0

# step 2:L4.overall_risk_level → cap 乘数
_RISK_LEVEL_MULTIPLIERS: dict[str, float] = {
    "low": 1.0, "moderate": 0.9, "elevated": 0.7, "high": 0.5, "critical": 0.3,
}

# step 2:L4.overall_risk_level → permission 建议
_RISK_LEVEL_PERMISSION: dict[str, str] = {
    "low": "can_open", "moderate": "cautious_open", "elevated": "ambush_only",
    "high": "watch", "critical": "protective",
}

# step 3:L4.crowding score 区间 → cap 乘数(score 0-8)
_CROWDING_BANDS: list[tuple[tuple[int, int], float]] = [
    ((6, 99), 0.70),
    ((4, 5),  0.85),
    ((0, 3),  1.00),
]

# step 3:crowding 建议
_CROWDING_PERMISSION_BANDS: list[tuple[tuple[int, int], str]] = [
    ((6, 99), "cautious_open"),
    ((0, 5),  "can_open"),
]

# step 4:L5.MacroHeadwind score 区间(-10..+10)→ cap 乘数
_MACRO_BANDS: list[tuple[tuple[int, int], float]] = [
    ((-99, -5), 0.70),
    ((-4, -2),  0.85),
    ((-1, 99),  1.00),
]

_MACRO_PERMISSION_BANDS: list[tuple[tuple[int, int], str]] = [
    ((-99, -5), "ambush_only"),
    ((-4, -2),  "cautious_open"),
    ((-1, 99),  "can_open"),
]

# step 5:L4.EventRisk score 区间(0-15+)→ cap 乘数
_EVENT_BANDS: list[tuple[tuple[int, int], float]] = [
    ((8, 999), 0.70),
    ((4, 7),   0.85),
    ((0, 3),   1.00),
]

_EVENT_PERMISSION_BANDS: list[tuple[tuple[int, int], str]] = [
    ((8, 999), "ambush_only"),
    ((4, 7),   "cautious_open"),
    ((0, 3),   "can_open"),
]

# A 级缓冲的下限
_A_GRADE_BUFFER_FLOOR: str = "cautious_open"
_A_GRADE_REGIME_STABLE: frozenset[str] = frozenset({"trend_up", "trend_down"})
_A_GRADE_STABILITY_OK: frozenset[str] = frozenset({"stable", "slightly_shifting"})


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
        l5: dict[str, Any] = context.get("layer_5_output") or {}
        composites: dict[str, Any] = context.get("composite_factors") or {}
        klines_1d: Optional[pd.DataFrame] = context.get("klines_1d")

        cap_cfg = self.scoring_config.get("position_cap_composition") or {}
        base_cap_pct = float(cap_cfg.get("base_position_cap_pct", _DEFAULT_BASE_CAP_PCT))
        hard_floor_pct = float(cap_cfg.get("hard_floor_pct", _DEFAULT_HARD_FLOOR_PCT))

        stop_cfg = self.scoring_config.get("stop_loss", {}) or {}
        rr_cfg = self.scoring_config.get("risk_reward", {}) or {}
        scale_plans = self.scoring_config.get("scale_in_plans", {}) or {}

        # -------- 基础字段 --------
        grade = l3.get("opportunity_grade") or l3.get("grade") or "none"
        stance = l2.get("stance", "neutral")
        l3_permission = l3.get("execution_permission", "watch")
        regime = l1.get("regime") or l1.get("regime_primary") or "unclear"
        regime_stability = l1.get("regime_stability") or "stable"
        vol_regime = (
            l1.get("volatility_regime") or l1.get("volatility_level") or "normal"
        )
        l5_extreme = bool(l5.get("extreme_event_detected", False))
        # Sprint 1.5c C1:从上次运行的 state_machine.current_state 读"前一次态"
        # (近似当前态;首次运行/冷启动默认 FLAT)。Adjudicator 再做一次前置拦截作为双保险。
        state_machine_state = (
            context.get("previous_state_machine_state")
            or context.get("state_machine_hint")
            or (context.get("state_machine_output") or {}).get("current_state")
            or "FLAT"
        )

        # -------- composite 分数(§4.5.5 / §4.5.6 的原料)--------
        crowding = composites.get("crowding") or {}
        event_risk = composites.get("event_risk") or {}
        macro_headwind = composites.get("macro_headwind") or {}

        crowding_score = _safe_int(crowding.get("score"))
        event_risk_score = _safe_number(event_risk.get("score"))
        macro_headwind_score = _safe_number(macro_headwind.get("score"))

        # -------- §4.5.7 overall_risk_level(规则层派生)--------
        overall_risk_level = _derive_overall_risk_level(
            vol_regime=vol_regime,
            crowding_score=crowding_score,
            event_risk_score=event_risk_score,
            macro_headwind_score=macro_headwind_score,
            l5_extreme=l5_extreme,
        )

        # -------- §4.5.5 Position Cap 5 步串行合成 --------
        (
            final_cap_pct, cap_composition,
        ) = _compose_position_cap(
            base_pct=base_cap_pct,
            overall_risk_level=overall_risk_level,
            crowding_score=crowding_score,
            macro_headwind_score=macro_headwind_score,
            event_risk_score=event_risk_score,
            hard_floor_pct=hard_floor_pct,
        )

        # -------- §4.5.6 Permission 归并 --------
        (
            final_permission, permission_composition,
        ) = _merge_permissions(
            overall_risk_level=overall_risk_level,
            crowding_score=crowding_score,
            event_risk_score=event_risk_score,
            macro_headwind_score=macro_headwind_score,
            grade=grade,
            regime=regime,
            regime_stability=regime_stability,
            l1_regime_chaos=(regime == "chaos"),
            l5_extreme=l5_extreme,
            state_machine_state=state_machine_state,
            l3_permission=l3_permission,
        )

        # -------- 硬下限 15% 的适用性(建模 §4.5.5 问题 4)--------
        final_cap_pct, cap_composition = _apply_floor_gate(
            cap_pct=final_cap_pct,
            composition=cap_composition,
            final_permission=final_permission,
            overall_risk_level=overall_risk_level,
            hard_floor_pct=hard_floor_pct,
        )
        final_cap = round(final_cap_pct / 100.0, 5)

        # -------- Stop Loss + hard_invalidation_levels(§4.5.4)--------
        stop_loss_ref: Optional[dict[str, Any]] = None
        if stance in {"bullish", "bearish"}:
            stop_loss_ref = _compute_stop_loss(
                klines_1d, stance, vol_regime, stop_cfg,
            )
        # Sprint 1.5c C2:§4.5.2 角度一(结构性失效位)+ stop_loss 兜底合并成 list
        hard_invalidation_levels = _build_hard_invalidation_levels(
            klines_1d=klines_1d,
            stop_loss_ref=stop_loss_ref,
            stance=stance,
        )

        # -------- Risk-Reward --------
        rr_result = _compute_rr(
            klines_1d, stance, stop_loss_ref, composites, rr_cfg,
        )

        # -------- Scale-in plan(Sprint 1.10 沿用,按 grade + cold_start)--------
        cold_start = context.get("cold_start") or {}
        is_cold = bool(cold_start.get("warming_up"))
        if is_cold:
            scale_in_plan = {
                "layers": 1, "allocations": [1.0],
                "trigger_conditions": ["冷启动期:不加仓,仅初始进场"],
            }
        else:
            plan_cfg = scale_plans.get(grade, scale_plans.get("none", {}))
            scale_in_plan = {
                "layers": int(plan_cfg.get("layers", 0)),
                "allocations": list(plan_cfg.get("allocations") or []),
                "trigger_conditions": list(plan_cfg.get("trigger_conditions") or []),
            }

        # -------- notes --------
        notes: list[str] = []
        if overall_risk_level == "critical":
            notes.append("overall_risk_level=critical: 允许 final_cap 低于 15% 硬下限")
        if cap_composition.get("hard_floor_applied_to_final"):
            notes.append(
                f"final_cap < hard_floor({hard_floor_pct}%) 且 "
                f"permission={final_permission},已抬升到 hard_floor"
            )
        if permission_composition.get("a_grade_buffer_applied"):
            notes.append("A 级缓冲激活:final_permission 不得严于 cautious_open")
        if permission_composition.get("override_reason"):
            notes.append(
                f"A 级缓冲被例外覆盖:{permission_composition['override_reason']}"
            )
        if stop_loss_ref is None and stance in {"bullish", "bearish"}:
            notes.append("stop_loss 不可用 → 慎重开仓")

        # -------- 回传 L3 merge(保守)--------
        risk_permission = merge_permissions(l3_permission, final_permission)
        rationale = (
            f"L3={l3_permission} | L4 merged={final_permission} | "
            f"final(stricter)={risk_permission}"
        )

        diagnostics = {
            "inputs": {
                "grade": grade, "stance": stance, "regime": regime,
                "regime_stability": regime_stability,
                "volatility_regime": vol_regime,
                "l3_permission": l3_permission,
                "crowding_score": crowding_score,
                "event_risk_score": event_risk_score,
                "macro_headwind_score": macro_headwind_score,
                "l5_extreme_event_detected": l5_extreme,
                "state_machine_state": state_machine_state,
            },
            "overall_risk_level": overall_risk_level,
            "cap_5_step_composition": cap_composition,
            "permission_composition": permission_composition,
            "stop_loss_details": stop_loss_ref,
            "rr_details": rr_result,
        }

        return {
            "overall_risk_level": overall_risk_level,
            "position_cap": final_cap,
            "position_cap_composition": cap_composition,
            "permission_composition": permission_composition,
            "execution_permission": final_permission,
            "risk_permission": risk_permission,          # 向后兼容
            "risk_permission_rationale": rationale,
            "hard_invalidation_levels": hard_invalidation_levels,
            "stop_loss_reference": stop_loss_ref,
            "risk_reward_ratio": rr_result.get("ratio"),
            "rr_pass_level": rr_result.get("pass_level"),
            "scale_in_plan": scale_in_plan,
            "notes": notes,
            "health_status": "healthy",
            "confidence_tier": _grade_to_tier(grade),
            "computation_method": "rule_based",
            "diagnostics": diagnostics,
        }


# ============================================================
# §4.5.7 overall_risk_level 规则
# ============================================================

def _derive_overall_risk_level(
    *,
    vol_regime: str,
    crowding_score: Optional[int],
    event_risk_score: Optional[float],
    macro_headwind_score: Optional[float],
    l5_extreme: bool,
) -> str:
    """按最严档归档(critical > high > elevated > moderate > low)。"""
    if l5_extreme:
        return "critical"

    # 按单因子严重度评估,取最严
    levels: list[str] = []

    # volatility_regime
    if vol_regime == "extreme":
        levels.append("high")
    elif vol_regime == "elevated":
        levels.append("elevated")
    else:
        levels.append("low")

    # crowding
    if crowding_score is not None:
        if crowding_score >= 7:
            levels.append("high")
        elif crowding_score >= 5:
            levels.append("elevated")
        elif crowding_score >= 3:
            levels.append("moderate")
        else:
            levels.append("low")

    # event_risk
    if event_risk_score is not None:
        if event_risk_score >= 10:
            levels.append("high")
        elif event_risk_score >= 6:
            levels.append("elevated")
        elif event_risk_score >= 3:
            levels.append("moderate")
        else:
            levels.append("low")

    # macro_headwind(负值越深越严)
    if macro_headwind_score is not None:
        if macro_headwind_score <= -6:
            levels.append("high")
        elif macro_headwind_score <= -3:
            levels.append("elevated")
        elif macro_headwind_score <= -1:
            levels.append("moderate")
        else:
            levels.append("low")

    severity = ["low", "moderate", "elevated", "high", "critical"]
    picked = max(levels, key=lambda x: severity.index(x)) if levels else "moderate"
    return picked


# ============================================================
# §4.5.5 Position Cap 5 步合成
# ============================================================

def _compose_position_cap(
    *,
    base_pct: float,
    overall_risk_level: str,
    crowding_score: Optional[int],
    macro_headwind_score: Optional[float],
    event_risk_score: Optional[float],
    hard_floor_pct: float,
) -> tuple[float, dict[str, Any]]:
    """
    建模 §4.5.5 的 5 步串行合成,返回 (final_pct, composition dict)。
    最终 floor 在 _apply_floor_gate 中处理(依赖 final_permission)。
    """
    comp: dict[str, Any] = {"base": round(base_pct, 4)}

    # step 2: × L4_overall_risk_level
    mult_risk = _RISK_LEVEL_MULTIPLIERS.get(overall_risk_level, 1.0)
    after_l4_risk = base_pct * mult_risk
    comp["after_l4_risk"] = round(after_l4_risk, 4)
    comp["l4_risk_multiplier"] = mult_risk

    # step 3: × L4_crowding
    mult_crowd = _score_to_multiplier(crowding_score, _CROWDING_BANDS, default=1.0)
    after_l4_crowding = after_l4_risk * mult_crowd
    comp["after_l4_crowding"] = round(after_l4_crowding, 4)
    comp["l4_crowding_multiplier"] = mult_crowd

    # step 4: × L5_macro_headwind
    mult_macro = _score_to_multiplier(
        macro_headwind_score, _MACRO_BANDS, default=1.0,
    )
    after_l5_macro = after_l4_crowding * mult_macro
    comp["after_l5_macro"] = round(after_l5_macro, 4)
    comp["l5_macro_headwind_multiplier"] = mult_macro

    # step 5: × L4_event_risk
    mult_event = _score_to_multiplier(event_risk_score, _EVENT_BANDS, default=1.0)
    after_l4_event = after_l5_macro * mult_event
    comp["after_l4_event"] = round(after_l4_event, 4)
    comp["l4_event_risk_multiplier"] = mult_event

    comp["hard_floor_pct"] = hard_floor_pct
    comp["hard_floor_applied_to_final"] = False  # 由 _apply_floor_gate 置位
    comp["final_before_floor_gate"] = round(after_l4_event, 4)
    comp["final"] = round(after_l4_event, 4)  # 会被 _apply_floor_gate 更新

    return after_l4_event, comp


def _apply_floor_gate(
    *,
    cap_pct: float,
    composition: dict[str, Any],
    final_permission: str,
    overall_risk_level: str,
    hard_floor_pct: float,
) -> tuple[float, dict[str, Any]]:
    """
    §4.5.5 问题 4:
      * permission ∈ {can_open, cautious_open, ambush_only} → hard_floor 生效
      * permission = no_chase → 保留计算值(不抬升)
      * permission = hold_only → 仅约束新开仓,对已持仓无约束(此处保留计算值)
      * permission ∈ {watch, protective} → 不抬升
      * overall_risk_level = critical → 不抬升(允许 < 15% 甚至 0)
    """
    final = cap_pct
    floor_applies = (
        overall_risk_level != "critical"
        and final_permission in {"can_open", "cautious_open", "ambush_only"}
    )
    if floor_applies and final < hard_floor_pct:
        final = hard_floor_pct
        composition["hard_floor_applied_to_final"] = True
    composition["final"] = round(final, 4)
    composition["final_permission_at_floor_eval"] = final_permission
    return final, composition


# ============================================================
# §4.5.6 Permission 归并 + A 级缓冲
# ============================================================

def _merge_permissions(
    *,
    overall_risk_level: str,
    crowding_score: Optional[int],
    event_risk_score: Optional[float],
    macro_headwind_score: Optional[float],
    grade: str,
    regime: str,
    regime_stability: str,
    l1_regime_chaos: bool,
    l5_extreme: bool,
    state_machine_state: Optional[str],
    l3_permission: str,
) -> tuple[str, dict[str, Any]]:
    """
    每个因子产出建议档位,final_permission = 所有建议中的最严档位。
    再依次应用 A 级缓冲 + 4 例外(§4.5.6 问题 3)。
    """
    suggestions: dict[str, str] = {}

    # L4 overall_risk_level 建议
    suggestions["l4_risk_level"] = _RISK_LEVEL_PERMISSION.get(
        overall_risk_level, "cautious_open",
    )

    # L4 Crowding 建议
    suggestions["l4_crowding"] = _score_to_permission(
        crowding_score, _CROWDING_PERMISSION_BANDS, default="can_open",
    )

    # L4 EventRisk 建议
    suggestions["l4_event_risk"] = _score_to_permission(
        event_risk_score, _EVENT_PERMISSION_BANDS, default="can_open",
    )

    # L5 MacroHeadwind 建议
    suggestions["l5_macro_headwind"] = _score_to_permission(
        macro_headwind_score, _MACRO_PERMISSION_BANDS, default="can_open",
    )

    merged = merge_permissions(*suggestions.values())

    composition: dict[str, Any] = {
        "suggestions": suggestions,
        "merged_before_buffer": merged,
        "a_grade_buffer_applied": False,
        "override_reason": None,
    }

    # ---- A 级缓冲 ----
    buffer_eligible = (
        grade == "A"
        and regime in _A_GRADE_REGIME_STABLE
        and regime_stability in _A_GRADE_STABILITY_OK
    )
    override_reason = _a_grade_buffer_override(
        l5_extreme=l5_extreme,
        overall_risk_level=overall_risk_level,
        state_machine_state=state_machine_state,
        l1_regime_chaos=l1_regime_chaos,
    )
    composition["a_grade_buffer_eligible"] = buffer_eligible
    composition["override_reason"] = override_reason

    if buffer_eligible and override_reason is None:
        # 抬升到 cautious_open(不得更严)
        loosened = merge_permissions(merged, _A_GRADE_BUFFER_FLOOR)
        # merge 返回"更严",我们要"不严于 cautious_open"——取严格度较低者
        final = _min_strict(merged, _A_GRADE_BUFFER_FLOOR)
        if final != merged:
            composition["a_grade_buffer_applied"] = True
        final_permission = final
    elif override_reason is not None:
        # 4 例外强制值
        final_permission = _override_permission_for_reason(override_reason)
    else:
        final_permission = merged

    composition["final_permission"] = final_permission
    return final_permission, composition


def _a_grade_buffer_override(
    *,
    l5_extreme: bool,
    overall_risk_level: str,
    state_machine_state: Optional[str],
    l1_regime_chaos: bool,
) -> Optional[str]:
    """建模 §4.5.6 问题 3 四例外,顺序:PROTECTION → extreme → critical → chaos。"""
    if state_machine_state == "PROTECTION":
        return "state_in_protection"
    if l5_extreme:
        return "l5_extreme_event_detected"
    if overall_risk_level == "critical":
        return "l4_overall_risk_critical"
    if l1_regime_chaos:
        return "l1_regime_chaos"
    return None


def _override_permission_for_reason(reason: str) -> str:
    return {
        "state_in_protection": "protective",
        "l5_extreme_event_detected": "protective",
        "l4_overall_risk_critical": "protective",
        "l1_regime_chaos": "watch",
    }.get(reason, "watch")


def _min_strict(a: str, b: str) -> str:
    """返回两个 permission 中"更不严"的那个(索引更小)。"""
    from ..utils.permission import get_permission_order
    order = get_permission_order()
    if a not in order:
        return b
    if b not in order:
        return a
    return a if order.index(a) < order.index(b) else b


# ============================================================
# §4.5.4 hard_invalidation_levels(Sprint 1.5b v1:由 stop_loss_reference 升格)
# ============================================================

def _build_hard_invalidation_levels(
    *,
    klines_1d: Optional["pd.DataFrame"],
    stop_loss_ref: Optional[dict[str, Any]],
    stance: str,
) -> list[dict[str, Any]]:
    """
    建模 §4.5.4:hard_invalidation_levels 是 **list**,每条含
      { price, direction, basis, priority, confirmation_timeframe }

    Sprint 1.5c C2:
      * priority=1 结构性失效位(§4.5.2 角度一)
          - 多头失效位 = 最近主要 Higher Low(HL)下方:价格跌破则多头结构失效
          - 空头失效位 = 最近主要 Lower High(LH)上方:价格突破则空头结构失效
      * priority=2 stop_loss_reference 兜底(ATR / swing 取最严)

    neutral / 数据不足 → 返回空 list(AI 裁决 trade_plan.stop_loss 则无处可选,
    program validator 会拒绝并走 Fallback Level 1)。
    """
    levels: list[dict[str, Any]] = []
    if stance not in {"bullish", "bearish"}:
        return levels

    # ---- priority=1 结构性失效位 ----
    structural = _find_structural_invalidation(klines_1d, stance)
    if structural is not None:
        levels.append({
            "price": structural["price"],
            "direction": "below" if stance == "bullish" else "above",
            "basis": f"structural_{structural['kind']}",
            "priority": 1,
            "confirmation_timeframe": "4H",
        })

    # ---- priority=2 stop_loss 兜底 ----
    if stop_loss_ref is not None and stop_loss_ref.get("price"):
        levels.append({
            "price": stop_loss_ref.get("price"),
            "direction": "below" if stance == "bullish" else "above",
            "basis": f"stop_{stop_loss_ref.get('method_used', 'atr')}",
            "priority": 2,
            "confirmation_timeframe": "4H",
        })

    return levels


def _find_structural_invalidation(
    klines_1d: Optional["pd.DataFrame"],
    stance: str,
) -> Optional[dict[str, Any]]:
    """
    在最近 60 根 1D 上找结构性失效位(§4.5.2):
      bullish 方向:最近一个 Higher Low(HL)= 最近的 swing_low,
                   且其价格 > 前一个 swing_low
      bearish 方向:最近一个 Lower High(LH)= 最近的 swing_high,
                   且其价格 < 前一个 swing_high

    找不到(结构不明确或数据不足)→ 返回 None。
    """
    if klines_1d is None or not isinstance(klines_1d, pd.DataFrame) \
            or len(klines_1d) < 20:
        return None

    recent = klines_1d.tail(60)
    events = swing_points(recent["high"], recent["low"], lookback=5)
    if len(events) < 2:
        return None

    if stance == "bullish":
        lows = [e for e in events if e["type"] == "low"]
        if len(lows) < 2:
            return None
        latest = lows[-1]
        prior = lows[-2]
        # 只在 Higher Low(高点更高)时认为结构成立
        if float(latest["price"]) > float(prior["price"]):
            return {
                "price": round(float(latest["price"]), 4),
                "kind": "hl",
            }
    elif stance == "bearish":
        highs = [e for e in events if e["type"] == "high"]
        if len(highs) < 2:
            return None
        latest = highs[-1]
        prior = highs[-2]
        if float(latest["price"]) < float(prior["price"]):
            return {
                "price": round(float(latest["price"]), 4),
                "kind": "lh",
            }
    return None


# ============================================================
# 辅助:score → 乘数 / permission 区间匹配
# ============================================================

def _score_to_multiplier(
    score: Optional[float],
    bands: list[tuple[tuple[int, int], float]],
    *,
    default: float,
) -> float:
    if score is None:
        return default
    for (lo, hi), mul in bands:
        if lo <= float(score) <= hi:
            return float(mul)
    return default


def _score_to_permission(
    score: Optional[float],
    bands: list[tuple[tuple[int, int], str]],
    *,
    default: str,
) -> str:
    if score is None:
        return default
    for (lo, hi), perm in bands:
        if lo <= float(score) <= hi:
            return perm
    return default


def _safe_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _safe_number(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ============================================================
# Sprint 1.10 保留:stop_loss + rr 计算
# ============================================================

def _compute_stop_loss(
    klines_1d: Optional[pd.DataFrame],
    stance: str, vol_regime: str,
    stop_cfg: dict[str, Any],
) -> Optional[dict[str, Any]]:
    if klines_1d is None or not isinstance(klines_1d, pd.DataFrame) \
            or len(klines_1d) < 20:
        return None

    current = float(klines_1d["close"].iloc[-1])
    if current <= 0:
        return None

    atr_series = atr(
        klines_1d["high"], klines_1d["low"], klines_1d["close"], period=14,
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

    swing_stop_price: Optional[float] = None
    buffer_pct = float(stop_cfg.get("swing_buffer_pct", 0.015))
    swing_max_dist = float(stop_cfg.get("swing_max_distance_pct", 0.10))

    recent = klines_1d.tail(60)
    events = swing_points(recent["high"], recent["low"], lookback=5)

    if stance == "bullish":
        lows = [e["price"] for e in events if e["type"] == "low"]
        lows = lows[-3:] if len(lows) >= 3 else lows
        valid_lows = [p for p in lows if 0 < p < current]
        if valid_lows:
            best = max(valid_lows)
            dist = (current - best) / current
            if dist <= swing_max_dist:
                swing_stop_price = best * (1 - buffer_pct)
    elif stance == "bearish":
        highs = [e["price"] for e in events if e["type"] == "high"]
        highs = highs[-3:] if len(highs) >= 3 else highs
        valid_highs = [p for p in highs if p > current > 0]
        if valid_highs:
            best = min(valid_highs)
            dist = (best - current) / current
            if dist <= swing_max_dist:
                swing_stop_price = best * (1 + buffer_pct)

    if atr_stop_price is None and swing_stop_price is None:
        return None

    if stance == "bullish":
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


def _compute_rr(
    klines_1d: Optional[pd.DataFrame],
    stance: str,
    stop_loss_ref: Optional[dict[str, Any]],
    composites: dict[str, Any],
    rr_cfg: dict[str, Any],
) -> dict[str, Any]:
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

    recent = klines_1d.tail(60)
    events = swing_points(recent["high"], recent["low"], lookback=5)

    if stance == "bullish":
        highs = [e["price"] for e in events if e["type"] == "high"]
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

    if target1_pct is None or target1_pct <= 0:
        atr_series = atr(
            klines_1d["high"], klines_1d["low"], klines_1d["close"], period=14,
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


def _grade_to_tier(grade: str) -> str:
    return {
        "A": "high", "B": "medium", "C": "low", "none": "very_low",
    }.get(grade, "very_low")
