"""Sprint B — /api/data_sources/freshness 端到端测试。

§Z 真 SQLite + 真 FastAPI TestClient + 真 FetchAttemptsDAO 写入,
verify API 返回 4 行 + 字段语义(success / failure / no_data / 中文徽章 /
last_success_at_bjt 在 failure 时回填)。
"""
from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.data.storage.connection import get_connection, init_db
from src.data.storage.dao import FetchAttemptsDAO


@pytest.fixture
def db_path():
    tmp = Path(tempfile.mkdtemp()) / "data_sources_freshness.db"
    init_db(db_path=tmp, verbose=False)
    return tmp


@pytest.fixture
def client(db_path):
    def _factory():
        return get_connection(db_path)
    app = create_app(conn_factory=_factory, pipeline_trigger_cooldown_sec=60.0)
    return TestClient(app)


def _seed(db_path: Path, **kwargs):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        FetchAttemptsDAO.record_attempt(conn, **kwargs)
        conn.commit()
    finally:
        conn.close()


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ============================================================
# 1. 空 DB:4 行 no_data
# ============================================================

def test_freshness_empty_db_returns_4_no_data_rows(client):
    r = client.get("/api/data_sources/freshness")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 4
    sources = [row["source"] for row in body]
    assert sources == [
        "binance_kline", "coinglass_derivatives",
        "glassnode_onchain", "fred_macro",
    ]
    for row in body:
        assert row["status"] == "no_data"
        assert row["last_attempt_at_utc"] is None
        assert row["last_success_at_utc"] is None
        assert row["failure_reason"] is None
        assert row["failure_reason_label"] is None


# ============================================================
# 2. display_name 中文标签
# ============================================================

def test_freshness_display_names_are_chinese(client):
    body = client.get("/api/data_sources/freshness").json()
    name_map = {r["source"]: r["display_name"] for r in body}
    assert name_map["binance_kline"] == "Binance K 线"
    assert name_map["coinglass_derivatives"] == "CoinGlass 衍生品"
    assert name_map["glassnode_onchain"] == "Glassnode 链上"
    assert name_map["fred_macro"] == "FRED 宏观"


# ============================================================
# 3. success 行字段
# ============================================================

def test_freshness_success_row_populates_all_fields(client, db_path):
    now = datetime.now(timezone.utc)
    _seed(
        db_path, source="binance_kline", status="success",
        rows_upserted=24, duration_ms=1234,
        attempted_at_utc=_iso(now - timedelta(minutes=12)),
    )
    body = client.get("/api/data_sources/freshness").json()
    row = next(r for r in body if r["source"] == "binance_kline")
    assert row["status"] == "success"
    assert row["rows_upserted"] == 24
    assert row["duration_ms"] == 1234
    assert row["last_attempt_at_utc"] is not None
    assert row["last_attempt_at_bjt"] is not None
    assert row["last_success_at_utc"] == row["last_attempt_at_utc"]
    assert row["last_success_at_bjt"] == row["last_attempt_at_bjt"]
    assert row["failure_reason"] is None
    assert row["failure_reason_label"] is None
    assert row["error_message"] is None
    assert 11 <= row["minutes_ago"] <= 13


# ============================================================
# 4. failure 行 + 中文徽章
# ============================================================

def test_freshness_failure_row_returns_chinese_label(client, db_path):
    now = datetime.now(timezone.utc)
    _seed(
        db_path, source="glassnode_onchain", status="failure",
        failure_reason="quota_exceeded",
        error_message='HTTP 403: 您的 glassnode 周期内配额已用尽',
        rows_upserted=0, duration_ms=8296,
        attempted_at_utc=_iso(now - timedelta(minutes=5)),
    )
    body = client.get("/api/data_sources/freshness").json()
    row = next(r for r in body if r["source"] == "glassnode_onchain")
    assert row["status"] == "failure"
    assert row["failure_reason"] == "quota_exceeded"
    assert row["failure_reason_label"] == "配额用尽"
    assert "配额已用尽" in row["error_message"]
    assert row["rows_upserted"] == 0
    assert row["duration_ms"] == 8296


