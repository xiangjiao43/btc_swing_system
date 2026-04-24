"""
src.pipeline — StrategyStateBuilder + Pipeline 协调层。

Sprint 1.12 打底;Sprint 1.13 加 State Machine;
Sprint 1.14 加 AI Adjudicator + Lifecycle FSM。
"""

from .lifecycle_fsm import LifecycleFSM
from .state_builder import (
    StrategyStateBuilder,
    BuildResult,
    DEFAULT_RULES_VERSION,
)
from .state_machine import StateMachine

__all__ = [
    "StrategyStateBuilder",
    "BuildResult",
    "DEFAULT_RULES_VERSION",
    "StateMachine",
    "LifecycleFSM",
]
