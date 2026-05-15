"""Sprint D — 共用 freshness 模块 + API fallback + 显示侧 stale 守卫 +
master prompt 注入 + stale 披露 validator 端到端测试。
"""
from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.data.freshness import (
    LAYER_SOURCE_DEPS, STALE_THRESHOLD_SECONDS,
    compute_all_freshness, compute_source_freshness, freshness_to_dict,
    stale_summary_for_layer,
)
from src.data.storage.connection import get_connection, init_db
from src.data.storage.dao import FetchAttemptsDAO


@pytest.fixture
def db_path():
    tmp = Path(tempfile.mkdtemp()) / "sprint_d.db"
    init_db(db_path=tmp, verbose=False)
    # v1.4 表(theses / virtual_account / virtual_orders 等),master_input_builder 需要
    import sqlite3 as _sqlite3
    from scripts.init_v14_tables import apply_migration
    c = _sqlite3.connect(str(tmp))
    apply_migration(c)
    c.commit()
    c.close()
    return tmp


@pytest.fixture
def client(db_path):
    def _factory():
        return get_connection(db_path)
    app = create_app(conn_factory=_factory, pipeline_trigger_cooldown_sec=60.0)
    return TestClient(app)


def _conn(db_path: Path) -> sqlite3.Connection:
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    return c


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ============================================================
# Item 1 — fetch_attempts 没 success → data 表 fallback
# ============================================================

def test_freshness_fallback_to_data_table_when_no_success_row(db_path):
    """fetch_attempts 只有 failure / 没 success → 从 onchain_metrics 一手 source
    MAX 取 last_success_at_utc。"""
    now = datetime.now(timezone.utc)
    fallback_iso = _iso(now - timedelta(hours=10))
    conn = _conn(db_path)
    try:
        # onchain_metrics 一手 source 写入(模拟历史成功 fetch 留下的数据)
        conn.execute(
            "INSERT INTO onchain_metrics "
            "(metric_name, captured_at_utc, value, source, inserted_at_utc) "
            "VALUES (?, ?, ?, ?, ?)",
            ("mvrv_z_score", fallback_iso, 1.5, "glassnode_primary", fallback_iso),
        )
        # fetch_attempts 只有 failure
        FetchAttemptsDAO.record_attempt(
            conn, source="glassnode_onchain", status="failure",
            failure_reason="quota_exceeded",
            attempted_at_utc=_iso(now - timedelta(minutes=30)),
        )
        conn.commit()
        f = compute_source_freshness(conn, "glassnode_onchain", now=now)
    finally:
        conn.close()

    assert f.status == "failure"
    assert f.last_success_at_utc == fallback_iso
    assert f.last_success_source == "data_table"
    assert f.failure_reason == "quota_exceeded"
    # fallback 时间 ≈ 10h 前,< 48h 阈值 → not stale
    assert abs(f.hours_since_last_success - 10.0) < 0.1
    assert f.is_stale is False


def test_freshness_partial_when_failure_upserted_rows_and_data_is_fresh(db_path):
    """Glassnode 单个 endpoint 失败但同轮已写入数据 → source 显示部分异常。"""
    now = datetime.now(timezone.utc)
    fresh_iso = _iso(now - timedelta(minutes=2))
    conn = _conn(db_path)
    try:
        conn.execute(
            "INSERT INTO onchain_metrics "
            "(metric_name, captured_at_utc, value, source, inserted_at_utc) "
            "VALUES (?, ?, ?, ?, ?)",
            ("mvrv", fresh_iso, 1.5, "glassnode_primary", fresh_iso),
        )
        FetchAttemptsDAO.record_attempt(
            conn, source="glassnode_onchain", status="failure",
            failure_reason="quota_exceeded",
            error_message="HTTP 429 on /v1/metrics/indicators/puell_multiple",
            rows_upserted=869,
            attempted_at_utc=_iso(now - timedelta(minutes=1)),
        )
        conn.commit()
        f = compute_source_freshness(conn, "glassnode_onchain", now=now)
    finally:
        conn.close()

    assert f.status == "partial"
    assert f.failure_reason == "quota_exceeded"
    assert f.failure_reason_label == "部分异常"
    assert f.display_label == "部分异常：Puell Multiple 429"
    assert f.main_failure_metric == "puell_multiple"
    assert f.main_failure_endpoint == "/v1/metrics/indicators/puell_multiple"
    assert f.main_failure_http_status == 429
    assert f.rows_upserted == 869
    assert f.is_stale is False


