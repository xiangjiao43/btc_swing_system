"""src/web_helpers/normalize_state.py — Sprint 1.8.2-A。

把 v12 / v13 strategy_runs.full_state_json 统一成"前端友好 + 已翻译"
schema:
  {
    "schema_version": "v13" | "v12",
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
        if schema_version == "v13":
            normalized = _normalize_v13(state)
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
    """v13 标识:run_mode='ai_orchestrator' 或 state 含 'layers' 键。"""
    if run_mode == "ai_orchestrator":
        return "v13"
    if isinstance(state.get("layers"), dict):
        return "v13"
    return "v12"


# ============================================================
# v13 路径(orchestrator + layers schema)
# ============================================================

def _normalize_v13(state: dict[str, Any]) -> dict[str, Any]:
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
    action_state = state_trans.get("to_state") or "FLAT"
    grade = l3.get("opportunity_grade")
    stance = l2.get("stance")

    summary_card = {
        "action_state_label": labels.translate(labels.MASTER_STATE, action_state),
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

    # 反模式 + 极端事件:从 context_summary 取(orchestrator 写入)
    anti = ctx_summary.get("anti_pattern_signals") or {}
    extreme = ctx_summary.get("extreme_event_flags") or {}

    return {
        "schema_version": "v13",
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
    state_trans = master.get("state_transition") or {}
    trade_plan = master.get("trade_plan") or {}
    pos_final = master.get("position_cap_final") or {}
    narrative = master.get("narrative") or ""
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
    if action_state == "FLIP_WATCH":
        return "刚平仓,反手冷却中"
    if action_state == "POST_PROTECTION_REASSESS":
        return "保护后重新评估"
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
