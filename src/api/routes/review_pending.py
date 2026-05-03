"""src/api/routes/review_pending.py — Sprint 1.10-I review_pending API。

对齐 docs/modeling.md b25cfe6(v1.4)§9.5 #18 + D4=b+c 决策:
- POST /api/review_pending/resolve
  body: {exit_type ∈ {a,b,c,d}, reason (min 10 chars), new_thesis_spec?, new_thesis_id?}
  - 后端校验 exit_type 枚举 + reason 长度,失败 422
  - 调对应 review_pending.exit_a/b/c/d_thesis_resumed
  - 写入 system_states.exit_reason(用户输入 reason 文本)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/review_pending", tags=["review_pending"])


class ResolveRequest(BaseModel):
    """POST /api/review_pending/resolve 请求 body(D4=b+c)。"""
    exit_type: Literal["a", "b", "c", "d"] = Field(
        ..., description="出口类型:a 调阈值 / b 续期 thesis / c reset 熔断 / d 自然恢复",
    )
    reason: str = Field(
        ..., min_length=10, max_length=500,
        description=(
            "用户输入的解除理由(min 10 chars,写入 system_states.exit_reason)。"
            "EXIT_C 清 14d_fuse 历史、EXIT_D 自动退过度保守 — 关键决策需说明"
        ),
    )
    new_thesis_spec: Optional[dict[str, Any]] = Field(
        None,
        description="EXIT_B 续期时传(1.10-C 老接口),其他 exit_type 忽略",
    )
    new_thesis_id: Optional[str] = Field(
        None,
        description="EXIT_D 自然恢复时传(指明触发退出的新 thesis_id),其他 exit_type 忽略",
    )

    @field_validator("reason")
    @classmethod
    def _strip_reason(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 10:
            raise ValueError("reason 去空格后必须 ≥ 10 字符")
        return v


@router.post("/resolve")
def resolve_review_pending(
    request: Request, payload: ResolveRequest,
) -> dict[str, Any]:
    """v1.4 §9.5 #18 + D4=b+c:解除 review_pending(出口 A/B/C/D)。

    - exit_a → exit_a_threshold_adjustment
    - exit_b → exit_b_thesis_renewal(可传 new_thesis_spec)
    - exit_c → exit_c_fuse_reset(清 14d_fuse 历史)
    - exit_d → exit_d_thesis_resumed(只对 reason='overly_conservative' 生效)

    Returns: {exited: bool, state_id, exit_reason, exit_type, user_reason}
    或 422(校验失败)/ 400(操作失败:无 active RP 或 exit_d 拒绝)。
    """
    from src.strategy import review_pending as rp_mod

    ctx = request.app.state.ctx
    conn = ctx.conn_factory()
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        if payload.exit_type == "a":
            res = rp_mod.exit_a_threshold_adjustment(
                conn, exit_at_utc=now_iso,
            )
        elif payload.exit_type == "b":
            res = rp_mod.exit_b_thesis_renewal(
                conn, exit_at_utc=now_iso,
                new_thesis_spec=payload.new_thesis_spec,
            )
        elif payload.exit_type == "c":
            res = rp_mod.exit_c_fuse_reset(
                conn, exit_at_utc=now_iso,
            )
        else:  # d
            res = rp_mod.exit_d_thesis_resumed(
                conn, exit_at_utc=now_iso,
                new_thesis_id=payload.new_thesis_id,
            )

        if not res.get("exited"):
            # 操作未生效(无 active RP 或 EXIT_D 拒绝其他 reason)
            conn.rollback()
            raise HTTPException(
                status_code=400,
                detail={
                    "exited": False,
                    "exit_type": payload.exit_type,
                    "reason_from_system": res.get("reason"),
                    "user_reason": payload.reason,
                },
            )

        # 把用户输入 reason 覆盖到 system_states.exit_reason(D4=c)
        # 默认 _exit() 写的是 EXIT_X 常量 — 我们追加用户 reason 让审计更清晰
        try:
            user_reason_full = f"{res.get('exit_reason') or ''} | user_reason={payload.reason}"
            conn.execute(
                "UPDATE system_states SET exit_reason=? WHERE state_id=?",
                (user_reason_full, res.get("state_id")),
            )
            conn.commit()
        except Exception as e:
            logger.warning("update exit_reason w/ user input failed: %s", e)
            conn.commit()

        res["exit_type"] = payload.exit_type
        res["user_reason"] = payload.reason
        return res
    finally:
        try:
            conn.close()
        except Exception:
            pass
