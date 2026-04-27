"""tests/test_glassnode_lth_sth_aggregator.py — Sprint 2.6-I unit tests for
the supply-weighted LTH/STH realized price aggregator.

Pure function tests on _aggregate_lth_sth_realized_price + bucket constants.
No HTTP, no DB.
"""

from __future__ import annotations

import pytest

from src.data.collectors.glassnode import GlassnodeCollector


_STH_BUCKETS = GlassnodeCollector._STH_BUCKETS
_LTH_BUCKETS = GlassnodeCollector._LTH_BUCKETS


# ============================================================
# Bucket grouping
# ============================================================

def test_bucket_grouping_no_overlap():
    """STH 与 LTH 桶不能交集。"""
    assert set(_STH_BUCKETS).isdisjoint(set(_LTH_BUCKETS))


def test_bucket_grouping_3m_6m_in_sth():
    """spec 简化:3m_6m 桶归 STH(桶中点 135 天 < 155 天)。"""
    assert "3m_6m" in _STH_BUCKETS
    assert "3m_6m" not in _LTH_BUCKETS


def test_bucket_grouping_6m_12m_in_lth():
    """spec:6m_12m 桶起进 LTH(下界 180 天 > 155 天)。"""
    assert "6m_12m" in _LTH_BUCKETS
    assert "6m_12m" not in _STH_BUCKETS


def test_bucket_grouping_more_10y_in_lth():
    """more_10y 桶不在 spec 显式列出但显然属 LTH。"""
    assert "more_10y" in _LTH_BUCKETS


def test_bucket_grouping_aggregated_excluded():
    """'aggregated' 桶是市场聚合,不属于任何一档分类。"""
    assert "aggregated" not in _STH_BUCKETS
    assert "aggregated" not in _LTH_BUCKETS


# ============================================================
# Aggregator math
# ============================================================

def _make_breakdown_row(ts: str, buckets: dict) -> dict:
    return {"timestamp": ts, "buckets": buckets}


def test_aggregate_simple_two_buckets_each_side():
    """LTH = (50000×100 + 80000×200) / (100+200) = 70000
       STH = (75000×50 + 90000×150) / (50+150) = 86250
    """
    ts = "2026-04-27T00:00:00Z"
    price = [_make_breakdown_row(ts, {
        "1m_3m": 75000, "3m_6m": 90000,         # STH 桶里抽 2 个有数据
        "1y_2y": 50000, "2y_3y": 80000,         # LTH 桶里抽 2 个
        "aggregated": 999999,                    # 应被忽略
    })]
    supply = [_make_breakdown_row(ts, {
        "1m_3m": 50, "3m_6m": 150,
        "1y_2y": 100, "2y_3y": 200,
        "aggregated": 999999,
    })]
    lth, sth = GlassnodeCollector._aggregate_lth_sth_realized_price(price, supply)

    assert len(lth) == 1
    assert len(sth) == 1
    assert lth[0]["metric_name"] == "lth_realized_price"
    assert sth[0]["metric_name"] == "sth_realized_price"
    assert lth[0]["timestamp"] == ts
    assert sth[0]["timestamp"] == ts
    expected_lth = (50000 * 100 + 80000 * 200) / (100 + 200)
    expected_sth = (75000 * 50 + 90000 * 150) / (50 + 150)
    assert lth[0]["metric_value"] == pytest.approx(expected_lth)
    assert sth[0]["metric_value"] == pytest.approx(expected_sth)


def test_aggregate_skips_buckets_with_missing_data():
    """某 bucket price 或 supply 缺 → 跳过该 bucket,其他正常计算。"""
    ts = "2026-04-27T00:00:00Z"
    price = [_make_breakdown_row(ts, {
        "1y_2y": 50000, "2y_3y": 80000, "3y_5y": 120000,
    })]
    supply = [_make_breakdown_row(ts, {
        "1y_2y": 100,             # 2y_3y 缺,3y_5y 也缺
    })]
    lth, _ = GlassnodeCollector._aggregate_lth_sth_realized_price(price, supply)
    # 只有 1y_2y 有完整数据 → LTH = 50000
    assert len(lth) == 1
    assert lth[0]["metric_value"] == pytest.approx(50000)


