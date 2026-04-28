#!/usr/bin/env python3
"""scripts/migrate_2_7_d.py — Sprint 2.7-D 幂等迁移。

应用:
1. CREATE TABLE event_throttle IF NOT EXISTS
2. ALTER TABLE events_calendar ADD COLUMN triggered_at_utc(检查存在性)

可重跑(idempotent):
- event_throttle 表用 IF NOT EXISTS
- triggered_at_utc 列检查 PRAGMA table_info,已存在则跳过

用法:
    .venv/bin/python scripts/migrate_2_7_d.py [/path/to/db]
不传参数则默认用 src.data.storage.connection.get_connection 路径。
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# 让脚本可独立执行(从仓库根目录)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def apply_migration(conn: sqlite3.Connection) -> dict[str, str]:
    """应用 2.7-D 迁移。返回 {step: status} 报告。"""
    report: dict[str, str] = {}

    # 1. event_throttle 表
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS event_throttle (
            event_type             TEXT PRIMARY KEY,
            last_triggered_at_utc  TEXT NOT NULL
        )
        """
    )
    report["event_throttle_table"] = "ok"

    # 2. events_calendar.triggered_at_utc 列(检查 PRAGMA)
    if column_exists(conn, "events_calendar", "triggered_at_utc"):
        report["triggered_at_utc_column"] = "skipped (already exists)"
    else:
        conn.execute(
            "ALTER TABLE events_calendar ADD COLUMN triggered_at_utc TEXT"
        )
        report["triggered_at_utc_column"] = "added"

    conn.commit()
    return report


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        db_path = Path(argv[1])
    else:
        from src.data.storage.connection import get_db_path
        db_path = get_db_path()

    print(f"[migrate_2_7_d] target DB: {db_path}")
    if not db_path.exists():
        print(f"[migrate_2_7_d] ERROR: DB does not exist at {db_path}")
        return 1

    conn = sqlite3.connect(db_path)
    try:
        report = apply_migration(conn)
        for step, status in report.items():
            print(f"[migrate_2_7_d]   {step}: {status}")
    finally:
        conn.close()
    print("[migrate_2_7_d] done.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
