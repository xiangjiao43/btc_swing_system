"""tests/test_glassnode_3_new_metrics_actually_fetched.py — Sprint 2.6-F.1。

Sprint 2.6-F Commit 1 加的 regression guard 只覆盖了 GlassnodeCollector.collect_and_save_all
的 source 文本,但生产端两条路径都绕开了 collect_and_save_all,自带硬编码列表:

  - src/scheduler/jobs.py::job_data_collection 的 glassnode loop
  - scripts/backfill_data.py::backfill_onchain 的 fetches dict

两处都漏了 lth_realized_price / sth_realized_price / sopr_adjusted。
本测试用 mock 实例验证两条路径都会**真的**调到这 3 个 fetch 方法。
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch


_NEW_METRIC_FETCHERS: tuple[str, ...] = (
    "fetch_lth_realized_price",
    "fetch_sth_realized_price",
    "fetch_sopr_adjusted",  # = aSOPR (adjusted SOPR)
)


# ============================================================
# 1. jobs.py::job_data_collection 的 glassnode 循环含这 3 个 fn
# ============================================================

def test_jobs_data_collection_glassnode_loop_includes_3_new_fetchers():
    """source-level guard:job_data_collection 的硬编码 fn_name 列表必须含这 3 个。"""
    from src.scheduler import jobs as jobs_mod
    src = inspect.getsource(jobs_mod.job_data_collection)
    missing = [m for m in _NEW_METRIC_FETCHERS if f'"{m}"' not in src]
    assert not missing, (
        f"jobs.job_data_collection glassnode loop missing: {missing}. "
        f"Without these, scheduler runs every hour but never pulls these "
        f"3 onchain metrics."
    )


# ============================================================
# 2. backfill_data.py::backfill_onchain 的 fetches dict 含这 3 个
# ============================================================

def test_backfill_onchain_fetches_dict_includes_3_new_metrics():
    """source-level guard:backfill_data.backfill_onchain 的 dict 必须含 3 个 lambda。"""
    import scripts.backfill_data as bf
    src = inspect.getsource(bf.backfill_onchain)
    for label in ("lth_realized_price", "sth_realized_price", "sopr_adjusted"):
        assert f'"{label}"' in src, (
            f"backfill_onchain.fetches missing key {label!r}. "
            f"--only onchain --days N will skip this metric forever."
        )
    for fn in _NEW_METRIC_FETCHERS:
        assert f"coll.{fn}" in src, (
            f"backfill_onchain doesn't actually invoke coll.{fn}"
        )


# ============================================================
# 3. behavior-level:job_data_collection 真的会 .called 这 3 个 mock 方法
# ============================================================

def _make_glassnode_mock() -> MagicMock:
    inst = MagicMock()
    for fn in (
        "fetch_mvrv_z_score", "fetch_nupl", "fetch_lth_supply",
        "fetch_exchange_net_flow", "fetch_mvrv", "fetch_realized_price",
        "fetch_lth_realized_price", "fetch_sth_realized_price",
        "fetch_sopr", "fetch_sopr_adjusted",
        "fetch_reserve_risk", "fetch_puell_multiple",
    ):
        getattr(inst, fn).return_value = []  # 不回数据,只看是否被调
    return inst


def test_job_data_collection_actually_calls_3_new_fetchers():
    """端到端 mock:跑一次 job_data_collection,断言 3 个 fetch 方法 .called。"""
    from src.scheduler.jobs import job_data_collection

    mock_conn = MagicMock()
    fred_mock = MagicMock()
    fred_mock.return_value.enabled = False  # FRED skip

    cg_mock = MagicMock()
    cg_inst = MagicMock()
    cg_inst.fetch_klines.return_value = []
    for fn in ("fetch_funding_rate_history", "fetch_open_interest_history",
               "fetch_long_short_ratio_history", "fetch_liquidation_history"):
        getattr(cg_inst, fn).return_value = []
    cg_mock.return_value = cg_inst

    gn_inst = _make_glassnode_mock()
    gn_mock = MagicMock(return_value=gn_inst)

    with patch("src.data.collectors.fred.FredCollector", new=fred_mock), \
         patch("src.data.collectors.coinglass.CoinglassCollector", new=cg_mock), \
         patch("src.data.collectors.glassnode.GlassnodeCollector", new=gn_mock):
        job_data_collection(conn_factory=lambda: mock_conn)

    for fn in _NEW_METRIC_FETCHERS:
        assert getattr(gn_inst, fn).called, (
            f"job_data_collection failed to invoke gn.{fn}() — "
            f"hardcoded loop missing the entry."
        )
