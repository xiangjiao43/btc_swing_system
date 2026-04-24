"""
pillars.py — Sprint 2.3 Task A:把五层 evidence 拍成"三支柱/四角度"结构,
供前端区域 2 的讲述式讲解使用。

建模对齐:
  §4.2.2 L1 三支柱:趋势强度 / 结构一致性 / 波动率体制
  §4.3.2 L2 三支柱:结构序列 / 相对位置 / 长周期背景
  §4.4.2 L3 不是三支柱,而是"纯规则判档"——输出 matched_rule + downstream_hint
  §4.5.2 L4 三角度:结构性失效位 / 衍生品拥挤度 / 事件窗口
  §4.6.2 L5 四类数据:结构化宏观 / 事件日历 / 定性事件 / 极端事件

输出结构(注入到 state.evidence_reports.layer_N.pillars):
  pillars: [
    {
      id: str,              # 机器可读 id
      name: str,             # 中文名
      value: Any,            # 当前值(可能 null 冷启动)
      interpretation: str,   # 一句中文解读
      status: "ok" | "missing"
    }, ...
  ]

L3 例外,产出:
  pillars: []
  rule_trace: {
    matched_rule: str,      # 规则表匹配到的条件
    grade: "A"|"B"|"C"|"none",
    upgrade_conditions: list[str],  # 升档所需条件
  }

每层额外补:
  core_question: str       # "这层回答什么问题"
  downstream_hint: str     # "给下游的建议"
"""

from __future__ import annotations

import logging
from typing import Any, Optional


logger = logging.getLogger(__name__)


# ============================================================
# Layer 1
# ============================================================

def _pillars_l1(l1: dict[str, Any]) -> dict[str, Any]:
    # 支柱一:趋势强度
    adx = _as_float(l1.get("adx_14_1d") or l1.get("trend_strength"))
    trend_strength_value = adx
    if adx is not None:
        if adx >= 25:
            trend_interp = f"ADX-14={adx:.1f},有效趋势(≥25)"
        elif adx < 20:
            trend_interp = f"ADX-14={adx:.1f},无明显趋势(<20)"
        else:
            trend_interp = f"ADX-14={adx:.1f},趋势过渡区(20-25)"
        trend_status = "ok"
    else:
        trend_interp = "ADX 未就绪(冷启动期,需 20+ 天 1D 数据)"
        trend_status = "missing"

    # 支柱二:结构一致性
    tf = l1.get("timeframe_alignment") or {}
    aligned = tf.get("aligned") if isinstance(tf, dict) else None
    struct_value = tf if isinstance(tf, dict) and tf else None
    if aligned is True:
        struct_interp = "4H/1D/1W 三周期方向一致,结构稳定"
        struct_status = "ok"
    elif aligned is False:
        struct_interp = "4H/1D/1W 三周期方向分歧,过渡期"
        struct_status = "ok"
    else:
        struct_interp = "多周期一致性未计算(需 1W K 线 20+ 根)"
        struct_status = "missing"

    # 支柱三:波动率体制
    vol_level = l1.get("volatility_level") or l1.get("volatility_regime")
    vol_pct = _as_float(l1.get("volatility_percentile"))
    vol_value = vol_level or (f"{vol_pct:.0f}%" if vol_pct is not None else None)
    if vol_level:
        labels = {"low": "低波动(<30 分位)", "normal": "正常波动(30-60)",
                  "elevated": "偏高波动(60-85)", "extreme": "极端波动(≥85)"}
        vol_interp = (
            labels.get(vol_level, vol_level)
            + (f",ATR 分位 {vol_pct:.0f}%" if vol_pct is not None else "")
        )
        vol_status = "ok"
    else:
        vol_interp = "ATR 分位未就绪(需 180 天数据)"
        vol_status = "missing"

    return {
        "core_question": "当前市场性格是什么?趋势性还是震荡性,稳定还是动荡?",
        "pillars": [
            {"id": "trend_strength", "name": "趋势强度",
             "value": trend_strength_value, "interpretation": trend_interp,
             "status": trend_status},
            {"id": "structure_coherence", "name": "结构一致性",
             "value": struct_value, "interpretation": struct_interp,
             "status": struct_status},
            {"id": "volatility_regime", "name": "波动率体制",
             "value": vol_value, "interpretation": vol_interp,
             "status": vol_status},
        ],
        "downstream_hint": _l1_downstream_hint(l1),
    }


