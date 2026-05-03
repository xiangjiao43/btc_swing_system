#!/usr/bin/env python3
"""scripts/verify_orders_engine.py — Sprint 1.10-B 端到端真实断言(§Z 纪律)。

用真实 DB 创建测试 thesis + 3 entry 挂单 + 1 个虚拟 1H K 线快照,
调 OrdersEngine.check_and_fill_orders,SQL 断言:
  - 74000 那条挂单 status=filled
  - 70000 / 66000 仍 pending
  - computed_snapshot.long_position_usdt = 20000
  - computed_snapshot.long_avg_price = 74000
  - computed_snapshot.long_btc_amount = 20000/74000 ≈ 0.27027

清理:断言完成后删除测试数据(thesis / orders / 测试 K 线 / 测试 snapshot),
不污染 DB(即使 sql 报错也走 finally 清理)。

用法:
    .venv/bin/python scripts/verify_orders_engine.py [/path/to/db]
不传则用 config/base.yaml::paths.db_path。

退出码:0 全通过 / 1 任一失败。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from src.data.storage.dao import (  # noqa: E402
    BTCKlinesDAO, ThesesDAO, VirtualAccountDAO, VirtualOrdersDAO,
)
from src.strategy.orders_engine import check_and_fill_orders  # noqa: E402

_BASE_YAML = _REPO_ROOT / "config" / "base.yaml"

# 测试用固定标识(便于清理)
_TEST_THESIS_ID = "verify_orders_engine_test_thesis"
_TEST_ORDER_PREFIX = "verify_orders_engine_test_"
_TEST_KLINE_OPEN = "2026-05-04T10:00:00Z"  # 测试用 K 线
_TEST_SNAPSHOT_ID = "verify_orders_engine_test_snap"
_TEST_RUN_ID = "verify_orders_engine_test_run"


# ============================================================
# 断言工具(同 1.10-A verify 风格)
# ============================================================
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
# 清理(idempotent)
# ============================================================

def cleanup(conn: sqlite3.Connection) -> None:
    try:
        conn.execute(
            "DELETE FROM virtual_orders WHERE thesis_id=?",
            (_TEST_THESIS_ID,),
        )
        conn.execute(
            "DELETE FROM theses WHERE thesis_id=?",
            (_TEST_THESIS_ID,),
        )
        conn.execute(
            "DELETE FROM virtual_account WHERE snapshot_id=?",
            (_TEST_SNAPSHOT_ID,),
        )
        conn.execute(
            "DELETE FROM price_candles WHERE timeframe='1h' "
            "AND open_time_utc=? AND symbol='BTCUSDT'",
            (_TEST_KLINE_OPEN,),
        )
        conn.commit()
    except sqlite3.OperationalError as e:
        print(f"  ⚠ cleanup 部分失败(可能表不存在,忽略):{e}")


# ============================================================
# 主流程
# ============================================================

def load_config() -> dict:
    with open(_BASE_YAML, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def resolve_db_path(cfg: dict, cli_arg: str | None) -> Path:
    if cli_arg:
        return Path(cli_arg).resolve()
    rel = (cfg.get("paths") or {}).get("db_path", "data/btc_strategy.db")
    return (_REPO_ROOT / rel).resolve()


def setup_test_data(conn: sqlite3.Connection) -> None:
    """创建 1 thesis + 3 entry 挂单 + 1 K 线(high=78000, low=73000)。"""
    ThesesDAO.create(
        conn,
        thesis_id=_TEST_THESIS_ID,
        created_at_run_id=_TEST_RUN_ID,
        created_at_utc="2026-05-03T08:00:00Z",
        direction="long",
        core_logic="verify_orders_engine 测试 thesis",
        confidence_score=70,
        break_conditions=["test_c1", "test_c2", "test_c3"],
    )
    for sfx, price in (("a_74000", 74000.0), ("b_70000", 70000.0), ("c_66000", 66000.0)):
        VirtualOrdersDAO.create_order(
            conn,
            order_id=f"{_TEST_ORDER_PREFIX}{sfx}",
            thesis_id=_TEST_THESIS_ID,
            direction="long", order_type="entry",
            price=price, size_pct=0.20, size_usdt=20000.0,
            created_at_utc="2026-05-03T08:00:00Z",
            expires_at_utc="2026-12-01T00:00:00Z",
        )
    # K 线:high=78000, low=73000 → 仅 74000 在范围 [73000, 78000]
    conn.execute(
        "INSERT INTO price_candles "
        "(symbol, timeframe, open_time_utc, open, high, low, close, volume) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("BTCUSDT", "1h", _TEST_KLINE_OPEN,
         75000.0, 78000.0, 73000.0, 76500.0, 100.0),
    )
    conn.commit()


def main(argv: list[str]) -> int:
    cfg = load_config()
    db_path = resolve_db_path(cfg, argv[1] if len(argv) > 1 else None)
    initial_capital = float(
        (cfg.get("virtual_account") or {}).get("initial_capital", 100000)
    )

    print(f"[verify_orders_engine] DB: {db_path}")
    print(f"[verify_orders_engine] initial_capital: {initial_capital}")

    if not db_path.exists():
        print(f"❌ DB 文件不存在:{db_path}(请先跑 scripts/init_v14_tables.py)")
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        # pre-clean(避免上次跑残留)
        print("\n=== 0. pre-clean 残留测试数据 ===")
        cleanup(conn)
        print("  ✅ pre-clean 完成")

        # setup
        print("\n=== 1. setup:1 thesis + 3 entry 挂单 + 1 K 线 ===")
        setup_test_data(conn)
        print(f"  ✅ thesis_id={_TEST_THESIS_ID}")
        print(f"  ✅ orders @ 74000 / 70000 / 66000(各 20000 USDT)")
        print(f"  ✅ K 线 1h {_TEST_KLINE_OPEN} high=78000 low=73000")

        # 调引擎
        print("\n=== 2. 调 OrdersEngine.check_and_fill_orders ===")
        result = check_and_fill_orders(
            conn,
            thesis_id=_TEST_THESIS_ID,
            last_check_utc="2026-05-04T00:00:00Z",
            now_utc="2026-05-04T20:00:00Z",
            current_btc_price=76500.0,  # K 线 close
            initial_capital=initial_capital,
            snapshot_id=_TEST_SNAPSHOT_ID,
            run_id=_TEST_RUN_ID,
            snapshot_at_utc="2026-05-04T20:00:00Z",
        )
        conn.commit()
        print(f"  filled_orders count: {len(result['filled_orders'])}")
        print(f"  expired_count: {result['expired_count']}")
        print(f"  skipped_orders count: {len(result['skipped_orders'])}")

        # 断言 1: filled_orders 长度
        print("\n=== 3. SQL 断言 ===")
        check(
            "filled_orders 长度 = 1(只有 74000 在 [73000, 78000])",
            len(result["filled_orders"]) == 1,
            detail=f"实际 {len(result['filled_orders'])}",
        )

        # 断言 2: 唯一 fill 是 74000
        if result["filled_orders"]:
            f = result["filled_orders"][0]
            check(
                "filled_order.order_id 是 74000 那条",
                f["order_id"] == f"{_TEST_ORDER_PREFIX}a_74000",
                detail=f"实际 {f['order_id']}",
            )
            check(
                "filled_price = 74000(§5.2.4 入场价 = 挂单价)",
                f["filled_price"] == 74000.0,
                detail=f"实际 {f['filled_price']}",
            )
            check(
                "filled_btc_amount ≈ 20000/74000 = 0.27027027",
                almost_eq(f["filled_btc_amount"], 20000.0 / 74000.0, eps=1e-6),
                detail=f"实际 {f['filled_btc_amount']}",
            )

        # 断言 3: 70000 / 66000 仍 pending
        pending = VirtualOrdersDAO.get_pending(conn, thesis_id=_TEST_THESIS_ID)
        pending_ids = sorted(p["order_id"] for p in pending)
        expected_pending = sorted([
            f"{_TEST_ORDER_PREFIX}b_70000",
            f"{_TEST_ORDER_PREFIX}c_66000",
        ])
        check(
            "70000 / 66000 仍 pending",
            pending_ids == expected_pending,
            detail=f"实际 {pending_ids}",
        )

        # 断言 4: computed_snapshot 字段(D1=C:不 insert,只算)
        snap = result["computed_snapshot_for_account"]
        check(
            "computed_snapshot.long_position_usdt = 20000",
            snap["long_position_usdt"] == 20000.0,
            detail=f"实际 {snap['long_position_usdt']}",
        )
        check(
            "computed_snapshot.long_avg_price = 74000",
            snap["long_avg_price"] == 74000.0,
            detail=f"实际 {snap['long_avg_price']}",
        )
        check(
            "computed_snapshot.long_btc_amount ≈ 0.27027027",
            almost_eq(snap["long_btc_amount"], 20000.0 / 74000.0, eps=1e-6),
            detail=f"实际 {snap['long_btc_amount']}",
        )
        check(
            "computed_snapshot.available_cash = 80000(100000 - 20000)",
            snap["available_cash"] == 80000.0,
            detail=f"实际 {snap['available_cash']}",
        )

        # 断言 5: 上层确实可以 insert(D1=C 完整链路)
        print("\n=== 4. D1=C 链路验证:上层调 VirtualAccountDAO.insert_snapshot ===")
        VirtualAccountDAO.insert_snapshot(conn, **snap)
        conn.commit()
        latest = VirtualAccountDAO.get_latest(conn)
        check(
            "DB 中 latest snapshot.snapshot_id = 测试 snap_id(insert 成功)",
            latest["snapshot_id"] == _TEST_SNAPSHOT_ID,
            detail=f"实际 {latest['snapshot_id']}",
        )
        check(
            "DB 中 latest snapshot.long_position_usdt = 20000(字段持久化)",
            latest["long_position_usdt"] == 20000.0,
            detail=f"实际 {latest['long_position_usdt']}",
        )

    finally:
        # 清理:即使中间报错也 cleanup
        print("\n=== 5. cleanup ===")
        cleanup(conn)
        print("  ✅ cleanup 完成,DB 不污染")
        conn.close()

    print()
    print(f"=== 总结 ===")
    print(f"通过:{len(_PASSED)} 项")
    print(f"失败:{len(_FAILED)} 项")
    if _FAILED:
        print()
        print("失败详情:")
        for f in _FAILED:
            print(f"  ❌ {f}")
        print()
        print("❌ 全部通过 — 失败")
        return 1

    print()
    print("✅ 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
