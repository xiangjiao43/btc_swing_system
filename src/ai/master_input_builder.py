"""src/ai/master_input_builder.py — Sprint 1.10-D thesis-aware master 输入装配。

对齐 docs/modeling.md b25cfe6(v1.4)§3.3.6。

职责:基于 1.10-A/B/C 数据层 + 业务层,装配 master AI 完整 input dict。
- L1-L5 outputs(由调用方/orchestrator 传入,不查 DB)
- active_thesis(ThesesDAO.get_active)
- current_position(VirtualAccountDAO.get_latest 抽 long/short)
- pending_orders(VirtualOrdersDAO.get_pending 当前 active thesis)
- cooldown_state(CooldownManager.is_in_cooldown)
- fuse_state(FuseMonitor.check_14d_fuse + 60d_cap_count + channel_c_uses)
- last_5_assessments(ThesesDAO.get_history 取 last_assessment 字段)

设计纪律(D1=a):
- 与 src/ai/context_builder.py 关注点分离:
  * context_builder 算客观指标(EMA / ADX / ATR / funding / onchain Series 计算)
  * master_input_builder 读业务表 + 装配 master 输入(thesis / position / orders / cooldown / fuse)
- 不调 AI(纯装配函数)
- 不写 DB(纯读)
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

from src.data.storage.dao import (
    ThesesDAO, VirtualAccountDAO, VirtualOrdersDAO,
)
from src.strategy.cooldown_manager import is_in_cooldown
from src.strategy.fuse_monitor import check_14d_fuse


def _parse_iso(s: str) -> datetime:
    s = str(s).replace("Z", "+00:00")
    return datetime.fromisoformat(s)


# ============================================================
# 主入口
# ============================================================

def build_master_input(
    conn: sqlite3.Connection,
    *,
    layer_outputs: dict[str, Any],          # {l1, l2, l3, l4, l5} from orchestrator
    current_btc_price: float,
    now_utc: str,
    last_5_history_limit: int = 5,
) -> dict[str, Any]:
    """装配 v1.4 §3.3.6 master input dict。

    Args:
        conn: sqlite3 连接(纯读)
        layer_outputs: dict 含 l1/l2/l3/l4/l5 outputs(orchestrator 给)
        current_btc_price: 当前价(用于算 current_pnl_pct)
        now_utc: 当前时间
        last_5_history_limit: 历史 thesis 数量(默认 5)

    Returns:
        dict 完整 master_input,字段对齐 v1.4 §3.3.6 input schema
    """
    return {
        # L1-L5(orchestrator 给,不查 DB)
        "l1_output": layer_outputs.get("l1"),
        "l2_output": layer_outputs.get("l2"),
        "l3_output": layer_outputs.get("l3"),
        "l4_output": layer_outputs.get("l4"),
        "l5_output": layer_outputs.get("l5"),
        # v1.4 新增 thesis-aware 字段
        "active_thesis": _build_active_thesis(conn, now_utc),
        "current_position": _build_current_position(conn, current_btc_price),
        "pending_orders": _build_pending_orders(conn),
        "cooldown_state": _build_cooldown_state(conn, now_utc),
        "fuse_state": _build_fuse_state(conn, now_utc),
        "last_5_assessments": _build_last_n_assessments(
            conn, limit=last_5_history_limit,
        ),
        # Sprint D Item 3:数据新鲜度摘要(注入 master prompt 让 AI 感知 stale)
        "data_freshness_summary": _build_data_freshness_summary(conn),
    }


def _build_data_freshness_summary(
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """Sprint D Item 3:把 4 个数据源的 freshness 序列化给 master_adjudicator
    prompt。AI 看到任一源 is_stale=true 时,system prompt 纪律要求 narrative
    必须明确提到"X 数据已过期 N 小时";否则 validator 会 fail 走 fallback。"""
    from src.data.freshness import compute_all_freshness, freshness_to_dict
    try:
        rows = compute_all_freshness(conn)
    except Exception:
        return []
    return [freshness_to_dict(f) for f in rows]


# ============================================================
# 子装配器
# ============================================================

def _build_active_thesis(
    conn: sqlite3.Connection, now_utc: str,
) -> Optional[dict[str, Any]]:
    """active_thesis(无 → None)。结构对齐 §3.3.6 input schema。"""
    th = ThesesDAO.get_active(conn)
    if th is None:
        return None
    try:
        created_dt = _parse_iso(th["created_at_utc"])
        now_dt = _parse_iso(now_utc)
        days_ago = (now_dt - created_dt).total_seconds() / 86400.0
    except (ValueError, TypeError, KeyError):
        days_ago = 0.0
    return {
        "thesis_id": th["thesis_id"],
        "direction": th["direction"],
        "confidence_score": th.get("confidence_score"),
        "core_logic": th.get("core_logic"),
        "break_conditions": th.get("break_conditions") or [],
        "created_days_ago": round(days_ago, 2),
        "lifecycle_stage": th.get("lifecycle_stage"),
        "is_60d_capped": int(th.get("is_60d_capped") or 0) == 1,
        "last_assessment": th.get("last_assessment"),
        "last_assessment_at_run": th.get("last_assessment_at_run"),
    }


def _build_current_position(
    conn: sqlite3.Connection, current_btc_price: float,
) -> Optional[dict[str, Any]]:
    """current_position dict(无持仓 → None)。"""
    snap = VirtualAccountDAO.get_latest(conn)
    if snap is None:
        return None
    long_btc = float(snap.get("long_btc_amount") or 0.0)
    short_btc = float(snap.get("short_btc_amount") or 0.0)
    if long_btc <= 0 and short_btc <= 0:
        return None

    out: dict[str, Any] = {}
    if long_btc > 0:
        long_avg = float(snap.get("long_avg_price") or 0.0)
        long_usdt = float(snap.get("long_position_usdt") or 0.0)
        out["long_position_usdt"] = round(long_usdt, 8)
        out["long_avg_price"] = round(long_avg, 8) if long_avg > 0 else None
        out["long_btc_amount"] = round(long_btc, 8)
        if long_avg > 0:
            out["long_pnl_pct"] = round(
                (current_btc_price - long_avg) / long_avg * 100.0, 4
            )
    if short_btc > 0:
        short_avg = float(snap.get("short_avg_price") or 0.0)
        short_usdt = float(snap.get("short_position_usdt") or 0.0)
        out["short_position_usdt"] = round(short_usdt, 8)
        out["short_avg_price"] = round(short_avg, 8) if short_avg > 0 else None
        out["short_btc_amount"] = round(short_btc, 8)
        if short_avg > 0:
            out["short_pnl_pct"] = round(
                (short_avg - current_btc_price) / short_avg * 100.0, 4
            )
    return out


def _build_pending_orders(
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """active thesis 的 pending 挂单(无 active thesis → 空 list)。"""
    th = ThesesDAO.get_active(conn)
    if th is None:
        return []
    pending = VirtualOrdersDAO.get_pending(conn, thesis_id=th["thesis_id"])
    out = []
    for o in pending:
        out.append({
            "order_id": o["order_id"],
            "type": o["order_type"],
            "price": float(o["price"]),
            "size_pct": float(o["size_pct"]),
            "size_usdt": float(o["size_usdt"]),
            "expires_at_utc": o["expires_at_utc"],
        })
    return out


def _build_cooldown_state(
    conn: sqlite3.Connection, now_utc: str,
) -> dict[str, Any]:
    """冷却期状态(无 closed thesis → in_cooldown=False)。"""
    # 取最近一条 closed thesis(任意 status != 'active')
    row = conn.execute(
        "SELECT thesis_id, closed_at_utc, close_channel "
        "FROM theses WHERE status != 'active' "
        "ORDER BY closed_at_utc DESC LIMIT 1"
    ).fetchone()
    latest_closed = dict(row) if row else None
    state = is_in_cooldown(now_utc, latest_closed)
    return {
        "in_cooldown": bool(state.get("in_cooldown")),
        "cooldown_remaining_hours": float(state.get("remaining_hours") or 0.0),
        "cooldown_reason": (
            f"channel_{state.get('channel')}" if state.get("in_cooldown") else None
        ),
    }


def _build_fuse_state(
    conn: sqlite3.Connection, now_utc: str,
) -> dict[str, Any]:
    """熔断状态(Validator 18 双触发)。"""
    fuse = check_14d_fuse(conn, now_utc)
    return {
        "in_14d_fuse": bool(fuse.get("in_thesis_cycle_fuse")),
        "thesis_cycles_in_14d": int(fuse.get("thesis_cycle_count_14d") or 0),
        "channel_c_uses_in_14d": int(fuse.get("channel_c_count_14d") or 0),
        "channel_c_disabled": bool(fuse.get("channel_c_disabled")),
    }


def _build_last_n_assessments(
    conn: sqlite3.Connection, limit: int = 5,
) -> list[dict[str, Any]]:
    """历史 N 条 thesis 评估(供 master 看趋势,§3.3.6 input)。"""
    history = ThesesDAO.get_history(conn, limit=limit)
    out: list[dict[str, Any]] = []
    for h in history:
        if not h.get("last_assessment"):
            continue  # 无评估的略
        out.append({
            "thesis_id": h.get("thesis_id"),
            "run_id": h.get("last_assessment_at_run") or h.get("created_at_run_id"),
            "assessment": h.get("last_assessment"),
            "narrative_brief": (h.get("last_assessment_note") or "")[:200],
        })
    return out