def test_freshness_all_5_failure_reasons_have_chinese_labels(client, db_path):
    """5 个 failure_reason 桶都要映射到中文徽章。"""
    now = datetime.now(timezone.utc)
    cases = [
        ("quota_exceeded", "配额用尽"),
        ("network_error", "网络错误"),
        ("api_error", "API 错误"),
        ("parse_error", "数据格式错误"),
        ("unknown", "未知错误"),
    ]
    # 4 sources × 多种 reason 不重复;复用 4 个固定 source 测前 4 个,
    # 第 5 个(unknown)再用一遍 binance_kline 覆盖。
    sources_iter = iter([
        "binance_kline", "coinglass_derivatives",
        "glassnode_onchain", "fred_macro",
    ])
    for reason, _ in cases[:4]:
        src = next(sources_iter)
        _seed(
            db_path, source=src, status="failure",
            failure_reason=reason, error_message=f"{reason} stub",
            attempted_at_utc=_iso(now - timedelta(minutes=10)),
        )
    body = {r["source"]: r for r in client.get("/api/data_sources/freshness").json()}
    assert body["binance_kline"]["failure_reason_label"] == "配额用尽"
    assert body["coinglass_derivatives"]["failure_reason_label"] == "网络错误"
    assert body["glassnode_onchain"]["failure_reason_label"] == "API 错误"
    assert body["fred_macro"]["failure_reason_label"] == "数据格式错误"

    # unknown 单独 case:再写一行覆盖 binance_kline 的最新 attempt
    _seed(
        db_path, source="binance_kline", status="failure",
        failure_reason="unknown", error_message="weird thing",
        attempted_at_utc=_iso(now),
    )
    body2 = client.get("/api/data_sources/freshness").json()
    bk = next(r for r in body2 if r["source"] == "binance_kline")
    assert bk["failure_reason_label"] == "未知错误"


def test_freshness_new_failure_labels_are_granular(client, db_path):
    """403/404/timeout 等不能再统一显示成配额用尽。"""
    now = datetime.now(timezone.utc)
    cases = [
        ("glassnode_onchain", "permission_denied", "套餐不支持 / 权限不足"),
        ("coinglass_derivatives", "endpoint_not_found", "接口不存在 / 配置错误"),
        ("fred_macro", "timeout", "请求超时"),
    ]
    for source, reason, _label in cases:
        _seed(
            db_path, source=source, status="failure",
            failure_reason=reason, error_message=f"{reason} stub",
            attempted_at_utc=_iso(now),
        )
    body = {r["source"]: r for r in client.get("/api/data_sources/freshness").json()}
    for source, reason, label in cases:
        assert body[source]["failure_reason"] == reason
        assert body[source]["failure_reason_label"] == label
        assert body[source]["failure_reason_label"] != "配额用尽"


def test_freshness_partial_failure_label_when_rows_were_upserted(client, db_path):
    """部分成功的 Glassnode 采集显示部分异常,不再把整源打成配额用尽。"""
    now = datetime.now(timezone.utc)
    fresh_iso = _iso(now - timedelta(minutes=3))
    conn = sqlite3.connect(db_path)
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
            error_message="HTTP 429 on puell_multiple",
            rows_upserted=869,
            attempted_at_utc=_iso(now - timedelta(minutes=1)),
        )
        conn.commit()
    finally:
        conn.close()

    body = client.get("/api/data_sources/freshness").json()
    row = next(r for r in body if r["source"] == "glassnode_onchain")
    assert row["status"] == "partial"
    assert row["failure_reason"] == "quota_exceeded"
    assert row["failure_reason_label"] == "部分异常"
    assert row["display_label"] == "部分异常：Puell Multiple 429"
    assert row["main_failure_metric"] == "puell_multiple"
    assert row["main_failure_endpoint"] == "/v1/metrics/indicators/puell_multiple"
    assert row["main_failure_http_status"] == 429
    assert row["rows_upserted"] == 869


