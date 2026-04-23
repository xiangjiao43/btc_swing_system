#!/usr/bin/env python3
"""
test_coinglass_collector.py — CoinGlass 采集人工验证脚本。

运行(从项目根):
    unset VIRTUAL_ENV   # 避免 Xcode Python 3.9 干扰
    uv run python scripts/test_coinglass_collector.py

动作:
    1. init_db()(幂等)
    2. 构造 CoinglassCollector(从 data_sources.yaml 读配置)
    3. collect_and_save_all(conn) → 4 档 K 线 + 5 衍生品端点
    4. 打印统计 + 抽查最新 5 根 1d K 线 + 最新 funding_rate

通过判据:
    - K 线 4 档至少 1d 和 4h 成功(> 0)
    - funding_rate / open_interest / long_short_ratio 至少有一个成功
    - 最新 1d K 线能读出

注意限速:15 req/min,本脚本会发 9 次请求,完整跑完约 36-60 秒。
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


def main() -> int:
    from src.data.collectors import CoinglassCollector
    from src.data.storage import BTCKlinesDAO, DerivativesDAO, get_connection, init_db

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

        total_1d = BTCKlinesDAO.count(conn, "1d")
        print(f"\n1d K 线:共 {total_1d} 根")

        klines = BTCKlinesDAO.get_klines(conn, timeframe="1d", limit=5)
        if klines:
            print(f"\n最旧 5 根(升序):")
            for k in klines:
                print(f"  {k['timestamp']} "
                      f"O={k['open']}  H={k['high']}  "
                      f"L={k['low']}  C={k['close']}")

        latest = BTCKlinesDAO.get_latest_kline(conn, "1d")
        if latest:
            print(f"\n最新 1d K 线:")
            print(f"  {latest['timestamp']} "
                  f"O={latest['open']}  H={latest['high']}  "
                  f"L={latest['low']}  C={latest['close']}  "
                  f"vol={latest['volume_btc']:.4f} BTC")

        # 抽查各衍生品最新值
        print()
        for metric in ("funding_rate", "open_interest", "long_short_ratio",
                       "liquidation", "net_position"):
            row = DerivativesDAO.get_latest(conn, metric_name=metric)
            if row:
                print(f"  latest {metric:<20}: {row['metric_value']} @ {row['timestamp']}")
            else:
                print(f"  latest {metric:<20}: <none>")

        # 判据
        klines_ok = stats.get("klines_1d", 0) > 0 and stats.get("klines_4h", 0) > 0
        any_derivs_ok = any(
            stats.get(k, 0) > 0
            for k in ("funding_rate", "open_interest", "long_short_ratio",
                      "liquidation", "net_position")
        )
        all_ok = klines_ok and any_derivs_ok
        print()
        if all_ok:
            print("VERDICT: PASS ✓")
        else:
            print("VERDICT: FAIL ✗")
            if not klines_ok:
                print("  reason: K-line 1d/4h not available")
            if not any_derivs_ok:
                print("  reason: all derivatives endpoints failed")
        return 0 if all_ok else 1
    except Exception as e:
        logging.exception("collect failed: %s", e)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
