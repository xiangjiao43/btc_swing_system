"""
alerts.py — Sprint 1.16c 告警检测

check_alerts(conn, lookback_hours=24) 扫最近窗口内的:
  * fallback_log:按 triggered_by 聚合
  * strategy_state_history:最新 N 条,用来查 AI 成功率 / 冷启动卡住

返回 list[dict],按 (level desc, last_seen desc) 排序。level 取值:
level_1 / level_2 / level_3。

告警规则(默认值可调):
  1. ai_high_failure_rate      AI 失败率 > 30% 且样本 ≥ 5 次 → level_2
  2. collector_consecutive_fail 某 collector 在窗口内失败 > 3 次 → level_2
  3. collector_mass_failure     同时多个 collector(≥ 2)在最近 1h 内失败 → level_3
  4. cold_start_stuck           最新 state warming_up=True 且 runs_completed
                                在 12h 内未增长 → level_1
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Optional


logger = logging.getLogger(__name__)


# Collector-like 阶段(失败往往意味着外部数据源出问题)。
# 目前 pipeline 里和数据采集直接相关的是 macro_headwind / event_risk / layer_5。
DEFAULT_COLLECTOR_STAGES: tuple[str, ...] = (
    "composite.macro_headwind",
    "composite.event_risk",
    "layer_5",
)


_LEVEL_ORDER: dict[str, int] = {"level_1": 1, "level_2": 2, "level_3": 3}


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


# ============================================================
# Individual checks
# ============================================================

def _check_ai_failure_rate(
    rows: list[dict[str, Any]],
    *,
    failure_rate_threshold: float = 0.3,
    min_samples: int = 5,
) -> Optional[dict[str, Any]]:
    ai_total = 0
    ai_fail = 0
    adj_total = 0
    adj_fail = 0
    first_seen = None
    last_seen = None
    for r in rows:
        state = r.get("state") or {}
        ctx = state.get("context_summary") or {}
        if ctx.get("status"):
            ai_total += 1
            if str(ctx.get("status")).startswith("degraded"):
                ai_fail += 1
        adj = state.get("adjudicator") or {}
        if adj.get("status"):
            adj_total += 1
            if str(adj.get("status")).startswith("degraded"):
                adj_fail += 1
        ts = r.get("run_timestamp_utc")
        if ts:
            if first_seen is None or ts < first_seen:
                first_seen = ts
            if last_seen is None or ts > last_seen:
                last_seen = ts

    rate_ai = (ai_fail / ai_total) if ai_total else 0.0
    rate_adj = (adj_fail / adj_total) if adj_total else 0.0
    worst_rate = max(rate_ai, rate_adj)
    total_samples = max(ai_total, adj_total)
    if worst_rate > failure_rate_threshold and total_samples >= min_samples:
        return {
            "level": "level_2",
            "type": "ai_high_failure_rate",
            "stage": "ai_summary/adjudicator",
            "count": ai_fail + adj_fail,
            "first_seen": first_seen,
            "last_seen": last_seen,
            "message": (
                f"AI 调用失败率过高:summary {ai_fail}/{ai_total} "
                f"({rate_ai:.0%}),adjudicator {adj_fail}/{adj_total} "
                f"({rate_adj:.0%})。阈值 {failure_rate_threshold:.0%}。"
            ),
        }
    return None


def _check_collector_streaks(
    conn: sqlite3.Connection,
    *,
    since_utc: str,
    collector_stages: tuple[str, ...],
    streak_threshold: int = 3,
) -> list[dict[str, Any]]:
    """返回 level_2 告警列表:某 collector 在窗口内失败 > N 次。"""
    alerts: list[dict[str, Any]] = []
    for stage in collector_stages:
        triggered_by = f"pipeline.{stage}"
        row = conn.execute(
            "SELECT COUNT(*) AS n, MIN(triggered_at_utc) AS first_seen, "
            "MAX(triggered_at_utc) AS last_seen "
            "FROM fallback_events "
            "WHERE reason = ? AND triggered_at_utc >= ?",
            (triggered_by, since_utc),
        ).fetchone()
        if not row:
            continue
        count = int(row["n"] or 0)
        if count > streak_threshold:
            alerts.append({
                "level": "level_2",
                "type": "collector_consecutive_fail",
                "stage": stage,
                "count": count,
                "first_seen": row["first_seen"],
                "last_seen": row["last_seen"],
                "message": (
                    f"{stage} 在近期窗口内失败 {count} 次(> {streak_threshold}),"
                    "疑似数据源异常。"
                ),
            })
    return alerts


def _check_collector_mass_failure(
    conn: sqlite3.Connection,
    *,
    mass_window_hours: int,
    collector_stages: tuple[str, ...],
    now_utc: datetime,
    min_distinct: int = 2,
) -> Optional[dict[str, Any]]:
    """短窗口(默认 1h)内 ≥ min_distinct 个 collector 失败 → level_3。"""
    cutoff = _iso(now_utc - timedelta(hours=mass_window_hours))
    placeholders = ",".join(["?"] * len(collector_stages))
    triggered_by_list = [f"pipeline.{s}" for s in collector_stages]
    rows = conn.execute(
        f"""
        SELECT reason AS triggered_by, COUNT(*) AS n,
               MIN(triggered_at_utc) AS first_seen,
               MAX(triggered_at_utc) AS last_seen
          FROM fallback_events
         WHERE reason IN ({placeholders})
           AND triggered_at_utc >= ?
      GROUP BY reason
        """,
        tuple(triggered_by_list) + (cutoff,),
    ).fetchall()
    distinct = len(rows)
    if distinct >= min_distinct:
        stage_names = [
            (r["triggered_by"] or "").split(".", 1)[1]
            for r in rows
        ]
        return {
            "level": "level_3",
            "type": "collector_mass_failure",
            "stage": "+".join(stage_names),
            "count": sum(int(r["n"] or 0) for r in rows),
            "first_seen": min((r["first_seen"] for r in rows), default=None),
            "last_seen": max((r["last_seen"] for r in rows), default=None),
            "message": (
                f"近 {mass_window_hours}h 内 {distinct} 个 collector 同时失败"
                f"({', '.join(stage_names)}),疑似数据断流。"
            ),
        }
    return None


def _check_cold_start_stuck(
    rows: list[dict[str, Any]],
    *,
    now_utc: datetime,
    stuck_hours: float = 12.0,
) -> Optional[dict[str, Any]]:
    if not rows:
        return None
    latest = rows[-1]
    state = latest.get("state") or {}
    cs = state.get("cold_start") or {}
    if not cs.get("warming_up"):
        return None

    latest_runs = int(cs.get("runs_completed") or 0)
    latest_ts = _parse_iso(latest.get("run_timestamp_utc"))
    if latest_ts is None:
        return None

    # 找 stuck_hours 之前最后一条同样 warming_up 的状态
    earlier_ref_ts = now_utc - timedelta(hours=stuck_hours)
    earlier: Optional[dict[str, Any]] = None
    for r in reversed(rows[:-1]):
        ts = _parse_iso(r.get("run_timestamp_utc"))
        if ts is None:
            continue
        if ts <= earlier_ref_ts:
            earlier = r
            break
    if earlier is None:
        return None
    earlier_cs = (earlier.get("state") or {}).get("cold_start") or {}
    earlier_runs = int(earlier_cs.get("runs_completed") or 0)

    if latest_runs <= earlier_runs:
        return {
            "level": "level_1",
            "type": "cold_start_stuck",
            "stage": "cold_start",
            "count": latest_runs,
            "first_seen": earlier.get("run_timestamp_utc"),
            "last_seen": latest.get("run_timestamp_utc"),
            "message": (
                f"冷启动进度卡住:runs_completed 在 {stuck_hours}h 内 "
                f"未从 {earlier_runs} 增长(当前 {latest_runs}/"
                f"{cs.get('threshold', 42)})。"
            ),
        }
    return None


# ============================================================
# check_alerts entry point
# ============================================================

def check_alerts(
    conn: sqlite3.Connection,
    *,
    lookback_hours: int = 24,
    collector_stages: tuple[str, ...] = DEFAULT_COLLECTOR_STAGES,
    mass_failure_window_hours: int = 1,
    now_utc: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    now = now_utc or datetime.now(timezone.utc)
    since_dt = now - timedelta(hours=lookback_hours)
    since_iso = _iso(since_dt)

    # strategy_runs 最近 N 条(Sprint 1.5c C4 对齐 §10.4)
    try:
        rows = conn.execute(
            "SELECT reference_timestamp_utc AS run_timestamp_utc, "
            "full_state_json AS state_json FROM strategy_runs "
            "WHERE reference_timestamp_utc >= ? "
            "ORDER BY reference_timestamp_utc ASC",
            (since_iso,),
        ).fetchall()
        state_rows: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            try:
                d["state"] = json.loads(d.pop("state_json"))
            except (json.JSONDecodeError, ValueError, TypeError):
                d["state"] = {}
            state_rows.append(d)
    except sqlite3.OperationalError:
        state_rows = []

    alerts: list[dict[str, Any]] = []

    # 1. AI failure rate
    ai_alert = _check_ai_failure_rate(state_rows)
    if ai_alert:
        alerts.append(ai_alert)

    # 2. collector streaks (level_2)
    alerts.extend(_check_collector_streaks(
        conn,
        since_utc=since_iso,
        collector_stages=collector_stages,
    ))

    # 3. mass failure (level_3)
    mass = _check_collector_mass_failure(
        conn,
        mass_window_hours=mass_failure_window_hours,
        collector_stages=collector_stages,
        now_utc=now,
    )
    if mass:
        alerts.append(mass)

    # 4. cold start stuck (level_1)
    cs_alert = _check_cold_start_stuck(state_rows, now_utc=now)
    if cs_alert:
        alerts.append(cs_alert)

    # 按 level desc, last_seen desc 排序
    alerts.sort(
        key=lambda a: (
            _LEVEL_ORDER.get(a.get("level") or "", 0),
            a.get("last_seen") or "",
        ),
        reverse=True,
    )
    return alerts