def test_freshness_newer_success_data_overrides_old_failure_without_rows(db_path):
    """旧失败后已有更新一手数据 → 不让旧失败继续污染当前健康状态。"""
    now = datetime.now(timezone.utc)
    failure_iso = _iso(now - timedelta(hours=2))
    newer_data_iso = _iso(now - timedelta(minutes=5))
    conn = _conn(db_path)
    try:
        FetchAttemptsDAO.record_attempt(
            conn, source="glassnode_onchain", status="failure",
            failure_reason="quota_exceeded",
            error_message="old quota failure",
            rows_upserted=0,
            attempted_at_utc=failure_iso,
        )
        conn.execute(
            "INSERT INTO onchain_metrics "
            "(metric_name, captured_at_utc, value, source, inserted_at_utc) "
            "VALUES (?, ?, ?, ?, ?)",
            ("mvrv", newer_data_iso, 1.5, "glassnode_primary", newer_data_iso),
        )
        conn.commit()
        f = compute_source_freshness(conn, "glassnode_onchain", now=now)
    finally:
        conn.close()

    assert f.status == "success"
    assert f.failure_reason is None
    assert f.failure_reason_label is None
    assert f.last_success_at_utc == newer_data_iso
    assert f.last_success_source == "data_table"


def test_freshness_excludes_computed_source_in_glassnode_fallback(db_path):
    """关键反退化:glassnode_onchain 的 fallback 必须排除 source='computed' 派生
    数据 — 否则 derived MVRV 写行会让网页假装"今天有数据"。"""
    now = datetime.now(timezone.utc)
    derived_only_iso = _iso(now - timedelta(hours=2))
    conn = _conn(db_path)
    try:
        conn.execute(
            "INSERT INTO onchain_metrics "
            "(metric_name, captured_at_utc, value, source, inserted_at_utc) "
            "VALUES (?, ?, ?, ?, ?)",
            ("lth_mvrv", derived_only_iso, 2.5, "computed", derived_only_iso),
        )
        conn.commit()
        f = compute_source_freshness(conn, "glassnode_onchain", now=now)
    finally:
        conn.close()

    # 没有任何一手 source 数据 → fallback 应返 None,is_stale=True
    assert f.last_success_at_utc is None
    assert f.is_stale is True


def test_freshness_data_table_fallback_for_each_source(db_path):
    """4 个 source 的 fallback 表映射全部正确。"""
    now = datetime.now(timezone.utc)
    fresh_iso = _iso(now - timedelta(minutes=30))
    conn = _conn(db_path)
    try:
        # binance_kline → price_candles 1h
        conn.execute(
            "INSERT INTO price_candles "
            "(symbol, timeframe, open_time_utc, open, high, low, close, volume, "
            " inserted_at_utc) "
            "VALUES ('BTCUSDT', '1h', ?, 50000, 50100, 49900, 50050, 1.0, ?)",
            (fresh_iso, fresh_iso),
        )
        # coinglass_derivatives → derivatives_snapshots
        conn.execute(
            "INSERT INTO derivatives_snapshots "
            "(captured_at_utc, inserted_at_utc) VALUES (?, ?)",
            (fresh_iso, fresh_iso),
        )
        # glassnode_onchain → onchain_metrics(一手)
        conn.execute(
            "INSERT INTO onchain_metrics "
            "(metric_name, captured_at_utc, value, source, inserted_at_utc) "
            "VALUES (?, ?, ?, ?, ?)",
            ("mvrv", fresh_iso, 1.0, "glassnode_primary", fresh_iso),
        )
        # fred_macro → macro_metrics
        conn.execute(
            "INSERT INTO macro_metrics "
            "(metric_name, captured_at_utc, value, source, inserted_at_utc) "
            "VALUES (?, ?, ?, ?, ?)",
            ("dxy", fresh_iso, 105.0, "fred", fresh_iso),
        )
        conn.commit()

        all_fresh = compute_all_freshness(conn, now=now)
    finally:
        conn.close()

    by_source = {f.source: f for f in all_fresh}
    for src in ("binance_kline", "coinglass_derivatives",
                "glassnode_onchain", "fred_macro"):
        f = by_source[src]
        assert f.last_success_at_utc == fresh_iso, (
            f"{src} fallback 没命中 — got {f.last_success_at_utc}"
        )
        assert f.last_success_source == "data_table"
        assert f.is_stale is False


