"""
src.data.collectors — 外部数据源采集器。

每个 collector 只做"抓 + 写 SQLite",不做计算。

架构(Sprint 1.2 v2):
  - CoinglassCollector:BTC K 线(主数据源)+ 所有衍生品
  - (Glassnode / Yahoo / FRED collectors 后续 Sprint 陆续落地)

Binance 已从架构移除(美国 IP 全线不可用);详见 docs/PROJECT_LOG.md。
"""

from .coinglass import CoinglassCollector, CoinglassCollectorError

__all__ = [
    "CoinglassCollector",
    "CoinglassCollectorError",
]
