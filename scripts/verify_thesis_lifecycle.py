#!/usr/bin/env python3
"""scripts/verify_thesis_lifecycle.py — Sprint 1.10-C 端到端真实断言(§Z)。

完整模拟 thesis lifecycle + 反手通道 + 14 天熔断 + 60 天上限 + review_pending,
SQL 断言每一步状态。

测试数据用 prefix `verify_1_10_c_lifecycle_*`(继承 1.10-B 风险 #4 教训:稳定 prefix +
pre/post cleanup,即使中间报错也不污染 DB)。

用法:.venv/bin/python scripts/verify_thesis_lifecycle.py [/path/to/db]
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from src.data.storage.dao import (  # noqa: E402
    ThesesDAO, VirtualAccountDAO, VirtualOrdersDAO,
)
from src.strategy.cooldown_manager import (  # noqa: E402
    determine_close_channel, compute_cooldown_end, is_in_cooldown,
)
from src.strategy.fuse_monitor import (  # noqa: E402
    record_thesis_cycle, record_channel_c_use, record_14d_fuse_triggered,
    check_14d_fuse, check_60d_cap, mark_60d_capped, check_consecutive_fuse,
)
from src.strategy.review_pending import (  # noqa: E402
    enter_review_pending, is_in_review_pending,
    exit_a_threshold_adjustment, exit_c_fuse_reset,
)
from src.strategy.thesis_manager import (  # noqa: E402
    create_thesis, advance_lifecycle, close_thesis,
)


_BASE_YAML = _REPO_ROOT / "config" / "base.yaml"
_PREFIX = "verify_1_10_c_lifecycle_"
_TEST_RUN_ID = f"{_PREFIX}run"


# 断言工具
_PASSED: list[str] = []
_FAILED: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        _PASSED.append(label)
        print(f"  ✅ {label}")
    else:
        _FAILED.append(f"{label} | {detail}")
        print(f"  ❌ {label} | {detail}")


def almost_eq(a: float, b: float, eps: float = 1e-6) -> bool:
    return abs(a - b) < eps


# ============================================================
# cleanup
# ============================================================

def cleanup(conn: sqlite3.Connection) -> None:
    """删测试数据(基于 prefix)。"""
    try:
        conn.execute(
            "DELETE FROM virtual_orders WHERE thesis_id LIKE ?", (f"{_PREFIX}%",),
        )
        conn.execute(
            "DELETE FROM theses WHERE thesis_id LIKE ?", (f"{_PREFIX}%",),
        )
        conn.execute(
            "DELETE FROM virtual_account WHERE snapshot_id LIKE ?", (f"{_PREFIX}%",),
        )
        conn.execute(
            "DELETE FROM fuse_events WHERE thesis_id LIKE ? OR thesis_id IS NULL "
            "AND metadata_json LIKE ?",
            (f"{_PREFIX}%", f"%{_PREFIX}%"),
        )
        # 14d_fuse_triggered 没 thesis_id,但 metadata_json 含 prefix(若有)
        conn.execute(
            "DELETE FROM fuse_events WHERE event_type='14d_fuse_triggered' "
            "AND metadata_json LIKE ?",
            (f"%{_PREFIX}%",),
        )
        conn.execute(
            "DELETE FROM system_states WHERE related_thesis_id LIKE ? "
            "OR reason LIKE ?",
            (f"{_PREFIX}%", f"%{_PREFIX}%"),
        )
        conn.commit()
    except sqlite3.OperationalError as e:
        print(f"  ⚠ cleanup 部分失败(可能表不存在,忽略):{e}")


# ============================================================
# helpers
# ============================================================

def load_config() -> dict:
    with open(_BASE_YAML, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def resolve_db_path(cfg: dict, cli_arg: str | None) -> Path:
    if cli_arg:
        return Path(cli_arg).resolve()
    rel = (cfg.get("paths") or {}).get("db_path", "data/btc_strategy.db")
    return (_REPO_ROOT / rel).resolve()


def _spec(thesis_id_suffix: str) -> dict:
    return {
        "direction": "long",
        "core_logic": f"verify_1_10_c thesis {thesis_id_suffix}",
        "confidence_score": 70,
        "break_conditions": ["c1", "c2", "c3"],
        "entry_orders": [
            {"price": 74000.0, "size_pct": 0.20, "size_usdt": 20000.0},
        ],
        "stop_loss_orders": [
            {"price": 67000.0, "size_pct": 1.00, "size_usdt": 20000.0},
        ],
        "take_profit_orders": [
            {"price": 80000.0, "size_pct": 0.50, "size_usdt": 10000.0},
            {"price": 85000.0, "size_pct": 0.50, "size_usdt": 10000.0},
        ],
    }


# ============================================================
# 主流程
# ============================================================

def main(argv: list[str]) -> int:
    cfg = load_config()
    db_path = resolve_db_path(cfg, argv[1] if len(argv) > 1 else None)
    initial_capital = float((cfg.get("virtual_account") or {}).get("initial_capital", 100000))

    print(f"[verify_thesis_lifecycle] DB: {db_path}")
    if not db_path.exists():
        print(f"❌ DB 文件不存在,先跑 scripts/init_v14_tables.py")
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # 自动 apply migrations(idempotent;复用 init_v14_tables.apply_migration 确保 010 已上)
    try:
        from scripts.init_v14_tables import apply_migration as _apply
        _apply(conn)
        conn.commit()
        print("[verify_thesis_lifecycle] migration 009 + 010 applied (idempotent)")
    except Exception as e:
        print(f"[verify_thesis_lifecycle] ⚠ apply_migration 失败:{e}(继续,可能 schema 已就位)")

    try:
        print("\n=== 0. pre-clean ===")
        cleanup(conn)
        print("  ✅ pre-clean 完成")

        # ============================================================
        # Section 1: 完整 thesis lifecycle (planned → ... → closed_profit)
        # ============================================================
        print("\n=== 1. 创建 long thesis(planned)===")
        tid_a = f"{_PREFIX}a"
        res = create_thesis(
            conn, thesis_spec=_spec("a"),
            run_id=_TEST_RUN_ID,
            now_utc="2026-04-01T08:00:00Z",
            expires_at_utc="2026-12-01T00:00:00Z",
            thesis_id=tid_a,
        )
        conn.commit()
        check("create_thesis 写入 theses + 5 挂单",
              len(res["entry_order_ids"]) == 1
              and len(res["stop_loss_order_ids"]) == 1
              and len(res["take_profit_order_ids"]) == 2)
        th = conn.execute("SELECT * FROM theses WHERE thesis_id=?", (tid_a,)).fetchone()
        check("初始 lifecycle_stage = planned",
              th["lifecycle_stage"] == "planned")

        print("\n=== 2. entry filled → advance to opened ===")
        eid = res["entry_order_ids"][0]
        VirtualOrdersDAO.fill_order(
            conn, eid, "2026-04-02T10:00:00Z", 74000.0, 20000.0/74000.0,
        )
        conn.commit()
        fills_entry = [{
            "order_id": eid, "thesis_id": tid_a, "direction": "long",
            "order_type": "entry", "size_usdt": 20000.0,
            "filled_price": 74000.0, "filled_btc_amount": 20000.0/74000.0,
            "filled_at_utc": "2026-04-02T10:00:00Z",
        }]
        adv = advance_lifecycle(
            conn, thesis_id=tid_a, fills=fills_entry,
            prev_snapshot=None, current_btc_price=74000.0,
            now_utc="2026-04-02T10:01:00Z",
        )
        conn.commit()
        check("planned → opened", adv["new_stage"] == "opened")

        print("\n=== 3. 24h + 浮盈 ≥ 2% → advance to holding ===")
        # 模拟 prev_snapshot:已开仓 0.27027 BTC @ 74000
        prev_snap = {
            "long_position_usdt": 20000.0,
            "long_avg_price": 74000.0,
            "long_btc_amount": 20000.0 / 74000.0,
            "short_position_usdt": 0.0, "short_avg_price": None, "short_btc_amount": 0.0,
            "available_cash": 80000.0, "realized_pnl_total": 0.0,
        }
        adv2 = advance_lifecycle(
            conn, thesis_id=tid_a, fills=[],
            prev_snapshot=prev_snap, current_btc_price=76500.0,  # +3.4%
            now_utc="2026-04-04T10:01:00Z",  # +48h
        )
        conn.commit()
        check("opened → holding(24h + 浮盈 ≥ 2%)", adv2["new_stage"] == "holding")

        print("\n=== 4. tp1 filled → trim ===")
        tp1_id = res["take_profit_order_ids"][0]
        VirtualOrdersDAO.fill_order(
            conn, tp1_id, "2026-05-01T08:00:00Z", 80000.0,
            (20000.0 / 74000.0) / 2,
        )
        conn.commit()
        fills_tp1 = [{
            "order_id": tp1_id, "thesis_id": tid_a, "direction": "long",
            "order_type": "take_profit", "size_usdt": 10000.0,
            "filled_price": 80000.0,
            "filled_btc_amount": (20000.0/74000.0) / 2,
            "filled_at_utc": "2026-05-01T08:00:00Z",
        }]
        adv3 = advance_lifecycle(
            conn, thesis_id=tid_a, fills=fills_tp1,
            prev_snapshot=prev_snap, current_btc_price=80000.0,
            now_utc="2026-05-01T08:01:00Z",
        )
        conn.commit()
        check("holding → trim", adv3["new_stage"] == "trim")

        print("\n=== 5. tp2 filled → ready_to_close ===")
        tp2_id = res["take_profit_order_ids"][1]
        VirtualOrdersDAO.fill_order(
            conn, tp2_id, "2026-05-05T09:00:00Z", 85000.0,
            (20000.0 / 74000.0) / 2,
        )
        conn.commit()
        fills_tp2 = [{
            "order_id": tp2_id, "thesis_id": tid_a, "direction": "long",
            "order_type": "take_profit", "size_usdt": 10000.0,
            "filled_price": 85000.0,
            "filled_btc_amount": (20000.0/74000.0) / 2,
            "filled_at_utc": "2026-05-05T09:00:00Z",
        }]
        adv4 = advance_lifecycle(
            conn, thesis_id=tid_a, fills=fills_tp2,
            prev_snapshot=prev_snap, current_btc_price=85000.0,
            now_utc="2026-05-05T09:01:00Z",
        )
        check("trim → ready_to_close + reason=all_take_profit_filled",
              adv4["ready_to_close"] and adv4["close_reason"] == "all_take_profit_filled")

        print("\n=== 6. close_thesis (channel A) ===")
        # D3=a 用 last fill 时间作 closed_at_utc
        all_close_fills = fills_tp1 + fills_tp2
        last_filled_at = max(f["filled_at_utc"] for f in all_close_fills)
        # 写 prev_snapshot 到 DB(供 close_thesis 调 get_latest)
        # snapshot_at_utc 用 "future" 保证 = latest(避免被 init_v14_tables 真 snapshot 抢先)
        VirtualAccountDAO.insert_snapshot(
            conn, snapshot_id=f"{_PREFIX}prev",
            run_id=_TEST_RUN_ID,
            snapshot_at_utc="2099-04-30T08:00:00Z",
            btc_price_at_snapshot=74000.0,
            initial_capital=initial_capital,
            **{k: v for k, v in prev_snap.items() if k in (
                "available_cash", "long_position_usdt", "long_avg_price",
                "long_btc_amount", "short_position_usdt", "short_avg_price",
                "short_btc_amount", "realized_pnl_total",
            )},
            total_equity=initial_capital,
        )
        conn.commit()

        ch = determine_close_channel("all_take_profit_filled")
        check("determine_close_channel = A(自然结束)", ch == "A")

        close_res = close_thesis(
            conn, thesis_id=tid_a,
            reason="all_take_profit_filled", close_channel=ch,
            closed_at_utc=last_filled_at,
            fills_for_close=all_close_fills,
            current_btc_price=85000.0,
            initial_capital=initial_capital,
            snapshot_id=f"{_PREFIX}snap_close_a", run_id=f"{_TEST_RUN_ID}_close",
            snapshot_at_utc="2026-05-05T09:02:00Z",
        )
        conn.commit()
        check("close_thesis status = closed_profit",
              close_res["status"] == "closed_profit")
        check("close_thesis final_realized_pnl > 0",
              close_res["final_realized_pnl"] > 0)
        # 残余挂单 cancel(stop_loss 还在 pending)
        check("close_thesis cancel 残余 pending(≥1 个 stop_loss)",
              close_res["cancelled_pending_count"] >= 1)
        # DB 状态
        th_after = conn.execute("SELECT * FROM theses WHERE thesis_id=?", (tid_a,)).fetchone()
        check("DB theses.closed_at_utc = 最后 fill 时间(D3=a)",
              th_after["closed_at_utc"] == last_filled_at)
        check("DB theses.lifecycle_stage = closed",
              th_after["lifecycle_stage"] == "closed")

        print("\n=== 7. is_in_cooldown(channel A 72h)===")
        # 关闭瞬间 → 在冷却
        cd1 = is_in_cooldown(
            "2026-05-05T10:00:00Z",
            latest_closed_thesis=dict(th_after),
        )
        check("close 后 1h 仍在冷却 + remaining ≈ 71h",
              cd1["in_cooldown"] and 70.5 < cd1["remaining_hours"] < 72.0)
        # 72h 之后不冷却
        cd2 = is_in_cooldown(
            "2026-05-08T10:00:00Z",
            latest_closed_thesis=dict(th_after),
        )
        check("close 后 73h 不冷却", not cd2["in_cooldown"])

        # 写 fuse_events thesis_cycle(为后续 14d 熔断测试)
        record_thesis_cycle(conn, tid_a, last_filled_at)
        conn.commit()

        # ============================================================
        # Section 2: invalidated thesis → channel B
        # ============================================================
        print("\n=== 8. 第二个 thesis: invalidated → channel B ===")
        tid_b = f"{_PREFIX}b"
        create_thesis(
            conn, thesis_spec=_spec("b"),
            run_id=_TEST_RUN_ID, now_utc="2026-05-09T08:00:00Z",
            expires_at_utc="2026-12-01T00:00:00Z", thesis_id=tid_b,
        )
        conn.commit()
        ch_b = determine_close_channel("invalidated")
        check("invalidated 默认 channel = B", ch_b == "B")

        close_b = close_thesis(
            conn, thesis_id=tid_b,
            reason="invalidated", close_channel=ch_b,
            closed_at_utc="2026-05-12T10:00:00Z",
            fills_for_close=[],
            current_btc_price=70000.0,
            initial_capital=initial_capital,
            snapshot_id=f"{_PREFIX}snap_close_b", run_id=f"{_TEST_RUN_ID}_close_b",
            snapshot_at_utc="2026-05-12T10:01:00Z",
            invalidated_reason="DXY 突破 110 持续 3 天 已触发",
        )
        conn.commit()
        check("close_thesis status = invalidated", close_b["status"] == "invalidated")
        check("close_b channel = B", close_b["close_channel"] == "B")
        record_thesis_cycle(conn, tid_b, "2026-05-12T10:00:00Z")
        conn.commit()

        # ============================================================
        # Section 3: 14 天熔断检测(2 thesis cycles 在 14 天内)
        # ============================================================
        print("\n=== 9. 14 天熔断检测(2 thesis cycles)===")
        fuse = check_14d_fuse(conn, "2026-05-13T08:00:00Z")
        check("14d 内 thesis_cycle_count = 2", fuse["thesis_cycle_count_14d"] == 2)
        check("in_thesis_cycle_fuse=True", fuse["in_thesis_cycle_fuse"])
        check("in_fuse=True", fuse["in_fuse"])

        # ============================================================
        # Section 4: 60 天上限(D4=b 显式字段)
        # ============================================================
        print("\n=== 10. 60 天上限(D4=b 维持 lifecycle_stage)===")
        tid_c = f"{_PREFIX}c"
        create_thesis(
            conn, thesis_spec=_spec("c"),
            run_id=_TEST_RUN_ID,
            now_utc="2026-04-01T08:00:00Z",  # 创建于 60+ 天前
            expires_at_utc="2026-12-01T00:00:00Z", thesis_id=tid_c,
        )
        conn.commit()
        # 60+ 天后查
        triggers = check_60d_cap(conn, tid_c, "2026-06-15T08:00:00Z")
        check("60d_cap triggers 60+ 天后", triggers)
        n = mark_60d_capped(conn, tid_c)
        conn.commit()
        check("mark_60d_capped 写入 1 行", n == 1)
        # 已标记 → 再 check 不触发
        triggers2 = check_60d_cap(conn, tid_c, "2026-06-15T08:00:00Z")
        check("已标记后不再触发(防重复)", not triggers2)
        # D4=b:lifecycle_stage 维持(不进 closed)
        th_c = conn.execute(
            "SELECT lifecycle_stage, status, is_60d_capped FROM theses WHERE thesis_id=?",
            (tid_c,),
        ).fetchone()
        check("60d-capped thesis status 维持 active(D4=b)",
              th_c["status"] == "active")
        check("60d-capped thesis lifecycle_stage 维持 planned(未进 closed)",
              th_c["lifecycle_stage"] == "planned")
        check("is_60d_capped = 1 持久化", th_c["is_60d_capped"] == 1)

        # ============================================================
        # Section 5: review_pending 三出口
        # ============================================================
        print("\n=== 11. review_pending enter / exit ===")
        ent = enter_review_pending(
            conn, reason=f"{_PREFIX}validator_19_60d_cap",
            related_thesis_id=tid_c, entered_at_utc="2026-06-15T08:00:00Z",
        )
        conn.commit()
        check("enter_review_pending 返 state_id > 0",
              ent["state_id"] > 0 and not ent["was_already_active"])
        st = is_in_review_pending(conn)
        check("is_in_review_pending = True", st["in_review_pending"])
        # exit_a
        ex = exit_a_threshold_adjustment(conn, "2026-06-16T08:00:00Z")
        conn.commit()
        check("exit_a 完成", ex["exited"])
        check("exit 后不在 review_pending",
              not is_in_review_pending(conn)["in_review_pending"])

        # ============================================================
        # Section 6: 连续 14 天熔断 → review_pending 触发
        # ============================================================
        print("\n=== 12. 连续 14 天熔断 → review_pending(Validator 20)===")
        record_14d_fuse_triggered(
            conn, "2026-04-01T08:00:00Z",
            fuse_subtype=f"{_PREFIX}_test_subtype_1",
            metadata={"prefix": _PREFIX},
        )
        record_14d_fuse_triggered(
            conn, "2026-04-25T08:00:00Z",
            fuse_subtype=f"{_PREFIX}_test_subtype_2",
            metadata={"prefix": _PREFIX},
        )
        conn.commit()
        cons = check_consecutive_fuse(conn, "2026-05-10T08:00:00Z")
        check("90 天内 14d_fuse 事件 ≥ 2",
              cons["fuse_count_90d"] >= 2)
        check("triggers_review_pending = True",
              cons["triggers_review_pending"])

        # exit_c reset 熔断
        enter_review_pending(
            conn, reason=f"{_PREFIX}validator_20_consecutive_fuse",
            related_thesis_id=None, entered_at_utc="2026-05-10T08:00:00Z",
        )
        conn.commit()
        ex_c = exit_c_fuse_reset(conn, "2026-05-12T08:00:00Z")
        conn.commit()
        check("exit_c_fuse_reset 删 14d_fuse 行 ≥ 2",
              ex_c["exited"] and ex_c["fuse_records_deleted"] >= 2)
        cons_after = check_consecutive_fuse(conn, "2026-05-13T08:00:00Z")
        check("reset 后不再触发 review_pending",
              not cons_after["triggers_review_pending"])

    finally:
        print("\n=== 13. cleanup ===")
        cleanup(conn)
        print("  ✅ cleanup 完成")
        conn.close()

    print()
    print(f"=== 总结 ===")
    print(f"通过:{len(_PASSED)} 项")
    print(f"失败:{len(_FAILED)} 项")
    if _FAILED:
        for f in _FAILED:
            print(f"  ❌ {f}")
        print("\n❌ 全部通过 — 失败")
        return 1

    print("\n✅ 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
