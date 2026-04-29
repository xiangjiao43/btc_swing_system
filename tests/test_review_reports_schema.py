"""tests/test_review_reports_schema.py — Sprint 1.5b-C.1 hotfix。

§Z 真实 DB schema 断言:
- 全新 init_db → review_reports 含 review_id 列
- 模拟生产 legacy schema → init_db 检测 + DROP + 重建,不报错
- 行数 > 0 的 legacy → ABORT(不静默丢数据)
- 修复后 ReviewReportsDAO.insert_report 真插入工作
- 修复幂等(跑两次)
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.data.storage.connection import (
    _fix_legacy_review_reports_schema,
    init_db,
)


def _cols(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [r[1] if not isinstance(r, sqlite3.Row) else r["name"] for r in rows]


def _create_legacy_review_reports(conn: sqlite3.Connection) -> None:
    """模拟 Sprint 1 老 schema(生产 DB 现状)。"""
    conn.execute("""
        CREATE TABLE review_reports (
            run_timestamp_utc  TEXT,
            lifecycle_id       TEXT,
            outcome_type       TEXT,
            report_json        TEXT,
            created_at         TEXT
        )
    """)
    conn.commit()


# ============================================================
# 全新 init_db
# ============================================================

def test_review_reports_has_review_id_column_after_init_db():
    tmp = Path(tempfile.mkdtemp()) / "fresh.db"
    init_db(db_path=tmp, verbose=False)
    conn = sqlite3.connect(tmp)
    try:
        cols = _cols(conn, "review_reports")
    finally:
        conn.close()
    assert "review_id" in cols, f"expected review_id col, got {cols}"
    assert "run_timestamp_utc" not in cols, (
        f"legacy col 不该出现在新 schema: {cols}"
    )


# ============================================================
# Legacy → init_db 自动修
# ============================================================

def test_init_db_fixes_legacy_review_reports_schema():
    """模拟生产残留 legacy schema,init_db 应自动 DROP + 重建。"""
    tmp = Path(tempfile.mkdtemp()) / "legacy.db"
    # 步骤 1:用一个最小 connection 建出"老版本 review_reports"模拟生产
    pre_conn = sqlite3.connect(tmp)
    try:
        _create_legacy_review_reports(pre_conn)
        cols_before = _cols(pre_conn, "review_reports")
    finally:
        pre_conn.close()
    assert "run_timestamp_utc" in cols_before
    assert "review_id" not in cols_before

    # 步骤 2:跑 init_db,应自动检测到 legacy 并修
    init_db(db_path=tmp, verbose=False)

    # 步骤 3:验证修复
    conn = sqlite3.connect(tmp)
    try:
        cols_after = _cols(conn, "review_reports")
    finally:
        conn.close()
    assert "review_id" in cols_after
    assert "run_timestamp_utc" not in cols_after


def test_legacy_schema_with_data_aborts_to_avoid_loss():
    """legacy schema 但行数 > 0 → 应 ABORT,不静默 DROP 丢数据。"""
    tmp = Path(tempfile.mkdtemp()) / "legacy_with_data.db"
    pre_conn = sqlite3.connect(tmp)
    try:
        _create_legacy_review_reports(pre_conn)
        # 插一行,模拟"生产侧已经写过 review"
        pre_conn.execute(
            "INSERT INTO review_reports VALUES (?, ?, ?, ?, ?)",
            ("2026-01-01T00:00:00Z", "lc-1", "A", "{}", "2026-01-01T00:00:00Z"),
        )
        pre_conn.commit()
    finally:
        pre_conn.close()

    with pytest.raises(RuntimeError, match="legacy schema with 1 rows"):
        init_db(db_path=tmp, verbose=False)


# ============================================================
# Idempotent
# ============================================================

def test_init_db_idempotent_on_already_new_schema():
    """全新 init_db 已是新 schema → 再跑一次不报错,不重建。"""
    tmp = Path(tempfile.mkdtemp()) / "idem.db"
    init_db(db_path=tmp, verbose=False)
    init_db(db_path=tmp, verbose=False)  # 跑第二次
    conn = sqlite3.connect(tmp)
    try:
        cols = _cols(conn, "review_reports")
    finally:
        conn.close()
    assert "review_id" in cols


def test_fix_helper_returns_correct_status():
    """_fix_legacy_review_reports_schema 返回字符串状态。"""
    tmp = Path(tempfile.mkdtemp()) / "status.db"
    # 表不存在
    conn = sqlite3.connect(tmp)
    try:
        assert _fix_legacy_review_reports_schema(conn, verbose=False) == "ok_no_table"
    finally:
        conn.close()

    # 老表
    pre_conn = sqlite3.connect(tmp)
    try:
        _create_legacy_review_reports(pre_conn)
    finally:
        pre_conn.close()
    conn2 = sqlite3.connect(tmp)
    try:
        assert _fix_legacy_review_reports_schema(conn2, verbose=False) == "fixed_legacy"
    finally:
        conn2.close()

    # 修完后:init_db 一次让 schema.sql 重建
    init_db(db_path=tmp, verbose=False)
    conn3 = sqlite3.connect(tmp)
    try:
        assert _fix_legacy_review_reports_schema(conn3, verbose=False) == "ok_already_new"
    finally:
        conn3.close()


# ============================================================
# 修复后 ReviewReportsDAO.insert_report 真工作
# ============================================================

def test_review_reports_dao_insert_works_after_fix():
    """模拟生产 legacy → init_db 修 → insert_report 真工作 + SELECT 查到。"""
    from src.data.storage.dao import ReviewReportsDAO

    tmp = Path(tempfile.mkdtemp()) / "dao_after_fix.db"
    pre_conn = sqlite3.connect(tmp)
    try:
        _create_legacy_review_reports(pre_conn)
    finally:
        pre_conn.close()

    init_db(db_path=tmp, verbose=False)

    conn = sqlite3.connect(tmp)
    conn.row_factory = sqlite3.Row
    try:
        ReviewReportsDAO.insert_report(
            conn,
            run_timestamp_utc="2026-04-29T12:00:00Z",
            lifecycle_id="lc-fix-1",
            outcome_type="A_perfect",
            report={"foo": "bar", "realized_pnl_pct": 6.5},
            review_id="lc-fix-1_2026-04-29T12:00:00Z",
            rules_version_at_review="v1.2.0",
        )
        conn.commit()
        rows = ReviewReportsDAO.get_reports_for_lifecycle(conn, "lc-fix-1")
        assert len(rows) == 1
        assert rows[0]["outcome_type"] == "A_perfect"
        assert rows[0]["report"]["realized_pnl_pct"] == 6.5
    finally:
        conn.close()
