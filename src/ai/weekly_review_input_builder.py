"""src/ai/weekly_review_input_builder.py — Sprint 1.10-H 周复盘 input 装配。

对齐 docs/modeling.md b25cfe6(v1.4)§3.3.9:
- 7 类输入聚合(strategy_runs / theses / virtual_orders / fallback_events /
  retry_log / virtual_account snapshots / fuse_events + system_states /
  constraint_activations)
- 23 条 Validator 激活率统计 + meta 4 字段(position_cap_compressed_avg /
  thesis_lock_blocks_count / channel_c_uses_count / review_pending_triggers)
- weekly_pnl_pct + max_drawdown_pct(从 virtual_account 7 天 snapshots 算)

设计纪律:
- 纯查询 + 聚合,不调 AI / 不写 DB
- 返回 dict,直接传 WeeklyReviewAnalyst.analyze(context=...)
- 失败时字段缺失 → fallback 默认值(0 / 空 list / None),不抛
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Optional


logger = logging.getLogger(__name__)


# v1.4 §3.4.9 的 23 条 Validator key(对应 _DEFAULT_ACTIVATIONS_V24 中的 *触发* 字段)
# 注:激活率统计**只**对 V1-V23 触发布尔字段聚合,不含 meta 4 字段
VALIDATOR_KEYS = (
    "validator_1_stop_loss_overridden",
    "validator_2_position_capped",
    "validator_3_entry_size_normalized",
    "validator_4_protection_blocked",
    "validator_5_grade_permission_lock",
    "validator_6_thesis_lock",
    "validator_7_invalidation_check",
    "validator_8_break_objectivity",
    "validator_9_break_distance",
    "validator_10_grade_lock",
    "validator_11_direction_lock",
    "validator_12_evidence_real",
    "validator_13_objective_evidence",
    "validator_14_counter_argument",
    "validator_15_confidence_capped",
    "validator_16_change_mind",
    "validator_17_stop_tightening",
    "validator_18_14d_fuse_active",
    "validator_19_60d_cap",
    "validator_20_consecutive_fuse",
    "validator_21_soft_resistance",
    "validator_22_3day_fail",
    "validator_23_conflict_missing",
)
assert len(VALIDATOR_KEYS) == 23, "v1.4 §3.4.9 必须 23 条 Validator"


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        s2 = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _to_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_json_loads(raw: Any) -> dict[str, Any]:
    """Best-effort JSON object parser for review-only diagnostics."""
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def _row_value(row: Any, key: str, idx: int) -> Any:
    if hasattr(row, "keys"):
        return row[key]
    return row[idx]


def _count_value(counter: dict[str, int], value: Any, empty_key: str = "empty") -> None:
    key = str(value) if value not in (None, "") else empty_key
    counter[key] = counter.get(key, 0) + 1


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _numeric_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "max": None, "avg": None}
    return {
        "count": len(values),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "avg": round(sum(values) / len(values), 4),
    }


def _safe_ratio(count: Optional[int], total: Optional[int]) -> Optional[float]:
    if count is None or total is None or total <= 0:
        return None
    return round(count / total, 4)


def _parse_rate_count_total(rate: Any) -> tuple[Optional[int], Optional[int]]:
    if not isinstance(rate, str):
        return None, None
    try:
        left, right = rate.strip().split("/", 1)
        total = right.strip().split()[0]
        return int(left.strip()), int(total)
    except Exception:
        return None, None


def _trend_point(
    *,
    week_start_utc: str,
    value: Optional[int] = None,
    count: Optional[int] = None,
    total: Optional[int] = None,
    source: str,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "week_start_utc": week_start_utc,
        "source": source,
    }
    if value is not None:
        out["value"] = value
    if count is not None:
        out["count"] = count
    if total is not None:
        out["total"] = total
        out["rate"] = _safe_ratio(count, total)
    return out


def _extract_layers(state: dict[str, Any]) -> dict[str, Any]:
    return state.get("layers") or {}


def _extract_master_action(state: dict[str, Any]) -> Any:
    layers = _extract_layers(state)
    master = layers.get("master") or {}
    trade_plan = master.get("trade_plan") or {}
    new_thesis = master.get("new_thesis") or {}
    return (
        master.get("mode")
        or master.get("action")
        or trade_plan.get("action")
        or new_thesis.get("mode")
        or (state.get("adjudicator") or {}).get("action")
        or (state.get("trade_plan") or {}).get("action")
    )


# ============================================================
# 7 类输入聚合 helper(每个返回独立 dict / list)
# ============================================================

def _aggregate_strategy_runs(
    conn: sqlite3.Connection, *, week_start: datetime, week_end: datetime,
) -> dict[str, Any]:
    """聚合 strategy_runs 计数 + ai_status 分布。

    Returns: {total_runs, successful_runs, ai_failures, runs_by_trigger}
    """
    # Sprint 1.10-K-A commit 2 §X(v1.4 §11.2):
    # SELECT 不再读 observation_category(列已删 / 业务逻辑 1.10-J 已废)。
    rows = conn.execute(
        "SELECT run_trigger, fallback_level "
        "FROM strategy_runs "
        "WHERE generated_at_utc >= ? AND generated_at_utc < ?",
        (_to_iso(week_start), _to_iso(week_end)),
    ).fetchall()
    total = len(rows)
    failures = sum(
        1 for r in rows
        if (r["fallback_level"] if hasattr(r, "keys") else r[1])
        not in (None, "", "level_0")
    )
    by_trigger: dict[str, int] = {}
    for r in rows:
        tr = (r["run_trigger"] if hasattr(r, "keys") else r[0]) or "unknown"
        by_trigger[tr] = by_trigger.get(tr, 0) + 1
    return {
        "total_runs": total,
        "successful_runs": total - failures,
        "ai_failures": failures,
        "runs_by_trigger": by_trigger,
    }


def _aggregate_theses(
    conn: sqlite3.Connection, *, week_start: datetime, week_end: datetime,
) -> dict[str, Any]:
    """聚合 theses 创建/关闭统计。

    Returns: {created, closed_profit, closed_loss, closed_invalidated,
              closed_60d_cap, closed_protection, channel_a, channel_b, channel_c,
              created_list, closed_list}
    """
    # 创建在窗口内
    created_rows = conn.execute(
        "SELECT thesis_id, direction, confidence_score, created_at_utc "
        "FROM theses "
        "WHERE created_at_utc >= ? AND created_at_utc < ?",
        (_to_iso(week_start), _to_iso(week_end)),
    ).fetchall()
    # 关闭在窗口内(closed_at_utc 可空)
    closed_rows = conn.execute(
        "SELECT thesis_id, direction, status, close_channel, "
        "       final_realized_pnl_pct, closed_at_utc, final_outcome "
        "FROM theses "
        "WHERE closed_at_utc IS NOT NULL "
        "  AND closed_at_utc >= ? AND closed_at_utc < ?",
        (_to_iso(week_start), _to_iso(week_end)),
    ).fetchall()

    counts = {
        "thesis_created": len(created_rows),
        "thesis_closed_profit": 0,
        "thesis_closed_loss": 0,
        "thesis_closed_invalidated": 0,
        "thesis_closed_60d_cap": 0,
        "thesis_closed_protection": 0,
        "channel_a_uses": 0,
        "channel_b_uses": 0,
        "channel_c_uses": 0,
    }
    for r in closed_rows:
        outcome = r["final_outcome"] if hasattr(r, "keys") else r[6]
        status = r["status"] if hasattr(r, "keys") else r[2]
        ch = r["close_channel"] if hasattr(r, "keys") else r[3]
        if outcome == "profit":
            counts["thesis_closed_profit"] += 1
        elif outcome == "loss" and status != "invalidated":
            counts["thesis_closed_loss"] += 1
        elif status == "invalidated":
            counts["thesis_closed_invalidated"] += 1
        elif status == "closed_60d_cap":
            counts["thesis_closed_60d_cap"] += 1
        elif status == "closed_protection":
            counts["thesis_closed_protection"] += 1
        if ch == "A":
            counts["channel_a_uses"] += 1
        elif ch == "B":
            counts["channel_b_uses"] += 1
        elif ch == "C":
            counts["channel_c_uses"] += 1

    return {
        **counts,
        "created_list": [
            {"thesis_id": r["thesis_id"] if hasattr(r, "keys") else r[0],
             "direction": r["direction"] if hasattr(r, "keys") else r[1],
             "confidence_score": r["confidence_score"] if hasattr(r, "keys") else r[2],
             "created_at_utc": r["created_at_utc"] if hasattr(r, "keys") else r[3]}
            for r in created_rows
        ],
        "closed_list": [
            {"thesis_id": r["thesis_id"] if hasattr(r, "keys") else r[0],
             "status": r["status"] if hasattr(r, "keys") else r[2],
             "close_channel": r["close_channel"] if hasattr(r, "keys") else r[3],
             "final_realized_pnl_pct": (
                 r["final_realized_pnl_pct"] if hasattr(r, "keys") else r[4]
             ),
             "closed_at_utc": r["closed_at_utc"] if hasattr(r, "keys") else r[5]}
            for r in closed_rows
        ],
    }


def _aggregate_virtual_orders(
    conn: sqlite3.Connection, *, week_start: datetime, week_end: datetime,
) -> dict[str, int]:
    """统计 virtual_orders 7 天触发分布(filled/cancelled/expired)。"""
    rows = conn.execute(
        "SELECT status, order_type FROM virtual_orders "
        "WHERE filled_at_utc IS NOT NULL "
        "  AND filled_at_utc >= ? AND filled_at_utc < ?",
        (_to_iso(week_start), _to_iso(week_end)),
    ).fetchall()
    counts = {"orders_filled": 0, "entry_filled": 0,
              "stop_loss_filled": 0, "take_profit_filled": 0}
    for r in rows:
        st = r["status"] if hasattr(r, "keys") else r[0]
        ot = r["order_type"] if hasattr(r, "keys") else r[1]
        if st == "filled":
            counts["orders_filled"] += 1
            if ot == "entry":
                counts["entry_filled"] += 1
            elif ot == "stop_loss":
                counts["stop_loss_filled"] += 1
            elif ot == "take_profit":
                counts["take_profit_filled"] += 1
    return counts


def _aggregate_retry_log(
    conn: sqlite3.Connection, *, week_start: datetime, week_end: datetime,
) -> dict[str, Any]:
    """聚合 strategy_runs.retry_log_json:fallback / retry / event_invalidation 统计。

    Returns:
      {macro_fallback_count, thesis_aware_fallback_count,
       validator_triggered_retry_count, event_invalidation_count,
       failed_layers_distribution: {l1: N, l2: N, ..., master: N}}
    """
    rows = conn.execute(
        "SELECT retry_log_json FROM strategy_runs "
        "WHERE generated_at_utc >= ? AND generated_at_utc < ? "
        "  AND retry_log_json IS NOT NULL",
        (_to_iso(week_start), _to_iso(week_end)),
    ).fetchall()
    counts = {
        "macro_fallback_count": 0,
        "thesis_aware_fallback_count": 0,
        "validator_triggered_retry_count": 0,
        "event_invalidation_count": 0,
    }
    failed_layers: dict[str, int] = {}
    for r in rows:
        rl_str = r["retry_log_json"] if hasattr(r, "keys") else r[0]
        try:
            rl = json.loads(rl_str)
        except Exception:
            continue
        if rl.get("macro_fallback_applied"):
            counts["macro_fallback_count"] += 1
        if rl.get("thesis_aware_fallback_applied"):
            counts["thesis_aware_fallback_count"] += 1
        if rl.get("validator_triggered_retry_applied"):
            counts["validator_triggered_retry_count"] += 1
        if rl.get("event_invalidation_triggered"):
            counts["event_invalidation_count"] += 1
        for layer in rl.get("failed_layers") or []:
            failed_layers[layer] = failed_layers.get(layer, 0) + 1
    return {**counts, "failed_layers_distribution": failed_layers}


def _aggregate_virtual_account(
    conn: sqlite3.Connection, *, week_start: datetime, week_end: datetime,
) -> dict[str, Any]:
    """从 virtual_account 7 天 snapshots 算 weekly_pnl_pct + max_drawdown_pct。

    Returns:
      {start_total_equity, end_total_equity, weekly_pnl_pct,
       max_drawdown_pct, snapshots_count}
    """
    rows = conn.execute(
        "SELECT snapshot_at_utc, total_equity FROM virtual_account "
        "WHERE snapshot_at_utc >= ? AND snapshot_at_utc < ? "
        "ORDER BY snapshot_at_utc ASC",
        (_to_iso(week_start), _to_iso(week_end)),
    ).fetchall()
    if not rows:
        return {
            "start_total_equity": None,
            "end_total_equity": None,
            "weekly_pnl_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "snapshots_count": 0,
        }
    equities = [
        float(r["total_equity"] if hasattr(r, "keys") else r[1])
        for r in rows
    ]
    start = equities[0]
    end = equities[-1]
    pnl_pct = ((end - start) / start * 100.0) if start > 0 else 0.0
    # max drawdown:从历史最高点跌幅
    peak = start
    max_dd = 0.0
    for eq in equities:
        if eq > peak:
            peak = eq
        if peak > 0:
            dd = (eq - peak) / peak * 100.0
            if dd < max_dd:
                max_dd = dd
    return {
        "start_total_equity": start,
        "end_total_equity": end,
        "weekly_pnl_pct": round(pnl_pct, 4),
        "max_drawdown_pct": round(max_dd, 4),
        "snapshots_count": len(equities),
    }


def _aggregate_fuse_and_states(
    conn: sqlite3.Connection, *, week_start: datetime, week_end: datetime,
) -> dict[str, Any]:
    """fuse_events + system_states(review_pending 触发)统计。"""
    fuse_rows = conn.execute(
        "SELECT event_type FROM fuse_events "
        "WHERE triggered_at_utc >= ? AND triggered_at_utc < ?",
        (_to_iso(week_start), _to_iso(week_end)),
    ).fetchall()
    fuse_counts: dict[str, int] = {}
    for r in fuse_rows:
        et = r["event_type"] if hasattr(r, "keys") else r[0]
        fuse_counts[et] = fuse_counts.get(et, 0) + 1

    rp_rows = conn.execute(
        "SELECT reason FROM system_states "
        "WHERE state_type='review_pending' "
        "  AND entered_at_utc >= ? AND entered_at_utc < ?",
        (_to_iso(week_start), _to_iso(week_end)),
    ).fetchall()
    rp_count = len(rp_rows)

    return {
        "fuse_events_by_type": fuse_counts,
        "review_pending_triggers": rp_count,
        "fuse_14d_triggered_count": fuse_counts.get("14d_fuse_triggered", 0),
        "channel_c_used_count": fuse_counts.get("channel_c_used", 0),
    }


def _aggregate_constraint_activations(
    conn: sqlite3.Connection, *, week_start: datetime, week_end: datetime,
    window_days: int = 7,
) -> dict[str, Any]:
    """聚合 strategy_runs.constraint_activations_json:
    - 23 条 V 激活次数(每条 'activations' / 'rate' 'N/M valid_runs')
    - meta 4 字段平均值(position_cap_compressed_avg / thesis_lock_blocks_count /
      channel_c_uses_count(从 fuse_events 取)/ review_pending_triggers)

    Returns 完整 hard_constraint_activation_review 雏形(weekly_review_analyst 后续填评估)。
    """
    rows = conn.execute(
        "SELECT constraint_activations_json FROM strategy_runs "
        "WHERE generated_at_utc >= ? AND generated_at_utc < ?",
        (_to_iso(week_start), _to_iso(week_end)),
    ).fetchall()

    # 23 条 V 累计触发数
    v_counts = {k: 0 for k in VALIDATOR_KEYS}
    cap_compressed_values: list[float] = []
    thesis_lock_count = 0
    total_strategy_runs = len(rows)
    valid_constraint_runs = 0
    missing_constraint_runs = 0

    for r in rows:
        ca_str = (
            r["constraint_activations_json"]
            if hasattr(r, "keys") else r[0]
        )
        if not ca_str:
            missing_constraint_runs += 1
            continue
        try:
            ca = json.loads(ca_str)
        except Exception:
            missing_constraint_runs += 1
            continue
        if not isinstance(ca, dict):
            missing_constraint_runs += 1
            continue
        valid_constraint_runs += 1
        for k in VALIDATOR_KEYS:
            if ca.get(k) is True:
                v_counts[k] += 1
        cap_v = ca.get("position_cap_compressed")
        if isinstance(cap_v, (int, float)):
            cap_compressed_values.append(float(cap_v))
        if ca.get("thesis_lock_active") is True:
            thesis_lock_count += 1

    # 23 条 V dict(input_builder 只装数据,evaluation 文本由 AI 填)
    v_review = {}
    for k in VALIDATOR_KEYS:
        v_review[k] = {
            "activations": v_counts[k],
            "rate": f"{v_counts[k]}/{valid_constraint_runs} valid_runs",
        }

    cap_avg = (
        round(sum(cap_compressed_values) / len(cap_compressed_values), 4)
        if cap_compressed_values else None
    )

    return {
        "v_activations_raw": v_review,                    # 23 条 V dict
        "position_cap_compressed_avg": cap_avg,
        "thesis_lock_blocks_count": thesis_lock_count,
        # 历史字段名不准确:这里不是 days,而是有效 Validator run 数。
        # 暂时保留给旧 prompt / 旧测试 / 旧输出兼容。
        "total_days_in_window": valid_constraint_runs,
        "sample_base": {
            "total_strategy_runs": total_strategy_runs,
            "valid_constraint_runs": valid_constraint_runs,
            "missing_constraint_runs": missing_constraint_runs,
            "window_days": window_days,
        },
    }


# ============================================================
# Sprint H Part B(2026-05-09):4 个新聚合
# 历史:weekly_review_audit.md 报告显示原 input 缺以下数据,导致 AI 无法做
# (1)反模式触发率分析 (2)L3 grade 分布 (3)L4 risk_tier 分布
# (4)BTC 实际走势 vs AI 判断对比。本 sprint 全部补齐。
# ============================================================


def _aggregate_anti_pattern_signals(
    conn: sqlite3.Connection, *, week_start: datetime, week_end: datetime,
) -> dict[str, Any]:
    """聚合 strategy_runs.full_state_json.layers.l3.anti_pattern_flags 触发率。

    每个反模式 5 类(extending_late_phase / against_long_cycle / chasing_breakout
    _no_pullback / failing_at_resistance / after_extreme_event_no_reset)
    分别统计触发次数 + 占总有效 run 比例。

    Returns:
      {total_runs_with_l3, anti_pattern_counts: {flag: count},
       trigger_rates: {flag: float 0-1}, top_flag: str | None}
    """
    rows = conn.execute(
        "SELECT json_extract(full_state_json,'$.layers.l3.anti_pattern_flags') "
        "FROM strategy_runs "
        "WHERE generated_at_utc >= ? AND generated_at_utc < ? "
        "  AND json_extract(full_state_json,'$.layers.l3.opportunity_grade') "
        "      IS NOT NULL",
        (_to_iso(week_start), _to_iso(week_end)),
    ).fetchall()

    counts: dict[str, int] = {}
    total = 0
    import json as _json
    for r in rows:
        raw = r[0] if not hasattr(r, "keys") else r[0]
        if raw is None:
            continue
        total += 1
        try:
            flags = _json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(flags, list):
                for f in flags:
                    if isinstance(f, str) and f:
                        counts[f] = counts.get(f, 0) + 1
        except (TypeError, ValueError):
            continue

    rates = {
        flag: round(c / total, 4) if total > 0 else 0.0
        for flag, c in counts.items()
    }
    top_flag = max(counts, key=lambda k: counts[k]) if counts else None
    return {
        "total_runs_with_l3": total,
        "anti_pattern_counts": counts,
        "trigger_rates": rates,
        "top_flag": top_flag,
    }


def _aggregate_l3_grade_distribution(
    conn: sqlite3.Connection, *, week_start: datetime, week_end: datetime,
) -> dict[str, int]:
    """聚合 L3 opportunity_grade 分布。Returns: {A, B, C, none, empty}"""
    rows = conn.execute(
        "SELECT json_extract(full_state_json, "
        "       '$.layers.l3.opportunity_grade') AS l3_grade "
        "FROM strategy_runs "
        "WHERE generated_at_utc >= ? AND generated_at_utc < ?",
        (_to_iso(week_start), _to_iso(week_end)),
    ).fetchall()
    out = {"A": 0, "B": 0, "C": 0, "none": 0, "empty": 0}
    for r in rows:
        g = r[0] if not hasattr(r, "keys") else r["l3_grade"]
        if g in ("A", "B", "C", "none"):
            out[g] += 1
        else:
            out["empty"] += 1
    return out


def _aggregate_l4_risk_tier_distribution(
    conn: sqlite3.Connection, *, week_start: datetime, week_end: datetime,
) -> dict[str, int]:
    """聚合 L4 risk_tier 分布。Returns: {low, moderate, elevated, extreme, empty}"""
    rows = conn.execute(
        "SELECT json_extract(full_state_json, "
        "       '$.layers.l4.risk_tier') AS l4r "
        "FROM strategy_runs "
        "WHERE generated_at_utc >= ? AND generated_at_utc < ?",
        (_to_iso(week_start), _to_iso(week_end)),
    ).fetchall()
    out = {"low": 0, "moderate": 0, "elevated": 0, "extreme": 0, "empty": 0}
    for r in rows:
        t = r[0] if not hasattr(r, "keys") else r["l4r"]
        if t in ("low", "moderate", "elevated", "extreme"):
            out[t] += 1
        else:
            out["empty"] += 1
    return out


def _aggregate_weekly_price_action(
    conn: sqlite3.Connection, *, week_start: datetime, week_end: datetime,
) -> dict[str, Any]:
    """从 price_candles 1d K 线读 7 天 BTC 走势(open/high/low/close)。

    Returns:
      {daily: [{date, open, high, low, close}, ...],
       week_open, week_close, week_high, week_low,
       week_pct_change, max_intra_drawdown_pct}
    """
    try:
        rows = conn.execute(
            "SELECT open_time_utc, open, high, low, close FROM price_candles "
            "WHERE timeframe = '1d' AND symbol = 'BTCUSDT' "
            "  AND open_time_utc >= ? AND open_time_utc < ? "
            "ORDER BY open_time_utc",
            (_to_iso(week_start)[:10], _to_iso(week_end)[:10] + "T23:59:59Z"),
        ).fetchall()
    except Exception:
        rows = []
    daily: list[dict[str, Any]] = []
    for r in rows:
        if hasattr(r, "keys"):
            d = {
                "date": str(r["open_time_utc"])[:10],
                "open": float(r["open"]) if r["open"] is not None else None,
                "high": float(r["high"]) if r["high"] is not None else None,
                "low": float(r["low"]) if r["low"] is not None else None,
                "close": float(r["close"]) if r["close"] is not None else None,
            }
        else:
            d = {
                "date": str(r[0])[:10],
                "open": float(r[1]) if r[1] is not None else None,
                "high": float(r[2]) if r[2] is not None else None,
                "low": float(r[3]) if r[3] is not None else None,
                "close": float(r[4]) if r[4] is not None else None,
            }
        daily.append(d)

    if not daily:
        return {
            "daily": [],
            "week_open": None, "week_close": None,
            "week_high": None, "week_low": None,
            "week_pct_change": None, "max_intra_drawdown_pct": None,
        }

    week_open = daily[0]["open"]
    week_close = daily[-1]["close"]
    week_high = max((d["high"] for d in daily if d["high"] is not None),
                    default=None)
    week_low = min((d["low"] for d in daily if d["low"] is not None),
                   default=None)
    week_pct_change = (
        round((week_close - week_open) / week_open * 100.0, 3)
        if week_open and week_close else None
    )
    # 简化 intra-week drawdown:max((d["high"] - 后续最低 low) / d["high"])
    drawdowns = []
    for i, d in enumerate(daily):
        if d["high"] is None:
            continue
        lows_after = [
            x["low"] for x in daily[i:] if x["low"] is not None
        ]
        if not lows_after:
            continue
        min_after = min(lows_after)
        drawdowns.append((min_after - d["high"]) / d["high"] * 100.0)
    max_intra_drawdown_pct = (
        round(min(drawdowns), 3) if drawdowns else None
    )
    return {
        "daily": daily,
        "week_open": week_open,
        "week_close": week_close,
        "week_high": week_high,
        "week_low": week_low,
        "week_pct_change": week_pct_change,
        "max_intra_drawdown_pct": max_intra_drawdown_pct,
    }


def _aggregate_master_runs_with_trade_plan(
    conn: sqlite3.Connection, *, week_start: datetime, week_end: datetime,
) -> list[dict[str, Any]]:
    """提取本周内 master AI 真跑通 + 给了 trade_plan 的 run(供 prompt 让 AI 对比
    系统当时判断 vs 后续实际走势)。

    Returns:
      list[{generated_at_bjt, btc_price_at_run, l3_grade, l4_risk_tier,
            master_direction, entry_zone, stop_loss, take_profit_zones}]
    """
    rows = conn.execute(
        "SELECT generated_at_bjt, btc_price_usd, fallback_level, "
        "       full_state_json FROM strategy_runs "
        "WHERE generated_at_utc >= ? AND generated_at_utc < ? "
        "  AND run_trigger IN ('scheduled', 'manual_api', 'manual') "
        "  AND (fallback_level IS NULL OR fallback_level = '') "
        "ORDER BY generated_at_utc",
        (_to_iso(week_start), _to_iso(week_end)),
    ).fetchall()

    import json as _json
    out: list[dict[str, Any]] = []
    for r in rows:
        raw = r["full_state_json"] if hasattr(r, "keys") else r[3]
        try:
            state = _json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            continue
        layers = state.get("layers") or {}
        master = layers.get("master") or {}
        l3 = layers.get("l3") or {}
        l4 = layers.get("l4") or {}
        # v1.3 schema: trade_plan
        tp = master.get("trade_plan")
        nt = master.get("new_thesis")  # v1.4
        if not (tp or nt):
            continue
        rec = {
            "generated_at_bjt": (
                r["generated_at_bjt"] if hasattr(r, "keys") else r[0]
            ),
            "btc_price_at_run": (
                r["btc_price_usd"] if hasattr(r, "keys") else r[1]
            ),
            "l3_grade": l3.get("opportunity_grade"),
            "l4_risk_tier": l4.get("risk_tier"),
        }
        if tp:
            rec.update({
                "schema": "v1.3",
                "master_direction": tp.get("direction"),
                "entry_zone": tp.get("entry_price_zone"),
                "stop_loss": tp.get("stop_loss"),
                "take_profit_zones": tp.get("take_profit_zones"),
                "position_size_pct": tp.get("position_size_pct"),
            })
        else:
            rec.update({
                "schema": "v1.4",
                "master_direction": nt.get("direction"),
                "entry_zone": [
                    o.get("price") for o in (nt.get("entry_orders") or [])
                ],
                "stop_loss": (nt.get("stop_loss") or {}).get("price"),
                "take_profit_zones": [
                    o.get("price") for o in (nt.get("take_profit") or [])
                ],
                "position_size_pct": None,
            })
        out.append(rec)
    return out


def _fetch_strategy_run_json_rows(
    conn: sqlite3.Connection, *, week_start: datetime, week_end: datetime,
) -> list[Any]:
    """Read only rows needed by evidence diagnostics."""
    return conn.execute(
        "SELECT run_id, generated_at_bjt, generated_at_utc, btc_price_usd, "
        "       full_state_json, constraint_activations_json "
        "FROM strategy_runs "
        "WHERE generated_at_utc >= ? AND generated_at_utc < ? "
        "ORDER BY generated_at_utc",
        (_to_iso(week_start), _to_iso(week_end)),
    ).fetchall()


def _aggregate_l3_diagnostics(rows: list[Any]) -> dict[str, Any]:
    """只读聚合 L3 异常解释证据;缺字段时返回空结构。"""
    phase_dist: dict[str, int] = {}
    anti_dist: dict[str, int] = {}
    grade_dist: dict[str, int] = {}
    permission_dist: dict[str, int] = {}
    anti_by_grade: dict[str, dict[str, int]] = {}
    extending_samples: list[dict[str, Any]] = []

    for r in rows:
        state = _safe_json_loads(_row_value(r, "full_state_json", 4))
        layers = _extract_layers(state)
        l2 = layers.get("l2") or state.get("layer_2") or {}
        l3 = layers.get("l3") or state.get("layer_3") or {}

        phase = (
            l2.get("phase")
            or l2.get("market_phase")
            or l3.get("phase")
            or l3.get("market_phase")
        )
        grade = l3.get("opportunity_grade") or l3.get("grade")
        permission = l3.get("execution_permission")
        anti_flags = [
            str(x) for x in _as_list(
                l3.get("anti_pattern_flags") or l3.get("anti_pattern_signals")
            )
            if x not in (None, "")
        ]

        if phase not in (None, ""):
            _count_value(phase_dist, phase)
        if grade not in (None, ""):
            _count_value(grade_dist, grade)
        if permission not in (None, ""):
            _count_value(permission_dist, permission)

        grade_key = str(grade) if grade not in (None, "") else "empty"
        anti_by_grade.setdefault(grade_key, {})
        for flag in anti_flags:
            anti_dist[flag] = anti_dist.get(flag, 0) + 1
            anti_by_grade[grade_key][flag] = (
                anti_by_grade[grade_key].get(flag, 0) + 1
            )

        if (
            "extending_late_phase" in anti_flags
            and len(extending_samples) < 10
        ):
            extending_samples.append({
                "run_id": _row_value(r, "run_id", 0),
                "run_at": (
                    _row_value(r, "generated_at_bjt", 1)
                    or _row_value(r, "generated_at_utc", 2)
                ),
                "phase": phase,
                "opportunity_grade": grade,
                "execution_permission": permission,
                "anti_pattern_signals": anti_flags,
                "master_action": _extract_master_action(state),
                "btc_price": _row_value(r, "btc_price_usd", 3),
            })

    return {
        "phase_distribution": phase_dist,
        "anti_pattern_signal_distribution": anti_dist,
        "opportunity_grade_distribution": grade_dist,
        "execution_permission_distribution": permission_dist,
        "anti_pattern_by_grade": anti_by_grade,
        "extending_late_phase_samples": extending_samples,
    }


def _aggregate_l4_diagnostics(rows: list[Any]) -> dict[str, Any]:
    """只读聚合 L4 risk_tier 异常解释证据;不改 L4 schema/阈值。"""
    tier_dist: dict[str, int] = {}
    risk_scores: list[float] = []
    cap_multipliers: list[float] = []
    breakdown_values: dict[str, list[float]] = {}
    breakdown_counts: dict[str, int] = {}
    elevated_samples: list[dict[str, Any]] = []

    for r in rows:
        state = _safe_json_loads(_row_value(r, "full_state_json", 4))
        layers = _extract_layers(state)
        l4 = layers.get("l4") or state.get("layer_4") or {}

        tier = l4.get("risk_tier")
        if tier not in (None, ""):
            _count_value(tier_dist, tier)

        risk_score = l4.get("risk_score")
        if isinstance(risk_score, (int, float)):
            risk_scores.append(float(risk_score))

        cap_mult = l4.get("position_cap_multiplier")
        if isinstance(cap_mult, (int, float)):
            cap_multipliers.append(float(cap_mult))

        risk_breakdown = l4.get("risk_breakdown") or {}
        if isinstance(risk_breakdown, dict):
            for reason, value in risk_breakdown.items():
                reason_key = str(reason)
                breakdown_counts[reason_key] = breakdown_counts.get(reason_key, 0) + 1
                if isinstance(value, (int, float)):
                    breakdown_values.setdefault(reason_key, []).append(float(value))

        if tier in ("elevated", "extreme") and len(elevated_samples) < 10:
            elevated_samples.append({
                "run_id": _row_value(r, "run_id", 0),
                "run_at": (
                    _row_value(r, "generated_at_bjt", 1)
                    or _row_value(r, "generated_at_utc", 2)
                ),
                "risk_tier": tier,
                "risk_score": risk_score,
                "position_cap_multiplier": cap_mult,
                "risk_breakdown": risk_breakdown if isinstance(risk_breakdown, dict) else {},
                "master_action": _extract_master_action(state),
                "btc_price": _row_value(r, "btc_price_usd", 3),
            })

    top_reasons = []
    for reason, count in breakdown_counts.items():
        values = breakdown_values.get(reason) or []
        top_reasons.append({
            "reason": reason,
            "count": count,
            "avg": (
                round(sum(values) / len(values), 4) if values else None
            ),
            "max": round(max(values), 4) if values else None,
        })
    top_reasons.sort(
        key=lambda x: (
            x["max"] if x["max"] is not None else -1,
            x["count"],
            x["reason"],
        ),
        reverse=True,
    )

    return {
        "risk_tier_distribution": tier_dist,
        "risk_score_summary": _numeric_summary(risk_scores),
        "position_cap_multiplier_summary": _numeric_summary(cap_multipliers),
        "risk_breakdown_top_reasons": top_reasons[:10],
        "elevated_samples": elevated_samples,
    }


def _validator_display_name(validator_key: str) -> str:
    if validator_key.startswith("validator_"):
        parts = validator_key.split("_", 2)
        if len(parts) == 3 and parts[1].isdigit():
            return f"V{parts[1]} {parts[2]}"
    return validator_key


def _activation_reason_for_validator(
    *, validator_key: str, ca: dict[str, Any], master: dict[str, Any],
) -> str:
    notes = [str(x) for x in _as_list(master.get("notes")) if x]
    if validator_key == "validator_16_change_mind":
        matched = [n for n in notes if "what_would_change_mind" in n]
        if matched:
            return "; ".join(matched[:3])
    if validator_key == "validator_23_conflict_missing":
        matched = [n for n in notes if "conflict_resolution" in n]
        if matched:
            return "; ".join(matched[:3])
    hints = [str(x) for x in _as_list(ca.get("validator_retry_hints")) if x]
    if hints:
        return "; ".join(hints[:3])
    return f"{_validator_display_name(validator_key)} triggered"


def _aggregate_validator_diagnostics(rows: list[Any]) -> dict[str, Any]:
    """只读聚合 Validator 异常解释证据;不改 Validator 判定。"""
    counts = {k: 0 for k in VALIDATOR_KEYS}
    valid_constraint_runs = 0
    missing_constraint_runs = 0
    v16_samples: list[dict[str, Any]] = []
    v23_samples: list[dict[str, Any]] = []

    for r in rows:
        ca = _safe_json_loads(_row_value(r, "constraint_activations_json", 5))
        if not ca:
            missing_constraint_runs += 1
            continue
        valid_constraint_runs += 1

        state = _safe_json_loads(_row_value(r, "full_state_json", 4))
        layers = _extract_layers(state)
        master = layers.get("master") or state.get("adjudicator") or {}
        master_action = _extract_master_action(state)

        for key in VALIDATOR_KEYS:
            if ca.get(key) is True:
                counts[key] += 1

        def _sample(validator_key: str) -> dict[str, Any]:
            return {
                "run_at": (
                    _row_value(r, "generated_at_bjt", 1)
                    or _row_value(r, "generated_at_utc", 2)
                ),
                "validator_id": validator_key.split("_")[1]
                if len(validator_key.split("_")) > 1 else validator_key,
                "validator_name": _validator_display_name(validator_key),
                "activation_reason": _activation_reason_for_validator(
                    validator_key=validator_key, ca=ca, master=master,
                ),
                "message": _activation_reason_for_validator(
                    validator_key=validator_key, ca=ca, master=master,
                ),
                "master_action": master_action,
                "what_would_change_mind": master.get("what_would_change_mind"),
                "conflict_resolution": (
                    master.get("conflict_resolution")
                    or master.get("conflict_resolution_summary")
                ),
            }

        if ca.get("validator_16_change_mind") is True and len(v16_samples) < 10:
            v16_samples.append(_sample("validator_16_change_mind"))
        if ca.get("validator_23_conflict_missing") is True and len(v23_samples) < 10:
            v23_samples.append(_sample("validator_23_conflict_missing"))

    top_triggered = [
        {
            "validator_id": key.split("_")[1],
            "validator_key": key,
            "validator_name": _validator_display_name(key),
            "activations": count,
        }
        for key, count in counts.items()
        if count > 0
    ]
    top_triggered.sort(key=lambda x: (x["activations"], x["validator_key"]), reverse=True)

    return {
        "top_triggered_validators": top_triggered[:10],
        "v16_samples": v16_samples,
        "v23_samples": v23_samples,
        "validator_sample_base": {
            "total_strategy_runs": len(rows),
            "valid_constraint_runs": valid_constraint_runs,
            "missing_constraint_runs": missing_constraint_runs,
        },
    }


def _review_recommendation_text(rec: dict[str, Any]) -> str:
    text = " ".join(
        str(rec.get(k) or "")
        for k in ("目标", "具体调整路径", "建议", "suggested_action")
    ).lower()
    return "".join(ch for ch in text if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def _recommendation_canonical_key(rec: dict[str, Any]) -> tuple[str, bool]:
    for key in (
        "normalized_recommendation_id",
        "recommendation_id",
        "id",
        "canonical_id",
        "issue_id",
    ):
        value = rec.get(key)
        if value:
            return str(value), True
    return _review_recommendation_text(rec), False


def _extract_review_metric(
    output: dict[str, Any], metric: str,
) -> tuple[Optional[int], Optional[int]]:
    if metric == "l3_extending_late_phase":
        l3_diag = output.get("l3_diagnostics") or {}
        anti_dist = l3_diag.get("anti_pattern_signal_distribution") or {}
        count = anti_dist.get("extending_late_phase")
        grade_dist = l3_diag.get("opportunity_grade_distribution") or {}
        total = sum(v for v in grade_dist.values() if isinstance(v, int))
        anti_pat = output.get("anti_pattern_signals") or {}
        if count is None:
            count = (anti_pat.get("anti_pattern_counts") or {}).get(
                "extending_late_phase",
            )
        if not total:
            total = anti_pat.get("total_runs_with_l3")
        return (
            int(count) if isinstance(count, int) else None,
            int(total) if isinstance(total, int) and total >= 0 else None,
        )

    if metric == "l4_elevated":
        l4_diag = output.get("l4_diagnostics") or {}
        tier_dist = (
            l4_diag.get("risk_tier_distribution")
            or output.get("l4_risk_tier_distribution")
            or {}
        )
        count = tier_dist.get("elevated")
        total = sum(v for v in tier_dist.values() if isinstance(v, int))
        return (
            int(count) if isinstance(count, int) else None,
            int(total) if isinstance(total, int) and total >= 0 else None,
        )

    if metric in ("validator_16_change_mind", "validator_23_conflict_missing"):
        hc = output.get("hard_constraint_activation_review") or {}
        row = hc.get(metric) or {}
        count = row.get("activations")
        parsed_count, parsed_total = _parse_rate_count_total(row.get("rate"))
        return (
            int(count) if isinstance(count, int) else parsed_count,
            parsed_total,
        )

    return None, None


def _current_temporal_week(
    *,
    week_start: datetime,
    anti_pattern: dict[str, Any],
    l4_risk_dist: dict[str, int],
    constraints: dict[str, Any],
    theses: dict[str, Any],
    orders: dict[str, int],
) -> dict[str, Any]:
    week_start_utc = _to_iso(week_start)[:10]
    valid_runs = (constraints.get("sample_base") or {}).get("valid_constraint_runs")
    v_raw = constraints.get("v_activations_raw") or {}
    l3_total = anti_pattern.get("total_runs_with_l3")
    l3_count = (anti_pattern.get("anti_pattern_counts") or {}).get(
        "extending_late_phase", 0,
    )
    l4_total = sum(v for v in l4_risk_dist.values() if isinstance(v, int))
    return {
        "week_start_utc": week_start_utc,
        "l3_extending_late_phase": _trend_point(
            week_start_utc=week_start_utc, count=int(l3_count or 0),
            total=int(l3_total or 0), source="current_strategy_runs",
        ),
        "l4_elevated": _trend_point(
            week_start_utc=week_start_utc,
            count=int(l4_risk_dist.get("elevated") or 0),
            total=int(l4_total or 0), source="current_strategy_runs",
        ),
        "validator_v16": _trend_point(
            week_start_utc=week_start_utc,
            count=int((v_raw.get("validator_16_change_mind") or {}).get("activations") or 0),
            total=int(valid_runs or 0), source="current_strategy_runs",
        ),
        "validator_v23": _trend_point(
            week_start_utc=week_start_utc,
            count=int((v_raw.get("validator_23_conflict_missing") or {}).get("activations") or 0),
            total=int(valid_runs or 0), source="current_strategy_runs",
        ),
        "thesis_creation": _trend_point(
            week_start_utc=week_start_utc,
            value=int(theses.get("thesis_created") or 0),
            source="current_strategy_runs",
        ),
        "trade_execution": _trend_point(
            week_start_utc=week_start_utc,
            value=int(orders.get("orders_filled") or 0),
            source="current_virtual_orders",
        ),
    }


def _streak_from_points(
    points: list[dict[str, Any]], predicate: Any,
) -> int:
    streak = 0
    for p in points[:8]:
        if predicate(p):
            streak += 1
        else:
            break
    return streak


def _aggregate_temporal_consistency_diagnostics(
    conn: sqlite3.Connection,
    *,
    week_start: datetime,
    anti_pattern: dict[str, Any],
    l4_risk_dist: dict[str, int],
    constraints: dict[str, Any],
    theses: dict[str, Any],
    orders: dict[str, int],
) -> dict[str, Any]:
    """只读聚合时间连续性诊断;旧周报缺字段时返回空/跳过,不抛异常。"""
    current = _current_temporal_week(
        week_start=week_start, anti_pattern=anti_pattern,
        l4_risk_dist=l4_risk_dist, constraints=constraints,
        theses=theses, orders=orders,
    )
    trends = {
        "l3_extending_late_phase_trend": [current["l3_extending_late_phase"]],
        "l4_elevated_trend": [current["l4_elevated"]],
        "validator_v16_trend": [current["validator_v16"]],
        "validator_v23_trend": [current["validator_v23"]],
        "thesis_creation_trend": [current["thesis_creation"]],
        "trade_execution_trend": [current["trade_execution"]],
    }

    recommendation_seen: dict[str, dict[str, Any]] = {}
    try:
        rows = conn.execute(
            "SELECT week_start_utc, output_json FROM weekly_reviews "
            "WHERE week_start_utc < ? "
            "ORDER BY week_start_utc DESC LIMIT 12",
            (_to_iso(week_start)[:10],),
        ).fetchall()
    except Exception:
        rows = []

    for row in rows:
        week_key = _row_value(row, "week_start_utc", 0)
        output = _safe_json_loads(_row_value(row, "output_json", 1))
        if not output:
            continue

        for metric, trend_key in (
            ("l3_extending_late_phase", "l3_extending_late_phase_trend"),
            ("l4_elevated", "l4_elevated_trend"),
            ("validator_16_change_mind", "validator_v16_trend"),
            ("validator_23_conflict_missing", "validator_v23_trend"),
        ):
            count, total = _extract_review_metric(output, metric)
            if count is None and total is None:
                continue
            trends[trend_key].append(_trend_point(
                week_start_utc=str(week_key), count=count, total=total,
                source="weekly_reviews",
            ))

        perf = output.get("performance_summary") or {}
        if isinstance(perf.get("thesis_created"), int):
            trends["thesis_creation_trend"].append(_trend_point(
                week_start_utc=str(week_key),
                value=int(perf["thesis_created"]),
                source="weekly_reviews",
            ))
        trades = perf.get("total_trades")
        if trades is None:
            trades = perf.get("orders_filled")
        if isinstance(trades, int):
            trends["trade_execution_trend"].append(_trend_point(
                week_start_utc=str(week_key),
                value=int(trades),
                source="weekly_reviews",
            ))

        for rec in output.get("adjustment_recommendations") or []:
            if not isinstance(rec, dict):
                continue
            key, has_canonical_id = _recommendation_canonical_key(rec)
            if not key:
                continue
            item = recommendation_seen.setdefault(key, {
                "recommendation_id": key,
                "category": rec.get("recommendation_category") or rec.get("category"),
                "target": (
                    rec.get("recommendation_target")
                    or rec.get("target")
                    or rec.get("目标")
                    or ""
                ),
                "recommendation_target": (
                    rec.get("recommendation_target")
                    or rec.get("target")
                    or rec.get("目标")
                    or ""
                ),
                "action_type": (
                    rec.get("recommendation_action_type")
                    or rec.get("action_type")
                ),
                "action": (
                    rec.get("具体调整路径")
                    or rec.get("建议")
                    or rec.get("suggested_action")
                    or ""
                ),
                "weeks_seen": 0,
                "recent_weeks": [],
                "last_seen": str(week_key),
                "confidence_levels_seen": [],
                "latest_priority": rec.get("优先级"),
                "latest_severity": rec.get("severity") or rec.get("严重级别"),
                "latest_evidence_confidence": (
                    rec.get("evidence_confidence")
                    or rec.get("confidence")
                    or rec.get("confidence_level")
                ),
                "key_source": "recommendation_id" if has_canonical_id else "text",
            })
            item["weeks_seen"] += 1
            confidence = (
                rec.get("evidence_confidence")
                or rec.get("confidence")
                or rec.get("confidence_level")
            )
            if confidence and confidence not in item["confidence_levels_seen"]:
                item["confidence_levels_seen"].append(confidence)
            if len(item["recent_weeks"]) < 8:
                item["recent_weeks"].append(str(week_key))

    for key in trends:
        trends[key] = trends[key][:8]

    recurrence = [
        item for item in recommendation_seen.values()
        if item.get("weeks_seen", 0) >= 2
    ]
    recurrence.sort(
        key=lambda x: (x.get("weeks_seen", 0), x.get("recent_weeks", [""])[0]),
        reverse=True,
    )

    l3_points = trends["l3_extending_late_phase_trend"]
    l4_points = trends["l4_elevated_trend"]
    v16_points = trends["validator_v16_trend"]
    v23_points = trends["validator_v23_trend"]
    thesis_points = trends["thesis_creation_trend"]
    trade_points = trends["trade_execution_trend"]
    anomaly_streaks = {
        "l3_extending_late_phase_weeks": _streak_from_points(
            l3_points, lambda p: (p.get("rate") or 0) > 0.4,
        ),
        "l4_elevated_weeks": _streak_from_points(
            l4_points, lambda p: (p.get("rate") or 0) > 0.5,
        ),
        "validator_v16_high_weeks": _streak_from_points(
            v16_points, lambda p: (p.get("rate") or 0) > 0.4,
        ),
        "validator_v23_high_weeks": _streak_from_points(
            v23_points, lambda p: (p.get("rate") or 0) > 0.4,
        ),
        "zero_thesis_weeks": _streak_from_points(
            thesis_points, lambda p: p.get("value") == 0,
        ),
        "zero_trade_weeks": _streak_from_points(
            trade_points, lambda p: p.get("value") == 0,
        ),
        "recent_weeks": [
            {
                "week_start_utc": p.get("week_start_utc"),
                "l3_extending_late_phase_rate": p.get("rate"),
            }
            for p in l3_points[:8]
        ],
    }

    return {
        **trends,
        "recommendation_recurrence": recurrence[:10],
        "anomaly_streaks": anomaly_streaks,
    }


# ============================================================
# 入口:build_weekly_review_input
# ============================================================

def build_weekly_review_input(
    conn: sqlite3.Connection,
    *,
    now_utc: Optional[datetime] = None,
    window_days: int = 7,
) -> dict[str, Any]:
    """7 类输入聚合,返完整 weekly_review_analyst input dict。

    Args:
        conn: SQLite 连接(只读)
        now_utc: 评估时点(测试可注入),默认 datetime.now(timezone.utc)
        window_days: 回看窗口(默认 7 天 = v1.4 周复盘)

    Returns:
      {
        "window": {"start_utc", "end_utc", "days"},
        "performance_summary_raw": {strategy_runs + theses + virtual_orders +
                                     virtual_account 算的 7 字段 + },
        "system_health_diagnosis_raw": {retry_log + fuse + states},
        "hard_constraint_activation_review_raw": {23 V + meta},
        "context": {current_virtual_account, equity_curve_7d}
      }

    AI 收到此 dict 后填 evaluation 文本 + 输出最终 5 段 JSON。
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    week_end = now_utc
    week_start = now_utc - timedelta(days=window_days)

    runs = _aggregate_strategy_runs(conn, week_start=week_start, week_end=week_end)
    theses = _aggregate_theses(conn, week_start=week_start, week_end=week_end)
    orders = _aggregate_virtual_orders(conn, week_start=week_start, week_end=week_end)
    retry = _aggregate_retry_log(conn, week_start=week_start, week_end=week_end)
    va = _aggregate_virtual_account(conn, week_start=week_start, week_end=week_end)
    fuse_states = _aggregate_fuse_and_states(
        conn, week_start=week_start, week_end=week_end,
    )
    constraints = _aggregate_constraint_activations(
        conn, week_start=week_start, week_end=week_end,
        window_days=window_days,
    )
    # Sprint H Part B:4 个新聚合
    anti_pattern = _aggregate_anti_pattern_signals(
        conn, week_start=week_start, week_end=week_end,
    )
    l3_grade_dist = _aggregate_l3_grade_distribution(
        conn, week_start=week_start, week_end=week_end,
    )
    l4_risk_dist = _aggregate_l4_risk_tier_distribution(
        conn, week_start=week_start, week_end=week_end,
    )
    price_action = _aggregate_weekly_price_action(
        conn, week_start=week_start, week_end=week_end,
    )
    master_runs_with_plan = _aggregate_master_runs_with_trade_plan(
        conn, week_start=week_start, week_end=week_end,
    )
    diagnostic_rows = _fetch_strategy_run_json_rows(
        conn, week_start=week_start, week_end=week_end,
    )
    l3_diagnostics = _aggregate_l3_diagnostics(diagnostic_rows)
    l4_diagnostics = _aggregate_l4_diagnostics(diagnostic_rows)
    validator_diagnostics = _aggregate_validator_diagnostics(diagnostic_rows)
    temporal_consistency_diagnostics = (
        _aggregate_temporal_consistency_diagnostics(
            conn,
            week_start=week_start,
            anti_pattern=anti_pattern,
            l4_risk_dist=l4_risk_dist,
            constraints=constraints,
            theses=theses,
            orders=orders,
        )
    )

    # 装配 performance_summary_raw(对齐 §3.3.9 schema 7 字段)
    performance_raw = {
        "total_runs": runs["total_runs"],
        "successful_runs": runs["successful_runs"],
        "ai_failures": runs["ai_failures"],
        "thesis_created": theses["thesis_created"],
        "thesis_closed_profit": theses["thesis_closed_profit"],
        "thesis_closed_loss": theses["thesis_closed_loss"],
        "weekly_pnl_pct": va["weekly_pnl_pct"],
        "max_drawdown_pct": va["max_drawdown_pct"],
    }

    # 当前 virtual_account snapshot
    current_va_row = conn.execute(
        "SELECT * FROM virtual_account "
        "ORDER BY snapshot_at_utc DESC LIMIT 1"
    ).fetchone()
    current_va = dict(current_va_row) if current_va_row is not None else None

    return {
        "window": {
            "start_utc": _to_iso(week_start),
            "end_utc": _to_iso(week_end),
            "days": window_days,
        },
        "performance_summary_raw": performance_raw,
        "thesis_lifecycle": theses,
        "virtual_orders_aggregate": orders,
        "retry_log_aggregate": retry,
        "virtual_account_window": va,
        "fuse_and_states": fuse_states,
        "hard_constraint_activation_raw": {
            "v_activations": constraints["v_activations_raw"],
            "position_cap_compressed_avg": constraints["position_cap_compressed_avg"],
            "thesis_lock_blocks_count": constraints["thesis_lock_blocks_count"],
            "channel_c_uses_count": fuse_states["channel_c_used_count"],
            "review_pending_triggers": fuse_states["review_pending_triggers"],
            "total_days_in_window": constraints["total_days_in_window"],
            "sample_base": constraints["sample_base"],
        },
        "context": {
            "current_virtual_account": current_va,
            "now_utc": _to_iso(now_utc),
        },
        # Sprint H Part B(2026-05-09):4 个新聚合 + 1 个 master 决策快照
        "anti_pattern_signals": anti_pattern,
        "l3_grade_distribution": l3_grade_dist,
        "l4_risk_tier_distribution": l4_risk_dist,
        "weekly_price_action": price_action,
        "master_runs_with_trade_plan": master_runs_with_plan,
        "sample_base": constraints["sample_base"],
        "l3_diagnostics": l3_diagnostics,
        "l4_diagnostics": l4_diagnostics,
        "validator_diagnostics": validator_diagnostics,
        "temporal_consistency_diagnostics": temporal_consistency_diagnostics,
    }
