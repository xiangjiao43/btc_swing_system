#!/usr/bin/env python3
"""scripts/init_v14_tables.py — Sprint 1.10-A 幂等初始化 v1.4 三表。

应用:
1. 跑 migrations/009_v14_virtual_account_thesis.sql(CREATE TABLE IF NOT EXISTS,幂等)
2. 写入 virtual_account 第一行 snapshot:
   - initial_capital / currency 从 config/base.yaml::virtual_account 读
   - 关联到当前最新 strategy_run 的 run_id(若无 run,使用 'init_v14_bootstrap')
   - available_cash = initial_capital,其他持仓字段全 0
3. 幂等(已初始化 → 跳过,不报错):若 virtual_account 已有 ≥ 1 行,只打印当前
   状态后退出 0

用法:
    .venv/bin/python scripts/init_v14_tables.py [/path/to/db]
不传参数则默认走 config/base.yaml::paths.db_path。
"""
from __future__ import annotations

import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml


# 让脚本可独立执行(从仓库根目录)
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from src.data.storage.dao import VirtualAccountDAO  # noqa: E402

_BASE_YAML = _REPO_ROOT / "config" / "base.yaml"
_MIGRATION = _REPO_ROOT / "migrations" / "009_v14_virtual_account_thesis.sql"
_MIGRATION_010 = _REPO_ROOT / "migrations" / "010_v14_fuse_system_states.sql"
_MIGRATION_011 = _REPO_ROOT / "migrations" / "011_v14_validator_meta.sql"
_MIGRATION_012 = _REPO_ROOT / "migrations" / "012_v14_retry_log.sql"
_MIGRATION_013 = _REPO_ROOT / "migrations" / "013_v14_event_throttle_class.sql"
_MIGRATION_014 = _REPO_ROOT / "migrations" / "014_v14_weekly_reviews.sql"
_MIGRATION_015 = _REPO_ROOT / "migrations" / "015_v14_drop_old_columns.sql"

# Sprint 1.10-K-B commit 3:1.10-J 后无人写的列 → migration 015 删
# (DROP 由 drop_obsolete_columns() 显式调用,不自动挂 apply_migration)
_OBSOLETE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("strategy_runs", "observation_category"),
    ("strategy_runs", "cold_start"),
)
_MIN_NATIVE_DROP_COLUMN_VERSION = (3, 35, 0)