def _l1_downstream_hint(l1: dict[str, Any]) -> str:
    regime = l1.get("regime") or l1.get("regime_primary")
    if regime == "trend_up":
        return "trend_up 下 L2 可给 stance=bullish 高置信度;L3 若 phase 合适可直接 A/B"
    if regime == "trend_down":
        return "trend_down 下 L2 可给 stance=bearish;空头仍走 §4.4.5 的 A/B 高门槛"
    if regime in ("range_high", "range_mid", "range_low"):
        return "震荡区间下 L2 倾向 neutral,L3 默认 none,不追趋势"
    if regime in ("transition_up", "transition_down"):
        return "过渡期 L3 最多给 C 档;结构未确认前不可重仓"
    if regime == "chaos":
        return "chaos 强制降级 watch / 冻结开仓"
    return "regime 未就绪,L2 将按动态门槛 unclear 处理(多头 0.65 / 空头 0.70)"


# ============================================================
# Layer 2
# ============================================================

def _pillars_l2(l2: dict[str, Any]) -> dict[str, Any]:
    # 支柱一:结构序列
    sf = l2.get("structure_features") or {}
    if isinstance(sf, dict) and sf:
        hh = sf.get("hh_count") or 0
        hl = sf.get("hl_count") or 0
        lh = sf.get("lh_count") or 0
        ll = sf.get("ll_count") or 0
        latest = sf.get("latest_structure") or "—"
        struct_value = {"hh": hh, "hl": hl, "lh": lh, "ll": ll, "latest": latest}
        if (hh + hl) > (lh + ll):
            struct_interp = f"HH+HL={hh + hl} > LH+LL={lh + ll},多头结构"
        elif (lh + ll) > (hh + hl):
            struct_interp = f"LH+LL={lh + ll} > HH+HL={hh + hl},空头结构"
        else:
            struct_interp = f"多空结构均衡(HH+HL={hh + hl}, LH+LL={lh + ll})"
        struct_status = "ok"
    else:
        struct_value = None
        struct_interp = "swing 结构未识别(需 K 线历史)"
        struct_status = "missing"

    # 支柱二:相对位置(扩展比率 + phase)
    tp = l2.get("trend_position") or {}
    phase = l2.get("phase") or "unclear"
    pct_of_move = tp.get("estimated_pct_of_move") if isinstance(tp, dict) else None
    phase_labels = {
        "early": "早期(<50%)", "mid": "中期(50-100%)",
        "late": "晚期(100-138%)", "exhausted": "衰竭期(>138%)",
        "unclear": "不明确", "n_a": "无明显波段",
    }
    if phase and phase != "unclear" and phase != "n_a":
        pos_interp = phase_labels.get(phase, phase)
        if pct_of_move is not None:
            pos_interp += f",扩展 {pct_of_move:.0f}%"
        pos_status = "ok"
    else:
        pos_interp = "波段位置未确定"
        pos_status = "missing" if phase in ("unclear", "n_a") else "ok"

    # 支柱三:长周期背景
    lcc = l2.get("long_cycle_context") or {}
    cp = lcc.get("cycle_position") if isinstance(lcc, dict) else None
    cp_conf = lcc.get("cycle_confidence") if isinstance(lcc, dict) else None
    cp_labels = {
        "accumulation": "累积期", "early_bull": "牛市早期",
        "mid_bull": "牛市中段", "late_bull": "牛市晚期",
        "distribution": "顶部分发", "early_bear": "熊市早期",
        "mid_bear": "熊市中段", "late_bear": "熊市晚期",
        "unclear": "不明朗",
    }
    if cp and cp != "unclear":
        cycle_interp = (
            cp_labels.get(cp, cp)
            + (f"(置信度 {cp_conf:.2f})" if isinstance(cp_conf, (int, float)) else "")
        )
        cycle_status = "ok"
    else:
        cycle_interp = "周期位置未共识(三主链上指标分歧)"
        cycle_status = "missing"

    return {
        "core_question": "方向偏哪边?当前波段走到第几阶段?",
        "pillars": [
            {"id": "structure_sequence", "name": "结构序列",
             "value": struct_value, "interpretation": struct_interp,
             "status": struct_status},
            {"id": "relative_position", "name": "相对位置",
             "value": phase, "interpretation": pos_interp,
             "status": pos_status},
            {"id": "long_cycle_context", "name": "长周期背景",
             "value": cp, "interpretation": cycle_interp,
             "status": cycle_status},
        ],
        "downstream_hint": _l2_downstream_hint(l2, cp),
    }


