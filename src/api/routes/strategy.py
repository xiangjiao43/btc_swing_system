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
import logging
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ...data.storage.dao import LatestFactorCardsDAO, StrategyStateDAO
from ..models import HistoryPage, StrategyStateRow
from ...web_helpers import normalize_state


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/strategy", tags=["strategy"])


# ==================================================================
# 序列化 helper
# ==================================================================

def _row_to_model(
    row: dict[str, Any],
    *,
    v14_summaries: dict[str, Any] | None = None,
) -> StrategyStateRow:
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

    # Sprint 1.8.2-A:经 normalize_state 把 v12/v13 统一成"前端友好+已翻译"
    # schema(含 schema_version + summary_card + layer_cards + raw)
    normalized: dict[str, Any] = {}
    try:
        normalized = normalize_state(
            state or {}, row.get("run_mode"),
            generated_at_utc=row.get("generated_at_utc"),
        )
    except Exception:
        # 任何异常 fallback 为空 normalized,前端可降级渲染
        normalized = {"schema_version": "unknown", "summary_card": {},
                      "layer_cards": [], "anti_patterns_active": [],
                      "extreme_events_active": [], "raw": state or {}}

    # Sprint 1.10-I §9.5:加 4 个 v1.4 摘要字段到 normalized state(向后兼容追加)
    if v14_summaries:
        for k, v in v14_summaries.items():
            normalized[k] = v

    return StrategyStateRow(
        run_timestamp_utc=row["run_timestamp_utc"],
        run_id=row["run_id"],
        run_trigger=row["run_trigger"],
        rules_version=row["rules_version"],
        ai_model_actual=row.get("ai_model_actual"),
        state=normalized,
        created_at=row.get("created_at"),
    )


# ==================================================================
# GET /current(建模 §9.10 #1)+ /latest alias(老路径)
# ==================================================================

def _build_v14_summaries(conn: Any) -> dict[str, Any]:
    """Sprint 1.10-I §9.5:构造 4 个 v1.4 摘要字段(GET /current 扩展)。

    向后兼容:仅**追加**字段,不动现有 state 字段顺序与值。
    任一摘要失败 → 该字段返 null,前端可降级渲染。

    Returns:
      {
        account_summary: dict | null,
        active_thesis: dict | null,
        position_summary: dict | null,
        pending_orders_summary: dict | null,
      }
    """
    out: dict[str, Any] = {
        "account_summary": None,
        "active_thesis": None,
        "position_summary": None,
        "pending_orders_summary": None,
    }
    try:
        from src.data.storage.dao import (
            ThesesDAO, VirtualAccountDAO, VirtualOrdersDAO,
        )
    except Exception as e:
        logger.warning("v14_summaries: import dao failed: %s", e)
        return out

    # 1. account_summary
    try:
        latest_va = VirtualAccountDAO.get_latest(conn)
        if latest_va:
            initial = float(latest_va.get("initial_capital") or 0.0)
            equity = float(latest_va.get("total_equity") or 0.0)
            cash = float(latest_va.get("available_cash") or 0.0)
            pnl_pct = (
                ((equity - initial) / initial * 100.0) if initial > 0 else 0.0
            )
            out["account_summary"] = {
                "snapshot_id": latest_va.get("snapshot_id"),
                "snapshot_at_utc": latest_va.get("snapshot_at_utc"),
                "initial_capital": initial,
                "total_equity": equity,
                "available_cash": cash,
                "total_pnl_pct": round(pnl_pct, 4),
            }
    except Exception as e:
        logger.warning("v14_summaries.account: %s", e)

    # 2. active_thesis(摘要,完整数据见 GET /api/theses/active)
    active = None
    try:
        active = ThesesDAO.get_active(conn)
        if active:
            out["active_thesis"] = {
                "thesis_id": active.get("thesis_id"),
                "direction": active.get("direction"),
                "lifecycle_stage": active.get("lifecycle_stage"),
                "confidence_score": active.get("confidence_score"),
                "created_at_utc": active.get("created_at_utc"),
                "last_assessment": active.get("last_assessment"),
                "is_60d_capped": bool(active.get("is_60d_capped") or 0),
            }
    except Exception as e:
        logger.warning("v14_summaries.active_thesis: %s", e)

    # 3. position_summary(从 active thesis + filled entry 推算)
    if active:
        try:
            filled = VirtualOrdersDAO.get_filled(
                conn, thesis_id=active["thesis_id"],
            )
            entry_filled = [o for o in filled if o.get("order_type") == "entry"]
            total_btc = sum(float(o.get("filled_btc_amount") or 0) for o in entry_filled)
            total_cost = sum(
                float(o.get("filled_btc_amount") or 0) * float(o.get("filled_price") or 0)
                for o in entry_filled
            )
            avg_price = (total_cost / total_btc) if total_btc > 0 else None
            out["position_summary"] = {
                "thesis_id": active["thesis_id"],
                "direction": active.get("direction"),
                "btc_amount": round(total_btc, 8) if total_btc else 0.0,
                "avg_entry_price": (
                    round(avg_price, 2) if avg_price is not None else None
                ),
                "entry_orders_filled": len(entry_filled),
            }
        except Exception as e:
            logger.warning("v14_summaries.position: %s", e)

    # 4. pending_orders_summary(从 active thesis 的 pending 算)
    if active:
        try:
            pending = VirtualOrdersDAO.get_pending(
                conn, thesis_id=active["thesis_id"],
            )
            by_type: dict[str, int] = {}
            for o in pending:
                t = o.get("order_type") or "unknown"
                by_type[t] = by_type.get(t, 0) + 1
            out["pending_orders_summary"] = {
                "thesis_id": active["thesis_id"],
                "total": len(pending),
                "by_type": by_type,
            }
        except Exception as e:
            logger.warning("v14_summaries.pending: %s", e)

    return out


