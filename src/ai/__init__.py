"""src.ai — AI 调用入口。

Sprint 1.8.1:旧 AIAdjudicator(v1.2 规则后裁决器)已退役;v1.3 改用
6 AI 角色 + MasterAdjudicator(在 src/ai/agents/)+ AdjudicatorValidator
(src/ai/validator.py),由 AIOrchestrator(src/ai/orchestrator.py)编排。

仍保留:
- summary.py(call_ai_summary,被 state_builder + ai/macro_l5_adjudicator 用)
- macro_l5_adjudicator.py(L5 宏观 AI,被 1.8 测试覆盖)
"""

from .summary import (
    AISummaryError,
    build_evidence_summary_prompt,
    call_ai_summary,
)

__all__ = [
    "AISummaryError",
    "build_evidence_summary_prompt",
    "call_ai_summary",
]
