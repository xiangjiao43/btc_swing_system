"""
src.composite — 6 个组合因子(建模 §3.8)。

每个 factor 类:
  - 继承 CompositeFactorBase
  - 从 config/thresholds.yaml 读阈值
  - compute(context) 返回符合 schemas.yaml composite_factors_schemas 的 dict
"""

from .band_position import BandPositionFactor
from .crowding import CrowdingFactor
from .cycle_position import CyclePositionFactor
from .event_risk import EventRiskFactor
from .macro_headwind import MacroHeadwindFactor
from .truth_trend import TruthTrendFactor
from ._base import CompositeFactorBase

__all__ = [
    "CompositeFactorBase",
    "TruthTrendFactor",
    "BandPositionFactor",
    "CyclePositionFactor",
    "CrowdingFactor",
    "MacroHeadwindFactor",
    "EventRiskFactor",
]
