"""src/strategy/thesis_manager.py — Sprint 1.10-C thesis 生命周期管理。

对齐 docs/modeling.md b25cfe6(v1.4)§4.2 / §5.3。

职责(本 sprint 范围):
- create_thesis:接 thesis_spec dict(由 1.10-D master AI 给),写 theses + 创建挂单
- advance_lifecycle:基于 fills 推进 5 档(planned → opened → holding → trim → closed)
- close_thesis:终态写入 + cancel 残余挂单 + compute_snapshot 含 close fills

本 sprint 严格不做(留后续):
- 不调 master AI(1.10-D)
- 不实现 break_conditions 真实触发判定(1.10-D + Validator 7)
- 不实现极端事件 PROTECTION(1.10-G)
- 不实现 60d_cap 检测(1.10-C commit 4 FuseMonitor 拥有)
- 不实现 14d 熔断(同上)
- 不写网页(1.10-I)

D3 原子化补充(用户拍板):
- OrdersEngine 触发 fill 后,调用方在同一调用栈内立刻调 close_thesis
- closed_at_utc 用 last fill 的 filled_at_utc(物理准确,不用 close_thesis 调用时刻)

D4 显式字段:
- theses.is_60d_capped(migration 010 加,本 commit 不依赖)
- 60d-capped thesis 不进 closed,挂单仍触发走自然平仓 → 通道 A
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from src.data.storage.dao import (
    ThesesDAO, VirtualAccountDAO, VirtualOrdersDAO,
)
from src.strategy.virtual_account import compute_snapshot


_HOLDING_HOURS_THRESHOLD = 24
_HOLDING_PNL_PCT_THRESHOLD = 2.0


def _parse_iso(s: str) -> datetime:
    s = str(s).replace("Z", "+00:00")
    return datetime.fromisoformat(s)


def _new_uuid_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ============================================================
# 创建 thesis
# ============================================================

def create_thesis(
    conn: sqlite3.Connection,
    *,
    thesis_spec: dict[str, Any],
    run_id: str,
    now_utc: str,
    expires_at_utc: str,
    thesis_id: Optional[str] = None,
) -> dict[str, Any]:
    """创建 thesis + 对应 entry/sl/tp 挂单(v1.4 §4.2.1 + §5.3.3)。

    thesis_spec dict 字段(由 1.10-D master AI 给):
        direction:           "long" / "short"
        core_logic:          str
        confidence_score:    int 0-100
        break_conditions:    list[str](≥3 条客观,Validator 8/9 强制)
        entry_orders:        list[{price, size_pct, size_usdt}]
        stop_loss_orders:    list[{price, size_pct, size_usdt}](可空)
        take_profit_orders:  list[{price, size_pct, size_usdt}](可空)

    expires_at_utc:调用方算(now_utc + base.yaml::virtual_orders.default_expiry_days * 86400)。

    返回 {thesis_id, entry_order_ids, stop_loss_order_ids, take_profit_order_ids}
    """
    direction = thesis_spec["direction"]
    if direction not in ("long", "short"):
        raise ValueError(f"thesis_spec.direction 必须 long/short,实际 {direction!r}")
    tid = thesis_id or _new_uuid_id("th")

    # 1) theses 表写入
    ThesesDAO.create(
        conn,
        thesis_id=tid,
        created_at_run_id=run_id,
        created_at_utc=now_utc,
        direction=direction,
        core_logic=str(thesis_spec.get("core_logic") or ""),
        confidence_score=int(thesis_spec.get("confidence_score") or 0),
        break_conditions=list(thesis_spec.get("break_conditions") or []),
        lifecycle_stage="planned",
        status="active",
    )

    # 2) 三类挂单写入。direction = thesis.direction(positional);
    #    买/卖动作由 order_type 隐含:long thesis 的 entry=buy,sl/tp=sell。
    entry_ids: list[str] = []
    sl_ids: list[str] = []
    tp_ids: list[str] = []
    for o in thesis_spec.get("entry_orders") or []:
        oid = _new_uuid_id("o_e")
        VirtualOrdersDAO.create_order(
            conn, order_id=oid, thesis_id=tid,
            direction=direction, order_type="entry",
            price=float(o["price"]), size_pct=float(o["size_pct"]),
            size_usdt=float(o["size_usdt"]),
            created_at_utc=now_utc, expires_at_utc=expires_at_utc,
        )
        entry_ids.append(oid)
    for o in thesis_spec.get("stop_loss_orders") or []:
        oid = _new_uuid_id("o_s")
        VirtualOrdersDAO.create_order(
            conn, order_id=oid, thesis_id=tid,
            direction=direction, order_type="stop_loss",
            price=float(o["price"]), size_pct=float(o["size_pct"]),
            size_usdt=float(o["size_usdt"]),
            created_at_utc=now_utc, expires_at_utc=expires_at_utc,
        )
        sl_ids.append(oid)
    for o in thesis_spec.get("take_profit_orders") or []:
        oid = _new_uuid_id("o_t")
        VirtualOrdersDAO.create_order(
            conn, order_id=oid, thesis_id=tid,
            direction=direction, order_type="take_profit",
            price=float(o["price"]), size_pct=float(o["size_pct"]),
            size_usdt=float(o["size_usdt"]),
            created_at_utc=now_utc, expires_at_utc=expires_at_utc,
        )
        tp_ids.append(oid)

    return {
        "thesis_id": tid,
        "entry_order_ids": entry_ids,
        "stop_loss_order_ids": sl_ids,
        "take_profit_order_ids": tp_ids,
    }


# ============================================================
# advance_lifecycle:5 档迁移
# ============================================================

def advance_lifecycle(
    conn: sqlite3.Connection,
    *,
    thesis_id: str,
    fills: list[dict[str, Any]],
    prev_snapshot: Optional[dict[str, Any]],
    current_btc_price: float,
    now_utc: str,
) -> dict[str, Any]:
    """基于 fills 推进 thesis lifecycle_stage(v1.4 §4.2.2-§4.2.5)。

    迁移规则:
        planned + 任 1 entry filled    → opened
        opened + (24h since opened + 浮盈 ≥ 2%) → holding
        holding + 任 1 take_profit filled → trim
        trim + 全 take_profit filled / 持仓 = 0 → ready_to_close (调用方调 close_thesis)

    走势确认 1/4 简化:本 sprint 实现 浮盈 ≥ 2% 一项;其他 3 项(4H 收盘 / 回撤反弹 / TP 50% 距离)
    留 1.10-D master AI 综合判断 + 强制推进。

    fills:由 OrdersEngine 给的本次 check 的 fill 记录(含 order_type 区分 entry/sl/tp)。
    调用方保证 fills 已去重(1.10-B 风险 #5)。

    返回 {old_stage, new_stage, ready_to_close, close_reason}
    """
    row = conn.execute(
        "SELECT * FROM theses WHERE thesis_id=?", (thesis_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"thesis {thesis_id} 不存在")
    thesis = dict(row)

    # closed thesis 不能 advance(防御 §4.2.5 后向操作)
    if thesis["status"] != "active":
        return {"old_stage": thesis["lifecycle_stage"],
                "new_stage": thesis["lifecycle_stage"],
                "ready_to_close": False, "close_reason": None,
                "skipped_reason": f"thesis already {thesis['status']}"}

    old_stage = thesis["lifecycle_stage"]
    direction = thesis["direction"]
    new_stage = old_stage
    ready_to_close = False
    close_reason: Optional[str] = None

    # 检测各类 fill
    entry_fills = [f for f in fills if f.get("order_type") == "entry"]
    sl_fills = [f for f in fills if f.get("order_type") == "stop_loss"]
    tp_fills = [f for f in fills if f.get("order_type") == "take_profit"]

    # stop_loss 触发任意时间 → ready_to_close(reason=stop_loss_filled)
    if sl_fills:
        ready_to_close = True
        close_reason = "stop_loss_filled"
        # 不改 stage,close_thesis 来设
        return {
            "old_stage": old_stage,
            "new_stage": old_stage,
            "ready_to_close": ready_to_close,
            "close_reason": close_reason,
        }

    # planned → opened
    if old_stage == "planned" and entry_fills:
        new_stage = "opened"
        conn.execute(
            "UPDATE theses SET lifecycle_stage='opened' WHERE thesis_id=?",
            (thesis_id,),
        )

    # opened → holding(24h + 浮盈 ≥ 2%)
    if new_stage == "opened":
        # 取最早 entry filled 的时间作 opened_at proxy
        entry_filled_rows = VirtualOrdersDAO.get_filled(
            conn, thesis_id=thesis_id,
        )
        entry_filled_rows = [e for e in entry_filled_rows if e.get("order_type") == "entry"]
        if entry_filled_rows:
            opened_at = min(e["filled_at_utc"] for e in entry_filled_rows if e.get("filled_at_utc"))
            try:
                opened_dt = _parse_iso(opened_at)
                now_dt = _parse_iso(now_utc)
                hours_elapsed = (now_dt - opened_dt).total_seconds() / 3600.0
            except (ValueError, TypeError):
                hours_elapsed = 0.0

            # 浮盈 % 基于 prev_snapshot 的 avg_price + 当前价
            pnl_pct = _compute_pnl_pct(prev_snapshot, direction, current_btc_price)

            if hours_elapsed >= _HOLDING_HOURS_THRESHOLD and pnl_pct >= _HOLDING_PNL_PCT_THRESHOLD:
                new_stage = "holding"
                conn.execute(
                    "UPDATE theses SET lifecycle_stage='holding' WHERE thesis_id=?",
                    (thesis_id,),
                )

    # holding → trim
    if new_stage == "holding" and tp_fills:
        new_stage = "trim"
        conn.execute(
            "UPDATE theses SET lifecycle_stage='trim' WHERE thesis_id=?",
            (thesis_id,),
        )

    # trim → ready_to_close(全 tp filled)
    if new_stage == "trim":
        all_tp = conn.execute(
            "SELECT status FROM virtual_orders "
            "WHERE thesis_id=? AND order_type='take_profit'",
            (thesis_id,),
        ).fetchall()
        if all_tp:
            statuses = [r["status"] for r in all_tp]
            if all(s == "filled" for s in statuses):
                ready_to_close = True
                close_reason = "all_take_profit_filled"

    return {
        "old_stage": old_stage,
        "new_stage": new_stage,
        "ready_to_close": ready_to_close,
        "close_reason": close_reason,
    }


def _compute_pnl_pct(
    prev_snapshot: Optional[dict[str, Any]], direction: str, current_price: float,
) -> float:
    """简化浮盈 %(opened → holding 4 走势 1 项)。"""
    if prev_snapshot is None:
        return 0.0
    if direction == "long":
        avg = prev_snapshot.get("long_avg_price")
        if avg is None or avg <= 0:
            return 0.0
        return (current_price - float(avg)) / float(avg) * 100.0
    elif direction == "short":
        avg = prev_snapshot.get("short_avg_price")
        if avg is None or avg <= 0:
            return 0.0
        return (float(avg) - current_price) / float(avg) * 100.0
    return 0.0


# ============================================================
# close_thesis
# ============================================================

# 5 种 close 原因 → final_outcome 映射
_REASON_TO_OUTCOME = {
    "all_take_profit_filled": ("closed_profit", "profit"),
    "stop_loss_filled":       ("closed_loss",   "loss"),
    "invalidated":            ("invalidated",   "loss"),       # break 触发,可能 loss/profit/breakeven
    "60d_cap":                ("closed_60d_cap", "60d_cap"),    # D4=b:理论上 60d 不进 closed,但 verify 可能用
    "protection":             ("closed_protection", "protection"),
}


def close_thesis(
    conn: sqlite3.Connection,
    *,
    thesis_id: str,
    reason: str,
    close_channel: str,             # A / B / C(由 CooldownManager 给)
    closed_at_utc: str,             # D3=a:用 last fill 的 filled_at_utc(调用方传)
    fills_for_close: list[dict[str, Any]],   # 触发关闭的 fills(stop/tp 等),用于 compute_snapshot
    current_btc_price: float,
    initial_capital: float,
    snapshot_id: str,
    run_id: str,
    snapshot_at_utc: str,
    invalidated_reason: Optional[str] = None,
    final_outcome_override: Optional[str] = None,
) -> dict[str, Any]:
    """关闭 thesis(v1.4 §4.2.6 + §5.3.5)。

    1. ThesesDAO.close 写终态字段
    2. cancel 残余 pending 挂单(cancelled_reason=f"thesis_closed_{reason}")
    3. 调 compute_snapshot 算 close 后快照(含 fills_for_close 触发的 realized_pnl)
       — 不 insert virtual_account(D1=C 沿用 1.10-B:上层协调写入)

    返回 {thesis_status, cancelled_count, computed_snapshot_for_account, final_realized_pnl, final_realized_pnl_pct}
    """
    if reason not in _REASON_TO_OUTCOME:
        raise ValueError(f"未知 close reason: {reason!r}")
    status, default_outcome = _REASON_TO_OUTCOME[reason]
    final_outcome = final_outcome_override or default_outcome

    # 算 close 后快照(含 close fills 的 realized_pnl)
    prev_snapshot = VirtualAccountDAO.get_latest(conn)
    computed_snapshot = compute_snapshot(
        prev_snapshot=prev_snapshot,
        current_btc_price=current_btc_price,
        fills_since_last=fills_for_close,
        initial_capital=initial_capital,
        snapshot_id=snapshot_id,
        run_id=run_id,
        snapshot_at_utc=snapshot_at_utc,
    )

    # 算本次 close 的 realized_pnl 增量(对比 prev_snapshot.realized_pnl_total)
    prev_pnl = float((prev_snapshot or {}).get("realized_pnl_total") or 0.0)
    final_pnl = float(computed_snapshot["realized_pnl_total"]) - prev_pnl
    final_pnl_pct = (
        (final_pnl / initial_capital) * 100.0 if initial_capital > 0 else 0.0
    )

    # ThesesDAO.close 写终态
    n = ThesesDAO.close(
        conn,
        thesis_id=thesis_id,
        status=status,
        closed_at_utc=closed_at_utc,
        invalidated_reason=invalidated_reason,
        close_channel=close_channel,
        final_realized_pnl=round(final_pnl, 8),
        final_realized_pnl_pct=round(final_pnl_pct, 4),
        final_outcome=final_outcome,
        lifecycle_stage="closed",
    )

    # cancel 残余 pending 挂单
    pending = VirtualOrdersDAO.get_pending(conn, thesis_id=thesis_id)
    cancelled_count = 0
    for o in pending:
        c = VirtualOrdersDAO.cancel_order(
            conn, order_id=o["order_id"],
            cancelled_reason=f"thesis_closed_{reason}",
        )
        cancelled_count += c

    return {
        "thesis_id": thesis_id,
        "status": status,
        "close_channel": close_channel,
        "final_outcome": final_outcome,
        "final_realized_pnl": round(final_pnl, 8),
        "final_realized_pnl_pct": round(final_pnl_pct, 4),
        "rows_updated": n,
        "cancelled_pending_count": cancelled_count,
        "computed_snapshot_for_account": computed_snapshot,
    }