def _overlay_latest_factor_cards(
    row: dict[str, Any], conn: Any,
) -> dict[str, Any]:
    """Sprint 2.8-A.1:把 latest_factor_cards 覆盖到 row.state.factor_cards。

    /current 和 /stream 共用此 helper(§X 不允许两路重复实现)。
    latest_factor_cards 表为空(冷启动 / 单测)→ 原样返回 row。
    state 可能是 str(JSON)或 dict;两种都处理。
    """
    if row is None:
        return row
    latest = LatestFactorCardsDAO.get_latest(conn)
    if latest is None:
        return row
    state = row.get("state")
    if isinstance(state, str):
        try:
            state = json.loads(state)
        except (json.JSONDecodeError, ValueError):
            state = {}
        row = dict(row)
        row["state"] = state
    if isinstance(state, dict):
        state["factor_cards"] = latest["cards"]
        state.setdefault("meta", {})["factor_cards_refreshed_at_utc"] = (
            latest["refreshed_at_utc"]
        )
    return row


def _get_current_impl(request: Request) -> StrategyStateRow:
    ctx = request.app.state.ctx
    conn = ctx.conn_factory()
    v14_summaries: dict[str, Any] = {}
    try:
        row = StrategyStateDAO.get_latest_state(conn)
        row = _overlay_latest_factor_cards(row, conn)
        # Sprint 1.10-I §9.5:加 4 个 v1.4 摘要字段(向后兼容)
        v14_summaries = _build_v14_summaries(conn)
    finally:
        try:
            conn.close()
        except Exception:
            pass
    if row is None:
        raise HTTPException(status_code=404, detail="No strategy state found")
    return _row_to_model(row, v14_summaries=v14_summaries)


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
                # Sprint 2.8-A.1:SSE 推送也走 latest_factor_cards 覆盖,
                # 与 /current 行为一致(避免 push 把前端硬刷拿到的新卡 revert 回旧值)
                row = _overlay_latest_factor_cards(row, conn)
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
                    # Sprint 2.8-A.1:轮询推送也覆盖
                    row = _overlay_latest_factor_cards(row, conn)
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
