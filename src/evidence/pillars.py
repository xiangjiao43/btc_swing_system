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
        return "上升趋势已确立,系统会判定倾向看多;如果波段位置合适,可能直接给出高/中等级机会"
    if regime == "trend_down":
        return "下跌趋势已确立,系统会判定倾向看空;但做空门槛比做多更高,需要更明确的证据"
    if regime in ("range_high", "range_mid", "range_low"):
        return "市场处于震荡区间,系统倾向方向不明,默认不给机会档,不追趋势"
    if regime in ("transition_up", "transition_down"):
        return "趋势在转向但还没站稳,系统最多给低等级参考机会;结构未确认前不可重仓"
    if regime == "chaos":
        return "市场失序,系统强制只观察、冻结开仓"
    return "市场状态尚未就绪,系统会按保守阈值处理(做多信心 65%,做空信心 70%)"


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
        return (f"方向不明,系统目前不给机会档"
                f"(做多信心要超过 {long_t*100:.0f}%,做空要超过 {short_t*100:.0f}%)")
    if stance == "bullish" and conf is not None:
        return (f"倾向看多,信心 {conf*100:.0f}% vs 多头门槛 {long_t*100:.0f}% → "
                + ("达标,系统会进入机会档评估" if conf >= long_t
                   else "未达标,系统不给机会档"))
    if stance == "bearish" and conf is not None:
        return (f"倾向看空,信心 {conf*100:.0f}% vs 空头门槛 {short_t*100:.0f}% → "
                + ("达标,系统会进入机会档评估(做空无低等级参考档)" if conf >= short_t
                   else "未达标,系统不给机会档"))
    return "系统会按规则表映射出机会档位"


# ============================================================
# Layer 3(纯规则层,不是三支柱)
# ============================================================

_REGIME_HUMAN: dict[str, str] = {
    "trend_up": "上升趋势确立",
    "trend_down": "下跌趋势确立",
    "transition_up": "趋势在转向多头但还没站稳",
    "transition_down": "趋势在转向空头但还没站稳",
    "range_high": "高位震荡",
    "range_mid": "中位震荡",
    "range_low": "低位震荡",
    "chaos": "市场失序",
    "unclear_insufficient": "数据不足",
}

_STANCE_HUMAN: dict[str, str] = {
    "bullish": "倾向看多",
    "bearish": "倾向看空",
    "neutral": "方向不明",
}

_PHASE_HUMAN: dict[str, str] = {
    "early": "趋势初段",
    "mid": "趋势中段",
    "late": "趋势末段",
    "exhausted": "衰竭期",
    "unclear": "波段位置不明",
    "n_a": "波段位置不明",
}

_PERM_HUMAN: dict[str, str] = {
    "can_open": "可以开仓",
    "cautious_open": "谨慎开仓",
    "ambush_only": "只允许埋伏单",
    "no_chase": "不追单",
    "hold_only": "仅持仓不开新",
    "watch": "仅观察,不开仓",
    "protective": "保护性减仓",
}

_GRADE_HUMAN: dict[str, str] = {
    "A": "高等级机会(信心高)",
    "B": "中等级机会(信心中)",
    "C": "低等级参考机会(信心低)",
    "none": "暂无符合条件的机会",
}


def _humanize(d: dict[str, str], v: Any) -> str:
    return d.get(v or "", str(v) if v else "—")


