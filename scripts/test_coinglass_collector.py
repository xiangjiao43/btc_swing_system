#!/usr/bin/env python3
"""
test_coinglass_collector.py — CoinGlass 采集人工验证脚本(Sprint 1.2 v2 fieldfix)

运行(从项目根):
    unset VIRTUAL_ENV   # 避免 Xcode Python 3.9 干扰
    uv run python scripts/test_coinglass_collector.py

动作:
    1. init_db()(幂等)
    2. 构造 CoinglassCollector(从 data_sources.yaml 读配置)
    3. collect_and_save_all(conn) → 4 档 K 线 + 5 衍生品端点
    4. 严格检查各数据量 + 打印每类数据的最新 3 条样本

通过判据(收紧):
  (a) K 线四档(1h/4h/1d/1w)各 ≥ 100 条
  (b) funding_rate / open_interest / long_short_ratio 各 ≥ 50 条
  (c) liquidation 至少一个方向有数据(liquidation_long 或 liquidation_short ≥ 1)
  (d) 其他衍生品(net_position)有无数据不影响 PASS,仅报告

限速 15 req/min,完整抓取 9 次请求约 32-60 秒。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# 让脚本从项目任意位置都能执行
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)


def _print_samples(title: str, rows: list[dict]) -> None:
    """打印若干样本行,字段值格式化。"""
    print(f"\n{title}({len(rows)} rows,最新 3 条):")
    if not rows:
        print("  <empty>")
        return
    for r in rows[:3]:
        # 价格类 vs 衍生品类:展示字段不同
        if "open" in r and "close" in r:
            print(f"  {r['timestamp']}  "
                  f"O={r['open']}  H={r['high']}  "
                  f"L={r['low']}  C={r['close']}  "
                  f"vol={r.get('volume_btc', 0):.2f}")
        else:
            print(f"  {r['timestamp']}  "
                  f"{r.get('metric_name', '?')} = {r.get('metric_value')}")


def main() -> int:
    from src.data.collectors import CoinglassCollector
    from src.data.storage import (
        BTCKlinesDAO,
        DerivativesDAO,
        get_connection,
        init_db,
    )

    init_db()
    conn = get_connection()
    try:
        collector = CoinglassCollector()
        stats = collector.collect_and_save_all(conn)
        conn.commit()

        print()
        print("=" * 60)
        print("Collect stats:")
        for label, n in stats.items():
            print(f"  {label:<22} {n:>6} rows")
        print("=" * 60)

        # --- 抽样打印 ---
        for tf in ("1h", "4h", "1d", "1w"):
            count = BTCKlinesDAO.count(conn, tf)
            latest = BTCKlinesDAO.get_klines(conn, timeframe=tf, limit=500)
            # get_klines 升序;取最新 3 条需要倒序后取
            latest_3 = list(reversed(latest))[:3] if latest else []
            _print_samples(f"K 线 [{tf}](总 {count} 根)", latest_3)

        for metric in (
            "funding_rate", "open_interest", "long_short_ratio",
            "liquidation_long", "liquidation_short", "liquidation_total",
            "net_position_long", "net_position_short",
        ):
            series = DerivativesDAO.get_series(conn, metric_name=metric)
            latest_3 = list(reversed(series))[:3] if series else []
            _print_samples(f"{metric}(总 {len(series)} 条)", latest_3)

        # --- 通过判据 ---
        print()
        print("=" * 60)
        print("判据检查:")
        print("=" * 60)

        def check(label: str, passed: bool, detail: str) -> bool:
            mark = "✓" if passed else "✗"
            print(f"  [{mark}] {label}: {detail}")
            return passed

        # (a) K 线四档各 ≥ 100
        kline_checks = [
            check(f"K 线 {tf} ≥ 100",
                  stats.get(f"klines_{tf}", 0) >= 100,
                  f"{stats.get(f'klines_{tf}', 0)} rows")
            for tf in ("1h", "4h", "1d", "1w")
        ]

        # (b) 三个核心衍生品各 ≥ 50
        # 注意:stats 里 funding_rate / open_interest / long_short_ratio
        # 的数值是 upsert 的 rowcount(通常等于行数)
        core_deriv_checks = [
            check(f"{m} ≥ 50",
                  stats.get(m, 0) >= 50,
                  f"{stats.get(m, 0)} rows")
            for m in ("funding_rate", "open_interest", "long_short_ratio")
        ]

        # (c) liquidation 至少一个方向
        # liquidation 端点的 stats 是 3 个 metric 合计;单独看 DAO:
        liq_long_count = len(DerivativesDAO.get_series(conn, "liquidation_long"))
        liq_short_count = len(DerivativesDAO.get_series(conn, "liquidation_short"))
        liq_check = check(
            "liquidation 至少一个方向 ≥ 1",
            liq_long_count >= 1 or liq_short_count >= 1,
            f"long={liq_long_count}, short={liq_short_count}",
        )

        all_ok = all(kline_checks) and all(core_deriv_checks) and liq_check
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
