#!/usr/bin/env python3
"""
test_macro_collector.py — Yahoo Finance + FRED 宏观采集验证脚本。

通过判据:
  - Yahoo 6 个 symbol 至少 5 个成功(> 0 行)
  - 每个成功的 metric 至少 100 行
  - FRED:若 key 在则 4 series 至少 3 个成功;key 不在则 skip,不影响 verdict
  - 退出码 0 PASS,1 FAIL
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)


def main() -> int:
    from src.data.collectors import FredCollector, YahooFinanceCollector
    from src.data.storage import MacroDAO, get_connection, init_db

    init_db()
    conn = get_connection()
    try:
        # ==============================
        # Yahoo Finance
        # ==============================
        yahoo = YahooFinanceCollector()
        yahoo_stats = yahoo.collect_and_save_all(conn)
        conn.commit()

        print()
        print("=" * 60)
        print("Yahoo Finance stats:")
        for metric, n in sorted(yahoo_stats.items()):
            print(f"  {metric:<16} {n:>6} rows")
        print("=" * 60)

        # ==============================
        # FRED
        # ==============================
        fred = FredCollector()
        if not fred.enabled:
            print("\nFRED: SKIPPED (FRED_API_KEY not set)")
            fred_stats: dict[str, int] = {}
        else:
            fred_stats = fred.collect_and_save_all(conn)
            conn.commit()
            print()
            print("=" * 60)
            print("FRED stats:")
            for metric, n in sorted(fred_stats.items()):
                print(f"  {metric:<20} {n:>6} rows")
            print("=" * 60)

        # ==============================
        # 最新值抽样
        # ==============================
        print()
        for m in ("dxy", "us10y", "vix", "sp500", "nasdaq", "gold_price"):
            latest = MacroDAO.get_latest(conn, metric_name=m)
            if latest:
                print(f"  latest {m:<12}: {latest['metric_value']:>10.4f}  @ "
                      f"{latest['timestamp']}  (src={latest['source']})")

        # ==============================
        # 判据
        # ==============================
        print()
        print("=" * 60)
        print("判据检查:")
        print("=" * 60)

        def check(label: str, passed: bool, detail: str) -> bool:
            print(f"  [{'✓' if passed else '✗'}] {label}: {detail}")
            return passed

        # Yahoo: 6 个 symbol 至少 5 个成功
        yahoo_success = sum(1 for n in yahoo_stats.values() if n > 0)
        yahoo_check = check(
            "Yahoo 6 symbols ≥ 5 成功",
            yahoo_success >= 5,
            f"{yahoo_success}/6 成功",
        )

        # Yahoo: 每个成功的 metric ≥ 100 行
        yahoo_row_checks = [
            check(
                f"  {m} ≥ 100 rows",
                n >= 100,
                f"{n} rows",
            )
            for m, n in yahoo_stats.items() if n > 0
        ]

        # FRED: 若 key 在则 4 series ≥ 3 成功;否则 skip check
        if fred.enabled:
            fred_success = sum(1 for n in fred_stats.values() if n > 0)
            fred_check = check(
                "FRED 4 series ≥ 3 成功",
                fred_success >= 3,
                f"{fred_success}/4 成功",
            )
        else:
            print("  [skip] FRED (no key)")
            fred_check = True

        all_ok = yahoo_check and all(yahoo_row_checks) and fred_check
        print()
        print("VERDICT:", "PASS ✓" if all_ok else "FAIL ✗")
        return 0 if all_ok else 1

    except Exception as e:
        logging.exception("collect failed: %s", e)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
