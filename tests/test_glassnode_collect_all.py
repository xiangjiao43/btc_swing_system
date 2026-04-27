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
    # Display 7
    "mvrv",
    "realized_price",
    "lth_realized_price",
    "sth_realized_price",
    "sopr",
    "sopr_adjusted",  # = aSOPR (adjusted SOPR)
    "reserve_risk",
    "puell_multiple",
}


def test_collect_and_save_all_registers_all_13_metrics():
    """source-level guard:13 个 metric 标签都出现在 collect_and_save_all 函数体里。

    用 inspect.getsource 读源码,避免真调用 (那会发 HTTP request)。
    """
    src = inspect.getsource(GlassnodeCollector.collect_and_save_all)
    missing = sorted(m for m in _EXPECTED_METRICS if f'"{m}"' not in src)
    assert not missing, (
        f"GlassnodeCollector.collect_and_save_all is missing metrics: "
        f"{missing}. All 13 must be registered in the tasks list."
    )


def test_glassnode_has_lth_sth_realized_price_methods():
    """fetch_lth_realized_price + fetch_sth_realized_price 必须存在。"""
    assert hasattr(GlassnodeCollector, "fetch_lth_realized_price")
    assert hasattr(GlassnodeCollector, "fetch_sth_realized_price")


def test_glassnode_has_asopr_method():
    """fetch_sopr_adjusted (= aSOPR) 必须存在。"""
    assert hasattr(GlassnodeCollector, "fetch_sopr_adjusted")
