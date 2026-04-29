#!/usr/bin/env python3
"""scripts/cleanup_hourly_pollution.py — Sprint 1.5f-revised 清污。

derivatives_snapshots 表里有 hourly 行(SSH 调试 fetch_*(interval='1h')
遗留写入)+ daily 行混存,导致派生因子算法 (7d 均 / 30d 分位 / 90d Z) 用
series.tail(N) 假设 daily,实际取的是混合频率 N 行 ≈ N/24 ~ N/2 天。

本脚本删除所有"非 00:00:00Z"的行,只保留 daily。

用法:
    .venv/bin/python scripts/cleanup_hourly_pollution.py            # dry-run
    .venv/bin/python scripts/cleanup_hourly_pollution.py --execute  # 真删
    .venv/bin/python scripts/cleanup_hourly_pollution.py --execute --db /path/to/x.db

幂等:重跑只会显示 0 行待删。
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
    ap.add_argument("--execute", action="store_true",
                    help="真执行 DELETE(默认 dry-run)")
    args = ap.parse_args(argv)

    if args.db:
        db_path = Path(args.db)
    else:
        from src.data.storage.connection import get_db_path
        db_path = get_db_path()

    print(f"[cleanup-hourly] DB: {db_path}")
    if not db_path.exists():
        print("[cleanup-hourly] DB not found")
        return 1

    conn = sqlite3.connect(db_path)
    try:
        # Step 1:统计
        total_before = _count(conn, "SELECT COUNT(*) FROM derivatives_snapshots")
        hourly = _count(
            conn,
            "SELECT COUNT(*) FROM derivatives_snapshots "
            "WHERE captured_at_utc NOT LIKE '%T00:00:00Z'",
        )
        daily = total_before - hourly
        print(f"[scan] total rows:  {total_before}")
        print(f"[scan] daily rows:  {daily}")
        print(f"[scan] hourly rows: {hourly} (will DELETE)")

        if hourly == 0:
            print("[cleanup-hourly] No hourly pollution — nothing to do.")
            return 0

        if not args.execute:
            print("[cleanup-hourly] DRY-RUN done. Re-run with --execute to delete.")
            return 0

        # Step 2:DELETE
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM derivatives_snapshots "
            "WHERE captured_at_utc NOT LIKE '%T00:00:00Z'"
        )
        deleted = cur.rowcount
        conn.commit()
        print(f"[apply] DELETED {deleted} hourly rows")

        # Step 3:VACUUM(回收空间;非 transaction)
        conn.execute("VACUUM")
        print("[apply] VACUUM done")

        # Step 4:验证
        total_after = _count(conn, "SELECT COUNT(*) FROM derivatives_snapshots")
        hourly_after = _count(
            conn,
            "SELECT COUNT(*) FROM derivatives_snapshots "
            "WHERE captured_at_utc NOT LIKE '%T00:00:00Z'",
        )
        print(f"[verify] total rows after: {total_after} (was {total_before})")
        print(f"[verify] hourly rows after: {hourly_after} (must be 0)")
        if hourly_after != 0:
            print("[verify] ❌ FAILED: hourly rows remain")
            return 2
        print("[cleanup-hourly] OK")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