def test_aggregate_zero_supply_bucket_ignored():
    """supply=0 的桶不加入加权(避免除零 / 噪声)。"""
    ts = "2026-04-27T00:00:00Z"
    price = [_make_breakdown_row(ts, {"1y_2y": 50000, "2y_3y": 999999})]
    supply = [_make_breakdown_row(ts, {"1y_2y": 100, "2y_3y": 0})]
    lth, _ = GlassnodeCollector._aggregate_lth_sth_realized_price(price, supply)
    assert lth[0]["metric_value"] == pytest.approx(50000)


def test_aggregate_skips_timestamp_with_no_lth_data():
    """全 LTH 桶都缺 → 该时间点不出 LTH 行(STH 仍可能出)。"""
    ts = "2026-04-27T00:00:00Z"
    price = [_make_breakdown_row(ts, {"1m_3m": 75000})]   # 只有 STH bucket
    supply = [_make_breakdown_row(ts, {"1m_3m": 50})]
    lth, sth = GlassnodeCollector._aggregate_lth_sth_realized_price(price, supply)
    assert lth == []
    assert len(sth) == 1


def test_aggregate_only_common_timestamps():
    """price 与 supply 时间戳不重合 → 只 join 共同时间点。"""
    price = [
        _make_breakdown_row("2026-04-26T00:00:00Z", {"1y_2y": 50000}),
        _make_breakdown_row("2026-04-27T00:00:00Z", {"1y_2y": 51000}),
    ]
    supply = [
        _make_breakdown_row("2026-04-27T00:00:00Z", {"1y_2y": 100}),
        _make_breakdown_row("2026-04-28T00:00:00Z", {"1y_2y": 100}),
    ]
    lth, _ = GlassnodeCollector._aggregate_lth_sth_realized_price(price, supply)
    assert len(lth) == 1
    assert lth[0]["timestamp"] == "2026-04-27T00:00:00Z"


def test_aggregate_emits_correct_source_label():
    """source 字段标记 derived,与原生 endpoint 区分(便于审计)。"""
    ts = "2026-04-27T00:00:00Z"
    price = [_make_breakdown_row(ts, {"1y_2y": 50000})]
    supply = [_make_breakdown_row(ts, {"1y_2y": 100})]
    lth, _ = GlassnodeCollector._aggregate_lth_sth_realized_price(price, supply)
    assert lth[0]["source"] == "glassnode_derived_breakdown_by_age"


def test_aggregate_empty_inputs():
    lth, sth = GlassnodeCollector._aggregate_lth_sth_realized_price([], [])
    assert lth == []
    assert sth == []


# ============================================================
# Public fetch wrapper share HTTP via instance cache
# ============================================================

def test_public_fetchers_share_http_via_instance_cache(monkeypatch):
    """fetch_lth + fetch_sth 调一次 _fetch_breakdown_by_age 各端点(共 2 次),
    缓存命中后再调不再发 HTTP。"""
    # Build a real instance bypassing __init__ (avoids needing API key)
    coll = GlassnodeCollector.__new__(GlassnodeCollector)
    calls: list = []

    def fake_fetch_breakdown(self, path, label, **kw):
        calls.append(path)
        ts = "2026-04-27T00:00:00Z"
        if "price_realized_usd_by_age" in path:
            return [{"timestamp": ts, "buckets": {"1y_2y": 50000, "1m_3m": 70000}}]
        if "supply_by_age" in path:
            return [{"timestamp": ts, "buckets": {"1y_2y": 100, "1m_3m": 50}}]
        return []

    monkeypatch.setattr(GlassnodeCollector, "_fetch_breakdown_by_age", fake_fetch_breakdown)

    lth1 = coll.fetch_lth_realized_price(since_days=7)
    sth1 = coll.fetch_sth_realized_price(since_days=7)
    # 第二轮调用,应该走缓存
    lth2 = coll.fetch_lth_realized_price(since_days=7)
    sth2 = coll.fetch_sth_realized_price(since_days=7)

    assert len(calls) == 2  # 价格 + 供应共 2 次
    assert lth1 == lth2
    assert sth1 == sth2
    assert lth1[0]["metric_value"] == pytest.approx(50000)
    assert sth1[0]["metric_value"] == pytest.approx(70000)
