"""src/scheduler/event_listener.py — Sprint 1.10-G v1.4 §6.2.3 改造版本。

**职责**:每 60 秒由 `job_event_listener` 调用一次,扫描 2 类 event,
返回本次应触发的 event_type 列表(给 caller 决定是否 enqueue pipeline_run)。

**剩余 2 种 event**(Sprint 1.10-G §X 拆分后):

| event_type | 触发条件 | 节流 |
|---|---|---|
| event_price | 双轨:空仓 ±5% / 持仓 ±3%(vs 上次任一 strategy_run baseline) | EventTrigger:event_price 类 2h cooldown + 距上次主 run < 30min 跳过 |
| event_macro | events_calendar 行 utc_trigger_time + 15min 命中(且 impact_level ≥ 2) | events_calendar.triggered_at_utc 防重 |

**§X Sprint 1.10-G 拆出独立 cron**:
- event_invalidation 拆到 1h cron(scheduler.yaml::hard_invalidation_monitor),
  规则平仓(channel A)无 AI(详 src/strategy/hard_invalidation_monitor.py)

**§X Sprint 1.10-G 删除**:
- `_check_event_invalidation`(移到 hard_invalidation_monitor 1h cron)
- `_is_throttled` / `_record_trigger`(替代:`EventTrigger.get_last_event_at` /
  `EventTrigger.record_event`,event_throttle 表加 event_class 列 D2=b)
- `_PRICE_CHANGE_THRESHOLD = 0.03` 单一硬编码(替代:base.yaml::event_trigger
  双轨 0.05 / 0.03)
- `_PRICE_RECENT_RUN_THROTTLE_SEC` / `_THROTTLE_DEFAULT_SEC` 硬编码常量
  (从 base.yaml::event_trigger 读)

**调用契约**:
    triggered = check_and_trigger_events(conn)
    # 返回 list[str],每个值 ∈ {'event_price', 'event_macro'}
    # 内部已写 event_throttle / events_calendar.triggered_at_utc(防重)
    # caller(jobs.job_event_listener)按返回值 enqueue pipeline_run_with_retry
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from src.strategy.event_trigger import (
    EVENT_CLASS_PRICE,
    EventTrigger,
    EventTriggerConfig,
    is_holding_state,
)


logger = logging.getLogger(__name__)


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_BASE_YAML = _REPO_ROOT / "config" / "base.yaml"

_MACRO_TRIGGER_OFFSET_SEC = 15 * 60  # event utc_trigger + 15 min
_MACRO_WINDOW_SEC = 60  # 与 event_listener cron 周期匹配
_MACRO_MIN_IMPACT = 2  # 只对 medium/high 触发

# Sprint 1.10-G:配置缓存(避免每 60s 读 yaml)
_cached_config: Optional[EventTriggerConfig] = None


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


def _load_event_trigger_config() -> EventTriggerConfig:
    """从 base.yaml::event_trigger 读双轨阈值 + 节流配置(D1=b + D2=b)。"""
    global _cached_config
    if _cached_config is not None:
        return _cached_config
    try:
        with open(_BASE_YAML, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        _cached_config = EventTriggerConfig.from_dict(cfg)
    except Exception as e:
        logger.warning("event_listener: load base.yaml failed (%s),用默认", e)
        _cached_config = EventTriggerConfig()
    return _cached_config


def _get_current_state(conn: sqlite3.Connection) -> Optional[str]:
    """从 strategy_runs 最新一行读 action_state(决定双轨阈值用)。"""
    try:
        row = conn.execute(
            "SELECT action_state FROM strategy_runs "
            "ORDER BY generated_at_utc DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return row[0] if not hasattr(row, "keys") else row["action_state"]
    except sqlite3.OperationalError:
        return None


# ============================================================
# event_price(双轨改造,D1=b 新 baseline)
# ============================================================

def _check_event_price(
    conn: sqlite3.Connection,
    *,
    now: Optional[datetime] = None,
) -> bool:
    """v1.4 §6.2.3 双轨判定(Sprint 1.10-G 改造):
    - baseline: 上次任一 strategy_run 的 btc_price_usd(D1=b 改 24h 滚动 → 决策窗口)
    - threshold: 持仓 3% / 空仓 5%(D1=b 双轨)
    - 节流: EventTrigger 内置(event_price 2h + 距上次 main_run < 30min)

    触发后写 event_throttle(event_type='event_price', class='event_price')。
    返 True 表示触发,False 表示未触发(原因见 logger.debug)。
    """
    now = now or _now_utc()
    cfg = _load_event_trigger_config()
    et = EventTrigger(cfg)

    # 当前 1h close
    latest_row = conn.execute(
        "SELECT close FROM price_candles WHERE timeframe = '1h' "
        "ORDER BY open_time_utc DESC LIMIT 1"
    ).fetchone()
    if latest_row is None:
        return False
    current_price = float(
        latest_row[0] if not hasattr(latest_row, "keys") else latest_row["close"]
    )

    baseline = EventTrigger.get_baseline_price(conn)
    if baseline is None:
        return False  # 冷启动,无 strategy_run 历史

    state = _get_current_state(conn)
    last_event = EventTrigger.get_last_event_at(conn, "event_price")
    last_main = EventTrigger.get_last_main_run_at(conn)

    triggered, reason = et.should_trigger_event_price(
        current_price=current_price,
        baseline_price=baseline,
        current_state=state,
        last_event_at_utc=last_event,
        last_main_run_at_utc=last_main,
        now_utc=now,
    )

    if not triggered:
        return False

    # 写 throttle
    EventTrigger.record_event(
        conn, event_type="event_price",
        event_class=EVENT_CLASS_PRICE,
        triggered_at_utc=_to_iso(now),
    )
    pct = (current_price - baseline) / baseline if baseline else 0
    logger.warning(
        "event_price TRIGGERED: state=%s pct=%+.2f%% (current=%.2f baseline=%.2f) reason=%s",
        state, pct * 100, current_price, baseline, reason,
    )
    return True


# ============================================================
# event_macro(无变化,沿用 2.7-D 实现)
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
        "event_macro TRIGGERED: event_id=%s name=%s",
        event_id, name,
    )
    return True


# ============================================================
# 入口
# ============================================================

def check_and_trigger_events(
    conn: sqlite3.Connection,
    *,
    now: Optional[datetime] = None,
) -> list[str]:
    """每 60s 调一次。返回本次触发的 event_type 列表。

    Sprint 1.10-G 改造:从 3 类 → 2 类(event_invalidation 拆到 1h cron)。

    内部已写 event_throttle / events_calendar.triggered_at_utc(防重)。
    caller(job_event_listener)按返回值 enqueue pipeline_run_with_retry。

    顺序:price > macro。任一失败被 catch 不阻塞其他。
    """
    triggered: list[str] = []

    for fn, evt in (
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