def _l2_downstream_hint(l2: dict[str, Any], cp: Optional[str]) -> str:
    stance = l2.get("stance")
    conf = _as_float(l2.get("stance_confidence"))
    # 动态门槛(建模 §4.3.6)
    thresholds = {
        "early_bull": (0.55, 0.75), "mid_bull": (0.60, 0.70),
        "late_bull": (0.65, 0.65), "distribution": (0.70, 0.60),
        "early_bear": (0.75, 0.55), "mid_bear": (0.75, 0.55),
        "late_bear": (0.65, 0.65), "accumulation": (0.60, 0.70),
    }
    long_t, short_t = thresholds.get(cp or "", (0.65, 0.70))
    if stance == "neutral":
        return f"stance=neutral,L3 直接判 none(未达多头 {long_t:.2f} 或空头 {short_t:.2f})"
    if stance == "bullish" and conf is not None:
        return (f"stance=bullish(confidence {conf:.2f} vs 多头门槛 {long_t:.2f})→ "
                + ("达标,L3 可进入 A/B/C 查档" if conf >= long_t
                   else "不达标,L3 判 none"))
    if stance == "bearish" and conf is not None:
        return (f"stance=bearish(confidence {conf:.2f} vs 空头门槛 {short_t:.2f})→ "
                + ("达标,L3 可进入 A/B 查档(空头无 C)" if conf >= short_t
                   else "不达标,L3 判 none"))
    return "L3 将按规则表映射 grade"


# ============================================================
# Layer 3(纯规则层,不是三支柱)
# ============================================================

def _pillars_l3(l3: dict[str, Any], l1: dict[str, Any], l2: dict[str, Any]) -> dict[str, Any]:
    grade = l3.get("opportunity_grade") or l3.get("grade") or "none"
    perm = l3.get("execution_permission") or "watch"
    regime = l1.get("regime") or l1.get("regime_primary")
    stance = l2.get("stance")
    conf = _as_float(l2.get("stance_confidence"))
    phase = l2.get("phase")

    # 反推为什么是这档 + 升档条件
    if grade == "A":
        matched = (f"regime={regime} / stance={stance} (conf {conf:.2f}) / "
                   f"phase={phase} / 位置合适 → A 档")
        upgrade_conditions = ["A 已经是最高档,维持证据直到开仓"]
    elif grade == "B":
        matched = (f"regime={regime} / stance={stance} (conf {conf:.2f}) / "
                   f"phase={phase} → B 档(位置或阶段条件未满足 A)")
        upgrade_conditions = ["phase 进入 early/mid", "位置进入 near_support / mid_range"]
    elif grade == "C":
        matched = (f"规则表匹配 C:{stance} + phase=late + 位置 near_resistance")
        upgrade_conditions = [
            "phase 由 late 回到 early/mid(需回撤)",
            "位置从 near_resistance 走到 mid_range",
            "stance_confidence 提升 0.1 以上",
        ]
    else:  # none
        reasons = []
        if stance == "neutral":
            reasons.append("stance=neutral 不满足任何档")
        elif conf is not None:
            reasons.append(f"stance_confidence={conf:.2f} 未达对应门槛")
        if regime in ("chaos", "transition_up", "transition_down"):
            reasons.append(f"regime={regime},过渡/混乱期 A/B 门槛不开")
        if not reasons:
            reasons.append("无任一 A/B/C 规则匹配")
        matched = "; ".join(reasons)
        upgrade_conditions = [
            "stance_confidence ≥ 多头门槛 0.55(牛市早期)或空头门槛 0.75",
            "regime 稳定(非 chaos / transition_*)",
            "phase 出现 early/mid",
            "CyclePosition 明确(非 unclear)",
        ]

    return {
        "core_question": "是不是好的动手时机?怎么动手?",
        "pillars": [],  # L3 不是三支柱,留空
        "rule_trace": {
            "grade": grade,
            "execution_permission": perm,
            "matched_rule": matched,
            "upgrade_conditions": upgrade_conditions,
            "anti_pattern_flags": l3.get("anti_pattern_flags") or [],
        },
        "downstream_hint": (
            f"grade={grade} / permission={perm} → AI 裁决在此档内决策"
            if grade != "none"
            else "grade=none → AI 强制 watch,不给交易计划"
        ),
    }


