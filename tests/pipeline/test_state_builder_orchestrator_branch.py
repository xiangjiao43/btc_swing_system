"""tests/pipeline/test_state_builder_orchestrator_branch.py — Sprint 1.9-A.5.1。

state_builder.run() 加 BTC_USE_ORCHESTRATOR feature flag。
- 默认 false → 走 v1.2 stub fallback 路径(self.build,行为不变)
- true → 走 v1.3 _run_v13_orchestrator 路径
- 大小写不敏感
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.data.storage.connection import init_db
from src.pipeline.state_builder import StrategyStateBuilder, BuildResult


@pytest.fixture
def db_path() -> Path:
    tmp = Path(tempfile.mkdtemp()) / "f.db"
    init_db(db_path=tmp, verbose=False)
    return tmp


@pytest.fixture(autouse=True)
def clean_env():
    """每测试前清掉 BTC_USE_ORCHESTRATOR 环境变量,避免测试间污染。"""
    os.environ.pop("BTC_USE_ORCHESTRATOR", None)
    yield
    os.environ.pop("BTC_USE_ORCHESTRATOR", None)


# ============================================================
# 默认行为 — env 未设
# ============================================================

def test_default_unset_goes_v12_legacy_path(db_path):
    """env 未设 → 走 self.build(v1.2 stub fallback 路径)。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    builder = StrategyStateBuilder(conn)
    # mock self.build 验证被调用
    with patch.object(builder, "build") as mock_build, \
            patch.object(builder, "_run_v13_orchestrator") as mock_v13:
        mock_build.return_value = BuildResult(
            run_id="x", run_timestamp_utc="2026-05-01T00:00:00Z",
            state={}, persisted=True,
        )
        builder.run()
    assert mock_build.called
    assert not mock_v13.called


def test_env_false_goes_v12_legacy_path(db_path):
    os.environ["BTC_USE_ORCHESTRATOR"] = "false"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    builder = StrategyStateBuilder(conn)
    with patch.object(builder, "build") as mock_build, \
            patch.object(builder, "_run_v13_orchestrator") as mock_v13:
        mock_build.return_value = BuildResult(
            run_id="x", run_timestamp_utc="...", state={}, persisted=True,
        )
        builder.run()
    assert mock_build.called
    assert not mock_v13.called


# ============================================================
# env=true 行为
# ============================================================

def test_env_true_lowercase_goes_v13(db_path):
    os.environ["BTC_USE_ORCHESTRATOR"] = "true"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    builder = StrategyStateBuilder(conn)
    with patch.object(builder, "build") as mock_build, \
            patch.object(builder, "_run_v13_orchestrator") as mock_v13:
        mock_v13.return_value = BuildResult(
            run_id="x", run_timestamp_utc="...", state={"v13": True},
            persisted=True, ai_status="ok",
        )
        builder.run()
    assert mock_v13.called
    assert not mock_build.called


def test_env_true_uppercase_case_insensitive(db_path):
    os.environ["BTC_USE_ORCHESTRATOR"] = "TRUE"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    builder = StrategyStateBuilder(conn)
    with patch.object(builder, "build") as mock_build, \
            patch.object(builder, "_run_v13_orchestrator") as mock_v13:
        mock_v13.return_value = BuildResult(
            run_id="x", run_timestamp_utc="...", state={}, persisted=True,
        )
        builder.run()
    assert mock_v13.called
    assert not mock_build.called


def test_env_true_mixed_case_case_insensitive(db_path):
    os.environ["BTC_USE_ORCHESTRATOR"] = "True"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    builder = StrategyStateBuilder(conn)
    with patch.object(builder, "build") as mock_build, \
            patch.object(builder, "_run_v13_orchestrator") as mock_v13:
        mock_v13.return_value = BuildResult(
            run_id="x", run_timestamp_utc="...", state={}, persisted=True,
        )
        builder.run()
    assert mock_v13.called


def test_env_other_value_goes_v12(db_path):
    """非 'true' 值(如 '1' / 'yes' / 'on')→ 仍走 v12(只认 'true')。"""
    os.environ["BTC_USE_ORCHESTRATOR"] = "1"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    builder = StrategyStateBuilder(conn)
    with patch.object(builder, "build") as mock_build, \
            patch.object(builder, "_run_v13_orchestrator") as mock_v13:
        mock_build.return_value = BuildResult(
            run_id="x", run_timestamp_utc="...", state={}, persisted=True,
        )
        builder.run()
    assert mock_build.called
    assert not mock_v13.called


# ============================================================
# v13 path 内部行为(mock orchestrator + mapper)
# ============================================================

