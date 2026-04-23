"""
src.evidence — 五层证据层。

每个 Layer 类继承 EvidenceLayerBase,compute(context, rules_version) 返回
对齐 schemas.yaml 的 EvidenceReport dict。
"""

from ._base import EvidenceLayerBase, confidence_tier_from_value, downgrade_tier
from .layer1_regime import Layer1Regime

__all__ = [
    "EvidenceLayerBase",
    "confidence_tier_from_value",
    "downgrade_tier",
    "Layer1Regime",
]
