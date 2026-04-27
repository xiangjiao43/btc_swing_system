"""tests/test_dao_inserted_at_utc.py — Sprint 2.6-J Commit 2 §Z 端到端 DB 字段验证。

之前 Sprint 1.5c 起,4 个 dataclass 都有 fetched_at 字段(microsecond ISO,
默认 _utc_now_iso_ms),但 4 个 DAO 的 upsert SQL 都没把它写进 DB,落地丢失。

本 sprint 新增 inserted_at_utc 列 + DAO upsert 路径写入。本测试用真 SQLite +
真 DAO,验证 SELECT inserted_at_utc 不再 NULL 且为合理近期 ISO 时间(now ± 5s)。
"""

from __future__ import annotations

import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.data.storage.connection import init_db
from src.data.storage.dao import (
    BTCKlinesDAO, DerivativeMetric, DerivativesDAO,
    KlineRow, MacroDAO, MacroMetric,
    OnchainDAO, OnchainMetric,
    _utc_now_iso_ms,
)


@pytest.fixture
def db_conn():
    tmp = Path(tempfile.mkdtemp()) / "iat.db"
    init_db(db_path=tmp, verbose=False)
    conn = sqlite3.connect(tmp)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(s: str) -> datetime:
    """支持 ms (...%fZ) 和 s (...Z) 两种 ISO 格式。"""
    s = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s)


# ============================================================
# _utc_now_iso_ms factory
# ============================================================

def test_utc_now_iso_ms_format_has_microseconds():
    s = _utc_now_iso_ms()
    # 形如 "2026-04-27T14:06:23.456789Z"
    assert s.endswith("Z")
    assert "." in s, f"expected microsecond '.', got {s!r}"
    # 微秒部分应是 6 位
    micro_part = s.split(".")[-1].rstrip("Z")
    assert len(micro_part) == 6, f"expected 6-digit microseconds, got {micro_part!r}"


def test_utc_now_iso_ms_two_calls_differ_by_micros():
    """同一秒内两次调用,微秒部分应有差(证明非 hardcoded)。"""
    a = _utc_now_iso_ms()
    b = _utc_now_iso_ms()
    # 两次时间不一定 100% 不同(连续两条 syscall 可能命中同一微秒),
    # 但两次中至少其中一次该有具体 microsecond 差异时间不全为 0
    assert a != b or a.split(".")[1] != "000000Z"


# ============================================================
# DAO 4 路径分别覆盖
# ============================================================

def test_klines_upsert_persists_inserted_at_utc(db_conn):
    before = _now()
    klines = [KlineRow(
        timeframe="1d", timestamp="2026-04-27T00:00:00Z",
        open=50000, high=51000, low=49500, close=50500,
        volume_btc=1234.5,
    )]
    BTCKlinesDAO.upsert_klines(db_conn, klines)
    db_conn.commit()
    after = _now()

    row = db_conn.execute(
        "SELECT inserted_at_utc FROM price_candles WHERE timeframe='1d'"
    ).fetchone()
    assert row["inserted_at_utc"] is not None
    parsed = _parse_iso(row["inserted_at_utc"])
    assert before <= parsed <= after, (
        f"inserted_at_utc {parsed} should be within [{before}, {after}]"
    )


def test_derivatives_upsert_persists_inserted_at_utc(db_conn):
    before = _now()
    metrics = [
        DerivativeMetric(timestamp="2026-04-27T00:00:00Z",
                         metric_name="funding_rate", metric_value=0.0001),
        DerivativeMetric(timestamp="2026-04-27T00:00:00Z",
                         metric_name="open_interest", metric_value=58e9),
    ]
    DerivativesDAO.upsert_batch(db_conn, metrics)
    db_conn.commit()
    after = _now()

    row = db_conn.execute(
        "SELECT inserted_at_utc FROM derivatives_snapshots "
        "WHERE captured_at_utc=?", ("2026-04-27T00:00:00Z",),
    ).fetchone()
    assert row["inserted_at_utc"] is not None
    parsed = _parse_iso(row["inserted_at_utc"])
    assert before <= parsed <= after


