from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.data.storage.connection import get_connection, init_db
from src.data.storage.dao import (
    LatestLayerASpotStrategyDAO,
    StrategyStateDAO,
)
from src.pipeline.layer_a_spot_runner import LayerASpotStrategyRunner
from src.pipeline.state_builder import StrategyStateBuilder
from src.scheduler.jobs import build_job_configs, load_scheduler_config


def _db_path() -> Path:
    tmp = Path(tempfile.mkdtemp()) / "layer_a_standalone.db"
    init_db(db_path=tmp, verbose=False)
    return tmp


def _sample_layer_a(action: str = "dca_buy") -> dict:
    return {
        "enabled": True,
        "a1_cycle_stage": {
            "cycle_stage": "recovery",
            "confidence": "medium",
            "headline": "底部吸筹",
            "human_summary": "大周期偏吸筹。",
        },
        "a2_onchain_macro": {
            "onchain_macro_stance": "neutral",
            "confidence": "medium",
            "human_summary": "链上宏观中性。",
        },
        "a3_spot_opportunity": {
            "preferred_action_candidate": action,
            "confidence": "medium",
            "human_summary": "适合分批。",
        },
        "a4_spot_risk": {
            "spot_risk_level": "moderate",
            "confidence": "medium",
            "human_summary": "风险中等。",
        },
        "a5_spot_adjudicator": {
            "spot_action": action,
            "cycle_stage": "recovery",
            "confidence": "medium",
            "headline": "分批买入",
            "human_summary": "现货仓分批买入。",
            "what_would_change_mind": ["跌破关键链上支撑"],
            "supporting_evidence": ["估值不高"],
            "opposing_evidence": ["宏观仍有压力"],
        },
        "validator": {"passed": True, "violations": [], "warnings": []},
        "unavailable_factors": [],
        "factor_coverage": {"confidence_cap": "high"},
    }


def test_scheduler_has_layer_a_1000_and_layer_b_1135():
    cfg = load_scheduler_config()
    jobs = {j.name: j for j in build_job_configs(cfg)}
    assert jobs["layer_a_spot_strategy"].trigger_kwargs == {"hour": 10, "minute": 0}
    assert jobs["pipeline_run_regular"].trigger_kwargs == {"hour": 11, "minute": 35}


def test_layer_b_builder_does_not_call_layer_a_by_default():
    db = _db_path()
    os.environ["BTC_USE_ORCHESTRATOR"] = "true"
    conn = get_connection(db)
    try:
        fake_ctx = {"_shared": {"current_close": 70000.0}, "l5": {}, "l2": {}}
        fake_result = {
            "layers": {
                "l1": {}, "l2": {}, "l3": {}, "l4": {}, "l5": {},
                "master": {"mode": "silent_cooldown"},
            },
            "validator": {"passed": True},
            "status": "ok",
            "latency_ms": {},
        }
        with patch("src.ai.context_builder.ContextBuilder") as mock_cb, \
             patch("src.ai.orchestrator.AIOrchestrator") as mock_orch:
            mock_cb.return_value.build_full_context.return_value = fake_ctx
            mock_orch.return_value.run_full_a.return_value = fake_result
            result = StrategyStateBuilder(conn).run(run_trigger="manual")
        assert result.persisted is True
        mock_orch.return_value.run_full_a.assert_called_once()
        assert mock_orch.return_value.run_full_a.call_args.kwargs["include_layer_a"] is False
        row = conn.execute("SELECT full_state_json FROM strategy_runs").fetchone()
        parsed = json.loads(row["full_state_json"])
        assert parsed.get("layer_a_spot_strategy") is None
    finally:
        os.environ.pop("BTC_USE_ORCHESTRATOR", None)
        conn.close()


def test_layer_a_runner_persists_latest_without_strategy_run_or_thesis():
    db = _db_path()
    conn = get_connection(db)
    try:
        with patch("src.pipeline.layer_a_spot_runner.ContextBuilder") as mock_cb, \
             patch("src.pipeline.layer_a_spot_runner.AIOrchestrator") as mock_orch:
            mock_cb.return_value.build_full_context.return_value = {
                "_shared": {},
                "_source_stale_map": {},
                "_source_hours_map": {},
            }
            mock_orch.return_value.run_layer_a_spot_only.return_value = _sample_layer_a()
            result = LayerASpotStrategyRunner(conn).run(run_trigger="manual", persist=True)
        assert result.persisted is True
        assert result.status == "success"
        assert conn.execute("SELECT COUNT(*) FROM latest_layer_a_spot_strategy").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM strategy_runs").fetchone()[0] == 0
        thesis_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='theses'"
        ).fetchone()
        if thesis_table is not None:
            assert conn.execute("SELECT COUNT(*) FROM theses").fetchone()[0] == 0
        latest = LatestLayerASpotStrategyDAO.get_latest(conn)
        assert latest["layer_a"]["a5_spot_adjudicator"]["spot_action"] == "dca_buy"
    finally:
        conn.close()


def test_layer_a_validate_stages_skips_ai_and_persist():
    db = _db_path()
    conn = get_connection(db)
    try:
        with patch("src.pipeline.layer_a_spot_runner.ContextBuilder") as mock_cb, \
             patch("src.pipeline.layer_a_spot_runner.AIOrchestrator") as mock_orch:
            mock_cb.return_value.build_full_context.return_value = {
                "_shared": {},
                "_source_stale_map": {},
                "_source_hours_map": {},
            }
            result = LayerASpotStrategyRunner(conn).run(
                run_trigger="manual",
                persist=True,
                validate_stages=True,
            )
        assert result.status == "success"
        assert result.persisted is False
        assert not mock_orch.return_value.run_layer_a_spot_only.called
        assert conn.execute("SELECT COUNT(*) FROM latest_layer_a_spot_strategy").fetchone()[0] == 0
    finally:
        conn.close()


def test_api_current_overlays_latest_layer_a_without_overwriting_layer_b():
    db = _db_path()
    conn = get_connection(db)
    try:
        StrategyStateDAO.insert_state(
            conn,
            run_timestamp_utc="2026-05-13T03:35:00Z",
            run_id="layer-b-run",
            run_trigger="scheduled",
            rules_version="v1",
            ai_model_actual="claude",
            state={
                "schema_version": "v14",
                "layers": {"l1": {}, "l2": {}, "l3": {}, "l4": {}, "l5": {}, "master": {}},
                "status": "ok",
                "layer_a_spot_strategy": None,
            },
        )
        LatestLayerASpotStrategyDAO.upsert(
            conn,
            run_id="layer-a-run",
            generated_at_utc="2026-05-13T02:00:00Z",
            generated_at_bjt="2026-05-13 10:00:00 BJT",
            run_trigger="scheduled_layer_a_spot",
            status="success",
            ai_model_actual=None,
            layer_a=_sample_layer_a(),
        )
        conn.commit()
    finally:
        conn.close()

    app = create_app(conn_factory=lambda: get_connection(db))
    with TestClient(app) as client:
        body = client.get("/api/strategy/current").json()
    assert body["run_id"] == "layer-b-run"
    assert body["state"]["layer_a_spot_strategy"]["run_id"] == "layer-a-run"
    assert body["state"]["layer_a_spot_strategy"]["generated_at_bjt"] == "2026-05-13 10:00:00 BJT"
    assert body["state"]["layer_a_spot_strategy"]["a5_spot_adjudicator"]["spot_action"] == "dca_buy"
