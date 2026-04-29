#!/usr/bin/env python3
"""scripts/fix_review_reports_schema.py — Sprint 1.5b-C.1 hotfix。

把生产 DB 残留的 Sprint 1 老版 review_reports 表 schema 对齐建模 §10.4。

逻辑(全部委托 src/data/storage/connection.py::init_db):
- 已是新 schema → 不动
- 仍是老 schema(行数 0)→ DROP + 重建
- 仍是老 schema(行数 > 0)→ ABORT(生产 lifecycle 还没归档过,理论行数 0;
  如真有数据需用户手动导出,避免静默丢数据)

用法:
    .venv/bin/python scripts/fix_review_reports_schema.py [/path/to/db]
不传参数走 config/base.yaml 的 paths.db_path。
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


# 让脚本可独立执行(从仓库根目录)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _cols(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [r[1] for r in rows]


def main(argv: list[str] | None = None) -> int:
    from src.data.storage.connection import get_db_path, init_db

    db_path = Path(argv[1]) if argv and len(argv) > 1 else get_db_path()
    print(f"[fix-review-reports] target DB: {db_path}")

    if not db_path.exists():
        print(f"[fix-review-reports] DB not found at {db_path}; nothing to fix")
        return 0

    # 检测当前 schema
    conn = sqlite3.connect(db_path)
    try:
        cols_before = _cols(conn, "review_reports")
        print(f"[fix-review-reports] before: review_reports cols = {cols_before}")
        if "review_id" in cols_before:
            print("[fix-review-reports] already new schema, no action")
            return 0
        if "run_timestamp_utc" not in cols_before:
            if not cols_before:
                print(
                    "[fix-review-reports] review_reports table not present; "
                    "init_db will create it from schema.sql"
                )
            else:
                print(
                    f"[fix-review-reports] unknown schema, no action: {cols_before}"
                )
        n = conn.execute(
            "SELECT COUNT(*) FROM review_reports"
        ).fetchone()[0] if cols_before else 0
        print(f"[fix-review-reports] legacy row count: {n}")
    finally:
        conn.close()

    # 调 init_db(它会自动跑 _fix_legacy_review_reports_schema 然后 schema.sql)
    init_db(db_path=db_path, verbose=True)

    # 验证修复成功
    conn = sqlite3.connect(db_path)
    try:
        cols_after = _cols(conn, "review_reports")
    finally:
        conn.close()
    print(f"[fix-review-reports] after: review_reports cols = {cols_after}")

    if "review_id" not in cols_after:
        print("[fix-review-reports] FAILED: review_id column missing")
        return 2
    print("[fix-review-reports] OK: schema aligned to §10.4")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
