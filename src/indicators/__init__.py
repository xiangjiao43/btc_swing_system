"""
src.indicators — 本地技术指标计算模块。

纯 pandas + numpy 实现,不访问外部 API。
覆盖建模 §4.2.5(L1 判断)和 §3.8 各组合因子所需指标。
"""

from .momentum import rsi, stoch_rsi
from .structure import latest_swing_amplitude, swing_points
from .trend import adx, ema, macd, minus_di, plus_di
from .volatility import atr, atr_percentile, bollinger_bands
from .ichimoku import ichimoku_cloud

__all__ = [
    # trend
    "ema", "adx", "plus_di", "minus_di", "macd",
    # volatility
    "atr", "atr_percentile", "bollinger_bands",
    # ichimoku
    "ichimoku_cloud",
    # momentum
    "rsi", "stoch_rsi",
    # structure
    "swing_points", "latest_swing_amplitude",
]
