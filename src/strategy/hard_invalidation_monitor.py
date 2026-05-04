"""src/strategy/hard_invalidation_monitor.py — Sprint 1.10-G 硬失效位监控。

对齐 docs/modeling.md b25cfe6(v1.4)§6.2.3 + §6.2.6 event_invalidation:
- 每小时 cron(scheduler.yaml::hard_invalidation_monitor)
- 取 active thesis + 其 pending stop_loss 挂单 + 当前 BTC 1h close
- 价格击穿 stop_loss → 规则平仓:
  - VirtualOrdersDAO.fill_order(stop_loss 那条)
  - ThesisManager.close_thesis(reason="stop_loss_filled", close_channel="A")
  - 写 retry_log["event_invalidation_triggered"] = True 区分场景(D4=b1)
- 推 critical 告警

**v1.4 §6.2.3 硬约束:本模块绝对不调 AI(规则平仓)**

D4=b1 决策(用户拍板):
- 复用 ThesisManager.close_thesis(reason="stop_loss_filled", close_channel="A")
- 不新增 reason,不改 _REASON_TO_OUTCOME 表
- retry_log_json 标记 `event_invalidation_triggered=True` 区分"被监控触发的击穿"
  vs 普通 OrdersEngine 触发的 stop_loss(后者会自然进 ThesisManager 关流程)

设计纪律:
- 纯规则,不调 AI(§6.2.3)
- 不写 strategy_runs(retry_log_json 由 caller 装入下一次主 run)
- 不调用 OrdersEngine(避免循环依赖;直接用 VirtualOrdersDAO)
"""
from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from src.data.storage.dao import (
    BTCKlinesDAO, ThesesDAO, VirtualAccountDAO, VirtualOrdersDAO,
)
from src.strategy import thesis_manager


logger = logging.getLogger(__name__)


