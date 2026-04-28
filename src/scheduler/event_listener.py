"""src/scheduler/event_listener.py — Sprint 2.7-D 事件触发监听器。

**职责**:每 60 秒由 `job_event_listener` 调用一次,扫描 4 类 event,
返回本次应触发的 event_type 列表(给 caller 决定是否 enqueue pipeline_run)。

**4 种 event**(对照用户 Sprint 2.7-D spec):

| event_type | 触发条件 | 节流 |
|---|---|---|
| event_invalidation | 当前 1h close 跌破/突破 lifecycle.hard_invalidation_level | event_throttle 2h 冷却 |
| event_price | 当前 1h close vs 24h 前 1h close 变化 ≥ ±3% | event_throttle 2h 冷却 + 距上次 scheduled run < 30 min 跳过 |
| event_macro | events_calendar 行 utc_trigger_time + 15min 命中(且 impact_level ≥ 2) | events_calendar.triggered_at_utc 防重 |
| event_onchain | (不在 check_and_trigger_events 里;由 job_collect_onchain 成功后直接 enqueue) | 不需要冷却 |

**调用契约**:
    triggered = check_and_trigger_events(conn)
    # 返回 list[str],每个值 ∈ {'event_invalidation', 'event_price', 'event_macro'}
    # 对每个 type, 内部已经写了 event_throttle 或 events_calendar.triggered_at_utc
    # caller 只需根据返回的 type 决定 enqueue 多少次 pipeline_run。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Optional


logger = logging.getLogger(__name__)


_THROTTLE_DEFAULT_SEC = 7200  # 2h
_PRICE_CHANGE_THRESHOLD = 0.03  # ±3%
_PRICE_RECENT_RUN_THROTTLE_SEC = 1800  # 30 min
_MACRO_TRIGGER_OFFSET_SEC = 15 * 60  # event utc_trigger + 15 min
_MACRO_WINDOW_SEC = 60  # 与 event_listener cron 周期匹配
_MACRO_MIN_IMPACT = 2  # 只对 medium/high 触发


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s: str) -> Optional[datetime]:
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


# ============================================================
# Throttle helpers
# ============================================================

def _is_throttled(
    conn: sqlite3.Connection,
    event_type: str,
    *,
    cooldown_sec: int = _THROTTLE_DEFAULT_SEC,
    now: Optional[datetime] = None,
) -> bool:
    """查 event_throttle:若 last_triggered_at_utc 距 now < cooldown_sec 则节流。"""
    now = now or _now_utc()
    row = conn.execute(
        "SELECT last_triggered_at_utc FROM event_throttle WHERE event_type = ?",
        (event_type,),
    ).fetchone()
    if row is None:
        return False
    last = _parse_iso(row[0] if not hasattr(row, "keys") else row["last_triggered_at_utc"])
    if last is None:
        return False
    return (now - last).total_seconds() < cooldown_sec


def _record_trigger(
    conn: sqlite3.Connection,
    event_type: str,
    now: Optional[datetime] = None,
) -> None:
    """写 event_throttle.last_triggered_at_utc。"""
    now_iso = _to_iso(now or _now_utc())
    conn.execute(
        "INSERT INTO event_throttle (event_type, last_triggered_at_utc) "
        "VALUES (?, ?) "
        "ON CONFLICT(event_type) DO UPDATE SET "
        "  last_triggered_at_utc = excluded.last_triggered_at_utc",
        (event_type, now_iso),
    )


# ============================================================
# event_invalidation
# ============================================================

def _check_event_invalidation(
    conn: sqlite3.Connection,
    *,
    now: Optional[datetime] = None,
) -> bool:
    """读最新 strategy_state lifecycle.hard_invalidation_levels + 当前 1h close。

    long 仓:close < hard_invalidation_level → 触发
    short 仓:close > hard_invalidation_level → 触发
    无 lifecycle / 无 hard_invalidation_levels / 无 1h close → 跳过(返回 False)
    节流:event_throttle 2h 冷却。
    """
    now = now or _now_utc()
    if _is_throttled(conn, "event_invalidation", now=now):
        return False

    # 最新 strategy_run lifecycle 块
    row = conn.execute(
        "SELECT full_state_json FROM strategy_runs "
        "ORDER BY generated_at_utc DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return False
    try:
        state = json.loads(row[0] if not hasattr(row, "keys") else row["full_state_json"])
    except Exception:
        return False

    lifecycle = state.get("lifecycle") or {}
    direction = (lifecycle.get("direction") or "").lower()
    if direction not in ("long", "short"):
        return False

    # hard_invalidation_levels 从 layer_4_output 取(modeling §4.5.4)
    l4 = ((state.get("evidence_reports") or {}).get("layer_4")) or {}
    invalidation_levels = l4.get("hard_invalidation_levels") or []
    if not invalidation_levels:
        return False
    # 取第一个数值类型的 level
    level: Optional[float] = None
    for entry in invalidation_levels:
        if isinstance(entry, (int, float)):
            level = float(entry)
            break
        if isinstance(entry, dict):
            v = entry.get("price") or entry.get("level") or entry.get("value")
            try:
                level = float(v) if v is not None else None
            except Exception:
                continue
            if level is not None:
                break
    if level is None:
        return False

    # 最新 1h close
    close_row = conn.execute(
        "SELECT close FROM price_candles "
        "WHERE timeframe = '1h' "
        "ORDER BY open_time_utc DESC LIMIT 1"
    ).fetchone()
    if close_row is None:
        return False
    close = float(close_row[0] if not hasattr(close_row, "keys") else close_row["close"])

    breach = (
        (direction == "long" and close < level)
        or (direction == "short" and close > level)
    )
    if not breach:
        return False

    _record_trigger(conn, "event_invalidation", now=now)
    logger.warning(
        "event_invalidation TRIGGERED: direction=%s close=%.2f level=%.2f",
        direction, close, level,
    )
    return True


# ============================================================
# event_price
# ============================================================

def _check_event_price(
    conn: sqlite3.Connection,
    *,
    now: Optional[datetime] = None,
) -> bool:
    """24h 前 1h close vs 当前 1h close,变化 ≥ ±3% 触发。

    额外节流:距上次 run_trigger='scheduled' < 30 min 跳过(避免跟刚跑完的常规档撞车)。
    """
    now = now or _now_utc()
    if _is_throttled(conn, "event_price", now=now):
        return False

    # 距上次 scheduled run < 30 min → 跳过
    last_sched_row = conn.execute(
        "SELECT generated_at_utc FROM strategy_runs "
        "WHERE run_trigger LIKE 'scheduled%' "
        "ORDER BY generated_at_utc DESC LIMIT 1"
    ).fetchone()
    if last_sched_row is not None:
        last_sched = _parse_iso(
            last_sched_row[0] if not hasattr(last_sched_row, "keys")
            else last_sched_row["generated_at_utc"]
        )
        if last_sched and (now - last_sched).total_seconds() < _PRICE_RECENT_RUN_THROTTLE_SEC:
            return False

    # 取最新 1h close
    latest_row = conn.execute(
        "SELECT open_time_utc, close FROM price_candles "
        "WHERE timeframe = '1h' "
        "ORDER BY open_time_utc DESC LIMIT 1"
    ).fetchone()
    if latest_row is None:
        return False
    latest_ts = (
        latest_row[0] if not hasattr(latest_row, "keys") else latest_row["open_time_utc"]
    )
    latest_close = float(
        latest_row[1] if not hasattr(latest_row, "keys") else latest_row["close"]
    )

    # 24h 前 1h close
    ts24h = _parse_iso(latest_ts)
    if ts24h is None:
        return False
    target_24h_ago = ts24h - timedelta(hours=24)
    target_iso = _to_iso(target_24h_ago)
    prior_row = conn.execute(
        "SELECT close FROM price_candles "
        "WHERE timeframe = '1h' AND open_time_utc <= ? "
        "ORDER BY open_time_utc DESC LIMIT 1",
        (target_iso,),
    ).fetchone()
    if prior_row is None:
        return False
    prior_close = float(
        prior_row[0] if not hasattr(prior_row, "keys") else prior_row["close"]
    )
    if prior_close <= 0:
        return False

    pct_change = (latest_close - prior_close) / prior_close
    if abs(pct_change) < _PRICE_CHANGE_THRESHOLD:
        return False

    _record_trigger(conn, "event_price", now=now)
    logger.warning(
        "event_price TRIGGERED: pct_change=%+.2f%% (latest %.2f vs 24h %.2f)",
        pct_change * 100, latest_close, prior_close,
    )
    return True


# ============================================================
# event_macro
# ============================================================

def _check_event_macro(
    conn: sqlite3.Connection,
    *,
    now: Optional[datetime] = None,
) -> bool:
    """events_calendar 命中:utc_trigger_time + 15min 落在过去 60s 内
    AND triggered_at_utc IS NULL AND impact_level >= 2。

    命中 → 写 triggered_at_utc + 返回 True(不走 event_throttle,
    每个 calendar 行天然只触发 1 次)。
    """
    now = now or _now_utc()
    # 触发窗:[now - 60s + 15min OFFSET, now + 15min OFFSET) 反推:
    #   now - 16min < utc_trigger_time <= now - 15min
    upper = now - timedelta(seconds=_MACRO_TRIGGER_OFFSET_SEC)
    lower = upper - timedelta(seconds=_MACRO_WINDOW_SEC)

    row = conn.execute(
        "SELECT event_id, event_type, event_name, utc_trigger_time, impact_level "
        "FROM events_calendar "
        "WHERE utc_trigger_time IS NOT NULL "
        "  AND triggered_at_utc IS NULL "
        "  AND impact_level >= ? "
        "  AND utc_trigger_time > ? "
        "  AND utc_trigger_time <= ? "
        "ORDER BY utc_trigger_time DESC LIMIT 1",
        (_MACRO_MIN_IMPACT, _to_iso(lower), _to_iso(upper)),
    ).fetchone()
    if row is None:
        return False

    event_id = row[0] if not hasattr(row, "keys") else row["event_id"]
    name = row[2] if not hasattr(row, "keys") else row["event_name"]
    conn.execute(
        "UPDATE events_calendar SET triggered_at_utc = ? WHERE event_id = ?",
        (_to_iso(now), event_id),
    )
    logger.warning(
        "event_macro TRIGGERED: event_id=%s name=%s", event_id, name,
    )
    return True


# ============================================================
# 公开入口
# ============================================================

def check_and_trigger_events(
    conn: sqlite3.Connection,
    *,
    now: Optional[datetime] = None,
) -> list[str]:
    """每 60s 调一次。返回本次触发的 event_type 列表。

    内部已写 event_throttle / events_calendar.triggered_at_utc(防重在 DAO 层)。
    caller(job_event_listener)按返回值 enqueue pipeline_run。

    顺序:invalidation > price > macro。任一失败被 catch 不阻塞其他。
    """
    triggered: list[str] = []

    for fn, evt in (
        (_check_event_invalidation, "event_invalidation"),
        (_check_event_price, "event_price"),
        (_check_event_macro, "event_macro"),
    ):
        try:
            if fn(conn, now=now):
                triggered.append(evt)
        except Exception as e:
            logger.warning("event_listener.%s exception: %s", evt, e)

    if triggered:
        try:
            conn.commit()
        except Exception:
            pass
    return triggered
