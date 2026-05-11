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
    - 23 条 V 激活次数(每条 'activations' / 'rate' 'N/valid_runs valid_runs')
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

    AI 收到此 dict 后填 evaluation 文本 + 输出最终 4 段 JSON。
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
    }
