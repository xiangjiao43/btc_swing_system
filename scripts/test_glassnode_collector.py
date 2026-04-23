#!/usr/bin/env python3
"""
test_glassnode_collector.py — Glassnode 采集人工验证脚本。

运行(从项目根):
    unset VIRTUAL_ENV
    uv run python scripts/test_glassnode_collector.py

通过判据:
  - primary 5 个 metric 各 ≥ 100 行
  - display 7 个 metric 至少 5 个成功(余下允许 path 不准)
  - btc_price_close ≥ 500 行(720d 覆盖)
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src import _env_loader  # noqa: F401, E402

assert os.getenv("GLASSNODE_API_KEY"), (
    "GLASSNODE_API_KEY 未设置。请检查 .env 文件含 GLASSNODE_API_KEY "
    "(通常和 COINGLASS_API_KEY 同值)。"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)


def main() -> int:
    from src.data.collectors import GlassnodeCollector
    from src.data.storage import OnchainDAO, get_connection, init_db

    init_db()
    conn = get_connection()
    try:
        collector = GlassnodeCollector()
        stats = collector.collect_and_save_all(conn)
        conn.commit()

        print()
        print("=" * 60)
        print("Glassnode Collect stats:")
        for metric, count in sorted(stats.items()):
            print(f"  {metric:<28} {count:>6} rows")
        print("=" * 60)

        # 打印几个关键 metric 的最新值
        for metric in ("mvrv_z_score", "nupl", "lth_supply",
                       "exchange_net_flow", "btc_price_close"):
            latest = OnchainDAO.get_latest(conn, metric_name=metric)
            if latest:
                print(f"\nLatest {metric}: {latest['timestamp']} "
                      f"= {latest['metric_value']:.4f}  (source={latest['source']})")

        # --- 判据 ---
        print()
        print("=" * 60)
        print("判据检查:")
        print("=" * 60)

        def check(label: str, passed: bool, detail: str) -> bool:
            mark = "✓" if passed else "✗"
            print(f"  [{mark}] {label}: {detail}")
            return passed

        primary = ("mvrv_z_score", "nupl", "lth_supply",
                   "exchange_net_flow", "btc_price_close")
        display = ("mvrv", "realized_price", "lth_realized_price",
                   "sth_realized_price", "sopr", "sopr_adjusted",
                   "reserve_risk", "puell_multiple")

        # primary 5 个各 ≥ 100(btc_price_close 单独判更严)
        primary_checks = [
            check(f"primary {m} ≥ 100",
                  stats.get(m, 0) >= 100,
                  f"{stats.get(m, 0)} rows")
            for m in ("mvrv_z_score", "nupl", "lth_supply", "exchange_net_flow")
        ]
        price_check = check(
            "btc_price_close ≥ 500 (720d)",
            stats.get("btc_price_close", 0) >= 500,
            f"{stats.get('btc_price_close', 0)} rows",
        )

        # display 至少 5 个成功(> 0)
        display_ok_count = sum(1 for m in display if stats.get(m, 0) > 0)
        display_check = check(
            "display 7 ≥ 5 成功",
            display_ok_count >= 5,
            f"{display_ok_count}/7 成功",
        )

        all_ok = all(primary_checks) and price_check and display_check
        print()
        if all_ok:
            print("VERDICT: PASS ✓")
        else:
            print("VERDICT: FAIL ✗")
        return 0 if all_ok else 1
    except Exception as e:
        logging.exception("collect failed: %s", e)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
