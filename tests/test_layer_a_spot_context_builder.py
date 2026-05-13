from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from src.ai.spot_cycle_context_builder import SpotCycleContextBuilder
from src.data.storage.connection import init_db
from src.data.storage.dao import MacroDAO, MacroMetric, OnchainDAO, OnchainMetric


def test_spot_cycle_context_builder_empty_db_does_not_crash():
    db_path = Path(tempfile.mkdtemp()) / "layer_a_empty.db"
    init_db(db_path=db_path, verbose=False)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        ctx = SpotCycleContextBuilder(conn).build_spot_cycle_context()
    finally:
        conn.close()

    assert ctx["schema_version"] == "layer_a_spot_cycle_context_v1"
    assert ctx["layer_a_boundaries"]["no_short"] is True
    assert ctx["layer_a_boundaries"]["no_thesis"] is True
    assert "onchain_holder_behavior" in ctx["available_factors"]
    assert "macro_liquidity" in ctx["available_factors"]
    assert ctx["available_factors"]["onchain_holder_behavior"]["percent_supply_in_profit"]["status"] == "missing"
    assert ctx["available_factors"]["macro_liquidity"]["us2y"]["status"] == "missing"
    assert isinstance(ctx["unavailable_factors"], list)
    unavailable_names = {x["factor"] for x in ctx["unavailable_factors"]}
    for name in (
        "percent_supply_in_profit", "exchange_balance", "us2y", "fed_funds_rate",
        "m2", "fed_balance_sheet", "percent_supply_in_loss",
        "exchange_net_position_change",
    ):
        assert name not in unavailable_names
    for name in (
        "lth_sopr", "sth_sopr",
    ):
        assert name in unavailable_names
    assert ctx["factor_coverage"]["critical_unavailable_count"] >= 5
    assert ctx["factor_coverage"]["confidence_cap"] == "low"
    assert ctx["data_quality_notes"]


def test_spot_cycle_context_builder_exposes_layer_a_factor_fetch_timestamps():
    db_path = Path(tempfile.mkdtemp()) / "layer_a_timestamps.db"
    init_db(db_path=db_path, verbose=False)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        OnchainDAO.upsert_batch(conn, [
            OnchainMetric(
                timestamp="2026-05-12T00:00:00Z",
                metric_name="percent_supply_in_profit",
                metric_value=0.915,
                source="glassnode_primary",
                fetched_at="2026-05-12T14:06:23Z",
            ),
            OnchainMetric(
                timestamp="2026-05-11T00:00:00Z",
                metric_name="exchange_balance",
                metric_value=3002200.0,
                source="glassnode_primary",
                fetched_at="2026-05-12T14:05:23Z",
            ),
            OnchainMetric(
                timestamp="2026-05-12T00:00:00Z",
                metric_name="exchange_balance",
                metric_value=3002175.0,
                source="glassnode_primary",
                fetched_at="2026-05-12T14:06:24Z",
            ),
        ])
        MacroDAO.upsert_batch(conn, [
            MacroMetric(
                timestamp="2026-05-12T00:00:00Z",
                metric_name="us2y",
                metric_value=3.91,
                source="fred",
                fetched_at="2026-05-12T14:07:30Z",
            ),
        ])
        conn.commit()

        ctx = SpotCycleContextBuilder(conn).build_spot_cycle_context()
    finally:
        conn.close()

    profit = ctx["available_factors"]["onchain_holder_behavior"]["percent_supply_in_profit"]
    loss = ctx["available_factors"]["onchain_holder_behavior"]["percent_supply_in_loss"]
    exchange_net_position_change = (
        ctx["available_factors"]["onchain_holder_behavior"]["exchange_net_position_change"]
    )
    us2y = ctx["available_factors"]["macro_liquidity"]["us2y"]
    assert profit["status"] == "available"
    assert profit["fetched_at_utc"] == "2026-05-12T14:06:23Z"
    assert profit["fetched_at_bjt"] == "2026-05-12 22:06:23 (BJT)"
    assert profit["captured_at_utc"] == "2026-05-12T00:00:00Z"
    assert loss["status"] == "available"
    assert loss["actual_value"] == 0.085
    assert loss["source"] == "glassnode_onchain_derived"
    assert loss["fetched_at_bjt"] == "2026-05-12 22:06:23 (BJT)"
    assert exchange_net_position_change["status"] == "available"
    assert exchange_net_position_change["actual_value"] == -25.0
    assert exchange_net_position_change["source"] == "glassnode_onchain_derived"
    assert exchange_net_position_change["fetched_at_bjt"] == "2026-05-12 22:06:24 (BJT)"
    assert us2y["status"] == "available"
    assert us2y["fetched_at_utc"] == "2026-05-12T14:07:30Z"
    assert us2y["fetched_at_bjt"] == "2026-05-12 22:07:30 (BJT)"
