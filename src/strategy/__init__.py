"""
src.strategy — 策略层(建模 §5 状态机 + §4.7 Observation Classifier 等)。

Sprint 1.5a 新建:把原 src/pipeline/state_machine.py(CC 自造 6 档分类器)+
src/pipeline/lifecycle_fsm.py(action 驱动 FSM)推翻,替换为对齐建模 §5
的统一 14 档 StateMachine。
"""

from .observation_classifier import ObservationResult, classify
from .state_machine import StateMachine, StateMachineResult, VALID_STATES

__all__ = [
    "StateMachine", "StateMachineResult", "VALID_STATES",
    "ObservationResult", "classify",
]
