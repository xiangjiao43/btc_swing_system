"""
src.pipeline — Sprint 1.12:StrategyStateBuilder + Pipeline 协调层。

负责把 6 个组合因子 + 5 层 Evidence + AI Summary 按依赖顺序串起来,
聚合成一个 BtcStrategyState dict,并持久化到 strategy_state_history。

本模块不做 State Machine(推迟到 Sprint 1.13)。
"""

from .state_builder import (
    StrategyStateBuilder,
    BuildResult,
    DEFAULT_RULES_VERSION,
)

__all__ = [
    "StrategyStateBuilder",
    "BuildResult",
    "DEFAULT_RULES_VERSION",
]
