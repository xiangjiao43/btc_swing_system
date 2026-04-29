#!/usr/bin/env python3
"""scripts/cleanup_zero_liquidation.py — Sprint 1.5e.1 假 0 清理。

老 1.5e bug `(long_val or 0.0) + (short_val or 0.0)` 单边 None 时把 total 写成
另一侧值 → DB 历史污染。本脚本扫 derivatives_snapshots 处理 3 类污染:

1. 全失败 row(funding_rate IS NULL AND liquidation_total = 0)→ DELETE
2. long=0 + short>0 → long=NULL, total=short(单边失败但短侧有真值)
3. long>0 + short=0 → 反之

dry-run 默认开启,显示"会删/会改多少行";-y / --apply 才真执行。

用法:
    .venv/bin/python scripts/cleanup_zero_liquidation.py             # dry-run
    .venv/bin/python scripts/cleanup_zero_liquidation.py --apply
    .venv/bin/python scripts/cleanup_zero_liquidation.py --db /path/to/x.db
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _count(conn: sqlite3.Connection, sql: str, params=()) -> int:
    return int(conn.execute(sql, params).fetchone()[0] or 0)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=str, default=None,
                    help="自定义 DB 路径(默认走 config/base.yaml)")
    ap.add_argument("--apply", "-y", action="store_true",
                    help="真执行(默认 dry-run)")
    args = ap.parse_args(argv)

    if args.db:
        db_path = Path(args.db)
    else:
        from src.data.storage.connection import get_db_path
        db_path = get_db_path()

    print(f"[cleanup-zero-liq] DB: {db_path}")
    if not db_path.exists():
        print("[cleanup-zero-liq] DB not found")
        return 1

    conn = sqlite3.connect(db_path)
    try:
        n_total_zero = _count(
            conn, "SELECT COUNT(*) FROM derivatives_snapshots "
                  "WHERE liquidation_total = 0"
        )
        n_full_fail = _count(
            conn, "SELECT COUNT(*) FROM derivatives_snapshots "
                  "WHERE liquidation_total = 0 AND funding_rate IS NULL"
        )
        n_long_zero = _count(
            conn, "SELECT COUNT(*) FROM derivatives_snapshots "
                  "WHERE liquidation_long = 0 AND liquidation_short > 0"
        )
        n_short_zero = _count(
            conn, "SELECT COUNT(*) FROM derivatives_snapshots "
                  "WHERE liquidation_long > 0 AND liquidation_short = 0"
        )
        print(f"[scan] liquidation_total=0 rows: {n_total_zero}")
        print(f"[scan] full-fail rows (will DELETE): {n_full_fail}")
        print(f"[scan] long=0 short>0 rows (will fix): {n_long_zero}")
        print(f"[scan] long>0 short=0 rows (will fix): {n_short_zero}")

        if not args.apply:
            print("[cleanup-zero-liq] DRY-RUN done. Re-run with --apply to execute.")
            return 0

        # 真执行
        cur = conn.cursor()
        # 1. 全失败 row → 删
        d = cur.execute(
            "DELETE FROM derivatives_snapshots "
            "WHERE liquidation_total = 0 AND funding_rate IS NULL"
        )
        deleted = d.rowcount
        # 2. long=0 short>0 → long=NULL, total=short
        u1 = cur.execute(
            "UPDATE derivatives_snapshots "
            "SET liquidation_long = NULL, liquidation_total = liquidation_short "
            "WHERE liquidation_long = 0 AND liquidation_short > 0"
        )
        fixed_long = u1.rowcount
        # 3. long>0 short=0 → short=NULL, total=long
        u2 = cur.execute(
            "UPDATE derivatives_snapshots "
            "SET liquidation_short = NULL, liquidation_total = liquidation_long "
            "WHERE liquidation_long > 0 AND liquidation_short = 0"
        )
        fixed_short = u2.rowcount
        conn.commit()
        print(f"[apply] deleted={deleted}, fixed_long={fixed_long}, fixed_short={fixed_short}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
