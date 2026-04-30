"""tests/test_glassnode_collect_all.py — Sprint 2.6-F Commit 1。

Regression guard:GlassnodeCollector.collect_and_save_all 必须把所有 13 个
expected metric(primary 5 + display 7 + btc_price_close)注册到 tasks 列表。
若有人不小心删掉 lth_realized_price / sth_realized_price / sopr_adjusted (aSOPR),
这个测试立刻失败。
"""

from __future__ import annotations

import inspect

from src.data.collectors.glassnode import GlassnodeCollector


_EXPECTED_METRICS: set[str] = {
    # Primary 5
    "mvrv_z_score",
    "nupl",
    "lth_supply",
    "exchange_net_flow",
    "btc_price_close",
    # Display(Sprint 1.7 后):删除 sopr / reserve_risk / puell_multiple
    "mvrv",
    "realized_price",
    "lth_realized_price",
    "sth_realized_price",
    "sopr_adjusted",  # = aSOPR (1.6 升级 primary)
}


def test_collect_and_save_all_registers_all_expected_metrics():
    """source-level guard:13 个 metric 标签都出现在 collect_and_save_all 函数体里。

    用 inspect.getsource 读源码,避免真调用 (那会发 HTTP request)。
    Sprint 2.6-I:lth/sth_realized_price 通过 /breakdowns/* 客户端聚合恢复。
    """
    src = inspect.getsource(GlassnodeCollector.collect_and_save_all)
    missing = sorted(m for m in _EXPECTED_METRICS if f'"{m}"' not in src)
    assert not missing, (
        f"GlassnodeCollector.collect_and_save_all is missing metrics: "
        f"{missing}. All {len(_EXPECTED_METRICS)} must be registered."
    )


def test_glassnode_has_lth_sth_realized_price_methods():
    """Sprint 2.6-I:fetch_lth/sth_realized_price 通过 breakdowns 聚合实现。"""
    assert hasattr(GlassnodeCollector, "fetch_lth_realized_price")
    assert hasattr(GlassnodeCollector, "fetch_sth_realized_price")
    assert hasattr(GlassnodeCollector, "_PATH_PRICE_REALIZED_BY_AGE")
    assert hasattr(GlassnodeCollector, "_PATH_SUPPLY_BY_AGE")
    # 老的独立 endpoint(F.3 删除)不应再回来
    assert not hasattr(GlassnodeCollector, "_PATH_LTH_REALIZED_PRICE")
    assert not hasattr(GlassnodeCollector, "_PATH_STH_REALIZED_PRICE")


def test_glassnode_has_asopr_method():
    """fetch_sopr_adjusted (= aSOPR) 必须存在。"""
    assert hasattr(GlassnodeCollector, "fetch_sopr_adjusted")