def _pillars_l3(l3: dict[str, Any], l1: dict[str, Any], l2: dict[str, Any]) -> dict[str, Any]:
    grade = l3.get("opportunity_grade") or l3.get("grade") or "none"
    perm = l3.get("execution_permission") or "watch"
    regime = l1.get("regime") or l1.get("regime_primary")
    stance = l2.get("stance")
    conf = _as_float(l2.get("stance_confidence"))
    phase = l2.get("phase")

    regime_h = _humanize(_REGIME_HUMAN, regime)
    stance_h = _humanize(_STANCE_HUMAN, stance)
    phase_h = _humanize(_PHASE_HUMAN, phase)
    perm_h = _humanize(_PERM_HUMAN, perm)
    grade_h = _humanize(_GRADE_HUMAN, grade)
    conf_str = f"{conf*100:.0f}%" if conf is not None else "—"

    # 反推为什么是这档 + 升档条件
    if grade == "A":
        matched = (f"市场处于{regime_h},{stance_h}(信心 {conf_str}),"
                   f"波段处于{phase_h},位置合适 — 满足高等级机会的全部条件")
        upgrade_conditions = ["已经是最高等级,维持现有证据直到开仓即可"]
    elif grade == "B":
        matched = (f"市场处于{regime_h},{stance_h}(信心 {conf_str}),"
                   f"波段处于{phase_h} — 满足中等级机会(位置或阶段未达高等级)")
        upgrade_conditions = ["波段进入趋势初段或中段", "价格回到关键支撑附近或区间中段"]
    elif grade == "C":
        matched = (f"{stance_h} + 波段处于趋势末段 + 价格靠近阻力位 — 仅给低等级参考机会")
        upgrade_conditions = [
            "波段从末段回到初段或中段(需要一次回撤)",
            "价格从阻力位附近回到区间中段",
            "做多/做空信心提升 10 个百分点以上",
        ]
    else:  # none
        reasons = []
        if stance == "neutral":
            reasons.append("方向不明,不满足任何机会档位的条件")
        elif conf is not None:
            reasons.append(f"做多/做空信心 {conf_str} 未达对应门槛")
        if regime in ("chaos", "transition_up", "transition_down"):
            reasons.append(f"市场处于{regime_h},过渡或混乱期不开高/中等级机会")
        if not reasons:
            reasons.append("没有任何机会档位的规则被命中")
        matched = ";".join(reasons)
        upgrade_conditions = [
            "做多信心达到 55% 以上(牛市早期门槛),或做空信心达到 75%",
            "市场状态稳定(不再是失序或过渡期)",
            "波段进入趋势初段或中段",
            "长周期位置明确(不再是周期不明朗)",
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
            f"机会等级:{grade_h};执行许可:{perm_h} — 系统会在此档位内做综合决策"
            if grade != "none"
            else "暂无符合条件的机会,系统强制观望,不下交易计划。证据真不够,这是按规则执行的纪律,不是判断保守。"
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
            cw_interp = f"拥挤度 {crowding_score}/8 极度拥挤,建议仓位上限收紧到 70%"
        elif crowding_score >= 4:
            cw_interp = f"拥挤度 {crowding_score}/8 偏拥挤,仓位上限轻度下调(× 85%)"
        else:
            cw_interp = f"拥挤度 {crowding_score}/8 正常,不收紧仓位"
        cw_status = "ok"
    else:
        cw_interp = "拥挤度数据未就绪"
        cw_status = "missing"

    # 角度三:事件窗口
    event_risk = (composite or {}).get("event_risk") or {}
    er_score = event_risk.get("score")
    er_events = event_risk.get("contributing_events") or []
    if er_score is not None:
        if er_score >= 8:
            er_interp = (f"风险事件密度 {er_score:.0f} 偏高,系统只允许埋伏单,不主动开仓"
                         + (f"(最近事件 {er_events[0].get('name', '?')})" if er_events else ""))
        elif er_score >= 4:
            er_interp = f"风险事件密度 {er_score:.0f} 中等,仓位上限轻度下调(× 85%)"
        else:
            er_interp = f"风险事件密度 {er_score:.0f},未来 72 小时风险低"
        er_status = "ok"
    else:
        er_interp = "事件风险数据未就绪(事件日历需手动维护)"
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
            "系统的止损价必须从这里给出的结构性失效位中选,不能另设"
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
        completeness_warning = f"宏观数据完整度 {completeness:.0f}% < 50%,系统降低宏观信号权重"

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
            "宏观环境只作为仓位修正,不直接决定方向;只有检测到极端宏观事件时才会强制保护"
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
