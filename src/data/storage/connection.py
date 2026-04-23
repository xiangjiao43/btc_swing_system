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


def init_db(db_path: Optional[Path] = None, verbose: bool = True) -> Path:
    """
    幂等初始化数据库。读取 schema.sql 建所有表与索引。

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
