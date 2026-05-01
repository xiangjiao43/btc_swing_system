"""
src.evidence — Sprint 1.8.1:Layer1-5 旧规则版已退役。

v1.2 五层证据层(Layer1Regime ~ Layer5Macro)被 Sprint 1.8 v5 的
6 AI 角色 + AdjudicatorValidator(在 src/ai/agents/ + src/ai/validator.py)
取代。本模块仍保留 EvidenceLayerBase + 辅助函数 + _anti_patterns +
pillars + plain_reading(其他模块仍消费)。
"""

from ._base import EvidenceLayerBase, confidence_tier_from_value, downgrade_tier

__all__ = [
    "EvidenceLayerBase",
    "confidence_tier_from_value",
    "downgrade_tier",
]
