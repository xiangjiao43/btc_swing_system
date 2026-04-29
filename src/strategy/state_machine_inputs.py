"""state_machine_inputs.py — Sprint 1.5b-A 触发字段填充器(state_machine 输入侧)。

建模 §5.2 14 状态机迁移逻辑已在 state_machine.py 完整实施,但迁移条件依赖
  trade_plan / lifecycle / layer_2 / layer_4 子字段,
而 state_builder 之前未填充这些字段(全 False / None),导致状态机即使条件成立
也卡在 FLAT。

本模块**只**做"输入侧填充":
  build_state_machine_fields(...)  → 返回 19 字段 flat dict(纯函数,可单测)
  apply_inputs_to_strategy_state(state, fields) → 把 fields 写到 strategy_state
                                                  对应路径(trade_plan / lifecycle /
                                                  evidence_reports.layer_2 / layer_4)
  derive_account_state(fields) → 返回 {long_position_size, short_position_size}
                                  供 state_machine.compute_next 的 account_state= 使用

不重写 state_machine.py 的迁移逻辑,不修改其字段名(§X)。

v1 简化(等 Sprint 1.5b-B lifecycle_manager 接通后改进):
  - hours_since_open / floating_pnl_pct / current_trim_completed / positions_flat
    用 lifecycle 占位的简化推断(详见各函数注释)。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd


logger = logging.getLogger(__name__)


_LONG_STATES: frozenset[str] = frozenset({
    "LONG_PLANNED", "LONG_OPEN", "LONG_HOLD", "LONG_TRIM", "LONG_EXIT",
})
_SHORT_STATES: frozenset[str] = frozenset({
    "SHORT_PLANNED", "SHORT_OPEN", "SHORT_HOLD", "SHORT_TRIM", "SHORT_EXIT",
})
_HOLDING_STATES: frozenset[str] = frozenset({
    "LONG_OPEN", "LONG_HOLD", "LONG_TRIM", "LONG_EXIT",
    "SHORT_OPEN", "SHORT_HOLD", "SHORT_TRIM", "SHORT_EXIT",
})


# ============================================================
# 主入口
# ============================================================

def build_state_machine_fields(
    *,
    prev_state: Optional[str],
    prev_strategy_state: Optional[dict[str, Any]],
    current_strategy_state: dict[str, Any],
    context: dict[str, Any],
    lifecycle: Optional[dict[str, Any]] = None,
    now_utc: Optional[str] = None,
) -> dict[str, Any]:
    """计算 state_machine 需要的所有触发字段。纯函数,不 mutate 入参。

    Args:
      prev_state: 上一次 state_machine.current_state(FLAT/LONG_OPEN/...)
      prev_strategy_state: 上一条 strategy_state(读 layer_2 stance flip / etc)
      current_strategy_state: 本次刚组装的 state(L1-L5 + adjudicator)
      context: state_builder 的 context dict(klines_1h/4h/1d / lifecycle / etc)
      lifecycle: lifecycle dict(1.5b-A 阶段是占位 / None)
      now_utc: 本次 tick 时间;默认 current_strategy_state.reference_timestamp_utc

    Returns:
      flat dict,key 对齐 state_machine.py `_build_field_snapshot` 字段名。
    """
    now_iso = now_utc or current_strategy_state.get("reference_timestamp_utc") or _utc_now_iso()
    lifecycle = lifecycle or context.get("lifecycle") or {}

    er = current_strategy_state.get("evidence_reports") or {}
    l1 = er.get("layer_1") or current_strategy_state.get("layer_1") or {}
    l2 = er.get("layer_2") or current_strategy_state.get("layer_2") or {}
    l4 = er.get("layer_4") or current_strategy_state.get("layer_4") or {}
    trade_plan = current_strategy_state.get("trade_plan") or {}
    adjudicator = current_strategy_state.get("adjudicator") or {}

    klines_1h = context.get("klines_1h")
    klines_4h = context.get("klines_4h")
    klines_1d = context.get("klines_1d")

    # ---------- 持仓侧 / 时间 ----------
    side = _side_from_state(prev_state)
    is_planned = prev_state in {"LONG_PLANNED", "SHORT_PLANNED"}
    is_holding = prev_state in _HOLDING_STATES

    # Sprint 1.5b-B:优先读 lifecycle_manager.compute_pre_sm 已写入的字段
    hours_since_open = (
        _as_float(lifecycle.get("hours_held"))
        if is_holding and lifecycle.get("hours_held") is not None
        else (_hours_since_open(lifecycle, now_iso) if is_holding else 0.0)
    )
    if hours_since_open is None:
        hours_since_open = 0.0
    floating_pnl_pct = (
        _as_float(lifecycle.get("current_floating_pnl_pct"))
        if is_holding and lifecycle.get("current_floating_pnl_pct") is not None
        else (_floating_pnl_pct(lifecycle, klines_1h, side) if is_holding else None)
    )

    # ---------- 入场区 1H 收盘确认 ----------
    entry_zone_filled = (
        _entry_zone_filled_confirmed_1h(trade_plan, klines_1h, side)
        if is_planned else False
    )

    # ---------- 止损 / 硬失效 ----------
    last_1h_close = _last_close(klines_1h)
    last_4h_close = _last_close(klines_4h)
    last_1d_high, last_1d_low = _last_high_low(klines_1d)

    stop_loss_hit = (
        _stop_loss_hit(trade_plan, last_1h_close, side)
        if is_holding else False
    )
    hard_invalidation_breached = (
        _hard_invalidation_breached(l4, last_4h_close, side)
        if is_holding else False
    )

    # ---------- L2 / L4 衍生 ----------
    l2_stance = l2.get("stance")
    l2_stance_confidence = l2.get("stance_confidence") or l2.get("confidence")
    l2_stance_flipped = _l2_stance_flipped(prev_strategy_state, l2_stance, side)
    l2_bullish_early = _l2_bullish_early_signal(l2)
    l2_bearish_early = _l2_bearish_early_signal(l2)

    l4_new_critical_risk = _l4_new_critical_risk(prev_strategy_state, l4)

    # ---------- thesis_still_valid ----------
    thesis = (
        adjudicator.get("thesis_still_valid")
        or (adjudicator.get("thesis_assessment") or {}).get("thesis_still_valid")
        or "fully_valid"  # 默认保守不触发 EXIT
    )

    # ---------- 账户(v1 不接执行反馈,从 prev_state 推断)----------
    account_has_long, account_has_short = _infer_account_status(
        prev_state, hours_since_open,
    )
    positions_flat = not (account_has_long or account_has_short)

    # ---------- 减仓档(LONG_TRIM / LONG_HOLD)----------
    # Sprint 1.5b-B:优先读 lifecycle.tp_target_hit_this_run(LifecycleManager.pre_sm 写入)
    if lifecycle.get("tp_target_hit_this_run") is True:
        next_trim_triggered = True
    else:
        next_trim_triggered = (
            _next_trim_triggered(trade_plan, last_1d_high, last_1d_low, side)
            if prev_state in {"LONG_HOLD", "SHORT_HOLD", "LONG_TRIM", "SHORT_TRIM"}
            else False
        )
    # current_trim_completed 优先读 lifecycle(pre_sm 已基于 cumulative_trim_pct 计算)
    if isinstance(lifecycle.get("current_trim_completed"), bool):
        current_trim_completed = lifecycle["current_trim_completed"]
    else:
        current_trim_completed = (
            _current_trim_completed_v1(prev_state, hours_since_open)
            if prev_state in {"LONG_TRIM", "SHORT_TRIM"} else False
        )

    # ---------- FLIP_WATCH 时间界 ----------
    flip_min_passed, flip_max_exceeded = _flip_watch_bounds_state(
        prev_state, prev_strategy_state, now_iso,
    )

    # ---------- prev_cycle_side(FLIP_WATCH 用)----------
    prev_cycle_side = _prev_cycle_side(prev_state, prev_strategy_state)

    # ---------- thesis_invalidated ----------
    # 持仓期看当前 side;FLIP_WATCH/POST_PROTECTION_REASSESS 期 side=None,
    # 看 prev_cycle_side(state_machine FLIP_WATCH → *_PLANNED 路径需要)。
    # lifecycle 显式写入的值优先(LifecycleManager 归档时可能已写入)。
    inv_side = side or prev_cycle_side
    long_thesis_inv = bool(lifecycle.get("long_thesis_invalidated")) or (
        inv_side == "long" and thesis == "invalidated"
    )
    short_thesis_inv = bool(lifecycle.get("short_thesis_invalidated")) or (
        inv_side == "short" and thesis == "invalidated"
    )

    return {
        # state_machine.py field-snapshot 兼容字段名
        "entry_zone_filled_confirmed_1h": entry_zone_filled,
        "hours_since_open": hours_since_open,
        "floating_pnl_pct": floating_pnl_pct,
        "hard_invalidation_breached": hard_invalidation_breached,
        "stop_loss_hit": stop_loss_hit,
        # Sprint 1.5b-B:LifecycleManager.compute_pre_sm 写入 tp_target_hit_this_run
        "tp_target_hit": bool(lifecycle.get("tp_target_hit_this_run", False)),
        "l2_stance": l2_stance,
        "l2_stance_flipped": l2_stance_flipped,
        "l2_stance_confidence": l2_stance_confidence,
        "thesis_still_valid": thesis,
        "l4_new_critical_risk": l4_new_critical_risk,
        "l1_regime": l1.get("regime") or l1.get("regime_primary"),
        "account_has_long": account_has_long,
        "account_has_short": account_has_short,
        "next_trim_triggered": next_trim_triggered,
        "current_trim_completed": current_trim_completed,
        "l2_bullish_early_signal": l2_bullish_early,
        "l2_bearish_early_signal": l2_bearish_early,
        "positions_flat": positions_flat,
        "flip_watch_min_hours_passed": flip_min_passed,
        "flip_watch_max_hours_exceeded": flip_max_exceeded,
        "long_thesis_invalidated": long_thesis_inv,
        "short_thesis_invalidated": short_thesis_inv,
        "prev_cycle_side": prev_cycle_side,
    }


def apply_inputs_to_strategy_state(
    strategy_state: dict[str, Any],
    fields: dict[str, Any],
) -> dict[str, Any]:
    """把计算好的 fields 写入 strategy_state 的对应路径(trade_plan / lifecycle /
    evidence_reports.layer_2 / layer_4),让 state_machine.compute_next 内部的
    `_build_field_snapshot` 自动捡到真实数据。

    返回 mutated strategy_state。
    """
    # trade_plan
    tp = strategy_state.setdefault("trade_plan", {})
    if not isinstance(tp, dict):
        tp = {}
        strategy_state["trade_plan"] = tp
    tp["entry_zone_filled_confirmed_1h"] = fields["entry_zone_filled_confirmed_1h"]
    tp["stop_loss_hit"] = fields["stop_loss_hit"]
    tp["tp_target_hit"] = fields["tp_target_hit"]

    # lifecycle
    lc = strategy_state.setdefault("lifecycle", {})
    if not isinstance(lc, dict):
        lc = {}
        strategy_state["lifecycle"] = lc
    lc["hours_since_open"] = fields["hours_since_open"]
    lc["floating_pnl_pct"] = fields["floating_pnl_pct"]
    lc["next_trim_triggered"] = fields["next_trim_triggered"]
    lc["current_trim_completed"] = fields["current_trim_completed"]
    lc["thesis_still_valid"] = fields["thesis_still_valid"]
    lc["long_thesis_invalidated"] = fields["long_thesis_invalidated"]
    lc["short_thesis_invalidated"] = fields["short_thesis_invalidated"]
    lc["prev_cycle_side"] = fields["prev_cycle_side"]

    # evidence_reports.layer_2 / layer_4
    er = strategy_state.setdefault("evidence_reports", {})
    if not isinstance(er, dict):
        er = {}
        strategy_state["evidence_reports"] = er
    l2 = er.setdefault("layer_2", {})
    if not isinstance(l2, dict):
        l2 = {}
        er["layer_2"] = l2
    l2["stance_flipped"] = fields["l2_stance_flipped"]
    l2["bullish_early_signal"] = fields["l2_bullish_early_signal"]
    l2["bearish_early_signal"] = fields["l2_bearish_early_signal"]

    l4 = er.setdefault("layer_4", {})
    if not isinstance(l4, dict):
        l4 = {}
        er["layer_4"] = l4
    l4["hard_invalidation_breached"] = fields["hard_invalidation_breached"]
    l4["new_critical_risk"] = fields["l4_new_critical_risk"]

    return strategy_state


def derive_account_state(fields: dict[str, Any]) -> dict[str, Any]:
    """从 fields 推出 account_state(state_machine.compute_next 单独参数)。"""
    return {
        "long_position_size": 1 if fields.get("account_has_long") else 0,
        "short_position_size": 1 if fields.get("account_has_short") else 0,
    }


# ============================================================
# 字段计算(私有)
# ============================================================

def _side_from_state(state: Optional[str]) -> Optional[str]:
    if state in _LONG_STATES:
        return "long"
    if state in _SHORT_STATES:
        return "short"
    return None


def _last_close(klines_df: Any) -> Optional[float]:
    if klines_df is None or not isinstance(klines_df, pd.DataFrame) or len(klines_df) == 0:
        return None
    try:
        return float(klines_df["close"].iloc[-1])
    except (KeyError, ValueError, TypeError):
        return None


def _last_high_low(
    klines_df: Any,
) -> tuple[Optional[float], Optional[float]]:
    if klines_df is None or not isinstance(klines_df, pd.DataFrame) or len(klines_df) == 0:
        return None, None
    try:
        return float(klines_df["high"].iloc[-1]), float(klines_df["low"].iloc[-1])
    except (KeyError, ValueError, TypeError):
        return None, None


def _entry_zone_filled_confirmed_1h(
    trade_plan: dict[str, Any], klines_1h: Any, side: Optional[str],
) -> bool:
    """LONG_PLANNED/SHORT_PLANNED:1H 收盘价是否进入任一 entry_zone。"""
    last_close = _last_close(klines_1h)
    if last_close is None:
        return False
    zones = trade_plan.get("entry_zones") or trade_plan.get("entry_zone")
    if not zones:
        return False
    if isinstance(zones, dict):
        zones = [zones]
    if not isinstance(zones, list):
        return False
    for z in zones:
        if not isinstance(z, dict):
            continue
        # 容忍多种字段命名(price_low/price_high / low/high / lower/upper)
        lo = _as_float(z.get("price_low") or z.get("low") or z.get("lower"))
        hi = _as_float(z.get("price_high") or z.get("high") or z.get("upper"))
        if lo is None and hi is None:
            continue
        if side == "long":
            # 收盘价 ≤ price_high(穿入区间或下方)即视为成交
            ref = hi if hi is not None else lo
            if ref is not None and last_close <= ref:
                return True
        elif side == "short":
            # 收盘价 ≥ price_low(穿入区间或上方)
            ref = lo if lo is not None else hi
            if ref is not None and last_close >= ref:
                return True
    return False


def _stop_loss_hit(
    trade_plan: dict[str, Any],
    last_1h_close: Optional[float],
    side: Optional[str],
) -> bool:
    if last_1h_close is None or side is None:
        return False
    sl = _as_float(
        trade_plan.get("stop_loss")
        or (trade_plan.get("stop_loss_reference") or {}).get("price")
    )
    if sl is None:
        return False
    if side == "long":
        return last_1h_close < sl
    return last_1h_close > sl  # short


def _hard_invalidation_breached(
    layer_4: dict[str, Any],
    last_4h_close: Optional[float],
    side: Optional[str],
) -> bool:
    if last_4h_close is None or side is None:
        return False
    levels = layer_4.get("hard_invalidation_levels") or []
    if not isinstance(levels, list):
        return False
    # 取 priority=1 的失效位(没 priority 时取第一个)
    target = None
    for lvl in levels:
        if isinstance(lvl, dict) and lvl.get("priority") == 1:
            target = lvl
            break
    if target is None and levels and isinstance(levels[0], dict):
        target = levels[0]
    if target is None:
        return False
    price = _as_float(target.get("price"))
    if price is None:
        return False
    if side == "long":
        return last_4h_close < price
    return last_4h_close > price  # short


def _l2_stance_flipped(
    prev_strategy_state: Optional[dict[str, Any]],
    curr_l2_stance: Optional[str],
    side: Optional[str],
) -> bool:
    """持仓期 (LONG_*/SHORT_*),L2 stance 从同向 → 反向 即视为 flip。"""
    if side is None or curr_l2_stance is None:
        return False
    prev_l2 = _prev_layer(prev_strategy_state, "layer_2")
    prev_stance = (prev_l2 or {}).get("stance")
    if prev_stance is None:
        return False
    if side == "long":
        return prev_stance == "bullish" and curr_l2_stance == "bearish"
    return prev_stance == "bearish" and curr_l2_stance == "bullish"


def _l2_bullish_early_signal(l2: dict[str, Any]) -> bool:
    """v1 简化:L2 stance=bullish 且 confidence > 0.4 即视为 early signal。"""
    if l2.get("stance") != "bullish":
        return False
    conf = _as_float(l2.get("stance_confidence") or l2.get("confidence"))
    return conf is not None and conf > 0.4


def _l2_bearish_early_signal(l2: dict[str, Any]) -> bool:
    if l2.get("stance") != "bearish":
        return False
    conf = _as_float(l2.get("stance_confidence") or l2.get("confidence"))
    return conf is not None and conf > 0.4


def _l4_new_critical_risk(
    prev_strategy_state: Optional[dict[str, Any]],
    curr_l4: dict[str, Any],
) -> bool:
    """prev != critical 且 curr == critical → True。"""
    curr = curr_l4.get("overall_risk_level") or curr_l4.get("overall_risk")
    if curr != "critical":
        return False
    prev_l4 = _prev_layer(prev_strategy_state, "layer_4") or {}
    prev = prev_l4.get("overall_risk_level") or prev_l4.get("overall_risk")
    return prev != "critical"


def _hours_since_open(lifecycle: dict[str, Any], now_iso: str) -> float:
    """从 lifecycle.origin_time_utc 算到 now 的小时数。lifecycle 占位返回 0.0。"""
    origin = lifecycle.get("origin_time_utc") or lifecycle.get("entry_time_utc")
    if not origin:
        return 0.0
    try:
        a = _parse_iso(origin)
        b = _parse_iso(now_iso)
        return max(0.0, (b - a).total_seconds() / 3600.0)
    except Exception:
        return 0.0


def _floating_pnl_pct(
    lifecycle: dict[str, Any], klines_1h: Any, side: Optional[str],
) -> Optional[float]:
    avg_entry = _as_float(
        lifecycle.get("average_entry_price")
        or lifecycle.get("entry_price")
    )
    last_price = _last_close(klines_1h)
    if avg_entry is None or last_price is None or avg_entry <= 0 or side is None:
        return None
    if side == "long":
        return (last_price - avg_entry) / avg_entry * 100.0
    return (avg_entry - last_price) / avg_entry * 100.0


def _next_trim_triggered(
    trade_plan: dict[str, Any],
    last_1d_high: Optional[float],
    last_1d_low: Optional[float],
    side: Optional[str],
) -> bool:
    if side is None:
        return False
    plan = trade_plan.get("take_profit_plan") or trade_plan.get("take_profits")
    if not isinstance(plan, list):
        return False
    for level in plan:
        if not isinstance(level, dict):
            continue
        if level.get("triggered"):
            continue  # 已触发档跳过
        target = _as_float(level.get("target_price") or level.get("price"))
        if target is None:
            continue
        if side == "long" and last_1d_high is not None and last_1d_high >= target:
            return True
        if side == "short" and last_1d_low is not None and last_1d_low <= target:
            return True
        # 找到第一个未触发档就停(下一档)
        return False
    return False


def _current_trim_completed_v1(
    prev_state: Optional[str], hours_since_open: float,
) -> bool:
    """v1 简化:进入 *_TRIM 状态后 24h 自动算"完成"。
    1.5b-B lifecycle.position_adjustments 接通后改成读累计平仓比例。
    """
    return prev_state in {"LONG_TRIM", "SHORT_TRIM"} and hours_since_open >= 24.0


def _infer_account_status(
    prev_state: Optional[str], hours_since_open: float,
) -> tuple[bool, bool]:
    """v1 简化:按 prev_state side 假定持仓;*_EXIT 状态 hours_since_open > 48h
    视为已平仓(positions_flat=True)。"""
    if prev_state in _LONG_STATES:
        if prev_state == "LONG_EXIT" and hours_since_open > 48.0:
            return False, False
        return True, False
    if prev_state in _SHORT_STATES:
        if prev_state == "SHORT_EXIT" and hours_since_open > 48.0:
            return False, False
        return False, True
    return False, False


def _flip_watch_bounds_state(
    prev_state: Optional[str],
    prev_strategy_state: Optional[dict[str, Any]],
    now_iso: str,
) -> tuple[bool, bool]:
    """仅 prev_state == FLIP_WATCH 计算;否则 (False, False)。"""
    if prev_state != "FLIP_WATCH":
        return False, False
    sm = (prev_strategy_state or {}).get("state_machine") or {}
    entered_at = sm.get("state_entered_at_utc")
    bounds = sm.get("flip_watch_bounds") or {}
    if not entered_at:
        return False, False
    try:
        a = _parse_iso(entered_at)
        b = _parse_iso(now_iso)
        hours_in = (b - a).total_seconds() / 3600.0
    except Exception:
        return False, False
    eff_min = _as_float(bounds.get("effective_min_hours")) or 18.0
    eff_max = _as_float(bounds.get("effective_max_hours")) or 96.0
    return hours_in >= eff_min, hours_in >= eff_max


def _prev_cycle_side(
    prev_state: Optional[str],
    prev_strategy_state: Optional[dict[str, Any]],
) -> Optional[str]:
    """FLIP_WATCH / POST_PROTECTION_REASSESS 时,从 prev lifecycle 持久值取;
    否则按 prev_state 推断。

    prev_strategy_state 可以是 {"state": {...}}(DAO row 形态)或直接 {...}。
    """
    if prev_state in {"FLIP_WATCH", "POST_PROTECTION_REASSESS"}:
        if prev_strategy_state:
            outer = (
                prev_strategy_state.get("state")
                if isinstance(prev_strategy_state.get("state"), dict)
                else prev_strategy_state
            )
            prev_lc = (outer or {}).get("lifecycle") or {}
            side = prev_lc.get("prev_cycle_side")
            if side in {"long", "short"}:
                return side
            # fallback:用归档 lifecycle 的 direction
            direction = prev_lc.get("direction")
            if direction in {"long", "short"}:
                return direction
    return _side_from_state(prev_state)


# ============================================================
# 工具
# ============================================================

def _as_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _prev_layer(
    prev_strategy_state: Optional[dict[str, Any]], layer_key: str,
) -> Optional[dict[str, Any]]:
    if not prev_strategy_state:
        return None
    state = (
        prev_strategy_state.get("state")
        if isinstance(prev_strategy_state.get("state"), dict)
        else prev_strategy_state
    )
    er = (state or {}).get("evidence_reports") or {}
    layer = er.get(layer_key)
    if isinstance(layer, dict):
        return layer
    # 顶层 fallback(legacy)
    if isinstance(state.get(layer_key), dict):
        return state[layer_key]
    return None
