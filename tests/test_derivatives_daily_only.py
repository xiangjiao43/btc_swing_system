"""tests/test_derivatives_daily_only.py — Sprint 1.5f-revised DAO timestamp guard。

§Z 真 init_db + 真 DerivativesDAO.upsert_batch:
- 非 daily timestamp(含 hourly)→ logger.warning + 跳过,DB 不写
- daily timestamp(T00:00:00Z)→ 正常写入
- 混 batch:只 daily 进 DB,hourly 被拒
- 清污后 get_all_metrics 平均间隔 ≈ 24h
"""

from __future__ import annotations

import logging
import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.data.storage.connection import init_db
from src.data.storage.dao import DerivativeMetric, DerivativesDAO


@pytest.fixture
def db_path():
    tmp = Path(tempfile.mkdtemp()) / "deriv_daily.db"
    init_db(db_path=tmp, verbose=False)
    return tmp


def test_upsert_rejects_hourly_timestamp(db_path, caplog):
    """hourly ts(T03:00:00Z)→ 被拒,DB 没数据,logger 出 warning。"""
    conn = sqlite3.connect(db_path)
    try:
        with caplog.at_level(logging.WARNING, logger="src.data.storage.dao"):
            DerivativesDAO.upsert_batch(conn, [
                DerivativeMetric(
                    timestamp="2026-04-29T03:00:00Z",
                    metric_name="funding_rate", metric_value=0.0001,
                ),
            ])
            conn.commit()
        n = conn.execute(
            "SELECT COUNT(*) FROM derivatives_snapshots"
        ).fetchone()[0]
        assert n == 0
        # warning 含 "non-daily ts"
        assert any("non-daily ts" in r.message for r in caplog.records)
    finally:
        conn.close()


def test_upsert_accepts_daily_timestamp(db_path):
    """daily ts(T00:00:00Z)→ 正常入库。"""
    conn = sqlite3.connect(db_path)
    try:
        DerivativesDAO.upsert_batch(conn, [
            DerivativeMetric(
                timestamp="2026-04-29T00:00:00Z",
                metric_name="funding_rate", metric_value=0.0001,
            ),
        ])
        conn.commit()
        rows = conn.execute(
            "SELECT captured_at_utc, funding_rate "
            "FROM derivatives_snapshots"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "2026-04-29T00:00:00Z"
        assert rows[0][1] == 0.0001
    finally:
        conn.close()


def test_upsert_mixed_batch_only_daily_kept(db_path):
    """混合 batch(2 daily + 3 hourly)→ DB 只有 2 行 daily。"""
    conn = sqlite3.connect(db_path)
    try:
        DerivativesDAO.upsert_batch(conn, [
            # 3 daily rows (different days to avoid PK collision)
            DerivativeMetric(timestamp="2026-04-27T00:00:00Z",
                             metric_name="funding_rate", metric_value=0.0001),
            DerivativeMetric(timestamp="2026-04-28T00:00:00Z",
                             metric_name="funding_rate", metric_value=0.0002),
            DerivativeMetric(timestamp="2026-04-29T00:00:00Z",
                             metric_name="funding_rate", metric_value=0.0003),
            # 3 hourly rows
            DerivativeMetric(timestamp="2026-04-29T01:00:00Z",
                             metric_name="funding_rate", metric_value=99.0),
            DerivativeMetric(timestamp="2026-04-29T02:00:00Z",
                             metric_name="funding_rate", metric_value=99.0),
            DerivativeMetric(timestamp="2026-04-29T15:30:00Z",
                             metric_name="funding_rate", metric_value=99.0),
        ])
        conn.commit()
        ts_in_db = sorted(
            r[0] for r in conn.execute(
                "SELECT captured_at_utc FROM derivatives_snapshots"
            ).fetchall()
        )
        assert ts_in_db == [
            "2026-04-27T00:00:00Z",
            "2026-04-28T00:00:00Z",
            "2026-04-29T00:00:00Z",
        ]
        # hourly 假数据 99.0 不应进 DB
        for ts, fr in conn.execute(
            "SELECT captured_at_utc, funding_rate FROM derivatives_snapshots"
        ).fetchall():
            assert fr != 99.0, f"hourly polluted ts {ts} got through guard"
    finally:
        conn.close()


def test_get_all_metrics_after_cleanup_is_pure_daily(db_path):
    """模拟清污后场景:DB 只有 daily;get_all_metrics 平均间隔 ≈ 24h。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # get_all_metrics 内部用 dict(raw) 需要 Row
    try:
        # 5 个 daily 行
        for d in (25, 26, 27, 28, 29):
            DerivativesDAO.upsert_batch(conn, [
                DerivativeMetric(
                    timestamp=f"2026-04-{d:02d}T00:00:00Z",
                    metric_name="funding_rate",
                    metric_value=0.0001 * d,
                ),
            ])
        conn.commit()

        m = DerivativesDAO.get_all_metrics(conn, lookback_days=180)
        assert "funding_rate" in m
        s = m["funding_rate"]
        assert len(s) == 5
        # 平均间隔
        if len(s) > 1:
            span_h = (s.index[-1] - s.index[0]).total_seconds() / 3600
            avg_h = span_h / (len(s) - 1)
            assert 23.5 <= avg_h <= 24.5, (
                f"expected ~24h cadence, got {avg_h}h"
            )
    finally:
        conn.close()