# ============================================================
# Layer 4
# ============================================================

def _pillars_l4(
    l4: dict[str, Any],
    composite: dict[str, Any],
) -> dict[str, Any]:
    # 角度一:结构性失效位
    his = l4.get("hard_invalidation_levels") or []
    if his:
        p1 = [h for h in his if h.get("priority") == 1]
        if p1:
            hi_interp = f"P1 结构性失效位:${p1[0].get('price')}(基于 {p1[0].get('basis')})"
        else:
            hi_interp = f"{len(his)} 条失效位已计算"
        hi_value = his
        hi_status = "ok"
    else:
        hi_interp = "失效位未计算(需明确 stance 和 swing 结构)"
        hi_value = None
        hi_status = "missing"

    # 角度二:衍生品拥挤度
    crowding = (composite or {}).get("crowding") or {}
    crowding_score = crowding.get("score")
    if crowding_score is not None:
        if crowding_score >= 6:
            cw_interp = f"Crowding={crowding_score}/8,极度拥挤(→ cap × 0.7)"
        elif crowding_score >= 4:
            cw_interp = f"Crowding={crowding_score}/8,偏拥挤(→ cap × 0.85)"
        else:
            cw_interp = f"Crowding={crowding_score}/8,正常"
        cw_status = "ok"
    else:
        cw_interp = "Crowding 未就绪"
        cw_status = "missing"

    # 角度三:事件窗口
    event_risk = (composite or {}).get("event_risk") or {}
    er_score = event_risk.get("score")
    er_events = event_risk.get("contributing_events") or []
    if er_score is not None:
        if er_score >= 8:
            er_interp = (f"EventRisk={er_score:.0f},≥8 permission 强制 ambush_only"
                         + (f"(最近事件 {er_events[0].get('name', '?')})" if er_events else ""))
        elif er_score >= 4:
            er_interp = f"EventRisk={er_score:.0f},中等(cap × 0.85)"
        else:
            er_interp = f"EventRisk={er_score:.0f},72h 低风险"
        er_status = "ok"
    else:
        er_interp = "EventRisk 未就绪(事件日历需手动维护)"
        er_status = "missing"

    # position_cap 合成过程
    cap_comp = l4.get("position_cap_composition") or {}
    # permission_composition
    perm_comp = l4.get("permission_composition") or {}

    return {
        "core_question": "什么条件下策略失效?有哪些风险?仓位应该多大?",
        "pillars": [
            {"id": "structural_invalidation", "name": "结构性失效位",
             "value": hi_value, "interpretation": hi_interp, "status": hi_status},
            {"id": "crowding", "name": "衍生品拥挤度",
             "value": crowding_score, "interpretation": cw_interp, "status": cw_status},
            {"id": "event_window", "name": "事件窗口",
             "value": er_score, "interpretation": er_interp, "status": er_status},
        ],
        "position_cap_chain": cap_comp,
        "permission_chain": perm_comp,
        "downstream_hint": (
            "AI 裁决的 trade_plan.stop_loss 必须从 hard_invalidation_levels 选"
        ),
    }


