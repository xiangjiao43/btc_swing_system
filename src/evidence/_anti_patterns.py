"""
_anti_patterns.py — L3 反模式扫描(§7.9,Sprint 1.9)

每个反模式返回 `details` dict:
  {triggered: bool, triggered_by: str,
   impact: one of DOWNGRADE_ONE / FORCE_NONE / FORCE_PROTECTIVE
             or permission_cap: str,
   severity: low/medium/high}

聚合器 `scan_anti_patterns(context, candidate, cfg)` 返回触发的 flag list
+ details dict(key=flag_name,value=details)。
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd


# ---- Impact 类型 ----
IMPACT_DOWNGRADE = "downgrade_one"
IMPACT_FORCE_NONE = "force_none"
IMPACT_FORCE_PROTECTIVE = "force_protective"  # catching_falling_knife 强制 protective(已持仓)或 watch

# 每个反模式的 impact 类型和 permission cap
_IMPACT_POLICY: dict[str, dict[str, Any]] = {
    "chasing_high":          {"impact": IMPACT_DOWNGRADE, "permission_cap": "no_chase"},
    "catching_falling_knife": {"impact": IMPACT_FORCE_PROTECTIVE, "permission_cap": "protective"},
    "counter_trend_trade":   {"impact": IMPACT_FORCE_NONE, "permission_cap": "watch"},
    "overtrading_crowding":  {"impact": IMPACT_DOWNGRADE, "permission_cap": "no_chase"},
    "event_window_trading":  {"impact": IMPACT_DOWNGRADE, "permission_cap": "ambush_only"},
    "macro_misalignment":    {"impact": IMPACT_DOWNGRADE, "permission_cap": None},
}


def scan_anti_patterns(
    context: dict[str, Any],
    candidate_direction: str,
    cfg: dict[str, Any],
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    """
    扫描所有反模式,返回 (触发的 flag list, flag→details dict)。
    """
    flags: list[str] = []
    details: dict[str, dict[str, Any]] = {}

    # --- 1. chasing_high ---
    r = _check_chasing_high(context, candidate_direction, cfg.get("chasing_high") or {})
    if r:
        flags.append("chasing_high")
        details["chasing_high"] = r

    # --- 2. catching_falling_knife ---
    r = _check_catching_falling_knife(
        context, candidate_direction, cfg.get("catching_falling_knife") or {}
    )
    if r:
        flags.append("catching_falling_knife")
        details["catching_falling_knife"] = r

    # --- 3. counter_trend_trade ---
    r = _check_counter_trend(context, candidate_direction)
    if r:
        flags.append("counter_trend_trade")
        details["counter_trend_trade"] = r

    # --- 4. overtrading_crowding ---
    r = _check_overtrading_crowding(
        context, candidate_direction, cfg.get("overtrading_crowding") or {}
    )
    if r:
        flags.append("overtrading_crowding")
        details["overtrading_crowding"] = r

    # --- 5. event_window_trading ---
    r = _check_event_window(context, cfg.get("event_window_trading") or {})
    if r:
        flags.append("event_window_trading")
        details["event_window_trading"] = r

    # --- 6. macro_misalignment ---
    r = _check_macro_misalignment(
        context, candidate_direction, cfg.get("macro_misalignment") or {}
    )
    if r:
        flags.append("macro_misalignment")
        details["macro_misalignment"] = r

    return flags, details


# ============================================================
# 各反模式检查
# ============================================================

def _check_chasing_high(
    context: dict[str, Any], candidate: str, cfg: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """bullish + 近 N 根日线涨幅 > 阈值 + band_position phase ∈ {late, exhausted}。"""
    if candidate != "bullish":
        return None
    klines = context.get("klines_1d")
    if not isinstance(klines, pd.DataFrame) or len(klines) < 4:
        return None
    bars = int(cfg.get("recent_bars", 3))
    th = float(cfg.get("rally_threshold_pct", 0.08))
    recent = klines.tail(bars + 1)["close"]
    if len(recent) < 2:
        return None
    rally = (float(recent.iloc[-1]) - float(recent.iloc[0])) / float(recent.iloc[0])

    # band phase 检查
    bp = (context.get("composite_factors") or {}).get("band_position") or {}
    bp_phase = bp.get("phase", "unknown")

    if rally > th and bp_phase in ("late", "exhausted", "unclear"):
        return {
            "triggered": True,
            "triggered_by": f"{bars}-bar rally {rally:+.2%} > {th:.0%} with phase={bp_phase}",
            "impact": _IMPACT_POLICY["chasing_high"]["impact"],
            "permission_cap": _IMPACT_POLICY["chasing_high"]["permission_cap"],
            "severity": "high" if rally > th * 1.5 else "medium",
        }
    return None


def _check_catching_falling_knife(
    context: dict[str, Any], candidate: str, cfg: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """
    bullish + 近 N 根急跌(负阈值)→ 触发
    bearish + 近 N 根急涨 → 触发
    """
    klines = context.get("klines_1d")
    if not isinstance(klines, pd.DataFrame) or len(klines) < 6:
        return None
    bars = int(cfg.get("recent_bars", 5))
    th = float(cfg.get("move_threshold_pct", 0.10))
    recent = klines.tail(bars + 1)["close"]
    if len(recent) < 2:
        return None
    move = (float(recent.iloc[-1]) - float(recent.iloc[0])) / float(recent.iloc[0])

    triggered = False
    desc = ""
    if candidate == "bullish" and move < -th:
        triggered = True
        desc = f"bullish candidate vs {bars}-bar {move:+.2%} drop (> {th:.0%} threshold)"
    elif candidate == "bearish" and move > th:
        triggered = True
        desc = f"bearish candidate vs {bars}-bar {move:+.2%} rally (> {th:.0%} threshold)"

    if triggered:
        return {
            "triggered": True,
            "triggered_by": desc,
            "impact": _IMPACT_POLICY["catching_falling_knife"]["impact"],
            "permission_cap": _IMPACT_POLICY["catching_falling_knife"]["permission_cap"],
            "severity": "high",
        }
    return None


def _check_counter_trend(
    context: dict[str, Any], candidate: str,
) -> Optional[dict[str, Any]]:
    """L1 regime 与 candidate 方向完全对立 → 触发(典型:trend_up + bearish)。"""
    l1 = context.get("layer_1_output") or {}
    regime = l1.get("regime") or l1.get("regime_primary") or ""
    bad = (
        (regime in ("trend_up", "transition_up") and candidate == "bearish")
        or (regime in ("trend_down", "transition_down") and candidate == "bullish")
    )
    if not bad:
        return None
    return {
        "triggered": True,
        "triggered_by": f"L1 regime={regime} vs candidate={candidate}",
        "impact": _IMPACT_POLICY["counter_trend_trade"]["impact"],
        "permission_cap": _IMPACT_POLICY["counter_trend_trade"]["permission_cap"],
        "severity": "high",
    }


def _check_overtrading_crowding(
    context: dict[str, Any], candidate: str, cfg: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """
    crowding.band ∈ crowding_triggers(默认 extreme);
    crowding.direction 与 candidate 同向 → 触发(跟极端拥挤进场)。
    """
    cr = (context.get("composite_factors") or {}).get("crowding") or {}
    band = cr.get("band")
    crowd_dir = cr.get("direction")
    triggers = cfg.get("crowding_triggers") or ["extreme"]
    if band not in triggers:
        return None

    # direction 检查:crowded_long + bullish candidate → 触发;
    # crowded_short + bearish candidate → 触发
    same_side = (
        (crowd_dir == "crowded_long" and candidate == "bullish")
        or (crowd_dir == "crowded_short" and candidate == "bearish")
    )
    if not same_side:
        return None
    return {
        "triggered": True,
        "triggered_by": f"crowding.band={band}, direction={crowd_dir} aligned with candidate={candidate}",
        "impact": _IMPACT_POLICY["overtrading_crowding"]["impact"],
        "permission_cap": _IMPACT_POLICY["overtrading_crowding"]["permission_cap"],
        "severity": "high",
    }


def _check_event_window(
    context: dict[str, Any], cfg: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """未来 `hours_window` 小时内有 high_event_types 类事件 → 触发。"""
    events = context.get("events_upcoming_48h") or []
    window_hours = float(cfg.get("hours_window", 24))
    high_types = set(cfg.get("high_event_types") or [])

    matching = []
    for ev in events:
        ht = ev.get("hours_to", ev.get("hours_to_event"))
        if ht is None:
            continue
        if float(ht) > window_hours:
            continue
        evt_type = (ev.get("event_type") or "").lower()
        if evt_type in high_types:
            matching.append({
                "name": ev.get("name", "unknown"),
                "type": evt_type,
                "hours_to": ht,
            })

    if not matching:
        return None
    return {
        "triggered": True,
        "triggered_by": f"{len(matching)} high-impact event(s) within {int(window_hours)}h: "
                        + ", ".join(f"{m['name']}@{m['hours_to']}h" for m in matching),
        "matching_events": matching,
        "impact": _IMPACT_POLICY["event_window_trading"]["impact"],
        "permission_cap": _IMPACT_POLICY["event_window_trading"]["permission_cap"],
        "severity": "medium",
    }


def _check_macro_misalignment(
    context: dict[str, Any], candidate: str, cfg: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """
    bullish + macro_headwind.band ∈ bullish_against_bands → 触发。
    bearish 侧 v1 不判(见 Sprint 1.9 Trigger)。
    macro 缺失不触发此项。
    """
    if candidate != "bullish":
        return None
    mh = (context.get("composite_factors") or {}).get("macro_headwind")
    if not mh or not mh.get("band"):
        return None
    band = mh.get("band")
    bad_bands = set(cfg.get("bullish_against_bands") or ["strong_headwind"])
    if band not in bad_bands:
        return None
    return {
        "triggered": True,
        "triggered_by": f"candidate=bullish vs macro_headwind.band={band}",
        "impact": _IMPACT_POLICY["macro_misalignment"]["impact"],
        "permission_cap": _IMPACT_POLICY["macro_misalignment"]["permission_cap"],
        "severity": "medium",
    }


# ============================================================
# 降级/permission 合并(聚合器)
# ============================================================

_DOWNGRADE_ONE = {"A": "B", "B": "C", "C": "none", "none": "none"}


def apply_anti_pattern_impacts(
    base_grade: str, base_permission: str,
    flags: list[str], details: dict[str, dict[str, Any]],
) -> tuple[str, str]:
    """
    按反模式清单依次降级 grade 并收紧 permission。
    返回 (final_grade, final_permission)。

    降级规则:
      * 任一 flag impact = force_none → grade=none
      * 任一 flag impact = force_protective → grade=none + permission=protective
      * 普通 downgrade_one 累积(A→B→C→none)
      * permission_cap 取所有 flag 里最严的(src.utils.permission.merge_permissions)
    """
    from ..utils.permission import merge_permissions

    grade = base_grade
    perm = base_permission

    for flag in flags:
        d = details.get(flag) or {}
        impact = d.get("impact")
        cap = d.get("permission_cap")

        if impact == IMPACT_FORCE_NONE:
            grade = "none"
            if cap:
                perm = merge_permissions(perm, cap)
        elif impact == IMPACT_FORCE_PROTECTIVE:
            grade = "none"
            perm = merge_permissions(perm, cap or "protective")
        elif impact == IMPACT_DOWNGRADE:
            grade = _DOWNGRADE_ONE.get(grade, "none")
            if cap:
                perm = merge_permissions(perm, cap)

    return grade, perm