def test_freshness_stale_thresholds_per_source():
    """4 源 stale 阈值与 spec 对齐。"""
    assert STALE_THRESHOLD_SECONDS["binance_kline"] == 3 * 3600
    assert STALE_THRESHOLD_SECONDS["coinglass_derivatives"] == 3 * 3600
    assert STALE_THRESHOLD_SECONDS["glassnode_onchain"] == 48 * 3600
    assert STALE_THRESHOLD_SECONDS["fred_macro"] == 72 * 3600


# ============================================================
# Item 1 — API endpoint:fallback 消除「从未成功过」/「尚未抓取」
# ============================================================

def test_api_freshness_uses_fallback_text_when_no_attempt(client, db_path):
    """no_data 状态 → API 仍尝试给 last_success_at(从数据表 fallback)。"""
    now = datetime.now(timezone.utc)
    fresh_iso = _iso(now - timedelta(hours=8))
    conn = _conn(db_path)
    try:
        conn.execute(
            "INSERT INTO macro_metrics "
            "(metric_name, captured_at_utc, value, source, inserted_at_utc) "
            "VALUES (?, ?, ?, ?, ?)",
            ("dxy", fresh_iso, 105.0, "fred", fresh_iso),
        )
        conn.commit()
    finally:
        conn.close()
    body = client.get("/api/data_sources/freshness").json()
    fred = next(r for r in body if r["source"] == "fred_macro")
    assert fred["status"] == "no_data"
    assert fred["last_success_at_utc"] == fresh_iso
    assert fred["last_success_at_bjt"] is not None


def test_api_freshness_failure_falls_back_to_data_table(client, db_path):
    """fetch_attempts 只有 failure + 数据表有 history → last_success_at 来自数据表。"""
    now = datetime.now(timezone.utc)
    fallback_iso = _iso(now - timedelta(hours=20))
    conn = _conn(db_path)
    try:
        conn.execute(
            "INSERT INTO onchain_metrics "
            "(metric_name, captured_at_utc, value, source, inserted_at_utc) "
            "VALUES (?, ?, ?, ?, ?)",
            ("mvrv", fallback_iso, 1.0, "glassnode_primary", fallback_iso),
        )
        FetchAttemptsDAO.record_attempt(
            conn, source="glassnode_onchain", status="failure",
            failure_reason="quota_exceeded",
            attempted_at_utc=_iso(now - timedelta(minutes=5)),
        )
        conn.commit()
    finally:
        conn.close()
    body = client.get("/api/data_sources/freshness").json()
    gn = next(r for r in body if r["source"] == "glassnode_onchain")
    assert gn["status"] == "failure"
    assert gn["last_success_at_utc"] == fallback_iso


# ============================================================
# Item 4 — 显示侧 evidence_layers stale 覆盖
# ============================================================

def test_evidence_layers_health_overridden_when_glassnode_stale(
    client, db_path,
):
    """L2 / L4 依赖 glassnode_onchain;一手 stale > 48h → 网页层 health=degraded。"""
    now = datetime.now(timezone.utc)
    stale_iso = _iso(now - timedelta(hours=72))
    fresh_iso = _iso(now - timedelta(minutes=30))
    conn = _conn(db_path)
    try:
        # 一手 Glassnode 数据 72 小时老 → stale
        conn.execute(
            "INSERT INTO onchain_metrics "
            "(metric_name, captured_at_utc, value, source, inserted_at_utc) "
            "VALUES (?, ?, ?, ?, ?)",
            ("mvrv", stale_iso, 1.0, "glassnode_primary", stale_iso),
        )
        # 其他源 fresh,确保 L1 / L5 不被 stale 覆盖
        conn.execute(
            "INSERT INTO price_candles "
            "(symbol, timeframe, open_time_utc, open, high, low, close, "
            " volume, inserted_at_utc) "
            "VALUES ('BTCUSDT', '1h', ?, 50000, 50100, 49900, 50050, 1.0, ?)",
            (fresh_iso, fresh_iso),
        )
        conn.execute(
            "INSERT INTO macro_metrics "
            "(metric_name, captured_at_utc, value, source, inserted_at_utc) "
            "VALUES (?, ?, ?, ?, ?)",
            ("dxy", fresh_iso, 105.0, "fred", fresh_iso),
        )
        # 写一行 strategy_run,layers 全 healthy
        import json
        full_state = {
            "layers": {
                f"l{i}": {"status": "success", "key_observations": ["ok"]}
                for i in range(1, 6)
            }
        }
        conn.execute(
            "INSERT INTO strategy_runs "
            "(run_id, generated_at_utc, generated_at_bjt, "
            " reference_timestamp_utc, action_state, stance, "
            " btc_price_usd, full_state_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("r_test", _iso(now), _iso(now), _iso(now),
             "FLAT", "neutral", 50000.0, json.dumps(full_state)),
        )
        conn.commit()
    finally:
        conn.close()

    body = client.get("/api/system/health-detail").json()
    layers = {L["layer_id"]: L for L in body["evidence_layers"]}
    assert layers[2]["health"] == "degraded", "L2 应被 stale 覆盖成 degraded"
    assert layers[4]["health"] == "degraded", "L4 应被 stale 覆盖成 degraded"
    # missing_reasons 应包含「依赖的 Glassnode 链上 数据已过期 N 小时」
    l2_reasons = " ".join(layers[2].get("missing_reasons") or [])
    assert "Glassnode" in l2_reasons and "过期" in l2_reasons
    # L1 不依赖 Glassnode → 不应被覆盖
    assert layers[1]["health"] == "healthy"


