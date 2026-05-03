"""src/strategy/fuse_monitor.py — Sprint 1.10-C 14 天熔断 + 60 天上限 + 连续熔断。

对齐 docs/modeling.md b25cfe6(v1.4)§4.3.4 + §3.4.6 Validator 18/19/20。

职责(本 sprint 范围):
- record_thesis_cycle / record_channel_c_use:写 fuse_events audit log
- check_14d_fuse:Validator 18 双触发(thesis 完整周期 ≥ 2 / 通道 C ≥ 2)
- check_60d_cap + mark_60d_capped:Validator 19(60 天上限,D4=b 显式字段)
- check_consecutive_fuse:Validator 20(连续 2 次 14 天熔断 → review_pending)

设计纪律:
- 不做实际"进 review_pending"动作(那是 review_pending 模块职责);
  本模块只检测 + 报告
- 60d-capped thesis 维持 lifecycle_stage(D4=b),不进 closed
- 60d-capped 后挂单仍触发自然平仓(走通道 A,3 天冷却)
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Optional


# ============================================================
# 常量
# ============================================================

_FUSE_WINDOW_DAYS = 14            # Validator 18:14 天滑窗
_60D_CAP_DAYS = 60                # Validator 19:60 天上限
_CONSECUTIVE_FUSE_WINDOW_DAYS = 90  # Validator 20:连续 2 次 14d 熔断的检测窗(覆盖 2 个 14d 周期 + 缓冲)

# fuse_events.event_type 枚举
EVT_THESIS_CYCLE = "thesis_cycle_completed"
EVT_CHANNEL_C = "channel_c_used"
EVT_14D_FUSE = "14d_fuse_triggered"


def _parse_iso(s: str) -> datetime:
    s = str(s).replace("Z", "+00:00")
    return datetime.fromisoformat(s)


def _format_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ============================================================
# fuse_events 写入(audit log)
# ============================================================

def record_thesis_cycle(
    conn: sqlite3.Connection,
    thesis_id: str,
    closed_at_utc: str,
    metadata: Optional[dict[str, Any]] = None,
) -> int:
    """thesis 关闭时记录(Validator 18 触发条件 #1)。返回 inserted id。"""
    cur = conn.execute(
        "INSERT INTO fuse_events (event_type, thesis_id, triggered_at_utc, metadata_json) "
        "VALUES (?, ?, ?, ?)",
        (EVT_THESIS_CYCLE, thesis_id, closed_at_utc,
         json.dumps(metadata or {}, ensure_ascii=False)),
    )
    return int(cur.lastrowid or 0)


def record_channel_c_use(
    conn: sqlite3.Connection,
    thesis_id: str,
    used_at_utc: str,
    metadata: Optional[dict[str, Any]] = None,
) -> int:
    """每次反手通道 C 触发(Validator 18 触发条件 #2)。"""
    cur = conn.execute(
        "INSERT INTO fuse_events (event_type, thesis_id, triggered_at_utc, metadata_json) "
        "VALUES (?, ?, ?, ?)",
        (EVT_CHANNEL_C, thesis_id, used_at_utc,
         json.dumps(metadata or {}, ensure_ascii=False)),
    )
    return int(cur.lastrowid or 0)


def record_14d_fuse_triggered(
    conn: sqlite3.Connection,
    triggered_at_utc: str,
    fuse_subtype: str,            # thesis_cycle / channel_c
    metadata: Optional[dict[str, Any]] = None,
) -> int:
    """14 天熔断触发时记录(Validator 20 连续熔断检测用)。"""
    md = dict(metadata or {})
    md["subtype"] = fuse_subtype
    cur = conn.execute(
        "INSERT INTO fuse_events (event_type, thesis_id, triggered_at_utc, metadata_json) "
        "VALUES (?, NULL, ?, ?)",
        (EVT_14D_FUSE, triggered_at_utc, json.dumps(md, ensure_ascii=False)),
    )
    return int(cur.lastrowid or 0)


# ============================================================
# Validator 18:14 天熔断双触发
# ============================================================

def check_14d_fuse(
    conn: sqlite3.Connection,
    now_utc: str,
) -> dict[str, Any]:
    """检测 14 天熔断(Validator 18,v1.4 §4.3.4)。

    双触发条件:
    - 14 天内 thesis 完整周期 ≥ 2 次 → 强制 FLAT 14 天 + critical 告警
    - 14 天内通道 C 触发 ≥ 2 次 → 14 天禁用通道 C

    Returns:
        {
          "thesis_cycle_count_14d":  int,    # 过去 14 天 thesis 关闭次数
          "channel_c_count_14d":     int,    # 过去 14 天通道 C 触发次数
          "in_thesis_cycle_fuse":    bool,   # 触发条件 #1
          "channel_c_disabled":      bool,   # 触发条件 #2
          "in_fuse":                 bool,   # 任一触发
        }
    """
    now_dt = _parse_iso(now_utc)
    window_start_dt = now_dt - timedelta(days=_FUSE_WINDOW_DAYS)
    window_start_iso = _format_iso(window_start_dt)

    cycle_count = conn.execute(
        "SELECT COUNT(*) FROM fuse_events "
        "WHERE event_type=? AND triggered_at_utc >= ?",
        (EVT_THESIS_CYCLE, window_start_iso),
    ).fetchone()[0]
    channel_c_count = conn.execute(
        "SELECT COUNT(*) FROM fuse_events "
        "WHERE event_type=? AND triggered_at_utc >= ?",
        (EVT_CHANNEL_C, window_start_iso),
    ).fetchone()[0]

    in_thesis_cycle_fuse = cycle_count >= 2
    channel_c_disabled = channel_c_count >= 2

    return {
        "thesis_cycle_count_14d": int(cycle_count),
        "channel_c_count_14d": int(channel_c_count),
        "in_thesis_cycle_fuse": in_thesis_cycle_fuse,
        "channel_c_disabled": channel_c_disabled,
        "in_fuse": in_thesis_cycle_fuse or channel_c_disabled,
    }


# ============================================================
# Validator 19:60 天上限(D4=b 显式字段)
# ============================================================

def check_60d_cap(
    conn: sqlite3.Connection,
    thesis_id: str,
    now_utc: str,
) -> bool:
    """检测 thesis 是否触发 60 天上限(Validator 19)。

    条件:
    - thesis.status='active'
    - thesis.is_60d_capped == 0(未标记过)
    - now - thesis.created_at_utc >= 60 天

    Returns:
        True = 应触发 60d_cap(调用方应调 mark_60d_capped + 进 review_pending)
        False = 未触发(< 60 天 / 已标记过 / 非 active)
    """
    row = conn.execute(
        "SELECT created_at_utc, status, is_60d_capped FROM theses WHERE thesis_id=?",
        (thesis_id,),
    ).fetchone()
    if row is None:
        return False
    if row["status"] != "active":
        return False
    if int(row["is_60d_capped"] or 0) == 1:
        return False
    try:
        created_dt = _parse_iso(row["created_at_utc"])
        now_dt = _parse_iso(now_utc)
    except (ValueError, TypeError):
        return False
    days_elapsed = (now_dt - created_dt).total_seconds() / 86400.0
    return days_elapsed >= _60D_CAP_DAYS


def mark_60d_capped(
    conn: sqlite3.Connection,
    thesis_id: str,
) -> int:
    """标记 thesis 为 60d_capped(D4=b)。返回受影响行数。

    后续 ThesisManager / OrdersEngine 看到 is_60d_capped=1:
    - 不允许新加仓(via Validator 19)
    - 不允许调整 stop_loss(via Validator 17 + 19)
    - 但挂单仍可被 OrdersEngine 触发(走自然平仓 → 通道 A)
    """
    cur = conn.execute(
        "UPDATE theses SET is_60d_capped=1 WHERE thesis_id=?",
        (thesis_id,),
    )
    return cur.rowcount


# ============================================================
# Validator 20:连续 2 次 14 天熔断
# ============================================================

def check_consecutive_fuse(
    conn: sqlite3.Connection,
    now_utc: str,
) -> dict[str, Any]:
    """检测连续 2 次 14 天熔断(Validator 20,v1.4 §3.4.6)。

    定义"连续":过去 90 天(覆盖 2 个 14d 周期 + 缓冲)内 14d_fuse_triggered 事件 ≥ 2。

    Returns:
        {
          "fuse_count_90d":          int,
          "triggers_review_pending": bool,
          "latest_fuse_at_utc":      str | None,
        }
    """
    now_dt = _parse_iso(now_utc)
    window_start_dt = now_dt - timedelta(days=_CONSECUTIVE_FUSE_WINDOW_DAYS)
    window_start_iso = _format_iso(window_start_dt)

    rows = conn.execute(
        "SELECT triggered_at_utc FROM fuse_events "
        "WHERE event_type=? AND triggered_at_utc >= ? "
        "ORDER BY triggered_at_utc DESC",
        (EVT_14D_FUSE, window_start_iso),
    ).fetchall()

    count = len(rows)
    latest = rows[0]["triggered_at_utc"] if rows else None
    return {
        "fuse_count_90d": count,
        "triggers_review_pending": count >= 2,
        "latest_fuse_at_utc": latest,
    }
