from __future__ import annotations

import sqlite3
import tempfile
import json
from pathlib import Path

from src.ai.spot_cycle_context_builder import (
    SpotCycleContextBuilder,
    build_a1_cycle_stage_context,
)
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
        "lth_sopr", "sth_sopr", "rhodl_ratio", "reserve_risk",
        "puell_multiple", "lth_net_position_change", "real_yield",
        "cpi", "core_cpi",
    ):
        assert name not in unavailable_names
    assert ctx["factor_coverage"]["critical_unavailable_count"] == 0
    assert ctx["factor_coverage"]["confidence_cap"] == "low"
    roles = ctx["factor_role_classification"]
    a1_core = {x["factor_name"] for x in roles["a1_core"]}
    a2_background = {x["factor_name"] for x in roles["a2_a4_background"]}
    layer_b_context = {x["factor_name"] for x in roles["layer_b_context"]}
    assert "mvrv_z_score" in a1_core
    assert "rhodl_ratio" in a1_core
    assert "cpi" in a2_background
    assert "m2" in a2_background
    assert "funding_rate" in layer_b_context
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
                timestamp="2026-05-12T00:00:00Z",
                metric_name="lth_sopr",
                metric_value=1.12,
                source="glassnode_layer_a",
                fetched_at="2026-05-12T14:06:20Z",
            ),
            OnchainMetric(
                timestamp="2026-05-12T00:00:00Z",
                metric_name="sth_sopr",
                metric_value=0.99,
                source="glassnode_layer_a",
                fetched_at="2026-05-12T14:06:21Z",
            ),
            OnchainMetric(
                timestamp="2026-05-12T00:00:00Z",
                metric_name="rhodl_ratio",
                metric_value=1055.6,
                source="glassnode_layer_a",
                fetched_at="2026-05-12T14:06:22Z",
            ),
            OnchainMetric(
                timestamp="2026-05-12T00:00:00Z",
                metric_name="reserve_risk",
                metric_value=0.0012,
                source="glassnode_layer_a",
                fetched_at="2026-05-12T14:06:22Z",
            ),
            OnchainMetric(
                timestamp="2026-05-12T00:00:00Z",
                metric_name="puell_multiple",
                metric_value=0.78,
                source="glassnode_layer_a",
                fetched_at="2026-05-12T14:06:22Z",
            ),
            OnchainMetric(
                timestamp="2026-05-12T00:00:00Z",
                metric_name="lth_net_position_change",
                metric_value=123394.3,
                source="glassnode_layer_a",
                fetched_at="2026-05-12T14:06:22Z",
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
            MacroMetric(
                timestamp="2026-05-12T00:00:00Z",
                metric_name="real_yield",
                metric_value=1.95,
                source="fred",
                fetched_at="2026-05-12T14:07:31Z",
            ),
            MacroMetric(
                timestamp="2026-04-01T00:00:00Z",
                metric_name="cpi",
                metric_value=332.407,
                source="fred",
                fetched_at="2026-05-12T14:07:32Z",
            ),
            MacroMetric(
                timestamp="2026-04-01T00:00:00Z",
                metric_name="core_cpi",
                metric_value=335.423,
                source="fred",
                fetched_at="2026-05-12T14:07:33Z",
            ),
        ])
        conn.commit()

        ctx = SpotCycleContextBuilder(conn).build_spot_cycle_context()
    finally:
        conn.close()

    profit = ctx["available_factors"]["onchain_holder_behavior"]["percent_supply_in_profit"]
    loss = ctx["available_factors"]["onchain_holder_behavior"]["percent_supply_in_loss"]
    lth_sopr = ctx["available_factors"]["onchain_holder_behavior"]["lth_sopr"]
    rhodl = ctx["available_factors"]["onchain_valuation"]["rhodl_ratio"]
    exchange_net_position_change = (
        ctx["available_factors"]["onchain_holder_behavior"]["exchange_net_position_change"]
    )
    us2y = ctx["available_factors"]["macro_liquidity"]["us2y"]
    real_yield = ctx["available_factors"]["macro_inflation_rates"]["real_yield"]
    cpi = ctx["available_factors"]["macro_inflation_rates"]["cpi"]
    core_cpi = ctx["available_factors"]["macro_inflation_rates"]["core_cpi"]
    assert profit["status"] == "available"
    assert profit["fetched_at_utc"] == "2026-05-12T14:06:23Z"
    assert profit["fetched_at_bjt"] == "2026-05-12 22:06:23 (BJT)"
    assert profit["captured_at_utc"] == "2026-05-12T00:00:00Z"
    assert loss["status"] == "available"
    assert loss["actual_value"] == 0.085
    assert loss["source"] == "glassnode_onchain_derived"
    assert loss["fetched_at_bjt"] == "2026-05-12 22:06:23 (BJT)"
    assert lth_sopr["status"] == "available"
    assert lth_sopr["actual_value"] == 1.12
    assert lth_sopr["fetched_at_bjt"] == "2026-05-12 22:06:20 (BJT)"
    assert rhodl["status"] == "available"
    assert rhodl["actual_value"] == 1055.6
    assert exchange_net_position_change["status"] == "available"
    assert exchange_net_position_change["actual_value"] == -25.0
    assert exchange_net_position_change["source"] == "glassnode_onchain_derived"
    assert exchange_net_position_change["fetched_at_bjt"] == "2026-05-12 22:06:24 (BJT)"
    assert us2y["status"] == "available"
    assert us2y["fetched_at_utc"] == "2026-05-12T14:07:30Z"
    assert us2y["fetched_at_bjt"] == "2026-05-12 22:07:30 (BJT)"
    assert real_yield["status"] == "available"
    assert real_yield["actual_value"] == 1.95
    assert cpi["status"] == "available"
    assert cpi["actual_value"] == 332.407
    assert cpi["freshness"]["frequency"] == "monthly"
    assert cpi["freshness"]["monthly_latest_ok"] is True
    assert core_cpi["status"] == "available"
    assert core_cpi["actual_value"] == 335.423
    assert core_cpi["freshness"]["frequency"] == "monthly"
    assert core_cpi["freshness"]["monthly_latest_ok"] is True