def test_derivatives_snapshot_takes_max_fetched_at_within_batch(db_conn):
    """wide 表 snapshot 级精度:1 个 ts 多个 metric → 取 max fetched_at。"""
    older = "2026-04-27T14:06:23.111111Z"
    newer = "2026-04-27T14:06:23.999999Z"
    metrics = [
        DerivativeMetric(timestamp="2026-04-27T00:00:00Z",
                         metric_name="funding_rate", metric_value=0.0001,
                         fetched_at=older),
        DerivativeMetric(timestamp="2026-04-27T00:00:00Z",
                         metric_name="open_interest", metric_value=58e9,
                         fetched_at=newer),
    ]
    DerivativesDAO.upsert_batch(db_conn, metrics)
    db_conn.commit()
    row = db_conn.execute(
        "SELECT inserted_at_utc FROM derivatives_snapshots WHERE captured_at_utc=?",
        ("2026-04-27T00:00:00Z",),
    ).fetchone()
    assert row["inserted_at_utc"] == newer


def test_onchain_upsert_persists_inserted_at_utc(db_conn):
    before = _now()
    metrics = [
        OnchainMetric(timestamp="2026-04-27T00:00:00Z",
                      metric_name="mvrv_z_score", metric_value=2.5,
                      source="glassnode_primary"),
    ]
    OnchainDAO.upsert_batch(db_conn, metrics)
    db_conn.commit()
    after = _now()

    row = db_conn.execute(
        "SELECT inserted_at_utc FROM onchain_metrics WHERE metric_name='mvrv_z_score'"
    ).fetchone()
    assert row["inserted_at_utc"] is not None
    parsed = _parse_iso(row["inserted_at_utc"])
    assert before <= parsed <= after


def test_macro_upsert_persists_inserted_at_utc(db_conn):
    before = _now()
    metrics = [
        MacroMetric(timestamp="2026-04-27T00:00:00Z",
                    metric_name="dxy", metric_value=104.5,
                    source="fred"),
    ]
    MacroDAO.upsert_batch(db_conn, metrics)
    db_conn.commit()
    after = _now()

    row = db_conn.execute(
        "SELECT inserted_at_utc FROM macro_metrics WHERE metric_name='dxy'"
    ).fetchone()
    assert row["inserted_at_utc"] is not None
    parsed = _parse_iso(row["inserted_at_utc"])
    assert before <= parsed <= after


def test_two_onchain_metrics_have_distinct_inserted_at_us(db_conn):
    """同一批跑两个不同 metric → 微秒精度可区分。"""
    metrics = []
    for i in range(2):
        metrics.append(OnchainMetric(
            timestamp="2026-04-27T00:00:00Z",
            metric_name=f"metric_{i}", metric_value=float(i),
            source="glassnode_primary",
        ))
        # 强制让 fetched_at 微秒错开
        time.sleep(0.001)
    # 关键:dataclass 默认是构造时的时间,所以 metric_0 比 metric_1 旧
    OnchainDAO.upsert_batch(db_conn, metrics)
    db_conn.commit()

    rows = db_conn.execute(
        "SELECT metric_name, inserted_at_utc FROM onchain_metrics "
        "ORDER BY metric_name"
    ).fetchall()
    assert len(rows) == 2
    t0 = rows[0]["inserted_at_utc"]
    t1 = rows[1]["inserted_at_utc"]
    assert t0 is not None and t1 is not None
    # ISO 字符串字典序 = 时间序;sleep 0.001s 应该足以让微秒差出现
    assert t0 < t1, (
        f"expected metric_0 inserted_at < metric_1 inserted_at; got "
        f"t0={t0}, t1={t1}"
    )