def test_glassnode_recovered_endpoint_returns_success_with_detail(
    monkeypatch, client, db_path,
):
    """health check 缓存显示失败 endpoint 已 ok → source 恢复 success。"""
    now = datetime.now(timezone.utc)
    fresh_iso = _iso(now - timedelta(minutes=3))
    conn = sqlite3.connect(db_path)
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
            error_message=(
                "Glassnode request failed: /v1/metrics/indicators/puell_multiple "
                "last error: HTTP 429"
            ),
            rows_upserted=869,
            attempted_at_utc=_iso(now - timedelta(minutes=10)),
        )
        conn.commit()
    finally:
        conn.close()

    from src.data import freshness as freshness_mod

    monkeypatch.setattr(
        freshness_mod,
        "_read_glassnode_health_cache",
        lambda: {
            "generated_at_utc": _iso(now - timedelta(minutes=1)),
            "checks": [
                {
                    "metric": "puell_multiple",
                    "endpoint": "/v1/metrics/indicators/puell_multiple",
                    "status": "ok",
                    "latest_value_present": True,
                }
            ],
        },
    )

    body = client.get("/api/data_sources/freshness").json()
    row = next(r for r in body if r["source"] == "glassnode_onchain")
    assert row["status"] == "success"
    assert row["recovered"] is True
    assert row["latest_success_after_failure"] is True
    assert row["display_label"] is None
    assert row["main_failure_metric"] == "puell_multiple"


# ============================================================
# 5. 失败时 last_success_at 回填
# ============================================================

def test_freshness_failure_falls_back_to_last_success(client, db_path):
    """current=failure,但历史 success 存在 → last_success_at_utc 指向那次。"""
    now = datetime.now(timezone.utc)
    # 昨天成功
    _seed(
        db_path, source="glassnode_onchain", status="success",
        rows_upserted=130,
        attempted_at_utc=_iso(now - timedelta(days=1)),
    )
    # 今天失败(更新 latest)
    _seed(
        db_path, source="glassnode_onchain", status="failure",
        failure_reason="quota_exceeded",
        error_message="HTTP 403 quota",
        attempted_at_utc=_iso(now - timedelta(minutes=2)),
    )
    body = client.get("/api/data_sources/freshness").json()
    row = next(r for r in body if r["source"] == "glassnode_onchain")
    assert row["status"] == "failure"
    assert row["last_attempt_at_utc"] is not None
    assert row["last_success_at_utc"] is not None
    assert row["last_attempt_at_utc"] != row["last_success_at_utc"]
    assert row["last_success_at_bjt"] is not None


def test_freshness_failure_with_no_historical_success_returns_none(
    client, db_path,
):
    now = datetime.now(timezone.utc)
    _seed(
        db_path, source="fred_macro", status="failure",
        failure_reason="api_error", error_message="HTTP 500",
        attempted_at_utc=_iso(now - timedelta(minutes=1)),
    )
    body = client.get("/api/data_sources/freshness").json()
    row = next(r for r in body if r["source"] == "fred_macro")
    assert row["status"] == "failure"
    assert row["last_success_at_utc"] is None
    assert row["last_success_at_bjt"] is None


# ============================================================
# 6. minutes_ago 计算粒度
# ============================================================

def test_freshness_minutes_ago_is_int(client, db_path):
    now = datetime.now(timezone.utc)
    _seed(
        db_path, source="binance_kline", status="success",
        rows_upserted=24,
        attempted_at_utc=_iso(now - timedelta(minutes=37)),
    )
    body = client.get("/api/data_sources/freshness").json()
    row = next(r for r in body if r["source"] == "binance_kline")
    assert isinstance(row["minutes_ago"], int)
    assert 35 <= row["minutes_ago"] <= 39


# ============================================================
# 7. 同 source 多行 → 取最新
# ============================================================

def test_freshness_picks_latest_attempt_per_source(client, db_path):
    now = datetime.now(timezone.utc)
    _seed(
        db_path, source="coinglass_derivatives", status="success",
        rows_upserted=10,
        attempted_at_utc=_iso(now - timedelta(hours=3)),
    )
    _seed(
        db_path, source="coinglass_derivatives", status="failure",
        failure_reason="network_error",
        attempted_at_utc=_iso(now - timedelta(minutes=8)),
    )
    body = client.get("/api/data_sources/freshness").json()
    row = next(r for r in body if r["source"] == "coinglass_derivatives")
    assert row["status"] == "failure"
    assert row["failure_reason"] == "network_error"
    assert row["minutes_ago"] is not None and row["minutes_ago"] < 30