class HardInvalidationMonitor:
    """v1.4 §6.2.3 硬失效位监控。

    用法(在 jobs.py::job_hard_invalidation_monitor 里):
        mon = HardInvalidationMonitor()

        # 1. 检查是否触发(纯查询,不动 DB)
        breaches = mon.check_active_theses(
            conn, current_btc_price=78500.0, now_utc=datetime.now(timezone.utc),
        )
        # breaches: list[dict],每条含 {thesis_id, direction, stop_loss_price,
        #                              breached_by, stop_loss_order_id}

        # 2. 对每条 breach 执行规则平仓
        for b in breaches:
            result = mon.execute_invalidation(
                conn, thesis_id=b["thesis_id"],
                stop_loss_order_id=b["stop_loss_order_id"],
                current_btc_price=78500.0,
                initial_capital=100000.0,
                now_utc=now_utc,
            )
            conn.commit()
            # caller 推 critical 告警 + 把 result["retry_log_marker"] 装入 strategy_runs
    """

    @staticmethod
    def check_active_theses(
        conn: sqlite3.Connection,
        *,
        current_btc_price: float,
        now_utc: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        """检查是否有 active thesis 的 stop_loss 被击穿。

        v1.4 §5.3.1 主线锁:同一时刻最多 1 active thesis。
        若有,取其所有 pending stop_loss 挂单,逐个判定击穿:
          - long 仓:current_price < stop_loss_price → 击穿
          - short 仓:current_price > stop_loss_price → 击穿

        Returns:
            list[dict]:每条 {thesis_id, direction, stop_loss_price, stop_loss_order_id,
                            breached_by(price diff)}
            空 list = 无 active thesis / 无 stop_loss 挂单 / 未击穿
        """
        if current_btc_price is None or current_btc_price <= 0:
            return []

        active = ThesesDAO.get_active(conn)
        if active is None:
            return []
        thesis_id = active["thesis_id"]
        direction = active.get("direction")
        if direction not in ("long", "short"):
            return []

        # 取该 thesis 的 pending stop_loss 挂单
        all_pending = VirtualOrdersDAO.get_pending(conn, thesis_id=thesis_id)
        sl_orders = [o for o in all_pending if o.get("order_type") == "stop_loss"]

        breaches: list[dict[str, Any]] = []
        for o in sl_orders:
            try:
                sl_price = float(o["price"])
            except (KeyError, TypeError, ValueError):
                continue
            breached = (
                (direction == "long" and current_btc_price < sl_price)
                or (direction == "short" and current_btc_price > sl_price)
            )
            if breached:
                breaches.append({
                    "thesis_id": thesis_id,
                    "direction": direction,
                    "stop_loss_price": sl_price,
                    "stop_loss_order_id": o["order_id"],
                    "breached_by": current_btc_price - sl_price,
                    "current_price": current_btc_price,
                })
        return breaches

    @staticmethod
    def execute_invalidation(
        conn: sqlite3.Connection,
        *,
        thesis_id: str,
        stop_loss_order_id: str,
        current_btc_price: float,
        initial_capital: float,
        now_utc: Optional[datetime] = None,
        run_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """规则平仓(D4=b1:复用 stop_loss_filled reason + channel A)。

        步骤:
        1. fill_order:stop_loss 挂单 → filled(filled_price=current_btc_price)
        2. close_thesis(reason="stop_loss_filled", close_channel="A")
        3. 返回 result + retry_log_marker(caller 装入 strategy_runs.retry_log_json)

        v1.4 §6.2.3 硬约束:**不调 AI**(规则平仓)。

        本方法不 commit;不写 strategy_runs(caller 责任,在下次主 run 装入 retry_log)。
        """
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)
        now_iso = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        if run_id is None:
            # 兜底:取 strategy_runs 最新 run_id 关联
            row = conn.execute(
                "SELECT run_id FROM strategy_runs ORDER BY generated_at_utc DESC LIMIT 1"
            ).fetchone()
            run_id = (
                row[0] if row and not hasattr(row, "keys") else
                row["run_id"] if row else "event_invalidation_no_run"
            )

        # 1. 取 stop_loss 挂单详情(needed for size_usdt → btc_amount)
        all_pending = VirtualOrdersDAO.get_pending(conn, thesis_id=thesis_id)
        sl_order = next(
            (o for o in all_pending if o.get("order_id") == stop_loss_order_id), None,
        )
        if sl_order is None:
            return {
                "thesis_id": thesis_id,
                "status": "skipped_order_not_pending",
                "stop_loss_order_id": stop_loss_order_id,
            }

        # 2. fill_order(filled_price = current_btc_price,模拟瞬时击穿成交)
        size_usdt = float(sl_order["size_usdt"])
        filled_btc_amount = size_usdt / current_btc_price
        filled_n = VirtualOrdersDAO.fill_order(
            conn,
            order_id=stop_loss_order_id,
            filled_at_utc=now_iso,
            filled_price=current_btc_price,
            filled_btc_amount=filled_btc_amount,
        )
        if filled_n != 1:
            return {
                "thesis_id": thesis_id,
                "status": "skipped_fill_failed",
                "stop_loss_order_id": stop_loss_order_id,
            }

        # 3. close_thesis(D4=b1:stop_loss_filled reason)
        # Sprint 1.10-L commit 6 §X(P0 #3 改造):
        # 写死 close_channel='A' → cooldown_manager.determine_close_channel(...)
        # 统一调用路径(stop_loss_filled 默认仍走 A,_REASON_TO_DEFAULT_CHANNEL 不变)
        from src.strategy.cooldown_manager import determine_close_channel
        ch = determine_close_channel(
            close_reason="stop_loss_filled",
            stop_loss_breached=True,  # 本路径 stop_loss 真触发
            # 4 条件分级仅 invalidated reason 用,stop_loss_filled 走默认 'A';
            # 其他 3 条件留 False 默认(此路径不读 L1/L2/L5,见 cooldown_manager:86)
        )
        snapshot_id = f"event_inv_{uuid.uuid4().hex[:12]}"
        close_result = thesis_manager.close_thesis(
            conn,
            thesis_id=thesis_id,
            reason="stop_loss_filled",
            close_channel=ch,
            closed_at_utc=now_iso,
            fills_for_close=[{
                "order_id": stop_loss_order_id,
                "thesis_id": thesis_id,
                "direction": sl_order["direction"],
                "order_type": "stop_loss",
                "size_usdt": size_usdt,
                "filled_price": current_btc_price,
                "filled_btc_amount": filled_btc_amount,
                "filled_at_utc": now_iso,
            }],
            current_btc_price=current_btc_price,
            initial_capital=initial_capital,
            snapshot_id=snapshot_id,
            run_id=run_id,
            snapshot_at_utc=now_iso,
        )

        logger.warning(
            "event_invalidation TRIGGERED: thesis=%s direction=%s "
            "stop_loss=%.2f current=%.2f → 规则平仓(channel A)",
            thesis_id, sl_order["direction"],
            float(sl_order["price"]), current_btc_price,
        )

        return {
            "thesis_id": thesis_id,
            "status": "event_invalidation_executed",
            "stop_loss_order_id": stop_loss_order_id,
            "filled_price": current_btc_price,
            "close_result": close_result,
            # caller 装入 strategy_runs.retry_log_json(D4=b1)
            "retry_log_marker": {
                "event_invalidation_triggered": True,
                "event_invalidation_thesis_id": thesis_id,
                "event_invalidation_close_channel": "A",
                "event_invalidation_close_reason": "stop_loss_filled",
                "event_invalidation_at_utc": now_iso,
            },
        }

    # ------------------------------------------------------------------
    # 辅助:从 1h K 线读最新 close(jobs.py 调用前可用)
    # ------------------------------------------------------------------

    @staticmethod
    def get_latest_btc_price(
        conn: sqlite3.Connection,
    ) -> Optional[float]:
        """从最新 1h K 线读 close(jobs.py 1h cron 用)。"""
        try:
            row = conn.execute(
                "SELECT close FROM price_candles "
                "WHERE timeframe = '1h' "
                "ORDER BY open_time_utc DESC LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            v = row[0] if not hasattr(row, "keys") else row["close"]
            return float(v) if v is not None else None
        except sqlite3.OperationalError:
            return None
