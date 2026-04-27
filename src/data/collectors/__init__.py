"""
src.data.collectors — 外部数据源采集器。

每个 collector 只做"抓 + 写 SQLite",不做计算。

架构(Sprint 2.6-A.4 起):
  - CoinglassCollector:BTC K 线 + 所有衍生品
  - GlassnodeCollector:链上指标(MVRV / NUPL / SOPR 等)
  - FredCollector:macro 唯一主源(覆盖 dxy/vix/sp500/nasdaq/dgs10/dff/cpi/unemployment_rate)

Binance / Yahoo Finance 已从架构移除(都因 IP 限速 / 封禁不可用);
详见 docs/PROJECT_LOG.md 与 docs/cc_reports/sprint_2_6_a*.md。
"""

# 在任何 collector 读 os.getenv 之前自动加载 .env(Sprint 1.2 Envfix)
from src import _env_loader  # noqa: F401

from .coinglass import CoinglassCollector, CoinglassCollectorError
from .fred import FredCollector, FredCollectorError
from .glassnode import GlassnodeCollector, GlassnodeCollectorError

__all__ = [
    "CoinglassCollector",
    "CoinglassCollectorError",
    "GlassnodeCollector",
    "GlassnodeCollectorError",
    "FredCollector",
    "FredCollectorError",
]
