"""src.ai — AI 调用入口(OpenAI-compatible via novaiapi.com)。"""

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
