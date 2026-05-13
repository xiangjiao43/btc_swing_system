from __future__ import annotations

from unittest.mock import MagicMock

import yaml

from src.data.collectors.fred import SERIES_TO_METRIC
from src.data.collectors.glassnode import GlassnodeCollector


def test_glassnode_layer_a_key_factor_paths_are_registered():
    assert GlassnodeCollector._PATH_PERCENT_SUPPLY_IN_PROFIT.endswith(
        "/supply/profit_relative"
    )
    assert GlassnodeCollector._PATH_EXCHANGE_BALANCE.endswith(
        "/distribution/balance_exchanges"
    )
    assert GlassnodeCollector._PATH_LTH_SOPR.endswith("/indicators/sopr_more_155")
    assert GlassnodeCollector._PATH_STH_SOPR.endswith("/indicators/sopr_less_155")
    assert GlassnodeCollector._PATH_RHODL_RATIO.endswith("/indicators/rhodl_ratio")
    assert GlassnodeCollector._PATH_RESERVE_RISK.endswith("/indicators/reserve_risk")
    assert GlassnodeCollector._PATH_PUELL_MULTIPLE.endswith("/indicators/puell_multiple")
    assert GlassnodeCollector._PATH_LTH_NET_CHANGE.endswith("/supply/lth_net_change")


def test_glassnode_layer_a_key_factor_fetchers_call_expected_metrics():
    collector = GlassnodeCollector.__new__(GlassnodeCollector)
    collector._fetch_series = MagicMock(return_value=[])

    cases = [
        (
            "fetch_percent_supply_in_profit",
            GlassnodeCollector._PATH_PERCENT_SUPPLY_IN_PROFIT,
            "percent_supply_in_profit",
            "glassnode_primary",
        ),
        (
            "fetch_exchange_balance",
            GlassnodeCollector._PATH_EXCHANGE_BALANCE,
            "exchange_balance",
            "glassnode_primary",
        ),
        (
            "fetch_lth_sopr",
            GlassnodeCollector._PATH_LTH_SOPR,
            "lth_sopr",
            "glassnode_layer_a",
        ),
        (
            "fetch_sth_sopr",
            GlassnodeCollector._PATH_STH_SOPR,
            "sth_sopr",
            "glassnode_layer_a",
        ),
        (
            "fetch_rhodl_ratio",
            GlassnodeCollector._PATH_RHODL_RATIO,
            "rhodl_ratio",
            "glassnode_layer_a",
        ),
        (
            "fetch_reserve_risk",
            GlassnodeCollector._PATH_RESERVE_RISK,
            "reserve_risk",
            "glassnode_layer_a",
        ),
        (
            "fetch_puell_multiple",
            GlassnodeCollector._PATH_PUELL_MULTIPLE,
            "puell_multiple",
            "glassnode_layer_a",
        ),
        (
            "fetch_lth_net_position_change",
            GlassnodeCollector._PATH_LTH_NET_CHANGE,
            "lth_net_position_change",
            "glassnode_layer_a",
        ),
    ]

    for fn_name, path, metric_name, source in cases:
        collector._fetch_series.reset_mock()
        getattr(collector, fn_name)(since_days=7)
        collector._fetch_series.assert_called_once_with(
            path,
            metric_name,
            interval="24h",
            since_days=7,
            source=source,
        )


def test_fred_layer_a_macro_series_are_registered():
    assert SERIES_TO_METRIC["DGS2"] == "us2y"
    assert SERIES_TO_METRIC["DFII10"] == "real_yield"
    assert SERIES_TO_METRIC["FEDFUNDS"] == "fed_funds_rate"
    assert SERIES_TO_METRIC["CPIAUCSL"] == "cpi"
    assert SERIES_TO_METRIC["CPILFESL"] == "core_cpi"
    assert SERIES_TO_METRIC["M2SL"] == "m2"
    assert SERIES_TO_METRIC["WALCL"] == "fed_balance_sheet"


def test_data_catalog_registers_layer_a_key_factor_sources():
    with open("config/data_catalog.yaml", "r", encoding="utf-8") as f:
        catalog = yaml.safe_load(f)
    sources = {item["name"]: item for item in catalog["sources"]}

    expected = {
        "glassnode_percent_supply_in_profit",
        "glassnode_exchange_balance",
        "glassnode_lth_sopr",
        "glassnode_sth_sopr",
        "glassnode_rhodl_ratio",
        "glassnode_reserve_risk",
        "glassnode_puell_multiple",
        "glassnode_lth_net_position_change",
        "fred_dgs2",
        "fred_real_yield",
        "fred_fed_funds_rate",
        "fred_cpi",
        "fred_core_cpi",
        "fred_m2",
        "fred_fed_balance_sheet",
    }
    missing = expected - set(sources)
    assert not missing
    for name in expected:
        assert sources[name]["role_in_v1"] == "primary"
    for name in expected - {"fred_cpi", "fred_core_cpi"}:
        assert sources[name]["frequency"] == "daily"
    assert sources["fred_cpi"]["frequency"] == "monthly"
    assert sources["fred_core_cpi"]["frequency"] == "monthly"
    assert sources["glassnode_lth_sopr"]["endpoint"].endswith("/sopr_more_155")
    assert sources["glassnode_sth_sopr"]["endpoint"].endswith("/sopr_less_155")
