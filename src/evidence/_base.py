"""
_base.py — EvidenceLayerBase 抽象基类 + 通用 EvidenceReport 字段构造。

设计原则:
  * 每个 layer 子类只实现 `_compute_specific(context)`,返回层专属字段 dict
  * 基类的 `compute(context, rules_version)` 作为模板方法,包装通用字段:
      layer_id / layer_name / reference_timestamp_utc / rules_version /
      run_trigger / data_freshness / health_status / confidence_tier /
      computation_method / generated_at_utc / notes
  * 所有数值阈值从 `config/thresholds.yaml` 读取
  * 严格对齐 `schemas.yaml` 的 evidence_report_base(§4.1)

Context 约定(由调用方构造):
  * klines_1h / _4h / _1d / _1w    pd.DataFrame(index=DatetimeIndex,UTC)
  * onchain / derivatives / macro  dict[metric_name → pd.Series]
  * events_upcoming_48h            list[dict]
  * reference_timestamp_utc        ISO 8601 字符串(数据采集完成时刻,§3.2.2 M29)
  * run_trigger                    scheduled / event_* / manual(§3.3.3 M38)
  * cold_start                     dict{warming_up: bool, days_elapsed: int}(可选)
  * state_history_dao              optional
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar, Optional

import pandas as pd
import yaml


logger = logging.getLogger(__name__)


_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent
_THRESHOLDS_PATH: Path = _PROJECT_ROOT / "config" / "thresholds.yaml"


@lru_cache(maxsize=1)
def _load_thresholds_full() -> dict[str, Any]:
    with open(_THRESHOLDS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def confidence_tier_from_value(value: float) -> str:
    """§4.1:0.75+ high / 0.5-0.75 medium / 0.3-0.5 low / <0.3 very_low。"""
    if value is None:
        return "very_low"
    if value >= 0.75:
        return "high"
    if value >= 0.50:
        return "medium"
    if value >= 0.30:
        return "low"
    return "very_low"


def downgrade_tier(tier: str, steps: int = 1) -> str:
    """把 tier 向下降 N 档。high → medium → low → very_low。"""
    order = ["high", "medium", "low", "very_low"]
    try:
        idx = order.index(tier)
    except ValueError:
        return "very_low"
    return order[min(idx + steps, len(order) - 1)]


def compute_data_freshness(
    context: dict[str, Any],
    reference_utc: Optional[str] = None,
) -> dict[str, Any]:
    """
    构造 data_freshness 字典:每个数据源的"最新一条记录距 reference 的秒数"。
    缺失源返回 None。reference_utc 不传时用当前时间。
    """
    ref = _parse_iso(reference_utc) if reference_utc else datetime.now(timezone.utc)

    def _latest_age_sec(obj: Any) -> Optional[int]:
        if obj is None:
            return None
        if isinstance(obj, pd.DataFrame):
            if obj.empty:
                return None
            last_idx = obj.index[-1]
        elif isinstance(obj, pd.Series):
            clean = obj.dropna()
            if clean.empty:
                return None
            last_idx = clean.index[-1]
        else:
            return None
        try:
            last_dt = pd.Timestamp(last_idx)
            if last_dt.tzinfo is None:
                last_dt = last_dt.tz_localize("UTC")
            return int((ref - last_dt.to_pydatetime()).total_seconds())
        except Exception:
            return None

    freshness: dict[str, Any] = {}
    for tf in ("klines_1h", "klines_4h", "klines_1d", "klines_1w"):
        if tf in context:
            freshness[tf] = _latest_age_sec(context[tf])
    for group_name in ("onchain", "derivatives", "macro"):
        group = context.get(group_name) or {}
        if isinstance(group, dict):
            for metric, series in group.items():
                freshness[f"{group_name}.{metric}"] = _latest_age_sec(series)
    return freshness


def _parse_iso(s: str) -> datetime:
    s2 = s.replace("Z", "+00:00") if s.endswith("Z") else s
    dt = datetime.fromisoformat(s2)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class EvidenceLayerBase:
    """
    Evidence 层抽象基类。子类通过覆盖 `layer_id / layer_name / thresholds_key`
    声明身份,通过覆盖 `_compute_specific(context)` 实现层专属逻辑。

    `compute(context, rules_version)` 是**模板方法**:先构造通用字段,再合并
    层专属字段,返回**完整 EvidenceReport dict**。

    冷启动(§8.10):context['cold_start']['warming_up'] = True 时,
    confidence_tier 自动降 1 档,health_status 标 'cold_start_warming_up'。
    """

    layer_id: ClassVar[int] = 0
    layer_name: ClassVar[str] = ""
    thresholds_key: ClassVar[str] = ""

    def __init__(self) -> None:
        if self.layer_id == 0 or not self.layer_name:
            raise NotImplementedError(
                f"{type(self).__name__} must set layer_id and layer_name"
            )
        self.full_thresholds: dict[str, Any] = _load_thresholds_full()
        self.scoring_config: dict[str, Any] = (
            self.full_thresholds.get(self.thresholds_key, {}) if self.thresholds_key
            else {}
        )

    # ------------------------------------------------------------------
    # 模板方法(子类不要覆盖;改子类 _compute_specific 即可)
    # ------------------------------------------------------------------

    def compute(
        self,
        context: dict[str, Any],
        rules_version: str = "v1.2.0",
    ) -> dict[str, Any]:
        try:
            specific = self._compute_specific(context)
        except Exception as e:
            logger.exception("%s compute failed: %s", self.layer_name, e)
            specific = {
                "health_status": "error",
                "confidence_tier": "very_low",
                "computation_method": "error",
                "notes": [f"compute exception: {type(e).__name__}: {e}"],
                "error": str(e),
            }

        common = self._build_common_fields(context, rules_version)
        merged = {**common, **specific}

        # 冷启动降级
        cold_start = context.get("cold_start") or {}
        if cold_start.get("warming_up"):
            merged["health_status"] = "cold_start_warming_up"
            merged["confidence_tier"] = downgrade_tier(
                merged.get("confidence_tier", "medium"), steps=1
            )
            merged.setdefault("notes", []).append(
                f"cold_start warming_up(days_elapsed={cold_start.get('days_elapsed')})"
            )

        return merged

    # ------------------------------------------------------------------
    # 子类必须实现
    # ------------------------------------------------------------------

    def _compute_specific(self, context: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 通用字段构造
    # ------------------------------------------------------------------

    def _build_common_fields(
        self,
        context: dict[str, Any],
        rules_version: str,
    ) -> dict[str, Any]:
        ref_utc = context.get("reference_timestamp_utc") or _utc_now_iso()
        return {
            "layer_id": self.layer_id,
            "layer_name": self.layer_name,
            "reference_timestamp_utc": ref_utc,
            "generated_at_utc": _utc_now_iso(),
            "rules_version": rules_version,
            "run_trigger": context.get("run_trigger", "scheduled"),
            "data_freshness": compute_data_freshness(context, ref_utc),
            # 默认值,子类可覆盖
            "health_status": "healthy",
            "confidence_tier": "medium",
            "computation_method": "rule_based",
            "notes": [],
        }

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------

    def _insufficient(
        self, reason: str, confidence_tier: str = "very_low", **extra: Any
    ) -> dict[str, Any]:
        """数据不足的降级 output。调用方 merge 到 compute 返回值中。"""
        out: dict[str, Any] = {
            "health_status": "insufficient_data",
            "confidence_tier": confidence_tier,
            "computation_method": "degraded",
            "notes": [reason],
        }
        out.update(extra)
        return out

    def _threshold(self, path: list[str], default: Any = None) -> Any:
        node: Any = self.full_thresholds
        for key in path:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node
