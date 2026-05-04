"""src/strategy/protection_handler.py — Sprint 1.10-L commit 2 PROTECTION 进入/退出处理。

对齐 docs/modeling.md b25cfe6(v1.4)§4.2.8/9 + 用户拍板方案 P1A 双向。

§4.2.8 PROTECTION 全局入口 — 任何状态触发 PROTECTION 时:
  - 所有 active thesis 进入 review_pending(reason='extreme_event_protection')
  - 挂单暂停(由 orders_engine 后续 sprint 接入)
  - AI 调用暂停 30 分钟(由调度器后续 sprint 接入)

§4.2.9 PROTECTION 退出 3 条件之一即可:
  1. 极端事件结束(L5: BTC 1H 价格 vs entry 回到 ±10% 以内 + VIX 回落)
  2. 30 分钟冷静期已过
  3. 用户手动确认

退出后: review_pending thesis 由用户决定出口(review_pending.exit_a/b/c 已存在)。

设计纪律:
- 纯函数 + 显式 conn(无单例 / 无全局状态)
- 不调 master AI(留给上层调度)
- 幂等:enter_review_pending 内部已幂等(同 active 不重复 INSERT)
- 单 active thesis(v1.4 §5.3.1 主线锁,Validator 6 强制)→ ThesesDAO.get_active 返 0/1
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional


# 进 PROTECTION 时 review_pending 的 reason
REASON_EXTREME_EVENT_PROTECTION = "extreme_event_protection"

# §4.2.9 #2 冷静期(分钟)
COOLING_PERIOD_MINUTES = 30

# §4.2.9 #1 极端事件结束阈值
EXTREME_EVENT_RESOLVED_BTC_PCT = 0.10   # ±10%
EXTREME_EVENT_RESOLVED_VIX_MAX = 25.0   # VIX 回落上限


def _parse_iso(s: str) -> datetime:
    s = str(s).replace("Z", "+00:00")
    return datetime.fromisoformat(s)


def on_protection_entered(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    now_utc: str,
) -> dict[str, Any]:
    """§4.2.8 进 PROTECTION 时调:active thesis 进 review_pending。

    实施(P1A 严格 modeling):遍历 active thesis(单 active 主线锁,实际 0/1 个),
    每个调 review_pending.enter_review_pending(reason='extreme_event_protection',
    related_thesis_id=...)。

    幂等:enter_review_pending 内部已幂等(同 active 不重复 INSERT,返回当前 state_id)。

    Args:
        conn: SQLite 连接(调用方 commit)
        run_id: 当前 strategy_run id(供归档关联)
        now_utc: 进入 PROTECTION 的 UTC ISO 时间

    Returns:
        {
          thesis_processed: int,                 # 0 = 无 active thesis;1 = 处理了
          review_pending_state_id: str | None,   # 写入或已存在的 state_id
          was_already_active: bool,              # review_pending 是否已 active(幂等命中)
          related_thesis_id: str | None,
        }
    """
    from src.data.storage.dao import ThesesDAO
    from src.strategy.review_pending import enter_review_pending

    active = ThesesDAO.get_active(conn)
    if active is None:
        return {
            "thesis_processed": 0,
            "review_pending_state_id": None,
            "was_already_active": False,
            "related_thesis_id": None,
        }

    thesis_id = active["thesis_id"]
    rp_result = enter_review_pending(
        conn,
        reason=REASON_EXTREME_EVENT_PROTECTION,
        related_thesis_id=thesis_id,
        entered_at_utc=now_utc,
    )
    return {
        "thesis_processed": 1,
        "review_pending_state_id": rp_result.get("state_id"),
        "was_already_active": rp_result.get("was_already_active", False),
        "related_thesis_id": thesis_id,
    }


def check_protection_exit_conditions(
    *,
    current_btc_price: Optional[float],
    btc_price_at_entry: Optional[float],
    vix: Optional[float],
    protection_entered_at_utc: str,
    now_utc: str,
    user_manual_confirmation: bool = False,
) -> dict[str, Any]:
    """§4.2.9 检查 PROTECTION 退出 3 条件 — 任一满足即可退出。

    条件 1:极端事件结束 — |current_btc - btc_at_entry| / btc_at_entry ≤ 10%
              AND(VIX 缺失或 VIX ≤ 25)
    条件 2:30 分钟冷静期已过 — now - entered_at ≥ 30 min
    条件 3:用户手动确认 — user_manual_confirmation=True

    Returns:
        {
          can_exit: bool,                        # 任一条件满足即 True
          conditions_met: list[str],             # 满足的条件名列表
          extreme_event_resolved: bool,
          cooling_period_passed: bool,
          minutes_elapsed: float,                # 实际已过分钟数(供调试)
          user_manual_confirmation: bool,
        }
    """
    conditions_met: list[str] = []

    # 条件 1:极端事件结束
    extreme_event_resolved = False
    if (current_btc_price is not None and btc_price_at_entry is not None
            and float(btc_price_at_entry) > 0):
        pct_change = abs(float(current_btc_price) - float(btc_price_at_entry)) / float(btc_price_at_entry)
        vix_ok = (vix is None) or (float(vix) <= EXTREME_EVENT_RESOLVED_VIX_MAX)
        if pct_change <= EXTREME_EVENT_RESOLVED_BTC_PCT and vix_ok:
            extreme_event_resolved = True
            conditions_met.append("extreme_event_resolved")

    # 条件 2:30 分钟冷静期过
    cooling_period_passed = False
    minutes_elapsed = 0.0
    try:
        entered = _parse_iso(protection_entered_at_utc)
        now = _parse_iso(now_utc)
        minutes_elapsed = (now - entered).total_seconds() / 60.0
        if minutes_elapsed >= COOLING_PERIOD_MINUTES:
            cooling_period_passed = True
            conditions_met.append("cooling_period_passed")
    except (ValueError, TypeError):
        pass

    # 条件 3:用户手动确认
    if user_manual_confirmation:
        conditions_met.append("user_manual_confirmation")

    return {
        "can_exit": len(conditions_met) > 0,
        "conditions_met": conditions_met,
        "extreme_event_resolved": extreme_event_resolved,
        "cooling_period_passed": cooling_period_passed,
        "minutes_elapsed": round(minutes_elapsed, 2),
        "user_manual_confirmation": user_manual_confirmation,
    }
