"""
plain_reading.py — Sprint 2.2 Task C:把五层工程字段转成"人话解读"。

为前端 §9.5 的五层摘要提供 plain_reading 字段。
规则层产出,不调 AI,2-3 句浅显中文,不用术语。

每层覆盖至少 6 种典型情况。数据不足时返回统一提示。
"""

from __future__ import annotations

from typing import Any, Optional


def _fmt_pct(v: Optional[float], digits: int = 1) -> str:
    if v is None:
        return "—"
    return f"{v * 100:.{digits}f}%" if abs(v) < 2 else f"{v:.{digits}f}"


def _fmt_conf(v: Any) -> str:
    try:
        f = float(v)
        return f"{f * 100:.0f}%"
    except (TypeError, ValueError):
        return "未知"


# ============================================================
# L1 市场状态
# ============================================================

def plain_reading_l1(layer_1_output: dict[str, Any]) -> str:
    """L1:regime + volatility + stability 三维组合翻译成人话。"""
    if not layer_1_output or layer_1_output.get("health_status") in (
        "error", "cold_start_warming_up",
    ):
        return (
            "市场状态数据不足或处于冷启动期。目前不能判断是趋势期还是震荡期,"
            "也不能确认市场稳定性。建议等更多数据积累后再下结论。"
        )

    regime = (
        layer_1_output.get("regime")
        or layer_1_output.get("regime_primary")
        or "unknown"
    )
    vol = (
        layer_1_output.get("volatility_regime")
        or layer_1_output.get("volatility_level")
        or "unknown"
    )
    stability = layer_1_output.get("regime_stability") or "unknown"

    regime_label = {
        "trend_up":        "上升趋势",
        "trend_down":      "下跌趋势",
        "transition_up":   "向上过渡中(从震荡区间开始突破)",
        "transition_down": "向下过渡中(从震荡区间开始破位)",
        "range_high":      "高位震荡",
        "range_mid":       "中位震荡",
        "range_low":       "低位震荡",
        "chaos":           "混乱态(波动无方向)",
        "unclear_insufficient": "数据不足",
    }.get(regime, str(regime))

    vol_label = {
        "low":      "波动率低",
        "normal":   "波动率正常",
        "elevated": "波动率偏高",
        "extreme":  "波动率极端",
        "unknown":  "波动率未知",
    }.get(vol, vol)

    stability_label = {
        "stable":            "结构稳定",
        "slightly_shifting": "结构轻微变动",
        "actively_shifting": "结构正在主动调整",
        "unstable":          "结构不稳定",
        "unknown":           "稳定性未知",
    }.get(stability, stability)

    # 六种典型组合
    if regime == "chaos":
        return (
            "市场处于混乱态,波动剧烈但没有清晰方向。这不是做多也不是做空的时机,"
            "保持观望,等 ADX 重新上升且价格结构清晰后再考虑。"
        )
    if regime == "unclear_insufficient":
        return (
            "市场状态数据不足(可能冷启动期或数据源延迟)。"
            "目前无法判断趋势或震荡,建议等数据齐全后再评估。"
        )
    if regime == "trend_up" and stability in ("stable", "slightly_shifting"):
        return (
            f"{regime_label},{stability_label}。"
            f"价格结构、成交、{vol_label}三方面一致支持上涨判断,是做多的有利背景。"
        )
    if regime == "trend_down" and stability in ("stable", "slightly_shifting"):
        return (
            f"{regime_label},{stability_label}。"
            f"三维证据一致指向下跌,做空或持币观望是符合纪律的选择。"
        )
    if regime in ("transition_up", "transition_down"):
        return (
            f"市场正在{regime_label}。"
            f"{stability_label},{vol_label}。过渡期信号有滞后,不建议在未确认前重仓。"
        )
    if regime.startswith("range"):
        return (
            f"市场{regime_label},{vol_label}。"
            "震荡期更适合区间交易或保持观望,而不是追趋势。"
        )
    # 兜底
    return f"市场 {regime_label},{stability_label},{vol_label}。"


# ============================================================
# L2 方向结构
# ============================================================