def test_cpi_core_cpi_monthly_freshness_does_not_hide_existing_values():
    db_path = Path(tempfile.mkdtemp()) / "layer_a_cpi_monthly.db"
    init_db(db_path=db_path, verbose=False)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        MacroDAO.upsert_batch(conn, [
            MacroMetric(
                timestamp="2026-04-01T00:00:00Z",
                metric_name="cpi",
                metric_value=332.407,
                source="fred",
                fetched_at="2026-05-12T14:07:32Z",
            ),
            MacroMetric(
                timestamp="2026-04-01T00:00:00Z",
                metric_name="core_cpi",
                metric_value=335.423,
                source="fred",
                fetched_at="2026-05-12T14:07:33Z",
            ),
        ])
        conn.commit()

        ctx = SpotCycleContextBuilder(conn).build_spot_cycle_context(
            existing_context={
                "_source_stale_map": {"fred_macro": True},
                "_source_hours_map": {"fred_macro": 72.0},
            },
        )
    finally:
        conn.close()

    inflation = ctx["available_factors"]["macro_inflation_rates"]
    assert inflation["cpi"]["status"] == "available"
    assert inflation["cpi"]["actual_value"] == 332.407
    assert inflation["cpi"]["freshness"]["is_stale"] is False
    assert inflation["cpi"]["freshness"]["frequency"] == "monthly"
    assert inflation["core_cpi"]["status"] == "available"
    assert inflation["core_cpi"]["actual_value"] == 335.423
    assert inflation["core_cpi"]["freshness"]["is_stale"] is False
    assert ctx["factor_coverage"]["stale_factor_count"] == 0


