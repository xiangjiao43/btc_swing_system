"""src/strategy/event_trigger.py — Sprint 1.10-G 事件触发判定器。

对齐 docs/modeling.md b25cfe6(v1.4)§6.2.3:
- **双轨阈值**(继承 v1.3 §5.2 + D1=b 改造):
  - 空仓 / planned / cooldown:price_pct_flat(默认 0.05)
  - 持仓中(opened/holding/trim):price_pct_holding(默认 0.03)
- **节流**(D2=b 两类独立计数):
  - 同 event_class(event_price)2h 节流(event_cooldown_seconds)
  - 距上次主 AI 介入 < 30min 跳过(skip_if_recent_scheduled_seconds)
  - event_invalidation 是另一类,**不被 event_price 节流挡住**(独立 cooldown)

**baseline_price 来源**(D1=b):
  上次任一 strategy_runs.btc_price_usd(由 caller 从 DB 读后传入,
  本类纯 stateless 判定 — 不读 DB)。

设计纪律:
- 纯 stateless 判定函数 + 一个 record_event helper(只这函数读写 event_throttle)
- 不调 AI / 不调 OrdersEngine / 不调 ThesisManager(这些由 caller 编排)
- 节流逻辑写在本类,event_listener.py 老 _is_throttled 删除(commit 5)
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional


# event_class 命名(D2=b)
EVENT_CLASS_PRICE = "event_price"
EVENT_CLASS_INVALIDATION = "event_invalidation"

# 持仓 / 空仓状态枚举(对齐 v1.4 §5.1 14 档状态机)
_HOLDING_STATES = frozenset({
    "LONG_OPEN", "LONG_HOLD", "LONG_TRIM",
    "SHORT_OPEN", "SHORT_HOLD", "SHORT_TRIM",
})


def is_holding_state(state: str | None) -> bool:
    """state ∈ {LONG_OPEN/HOLD/TRIM, SHORT_OPEN/HOLD/TRIM} → True;其他 → False。"""
    if not state:
        return False
    return state.upper() in _HOLDING_STATES


@dataclass(frozen=True)
class EventTriggerConfig:
    """从 base.yaml::event_trigger 读的 4 配置项(v1.4 §10.4.3)。"""
    price_pct_flat: float = 0.05
    price_pct_holding: float = 0.03
    event_cooldown_seconds: int = 7200
    skip_if_recent_scheduled_seconds: int = 1800

    @classmethod
    def from_dict(cls, cfg: dict[str, Any]) -> "EventTriggerConfig":
        et = cfg.get("event_trigger") or {}
        return cls(
            price_pct_flat=float(et.get("price_pct_flat", 0.05)),
            price_pct_holding=float(et.get("price_pct_holding", 0.03)),
            event_cooldown_seconds=int(et.get("event_cooldown_seconds", 7200)),
            skip_if_recent_scheduled_seconds=int(
                et.get("skip_if_recent_scheduled_seconds", 1800)
            ),
        )


class EventTrigger:
    """v1.4 §6.2.3 双轨事件触发判定器。

    用法:
        cfg = EventTriggerConfig.from_dict(yaml.safe_load(open("config/base.yaml")))
        et = EventTrigger(cfg)

        # 价格异动判定(stateless)
        triggered, reason = et.should_trigger_event_price(
            current_price=78500.0,
            baseline_price=75000.0,        # 从 strategy_runs 最新行读
            current_state="FLAT",
            last_event_at_utc=last_throttle_row,  # 从 event_throttle 读
            last_main_run_at_utc=last_run_row,    # 从 strategy_runs 最新行读
            now_utc=now,
        )

        # 触发后写 throttle
        if triggered:
            EventTrigger.record_event(conn, EVENT_CLASS_PRICE, now_iso)
    """

    def __init__(self, config: Optional[EventTriggerConfig] = None) -> None:
        self.cfg = config or EventTriggerConfig()

    # ------------------------------------------------------------------
    # 核心判定(stateless,纯函数)
    # ------------------------------------------------------------------

    def get_threshold(self, current_state: str | None) -> float:
        """根据状态选阈值:持仓 → price_pct_holding;否则 price_pct_flat。"""
        if is_holding_state(current_state):
            return self.cfg.price_pct_holding
        return self.cfg.price_pct_flat

    def should_trigger_event_price(
        self,
        *,
        current_price: float,
        baseline_price: float,
        current_state: str | None,
        last_event_at_utc: Optional[str] = None,
        last_main_run_at_utc: Optional[str] = None,
        now_utc: Optional[datetime] = None,
    ) -> tuple[bool, str]:
        """v1.4 §6.2.3 价格异动判定。

        Args:
            current_price: 当前 1h close
            baseline_price: 上次任一 strategy_run 的 BTC 价格(D1=b,caller 读)
            current_state: 14 档状态(决定双轨阈值)
            last_event_at_utc: event_class=event_price 的上次触发时间(节流用)
            last_main_run_at_utc: 上次主 AI run 时间(skip 节流用)
            now_utc: 评估时点(测试可注入)

        Returns:
            (triggered, reason);reason ∈ {
                "below_threshold", "throttled_event_price",
                "throttled_recent_main_run", "triggered_flat_5pct",
                "triggered_holding_3pct", "invalid_baseline"
            }
        """
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)

        if baseline_price is None or baseline_price <= 0:
            return (False, "invalid_baseline")
        if current_price is None or current_price <= 0:
            return (False, "invalid_baseline")

        # 节流 1:event_class=event_price 同类 2h cooldown
        if last_event_at_utc:
            last_evt = _parse_iso(last_event_at_utc)
            if last_evt and (now_utc - last_evt).total_seconds() < self.cfg.event_cooldown_seconds:
                return (False, "throttled_event_price")

        # 节流 2:距上次主 AI run < 30min 跳过(避免噪音)
        if last_main_run_at_utc:
            last_run = _parse_iso(last_main_run_at_utc)
            if last_run and (now_utc - last_run).total_seconds() < self.cfg.skip_if_recent_scheduled_seconds:
                return (False, "throttled_recent_main_run")

        threshold = self.get_threshold(current_state)
        pct_change = abs(current_price - baseline_price) / baseline_price

        if pct_change < threshold:
            return (False, "below_threshold")

        if is_holding_state(current_state):
            return (True, "triggered_holding_3pct")
        return (True, "triggered_flat_5pct")

    # ------------------------------------------------------------------
    # event_throttle 表 helper(D2=b:两类独立计数 via PK + event_class 标记)
    # ------------------------------------------------------------------

    @staticmethod
    def record_event(
        conn: sqlite3.Connection,
        event_type: str,
        event_class: str,
        triggered_at_utc: str,
    ) -> None:
        """写 event_throttle:event_type 是 PK,event_class 是 D2=b 元数据。

        event_type 可以是 'event_price' / 'event_invalidation';
        event_class 同名(本 sprint 简化)— 未来如分 event_price_flat /
        event_price_holding,event_class 仍指向 'event_price' 大类。
        """
        conn.execute(
            "INSERT INTO event_throttle (event_type, last_triggered_at_utc, event_class) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(event_type) DO UPDATE SET "
            "  last_triggered_at_utc = excluded.last_triggered_at_utc, "
            "  event_class = excluded.event_class",
            (event_type, triggered_at_utc, event_class),
        )

    @staticmethod
    def get_last_event_at(
        conn: sqlite3.Connection,
        event_type: str,
    ) -> Optional[str]:
        """读 event_throttle.last_triggered_at_utc(给 should_trigger_event_price 用)。"""
        try:
            row = conn.execute(
                "SELECT last_triggered_at_utc FROM event_throttle WHERE event_type = ?",
                (event_type,),
            ).fetchone()
            if row is None:
                return None
            return row[0] if not hasattr(row, "keys") else row["last_triggered_at_utc"]
        except sqlite3.OperationalError:
            return None

    @staticmethod
    def get_last_main_run_at(conn: sqlite3.Connection) -> Optional[str]:
        """读 strategy_runs 最新一行 generated_at_utc(skip 节流用)。"""
        try:
            row = conn.execute(
                "SELECT generated_at_utc FROM strategy_runs "
                "ORDER BY generated_at_utc DESC LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            return row[0] if not hasattr(row, "keys") else row["generated_at_utc"]
        except sqlite3.OperationalError:
            return None

    @staticmethod
    def get_baseline_price(conn: sqlite3.Connection) -> Optional[float]:
        """D1=b:从 strategy_runs 最新一行读 btc_price_usd(baseline_price)。

        改造 2.7-D 24h 滚动 → 上次 run 决策窗口语义。
        无 strategy_runs 行(冷启动)→ 返 None,caller 应跳过事件触发。
        """
        try:
            row = conn.execute(
                "SELECT btc_price_usd FROM strategy_runs "
                "WHERE btc_price_usd IS NOT NULL "
                "ORDER BY generated_at_utc DESC LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            v = row[0] if not hasattr(row, "keys") else row["btc_price_usd"]
            return float(v) if v is not None else None
        except sqlite3.OperationalError:
            return None


# ============================================================
# 内部 helpers
# ============================================================

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
