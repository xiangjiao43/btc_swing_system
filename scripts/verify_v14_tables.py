#!/usr/bin/env python3
"""scripts/verify_v14_tables.py — Sprint 1.10-A 端到端真实断言(§Z 纪律)。

用途:用户 SSH 到服务器跑此脚本,验证 v1.4 三表 + 索引 + 初始化 snapshot
全部就位。**不接受 mock pass**(§Z),全是真 SQL 断言连真 DB。

执行前:用户应已经跑过 scripts/init_v14_tables.py(此脚本本身不主动初始化,
只断言已初始化的 DB 状态符合预期)。

用法:
    .venv/bin/python scripts/verify_v14_tables.py [/path/to/db]
不传参数则读 config/base.yaml::paths.db_path。

退出码:
    0  全部通过
    1  有任一断言失败(打印具体错误后 exit)
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import yaml


_REPO_ROOT = Path(__file__).resolve().parent.parent
_BASE_YAML = _REPO_ROOT / "config" / "base.yaml"


# ============================================================
# 断言工具
# ============================================================

class AssertionFailure(Exception):
    pass


_PASSED: list[str] = []
_FAILED: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        _PASSED.append(label)
        print(f"  ✅ {label}")
    else:
        _FAILED.append(f"{label} | {detail}")
        print(f"  ❌ {label} | {detail}")


# ============================================================
# 断言项
# ============================================================

def assert_table_exists(conn: sqlite3.Connection, table: str) -> None:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    check(f"表 `{table}` 存在", row is not None,
          detail=f"sqlite_master 无 type=table name={table}")


def assert_index_exists(conn: sqlite3.Connection, index: str) -> None:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
        (index,),
    ).fetchone()
    check(f"索引 `{index}` 存在", row is not None,
          detail=f"sqlite_master 无 type=index name={index}")


def assert_row_count(conn: sqlite3.Connection, table: str, expected: int) -> None:
    try:
        cnt = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except sqlite3.OperationalError as e:
        check(f"`{table}` 行数 = {expected}", False,
              detail=f"表不存在或查询失败:{e}")
        return
    check(f"`{table}` 行数 = {expected}", cnt == expected,
          detail=f"实际 {cnt}")


def assert_va_initial_capital(conn: sqlite3.Connection, expected: float) -> None:
    try:
        row = conn.execute(
            "SELECT initial_capital, available_cash, total_equity FROM virtual_account "
            "ORDER BY snapshot_at_utc DESC LIMIT 1"
        ).fetchone()
    except sqlite3.OperationalError as e:
        check(f"virtual_account.initial_capital = {expected}", False,
              detail=f"virtual_account 表查询失败:{e}")
        return
    if row is None:
        check(f"virtual_account.initial_capital = {expected}", False,
              detail="无 virtual_account 行(请先跑 scripts/init_v14_tables.py)")
        return
    check(
        f"virtual_account.initial_capital = {expected}",
        row[0] == expected,
        detail=f"实际 {row[0]}",
    )
    check(
        f"virtual_account.available_cash = {expected}(初始时 = initial_capital)",
        row[1] == expected,
        detail=f"实际 {row[1]}",
    )
    check(
        f"virtual_account.total_equity = {expected}(初始时 = initial_capital)",
        row[2] == expected,
        detail=f"实际 {row[2]}",
    )


# ============================================================
# 主流程
# ============================================================

def load_config() -> dict:
    with open(_BASE_YAML, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def resolve_db_path(cfg: dict, cli_arg: str | None) -> Path:
    if cli_arg:
        return Path(cli_arg).resolve()
    rel = (cfg.get("paths") or {}).get("db_path", "data/btc_strategy.db")
    return (_REPO_ROOT / rel).resolve()


def main(argv: list[str]) -> int:
    cfg = load_config()
    db_path = resolve_db_path(cfg, argv[1] if len(argv) > 1 else None)
    expected_capital = float(
        (cfg.get("virtual_account") or {}).get("initial_capital", 100000)
    )

    print(f"[verify_v14_tables] DB: {db_path}")
    print(f"[verify_v14_tables] expected initial_capital: {expected_capital}")
    print()

    if not db_path.exists():
        print(f"❌ DB 文件不存在:{db_path}")
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        print("=== 1. 三张表存在 ===")
        for tbl in ("virtual_account", "virtual_orders", "theses"):
            assert_table_exists(conn, tbl)

        print("\n=== 2. 五个索引存在 ===")
        for idx in (
            "idx_va_time",
            "idx_vo_status", "idx_vo_thesis",
            "idx_theses_status", "idx_theses_created",
        ):
            assert_index_exists(conn, idx)

        print("\n=== 3. virtual_account 第一行 snapshot ===")
        assert_row_count(conn, "virtual_account", 1)
        assert_va_initial_capital(conn, expected_capital)

        print("\n=== 4. virtual_orders 与 theses 初始为空 ===")
        assert_row_count(conn, "virtual_orders", 0)
        assert_row_count(conn, "theses", 0)

    finally:
        conn.close()

    print()
    print(f"=== 总结 ===")
    print(f"通过:{len(_PASSED)} 项")
    print(f"失败:{len(_FAILED)} 项")
    if _FAILED:
        print()
        print("失败详情:")
        for f in _FAILED:
            print(f"  ❌ {f}")
        print()
        print("❌ 全部通过 — 失败")
        return 1

    print()
    print("✅ 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
