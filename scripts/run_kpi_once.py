"""
scripts/run_kpi_once.py — 一键生成当前 KPI + 复盘 Markdown(Sprint 1.16 验收)

用法:
    unset VIRTUAL_ENV
    uv run python scripts/run_kpi_once.py                     # 周报
    uv run python scripts/run_kpi_once.py --period monthly    # 月报
    uv run python scripts/run_kpi_once.py --no-ai             # 跳过 AI 观察段
    uv run python scripts/run_kpi_once.py --print-kpi         # 打印 KPI JSON

默认输出:
    * KPI 摘要 → stdout
    * Markdown 报告 → data/reviews/<period>_<YYYYMMDD>.md
    * 当前活跃告警 → stdout
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import _env_loader  # noqa: F401
from src.data.storage.connection import get_connection, init_db
from src.kpi import KPICollector
from src.monitoring import check_alerts
from src.review import ReviewReportGenerator


_PERIOD_TO_DAYS = {"daily": 1, "weekly": 7, "monthly": 30}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", choices=list(_PERIOD_TO_DAYS), default="weekly")
    parser.add_argument("--no-ai", action="store_true",
                        help="不调 AI 生成第 7 节")
    parser.add_argument("--output-dir", default="data/reviews/")
    parser.add_argument("--print-kpi", action="store_true",
                        help="额外打印完整 KPI JSON")
    args = parser.parse_args()

    init_db(verbose=False)
    conn = get_connection()
    try:
        # --- KPI ---
        collector = KPICollector(conn)
        kpi = collector.compute_kpis(
            lookback_days=_PERIOD_TO_DAYS[args.period]
        )
        exec_ = kpi.get("execution") or {}
        fb = kpi.get("fallback") or {}
        print(
            f"[KPI] period={args.period} "
            f"runs_total={exec_.get('runs_total')} "
            f"runs_per_day={exec_.get('runs_per_day')} "
            f"fallback_events={fb.get('events_total')}"
        )
        if args.print_kpi:
            print(json.dumps(kpi, ensure_ascii=False, indent=2, default=str))

        # --- Review report ---
        gen = ReviewReportGenerator(conn, kpi_collector=collector)
        path = gen.generate_and_save(
            period=args.period,
            output_dir=args.output_dir,
            include_ai_narrative=not args.no_ai,
        )
        print(f"[Report] saved to {path}")

        # --- Alerts ---
        alerts = check_alerts(conn, lookback_hours=24)
        if not alerts:
            print("[Alerts] 无活跃告警(近 24h)")
        else:
            print(f"[Alerts] 活跃告警 {len(alerts)} 条:")
            for a in alerts:
                print(
                    f"  - [{a['level']}] {a['type']} stage={a.get('stage')} "
                    f"count={a.get('count')}"
                )
                print(f"      {a.get('message')}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