def test_v13_path_calls_context_builder_orchestrator_mapper(db_path):
    os.environ["BTC_USE_ORCHESTRATOR"] = "true"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    builder = StrategyStateBuilder(conn)

    # 构造完整 mock chain
    fake_ctx = {"_shared": {"current_close": 75000.0,
                            "reference_timestamp_utc": "2026-05-01T08:00:00Z"},
                "l5": {"extreme_event_flags": {}},
                "l2": {"rule_cycle_position": {"label": "early_bull"}}}
    fake_result = {
        "layers": {
            "l1": {"regime": "trend_up"}, "l2": {"stance": "bullish"},
            "l3": {"opportunity_grade": "A"}, "l4": {"risk_tier": "moderate"},
            "l5": {"macro_stance": "supportive"},
            "master": {"state_transition": {"to_state": "LONG_PLANNED",
                                             "from_state": "FLAT"},
                       "trade_plan": {"action": "open"}},
        },
        "validator": {"violations": [], "passed": True},
        "status": "ok",
        "latency_ms": {},
    }

    with patch("src.ai.context_builder.ContextBuilder") as mock_cb, \
            patch("src.ai.orchestrator.AIOrchestrator") as mock_orch:
        mock_cb.return_value.build_full_context.return_value = fake_ctx
        mock_orch.return_value.run_full_a.return_value = fake_result
        result = builder.run()

    assert result.persisted is True
    assert result.ai_status == "ok"
    assert result.state.get("v13_orchestrator") is True
    # 验证 strategy_runs 真有 1 行写入
    cur = conn.execute("SELECT COUNT(*) FROM strategy_runs")
    assert cur.fetchone()[0] == 1


def test_v13_path_db_row_action_state_matches_master_to_state(db_path):
    """端到端:走 v13 路径,DB 中新行 action_state == master.to_state。"""
    os.environ["BTC_USE_ORCHESTRATOR"] = "true"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    builder = StrategyStateBuilder(conn)

    fake_ctx = {"_shared": {"current_close": 80000.0,
                            "reference_timestamp_utc": "2026-05-01T16:00:00Z"},
                "l5": {"extreme_event_flags": {}},
                "l2": {"rule_cycle_position": {}}}
    fake_result = {
        "layers": {
            "l1": {}, "l2": {"stance": "bearish"}, "l3": {}, "l4": {}, "l5": {},
            "master": {"state_transition": {"to_state": "SHORT_PLANNED",
                                             "from_state": "FLAT"}},
        },
        "validator": {"passed": True},
        "status": "ok",
        "latency_ms": {},
    }

    with patch("src.ai.context_builder.ContextBuilder") as mock_cb, \
            patch("src.ai.orchestrator.AIOrchestrator") as mock_orch:
        mock_cb.return_value.build_full_context.return_value = fake_ctx
        mock_orch.return_value.run_full_a.return_value = fake_result
        builder.run()

    row = conn.execute(
        "SELECT action_state, stance, btc_price_usd FROM strategy_runs"
    ).fetchone()
    assert row["action_state"] == "SHORT_PLANNED"
    assert row["stance"] == "bearish"
    assert row["btc_price_usd"] == 80000.0


def test_v13_path_handles_orchestrator_exception_gracefully(db_path):
    """orchestrator raise → 返回 persisted=False + ai_status='failed_*',不抛。"""
    os.environ["BTC_USE_ORCHESTRATOR"] = "true"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    builder = StrategyStateBuilder(conn)

    with patch("src.ai.context_builder.ContextBuilder") as mock_cb:
        mock_cb.return_value.build_full_context.side_effect = (
            RuntimeError("ctx build failed"))
        result = builder.run()
    assert result.persisted is False
    assert result.ai_status.startswith("failed_")


def test_v13_path_full_state_json_contains_layers(db_path):
    """端到端:写入 DB 的 full_state_json 含 layers 子键(parse_previous 依赖)。"""
    import json
    os.environ["BTC_USE_ORCHESTRATOR"] = "true"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    builder = StrategyStateBuilder(conn)

    fake_ctx = {"_shared": {"current_close": 75000.0}, "l5": {}, "l2": {}}
    fake_result = {
        "layers": {
            "l1": {"regime": "trend_up"}, "l2": {"stance": "bullish"},
            "l3": {}, "l4": {}, "l5": {},
            "master": {"state_transition": {"to_state": "FLAT",
                                             "from_state": "FLAT"}},
        },
        "validator": {"passed": True}, "status": "ok", "latency_ms": {},
    }
    with patch("src.ai.context_builder.ContextBuilder") as mock_cb, \
            patch("src.ai.orchestrator.AIOrchestrator") as mock_orch:
        mock_cb.return_value.build_full_context.return_value = fake_ctx
        mock_orch.return_value.run_full_a.return_value = fake_result
        builder.run()

    row = conn.execute(
        "SELECT full_state_json FROM strategy_runs"
    ).fetchone()
    parsed = json.loads(row["full_state_json"])
    assert "layers" in parsed
    assert "l1" in parsed["layers"]
    assert parsed["layers"]["l1"]["regime"] == "trend_up"
