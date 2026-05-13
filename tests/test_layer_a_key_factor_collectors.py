from __future__ import annotations

from unittest.mock import MagicMock

import yaml

from src.data.collectors.fred import SERIES_TO_METRIC
from src.data.collectors.glassnode import GlassnodeCollector


def test_glassnode_layer_a_key_factor_paths_are_registered():
    assert GlassnodeCollector._PATH_LTH_SOPR.endswith("/indicators/sopr_lth")
    assert GlassnodeCollector._PATH_STH_SOPR.endswith("/indicators/sopr_sth")
    assert GlassnodeCollector._PATH_PERCENT_SUPPLY_IN_PROFIT.endswith(
        "/supply/profit_relative"
    )
    assert GlassnodeCollector._PATH_PERCENT_SUPPLY_IN_LOSS.endswith(
        "/supply/loss_relative"
    )
    assert GlassnodeCollector._PATH_EXCHANGE_BALANCE.endswith(
        "/distribution/balance_exchanges"
    )
    assert GlassnodeCollector._PATH_EXCHANGE_NET_POSITION_CHANGE.endswith(
        "/distribution/exchange_net_position_change"
    )


def test_glassnode_layer_a_key_factor_fetchers_call_expected_metrics():
    collector = GlassnodeCollector.__new__(GlassnodeCollector)
    collector._fetch_series = MagicMock(return_value=[])

    cases = [
        ("fetch_lth_sopr", GlassnodeCollector._PATH_LTH_SOPR, "lth_sopr"),
        ("fetch_sth_sopr", GlassnodeCollector._PATH_STH_SOPR, "sth_sopr"),
        (
            "fetch_percent_supply_in_profit",
            GlassnodeCollector._PATH_PERCENT_SUPPLY_IN_PROFIT,
            "percent_supply_in_profit",
        ),
        (
            "fetch_percent_supply_in_loss",
            GlassnodeCollector._PATH_PERCENT_SUPPLY_IN_LOSS,
            "percent_supply_in_loss",
        ),
        (
            "fetch_exchange_balance",
            GlassnodeCollector._PATH_EXCHANGE_BALANCE,
            "exchange_balance",
        ),
        (
            "fetch_exchange_net_position_change",
            GlassnodeCollector._PATH_EXCHANGE_NET_POSITION_CHANGE,
            "exchange_net_position_change",
        ),
    ]

    for fn_name, path, metric_name in cases:
        collector._fetch_series.reset_mock()
        getattr(collector, fn_name)(since_days=7)
        collector._fetch_series.assert_called_once_with(
            path,
            metric_name,
            interval="24h",
            since_days=7,
            source="glassnode_primary",
        )


def test_fred_layer_a_macro_series_are_registered():
    assert SERIES_TO_METRIC["DGS2"] == "us2y"
    assert SERIES_TO_METRIC["FEDFUNDS"] == "fed_funds_rate"
    assert SERIES_TO_METRIC["M2SL"] == "m2"
    assert SERIES_TO_METRIC["WALCL"] == "fed_balance_sheet"


def test_data_catalog_registers_layer_a_key_factor_sources():
    with open("config/data_catalog.yaml", "r", encoding="utf-8") as f:
        catalog = yaml.safe_load(f)
    sources = {item["name"]: item for item in catalog["sources"]}

    expected = {
        "glassnode_lth_sopr",
        "glassnode_sth_sopr",
        "glassnode_percent_supply_in_profit",
        "glassnode_percent_supply_in_loss",
        "glassnode_exchange_balance",
        "glassnode_exchange_net_position_change",
        "fred_dgs2",
        "fred_fed_funds_rate",
        "fred_m2",
        "fred_fed_balance_sheet",
    }
    missing = expected - set(sources)
    assert not missing
    for name in expected:
        assert sources[name]["role_in_v1"] == "primary"
        assert sources[name]["frequency"] == "daily"
