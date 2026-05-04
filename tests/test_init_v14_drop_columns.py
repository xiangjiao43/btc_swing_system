"""tests/test_init_v14_drop_columns.py — Sprint 1.10-K-B commit 3 单测。

覆盖 migration 015:strategy_runs.observation_category + cold_start 删列。

5 个测试:
1. 新 sqlite(≥ 3.35.0)走原生 ALTER … DROP COLUMN
2. 老 sqlite(< 3.35.0)mock → 走 CREATE TABLE 复制法
3. 幂等(列已不存在 → no_op,不抛异常)
4. 数据完整性(其他列 + 行数全保留)
5. 索引完整性(strategy_runs 8 个 idx_runs_* 全保留)
"""
from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest

from scripts.init_v14_tables import (
    _drop_column_or_recreate,
    _supports_native_drop_column,
    drop_obsolete_columns,
)


def _make_conn_with_schema() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    with open("src/data/storage/schema.sql", encoding="utf-8") as f:
        c.executescript(f.read())
    return c


def _insert_sample_run(conn: sqlite3.Connection, run_id: str = "r_test_1") -> None:
    """插入一行 strategy_run 含两列(observation_category / cold_start)赋值。"""
    conn.execute(
        "INSERT INTO strategy_runs ("
        "  run_id, generated_at_utc, generated_at_bjt,"
        "  action_state, full_state_json,"
        "  observation_category, cold_start"
        ") VALUES (?, ?, ?, ?, ?, ?, ?)",
        (run_id, "2026-04-24T07:00:00Z", "2026-04-24T15:00:00",
         "FLAT", "{}", "neutral", 1),
    )
    conn.commit()


# ============================================================
# 1. 新 sqlite(≥ 3.35.0):原生 ALTER DROP COLUMN
# ============================================================

def test_native_alter_drops_column_when_sqlite_supports():
    """本地 sqlite 3.50.4 + 服务器 3.45.1 都支持原生 DROP COLUMN。"""
    if not _supports_native_drop_column():
        pytest.skip("local sqlite < 3.35.0; covered by mock test below")
    conn = _make_conn_with_schema()
    _insert_sample_run(conn)
    res = _drop_column_or_recreate(conn, "strategy_runs", "observation_category")
    assert res == "native_alter"
    cols = [r[1] for r in conn.execute("PRAGMA table_info(strategy_runs)").fetchall()]
    assert "observation_category" not in cols
    # cold_start 还在(只删一列)
    assert "cold_start" in cols
    conn.close()


# ============================================================
# 2. 老 sqlite mock(< 3.35.0):CREATE TABLE 复制法
# ============================================================

def test_recreate_path_when_sqlite_too_old():
    """mock sqlite_version_info=(3, 30, 0) → CREATE TABLE 复制法。"""
    conn = _make_conn_with_schema()
    _insert_sample_run(conn, run_id="r_recreate_1")
    _insert_sample_run(conn, run_id="r_recreate_2")
    with patch("scripts.init_v14_tables.sqlite3.sqlite_version_info", (3, 30, 0)):
        res = _drop_column_or_recreate(conn, "strategy_runs", "cold_start")
    assert res == "recreate"
    cols = [r[1] for r in conn.execute("PRAGMA table_info(strategy_runs)").fetchall()]
    assert "cold_start" not in cols
    # 数据保留
    rows = conn.execute("SELECT run_id FROM strategy_runs ORDER BY run_id").fetchall()
    assert [r[0] for r in rows] == ["r_recreate_1", "r_recreate_2"]
    conn.close()


# ============================================================
# 3. 幂等(列已不存在 → no_op)
# ============================================================

def test_idempotent_when_column_already_dropped():
    """列不存在 → no_op,不抛异常。"""
    conn = _make_conn_with_schema()
    # 第一次 drop
    res1 = _drop_column_or_recreate(conn, "strategy_runs", "observation_category")
    assert res1 in ("native_alter", "recreate")
    # 第二次 drop(已不存在)
    res2 = _drop_column_or_recreate(conn, "strategy_runs", "observation_category")
    assert res2 == "no_op"
    conn.close()


