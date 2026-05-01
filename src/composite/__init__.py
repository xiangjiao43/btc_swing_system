"""
src.composite — Sprint 1.8.1:仅保留 CyclePosition。

v1.2 旧组合因子(TruthTrend / BandPosition / Crowding / MacroHeadwind)
已退役;v1.3 改用 6 AI 角色综合判断。CyclePosition 是规则版长周期定位
辅助因子,L2 prompt 仍消费它(rule_cycle_position 字段),保留。
"""

from .cycle_position import CyclePositionFactor
from ._base import CompositeFactorBase

__all__ = [
    "CompositeFactorBase",
    "CyclePositionFactor",
]
