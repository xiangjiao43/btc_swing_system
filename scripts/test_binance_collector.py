#!/usr/bin/env python3
"""
test_binance_collector.py — Binance K 线采集人工验证脚本。

运行(从项目根):
    unset VIRTUAL_ENV   # 避免 Xcode Python 3.9 干扰
    uv run python scripts/test_binance_collector.py

动作:
    1. init_db()(幂等)
    2. 构造 BinanceCollector(走 data.binance.vision)
    3. collect_and_save_all(conn) → 抓 4 档 K 线 × 500 条
    4. 打印统计 + 最新 5 根 1d K 线

通过判据:
    - stats 四个 timeframe 都返回 > 0(注:1w 可能 < 500 因 BTC 交易历史有限)
    - 1d 的 klines 能读出最新 5 条
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
    from src.data.collectors import BinanceCollector
    from src.data.storage import BTCKlinesDAO, get_connection, init_db

    init_db()
    conn = get_connection()
    try:
        collector = BinanceCollector()
        stats = collector.collect_and_save_all(conn)
        conn.commit()

        print()
        print("=" * 60)
        print("Collect stats (K-lines only — derivatives now go via CoinGlass):")
        for timeframe, n in stats.items():
            print(f"  {timeframe:<6} {n:>6} rows")
        print("=" * 60)

        total_1d = BTCKlinesDAO.count(conn, "1d")
        print(f"\n1d K 线:共 {total_1d} 根")

        # 最新 1d K 线(真正最新 5 根)
        latest = BTCKlinesDAO.get_latest_kline(conn, "1d")
        if latest:
            print(f"\n最新 1d K 线:")
            print(f"  {latest['timestamp']} "
                  f"O={latest['open']}  H={latest['high']}  "
                  f"L={latest['low']}  C={latest['close']}  "
                  f"vol={latest['volume_btc']:.2f} BTC")

        # 最旧 5 根(升序 limit 5)
        first_five = BTCKlinesDAO.get_klines(conn, timeframe="1d", limit=5)
        if first_five:
            print("\n最旧 5 根(限 limit=5,升序):")
            for k in first_five:
                print(f"  {k['timestamp']} "
                      f"O={k['open']}  H={k['high']}  "
                      f"L={k['low']}  C={k['close']}")

        # 通过判据:四档都 > 0
        all_ok = all(n > 0 for n in stats.values())
        print()
        print("VERDICT:", "PASS ✓" if all_ok else "FAIL ✗(有 timeframe 抓取失败,看上方 ERROR 日志)")
        return 0 if all_ok else 1
    except Exception as e:
        logging.exception("collect failed: %s", e)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
