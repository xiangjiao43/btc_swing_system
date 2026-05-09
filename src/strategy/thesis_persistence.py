"""src/strategy/thesis_persistence.py — Sprint G P0(2026-05-09)

接通 master.trade_plan → ThesisManager.create_thesis 持久化链路。

历史:Sprint 1.10-D master prompt 改 v1.4 thesis-aware schema 时,加了
ThesisManager.create_thesis 函数定义,但 review_pending.py:159 注释里
明确写"留 1.10-D 的 master_run wrapper" — 这个 wrapper **从未实施**。
导致 60 天 theses 表 0 行 / virtual_orders 表 0 行(详见 audit
docs/cc_reports/run_2026_05_03_16_08_audit.md)。

本模块是那个 wrapper:在 state_builder._run_v13_orchestrator 跑完
orchestrator.run_full_a() 后调用,根据 master 输出和约束条件决定是否创建
thesis,真插 theses + virtual_orders 表。

# ============================================================
# 创建条件(全部 AND;任一不满足 → 不创建,return skip_reason)
# ============================================================

a. validator pass — orchestrator status startswith "ok"
b. fallback_level 是 None / "normal"(master 真跑通,非 fallback silent)
c. L3 opportunity_grade ∈ {"A", "B"}(用户决策:C 级观望,不创建 thesis)
d. master output 表示要创建新 thesis(v1.4: mode=="new_thesis";
   v1.3: state_transition.to_state in {LONG_PLANNED, SHORT_PLANNED}
         + trade_plan.action == "open")
e. master.trade_plan 完整(direction 非空,entry/stop_loss/take_profit 非空)
f. 当前没有同方向 active thesis(防重复创建)

# ============================================================
# v1.3 vs v1.4 schema 兼容
# ============================================================

v1.3 (5/3 16:08 实测):
  master.state_transition = {from_state: FLAT, to_state: LONG_PLANNED}
  master.trade_plan = {
    action: open, direction: long,
    entry_price_zone: [76251, 77000],   # 价格列表
    stop_loss: 76251,                    # 单价
    take_profit_zones: [79455, 82309, 85000],  # 价格列表
    position_size_pct: 0.33
  }

v1.4 (master_adjudicator.txt prompt 期望):
  master.mode = "new_thesis"
  master.new_thesis = {
    direction: long, confidence_score: 70, core_logic: ...,
    break_conditions: [...3+ 条客观...],
    entry_orders: [{price, size_pct}, ...],
    stop_loss: {price, size_pct: 100},
    take_profit: [{price, size_pct}, ...]
  }

本模块两种 schema 都兼容。
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from src.data.storage.dao import ThesesDAO


logger = logging.getLogger(__name__)


_PLANNED_STATES = ("LONG_PLANNED", "SHORT_PLANNED")
_ALLOWED_GRADES = ("A", "B")
_DEFAULT_INITIAL_CAPITAL = 100_000.0  # USDT
_DEFAULT_EXPIRY_DAYS = 7              # 与 base.yaml::virtual_orders.default_expiry_days 一致


# ============================================================
# 主入口
# ============================================================

def try_create_thesis_from_master_run(
    conn: sqlite3.Connection,
    *,
    orchestrator_result: dict[str, Any],
    fallback_level: Optional[str],
    run_id: str,
    now_utc: str,
    initial_capital: float = _DEFAULT_INITIAL_CAPITAL,
    expiry_days: int = _DEFAULT_EXPIRY_DAYS,
) -> dict[str, Any]:
    """主入口:根据 master 输出 + 约束条件决定是否创建 thesis。

    Args:
        conn: SQLite 连接(调用方 commit)
        orchestrator_result: AIOrchestrator.run_full_a() 返回 dict
        fallback_level: strategy_runs.fallback_level("level_1"/"level_2"/None)
        run_id: 当前 strategy_run id
        now_utc: ISO 字符串
        initial_capital: 计 size_usdt 用,默认 100k
        expiry_days: 挂单过期天数,默认 7

    Returns:
        {
          "created": bool,
          "thesis_id": str | None,
          "skip_reason": str | None,
          "schema_version": "v1.3" | "v1.4" | None,
        }

    设计:任何一个条件 a-f 不满足都返回 created=False + skip_reason 字符串。
    create_thesis 抛异常 → 捕获 → return created=False + skip_reason。
    保证不抛异常出去,不影响调用方写 strategy_runs。
    """
    layers = orchestrator_result.get("layers") or {}
    master = layers.get("master") or {}
    l3 = layers.get("l3") or {}

    # ---- 条件 a:validator pass ----
    status = str(orchestrator_result.get("status") or "")
    if not (status == "ok" or status.startswith("ok")):
        return {"created": False, "thesis_id": None,
                "skip_reason": f"orchestrator status={status!r} 非 ok",
                "schema_version": None}

    # ---- 条件 b:非 fallback ----
    if fallback_level and str(fallback_level) not in ("normal", ""):
        return {"created": False, "thesis_id": None,
                "skip_reason": f"fallback_level={fallback_level!r}",
                "schema_version": None}

    # ---- 条件 c:L3 grade ∈ {A, B} ----
    l3_grade = l3.get("opportunity_grade")
    if l3_grade not in _ALLOWED_GRADES:
        return {"created": False, "thesis_id": None,
                "skip_reason": f"l3_grade={l3_grade!r} not in {_ALLOWED_GRADES}",
                "schema_version": None}

    # ---- 条件 d:master 表示 new thesis ----
    schema_version, intent_ok = _check_new_thesis_intent(master)
    if not intent_ok:
        return {"created": False, "thesis_id": None,
                "skip_reason": "master 输出无 new thesis 意图(无 mode 也无 LONG_PLANNED)",
                "schema_version": None}

    # ---- 条件 e:trade_plan 完整 ----
    spec, missing = _build_thesis_spec(
        master, l3_grade, schema_version,
        initial_capital=initial_capital,
    )
    if missing:
        return {"created": False, "thesis_id": None,
                "skip_reason": f"trade_plan 缺字段: {missing}",
                "schema_version": schema_version}

    # ---- 条件 f:无同方向 active thesis ----
    direction = spec["direction"]
    existing = ThesesDAO.get_active(conn)
    if existing is not None and existing.get("direction") == direction:
        return {"created": False, "thesis_id": None,
                "skip_reason": (
                    f"已有 active {direction} thesis "
                    f"thesis_id={existing.get('thesis_id')}"
                ),
                "schema_version": schema_version}

    # ---- 真创建 ----
    expires_at_utc = _compute_expiry(now_utc, expiry_days)
    try:
        from src.strategy.thesis_manager import create_thesis
        result = create_thesis(
            conn,
            thesis_spec=spec,
            run_id=run_id,
            now_utc=now_utc,
            expires_at_utc=expires_at_utc,
        )
        return {
            "created": True,
            "thesis_id": result["thesis_id"],
            "skip_reason": None,
            "schema_version": schema_version,
            "entry_order_ids": result.get("entry_order_ids") or [],
            "stop_loss_order_ids": result.get("stop_loss_order_ids") or [],
            "take_profit_order_ids": result.get("take_profit_order_ids") or [],
        }
    except Exception as e:
        logger.exception("thesis_persistence: create_thesis raised: %s", e)
        return {"created": False, "thesis_id": None,
                "skip_reason": f"create_thesis raised {type(e).__name__}: {str(e)[:200]}",
                "schema_version": schema_version}


# ============================================================
# Helpers
# ============================================================

def _check_new_thesis_intent(
    master: dict[str, Any],
) -> tuple[Optional[str], bool]:
    """识别 master 输出 schema + 是否有 new thesis 意图。

    Returns:
        (schema_version, intent_ok)
        schema_version: "v1.4" 或 "v1.3" 或 None
    """
    # v1.4 优先:有 mode 字段
    mode = master.get("mode")
    if mode is not None:
        return "v1.4", str(mode) == "new_thesis"

    # v1.3 退回:state_transition + trade_plan
    state_trans = master.get("state_transition") or {}
    to_state = state_trans.get("to_state")
    trade_plan = master.get("trade_plan") or {}
    action = trade_plan.get("action")
    if to_state in _PLANNED_STATES and action == "open":
        return "v1.3", True

    return None, False


def _build_thesis_spec(
    master: dict[str, Any],
    l3_grade: str,
    schema_version: str,
    *,
    initial_capital: float,
) -> tuple[dict[str, Any], list[str]]:
    """master output → thesis_spec(create_thesis 入参格式)。

    Returns:
        (spec, missing_fields):missing_fields 非空 → 不能创建
    """
    if schema_version == "v1.4":
        return _build_spec_v14(master, l3_grade, initial_capital=initial_capital)
    if schema_version == "v1.3":
        return _build_spec_v13(master, l3_grade, initial_capital=initial_capital)
    return {}, ["unknown_schema_version"]


def _build_spec_v14(
    master: dict[str, Any], l3_grade: str, *, initial_capital: float,
) -> tuple[dict[str, Any], list[str]]:
    nt = master.get("new_thesis") or {}
    direction = nt.get("direction")
    entry_orders_raw = nt.get("entry_orders") or []
    stop_loss_raw = nt.get("stop_loss")
    tp_raw = nt.get("take_profit") or nt.get("take_profit_orders") or []

    missing: list[str] = []
    if direction not in ("long", "short"):
        missing.append("direction")
    if not entry_orders_raw:
        missing.append("entry_orders")
    if not stop_loss_raw:
        missing.append("stop_loss")
    if not tp_raw:
        missing.append("take_profit")
    if missing:
        return {}, missing

    # v1.4 entry_orders: list[{price, size_pct}] — size_usdt = size_pct% * initial_capital
    entry_list: list[dict[str, Any]] = []
    for o in entry_orders_raw:
        price = float(o["price"])
        sp = float(o.get("size_pct") or 0.0)
        entry_list.append({
            "price": price,
            "size_pct": sp,
            "size_usdt": round(initial_capital * sp / 100.0, 2),
        })

    # stop_loss: single dict {price, size_pct=100}
    sl_price = float(stop_loss_raw["price"]) if isinstance(stop_loss_raw, dict) else float(stop_loss_raw)
    sl_sp = (
        float(stop_loss_raw.get("size_pct", 100.0))
        if isinstance(stop_loss_raw, dict) else 100.0
    )
    sl_list = [{
        "price": sl_price,
        "size_pct": sl_sp,
        "size_usdt": round(initial_capital * sl_sp / 100.0, 2),
    }]

    tp_list: list[dict[str, Any]] = []
    for o in tp_raw:
        price = float(o["price"])
        sp = float(o.get("size_pct") or 0.0)
        tp_list.append({
            "price": price,
            "size_pct": sp,
            "size_usdt": round(initial_capital * sp / 100.0, 2),
        })

    spec = {
        "direction": direction,
        "core_logic": str(nt.get("core_logic") or master.get("narrative") or ""),
        "confidence_score": int(
            (nt.get("confidence_score") or 0)
            if (nt.get("confidence_score") is not None)
            else int(round(float(master.get("confidence") or 0.0) * 100))
        ),
        "break_conditions": list(nt.get("break_conditions") or []),
        "entry_orders": entry_list,
        "stop_loss_orders": sl_list,
        "take_profit_orders": tp_list,
    }
    return spec, []


def _build_spec_v13(
    master: dict[str, Any], l3_grade: str, *, initial_capital: float,
) -> tuple[dict[str, Any], list[str]]:
    """v1.3 schema 映射:trade_plan 各字段 → entry/sl/tp orders。

    v1.3 trade_plan 字段:
      direction, action, entry_price_zone(list 或 单价), stop_loss(单价),
      take_profit_zones(list), position_size_pct(0-1)

    映射:
      total position_usdt = position_size_pct * initial_capital
      entry: 把 entry_price_zone 拆成 N 个挂单(N=len(zone)),平均分仓
        size_pct(per entry)= position_size_pct * 100 / N
        size_usdt(per entry)= position_usdt / N
      stop_loss: 1 个挂单,size 全仓
      take_profit: 把 take_profit_zones N 个 价位转成 N 个挂单
        默认拆分 30/40/30 (3 档),其它数量按等分

    设计权衡:v1.3 trade_plan 没显式 size_pct per entry/tp,这里用启发式
    估值 — 以后 master 输出统一到 v1.4 后,本路径可弃用。
    """
    tp = master.get("trade_plan") or {}
    direction = tp.get("direction")
    entry_zone = tp.get("entry_price_zone")
    sl = tp.get("stop_loss")
    tp_zones = tp.get("take_profit_zones") or tp.get("take_profit") or []
    pos_size_pct = tp.get("position_size_pct")

    missing: list[str] = []
    if direction not in ("long", "short"):
        missing.append("direction")
    if not entry_zone:
        missing.append("entry_price_zone")
    if sl is None:
        missing.append("stop_loss")
    if not tp_zones:
        missing.append("take_profit_zones")
    if pos_size_pct is None:
        missing.append("position_size_pct")
    if missing:
        return {}, missing

    # 归一化 entry_zone → list of prices
    if isinstance(entry_zone, (int, float)):
        entry_prices = [float(entry_zone)]
    else:
        entry_prices = [float(p) for p in entry_zone]
    if not entry_prices:
        return {}, ["entry_price_zone_empty"]

    pos_pct_total = float(pos_size_pct)
    if pos_pct_total <= 1.0:
        pos_pct_total *= 100.0  # 0.33 → 33(百分比)
    pos_usdt_total = round(initial_capital * pos_pct_total / 100.0, 2)

    # entry orders 等分
    n_entry = len(entry_prices)
    per_entry_pct = round(pos_pct_total / n_entry, 4)
    per_entry_usdt = round(pos_usdt_total / n_entry, 2)
    entry_list = [
        {"price": p, "size_pct": per_entry_pct, "size_usdt": per_entry_usdt}
        for p in entry_prices
    ]

    # stop_loss 单挂单,全仓
    sl_price = float(sl)
    sl_list = [{
        "price": sl_price,
        "size_pct": pos_pct_total,
        "size_usdt": pos_usdt_total,
    }]

    # take_profit:启发式权重(3 档:30/40/30;其他档数等分)
    tp_prices = [float(p) for p in tp_zones]
    n_tp = len(tp_prices)
    if n_tp == 3:
        tp_weights = [30.0, 40.0, 30.0]
    else:
        tp_weights = [round(100.0 / n_tp, 2)] * n_tp
    tp_list = []
    for price, weight in zip(tp_prices, tp_weights):
        tp_list.append({
            "price": price,
            "size_pct": round(pos_pct_total * weight / 100.0, 4),
            "size_usdt": round(pos_usdt_total * weight / 100.0, 2),
        })

    # confidence_score
    conf = master.get("confidence")
    confidence_score = int(round(float(conf or 0.0) * 100)) if conf is not None else 70

    spec = {
        "direction": direction,
        "core_logic": str(master.get("narrative") or ""),
        "confidence_score": confidence_score,
        # v1.3 没显式 break_conditions list — 用 master.what_would_change_mind 字符串
        # 拆成 list,或填占位(thesis_manager 不强制 ≥ 3 条;Validator 8 才强制)
        "break_conditions": _v13_break_conditions(master),
        "entry_orders": entry_list,
        "stop_loss_orders": sl_list,
        "take_profit_orders": tp_list,
    }
    return spec, []


def _v13_break_conditions(master: dict[str, Any]) -> list[str]:
    """v1.3 没 break_conditions 字段;尝试从 what_would_change_mind 推导。"""
    raw = master.get("what_would_change_mind")
    if isinstance(raw, list):
        return [str(x) for x in raw if x]
    if isinstance(raw, str) and raw:
        # 用分号 / 或/逗号 切开
        for sep in ("; ", ";", "\n", "/", ","):
            if sep in raw:
                items = [s.strip() for s in raw.split(sep) if s.strip()]
                if items:
                    return items
        return [raw]
    return ["v1.3_master_no_break_conditions_field"]


def _compute_expiry(now_utc: str, days: int) -> str:
    """now_utc + days 天 → ISO 字符串。"""
    try:
        if now_utc.endswith("Z"):
            now = datetime.fromisoformat(now_utc.replace("Z", "+00:00"))
        else:
            now = datetime.fromisoformat(now_utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        now = datetime.now(timezone.utc)
    return (now + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