def plain_reading_l2(layer_2_output: dict[str, Any]) -> str:
    if not layer_2_output or layer_2_output.get("health_status") in (
        "error", "cold_start_warming_up",
    ):
        return (
            "方向判断数据不足或冷启动期。多空置信度都未达到门槛,"
            "系统按纪律保持中性观望。"
        )

    stance = layer_2_output.get("stance") or "neutral"
    conf_raw = layer_2_output.get("stance_confidence")
    try:
        conf = float(conf_raw) if conf_raw is not None else None
    except (TypeError, ValueError):
        conf = None
    phase = layer_2_output.get("phase") or "n_a"

    stance_label = {"bullish": "看多", "bearish": "看空", "neutral": "方向不明"}.get(
        stance, stance,
    )
    phase_label = {
        "early":     "趋势初段",
        "mid":       "趋势中段",
        "late":      "趋势末段",
        "exhausted": "衰竭期",
        "n_a":       "波段位置不明",
    }.get(phase, phase)

    if stance == "neutral":
        return (
            f"方向不明,信心 {_fmt_conf(conf)}。"
            "做多和做空门槛均未达到,系统不给方向性建议,保持观望。"
        )

    if conf is not None and conf < 0.55:
        return (
            f"当前信号偏{stance_label},但信心仅 {_fmt_conf(conf)},"
            "低于开仓门槛。建议只观察,不下单。"
        )

    if stance == "bullish" and phase in ("early", "mid"):
        return (
            f"倾向看多,信心 {_fmt_conf(conf)},当前波段{phase_label}。"
            "位置相对合理,如果机会层给出高/中等级机会,可以按计划分层入场。"
        )
    if stance == "bullish" and phase == "late":
        return (
            f"倾向看多,但波段已到末段(信心 {_fmt_conf(conf)})。"
            "追涨风险大,更合理的策略是等待深回撤或干脆放弃这波。"
        )
    if stance == "bearish":
        return (
            f"倾向看空,信心 {_fmt_conf(conf)},波段{phase_label}。"
            "做空门槛比做多严,若机会层同时给出高/中等级空头机会,可以考虑顺势。"
        )
    return f"方向:{stance_label}({_fmt_conf(conf)}),阶段:{phase_label}。"


# ============================================================
# L3 机会执行
# ============================================================

def plain_reading_l3(layer_3_output: dict[str, Any]) -> str:
    if not layer_3_output:
        return (
            "机会评级未能产出(数据不足)。"
        )

    grade = (
        layer_3_output.get("opportunity_grade")
        or layer_3_output.get("grade")
        or "none"
    )
    perm = layer_3_output.get("execution_permission") or "watch"
    anti = layer_3_output.get("anti_pattern_flags") or []

    perm_label = {
        "can_open":      "可以开仓",
        "cautious_open": "谨慎开仓",
        "ambush_only":   "只允许埋伏单",
        "no_chase":      "不追单",
        "hold_only":     "仅持仓不开新",
        "watch":         "仅观察,不开仓",
        "protective":    "保护性减仓",
    }.get(perm, perm)

    if grade == "A":
        base = (
            f"高等级机会(信心高),执行许可:{perm_label}。"
            "这是系统判定的最高等级机会,交易计划按满仓配置给出。"
        )
    elif grade == "B":
        base = (
            f"中等级机会(信心中),执行许可:{perm_label}。"
            "门槛比高等级宽但仍然可行,交易计划按 70% 仓位给出。"
        )
    elif grade == "C":
        base = (
            f"低等级参考机会(信心低),执行许可:{perm_label}。"
            "交易计划按 40% 仓位给出,不建议重仓;等条件升到中等级再加码。"
        )
    elif grade == "none":
        base = (
            "当前没有符合条件的交易机会。"
            f"不是'不会涨',只是条件不满足任何机会档位的门槛 — {perm_label}。"
        )
    else:
        base = f"机会评级:{grade},执行许可:{perm_label}。"

    if anti:
        base += f" 触发 {len(anti)} 条反模式:{', '.join(map(str, anti[:3]))}。"
    return base


# ============================================================
# L4 风险失效
# ============================================================

