"""src/web_helpers/normalize_state.py — Sprint 1.8.2-A / 1.10-K-B commit 4。

把 v12 / v13 / v14 strategy_runs.full_state_json 统一成"前端友好 + 已翻译"
schema:
  {
    "schema_version": "v14" | "v13" | "v12",
    "summary_card": {action_state_label, stance_label, headline, ...},
    "layer_cards": [{layer, title, label, secondary_labels, summary,
                     key_observations, narrative, contradicting_signals,
                     supporting_data}, ...],
    "anti_patterns_active": ["⚠️ ..."],
    "extreme_events_active": ["🚨 ..."],
    "raw": <原始 state dict,前端不渲染但保留供调试>,
  }

铁律:
- 不重新生成 narrative(AI 已写中文,直接透传)
- 不暴露开发者枚举(全部经 labels.py 翻译)
- 找不到字段返回 None,不抛异常(前端按 None 渲染)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from . import labels


_BJT = ZoneInfo("Asia/Shanghai")


logger = logging.getLogger(__name__)


# ============================================================
# 主入口
# ============================================================

def normalize_state(
    state: dict[str, Any],
    run_mode: Optional[str] = None,
    *,
    generated_at_utc: Optional[str] = None,
) -> dict[str, Any]:
    """v12 / v13 → 统一前端友好 schema。

    Args:
        state: strategy_runs.full_state_json 解析后的 dict(可能 v12 也可能 v13)
        run_mode: strategy_runs.run_mode("ai_orchestrator" 表 v13)
        generated_at_utc: strategy_runs.generated_at_utc(用于 summary_card.decision_time
            转 BJT 显示);若 None 则从 state 内部 fallback
    """
    if not isinstance(state, dict):
        return _empty_normalized("invalid_state")

    schema_version = _detect_schema(state, run_mode)
    try:
        if schema_version in ("v13", "v14"):
            normalized = _normalize_v13(state, schema_version=schema_version)
        else:
            normalized = _normalize_v12(state)
    except Exception as e:
        logger.warning("normalize_state failed (%s): %s", schema_version, e)
        return _empty_normalized(f"normalize_failed_{schema_version}",
                                 raw=state)

    # Sprint 1.8.2-A 修:summary_card.decision_time 用 generated_at_utc 转 BJT
    bjt = _format_bjt(generated_at_utc) if generated_at_utc else None
    if bjt is None:
        bjt = _format_bjt(_decision_time(state))
    normalized["summary_card"]["decision_time"] = bjt

    # Sprint 1.8.2-A:passthrough 前端依赖的 v12 兼容字段(factor_cards / meta)
    if isinstance(state, dict):
        if "factor_cards" in state:
            normalized["factor_cards"] = state["factor_cards"]
        meta = state.get("meta")
        if isinstance(meta, dict):
            normalized["meta"] = meta
    return normalized


def _format_bjt(utc_iso: Optional[str]) -> Optional[str]:
    """UTC ISO 字符串 → 'YYYY-MM-DD HH:MM BJT' 格式;无效返回 None。"""
    if not utc_iso:
        return None
    try:
        s = str(utc_iso).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_BJT).strftime("%Y-%m-%d %H:%M BJT")
    except (ValueError, TypeError):
        return None


# ============================================================
# Schema 检测
# ============================================================

def _detect_schema(state: dict[str, Any], run_mode: Optional[str]) -> str:
    """三态检测(v14 / v13 / v12)。

    优先级:
    1. 显式 state['schema_version'] ∈ {'v14','v13','v12'} → 直接返回
    2. run_mode='ai_orchestrator' 或 state.layers 是 dict → 默认 'v14'
       (1.10-I commit 7 后 ai_orchestrator 默认写 'v14';老数据无 schema_version
       字段时按最新版兜底,layered schema 完全兼容)
    3. else → 'v12'(legacy evidence_reports)
    """
    explicit = state.get("schema_version")
    if explicit in ("v14", "v13", "v12"):
        return explicit
    if run_mode == "ai_orchestrator":
        return "v14"
    if isinstance(state.get("layers"), dict):
        return "v14"
    return "v12"


# ============================================================
# v13 / v14 路径(orchestrator + layers schema)
# v14 schema 与 v13 layered 结构完全兼容;schema_version 字段参数化输出。
# ============================================================

def _normalize_v13(
    state: dict[str, Any], *, schema_version: str = "v14",
) -> dict[str, Any]:
    layers = state.get("layers") or {}
    l1 = layers.get("l1") or {}
    l2 = layers.get("l2") or {}
    l3 = layers.get("l3") or {}
    l4 = layers.get("l4") or {}
    l5 = layers.get("l5") or {}
    master = layers.get("master") or {}
    ctx_summary = state.get("context_summary") or {}

    state_trans = master.get("state_transition") or {}
    trade_plan = master.get("trade_plan") or {}
    grade = l3.get("opportunity_grade")
    stance = l2.get("stance")

    # Sprint K:v1.4 master 用 mode + new_thesis(无 state_transition);
    # action_state 从 mode + new_thesis.direction 推。
    mode = master.get("mode")
    new_thesis = master.get("new_thesis") or {}
    direction = new_thesis.get("direction") if new_thesis else None
    if state_trans.get("to_state"):
        action_state = state_trans.get("to_state")
    else:
        action_state = _derive_v14_action_state(mode, direction)

    # Sprint K:v1.4 路径用 master_mode 当 action_state_label;
    # 老路径继续用 MASTER_STATE 翻 14 档名。
    if mode is not None or new_thesis:
        action_state_label = _build_v14_action_state_label(
            mode, direction, action_state,
        )
    else:
        action_state_label = labels.translate(labels.MASTER_STATE, action_state)

    summary_card = {
        "action_state_label": action_state_label,
        "stance_label": labels.translate(labels.L2_STANCE, stance),
        "headline": _build_headline(action_state, grade, stance),
        "validator_passed": (state.get("validator") or {}).get("passed"),
        "decision_time": _decision_time(state),
        "ai_status": state.get("status"),
    }

    layer_cards = [
        _l1_card_v13(l1, ctx_summary),
        _l2_card_v13(l2, ctx_summary),
        _l3_card_v13(l3, ctx_summary),
        _l4_card_v13(l4, ctx_summary),
        _l5_card_v13(l5, ctx_summary),
        _master_card_v13(master, ctx_summary),
    ]

    anti = ctx_summary.get("anti_pattern_signals") or {}
    extreme = ctx_summary.get("extreme_event_flags") or {}

    out: dict[str, Any] = {
        "schema_version": schema_version,
        "summary_card": summary_card,
        "layer_cards": layer_cards,
        "anti_patterns_active": [
            labels.ANTI_PATTERN_LABELS.get(k, k)
            for k, v in anti.items() if v
        ],
        "extreme_events_active": [
            labels.EXTREME_EVENT_LABELS.get(k, k)
            for k, v in extreme.items() if v
        ],
        "raw": state,
    }

    # Sprint K:从 v1.4 master.new_thesis 派生 trade_plan,前端 cards 兼容。
    if new_thesis:
        out["trade_plan"] = _build_v14_trade_plan(new_thesis, l4)

    # Sprint K:派生 main_strategy(给顶部状态条用),v1.4 / v1.3 双兼容。
    out["main_strategy"] = {
        "action_state": action_state,
        "lifecycle_phase": action_state_label,
        "opportunity_grade": grade or "none",
        "execution_permission": (
            l3.get("execution_permission")
            or (new_thesis.get("execution_permission") if new_thesis else None)
            or "watch"
        ),
        "observation_category": "disciplined",
    }

    return out


def _derive_v14_action_state(
    mode: Optional[str], direction: Optional[str],
) -> str:
    """v1.4 mode + direction → 14 档状态机近似映射(给前端 stateColor 等用)。"""
    if mode == "new_thesis":
        if direction == "long": return "LONG_PLANNED"
        if direction == "short": return "SHORT_PLANNED"
    if mode == "evaluate_existing":
        if direction == "long": return "LONG_HOLD"
        if direction == "short": return "SHORT_HOLD"
    if mode == "protection":
        return "PROTECTION"
    return "FLAT"


def _build_v14_action_state_label(
    mode: Optional[str], direction: Optional[str], action_state: str,
) -> str:
    """v1.4 友好文案 — mode + direction 优先,fallback 14 档名。"""
    if mode == "new_thesis":
        if direction == "long": return "准备做多(还没开)"
        if direction == "short": return "准备做空(还没开)"
    if mode == "evaluate_existing":
        if direction == "long": return "持有多单"
        if direction == "short": return "持有空单"
    if mode and mode in labels.MASTER_MODE:
        return labels.MASTER_MODE[mode]
    return labels.translate(labels.MASTER_STATE, action_state)


def _build_v14_trade_plan(new_thesis: dict, l4: dict) -> dict:
    """从 v1.4 master.new_thesis 派生前端 cards 用 trade_plan 形态。

    前端 cardEntryZones / cardStopLoss / cardTakeProfits / cardPositionCap /
    cardConfidence 等读 state.trade_plan(经 tp() 兜底),原本只 v1.3
    AdjudicatorV1 路径填这字段;Sprint K 给 v1.4 也派生一份。
    """
    entry_orders = new_thesis.get("entry_orders") or []
    entry_zones: list[dict[str, Any]] = []
    for o in entry_orders:
        if not isinstance(o, dict): continue
        p = o.get("price")
        if p is None: continue
        entry_zones.append({
            "price_low": p, "price_high": p,
            "allocation_pct": o.get("size_pct"),
        })
    stop_loss = new_thesis.get("stop_loss") or {}
    sl_price = stop_loss.get("price") if isinstance(stop_loss, dict) else stop_loss
    tp_orders = (new_thesis.get("take_profit")
                 or new_thesis.get("take_profit_orders") or [])
    tp_plan: list[dict[str, Any]] = []
    for t in tp_orders:
        if not isinstance(t, dict): continue
        if t.get("price") is None: continue
        tp_plan.append({
            "price": t.get("price"),
            "size_pct": t.get("size_pct"),
        })
    cs = new_thesis.get("confidence_score")
    if isinstance(cs, (int, float)):
        if cs >= 75: tier = "high"
        elif cs >= 50: tier = "medium"
        else: tier = "low"
    else:
        tier = None
    pos_cap = l4.get("position_cap_pct")
    return {
        "entry_zones": entry_zones,
        "stop_loss": sl_price,
        "take_profit_plan": tp_plan,
        "max_position_size_pct": pos_cap,
        "confidence_tier": tier,
        "confidence_score": cs,
    }


def _l1_card_v13(l1: dict, ctx: dict) -> dict:
    regime = l1.get("regime")
    volatility = l1.get("volatility_regime")
    narrative = l1.get("narrative") or ""
    return {
        "layer": "l1",
        "title": "L1 市场状态",
        "label": labels.translate(labels.L1_REGIME, regime),
        "secondary_labels": [
            labels.translate(labels.L1_VOLATILITY, volatility),
        ],
        "summary": _first_sentence(narrative, max_chars=60),
        "key_observations": l1.get("key_observations") or [],
        "narrative": narrative,
        "contradicting_signals": l1.get("contradicting_signals") or [],
        "supporting_data": _l1_supporting_data(ctx),
        "confidence": l1.get("confidence"),
    }


def _l2_card_v13(l2: dict, ctx: dict) -> dict:
    stance = l2.get("stance")
    phase = l2.get("phase")
    tier = l2.get("stance_confidence_tier")
    narrative = l2.get("narrative") or ""
    return {
        "layer": "l2",
        "title": "L2 方向结构",
        "label": labels.translate(labels.L2_STANCE, stance),
        "secondary_labels": [
            labels.translate(labels.L2_PHASE, phase),
            f"方向可信度:{tier}" if tier else None,
        ],
        "summary": _first_sentence(narrative, max_chars=60),
        "key_observations": l2.get("key_observations") or [],
        "narrative": narrative,
        "contradicting_signals": l2.get("contradicting_signals") or [],
        "supporting_data": _l2_supporting_data(l2, ctx),
        "confidence": l2.get("confidence"),
    }


def _l3_card_v13(l3: dict, ctx: dict) -> dict:
    grade = l3.get("opportunity_grade")
    permission = l3.get("execution_permission")
    narrative = l3.get("narrative") or ""
    return {
        "layer": "l3",
        "title": "L3 机会评级",
        "label": labels.translate(labels.L3_OPPORTUNITY_GRADE, grade),
        "secondary_labels": [
            labels.translate(labels.L3_EXECUTION_PERMISSION, permission),
        ],
        "summary": _first_sentence(narrative, max_chars=60),
        "key_observations": l3.get("key_observations") or [],
        "narrative": narrative,
        "contradicting_signals": l3.get("contradicting_signals") or [],
        "supporting_data": {
            "anti_pattern_flags": {
                "value": l3.get("anti_pattern_flags") or [],
                "explanation": "AI 检测到的反模式列表",
            },
        },
        "confidence": l3.get("confidence"),
    }


def _l4_card_v13(l4: dict, ctx: dict) -> dict:
    risk_tier = l4.get("risk_tier")
    pos_cap = l4.get("position_cap_multiplier")
    narrative = l4.get("narrative") or ""
    return {
        "layer": "l4",
        "title": "L4 风险评估",
        "label": labels.translate(labels.L4_RISK_TIER, risk_tier),
        "secondary_labels": [
            (f"L4 仓位乘数:{pos_cap:.2f}" if isinstance(pos_cap, (int, float))
             else None),
        ],
        "summary": _first_sentence(narrative, max_chars=60),
        "key_observations": l4.get("key_observations") or [],
        "narrative": narrative,
        "contradicting_signals": l4.get("contradicting_signals") or [],
        "supporting_data": _l4_supporting_data(l4),
        "confidence": l4.get("confidence"),
    }


def _l5_card_v13(l5: dict, ctx: dict) -> dict:
    macro_stance = l5.get("macro_stance")
    headwind = l5.get("headwind_score")
    narrative = l5.get("narrative") or ""
    return {
        "layer": "l5",
        "title": "L5 宏观背景",
        "label": labels.translate(labels.L5_MACRO_STANCE, macro_stance),
        "secondary_labels": [
            (f"宏观逆风分数:{headwind}"
             if isinstance(headwind, (int, float)) else None),
        ],
        "summary": _first_sentence(narrative, max_chars=60),
        "key_observations": l5.get("key_observations") or [],
        "narrative": narrative,
        "contradicting_signals": l5.get("contradicting_signals") or [],
        "supporting_data": {
            "extreme_event_detected": {
                "value": l5.get("extreme_event_detected"),
                "explanation": "是否检测到极端事件(如有触发,会强制 PROTECTION)",
            },
            "extreme_event_type": {
                "value": l5.get("extreme_event_type"),
                "explanation": "极端事件类型(若 detected=true)",
            },
        },
        "confidence": l5.get("confidence"),
    }


def _master_card_v13(master: dict, ctx: dict) -> dict:
    """v1.4 master 卡。Sprint K:同时兼容 v1.3(state_transition + trade_plan)
    与 v1.4(mode + new_thesis)两种 schema。

    v1.4 优先识别(`mode` 字段存在),否则 fallback 到 v1.3 路径。
    """
    narrative = master.get("narrative") or ""
    mode = master.get("mode")
    new_thesis = master.get("new_thesis") or {}
    if mode is not None or new_thesis:
        return _master_card_v14(master, ctx, narrative, mode, new_thesis)
    state_trans = master.get("state_transition") or {}
    trade_plan = master.get("trade_plan") or {}
    pos_final = master.get("position_cap_final") or {}
    from_s = state_trans.get("from_state")
    to_s = state_trans.get("to_state")
    return {
        "layer": "master",
        "title": "主裁(综合决策)",
        "label": labels.translate(labels.MASTER_STATE, to_s),
        "secondary_labels": [
            (f"从 {labels.translate(labels.MASTER_STATE, from_s)} → "
             f"{labels.translate(labels.MASTER_STATE, to_s)}"
             if from_s and to_s and from_s != to_s else None),
            (f"最终仓位上限:{pos_final.get('value'):.2%}"
             if isinstance(pos_final.get("value"), (int, float))
             else None),
        ],
        "summary": _first_sentence(narrative, max_chars=80),
        "key_observations": master.get("key_observations") or [],
        "narrative": narrative,
        "contradicting_signals": master.get("counter_arguments") or [],
        "supporting_data": {
            "trade_action": {
                "value": labels.translate(
                    labels.MASTER_ACTION, trade_plan.get("action")),
                "explanation": "本次决策动作",
            },
            "trade_direction": {
                "value": trade_plan.get("direction") or "—",
                "explanation": "做多/做空/无方向",
            },
            "stop_loss": {
                "value": trade_plan.get("stop_loss"),
                "explanation": "止损价位(必须从 L4 hard_invalidation_levels 选)",
            },
            "transition_reasoning": {
                "value": state_trans.get("transition_reasoning"),
                "explanation": "状态迁移理由",
            },
        },
        "confidence": master.get("confidence"),
    }


def _master_card_v14(
    master: dict, ctx: dict, narrative: str, mode: Optional[str],
    new_thesis: dict,
) -> dict:
    """v1.4 master 卡:label 从 mode 翻译,supporting_data 从 new_thesis 抽。"""
    direction = new_thesis.get("direction")
    confidence_score = new_thesis.get("confidence_score")
    entry_orders = new_thesis.get("entry_orders") or []
    stop_loss = new_thesis.get("stop_loss") or {}
    take_profit = (new_thesis.get("take_profit")
                   or new_thesis.get("take_profit_orders") or [])
    label = labels.translate(labels.MASTER_MODE, mode)
    secondary: list[Optional[str]] = []
    if mode == "new_thesis" and direction:
        dir_zh = "做多" if direction == "long" else (
            "做空" if direction == "short" else direction)
        secondary.append(f"{label} → {dir_zh}")
    if isinstance(confidence_score, (int, float)):
        secondary.append(f"信心 {confidence_score}/100")
    return {
        "layer": "master",
        "title": "主裁(综合决策)",
        "label": label,
        "secondary_labels": secondary,
        "summary": _first_sentence(narrative, max_chars=80)
                   or master.get("one_line_summary") or "",
        "key_observations": master.get("key_observations") or [],
        "narrative": narrative,
        "contradicting_signals": (master.get("counter_arguments")
                                  or master.get("contradicting_signals") or []),
        "supporting_data": {
            "mode": {
                "value": label,
                "explanation": "v1.4 master mode(决策模式)",
            },
            "trade_direction": {
                "value": (direction or "—"),
                "explanation": "做多 / 做空 / 无方向",
            },
            "entry_orders": {
                "value": entry_orders,
                "explanation": "分批入场计划(price + size_pct%)",
            },
            "stop_loss": {
                "value": (stop_loss.get("price")
                          if isinstance(stop_loss, dict) else stop_loss),
                "explanation": "止损价位(从 L4 hard_invalidation_levels 选)",
            },
            "take_profit": {
                "value": take_profit,
                "explanation": "分批止盈计划(price + size_pct%)",
            },
            "break_conditions": {
                "value": new_thesis.get("break_conditions") or [],
                "explanation": "破灭条件(任一触发即关闭 thesis)",
            },
        },
        "confidence": (confidence_score / 100.0
                       if isinstance(confidence_score, (int, float))
                       else master.get("confidence")),
    }


# ============================================================
# v13 supporting_data 提取
# ============================================================

def _l1_supporting_data(ctx: dict) -> dict:
    """L1 用 ADX / EMA 关系 / ATR 等。从 context_summary 取(可能空)。"""
    out: dict[str, Any] = {}
    rule_cycle = ctx.get("rule_cycle_position") or {}
    if rule_cycle.get("label"):
        out["rule_cycle_position"] = {
            "value": rule_cycle.get("label"),
            "explanation": "规则版长周期定位(辅助参考)",
        }
    return out


def _l2_supporting_data(l2: dict, ctx: dict) -> dict:
    out: dict[str, Any] = {}
    key_levels = l2.get("key_levels") or {}
    if key_levels:
        out["key_levels"] = {
            "value": key_levels,
            "explanation": "关键价格位(支撑/阻力)",
        }
    long_cycle = l2.get("long_cycle_context") or {}
    if long_cycle:
        out["long_cycle_context"] = {
            "value": long_cycle,
            "explanation": "长周期背景判断(AI 看 cycle_position 是否 agree)",
        }
    return out


def _l4_supporting_data(l4: dict) -> dict:
    out: dict[str, Any] = {}
    hard_inv = l4.get("hard_invalidation_levels") or []
    if hard_inv:
        out["hard_invalidation_levels"] = {
            "value": hard_inv,
            "explanation": "硬失效价位(止损唯一权威)",
        }
    risk_breakdown = l4.get("risk_breakdown") or {}
    if risk_breakdown:
        out["risk_breakdown"] = {
            "value": risk_breakdown,
            "explanation": "结构/拥挤/流动性/事件 各类风险评分",
        }
    return out


# ============================================================
# v12 路径(老 evidence_reports / adjudicator schema)
# ============================================================

def _normalize_v12(state: dict[str, Any]) -> dict[str, Any]:
    """v12 降级显示:旧字段路径,翻译能翻的,翻不到原样保留。"""
    evidence = state.get("evidence_reports") or {}
    l1 = evidence.get("layer_1") or {}
    l2 = evidence.get("layer_2") or {}
    l3 = evidence.get("layer_3") or {}
    l4 = evidence.get("layer_4") or {}
    l5 = evidence.get("layer_5") or {}
    sm = state.get("state_machine") or {}
    adj = state.get("adjudicator") or {}

    action_state = sm.get("current_state") or "FLAT"
    grade = (l3.get("opportunity_grade")
             or adj.get("opportunity_grade") or "none")
    stance = l2.get("stance")

    summary_card = {
        "action_state_label": labels.translate(labels.MASTER_STATE, action_state),
        "stance_label": labels.translate(labels.L2_STANCE, stance),
        "headline": _build_headline(action_state, grade, stance),
        "validator_passed": None,
        "decision_time": (state.get("generated_at_bjt")
                          or state.get("generated_at_utc")),
        "ai_status": (state.get("context_summary") or {}).get("status"),
    }

    layer_cards = [
        _layer_card_v12("l1", "L1 市场状态", l1, labels.L1_REGIME, "regime",
                        secondary_table=labels.L1_VOLATILITY,
                        secondary_field="volatility_regime"),
        _layer_card_v12("l2", "L2 方向结构", l2, labels.L2_STANCE, "stance",
                        secondary_table=labels.L2_PHASE, secondary_field="phase"),
        _layer_card_v12("l3", "L3 机会评级", l3,
                        labels.L3_OPPORTUNITY_GRADE, "opportunity_grade",
                        secondary_table=labels.L3_EXECUTION_PERMISSION,
                        secondary_field="execution_permission"),
        _layer_card_v12("l4", "L4 风险评估", l4,
                        labels.L4_RISK_TIER, "overall_risk_level"),
        _layer_card_v12("l5", "L5 宏观背景", l5,
                        labels.L5_MACRO_STANCE, "macro_environment"),
        {
            "layer": "master",
            "title": "主裁(综合决策)",
            "label": labels.translate(labels.MASTER_STATE, action_state),
            "secondary_labels": [
                labels.translate(labels.MASTER_ACTION, adj.get("action")),
            ],
            "summary": _first_sentence(adj.get("narrative") or "", max_chars=80),
            "key_observations": [],
            "narrative": adj.get("narrative") or adj.get("rationale") or "",
            "contradicting_signals": [],
            "supporting_data": {},
            "confidence": adj.get("confidence"),
        },
    ]

    return {
        "schema_version": "v12",
        "summary_card": summary_card,
        "layer_cards": layer_cards,
        "anti_patterns_active": [],
        "extreme_events_active": [],
        "raw": state,
    }


def _layer_card_v12(
    layer: str, title: str, layer_dict: dict,
    label_table: dict, label_field: str,
    *, secondary_table: Optional[dict] = None,
    secondary_field: Optional[str] = None,
) -> dict:
    label_value = layer_dict.get(label_field)
    secondary = []
    if secondary_table and secondary_field:
        sec_value = layer_dict.get(secondary_field)
        if sec_value is not None:
            secondary.append(labels.translate(secondary_table, sec_value))
    narrative = layer_dict.get("narrative") or ""
    return {
        "layer": layer,
        "title": title,
        "label": labels.translate(label_table, label_value),
        "secondary_labels": secondary,
        "summary": _first_sentence(narrative, max_chars=60),
        "key_observations": layer_dict.get("key_observations") or [],
        "narrative": narrative,
        "contradicting_signals": layer_dict.get("contradicting_signals") or [],
        "supporting_data": {},
        "confidence": layer_dict.get("confidence"),
    }


# ============================================================
# Helpers
# ============================================================

def _build_headline(
    action_state: Optional[str], grade: Optional[str], stance: Optional[str],
) -> str:
    """简单 if/elif 拼装 headline,不调 LLM。"""
    if action_state == "PROTECTION":
        return "保护模式(极端事件,只清仓不开新仓)"
    if action_state in ("LONG_HOLD", "LONG_OPEN"):
        return "持有多单"
    if action_state in ("SHORT_HOLD", "SHORT_OPEN"):
        return "持有空单"
    if action_state == "LONG_TRIM":
        return "多单减仓中"
    if action_state == "SHORT_TRIM":
        return "空单减仓中"
    if action_state in ("LONG_EXIT", "SHORT_EXIT"):
        return "已清仓"
    if action_state == "LONG_PLANNED":
        return "准备做多(等待入场)"
    if action_state == "SHORT_PLANNED":
        return "准备做空(等待入场)"
    # Sprint 1.10-J commit 4b §X(E.1.a 网页层脱钩):
    # 删 FLIP_WATCH / POST_PROTECTION_REASSESS 渲染分支(v1.4 §11.2);
    # state_machine 主体若仍输出这两档,fallthrough 到 FLAT 兜底逻辑显示
    # "空仓观察"(graceful)。state_machine 主体重写留 1.10-K(E.3)。
    # FLAT
    if grade == "A":
        return "建议开仓(高级别机会)"
    if grade == "B":
        return "可考虑开仓(中级别机会)"
    if grade == "C":
        return "保持空仓观察(机会一般)"
    if grade in ("none", "None", None):
        return "保持空仓观察(暂无机会)"
    return "空仓观察"


def _first_sentence(text: str, *, max_chars: int = 60) -> str:
    """从 narrative 提第一个完整句子(以 。/!/?/. 截断),最多 max_chars。"""
    if not text:
        return ""
    s = text.strip()
    for sep in ("。", "!", "?", ". ", "! ", "? "):
        idx = s.find(sep)
        if idx != -1 and idx < max_chars:
            return s[:idx + 1].strip()
    return s[:max_chars].strip() + ("…" if len(s) > max_chars else "")


def _decision_time(state: dict) -> Optional[str]:
    """v13 用 generated_at_bjt;若无,fallback 各种 timestamp。"""
    return (
        state.get("generated_at_bjt")
        or state.get("generated_at_utc")
        or (state.get("context_summary") or {}).get("reference_timestamp_utc")
    )


def _empty_normalized(reason: str, *, raw: Any = None) -> dict[str, Any]:
    return {
        "schema_version": "unknown",
        "summary_card": {
            "action_state_label": "未知",
            "stance_label": "未知",
            "headline": f"数据无法解析({reason})",
            "validator_passed": None,
            "decision_time": None,
            "ai_status": None,
        },
        "layer_cards": [],
        "anti_patterns_active": [],
        "extreme_events_active": [],
        "raw": raw,
    }
