"""
_base.py — CompositeFactorBase 抽象基类 + 共享工具。

设计原则:
  * 每个 factor 的 output 必须对齐 schemas.yaml 的 composite_factors_schemas
    块(以该文件为最终权威);同时附加 computation_method / health_status /
    notes 等运行时元信息,让下游审计友好。
  * 所有数值阈值从 config/thresholds.yaml 读取,**不在代码里硬编码**。
  * context 为空 / 数据缺失时走降级路径,返回 health_status=insufficient_data。

context 字典约定(由 Sprint 1.7+ 的调用方构造):
  * klines_1h / _4h / _1d / _1w: pd.DataFrame,index=timestamp,
    columns=open/high/low/close/volume_btc/volume_usdt
  * derivatives: dict[metric_name → pd.Series],time-indexed
  * onchain: dict[metric_name → pd.Series],time-indexed
  * macro:     dict[metric_name → pd.Series],time-indexed(可为空)
  * events_upcoming_48h: list[dict],每个 dict 含 name / time_utc / hours_to / event_type
  * state_history_dao: Optional(为 cycle_position 提供 last_stable 查询)
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar, Optional

import yaml


logger = logging.getLogger(__name__)


_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent
_THRESHOLDS_PATH: Path = _PROJECT_ROOT / "config" / "thresholds.yaml"


@lru_cache(maxsize=1)
def _load_thresholds_full() -> dict[str, Any]:
    """缓存:整份 thresholds.yaml。"""
    with open(_THRESHOLDS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_thresholds_block(key: str) -> dict[str, Any]:
    """
    读取 thresholds.yaml 顶层某一块。
    未定义时返回 {},调用方自行判断 default 行为。
    """
    full = _load_thresholds_full()
    block = full.get(key)
    if block is None:
        logger.warning("thresholds.yaml key %r not found", key)
        return {}
    return block


def confidence_tier_from_value(value: float) -> str:
    """
    schemas.yaml common_types.enums.confidence_tier + confidence_tier_bands。
    0.75+ → high;0.5-0.75 → medium;0.3-0.5 → low;<0.3 → very_low。
    """
    if value is None:
        return "very_low"
    if value >= 0.75:
        return "high"
    if value >= 0.50:
        return "medium"
    if value >= 0.30:
        return "low"
    return "very_low"


def reduce_metadata(
    computation_method: str = "rule_based",
    health_status: str = "healthy",
    notes: Optional[list[str]] = None,
) -> dict[str, Any]:
    """标准元信息字段集合。"""
    return {
        "computation_method": computation_method,
        "health_status": health_status,
        "notes": list(notes) if notes else [],
    }


class CompositeFactorBase:
    """
    组合因子抽象基类。

    子类约定:
      * 覆盖 `name`(str)+ `thresholds_key`(str)
      * 实现 `compute(self, context) -> dict`
      * 用 `self.scoring_config` 访问 thresholds 块
      * 数据缺失时返回 `self._insufficient(reason)`
    """

    name: ClassVar[str] = ""
    thresholds_key: ClassVar[str] = ""

    def __init__(self) -> None:
        if not self.thresholds_key:
            raise NotImplementedError(
                f"{type(self).__name__} must set class-level thresholds_key"
            )
        self.full_thresholds: dict[str, Any] = _load_thresholds_full()
        self.scoring_config: dict[str, Any] = self.full_thresholds.get(
            self.thresholds_key, {}
        )

    # ------------------------------------------------------------------
    # 子类必须实现
    # ------------------------------------------------------------------

    def compute(self, context: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 通用工具
    # ------------------------------------------------------------------

    def _insufficient(self, reason: str, **extra: Any) -> dict[str, Any]:
        """数据不足的降级 output,调用方可叠加 factor-specific 字段。"""
        base = {
            "factor": self.name,
            **reduce_metadata(
                health_status="insufficient_data",
                notes=[reason],
            ),
        }
        base.update(extra)
        return base

    def _threshold(self, path: list[str], default: Any = None) -> Any:
        """
        从 full_thresholds 按 path 读取,例如
        `self._threshold(['layer_1_regime','adx','strong_threshold'], 25)`.
        """
        node: Any = self.full_thresholds
        for key in path:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node
