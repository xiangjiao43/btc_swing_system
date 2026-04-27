"""tests/test_derivatives_extras_merge.py — Sprint 2.6-F.4。

Sprint 2.6-F.3 后服务器实测发现:`backfill --only derivatives` 报告
upserted=7,但 `SELECT COUNT(*) FROM derivatives_snapshots
WHERE full_data_json LIKE '%funding_rate_aggregated%'` 返回 0。

根因:DerivativesDAO.upsert_batch 的 ON CONFLICT 用了
`full_data_json = COALESCE(excluded.full_data_json, existing.full_data_json)`
COALESCE 取第一个非 NULL → 后续 batch 的 extras **覆盖**前面 batch 的 extras。

backfill 的批次顺序:
  funding_rate → funding_rate_aggregated → OI → long_short_ratio (alias 写 extras)
  → liquidation

funding_rate_aggregated 在 batch 2 写入 extras,在 batch 4 (LSR 别名) 被覆盖
→ 表现为生产 DB 看不到这个字段。

修复:full_data_json 改为 json_patch(existing, excluded) 真正合并 keys。

本测试覆盖之前 F.1 / F.3 的 mock-only 测试漏掉的关键断言:
**端到端 + DB 行数 + JSON keys 同时存在**,而不是光看 .called。
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.data.storage.connection import init_db
from src.data.storage.dao import DerivativesDAO, DerivativeMetric


@pytest.fixture
def db_conn():
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    init_db(db_path=tmp, verbose=False)
    conn = sqlite3.connect(tmp)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


# ============================================================
# Core merge behavior
# ============================================================

def test_full_data_json_merges_keys_across_batches(db_conn):
    """两个 batch 各写不同的 extras key,合并后两个 key 都在。"""
    ts = "2026-04-27T00:00:00Z"
    DerivativesDAO.upsert_batch(db_conn, [
        DerivativeMetric(ts, "funding_rate_aggregated", 0.0002),
    ])
    DerivativesDAO.upsert_batch(db_conn, [
        DerivativeMetric(ts, "long_short_ratio_top", 1.5),
    ])
    db_conn.commit()

    row = db_conn.execute(
        "SELECT full_data_json FROM derivatives_snapshots WHERE captured_at_utc=?",
        (ts,),
    ).fetchone()
    extras = json.loads(row["full_data_json"])
    assert "funding_rate_aggregated" in extras
    assert "long_short_ratio_top" in extras
    assert extras["funding_rate_aggregated"] == 0.0002
    assert extras["long_short_ratio_top"] == 1.5


def test_full_data_json_later_batch_does_not_overwrite_earlier(db_conn):
    """监管回归测试:后一个 batch 写入 extras 不能丢前一个 batch 的 keys。"""
    ts = "2026-04-27T00:00:00Z"
    # 模拟 backfill 的 5 batch 顺序
    DerivativesDAO.upsert_batch(db_conn, [DerivativeMetric(ts, "funding_rate", 0.0001)])
    DerivativesDAO.upsert_batch(db_conn, [
        DerivativeMetric(ts, "funding_rate_aggregated", 0.0002),
    ])
    DerivativesDAO.upsert_batch(db_conn, [DerivativeMetric(ts, "open_interest", 58e9)])
    DerivativesDAO.upsert_batch(db_conn, [
        DerivativeMetric(ts, "long_short_ratio_top", 1.5),
        DerivativeMetric(ts, "long_short_ratio_global", 1.4),
    ])
    DerivativesDAO.upsert_batch(db_conn, [
        DerivativeMetric(ts, "liquidation_long", 1000),
        DerivativeMetric(ts, "liquidation_short", 500),
        DerivativeMetric(ts, "liquidation_total", 1500),
    ])
    db_conn.commit()

    # SQL-level row count check
    n = db_conn.execute(
        "SELECT COUNT(*) FROM derivatives_snapshots "
        "WHERE full_data_json LIKE '%funding_rate_aggregated%'"
    ).fetchone()[0]
    assert n == 1, (
        f"Expected exactly 1 row with funding_rate_aggregated in extras, "
        f"got {n}. The earlier-batch extras was overwritten by a later batch."
    )

    # All wide cols + all extras present
    row = db_conn.execute(
        "SELECT * FROM derivatives_snapshots WHERE captured_at_utc=?", (ts,)
    ).fetchone()
    assert row["funding_rate"] == 0.0001
    assert row["open_interest"] == 58e9
    assert row["long_short_ratio"] == 1.5  # alias 归一
    assert row["liquidation_total"] == 1500
    extras = json.loads(row["full_data_json"])
    assert extras.get("funding_rate_aggregated") == 0.0002
    assert "long_short_ratio_top" in extras
    assert "long_short_ratio_global" in extras


def test_full_data_json_handles_null_existing(db_conn):
    """initial INSERT(existing 是 NULL)→ extras 直接写入。"""
    ts = "2026-04-27T00:00:00Z"
    DerivativesDAO.upsert_batch(db_conn, [
        DerivativeMetric(ts, "funding_rate_aggregated", 0.0002),
    ])
    db_conn.commit()
    row = db_conn.execute(
        "SELECT full_data_json FROM derivatives_snapshots WHERE captured_at_utc=?",
        (ts,),
    ).fetchone()
    assert json.loads(row["full_data_json"]) == {"funding_rate_aggregated": 0.0002}


def test_full_data_json_handles_null_excluded(db_conn):
    """ON CONFLICT 时新 batch 没 extras → 保留旧 extras。"""
    ts = "2026-04-27T00:00:00Z"
    DerivativesDAO.upsert_batch(db_conn, [
        DerivativeMetric(ts, "funding_rate_aggregated", 0.0002),
    ])
    DerivativesDAO.upsert_batch(db_conn, [
        DerivativeMetric(ts, "funding_rate", 0.0001),  # 仅 wide col,无 extras
    ])
    db_conn.commit()
    row = db_conn.execute(
        "SELECT full_data_json FROM derivatives_snapshots WHERE captured_at_utc=?",
        (ts,),
    ).fetchone()
    extras = json.loads(row["full_data_json"])
    assert extras.get("funding_rate_aggregated") == 0.0002


def test_full_data_json_same_key_overwrite_within_key(db_conn):
    """同一 extras key 多次写入 → 取最后一次值(json_patch 覆盖单 key 的语义)。"""
    ts = "2026-04-27T00:00:00Z"
    DerivativesDAO.upsert_batch(db_conn, [
        DerivativeMetric(ts, "funding_rate_aggregated", 0.0002),
    ])
    DerivativesDAO.upsert_batch(db_conn, [
        DerivativeMetric(ts, "funding_rate_aggregated", 0.0005),  # 同 key 新值
    ])
    db_conn.commit()
    row = db_conn.execute(
        "SELECT full_data_json FROM derivatives_snapshots WHERE captured_at_utc=?",
        (ts,),
    ).fetchone()
    extras = json.loads(row["full_data_json"])
    assert extras["funding_rate_aggregated"] == 0.0005


# ============================================================
# Real backfill flow simulation (mock fetch, real DAO + real DB)
# ============================================================

def test_real_backfill_flow_keeps_funding_rate_aggregated(db_conn):
    """模拟真实 backfill 顺序,断言 DB 行数 > 0(F.3 漏掉的关键断言)。

    用真 DAO + 真 SQLite,只 mock fetch 返回。这是 F.1 / F.3 mock-only
    测试漏掉的端到端检验:.called 为 True 不等于数据真的进 DB。
    """
    ts_list = [f"2026-04-{d:02d}T00:00:00Z" for d in (21, 22, 23, 24, 25, 26, 27)]

    # batch 1: funding_rate
    DerivativesDAO.upsert_batch(db_conn, [
        DerivativeMetric(t, "funding_rate", 0.0001 * (i+1)) for i, t in enumerate(ts_list)
    ])
    # batch 2: funding_rate_aggregated(就是 F.3 添加的那批)
    DerivativesDAO.upsert_batch(db_conn, [
        DerivativeMetric(t, "funding_rate_aggregated", 0.0002 * (i+1))
        for i, t in enumerate(ts_list)
    ])
    # batch 3: open_interest
    DerivativesDAO.upsert_batch(db_conn, [
        DerivativeMetric(t, "open_interest", 5e10 + i) for i, t in enumerate(ts_list)
    ])
    # batch 4: long_short_ratio (用 alias name 触发 extras 写入)
    DerivativesDAO.upsert_batch(db_conn, [
        DerivativeMetric(t, "long_short_ratio_top", 1.0 + i * 0.1)
        for i, t in enumerate(ts_list)
    ])
    # batch 5: liquidation
    DerivativesDAO.upsert_batch(db_conn, [
        DerivativeMetric(t, "liquidation_total", 1000 * (i+1))
        for i, t in enumerate(ts_list)
    ])
    db_conn.commit()

    n = db_conn.execute(
        "SELECT COUNT(*) FROM derivatives_snapshots "
        "WHERE full_data_json LIKE '%funding_rate_aggregated%'"
    ).fetchone()[0]
    assert n == 7, (
        f"Expected 7 rows with funding_rate_aggregated in extras after full "
        f"backfill flow, got {n}. This is the production bug: extras "
        f"overwritten by a later batch's extras."
    )
