"""src/strategy/review_pending.py — Sprint 1.10-C review_pending 状态管理。

对齐 docs/modeling.md b25cfe6(v1.4)§4.2.6 + §3.4.6 / §3.4.7。

review_pending 触发场景:
- 60 天上限触发(Validator 19)
- 连续 2 次 14 天熔断(Validator 20)
- master AI 连续 3 天失败(Validator 22,留 1.10-D)
- 极端事件 PROTECTION 期间(留 1.10-G)

三种出口(用户介入,本 sprint 只实现底层 API,UI 留 1.10-I):
- A 调阈值(降 grade 门槛 / 调 cooldown 等)
- B 续期 thesis(在已存在 thesis 基础上 master AI 重出 break_conditions)
- C reset 熔断(清 fuse_events 14d_fuse_triggered 计数,允许重新创建 thesis)

D2=a 落地:用 system_states 表持久化(state_type='review_pending')。
"""
from __future__ import annotations

import sqlite3
from typing import Any, Optional


_STATE_TYPE = "review_pending"

# 三种出口枚举
EXIT_A = "exit_a_threshold_adjustment"
EXIT_B = "exit_b_thesis_renewal"
EXIT_C = "exit_c_fuse_reset"


# ============================================================
# 进入 review_pending
# ============================================================

def enter_review_pending(
    conn: sqlite3.Connection,
    *,
    reason: str,                              # validator_19_60d_cap / validator_20_consecutive_fuse / ...
    related_thesis_id: Optional[str],
    entered_at_utc: str,
) -> dict[str, Any]:
    """进 review_pending(写 system_states 一行 active)。

    幂等:已在 review_pending(active 行存在)→ 不再插入,返回当前 state_id。

    Returns:
        {state_id: int, was_already_active: bool, entered_at_utc: str, reason: str}
    """
    # 检测当前是否已 active
    current = conn.execute(
        "SELECT state_id, entered_at_utc, reason FROM system_states "
        "WHERE state_type=? AND exit_at_utc IS NULL "
        "ORDER BY entered_at_utc DESC LIMIT 1",
        (_STATE_TYPE,),
    ).fetchone()
    if current is not None:
        return {
            "state_id": int(current["state_id"]),
            "was_already_active": True,
            "entered_at_utc": current["entered_at_utc"],
            "reason": current["reason"],
        }

    cur = conn.execute(
        "INSERT INTO system_states "
        "(state_type, entered_at_utc, exit_at_utc, reason, related_thesis_id, exit_reason) "
        "VALUES (?, ?, NULL, ?, ?, NULL)",
        (_STATE_TYPE, entered_at_utc, reason, related_thesis_id),
    )
    return {
        "state_id": int(cur.lastrowid or 0),
        "was_already_active": False,
        "entered_at_utc": entered_at_utc,
        "reason": reason,
    }


# ============================================================
# 查询当前是否在 review_pending
# ============================================================

def is_in_review_pending(conn: sqlite3.Connection) -> dict[str, Any]:
    """查询当前是否在 review_pending(active 行存在)。

    Returns:
        {in_review_pending: bool, state_id, entered_at_utc, reason, related_thesis_id}
    """
    row = conn.execute(
        "SELECT * FROM system_states "
        "WHERE state_type=? AND exit_at_utc IS NULL "
        "ORDER BY entered_at_utc DESC LIMIT 1",
        (_STATE_TYPE,),
    ).fetchone()
    if row is None:
        return {
            "in_review_pending": False,
            "state_id": None,
            "entered_at_utc": None,
            "reason": None,
            "related_thesis_id": None,
        }
    d = dict(row)
    return {
        "in_review_pending": True,
        "state_id": int(d["state_id"]),
        "entered_at_utc": d["entered_at_utc"],
        "reason": d["reason"],
        "related_thesis_id": d["related_thesis_id"],
    }


# ============================================================
# 三个出口
# ============================================================

def _exit(
    conn: sqlite3.Connection, exit_reason: str, exit_at_utc: str,
) -> dict[str, Any]:
    """通用出口实现:把当前 active review_pending 行的 exit_at_utc/exit_reason 写入。"""
    row = conn.execute(
        "SELECT state_id FROM system_states "
        "WHERE state_type=? AND exit_at_utc IS NULL "
        "ORDER BY entered_at_utc DESC LIMIT 1",
        (_STATE_TYPE,),
    ).fetchone()
    if row is None:
        return {"exited": False, "reason": "no_active_review_pending"}
    state_id = int(row["state_id"])
    conn.execute(
        "UPDATE system_states SET exit_at_utc=?, exit_reason=? WHERE state_id=?",
        (exit_at_utc, exit_reason, state_id),
    )
    return {"exited": True, "state_id": state_id, "exit_reason": exit_reason}


def exit_a_threshold_adjustment(
    conn: sqlite3.Connection, exit_at_utc: str,
) -> dict[str, Any]:
    """出口 A:调阈值(用户决策降 grade 门槛 / 调 cooldown 等)。

    本 sprint 只实现状态退出,具体阈值修改 API 留 1.10-I。
    """
    return _exit(conn, EXIT_A, exit_at_utc)


def exit_b_thesis_renewal(
    conn: sqlite3.Connection, exit_at_utc: str,
    *,
    new_thesis_spec: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """出口 B:续期 thesis(用户接受 master AI 重出 break_conditions)。

    本 sprint 只实现状态退出 + 接 new_thesis_spec dict(具体调用
    ThesisManager.create_thesis 留 1.10-D 的 master_run wrapper)。
    """
    res = _exit(conn, EXIT_B, exit_at_utc)
    res["new_thesis_spec_received"] = new_thesis_spec is not None
    return res


def exit_c_fuse_reset(
    conn: sqlite3.Connection, exit_at_utc: str,
) -> dict[str, Any]:
    """出口 C:reset 熔断(清 fuse_events 14d_fuse_triggered 计数)。

    实施:删除 fuse_events 中所有 event_type='14d_fuse_triggered' 行,
    避免 Validator 20 持续触发。其他 fuse_events(thesis_cycle / channel_c)保留作 audit。
    """
    res = _exit(conn, EXIT_C, exit_at_utc)
    if res.get("exited"):
        cur = conn.execute(
            "DELETE FROM fuse_events WHERE event_type='14d_fuse_triggered'"
        )
        res["fuse_records_deleted"] = cur.rowcount
    return res
