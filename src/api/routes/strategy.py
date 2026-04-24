"""建模 §9.10 /api/strategy/* 路由。

Sprint 1.5c C5 新增:
  GET /api/strategy/current         — 最新策略(替代 /latest,保留老路径向后兼容)
  GET /api/strategy/stream          — SSE 实时推送
  GET /api/strategy/history         — 分页历史(已有)
  GET /api/strategy/runs/{run_id}   — 单次详情(替代 /history/{run_id})

响应的 state 字段严格是建模 §7 的 12 业务块 JSON;meta.strategy_flavor 固定
'swing'。不接受 ?flavor=xxx 过滤(§9.10 v1.2 API 层 flavor 处理)。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ...data.storage.dao import StrategyStateDAO
from ..models import HistoryPage, StrategyStateRow


router = APIRouter(prefix="/strategy", tags=["strategy"])


# ==================================================================
# 序列化 helper
# ==================================================================

def _row_to_model(row: dict[str, Any]) -> StrategyStateRow:
    state = row.get("state")
    if isinstance(state, str):
        try:
            state = json.loads(state)
        except (json.JSONDecodeError, ValueError):
            state = {}
    # §9.10:meta.strategy_flavor 固定 'swing'
    if isinstance(state, dict):
        meta = state.get("meta")
        if not isinstance(meta, dict):
            meta = {}
            state["meta"] = meta
        meta.setdefault("strategy_flavor", "swing")
    return StrategyStateRow(
        run_timestamp_utc=row["run_timestamp_utc"],
        run_id=row["run_id"],
        run_trigger=row["run_trigger"],
        rules_version=row["rules_version"],
        ai_model_actual=row.get("ai_model_actual"),
        state=state or {},
        created_at=row.get("created_at"),
    )


# ==================================================================
# GET /current(建模 §9.10 #1)+ /latest alias(老路径)
# ==================================================================

def _get_current_impl(request: Request) -> StrategyStateRow:
    ctx = request.app.state.ctx
    conn = ctx.conn_factory()
    try:
        row = StrategyStateDAO.get_latest_state(conn)
    finally:
        try:
            conn.close()
        except Exception:
            pass
    if row is None:
        raise HTTPException(status_code=404, detail="No strategy state found")
    return _row_to_model(row)


@router.get("/current", response_model=StrategyStateRow)
def get_current(request: Request) -> StrategyStateRow:
    """§9.10 #1:最新策略。"""
    return _get_current_impl(request)


@router.get("/latest", response_model=StrategyStateRow)
def get_latest(request: Request) -> StrategyStateRow:
    """向后兼容旧版路径;建议用 /current。"""
    return _get_current_impl(request)


# ==================================================================
# GET /stream(建模 §9.10 #2:SSE 实时推送)
# ==================================================================

@router.get("/stream")
async def strategy_stream(request: Request) -> StreamingResponse:
    """§9.10 #2:SSE 实时推送最新 StrategyState。

    每 30 秒检查一次 latest_state,若 run_id 变化就推送;
    客户端断开会收到 CancelledError 并退出。
    """
    ctx = request.app.state.ctx
    poll_interval = 30.0

    async def event_gen() -> AsyncIterator[bytes]:
        last_run_id: str | None = None
        # 初始发送一次 current
        try:
            conn = ctx.conn_factory()
            try:
                row = StrategyStateDAO.get_latest_state(conn)
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
            if row:
                model = _row_to_model(row)
                last_run_id = model.run_id
                payload = model.model_dump_json()
                yield f"data: {payload}\n\n".encode("utf-8")
        except Exception as e:
            err = json.dumps({"error": f"initial_fetch_failed: {e}"})
            yield f"data: {err}\n\n".encode("utf-8")

        while True:
            if await request.is_disconnected():
                return
            await asyncio.sleep(poll_interval)
            try:
                conn = ctx.conn_factory()
                try:
                    row = StrategyStateDAO.get_latest_state(conn)
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass
                if row and row.get("run_id") != last_run_id:
                    model = _row_to_model(row)
                    last_run_id = model.run_id
                    payload = model.model_dump_json()
                    yield f"data: {payload}\n\n".encode("utf-8")
                else:
                    # keep-alive(可选):SSE 冒号开头的行是 heartbeat comment
                    yield b": keep-alive\n\n"
            except Exception as e:
                err = json.dumps({"error": f"stream_error: {e}"})
                yield f"data: {err}\n\n".encode("utf-8")

    return StreamingResponse(event_gen(), media_type="text/event-stream")


# ==================================================================
# GET /history(建模 §9.10 #3)
# ==================================================================

@router.get("/history", response_model=HistoryPage)
def list_history(
    request: Request,
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> HistoryPage:
    """§9.10 #3:分页历史。"""
    ctx = request.app.state.ctx
    conn = ctx.conn_factory()
    try:
        total_row = conn.execute(
            "SELECT COUNT(*) AS n FROM strategy_runs"
        ).fetchone()
        total = int(total_row["n"]) if total_row else 0
        rows = conn.execute(
            "SELECT * FROM strategy_runs "
            "ORDER BY reference_timestamp_utc DESC, generated_at_utc DESC "
            "LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    finally:
        try:
            conn.close()
        except Exception:
            pass

    items: list[StrategyStateRow] = []
    for r in rows:
        d = dict(r)
        d["state"] = json.loads(d.pop("full_state_json"))
        d["run_timestamp_utc"] = (
            d.get("reference_timestamp_utc") or d.get("generated_at_utc")
        )
        d.setdefault("created_at", d.get("generated_at_utc"))
        items.append(_row_to_model(d))
    return HistoryPage(total=total, limit=limit, offset=offset, items=items)


# ==================================================================
# GET /runs/{run_id}(建模 §9.10 #4)+ /history/{run_id} 老路径
# ==================================================================

def _get_run_impl(request: Request, run_id: str) -> StrategyStateRow:
    ctx = request.app.state.ctx
    conn = ctx.conn_factory()
    try:
        row = conn.execute(
            "SELECT * FROM strategy_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"run_id {run_id} not found",
        )
    d = dict(row)
    d["state"] = json.loads(d.pop("full_state_json"))
    d["run_timestamp_utc"] = (
        d.get("reference_timestamp_utc") or d.get("generated_at_utc")
    )
    d.setdefault("created_at", d.get("generated_at_utc"))
    return _row_to_model(d)


@router.get("/runs/{run_id}", response_model=StrategyStateRow)
def get_run(request: Request, run_id: str) -> StrategyStateRow:
    """§9.10 #4:单次运行详情。"""
    return _get_run_impl(request, run_id)


@router.get("/history/{run_id}", response_model=StrategyStateRow)
def get_one_history(request: Request, run_id: str) -> StrategyStateRow:
    """向后兼容老路径;建议用 /runs/{run_id}。"""
    return _get_run_impl(request, run_id)
