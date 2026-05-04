"""tests/test_web_schema_gate.py — Sprint 1.10-I commit 7 schema gate 测试。

真用户视觉验证发现 bug:web/assets/app.js:549 写死 schema_version === 'v13',
新 v14 数据永远不渲染。本测试覆盖:
- 前端 _normalize gate 三态(v13 / v14 / hasBasicData / 空)
- 后端 state_builder._assemble_state 含 schema_version='v14'
- _orchestrator_mapper._build_full_state_json 含 schema_version='v14'
- §X v13-only error 文本已删
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parent.parent
_APP_JS = _REPO_ROOT / "web" / "assets" / "app.js"


@pytest.fixture(scope="module")
def js() -> str:
    return _APP_JS.read_text(encoding="utf-8")


# ============================================================
# 1. 前端 _normalize gate 三态升级
# ============================================================

def test_gate_no_longer_only_v13(js):
    """§X:不再写死 raw.schema_version === 'v13'(单条件 gate)。"""
    # 不能再有"只有 v13 时渲染,否则报错"的死循环
    # 旧错误文本必须删
    assert "数据格式异常(非 v13 schema)" not in js


def test_gate_handles_v13_path(js):
    """v13 路径保留:hasV13Schema → _to_display_state_v13。"""
    assert "hasV13Schema" in js
    assert "_to_display_state_v13" in js


def test_gate_handles_v14_modules(js):
    """v14 检测:含 1.10-I 4 字段任一 OR schema_version='v14' → 直接消费。"""
    assert "hasV14Modules" in js
    assert "account_summary" in js
    assert "active_thesis" in js
    assert "position_summary" in js
    assert "pending_orders_summary" in js
    assert "schema_version === 'v14'" in js


def test_gate_basic_data_fallback(js):
    """hasBasicData:run_id + generated_at_utc 兜底,避免未来 schema 死锁。"""
    assert "hasBasicData" in js
    assert "raw.run_id" in js
    assert "raw.generated_at_utc" in js


def test_gate_empty_data_friendly_error(js):
    """完全空数据:不报"格式异常",改为等待下次 run 提示。"""
    assert "数据为空,等待下次 strategy_run" in js
    # 老误导文本不在
    assert "管理员重启服务" not in js


def test_gate_returns_raw_for_v14_path(js):
    """v14 路径直接 return raw(各模块处理空字段)。"""
    # 检查 hasV14Modules || hasBasicData 分支返 raw
    assert "if (hasV14Modules || hasBasicData)" in js
    # 注释说明各模块 cold-start placeholder 已实施
    assert "cold-start placeholder" in js or "未初始化" in js


# ============================================================
# 2. 后端 state_builder._assemble_state 含 schema_version='v14'
# ============================================================

def test_state_builder_assemble_state_includes_schema_version():
    """state_builder._assemble_state 返 dict 含 schema_version='v14'。"""
    src = (_REPO_ROOT / "src" / "pipeline" / "state_builder.py").read_text(
        encoding="utf-8",
    )
    # _assemble_state 函数体内有 "schema_version": "v14"
    assert '"schema_version": "v14"' in src


def test_orchestrator_mapper_full_state_json_includes_schema_version():
    """_orchestrator_mapper._build_full_state_json 返 JSON 含 schema_version='v14'。"""
    src = (
        _REPO_ROOT / "src" / "pipeline" / "_orchestrator_mapper.py"
    ).read_text(encoding="utf-8")
    assert '"schema_version": "v14"' in src


# ============================================================
# 3. _assemble_state 单元行为验证(直接调,不走 builder.run)
# ============================================================

def test_assemble_state_writes_v14_schema_version():
    """直接调 StrategyStateBuilder._assemble_state,验证返回 dict 含
    schema_version='v14'。"""
    from src.pipeline.state_builder import StrategyStateBuilder
    from unittest.mock import MagicMock

    # MagicMock conn 即可(_assemble_state 不读 conn)
    conn = MagicMock()
    builder = StrategyStateBuilder(
        conn, account_state_provider=None,
    )
    state = builder._assemble_state(
        run_id="r_test", run_ts_utc="2026-05-04T08:00:00Z",
        run_trigger="scheduled",
        context={},
        composite_factors={},
        ai_result={"model_used": "claude-test", "status": "success"},
        failures=[],
        degraded_stages=[],
    )
    assert state.get("schema_version") == "v14"
    # 原字段仍在
    assert state.get("run_id") == "r_test"
    assert state.get("run_trigger") == "scheduled"


# ============================================================
# 4. _build_full_state_json 单元行为验证
# ============================================================

def test_build_full_state_json_includes_schema_version():
    from src.pipeline._orchestrator_mapper import _build_full_state_json

    json_str = _build_full_state_json(
        result={"layers": {}, "status": "ok", "latency_ms": {}},
        context={},
    )
    parsed = json.loads(json_str)
    assert parsed.get("schema_version") == "v14"


# ============================================================
# 5. 端到端:strategy/current 返 schema_version='v14'(真 DAO)
# ============================================================

@pytest.fixture
def db_path(tmp_path):
    """新建 DB + apply migrations。"""
    import sqlite3
    db = tmp_path / "test_schema.db"
    from src.data.storage.connection import init_db
    init_db(db_path=db, verbose=False)
    conn = sqlite3.connect(str(db))
    from scripts.init_v14_tables import apply_migration
    apply_migration(conn)
    conn.commit()
    conn.close()
    return db


def test_e2e_state_persisted_with_schema_version(db_path):
    """模拟一次真 _persist_state → 读回 → 含 schema_version='v14'。"""
    import sqlite3
    from src.data.storage.dao import StrategyStateDAO

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    StrategyStateDAO.insert_state(
        conn,
        run_timestamp_utc="2026-05-04T08:00:00Z",
        run_id="r_v14_test",
        run_trigger="scheduled",
        rules_version="v1.4",
        ai_model_actual="claude-test",
        state={
            "schema_version": "v14",
            "run_id": "r_v14_test",
            "generated_at_utc": "2026-05-04T08:00:00Z",
            "state_machine": {"current_state": "FLAT"},
            "market_snapshot": {"btc_price_usd": 75000.0},
            "observation": {"observation_category": "neutral"},
        },
    )
    conn.commit()

    row = conn.execute(
        "SELECT full_state_json FROM strategy_runs WHERE run_id=?",
        ("r_v14_test",),
    ).fetchone()
    parsed = json.loads(row["full_state_json"])
    assert parsed.get("schema_version") == "v14"
    conn.close()
