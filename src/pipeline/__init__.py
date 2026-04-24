"""
src.pipeline — StrategyStateBuilder + Pipeline 协调层。

Sprint 1.5a:旧的 src/pipeline/state_machine.py 与 lifecycle_fsm.py 已推翻,
新的 14 档状态机在 src/strategy/state_machine.py,由 StrategyStateBuilder 调用。
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
