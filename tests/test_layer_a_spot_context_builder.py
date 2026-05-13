from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from src.ai.spot_cycle_context_builder import SpotCycleContextBuilder
from src.data.storage.connection import init_db


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
    assert ctx["available_factors"]["onchain_holder_behavior"]["lth_sopr"]["status"] == "missing"
    assert ctx["available_factors"]["macro_liquidity"]["us2y"]["status"] == "missing"
    assert isinstance(ctx["unavailable_factors"], list)
    unavailable_names = {x["factor"] for x in ctx["unavailable_factors"]}
    for name in (
        "lth_sopr", "sth_sopr", "percent_supply_in_profit",
        "percent_supply_in_loss", "exchange_balance",
        "exchange_net_position_change", "us2y", "fed_funds_rate",
        "m2", "fed_balance_sheet",
    ):
        assert name not in unavailable_names
    assert ctx["factor_coverage"]["critical_unavailable_count"] >= 5
    assert ctx["factor_coverage"]["confidence_cap"] == "low"
    assert ctx["data_quality_notes"]