# ============================================================
# Layer 5
# ============================================================

def _pillars_l5(l5: dict[str, Any]) -> dict[str, Any]:
    structured = l5.get("structured_macro") or {}
    active_tags = l5.get("active_macro_tags") or []
    event_summaries = l5.get("active_event_summaries") or []
    extreme = bool(l5.get("extreme_event_detected", False))
    stance = l5.get("macro_stance") or l5.get("macro_environment")
    completeness = _as_float(l5.get("data_completeness_pct"))

    # 四类
    if structured:
        pieces = []
        for k in ("DXY", "US10Y", "VIX", "sp500", "nasdaq"):
            v = structured.get(k) or structured.get(k.lower())
            if v is not None:
                pieces.append(f"{k}={v}")
        sm_interp = "; ".join(pieces) if pieces else "已就绪但字段未命名"
        sm_status = "ok"
    else:
        sm_interp = "结构化宏观指标未就绪"
        sm_status = "missing"

    if event_summaries:
        ec_interp = f"未来 72h 含 {len(event_summaries)} 条事件"
        ec_status = "ok"
    else:
        ec_interp = "72h 内无登记事件"
        ec_status = "ok"

    qual_interp = (
        f"AI 定性摘要 {len(event_summaries)} 条" if event_summaries
        else "定性事件摘要 v0.5 启用(当前不产出)"
    )
    qual_status = "ok" if event_summaries else "missing"

    extreme_interp = (
        "已检测到极端事件,触发 PROTECTION 流程" if extreme
        else "未检测到极端事件"
    )
    extreme_status = "ok"

    completeness_warning = None
    if completeness is not None and completeness < 50:
        completeness_warning = f"宏观数据完整度 {completeness:.0f}% < 50%,影响力降级"

    return {
        "core_question": "宏观对当前 BTC 是加分还是减分?有没有极端事件?",
        "pillars": [
            {"id": "structured_macro", "name": "结构化宏观",
             "value": structured, "interpretation": sm_interp, "status": sm_status},
            {"id": "event_calendar", "name": "事件日历",
             "value": event_summaries, "interpretation": ec_interp, "status": ec_status},
            {"id": "qualitative_events", "name": "定性事件摘要",
             "value": None, "interpretation": qual_interp, "status": qual_status},
            {"id": "extreme_event", "name": "极端事件检测",
             "value": extreme, "interpretation": extreme_interp, "status": extreme_status},
        ],
        "macro_stance": stance,
        "adjustment_guidance": l5.get("adjustment_guidance") or {},
        "data_completeness_pct": completeness,
        "completeness_warning": completeness_warning,
        "downstream_hint": (
            "macro_stance 只作修正项,不主导方向;extreme=true 才能硬接管"
        ),
    }


# ============================================================
# 注入
# ============================================================

def inject_pillars(state: dict[str, Any]) -> None:
    """为 state.evidence_reports.layer_{1..5} 就地注入:
       core_question / pillars / downstream_hint / 以及层专属补充字段。
    """
    er = state.get("evidence_reports") or {}
    if not isinstance(er, dict):
        return

    l1 = er.get("layer_1") or {}
    l2 = er.get("layer_2") or {}
    l3 = er.get("layer_3") or {}
    l4 = er.get("layer_4") or {}
    l5 = er.get("layer_5") or {}
    composite = state.get("composite_factors") or {}

    try:
        if isinstance(l1, dict):
            l1.update(_pillars_l1(l1))
        if isinstance(l2, dict):
            l2.update(_pillars_l2(l2))
        if isinstance(l3, dict):
            l3.update(_pillars_l3(l3, l1, l2))
        if isinstance(l4, dict):
            l4.update(_pillars_l4(l4, composite))
        if isinstance(l5, dict):
            l5.update(_pillars_l5(l5))
    except Exception as e:  # pragma: no cover
        logger.warning("inject_pillars failed: %s", e)


def _as_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        return f
    except (TypeError, ValueError):
        return None
