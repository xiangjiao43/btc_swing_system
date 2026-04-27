"""tests/test_fred_collector.py — Sprint 2.6-A.4:验证 FRED collector 字段覆盖。

确保 SERIES_TO_METRIC 涵盖 layer5_macro.py 需要的全部 macro 字段
(允许 gold_price 缺,因为 FRED 没有黄金价格 series)。
"""

from __future__ import annotations

from src.data.collectors.fred import SERIES_TO_METRIC, _METRIC_ALIASES
from src.evidence.layer5_macro import _ALL_MACRO_METRICS


def _all_writable_metrics() -> set[str]:
    """SERIES_TO_METRIC 直接映射 + _METRIC_ALIASES 别名。"""
    out = set(SERIES_TO_METRIC.values())
    for primary, aliases in _METRIC_ALIASES.items():
        out.update(aliases)
    return out


def test_fred_series_to_metric_covers_layer5_required_fields():
    """FRED collector 必须覆盖 layer5 期望的全部字段(gold_price 除外)。

    包含通过 _METRIC_ALIASES 别名间接写入的字段(如 us10y = DGS10 的别名)。
    """
    fred_metrics = _all_writable_metrics()
    required = set(_ALL_MACRO_METRICS) - {"gold_price"}
    missing = required - fred_metrics
    assert not missing, (
        f"FRED collector 缺少 layer5 需要的字段: {missing}\n"
        f"当前可写 metrics(含别名)={fred_metrics}\n"
        f"layer5 require={required}"
    )


def test_fred_series_to_metric_keys_are_uppercase_fred_ids():
    """SERIES_TO_METRIC 的 key 应是 FRED 大写 series_id。"""
    for series_id in SERIES_TO_METRIC:
        assert series_id == series_id.upper(), \
            f"FRED series_id 应全大写:{series_id!r}"
        assert len(series_id) >= 3, f"series_id 太短:{series_id!r}"


def test_fred_metrics_include_all_8_core_fields():
    """显式列出 8 个核心字段必须存在(直接映射,不算别名)。"""
    expected_metrics = {
        "dgs10", "dff", "cpi", "unemployment_rate",
        "sp500", "nasdaq", "vix", "dxy",
    }
    actual_metrics = set(SERIES_TO_METRIC.values())
    missing = expected_metrics - actual_metrics
    assert not missing, f"FRED 缺少核心字段: {missing}"


def test_us10y_alias_resolves_to_dgs10():
    """us10y 必须通过别名映射到 DGS10。"""
    assert "us10y" in _METRIC_ALIASES.get("dgs10", []), \
        f"us10y 应作为 dgs10 的别名,当前 _METRIC_ALIASES={_METRIC_ALIASES}"
