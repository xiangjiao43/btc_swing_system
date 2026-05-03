"""src/strategy/orders_engine.py — Sprint 1.10-B 挂单触发引擎。

对齐 docs/modeling.md b25cfe6(v1.4)§5.2.3 / §5.2.4 / §5.2.5。

职责:
- 取上次检查至今的 1H K 线
- 对 pending entry 挂单做"low ≤ price ≤ high"穿过判定
- 触发的挂单 → VirtualOrdersDAO.fill_order
- 过期挂单 → VirtualOrdersDAO.mark_expired(兜底所有 order_type)
- 计算 computed_snapshot via VirtualAccountManager(**不写入** DB)

设计纪律:
- D1=C(用户拍板):本模块 0 DAO 写 virtual_account,只产 dict 让上层协调
- D2=a:内部过滤 order_type='entry';**stop_loss / take_profit 触发判定
  留 1.10-C ThesisManager 处理**
- 不动 thesis.lifecycle_stage(留 1.10-C)
- 不调 master AI(留 1.10-D)

3 条硬约束(§5.2.4 + §5.2.5):
1. 入场价 = 挂单价(filled_price = order.price,不是 K 线 close/high/low)
2. 同 1H 多挂单全触发(low ≤ price ≤ high 任一满足都触发,等号也算)
3. BTC 数量 = size_usdt / filled_price

触发顺序:K 线 ASC(早 K 线先)+ 同 1H 内 order_id 字典序(确定性 tie-break)。
"""
from __future__ import annotations

import sqlite3
from typing import Any, Optional

from src.data.storage.dao import (
    BTCKlinesDAO, VirtualAccountDAO, VirtualOrdersDAO,
)
from src.strategy.virtual_account import compute_snapshot


def check_and_fill_orders(
    conn: sqlite3.Connection,
    *,
    thesis_id: str,
    last_check_utc: str,
    now_utc: str,
    current_btc_price: float,
    initial_capital: float,
    snapshot_id: str,
    run_id: str,
    snapshot_at_utc: str,
) -> dict[str, Any]:
    """挂单触发主流程(v1.4 §5.2.3)。

    Args:
        conn: sqlite3 连接(调用方 commit)
        thesis_id: 当前 active thesis(由 ThesesDAO.get_active 拿到)
        last_check_utc: 上次检查时间(用于取 1H K 线起点)
        now_utc: 本次检查时间(K 线终点;mark_expired 比较基准)
        current_btc_price: 当前 BTC 价格(用于 mark-to-market 算 unrealized_pnl)
        initial_capital: 从 base.yaml::virtual_account.initial_capital 读
        snapshot_id / run_id / snapshot_at_utc: computed_snapshot 元数据(调用方提供)

    Returns:
        {
          "filled_orders":      [{order_id, price, size_usdt, ...}, ...],
          "expired_count":      N,
          "skipped_orders":     [{order_id, order_type, reason}, ...],  # 非 entry 的 pending
          "computed_snapshot_for_account": dict (16 字段 ready-to-insert),
        }

    本方法不 commit,不 insert virtual_account(D1=C)。
    """
    # 1. 批量过期(兜底所有 order_type — 挂过期的 stop/tp 也得清理)
    expired_count = VirtualOrdersDAO.mark_expired(conn, now_utc=now_utc)

    # 2. 拿 thesis 的所有 pending 挂单
    pending_all = VirtualOrdersDAO.get_pending(conn, thesis_id=thesis_id)

    # 3. 过滤 entry(D2=a:stop_loss/take_profit 留 1.10-C)
    entry_orders: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for o in pending_all:
        if o.get("order_type") == "entry":
            entry_orders.append(o)
        else:
            skipped.append({
                "order_id": o["order_id"],
                "order_type": o.get("order_type"),
                "reason": "non_entry_skipped_by_1.10_b_(留 1.10-C ThesisManager)",
            })

    # 4. 取 1H K 线(open_time_utc 范围 (last_check_utc, now_utc])
    # 注:DAO 的 start/end 是 inclusive,我们传 last_check 的下一秒避免重复触发
    klines = BTCKlinesDAO.get_klines(
        conn, timeframe="1h",
        start=last_check_utc,
        end=now_utc,
    )
    # 已按 open_time_utc ASC 排序

    # 5. 触发判定:K 线 ASC + 同 K 线内 order_id 字典序
    fills: list[dict[str, Any]] = []
    still_pending = sorted(entry_orders, key=lambda o: o["order_id"])

    for kline in klines:
        if not still_pending:
            break
        kl_low = float(kline.get("low") or 0.0)
        kl_high = float(kline.get("high") or 0.0)
        kl_close_time = (
            kline.get("close_time_utc")
            or kline.get("open_time_utc")
            or kline.get("timestamp")
        )
        # 本 K 线触发的挂单
        triggered_this_kline: list[dict[str, Any]] = []
        for o in still_pending:
            price = float(o["price"])
            if kl_low <= price <= kl_high:
                triggered_this_kline.append(o)

        # 调 fill_order + 收集 fills
        for o in triggered_this_kline:
            filled_price = float(o["price"])  # §5.2.4 入场价 = 挂单价
            # §5.2.4 公式;不预 round —— round 会让 compute_snapshot 反推
            # avg_price 时丢精度(实测 verify_orders_engine 0.27027027 反推
            # → 74000.000074 而非 74000)。SQLite REAL 是 64-bit double,
            # 直接存全精度。
            filled_btc_amount = float(o["size_usdt"]) / filled_price
            n = VirtualOrdersDAO.fill_order(
                conn,
                order_id=o["order_id"],
                filled_at_utc=str(kl_close_time),
                filled_price=filled_price,
                filled_btc_amount=filled_btc_amount,
            )
            if n == 1:
                fills.append({
                    "order_id": o["order_id"],
                    "thesis_id": o["thesis_id"],
                    "direction": o["direction"],
                    "order_type": o["order_type"],
                    "size_usdt": float(o["size_usdt"]),
                    "filled_price": filled_price,
                    "filled_btc_amount": filled_btc_amount,
                    "filled_at_utc": str(kl_close_time),
                })

        # 移出 still_pending(已触发的不再参与下一 K 线)
        triggered_ids = {o["order_id"] for o in triggered_this_kline}
        still_pending = [o for o in still_pending if o["order_id"] not in triggered_ids]

    # 6. 算新快照(prev_snapshot from VirtualAccountDAO,**不写入**)
    prev_snapshot = VirtualAccountDAO.get_latest(conn)
    computed_snapshot = compute_snapshot(
        prev_snapshot=prev_snapshot,
        current_btc_price=current_btc_price,
        fills_since_last=fills,
        initial_capital=initial_capital,
        snapshot_id=snapshot_id,
        run_id=run_id,
        snapshot_at_utc=snapshot_at_utc,
    )

    return {
        "filled_orders": fills,
        "expired_count": expired_count,
        "skipped_orders": skipped,
        "computed_snapshot_for_account": computed_snapshot,
    }