def test_drop_obsolete_columns_idempotent():
    """drop_obsolete_columns 第二次跑不抛、所有列均 no_op。"""
    conn = _make_conn_with_schema()
    res1 = drop_obsolete_columns(conn)
    # 第一次:两列都 drop
    assert res1["strategy_runs.observation_category"] in ("native_alter", "recreate")
    assert res1["strategy_runs.cold_start"] in ("native_alter", "recreate")
    # 第二次:两列都 no_op
    res2 = drop_obsolete_columns(conn)
    assert res2["strategy_runs.observation_category"] == "no_op"
    assert res2["strategy_runs.cold_start"] == "no_op"
    conn.close()


# ============================================================
# 4. 数据完整性(其他列 + 行数全保留)
# ============================================================

def test_data_integrity_preserved_after_drop():
    """drop 后:run_id / generated_at_utc / action_state / full_state_json 全保留。"""
    conn = _make_conn_with_schema()
    # 插 3 行
    for i in range(3):
        conn.execute(
            "INSERT INTO strategy_runs ("
            "  run_id, generated_at_utc, generated_at_bjt,"
            "  action_state, full_state_json,"
            "  observation_category, cold_start, btc_price_usd"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (f"r_{i}", f"2026-04-24T0{i}:00:00Z", f"2026-04-24T1{i}:00:00",
             "FLAT", '{"key": "value"}', "neutral", i, 80000.0 + i * 100),
        )
    conn.commit()

    drop_obsolete_columns(conn)

    rows = conn.execute(
        "SELECT run_id, generated_at_utc, action_state, full_state_json, btc_price_usd "
        "FROM strategy_runs ORDER BY run_id"
    ).fetchall()
    assert len(rows) == 3
    assert rows[0][0] == "r_0"
    assert rows[2][0] == "r_2"
    assert rows[1][2] == "FLAT"
    assert rows[1][3] == '{"key": "value"}'
    assert rows[2][4] == pytest.approx(80200.0)
    # 两列删了
    cols = [r[1] for r in conn.execute("PRAGMA table_info(strategy_runs)").fetchall()]
    assert "observation_category" not in cols
    assert "cold_start" not in cols
    conn.close()


# ============================================================
# 5. 索引完整性(strategy_runs 8 个 idx_runs_* 保留)
# ============================================================

def test_indexes_preserved_after_drop_native_path():
    """新 sqlite 原生 DROP COLUMN 不影响其他列上的索引。"""
    if not _supports_native_drop_column():
        pytest.skip("local sqlite < 3.35.0")
    conn = _make_conn_with_schema()
    indexes_before = sorted(
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='index' AND tbl_name='strategy_runs' AND sql IS NOT NULL"
        ).fetchall()
    )
    drop_obsolete_columns(conn)
    indexes_after = sorted(
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='index' AND tbl_name='strategy_runs' AND sql IS NOT NULL"
        ).fetchall()
    )
    # 8 个 idx_runs_* 索引全部保留(它们都不引用被删的两列)
    assert indexes_before == indexes_after
    assert len(indexes_after) >= 7  # schema.sql 定义 7 个 idx_runs_*
    conn.close()


def test_indexes_preserved_after_drop_recreate_path():
    """老 sqlite CREATE TABLE 复制法也要重建索引。"""
    conn = _make_conn_with_schema()
    indexes_before = sorted(
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='index' AND tbl_name='strategy_runs' AND sql IS NOT NULL"
        ).fetchall()
    )
    with patch("scripts.init_v14_tables.sqlite3.sqlite_version_info", (3, 30, 0)):
        drop_obsolete_columns(conn)
    indexes_after = sorted(
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='index' AND tbl_name='strategy_runs' AND sql IS NOT NULL"
        ).fetchall()
    )
    assert indexes_before == indexes_after
    conn.close()