def test_layer_source_deps_mapping():
    """L1-L5 依赖 source 映射符合 Sprint D 设计。"""
    assert LAYER_SOURCE_DEPS[1] == ("binance_kline",)
    assert "glassnode_onchain" in LAYER_SOURCE_DEPS[2]
    assert LAYER_SOURCE_DEPS[3] == ()  # L3 衍生自 L1+L2
    assert "coinglass_derivatives" in LAYER_SOURCE_DEPS[4]
    assert LAYER_SOURCE_DEPS[5] == ("fred_macro",)


def test_stale_summary_for_layer_returns_chinese_msg(db_path):
    now = datetime.now(timezone.utc)
    stale_iso = _iso(now - timedelta(hours=60))
    conn = _conn(db_path)
    try:
        conn.execute(
            "INSERT INTO onchain_metrics "
            "(metric_name, captured_at_utc, value, source, inserted_at_utc) "
            "VALUES (?, ?, ?, ?, ?)",
            ("mvrv", stale_iso, 1.0, "glassnode_primary", stale_iso),
        )
        conn.commit()
        all_fresh = compute_all_freshness(conn, now=now)
    finally:
        conn.close()

    msgs_l2 = stale_summary_for_layer(2, all_fresh)
    assert any("Glassnode 链上" in m for m in msgs_l2)
    assert any("过期" in m and "小时" in m for m in msgs_l2)
    msgs_l1 = stale_summary_for_layer(1, all_fresh)
    # L1 不依赖 Glassnode,且 binance_kline 数据库空 → fallback null →
    # binance_kline 也算 stale(无可用数据)→ 也产 1 条 stale 句子
    assert any("Binance K 线" in m for m in msgs_l1)


# ============================================================
# Item 3 — master_input_builder 注入 freshness summary
# ============================================================

def test_master_input_builder_injects_freshness_summary(db_path):
    from src.ai.master_input_builder import build_master_input
    now = datetime.now(timezone.utc)
    stale_iso = _iso(now - timedelta(hours=72))
    conn = _conn(db_path)
    try:
        conn.execute(
            "INSERT INTO onchain_metrics "
            "(metric_name, captured_at_utc, value, source, inserted_at_utc) "
            "VALUES (?, ?, ?, ?, ?)",
            ("mvrv", stale_iso, 1.0, "glassnode_primary", stale_iso),
        )
        conn.commit()
        master_input = build_master_input(
            conn,
            layer_outputs={f"l{i}": {} for i in range(1, 6)},
            current_btc_price=50000.0,
            now_utc=_iso(now),
        )
    finally:
        conn.close()

    assert "data_freshness_summary" in master_input
    rows = master_input["data_freshness_summary"]
    assert isinstance(rows, list) and len(rows) == 4
    by_src = {r["source"]: r for r in rows}
    assert by_src["glassnode_onchain"]["is_stale"] is True
    assert by_src["glassnode_onchain"]["failure_reason"] is None  # fallback 路径


def test_master_adjudicator_prompt_renders_stale_warning():
    """MasterAdjudicator._build_user_prompt 必须把 stale 源标 ⚠️。"""
    from src.ai.agents.master_adjudicator import MasterAdjudicator
    agent = MasterAdjudicator(client=None)
    context = {
        "l1_output": {"status": "success"},
        "data_freshness_summary": [
            {"source": "glassnode_onchain",
             "display_name": "Glassnode 链上",
             "status": "failure",
             "is_stale": True,
             "hours_since_last_success": 72.5,
             "last_success_at_utc": "2026-05-05T00:00:00Z",
             "failure_reason": "quota_exceeded",
             "failure_reason_label": "配额用尽"},
            {"source": "binance_kline",
             "display_name": "Binance K 线",
             "status": "success",
             "is_stale": False,
             "hours_since_last_success": 0.5,
             "last_success_at_utc": "2026-05-08T07:30:00Z",
             "failure_reason": None,
             "failure_reason_label": None},
        ],
    }
    prompt = agent._build_user_prompt(context)
    assert "[数据新鲜度]" in prompt
    assert "⚠️ Glassnode 链上" in prompt
    assert "已过期 72.5 小时" in prompt
    assert "配额用尽" in prompt
    assert "🟢 Binance K 线" in prompt
    assert "纪律" in prompt


