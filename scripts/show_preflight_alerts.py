#!/usr/bin/env python3
"""scripts/show_preflight_alerts.py — Sprint 2.8-B 查询脚本。

打印最近 N 天(默认 7)的 pre_flight_degraded alerts,便于用户监控
pipeline 数据就绪状况。

用法:
    .venv/bin/python scripts/show_preflight_alerts.py
    .venv/bin/python scripts/show_preflight_alerts.py --days 1
    .venv/bin/python scripts/show_preflight_alerts.py --since 2026-04-28
    .venv/bin/python scripts/show_preflight_alerts.py --db /path/to/btc.db
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# 让脚本可独立执行
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.storage.connection import get_db_path  # noqa: E402

_BJT = ZoneInfo("Asia/Shanghai")


def _parse_since(since_arg: str | None, days: int) -> str:
    """返回查询起点的 ISO UTC。--since 优先;否则用 --days。"""
    if since_arg:
        # 接受 "2026-04-28" 或完整 ISO
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", since_arg):
            return f"{since_arg}T00:00:00Z"
        return since_arg
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_bjt(iso_utc: str) -> str:
    """ISO UTC → '2026-04-28 16:05 (BJT)' 字符串。"""
    try:
        ts = iso_utc.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts).astimezone(_BJT)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso_utc


def _extract_groups(message: str) -> str:
    """从 message 文本里提取 groups 列表,简短显示。"""
    m = re.search(r"groups:\s*\[([^\]]*)\]", message or "")
    if not m:
        return "?"
    return m.group(1).replace("'", "").strip()


def query_preflight_alerts(
    conn: sqlite3.Connection, since_iso: str,
) -> list[dict]:
    rows = conn.execute(
        "SELECT raised_at_utc, message, related_run_id "
        "FROM alerts "
        "WHERE alert_type = 'pre_flight_degraded' "
        "  AND raised_at_utc >= ? "
        "ORDER BY raised_at_utc DESC",
        (since_iso,),
    ).fetchall()
    return [
        {
            "raised_at_utc": r["raised_at_utc"]
            if isinstance(r, sqlite3.Row) else r[0],
            "message": r["message"]
            if isinstance(r, sqlite3.Row) else r[1],
            "related_run_id": r["related_run_id"]
            if isinstance(r, sqlite3.Row) else r[2],
        }
        for r in rows
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=7,
                    help="查询最近 N 天(默认 7)")
    ap.add_argument("--since", type=str, default=None,
                    help="起点 YYYY-MM-DD 或 ISO,优先于 --days")
    ap.add_argument("--db", type=str, default=None,
                    help="自定义 DB 路径(默认走 config/base.yaml)")
    args = ap.parse_args(argv)

    db_path = Path(args.db) if args.db else get_db_path()
    since_iso = _parse_since(args.since, args.days)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        alerts = query_preflight_alerts(conn, since_iso)
    finally:
        conn.close()

    print(f"[{len(alerts)}] alerts since {since_iso}")
    if not alerts:
        return 0

    print(f"{'timestamp_bjt':<18} | {'groups':<35} | run_id")
    print("-" * 80)
    for a in alerts:
        ts = _to_bjt(a["raised_at_utc"] or "")
        groups = _extract_groups(a["message"] or "")[:35]
        run_id = (a["related_run_id"] or "")[:8]
        print(f"{ts:<18} | {groups:<35} | {run_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
