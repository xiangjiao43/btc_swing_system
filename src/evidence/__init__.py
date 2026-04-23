"""
src.evidence — 五层证据层。

每个 Layer 类继承 EvidenceLayerBase,compute(context, rules_version) 返回
对齐 schemas.yaml 的 EvidenceReport dict。
"""

from ._base import EvidenceLayerBase, confidence_tier_from_value, downgrade_tier
from .layer1_regime import Layer1Regime
from .layer2_direction import Layer2Direction
from .layer3_opportunity import Layer3Opportunity

__all__ = [
    "EvidenceLayerBase",
    "confidence_tier_from_value",
    "downgrade_tier",
    "Layer1Regime",
    "Layer2Direction",
    "Layer3Opportunity",
]