def plain_reading_l4(layer_4_output: dict[str, Any]) -> str:
    if not layer_4_output:
        return "风险层未能产出(数据不足)。"

    overall = layer_4_output.get("overall_risk_level") or "unknown"
    cap = layer_4_output.get("position_cap")
    perm = (
        layer_4_output.get("execution_permission")
        or layer_4_output.get("risk_permission")
        or "watch"
    )
    his = layer_4_output.get("hard_invalidation_levels") or []

    risk_label = {
        "low":      "整体风险低",
        "moderate": "整体风险适中",
        "elevated": "整体风险偏高",
        "high":     "整体风险高",
        "critical": "整体风险严重",
        "unknown":  "风险档位未知",
    }.get(overall, overall)

    cap_pct = f"{float(cap) * 100:.1f}%" if cap is not None else "未知"

    if overall == "critical":
        return (
            f"{risk_label}。建议仓位上限压到 {cap_pct},不开新仓。"
            "优先平仓或执行保护流程。"
        )
    if overall in ("high", "elevated"):
        base = (
            f"{risk_label},建议仓位上限压到 {cap_pct}。"
            "开仓必须有明确失效位,且严格按止损价执行。"
        )
    else:
        base = (
            f"{risk_label}。建议仓位上限 {cap_pct},"
            "在此范围内按机会等级分配仓位。"
        )

    if his:
        lvl1 = [h for h in his if h.get("priority") == 1]
        if lvl1:
            p = lvl1[0].get("price")
            base += f" 结构性失效位在 {p}(优先级 1,4H 收盘确认)。"
    return base


# ============================================================
# L5 背景事件
# ============================================================

def plain_reading_l5(layer_5_output: dict[str, Any]) -> str:
    if not layer_5_output:
        return "宏观环境数据不足。"

    stance = (
        layer_5_output.get("macro_stance")
        or layer_5_output.get("macro_environment")
        or "unclear"
    )
    headwind_val = layer_5_output.get("macro_headwind_score")
    extreme = bool(layer_5_output.get("extreme_event_detected", False))
    completeness = layer_5_output.get("data_completeness_pct")

    if extreme:
        return (
            "极端宏观事件已检测到。系统会冻结新开仓,按 PROTECTION 流程处理存量仓位。"
        )

    stance_label = {
        "risk_on":         "风险偏好(顺风)",
        "risk_neutral":    "中性",
        "risk_off":        "避险(逆风)",
        "extreme_risk_off": "极端避险",
        "neutral":         "中性",
        "unclear":         "不明",
    }.get(stance, stance)

    if stance == "extreme_risk_off":
        return (
            "宏观环境处于极端避险模式。风险资产几乎无承接盘,"
            "系统硬性禁止新开仓,等宏观环境缓和后再考虑。"
        )
    if stance == "risk_off":
        return (
            f"宏观环境{stance_label}。DXY / US10Y / VIX 里至少一项在警戒区间,"
            f"建议仓位上限受逆风系数压低。"
        )
    if stance == "risk_on":
        return (
            f"宏观环境{stance_label}。对 BTC 是顺风,"
            "如果市场状态、方向判断、机会档也都偏多,可以适度放开仓位。"
        )
    if stance in ("risk_neutral", "neutral"):
        return (
            f"宏观中性。对 BTC 不构成明显顺风或逆风,主要看市场内部信号。"
        )
    # Fallback
    if completeness is not None and float(completeness) < 50:
        return (
            f"宏观数据完整度仅 {completeness:.0f}%,"
            "暂无法给出稳定判断,建议只把它当参考而不当决策依据。"
        )
    return f"宏观:{stance_label}。"


# ============================================================
# 批量注入
# ============================================================

def inject_plain_readings(state: dict[str, Any]) -> None:
    """就地把 plain_reading 字段塞进 state['evidence_reports']['layer_N']。"""
    er = state.get("evidence_reports") or {}
    if not isinstance(er, dict):
        return
    _pairs = [
        ("layer_1", plain_reading_l1),
        ("layer_2", plain_reading_l2),
        ("layer_3", plain_reading_l3),
        ("layer_4", plain_reading_l4),
        ("layer_5", plain_reading_l5),
    ]
    for key, fn in _pairs:
        layer_out = er.get(key) or {}
        if isinstance(layer_out, dict):
            layer_out["plain_reading"] = fn(layer_out)
            er[key] = layer_out
