"""tests/test_lth_sth_realized_price_e2e.py — Sprint 2.6-I §Z 端到端 DB 行数验证。

Sprint 2.6-F.1 / F.3 教训:mock 端到端 fetch+wiring,断言 .called=True 不够 —
.called 真的不等于 DB 真的有数据(中间会 silently 丢失,例如 DAO 字段不匹配 / JSON
overwrite / schema 缺列)。

本测试用 mock HTTP(让 _request 返回 fixture)+ 真 SQLite + 真 OnchainDAO,
跑 backfill_onchain 后 SELECT COUNT(*) 断言:
  - lth_realized_price 行数 > 0
  - sth_realized_price 行数 > 0
  - 加权值在合理 BTC 价格区间(20000-200000)
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.data.storage.connection import get_connection, init_db


@pytest.fixture
def db_conn():
    tmp = Path(tempfile.mkdtemp()) / "e2e.db"
    init_db(db_path=tmp, verbose=False)
    conn = get_connection(tmp)
    yield conn
    conn.close()


def _make_breakdown_response(timestamps: list[str], buckets_per_ts: dict[str, dict]):
    """构造 Glassnode breakdown endpoint 的 raw response 形状。

    response 形如 [{"t": <unix>, "o": {bucket: value, ...}}, ...]
    """
    import datetime as dt
    out = []
    for ts in timestamps:
        # Parse ISO Z to unix
        d = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        out.append({
            "t": int(d.timestamp()),
            "o": buckets_per_ts[ts],
        })
    return {"data": out}  # _unwrap_data picks out "data" key


def test_e2e_backfill_writes_lth_sth_realized_price_rows(db_conn):
    """端到端:mock HTTP → backfill_onchain → SQL COUNT > 0 + 数值在合理范围。"""
    timestamps = [
        "2026-04-21T00:00:00Z",
        "2026-04-22T00:00:00Z",
        "2026-04-23T00:00:00Z",
    ]
    # 各 timestamp 的桶数据(price_realized + supply 必须 key 一致)
    price_buckets = {
        ts: {
            # STH 桶
            "24h":     65000.0 + i * 100,
            "1d_1w":   68000.0 + i * 100,
            "1w_1m":   70000.0 + i * 100,
            "1m_3m":   72000.0 + i * 100,
            "3m_6m":   75000.0 + i * 100,
            # LTH 桶
            "6m_12m":  60000.0 + i * 100,
            "1y_2y":   45000.0 + i * 100,
            "2y_3y":   30000.0 + i * 100,
            "3y_5y":   18000.0 + i * 100,
            "5y_7y":   10000.0 + i * 100,
            "7y_10y":   5000.0 + i * 100,
            "more_10y": 2000.0 + i * 100,
            "aggregated": 50000.0,  # 应被忽略
        }
        for i, ts in enumerate(timestamps)
    }
    supply_buckets = {
        ts: {
            "24h":     5e3,
            "1d_1w":   2e4,
            "1w_1m":   5e4,
            "1m_3m":   2e5,
            "3m_6m":   3e5,
            "6m_12m":  4e5,
            "1y_2y":   7e5,
            "2y_3y":   5e5,
            "3y_5y":   3e5,
            "5y_7y":   2e5,
            "7y_10y":  1e5,
            "more_10y":1e5,
            "aggregated": 1e7,
        }
        for ts in timestamps
    }

    price_resp = _make_breakdown_response(timestamps, price_buckets)
    supply_resp = _make_breakdown_response(timestamps, supply_buckets)

    def fake_request(self, method, path, **kw):
        if "price_realized_usd_by_age" in path:
            return price_resp
        if "supply_by_age" in path:
            return supply_resp
        # other endpoints (mvrv etc) → return empty so backfill skips
        return {"data": []}

    with patch(
        "src.data.collectors.glassnode.GlassnodeCollector._request",
        new=fake_request,
    ), patch.dict(
        "os.environ", {"GLASSNODE_API_KEY": "test-key"}
    ):
        # Need to also avoid base_url validation in __init__
        from scripts.backfill_data import backfill_onchain
        backfill_onchain(db_conn, days=7, dry_run=False)

    # ---- DB-level assertions ----
    cur = db_conn.execute(
        "SELECT COUNT(*) FROM onchain_metrics WHERE metric_name=?",
        ("lth_realized_price",),
    )
    n_lth = cur.fetchone()[0]
    cur = db_conn.execute(
        "SELECT COUNT(*) FROM onchain_metrics WHERE metric_name=?",
        ("sth_realized_price",),
    )
    n_sth = cur.fetchone()[0]
    assert n_lth >= 3, (
        f"Expected >= 3 lth_realized_price rows, got {n_lth}. "
        f"This is the §Z guard the F.1/F.3 mock-only tests didn't have."
    )
    assert n_sth >= 3, f"Expected >= 3 sth_realized_price rows, got {n_sth}"

    # ---- Value sanity: aggregated weighted average must be in BTC price range ----
    cur = db_conn.execute(
        "SELECT value FROM onchain_metrics WHERE metric_name=? ORDER BY captured_at_utc",
        ("lth_realized_price",),
    )
    lth_values = [r[0] for r in cur.fetchall()]
    cur = db_conn.execute(
        "SELECT value FROM onchain_metrics WHERE metric_name=? ORDER BY captured_at_utc",
        ("sth_realized_price",),
    )
    sth_values = [r[0] for r in cur.fetchall()]

    for v in lth_values:
        assert 5000 < v < 100000, f"LTH realized price out of sane range: {v}"
    for v in sth_values:
        assert 50000 < v < 100000, f"STH realized price out of sane range: {v}"

    # LTH cohorts skew older / cheaper; STH skews newer / closer to spot.
    # Given fixture, STH avg should be > LTH avg.
    avg_lth = sum(lth_values) / len(lth_values)
    avg_sth = sum(sth_values) / len(sth_values)
    assert avg_sth > avg_lth, (
        f"Sanity: STH cost basis ({avg_sth}) should exceed LTH ({avg_lth})"
    )


def test_e2e_backfill_handles_missing_breakdown_endpoint(db_conn):
    """如果 /breakdowns/* HTTP 失败 → backfill 跳过 LTH/STH 但其他 metric 不受影响。"""
    def fake_request(self, method, path, **kw):
        if "by_age" in path:
            raise RuntimeError("simulated upstream 500 on breakdown endpoint")
        return {"data": []}

    with patch(
        "src.data.collectors.glassnode.GlassnodeCollector._request",
        new=fake_request,
    ), patch.dict(
        "os.environ", {"GLASSNODE_API_KEY": "test-key"}
    ):
        from scripts.backfill_data import backfill_onchain
        # 不应抛 — backfill 单 metric 失败不影响其他
        backfill_onchain(db_conn, days=7, dry_run=False)

    # LTH/STH 0 行(预期)
    cur = db_conn.execute(
        "SELECT COUNT(*) FROM onchain_metrics WHERE metric_name IN (?, ?)",
        ("lth_realized_price", "sth_realized_price"),
    )
    assert cur.fetchone()[0] == 0