def load_config() -> dict:
    with open(_BASE_YAML, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def resolve_db_path(cfg: dict, cli_arg: str | None) -> Path:
    if cli_arg:
        return Path(cli_arg).resolve()
    rel = (cfg.get("paths") or {}).get("db_path", "data/btc_strategy.db")
    return (_REPO_ROOT / rel).resolve()


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def apply_migration(conn: sqlite3.Connection) -> None:
    """幂等跑 migration 009 + 010。

    009:CREATE TABLE IF NOT EXISTS,executescript 幂等
    010 SQL 部分:同 009(fuse_events / system_states 用 IF NOT EXISTS)
    010 ALTER:Python 侧条件 ALTER(SQLite ALTER 不支持 IF NOT EXISTS)
    """
    # 009
    sql_009 = _MIGRATION.read_text(encoding="utf-8")
    conn.executescript(sql_009)

    # 010 SQL 部分(fuse_events + system_states)
    if _MIGRATION_010.exists():
        sql_010 = _MIGRATION_010.read_text(encoding="utf-8")
        conn.executescript(sql_010)
        # 010 ALTER:theses.is_60d_capped(条件 ALTER)
        if not _column_exists(conn, "theses", "is_60d_capped"):
            conn.execute(
                "ALTER TABLE theses ADD COLUMN is_60d_capped INTEGER NOT NULL DEFAULT 0"
            )

    # 011 ALTER:strategy_runs.constraint_activations_json(条件 ALTER)
    # SQL 文件本身只含注释(audit trail);ALTER 在 Python 侧
    if not _column_exists(conn, "strategy_runs", "constraint_activations_json"):
        conn.execute(
            "ALTER TABLE strategy_runs ADD COLUMN constraint_activations_json TEXT"
        )

    # 012 ALTER:strategy_runs.retry_log_json(条件 ALTER)
    if not _column_exists(conn, "strategy_runs", "retry_log_json"):
        conn.execute(
            "ALTER TABLE strategy_runs ADD COLUMN retry_log_json TEXT"
        )

    # 013 ALTER:event_throttle.event_class(条件 ALTER,Sprint 1.10-G D2=b)
    # 已存在 event_throttle 表(2.7-D 创建);加 event_class 标记两类节流
    if not _column_exists(conn, "event_throttle", "event_class"):
        conn.execute(
            "ALTER TABLE event_throttle ADD COLUMN event_class TEXT"
        )

    # 014:weekly_reviews(全新表,CREATE TABLE IF NOT EXISTS 幂等,Sprint 1.10-H D1=a)
    if _MIGRATION_014.exists():
        sql_014 = _MIGRATION_014.read_text(encoding="utf-8")
        conn.executescript(sql_014)

    # Sprint 1.10-J commit 7 §X(累积清单 H#2/H#3 修):
    # events_calendar.triggered_at_utc 条件 ALTER
    # 历史:1.10-G verify event_macro 报"no such column" — 因为生产 DB
    # 是 2.7-D 之前 schema(无此列)+ schema.sql 已含但 IF NOT EXISTS
    # 不会加列到已存在表 + init_v14_tables 之前不调 migrate_2_7_d
    if not _column_exists(conn, "events_calendar", "triggered_at_utc"):
        conn.execute(
            "ALTER TABLE events_calendar ADD COLUMN triggered_at_utc TEXT"
        )


def _supports_native_drop_column() -> bool:
    """SQLite ≥ 3.35.0(2021-03-12)原生支持 ALTER TABLE … DROP COLUMN。

    < 3.35.0 需 CREATE TABLE 复制法兜底。
    服务器 SQLite 3.45.1 + 本地 3.50.4 均走原生路径。
    """
    return sqlite3.sqlite_version_info >= _MIN_NATIVE_DROP_COLUMN_VERSION


def _list_indexes_for_table(
    conn: sqlite3.Connection, table: str,
) -> list[tuple[str, str]]:
    """返回表的所有非自动索引 (name, create_sql)。"""
    rows = conn.execute(
        "SELECT name, sql FROM sqlite_master "
        "WHERE type='index' AND tbl_name = ? AND sql IS NOT NULL",
        (table,),
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def _drop_column_or_recreate(
    conn: sqlite3.Connection, table: str, column: str,
) -> str:
    """自适应删列:新 sqlite 走原生 ALTER;老 sqlite 走 CREATE TABLE 复制法。

    幂等:列不存在 → no-op,返回 'no_op'。
    Returns: 'no_op' | 'native_alter' | 'recreate'
    """
    if not _column_exists(conn, table, column):
        return "no_op"
    if _supports_native_drop_column():
        conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        return "native_alter"
    # 老 sqlite:CREATE TABLE 复制法(保留索引)
    indexes = _list_indexes_for_table(conn, table)
    cols_info = conn.execute(f"PRAGMA table_info({table})").fetchall()
    keep_cols = [r[1] for r in cols_info if r[1] != column]
    keep_cols_csv = ", ".join(keep_cols)
    tmp = f"{table}__migration015_tmp"
    conn.execute(
        f"CREATE TABLE {tmp} AS SELECT {keep_cols_csv} FROM {table}"
    )
    conn.execute(f"DROP TABLE {table}")
    conn.execute(f"ALTER TABLE {tmp} RENAME TO {table}")
    # 重建索引(CREATE TABLE AS 不带索引)
    for _idx_name, idx_sql in indexes:
        if idx_sql:
            try:
                conn.execute(idx_sql)
            except sqlite3.OperationalError:
                # 已存在 → 跳过
                pass
    return "recreate"


def drop_obsolete_columns(
    conn: sqlite3.Connection,
    *,
    backup_path: Optional[Path] = None,
) -> dict[str, str]:
    """Sprint 1.10-K-B commit 3:删 1.10-J 已弃用的 strategy_runs 列。

    **重要**:本函数不挂 apply_migration() 主流程,需调用方明确 opt-in。
    部署前置:dao.py / state_builder.py / weekly_review_input_builder.py
    需先更新为不再 INSERT/SELECT 这两列(否则 DROP 后下次 INSERT 崩溃)。

    Args:
        conn: 已连接的 sqlite3.Connection
        backup_path: 可选备份路径(传则在 DROP 前 cp DB)

    Returns:
        {column: result} dict,result ∈ {'no_op', 'native_alter', 'recreate'}
    """
    if backup_path is not None:
        # 仅文件型 DB 才能备份(in-memory ':memory:' 跳过)
        try:
            db_file = Path(conn.execute("PRAGMA database_list").fetchone()[2])
            if db_file.exists():
                import shutil
                shutil.copy2(db_file, backup_path)
        except Exception:
            pass

    results: dict[str, str] = {}
    try:
        for table, column in _OBSOLETE_COLUMNS:
            results[f"{table}.{column}"] = _drop_column_or_recreate(
                conn, table, column,
            )
        conn.commit()
    except Exception:
        # 错误回滚:用未提交事务回滚 + 抛 raise(由调用方决定是否 restore backup)
        conn.rollback()
        raise
    return results


def get_latest_run_id(conn: sqlite3.Connection) -> str | None:
    """从 strategy_runs 取最新 run_id;无则返 None。"""
    try:
        row = conn.execute(
            "SELECT run_id FROM strategy_runs "
            "ORDER BY generated_at_utc DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:
        # strategy_runs 表不存在(极早期 / 全新 DB)
        return None


def already_initialized(conn: sqlite3.Connection) -> bool:
    """检测 virtual_account 是否已写过 ≥ 1 行(幂等条件)。"""
    cnt = conn.execute("SELECT COUNT(*) FROM virtual_account").fetchone()[0]
    return cnt >= 1


def init_first_snapshot(conn: sqlite3.Connection, cfg: dict) -> dict:
    """写入 virtual_account 第一行;返回写入字段 dict。"""
    va_cfg = cfg.get("virtual_account") or {}
    initial_capital = float(va_cfg.get("initial_capital", 100000))
    currency = va_cfg.get("currency", "USDT")
    if currency != "USDT":
        # v1.4 暂只支持 USDT,但 schema 没强约束,留警告
        print(f"WARN: virtual_account.currency='{currency}' (v1.4 仅 USDT,将仍以 USDT 计价)")

    run_id = get_latest_run_id(conn) or "init_v14_bootstrap"
    snapshot_id = f"init_{uuid.uuid4().hex[:12]}"
    snapshot_at_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    VirtualAccountDAO.insert_snapshot(
        conn,
        snapshot_id=snapshot_id,
        run_id=run_id,
        snapshot_at_utc=snapshot_at_utc,
        btc_price_at_snapshot=0.0,         # 初始化无 K 线快照,留 0
        initial_capital=initial_capital,
        available_cash=initial_capital,    # 全部资金可用
        total_equity=initial_capital,      # = initial_capital
    )
    return {
        "snapshot_id": snapshot_id,
        "run_id": run_id,
        "initial_capital": initial_capital,
        "currency": currency,
    }


def main(argv: list[str]) -> int:
    cfg = load_config()
    db_path = resolve_db_path(cfg, argv[1] if len(argv) > 1 else None)

    print(f"[init_v14_tables] DB: {db_path}")
    if not db_path.exists():
        print(f"[init_v14_tables] DB file not found, will be created on connect")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        apply_migration(conn)
        conn.commit()
        print("[init_v14_tables] migration 009 applied (idempotent)")

        if already_initialized(conn):
            existing = VirtualAccountDAO.get_latest(conn)
            print(f"[init_v14_tables] ALREADY INITIALIZED — skip")
            print(f"  latest snapshot_id: {existing['snapshot_id']}")
            print(f"  initial_capital:    {existing['initial_capital']}")
            print(f"  available_cash:     {existing['available_cash']}")
            print(f"  total_equity:       {existing['total_equity']}")
            return 0

        first = init_first_snapshot(conn, cfg)
        conn.commit()
        print(f"[init_v14_tables] INITIALIZED first snapshot:")
        print(f"  snapshot_id:        {first['snapshot_id']}")
        print(f"  run_id:             {first['run_id']}")
        print(f"  initial_capital:    {first['initial_capital']} {first['currency']}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
