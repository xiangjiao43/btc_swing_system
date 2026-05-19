"""
src.composite — Sprint Layer-B Cleanup:CyclePosition 已删除。

历史:
- v1.2 旧组合因子(TruthTrend / BandPosition / Crowding / MacroHeadwind)退役
- v1.3 改用 6 AI 角色综合判断
- Sprint Layer-B Cleanup:CyclePositionFactor(9 档大周期)删除,Layer A
  独立子系统的 6 阶段(bear_bottom / recovery / bull_main / bull_late /
  top_distribution / bear_decline)替代它的全部职责
"""

from ._base import CompositeFactorBase

__all__ = [
    "CompositeFactorBase",
]
