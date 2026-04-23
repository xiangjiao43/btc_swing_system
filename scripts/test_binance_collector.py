#!/usr/bin/env python3
"""
test_binance_collector.py — 人工验证脚本。

运行(从项目根):
    unset VIRTUAL_ENV   # 避免 Xcode Python 3.9 干扰
    uv run python scripts/test_binance_collector.py

动作:
    1. init_db()(幂等)
    2. 构造 BinanceCollector
    3. collect_and_save_all(conn)
    4. 打印统计 + 抽查 klines / funding_rate 最新值
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
    from src.data.storage import (
        BTCKlinesDAO,
        DerivativesDAO,
        get_connection,
        init_db,
    )

    init_db()
    conn = get_connection()
    try:
        collector = BinanceCollector()
        stats = collector.collect_and_save_all(conn)
        conn.commit()

        print()
        print("=" * 60)
        print("Collect stats:")
        for label, n in stats.items():
            print(f"  {label:<30} {n:>6} rows")
        print("=" * 60)

        # 抽查 1d K 线最新 5 根
        klines = BTCKlinesDAO.get_klines(conn, timeframe="1d", limit=5)
        # get_klines 返回升序前 N;我们要最后 5 根,直接取 latest 看一次即可
        latest = BTCKlinesDAO.get_latest_kline(conn, "1d")
        total_1d = BTCKlinesDAO.count(conn, "1d")
        print(f"\n1d K 线:共 {total_1d} 根;最新一根:")
        if latest:
            print(f"  {latest['timestamp']} "
                  f"O={latest['open']}  H={latest['high']}  "
                  f"L={latest['low']}  C={latest['close']}  "
                  f"vol={latest['volume_btc']:.2f} BTC")
        if klines:
            print("\n前 5 根(最旧):")
            for k in klines:
                print(f"  {k['timestamp']} "
                      f"O={k['open']}  H={k['high']}  "
                      f"L={k['low']}  C={k['close']}")

        # 抽查最新 funding_rate
        fr = DerivativesDAO.get_latest(conn, metric_name="funding_rate")
        if fr:
            print(f"\nLatest funding_rate: {fr['metric_value']} @ {fr['timestamp']}")
        else:
            print("\nLatest funding_rate: <not found>")

        # 抽查最新 basis
        basis = DerivativesDAO.get_latest(conn, metric_name="basis_premium_pct")
        if basis:
            print(f"Latest basis_premium_pct: {basis['metric_value']:.6f} @ {basis['timestamp']}")

        # 抽查最新 open_interest
        oi = DerivativesDAO.get_latest(conn, metric_name="open_interest_btc")
        if oi:
            print(f"Latest open_interest_btc: {oi['metric_value']:.2f} @ {oi['timestamp']}")

        return 0
    except Exception as e:
        logging.exception("collect failed: %s", e)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
