"""
src.data.collectors — 外部数据源采集器。

每个 collector 只做"抓 + 写 SQLite",不做计算。
"""

from .binance import BinanceCollector, BinanceCollectorError

__all__ = [
    "BinanceCollector",
    "BinanceCollectorError",
]
