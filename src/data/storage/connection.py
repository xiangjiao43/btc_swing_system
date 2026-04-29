"""
connection.py — SQLite connection + init_db

读取 config/base.yaml 的 paths.db_path,解析为 repo-root 相对路径;
提供 get_connection() 返回开启 foreign_keys 的 sqlite3.Connection;
init_db() 读取 schema.sql 幂等建表。

对应建模 §8.5 / §10.4。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

import yaml


_THIS_DIR: Path = Path(__file__).resolve().parent
_REPO_ROOT: Path = _THIS_DIR.parent.parent.parent           # src/data/storage -> repo root
_BASE_YAML: Path = _REPO_ROOT / "config" / "base.yaml"
_SCHEMA_SQL: Path = _THIS_DIR / "schema.sql"


def _load_base_config() -> dict:
    """读取 config/base.yaml。"""
    with open(_BASE_YAML, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_db_path() -> Path:
    """
    返回 SQLite 数据库绝对路径。
    路径来源:config/base.yaml → paths.db_path(默认 "data/btc_strategy.db")。
    若 .env 的 DATABASE_URL 被设置为 sqlite:/// 形式,暂不在此解析
    (后续 config loader 统一处理)。
    """
    cfg = _load_base_config()
    rel = cfg["paths"]["db_path"]
    return (_REPO_ROOT / rel).resolve()


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """
    返回一个 sqlite3.Connection。
    - 启用 foreign_keys
    - row_factory = sqlite3.Row,字段名可 dict 形式访问
    - 父目录不存在会自动创建(利于冷启动)

    Args:
        db_path: 可选覆盖路径;不传则走 base.yaml。

    Returns:
        已开 PRAGMA foreign_keys 的 Connection。调用方负责 close。
    """
    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(
        str(path),
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _fix_legacy_review_reports_schema(
    conn: sqlite3.Connection, *, verbose: bool = False,
) -> str:
    """Sprint 1.5b-C.1 hotfix:对齐 review_reports 表到建模 §10.4。

    Sprint 1 老 schema:run_timestamp_utc / report_json / created_at
    建模 §10.4 新 schema:review_id (PK) / generated_at_utc /
                         rules_version_at_review / full_report_json

    生产 DB 漂移情况:migrations/001_align_to_modeling_schema.sql 没真在生产 DB
    跑过,review_reports 仍是老 schema。schema.sql 的 IF NOT EXISTS 不会修。

    本函数幂等:
      - 已是新 schema(含 review_id 列)→ "ok_already_new"
      - 仍是老 schema(含 run_timestamp_utc 但无 review_id)→ DROP + 重建,
        返回 "fixed_legacy"。生产 lifecycle 还没真归档过,行数预期 0;
        若 > 0 就 ABORT(不静默丢数据)
      - review_reports 表不存在 → "ok_no_table"(后续 schema.sql IF NOT EXISTS 会建)
    """
    rows = conn.execute("PRAGMA table_info(review_reports)").fetchall()
    if not rows:
        return "ok_no_table"
    cols = [r[1] if not isinstance(r, sqlite3.Row) else r["name"] for r in rows]

    has_old = "run_timestamp_utc" in cols
    has_new = "review_id" in cols
    if has_new:
        return "ok_already_new"
    if not has_old:
        # 既不旧也不新 → 不动
        return "ok_unknown_schema"

    # 老 schema:DROP + 重建。先核对行数,> 0 则 ABORT 保护数据
    n = conn.execute("SELECT COUNT(*) FROM review_reports").fetchone()[0]
    if n and n > 0:
        raise RuntimeError(
            f"review_reports has legacy schema with {n} rows; aborting to "
            f"avoid data loss. Manually export rows then drop the table."
        )

    if verbose:
        print(
            f"[init_db] legacy review_reports detected (cols={cols}); "
            f"DROP + recreate to align with §10.4"
        )
    conn.execute("DROP TABLE review_reports")
    conn.commit()
    return "fixed_legacy"


def init_db(db_path: Optional[Path] = None, verbose: bool = True) -> Path:
    """
    幂等初始化数据库。读取 schema.sql 建所有表与索引。

    Sprint 1.5b-C.1:在跑 schema.sql 之前,先做 schema 漂移检测与修复
    (review_reports 老/新 schema 对齐),然后让 schema.sql 的 IF NOT EXISTS
    自动重建到新 schema。

    Args:
        db_path: 可选覆盖路径;不传则走 base.yaml。
        verbose: True 时打印创建结果。

    Returns:
        实际使用的数据库文件路径。
    """
    path = db_path or get_db_path()
    sql = _SCHEMA_SQL.read_text(encoding="utf-8")

    conn = get_connection(path)
    try:
        # Sprint 1.5b-C.1:先修 schema 漂移
        try:
            status = _fix_legacy_review_reports_schema(conn, verbose=verbose)
            if verbose and status != "ok_no_table":
                print(f"[init_db] review_reports schema check: {status}")
        except Exception as e:
            # 漂移修复失败(如行数 > 0 ABORT)→ raise 让用户看到
            conn.close()
            raise

        conn.executescript(sql)
        conn.commit()
        if verbose:
            # 列出已创建的表
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = [r["name"] for r in cur.fetchall()]
            print(f"[init_db] db_path = {path}")
            print(f"[init_db] tables ({len(tables)}): {', '.join(tables)}")
            cur = conn.execute(
                "SELECT COUNT(*) AS n FROM sqlite_master WHERE type='index' "
                "AND name NOT LIKE 'sqlite_%'"
            )
            idx_count = cur.fetchone()["n"]
            print(f"[init_db] user indices: {idx_count}")
    finally:
        conn.close()

    return path
