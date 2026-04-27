"""tests/test_data_collection_job.py — Sprint 2.6-A:scheduler 数据采集任务覆盖。

Sprint 2.6-A.4:Yahoo collector 已删除,只剩 FRED / CoinGlass / Glassnode 3 家。

验证:
  - 至少一个 collector 成功 → status='ok'
  - 全部失败 → status='all_failed'(不抛异常)
  - conn_factory 本身抛错 → status='fatal_error'(不 crash)
  - 每个 collector 失败被独立捕获,不影响其他
  - FRED key 未配 → 优雅 skip,不算失败
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.scheduler.jobs import job_data_collection


def _patch_collectors(
    fred_enabled=False, fred_stats=None,
    cg_klines=None, cg_funding=None, cg_lsr=None,
    gn_rows=None,
    fred_raise=None, cg_raise=None, gn_raise=None,
):
    """统一 patch 3 个 collector(Yahoo 已弃用)。"""
    fred_mock = MagicMock()
    if fred_raise:
        fred_mock.side_effect = fred_raise
    else:
        fred_inst = MagicMock()
        fred_inst.enabled = fred_enabled
        fred_inst.collect_and_save_all.return_value = fred_stats or {}
        fred_mock.return_value = fred_inst

    cg_mock = MagicMock()
    if cg_raise:
        cg_mock.side_effect = cg_raise
    else:
        cg_inst = MagicMock()
        cg_inst.fetch_klines.return_value = cg_klines or []
        cg_inst.fetch_funding_rate_history.return_value = cg_funding or []
        cg_inst.fetch_long_short_ratio_history.return_value = cg_lsr or []
        cg_mock.return_value = cg_inst

    gn_mock = MagicMock()
    if gn_raise:
        gn_mock.side_effect = gn_raise
    else:
        gn_inst = MagicMock()
        for fn in ("fetch_mvrv_z_score", "fetch_nupl", "fetch_lth_supply",
                   "fetch_exchange_net_flow", "fetch_mvrv",
                   "fetch_realized_price", "fetch_sopr",
                   "fetch_reserve_risk", "fetch_puell_multiple"):
            getattr(gn_inst, fn).return_value = gn_rows or []
        gn_mock.return_value = gn_inst

    return (
        patch("src.data.collectors.fred.FredCollector", new=fred_mock),
        patch("src.data.collectors.coinglass.CoinglassCollector", new=cg_mock),
        patch("src.data.collectors.glassnode.GlassnodeCollector", new=gn_mock),
    )


# ============================================================
# Tests
# ============================================================

def test_data_collection_status_ok_when_at_least_one_collector_succeeds():
    """FRED 成功 + 其他失败 → status='ok'(任一成功就算成功)。"""
    mock_conn = MagicMock()
    patches = _patch_collectors(
        fred_enabled=True,
        fred_stats={"dxy": 5, "vix": 5, "sp500": 5},
        cg_raise=Exception("cg init fail"),
        gn_raise=Exception("gn init fail"),
    )
    with patches[0], patches[1], patches[2]:
        result = job_data_collection(conn_factory=lambda: mock_conn)

    assert result["status"] == "ok"
    assert result["by_collector"]["fred"] == 15
    assert result["by_collector"]["coinglass"] == 0
    assert result["by_collector"]["glassnode"] == 0
    assert result["total_upserted"] == 15
    assert "duration_ms" in result
    assert "errors" in result
    assert "coinglass" in result["errors"]
    assert "glassnode" in result["errors"]


def test_data_collection_all_failed_when_no_collector_succeeds():
    """所有 collector 都失败/无数据 → status='all_failed'。"""
    mock_conn = MagicMock()
    patches = _patch_collectors(
        fred_raise=Exception("fred fail"),
        cg_raise=Exception("cg fail"),
        gn_raise=Exception("gn fail"),
    )
    with patches[0], patches[1], patches[2]:
        result = job_data_collection(conn_factory=lambda: mock_conn)

    assert result["status"] == "all_failed"
    assert result["total_upserted"] == 0
    assert all(v == 0 for v in result["by_collector"].values())
    assert len(result["errors"]) == 3


def test_data_collection_fatal_error_when_conn_factory_fails():
    """conn_factory 本身抛错 → status='fatal_error',不 crash。"""
    def bad_factory():
        raise RuntimeError("DB unavailable")

    result = job_data_collection(conn_factory=bad_factory)
    assert result["status"] == "fatal_error"
    assert "error_type" in result
    assert result["error_type"] == "RuntimeError"
    assert "DB unavailable" in result["error_message"]


def test_data_collection_fred_skipped_when_disabled():
    """FRED key 未配 → fred 优雅 skip,不计入 errors。"""
    mock_conn = MagicMock()
    patches = _patch_collectors(
        fred_enabled=False,
        cg_klines=[{"timestamp": "2026-04-25T00:00:00Z",
                    "open": 1, "high": 1, "low": 1, "close": 1,
                    "volume": 0}],
        gn_raise=Exception("gn fail"),
    )
    with patches[0], patches[1], patches[2], \
         patch("src.data.storage.dao.BTCKlinesDAO") as dao_mock:
        dao_mock.upsert_klines.return_value = 1
        result = job_data_collection(conn_factory=lambda: mock_conn)

    assert result["by_collector"]["fred"] == 0
    assert "fred" not in result["errors"]  # skip 不算 error
    assert result["status"] == "ok"  # CoinGlass 成功就算 ok


def test_data_collection_partial_collector_failure_does_not_block_others():
    """coinglass 内部某个 fn_name 失败,不影响整体 collector 计数。"""
    mock_conn = MagicMock()

    cg_inst = MagicMock()
    def klines_side_effect(interval, limit):
        if interval == "1h":
            raise Exception("1h fail")
        return [{"timestamp": "2026-04-25T00:00:00Z",
                 "open": 1, "high": 1, "low": 1, "close": 1,
                 "volume": 0}] * 3
    cg_inst.fetch_klines.side_effect = klines_side_effect
    cg_inst.fetch_funding_rate_history.return_value = []
    cg_inst.fetch_long_short_ratio_history.return_value = []
    cg_mock = MagicMock(return_value=cg_inst)

    with patch("src.data.collectors.fred.FredCollector") as fred_mock, \
         patch("src.data.collectors.coinglass.CoinglassCollector", new=cg_mock), \
         patch("src.data.collectors.glassnode.GlassnodeCollector") as gn_mock, \
         patch("src.data.storage.dao.BTCKlinesDAO") as dao_mock:
        fred_mock.return_value.enabled = False
        gn_mock.return_value = MagicMock()
        for fn in ("fetch_mvrv_z_score", "fetch_nupl", "fetch_lth_supply",
                   "fetch_exchange_net_flow", "fetch_mvrv",
                   "fetch_realized_price", "fetch_sopr",
                   "fetch_reserve_risk", "fetch_puell_multiple"):
            getattr(gn_mock.return_value, fn).return_value = []
        dao_mock.upsert_klines.return_value = 3

        result = job_data_collection(conn_factory=lambda: mock_conn)

    # coinglass 计数应该 = 4h(3) + 1d(3) = 6,不被 1h 失败拖累
    assert result["by_collector"]["coinglass"] == 6
    assert result["status"] == "ok"