def test_master_adjudicator_prompt_skips_block_when_no_freshness():
    """没传 data_freshness_summary → prompt 不含 [数据新鲜度] 段(向后兼容)。"""
    from src.ai.agents.master_adjudicator import MasterAdjudicator
    agent = MasterAdjudicator(client=None)
    prompt = agent._build_user_prompt({"l1_output": {}})
    assert "[数据新鲜度]" not in prompt


# ============================================================
# Item 3 — VStale validator
# ============================================================

def test_validator_stale_disclosure_passes_when_narrative_mentions_keyword():
    from src.ai.validator import validator_stale_disclosure
    master_output = {
        "mode": "new_thesis",
        "narrative": (
            "L1 趋势上行,但 Glassnode 链上数据已过期 72 小时,"
            "本判断可信度相应降级。"
        ),
        "one_line_summary": "stale 数据警告,谨慎做多。",
    }
    context = {
        "data_freshness_summary": [
            {"source": "glassnode_onchain", "is_stale": True}
        ],
    }
    out, act = validator_stale_disclosure(master_output, context)
    assert act["validator_stale_disclosure_missing"] is False


def test_validator_stale_disclosure_fails_when_narrative_silent():
    from src.ai.validator import validator_stale_disclosure
    master_output = {
        "mode": "new_thesis",
        "narrative": "L1 趋势上行,L2 突破颈线,做多 70% 仓位。",
        "one_line_summary": "做多。",
    }
    context = {
        "data_freshness_summary": [
            {"source": "glassnode_onchain", "is_stale": True}
        ],
    }
    out, act = validator_stale_disclosure(master_output, context)
    assert act["validator_stale_disclosure_missing"] is True
    assert act["validator_stale_disclosure_needs_retry"] is True
    assert "stale_disclosure_missing_needs_retry" in (out.get("notes") or [])


def test_validator_stale_disclosure_skips_silent_cooldown_mode():
    """silent_cooldown 已最保守,不强制 stale 披露。"""
    from src.ai.validator import validator_stale_disclosure
    master_output = {
        "mode": "silent_cooldown",
        "narrative": "在 24h 冷却期。",
        "silent_reason": "in cooldown",
    }
    context = {
        "data_freshness_summary": [
            {"source": "glassnode_onchain", "is_stale": True}
        ],
    }
    out, act = validator_stale_disclosure(master_output, context)
    assert act["validator_stale_disclosure_missing"] is False


def test_validator_stale_disclosure_passes_when_no_stale_source():
    """所有源 fresh → 不强制披露关键词。"""
    from src.ai.validator import validator_stale_disclosure
    master_output = {
        "mode": "new_thesis",
        "narrative": "L1 趋势上行,做多。",
    }
    context = {
        "data_freshness_summary": [
            {"source": "glassnode_onchain", "is_stale": False}
        ],
    }
    out, act = validator_stale_disclosure(master_output, context)
    assert act["validator_stale_disclosure_missing"] is False


def test_full_validate_pipeline_aggregates_stale_retry():
    """validate_master_output 调用全 pipeline 时,stale_disclosure_needs_retry
    应聚合到 validator_needs_retry=True。"""
    from src.ai.validator import validate_master_output
    master_output = {
        "mode": "new_thesis",
        "narrative": "L1 上行做多,做多 70% 仓位。",  # 不含 stale 关键词
        "new_thesis": {
            "direction": "long",
            "entry_orders": [{"price": 50000, "size_pct": 50}],
            "break_conditions": ["breakA", "breakB", "breakC"],
            "stop_loss": {"price": 45000},
        },
    }
    context = {
        "l3_grade": "B",
        "data_freshness_summary": [
            {"source": "glassnode_onchain", "is_stale": True}
        ],
    }
    _, activations = validate_master_output(master_output, context)
    assert activations["validator_stale_disclosure_missing"] is True
    assert activations["validator_needs_retry"] is True