def test_cpi_core_cpi_support_legacy_fred_series_id_metric_names():
    db_path = Path(tempfile.mkdtemp()) / "layer_a_cpi_alias.db"
    init_db(db_path=db_path, verbose=False)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        MacroDAO.upsert_batch(conn, [
            MacroMetric(
                timestamp="2026-04-01T00:00:00Z",
                metric_name="CPIAUCSL",
                metric_value=332.407,
                source="fred",
                fetched_at="2026-05-12T14:07:32Z",
            ),
            MacroMetric(
                timestamp="2026-04-01T00:00:00Z",
                metric_name="CPILFESL",
                metric_value=335.423,
                source="fred",
                fetched_at="2026-05-12T14:07:33Z",
            ),
        ])
        conn.commit()

        ctx = SpotCycleContextBuilder(conn).build_spot_cycle_context()
    finally:
        conn.close()

    inflation = ctx["available_factors"]["macro_inflation_rates"]
    assert inflation["cpi"]["status"] == "available"
    assert inflation["cpi"]["actual_value"] == 332.407
    assert inflation["cpi"]["fetched_at_utc"] == "2026-05-12T14:07:32Z"
    assert inflation["core_cpi"]["status"] == "available"
    assert inflation["core_cpi"]["actual_value"] == 335.423
    assert inflation["core_cpi"]["fetched_at_utc"] == "2026-05-12T14:07:33Z"


def test_a1_lightweight_context_contains_only_stage_essentials():
    db_path = Path(tempfile.mkdtemp()) / "layer_a_a1_light.db"
    init_db(db_path=db_path, verbose=False)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        OnchainDAO.upsert_batch(conn, [
            OnchainMetric(
                timestamp="2026-05-12T00:00:00Z",
                metric_name="mvrv_z_score",
                metric_value=1.8,
                source="glassnode_primary",
                fetched_at="2026-05-12T14:06:20Z",
            ),
            OnchainMetric(
                timestamp="2026-05-12T00:00:00Z",
                metric_name="rhodl_ratio",
                metric_value=1200.0,
                source="glassnode_layer_a",
                fetched_at="2026-05-12T14:06:21Z",
            ),
            OnchainMetric(
                timestamp="2026-05-12T00:00:00Z",
                metric_name="lth_sopr",
                metric_value=1.02,
                source="glassnode_layer_a",
                fetched_at="2026-05-12T14:06:22Z",
            ),
        ])
        conn.commit()
        ctx = SpotCycleContextBuilder(conn).build_spot_cycle_context()
    finally:
        conn.close()

    ctx["previous_layer_a_state"] = {
        "generated_at_bjt": "2026-05-14 10:00:00 BJT",
        "cycle_stage_model_version": "layer_a_five_stage_v1",
        "a1_cycle_stage": {
            "official_cycle_stage": "accumulation",
            "raw_stage_assessment": "accumulation",
            "transition_status": "confirmed",
        },
        "a5_spot_adjudicator": {"spot_action": "dca_buy"},
    }
    light = build_a1_cycle_stage_context({"spot_cycle_context": ctx})
    payload = json.dumps(light, ensure_ascii=False, default=str)

    assert set(light.keys()) == {
        "stage_model", "cycle_evidence_summary", "recent_stage_history", "instructions",
    }
    assert light["stage_model"]["previous_official_stage"] == "accumulation"
    assert light["recent_stage_history"][0]["official_stage"] == "accumulation"
    assert "mvrv_z_score" in light["cycle_evidence_summary"]["valuation"]
    assert "rhodl_ratio" in light["cycle_evidence_summary"]["valuation"]
    assert "lth_sopr" in light["cycle_evidence_summary"]["holder_behavior"]
    assert "funding_rate" not in payload
    assert "open_interest" not in payload
    assert "factor_role_classification" not in payload
    assert "series_samples" not in payload
    assert "available_factors" not in light
    assert len(payload) < 12000
