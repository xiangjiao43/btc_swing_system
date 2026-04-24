"""
composite_composition.py — Sprint 2.3 Task A:为 6 个组合因子补 composition /
rule_description / value_interpretation / affects_layer 四个字段,给前端
区域 3 做讲述式展示。

建模对齐 §3.8.1-§3.8.6。

注入到 state.composite_factors[key] 就地扩展字段,不改原值。
"""

from __future__ import annotations

import logging
from typing import Any, Optional


logger = logging.getLogger(__name__)


def _as_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _lookup(d: Any, key: str, default=None) -> Any:
    if isinstance(d, dict):
        return d.get(key, default)
    return default


# ============================================================
# TruthTrend(§3.8.1,L1+L2,0-9 分)
# ============================================================

def _truth_trend(tt: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    score = _as_float(tt.get("score"))
    band = tt.get("band")
    l1 = ctx.get("l1") or {}
    # composition:影响这个分数的底层因子当前值
    composition = [
        {
            "factor_id": "price_adx_14_1d",
            "name": "ADX-14(1D)",
            "value": _as_float(l1.get("adx_14_1d") or l1.get("trend_strength")),
            "weight": 0.30,
            "role": "主权重(≥25 +2 / ≥20 +1)",
        },
        {
            "factor_id": "price_adx_14_4h",
            "name": "ADX-14(4H)",
            "value": _as_float(l1.get("adx_14_4h")),
            "weight": 0.15,
            "role": "辅助(≥20 +1)",
        },
        {
            "factor_id": "price_tf_alignment",
            "name": "多周期方向一致性",
            "value": _lookup(l1.get("timeframe_alignment"), "aligned"),
            "weight": 0.25,
            "role": "过滤器(三周期一致 +3)",
        },
        {
            "factor_id": "price_ma_stack",
            "name": "MA-20/60/120 排列",
            "value": _lookup(l1.get("ma_alignment"), "direction"),
            "weight": 0.15,
            "role": "趋势确认(正确排列 +2)",
        },
        {
            "factor_id": "price_ma_200_relation",
            "name": "价格相对 MA-200",
            "value": _lookup(l1.get("ma_200_relation"), "above"),
            "weight": 0.15,
            "role": "长期趋势确认(方向一致 +1)",
        },
    ]
    if score is None:
        interp = "未就绪"
    elif score >= 6:
        interp = f"{score}/9 真趋势,下游可给高置信度方向判断"
    elif score >= 4:
        interp = f"{score}/9 弱趋势,谨慎跟进"
    else:
        interp = f"{score}/9 无趋势,以区间思路为主"
    return {
        "composition": composition,
        "rule_description": (
            "ADX 主权重 + 多周期方向一致性过滤 + MA 排列修正,累加 0-9 分;"
            "≥6 真趋势 / 4-5 弱 / ≤3 无"
        ),
        "value_interpretation": interp,
        "affects_layer": "L1 regime 判定 + L2 stance_confidence 轻度修正",
    }


# ============================================================
# BandPosition(§3.8.2,L2 phase)
# ============================================================

def _band_position(bp: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    phase = bp.get("phase") or bp.get("band")
    conf = _as_float(bp.get("phase_confidence"))
    l2 = ctx.get("l2") or {}
    tp = _lookup(l2, "trend_position") or {}
    pct = _lookup(tp, "estimated_pct_of_move")

    composition = [
        {
            "factor_id": "price_swing_extension_ratio",
            "name": "Swing 扩展比率",
            "value": pct,
            "weight": 0.35,
            "role": "主(< 50% early / 50-100% mid / 100-138% late / > 138% exhausted)",
        },
        {
            "factor_id": "price_swing_sequence",
            "name": "Swing 序列(HH+HL vs LH+LL)",
            "value": _lookup(l2.get("structure_features"), "latest_structure"),
            "weight": 0.25,
            "role": "结构一致性(HH+HL → early/mid / LH+LL → late/exhausted)",
        },
        {
            "factor_id": "price_ma_60_distance",
            "name": "距 MA-60 距离",
            "value": _lookup(l2, "ma_60_distance_pct"),
            "weight": 0.20,
            "role": "位置修正(贴近 → early/mid,远离 → late)",
        },
        {
            "factor_id": "price_pullback_depth",
            "name": "最近回撤深度",
            "value": _lookup(l2, "latest_pullback_depth"),
            "weight": 0.20,
            "role": "位置修正(> 0.5 回撤 +early / < 0.2 +late)",
        },
    ]
    phase_labels = {
        "early": "早期,回撤充足,性价比高",
        "mid": "中期,主升浪,仍可跟进",
        "late": "晚期,追涨风险大",
        "exhausted": "衰竭期,反向概率升高",
        "unclear": "位置不明",
        "n_a": "无明显波段",
    }
    interp = (
        phase_labels.get(phase, phase or "—")
        + (f"(confidence {conf:.2f})" if conf is not None else "")
    )
    return {
        "composition": composition,
        "rule_description": (
            "v1.2 只用价格几何:扩展比率主 + swing 序列 + MA 距离 + 回撤深度;"
            "最高得分 phase 胜出"
        ),
        "value_interpretation": interp,
        "affects_layer": "L2.phase → L3 规则表查档",
    }


# ============================================================
# CyclePosition(§3.8.4,L2 长周期)
# ============================================================

def _cycle_position(cp: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    pos = cp.get("cycle_position") or cp.get("band")
    conf = _as_float(cp.get("cycle_confidence"))
    onchain = ctx.get("onchain") or {}

    def _latest(series_key: str) -> Any:
        import pandas as pd
        s = onchain.get(series_key) if isinstance(onchain, dict) else None
        if s is None:
            return None
        try:
            c = s.dropna() if hasattr(s, "dropna") else None
            if c is None or (hasattr(c, "empty") and c.empty):
                return None
            return round(float(c.iloc[-1]), 3)
        except Exception:
            return None

    # ATH 跌幅
    klines_1d = ctx.get("klines_1d")
    ath_dd = None
    try:
        if klines_1d is not None and hasattr(klines_1d, "empty") and not klines_1d.empty:
            closes = klines_1d["close"].astype(float)
            ath_dd = (float(closes.iloc[-1]) / float(closes.max()) - 1.0) * 100.0
    except Exception:
        pass

    composition = [
        {"factor_id": "onchain_mvrv_z", "name": "MVRV Z-Score",
         "value": _latest("mvrv_z_score"), "weight": 0.35,
         "role": "主(< -0.5 accumulation / 2-4 mid_bull / > 6 distribution)"},
        {"factor_id": "onchain_nupl", "name": "NUPL",
         "value": _latest("nupl"), "weight": 0.30,
         "role": "主(< 0 底 / 0.5-0.65 晚牛 / > 0.65 分发)"},
        {"factor_id": "onchain_lth_supply", "name": "LTH Supply 90d 变化",
         "value": None, "weight": 0.25,
         "role": "主(> +2% 增持 / < -3% 减持)"},
        {"factor_id": "price_drawdown_from_ath", "name": "距 ATH 跌幅",
         "value": (round(ath_dd, 2) if ath_dd is not None else None),
         "weight": 0.10,
         "role": "辅助(early_bear 需跌幅 > 20%)"},
    ]
    labels = {
        "accumulation": "累积期,底部吸筹,做多性价比极高",
        "early_bull": "牛市早期,做多最佳窗口",
        "mid_bull": "牛市中段,仍可持仓",
        "late_bull": "牛市晚期,开始减仓",
        "distribution": "顶部分发,空头布局期",
        "early_bear": "熊市早期,做空或观望",
        "mid_bear": "熊市中段,现金为王",
        "late_bear": "熊市晚期,开始关注底部信号",
        "unclear": "周期不明朗,保守观望",
    }
    interp = (
        labels.get(pos, pos or "—")
        + (f"(confidence {conf:.2f})" if conf is not None else "")
    )
    return {
        "composition": composition,
        "rule_description": (
            "三主指标各自映射 9 档候选;辅助条件否决;投票决定最终档位。"
            "三票一致 conf=0.85 / 两票一致 conf=0.60 / 分歧 → unclear"
        ),
        "value_interpretation": interp,
        "affects_layer": "L2.动态门槛表(多头 / 空头门槛按周期档位调整)",
    }


# ============================================================
# Crowding(§3.8.3,L4 拥挤)
# ============================================================

def _crowding(cr: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    score = cr.get("score")
    band = cr.get("band")
    derivatives = ctx.get("derivatives") or {}

    def _latest(k: str):
        s = derivatives.get(k) if isinstance(derivatives, dict) else None
        if s is None:
            return None
        try:
            c = s.dropna() if hasattr(s, "dropna") else None
            if c is None or (hasattr(c, "empty") and c.empty):
                return None
            return round(float(c.iloc[-1]), 4)
        except Exception:
            return None

    composition = [
        {"factor_id": "derivatives_funding_rate_current", "name": "资金费率 · 当前",
         "value": _latest("funding_rate"), "weight": 0.30,
         "role": "> 0.03% 连续 3 次 → +2"},
        {"factor_id": "derivatives_funding_rate_30d_pctile",
         "name": "资金费率 30 日分位", "value": None, "weight": 0.20,
         "role": "> 85 分位 → +2"},
        {"factor_id": "derivatives_oi_24h_change", "name": "OI 24h 变化",
         "value": None, "weight": 0.15,
         "role": "> +15% → +1"},
        {"factor_id": "derivatives_top_long_short_ratio",
         "name": "大户多空比", "value": _latest("long_short_ratio"), "weight": 0.15,
         "role": "> 2.5 → +1"},
        {"factor_id": "derivatives_basis", "name": "基差年化",
         "value": _latest("basis"), "weight": 0.10,
         "role": "> 20% → +1"},
        {"factor_id": "derivatives_put_call", "name": "Put/Call Ratio",
         "value": _latest("put_call_ratio"), "weight": 0.10,
         "role": "< 0.5 → +1(多头情绪热)"},
    ]
    if score is None:
        interp = "未就绪"
    elif score >= 6:
        interp = f"{score}/8 极度拥挤,position_cap × 0.7(band={band or '—'})"
    elif score >= 4:
        interp = f"{score}/8 偏拥挤,position_cap × 0.85"
    else:
        interp = f"{score}/8 正常,无压缩"
    return {
        "composition": composition,
        "rule_description": (
            "多头拥挤对称空头:六项阈值加权累加 0-8 分;"
            "≥6 极度(× 0.7)/ 4-5 偏拥挤(× 0.85)/ ≤3 正常"
        ),
        "value_interpretation": interp,
        "affects_layer": "L4.position_cap × crowding_multiplier + active_risk_tags",
    }


# ============================================================
# MacroHeadwind(§3.8.5,L5)
# ============================================================

def _macro_headwind(mh: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    score = _as_float(mh.get("score"))
    band = mh.get("band")
    macro = ctx.get("macro") or {}

    def _latest(k: str):
        s = macro.get(k) if isinstance(macro, dict) else None
        if s is None:
            return None
        try:
            c = s.dropna() if hasattr(s, "dropna") else None
            if c is None or (hasattr(c, "empty") and c.empty):
                return None
            return round(float(c.iloc[-1]), 3)
        except Exception:
            return None

    composition = [
        {"factor_id": "macro_dxy_20d_change", "name": "DXY 20 日变化",
         "value": None, "weight": 0.30, "role": "> +2% → -2 分"},
        {"factor_id": "macro_us10y_30d_change", "name": "US10Y 30 日变化",
         "value": None, "weight": 0.25, "role": "> +30bp → -2 分"},
        {"factor_id": "macro_vix_current", "name": "VIX 当前",
         "value": _latest("vix"), "weight": 0.25,
         "role": "> 25 → -2 / < 15 → 加分"},
        {"factor_id": "macro_nasdaq_20d", "name": "纳指 20 日变化",
         "value": None, "weight": 0.20,
         "role": "< -5% → -2 / > +5% → +2"},
        {"factor_id": "macro_btc_nasdaq_corr", "name": "BTC-纳指 60d 相关性",
         "value": None, "weight": 0,
         "role": "权重乘数(> 0.7 时美宏影响 × 1.5)"},
    ]
    if score is None:
        interp = "未就绪"
    elif score <= -5:
        interp = f"{score} 强逆风,position_cap × 0.7"
    elif score <= -2:
        interp = f"{score} 轻度逆风,position_cap × 0.85"
    elif score >= 3:
        interp = f"+{score} 顺风"
    else:
        interp = f"{score} 中性"
    return {
        "composition": composition,
        "rule_description": (
            "五项宏观指标加权累加 -10 到 +10;"
            "≤-5 强逆风 / -4~-2 轻度 / ≥-1 中性+顺风"
        ),
        "value_interpretation": interp,
        "affects_layer": "L5.macro_headwind_score → position_cap 乘数 + permission 建议",
    }


# ============================================================
# EventRisk(§3.8.6,L4)
# ============================================================

def _event_risk(er: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    score = _as_float(er.get("score"))
    events = er.get("contributing_events") or []
    nearest = events[0] if events else {}

    composition = [
        {"factor_id": "event_fomc_next", "name": "下次 FOMC 距离",
         "value": nearest.get("hours_to") if nearest.get("type") == "fomc" else None,
         "weight": 0.35,
         "role": "重要度 4;24h 内 × 1.5 / 24-48h × 1.0 / 48-72h × 0.5"},
        {"factor_id": "event_cpi_next", "name": "下次 CPI 距离",
         "value": nearest.get("hours_to") if nearest.get("type") == "cpi" else None,
         "weight": 0.25, "role": "重要度 3;时间衰减同上"},
        {"factor_id": "event_nfp_next", "name": "下次 NFP 距离",
         "value": nearest.get("hours_to") if nearest.get("type") == "nfp" else None,
         "weight": 0.20, "role": "重要度 3;时间衰减同上"},
        {"factor_id": "event_options_expiry", "name": "期权大到期",
         "value": nearest.get("hours_to") if nearest.get("type") == "options_expiry_major" else None,
         "weight": 0.10, "role": "重要度 2"},
        {"factor_id": "event_vol_extreme_bonus",
         "name": "波动率 extreme 额外加分",
         "value": None, "weight": 0.10, "role": "vol_extreme +1"},
    ]
    if score is None:
        interp = "未就绪"
    elif score >= 8:
        interp = f"{score:.0f} 高事件密度,permission 自动降到 ambush_only"
    elif score >= 4:
        interp = f"{score:.0f} 中等密度,position_cap × 0.85"
    else:
        interp = f"{score:.0f} 72h 低风险"
    return {
        "composition": composition,
        "rule_description": (
            "按事件类型加分(FOMC=4 / CPI=3 / NFP=3 / 期权 2)× 时间衰减;"
            "vol extreme 每事件 +1;相关性高时美宏事件 +1"
        ),
        "value_interpretation": interp,
        "affects_layer": "L4.event_risk_multiplier 和 permission 降档建议",
    }


# ============================================================
# 入口
# ============================================================

_SPECS: dict[str, Any] = {
    "truth_trend": _truth_trend,
    "band_position": _band_position,
    "cycle_position": _cycle_position,
    "crowding": _crowding,
    "macro_headwind": _macro_headwind,
    "event_risk": _event_risk,
}


def inject_composite_composition(
    state: dict[str, Any],
    context: dict[str, Any],
) -> None:
    """就地为 state.composite_factors[k] 加 composition / rule_description /
    value_interpretation / affects_layer 四个讲述式字段。
    """
    composite = state.get("composite_factors") or {}
    if not isinstance(composite, dict):
        return
    ctx = {
        "l1": (state.get("evidence_reports") or {}).get("layer_1") or {},
        "l2": (state.get("evidence_reports") or {}).get("layer_2") or {},
        "onchain": context.get("onchain") or {},
        "derivatives": context.get("derivatives") or {},
        "macro": context.get("macro") or {},
        "klines_1d": context.get("klines_1d"),
    }
    for key, fn in _SPECS.items():
        c = composite.get(key)
        if not isinstance(c, dict):
            continue
        try:
            extras = fn(c, ctx)
            c.update(extras)
        except Exception as e:  # pragma: no cover
            logger.warning("composite_composition[%s] failed: %s", key, e)
