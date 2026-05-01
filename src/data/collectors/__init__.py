"""
src.data.collectors — 外部数据源采集器。

每个 collector 只做"抓 + 写 SQLite",不做计算。

架构(Sprint 2.6-A.4 起):
  - CoinglassCollector:BTC K 线 + 所有衍生品
  - GlassnodeCollector:链上指标(MVRV / NUPL / SOPR 等)
  - FredCollector:macro 唯一主源(覆盖 dxy/vix/nasdaq/dgs10)

Binance / Yahoo Finance 已从架构移除(都因 IP 限速 / 封禁不可用);
详见 docs/PROJECT_LOG.md 与 docs/cc_reports/sprint_2_6_a*.md。
"""

# Sprint 2.8-C:env 加载移到生产入口(scripts/run_api.py / run_scheduler.py),
# 不在 collectors 包导入时副作用 load_dotenv。
# 原因:tests/test_layer5_macro.py 等单测只要 import 了 src.data.collectors.*,
# 就会触发 _env_loader → 把 OPENAI_API_KEY 灌进 os.environ → 后续 Layer5Macro
# 走 _try_call_l5_ai 的真实 HTTP 路径,在受限网络下挂死。
# 生产 OK:run_api.py 和 run_scheduler.py 顶层已显式 `from src import _env_loader`。
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
