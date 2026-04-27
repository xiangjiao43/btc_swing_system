"""tests/test_funding_aggregated_actually_fetched.py — Sprint 2.6-F.3。

Sprint 2.6-F Commit 2 加了 fetch_funding_rate_aggregated 方法 + 注册到
CoinglassCollector.collect_and_save_all,但生产端两条路径都绕过 collect_and_save_all
自带硬编码列表(同 Glassnode 的 lth/sth 漏注册一样模式):
  - src/scheduler/jobs.py::job_data_collection 的 coinglass 衍生品 loop
  - scripts/backfill_data.py::backfill_derivatives 的 fetches dict

服务器实测 derivatives_snapshots.full_data_json 0 行含 funding_rate_aggregated
就是因为这两处漏注册。本测试用 source-level + behavior-level 双重 guard。
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch


# ============================================================
# 1. jobs.py 的 coinglass 衍生品循环含 fetch_funding_rate_aggregated
# ============================================================

def test_jobs_coinglass_loop_includes_funding_rate_aggregated():
    from src.scheduler import jobs as jobs_mod
    src = inspect.getsource(jobs_mod.job_data_collection)
    assert '"fetch_funding_rate_aggregated"' in src, (
        "jobs.job_data_collection coinglass loop is missing "
        "fetch_funding_rate_aggregated. Without this entry, scheduler "
        "runs every hour but never pulls the OI-weighted aggregated funding rate."
    )


# ============================================================
# 2. backfill_data.py 的 backfill_derivatives fetches dict 含 lambda
# ============================================================

def test_backfill_derivatives_fetches_dict_includes_funding_rate_aggregated():
    import scripts.backfill_data as bf
    src = inspect.getsource(bf.backfill_derivatives)
    assert '"funding_rate_aggregated"' in src, (
        "backfill_derivatives.fetches missing key 'funding_rate_aggregated'. "
        "--only derivatives --days N will skip this metric forever."
    )
    assert "coll.fetch_funding_rate_aggregated" in src, (
        "backfill_derivatives doesn't actually invoke fetch_funding_rate_aggregated"
    )


# ============================================================
# 3. behavior:跑一次 job_data_collection,断言 fetch_funding_rate_aggregated .called
# ============================================================

def _make_coinglass_mock_with_all_methods() -> MagicMock:
    inst = MagicMock()
    inst.fetch_klines.return_value = []
    for fn in (
        "fetch_funding_rate_history",
        "fetch_funding_rate_aggregated",
        "fetch_open_interest_history",
        "fetch_long_short_ratio_history",
        "fetch_liquidation_history",
    ):
        getattr(inst, fn).return_value = []
    return inst


def test_job_data_collection_actually_invokes_funding_rate_aggregated():
    from src.scheduler.jobs import job_data_collection

    mock_conn = MagicMock()
    fred_mock = MagicMock()
    fred_mock.return_value.enabled = False

    cg_inst = _make_coinglass_mock_with_all_methods()
    cg_mock = MagicMock(return_value=cg_inst)

    gn_mock = MagicMock()
    gn_inst = MagicMock()
    for fn in ("fetch_mvrv_z_score", "fetch_nupl", "fetch_lth_supply",
               "fetch_exchange_net_flow", "fetch_mvrv", "fetch_realized_price",
               "fetch_sopr", "fetch_sopr_adjusted",
               "fetch_reserve_risk", "fetch_puell_multiple"):
        getattr(gn_inst, fn).return_value = []
    gn_mock.return_value = gn_inst

    with patch("src.data.collectors.fred.FredCollector", new=fred_mock), \
         patch("src.data.collectors.coinglass.CoinglassCollector", new=cg_mock), \
         patch("src.data.collectors.glassnode.GlassnodeCollector", new=gn_mock):
        job_data_collection(conn_factory=lambda: mock_conn)

    assert cg_inst.fetch_funding_rate_aggregated.called, (
        "job_data_collection failed to invoke "
        "cg.fetch_funding_rate_aggregated() — hardcoded loop missing entry."
    )
