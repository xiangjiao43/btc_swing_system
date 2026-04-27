"""
factor_card_emitter.py — Sprint 2.2,把一次 pipeline 运行的全量数据因子
拍成 factor_cards list,给前端 §9.6 平铺展示。

建模对齐:
  §3.6 L1 原始数据清单 + §3.7 L2 单因子 + §3.8 L3 六组合因子 = 约 35-40 条
  §6.7 card_id 命名规则:{category}_{metric_name}_{bjt_date}

输出结构(每卡):
  {
    card_id:      str,      # 按 §6.7 规则
    category:     str,      # price_structure | derivatives | onchain |
                           # liquidity | macro | events | risk_tags
    tier:         str,      # "primary"(主裁决因子)| "reference"(参考因子)
                           # | "composite"(L3 组合因子)
    name:         str,      # 中文展示名
    name_en:      str,      # 英文 key
    current_value:Any,      # float / str,可能为 None(冷启动 / 数据缺失)
    value_unit:   str,
    historical_percentile: Optional[float],   # 过去 180 天分位(若能算)
    captured_at_bjt:       Optional[str],     # BJT 时间
    data_fresh:            bool,              # 新鲜 = True
    plain_interpretation:  str,               # 一句人话解读
    strategy_impact:       str,               # 对策略的影响
    impact_direction:      str,               # bullish / bearish / neutral
    impact_weight:         float,             # 0-1
    linked_layer:          str,               # L1/L2/L3/L4/L5
    source:                str,               # 数据源
  }

容错:数据缺失 → current_value=None, data_fresh=False,
      plain_interpretation="数据不足(冷启动期或数据源失败)"。绝不 raise。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

import pandas as pd


logger = logging.getLogger(__name__)


_BJT = ZoneInfo("Asia/Shanghai")


def _today_bjt_date() -> str:
    return datetime.now(_BJT).strftime("%Y%m%d")


def _to_bjt(dt_like: Any) -> Optional[str]:
    """把 ISO / datetime / Timestamp 转成 'YYYY-MM-DD HH:mm (BJT)'。"""
    try:
        if isinstance(dt_like, str):
            s = dt_like.replace("Z", "+00:00")
            d = datetime.fromisoformat(s)
        elif isinstance(dt_like, pd.Timestamp):
            d = dt_like.to_pydatetime()
        elif isinstance(dt_like, datetime):
            d = dt_like
        else:
            return None
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(_BJT).strftime("%Y-%m-%d %H:%M (BJT)")
    except Exception:
        return None


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    # 如果意外拿到 pd.Series(应已在 _latest 取标量,这里是防御),取最后一个有效值
    if isinstance(v, pd.Series):
        try:
            v = v.dropna().iloc[-1] if not v.dropna().empty else None
        except Exception:
            return None
        if v is None:
            return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    try:
        if pd.isna(f):
            return None
    except Exception:
        pass
    return f


def _percentile_180d(series: Optional[pd.Series], current: Optional[float]) -> Optional[float]:
    """最近 180 天内当前值的分位(0-100)。数据不足或 current None → None。"""
    if series is None or current is None:
        return None
    try:
        s = series.dropna().astype(float)
        if len(s) < 5:
            return None
        s = s.iloc[-180:] if len(s) > 180 else s
        rank = (s <= current).sum()
        return round(rank / len(s) * 100.0, 1)
    except Exception:
        return None


def _is_fresh(captured_bjt: Optional[str], max_hours: float = 48.0) -> bool:
    """captured 距现在 < max_hours 视为 fresh。解析失败视为 stale。"""
    if not captured_bjt:
        return False
    try:
        s = captured_bjt.replace(" (BJT)", "").strip()
        d = datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=_BJT)
        age_h = (datetime.now(_BJT) - d).total_seconds() / 3600.0
        return age_h < max_hours
    except Exception:
        return False


def _impact_direction_from_value(
    value: Optional[float],
    bull_above: Optional[float] = None,
    bear_above: Optional[float] = None,
    bear_below: Optional[float] = None,
    bull_below: Optional[float] = None,
) -> str:
    """按阈值判方向。优先级:bull_above > bear_above > bear_below > bull_below。"""
    if value is None:
        return "neutral"
    if bull_above is not None and value >= bull_above:
        return "bullish"
    if bear_above is not None and value >= bear_above:
        return "bearish"
    if bear_below is not None and value <= bear_below:
        return "bearish"
    if bull_below is not None and value <= bull_below:
        return "bullish"
    return "neutral"


def _make_card(
    *,
    card_id: str,
    category: str,
    tier: str,
    name: str,
    name_en: str,
    linked_layer: str,
    source: str,
    current_value: Any = None,
    value_unit: str = "",
    historical_percentile: Optional[float] = None,
    captured_at_bjt: Optional[str] = None,
    data_fresh: Optional[bool] = None,
    plain_interpretation: str = "",
    strategy_impact: str = "",
    impact_direction: str = "neutral",
    impact_weight: float = 0.5,
    expected_range: str = "",
) -> dict[str, Any]:
    """构造 factor card dict。data_fresh 自动从 captured_at_bjt 推,也可显式给。

    Sprint 2.3 新增字段:
      * group         ∈ {onchain / derivatives / price_technical / macro / events}
                       前端区域 4 分组用(从 category 自动映射)
      * is_primary    bool,等同 tier == 'primary'(给前端区分"平铺/折叠")
      * expected_range: 冷启动期告诉用户"这个因子正常什么区间"
    """
    if current_value is None and not plain_interpretation:
        plain_interpretation = "数据不足(冷启动期或数据源失败)"
    if data_fresh is None:
        data_fresh = _is_fresh(captured_at_bjt) if current_value is not None else False
    group = _category_to_group(category)
    return {
        "card_id": card_id,
        "category": category,
        "group": group,
        "tier": tier,
        "is_primary": tier == "primary",
        "name": name,
        "name_en": name_en,
        "current_value": current_value,
        "value_unit": value_unit,
        "historical_percentile": historical_percentile,
        "captured_at_bjt": captured_at_bjt,
        "data_fresh": data_fresh,
        "plain_interpretation": plain_interpretation,
        "strategy_impact": strategy_impact,
        "impact_direction": impact_direction,
        "impact_weight": impact_weight,
        "expected_range": expected_range,
        "linked_layer": linked_layer,
        "source": source,
    }


_CATEGORY_TO_GROUP: dict[str, str] = {
    "onchain":         "onchain",
    "derivatives":     "derivatives",
    "liquidity":       "derivatives",      # 流动性归衍生品区
    "price_structure": "price_technical",
    "macro":           "macro",
    "events":          "events",
    "risk_tags":       "derivatives",
}


def _category_to_group(category: str) -> str:
    return _CATEGORY_TO_GROUP.get(category, category)


# ============================================================
# 数据抽取工具
# ============================================================

def _latest(series: Optional[pd.Series]) -> tuple[Optional[float], Optional[str]]:
    """series 的最近值 + BJT 时间戳。"""
    if series is None:
        return None, None
    try:
        s = series.dropna()
        if s.empty:
            return None, None
        return _safe_float(s.iloc[-1]), _to_bjt(s.index[-1])
    except Exception:
        return None, None


def _pct_change(series: Optional[pd.Series], days: int) -> Optional[float]:
    if series is None:
        return None
    try:
        s = series.dropna()
        if len(s) < days + 1:
            return None
        return (float(s.iloc[-1]) / float(s.iloc[-1 - days]) - 1.0) * 100.0
    except Exception:
        return None


def _series_from_df(df: Any, col: str) -> Optional[pd.Series]:
    if df is None or not isinstance(df, pd.DataFrame) or col not in df.columns:
        return None
    return df[col]


# ============================================================
# 主入口
# ============================================================

def emit_factor_cards(
    strategy_state: dict[str, Any],
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    把一次 pipeline 运行产出的 state + context 压成 factor_cards 列表。

    strategy_state 期望已经 assemble 过 evidence_reports / composite_factors。
    context 是 state_builder 用过的 context,含 klines / derivatives / onchain
    / macro 这些 dataframe / dict。
    """
    cards: list[dict[str, Any]] = []
    today = _today_bjt_date()

    onchain: dict[str, Any] = context.get("onchain") or {}
    derivatives: dict[str, Any] = context.get("derivatives") or {}
    macro: dict[str, Any] = context.get("macro") or {}
    klines_1d = context.get("klines_1d")
    composite = strategy_state.get("composite_factors") or {}
    l1 = ((strategy_state.get("evidence_reports") or {}).get("layer_1")) or {}
    events = context.get("events_upcoming_48h") or []

    # ========== 组合因子(6 个,tier=composite)==========
    cards.extend(_emit_composite_cards(composite, today))

    # ========== 链上主裁决(primary)==========
    cards.extend(_emit_onchain_primary(onchain, klines_1d, today))

    # ========== 衍生品主裁决(primary)==========
    cards.extend(_emit_derivatives_primary(derivatives, today))

    # ========== 技术指标主裁决(primary)==========
    cards.extend(_emit_price_tech_primary(l1, klines_1d, today))

    # ========== 宏观主裁决(primary)==========
    cards.extend(_emit_macro_primary(macro, today))

    # ========== 链上参考(reference)==========
    cards.extend(_emit_onchain_reference(onchain, today))

    # ========== 衍生品参考(reference)==========
    cards.extend(_emit_derivatives_reference(derivatives, today))

    # ========== 价格技术参考(reference)==========
    cards.extend(_emit_price_tech_reference(klines_1d, today))

    # ========== 宏观参考(reference)==========
    cards.extend(_emit_macro_reference(macro, today))

    # ========== 事件日历(reference)==========
    cards.extend(_emit_events_reference(events, today))

    return cards


# ============================================================
# 组合因子(6)
# ============================================================

def _emit_composite_cards(composite: dict[str, Any], today: str) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    now_bjt = datetime.now(_BJT).strftime("%Y-%m-%d %H:%M (BJT)")

    _composite_specs: list[tuple[str, str, str, str, str, str]] = [
        # (key, card_id_suffix, name_cn, name_en, linked_layer, plain_impact)
        ("truth_trend", "truth_trend", "趋势真实性指数",
         "TruthTrend", "L1",
         "📍 综合 ADX、多周期方向一致性、均线排列,判定当前是真趋势还是震荡。≥6 真趋势,≤3 无趋势。"),
        ("band_position", "band_position", "波段位置综合指数",
         "BandPosition", "L2",
         "📍 用价格几何(swing 扩展比、结构序列、MA 距离、回撤深度)判定当前波段处在初段/中段/末段/衰竭期。"),
        ("cycle_position", "cycle_position", "长周期位置",
         "CyclePosition", "L2",
         "📍 用 MVRV、NUPL、LTH 持仓和距 ATH 跌幅,判断 BTC 处于 9 档长周期中的哪一档,直接影响系统做多/做空的门槛。"),
        ("crowding", "crowding", "拥挤度指数",
         "Crowding", "L4",
         "📍 用 funding、OI、多空比、basis、Put/Call 综合判定衍生品是否极端拥挤。≥6 极度拥挤,系统会收紧仓位。"),
        ("macro_headwind", "macro_headwind", "宏观逆风指数",
         "MacroHeadwind", "L5",
         "📍 综合 DXY、US10Y、VIX、纳指变化,衡量宏观环境对 BTC 是顺风还是逆风。≤-5 强逆风,系统会收紧仓位。"),
        ("event_risk", "event_risk", "风险事件密度",
         "EventRisk", "L4",
         "📍 综合未来 72 小时的 FOMC、CPI、NFP、期权大到期等事件,按重要度和距离加权打分。≥8 系统会强制只埋伏单。"),
    ]

    for key, slug, name_cn, name_en, layer, impact in _composite_specs:
        data = composite.get(key) or {}
        # 每个 composite 有自己的"值"字段:score / band / phase / cycle_position
        score = data.get("score")
        band = (
            data.get("band") or data.get("phase")
            or data.get("cycle_position")
        )
        current_value = score if score is not None else band
        if current_value is None:
            current_value = "n/a"
        direction = _composite_direction(key, data)
        plain = _composite_plain_reading(key, data)

        cards.append(_make_card(
            card_id=f"composite_{slug}_{today}",
            category=_composite_category(key),
            tier="composite",
            name=name_cn,
            name_en=name_en,
            current_value=current_value,
            value_unit="",
            historical_percentile=None,
            captured_at_bjt=now_bjt,
            data_fresh=score is not None or band is not None,
            plain_interpretation=plain,
            strategy_impact=impact,
            impact_direction=direction,
            impact_weight=0.8,
            linked_layer=layer,
            source="composite",
        ))
    return cards


def _composite_category(key: str) -> str:
    return {
        "truth_trend": "price_structure",
        "band_position": "price_structure",
        "cycle_position": "onchain",
        "crowding": "derivatives",
        "macro_headwind": "macro",
        "event_risk": "events",
    }.get(key, "price_structure")


def _composite_direction(key: str, data: dict[str, Any]) -> str:
    if not data:
        return "neutral"
    score = data.get("score")
    band = data.get("band") or data.get("phase") or data.get("cycle_position")
    if key == "truth_trend":
        if score is None:
            return "neutral"
        if score >= 6:
            return "bullish"  # 真趋势,但方向由 L1 regime 定,这里只表示"强"
        return "neutral"
    if key == "cycle_position":
        if band in {"accumulation", "early_bull", "mid_bull"}:
            return "bullish"
        if band in {"late_bull", "distribution", "early_bear", "mid_bear", "late_bear"}:
            return "bearish"
        return "neutral"
    if key == "crowding":
        # crowding 高 → 反向风险
        if score is not None and score >= 6:
            return "bearish"
        return "neutral"
    if key == "macro_headwind":
        if score is not None and score <= -5:
            return "bearish"
        if score is not None and score >= 3:
            return "bullish"
        return "neutral"
    if key == "event_risk":
        if score is not None and score >= 8:
            return "bearish"
        return "neutral"
    if key == "band_position":
        if band in {"early", "mid"}:
            return "bullish"
        if band in {"late", "exhausted"}:
            return "bearish"
    return "neutral"


def _composite_plain_reading(key: str, data: dict[str, Any]) -> str:
    if not data:
        return "📊 数据不足(该组合因子未能产出)\n🔍 等数据齐全后系统会重新计算"
    score = data.get("score")
    band = data.get("band") or data.get("phase") or data.get("cycle_position")

    if key == "truth_trend":
        if score is None:
            return "📊 趋势强度未能计算(数据不足)\n🔍 ≥6 = 真趋势;4-5 = 弱趋势;≤3 = 无趋势(震荡)"
        if score >= 6:
            return (f"📊 当前 ADX + 均线 + 多周期一致性综合 {score}/9 分,属于真趋势\n"
                    f"🔍 ≥6 = 真趋势;4-5 = 弱趋势,谨慎跟进;≤3 = 无趋势,以区间思路为主")
        if score >= 4:
            return (f"📊 当前趋势信号 {score}/9 分,弱趋势,谨慎跟进\n"
                    f"🔍 ≥6 = 真趋势;4-5 = 弱趋势;≤3 = 无趋势")
        return (f"📊 当前趋势信号 {score}/9 分,无趋势,以区间思路为主\n"
                f"🔍 ≥6 = 真趋势;4-5 = 弱趋势;≤3 = 无趋势")

    if key == "cycle_position":
        if band is None or band == "unclear":
            return ("📊 长周期位置不明朗,三主指标未形成共识\n"
                    "🔍 三主指标 = MVRV-Z / NUPL / LTH 90 日变化;一致 = 高置信,分歧 = 不明")
        labels = {
            "accumulation": "底部累积期(底部吸筹)",
            "early_bull": "牛市早期",
            "mid_bull": "牛市中段",
            "late_bull": "牛市晚期",
            "distribution": "顶部派发期",
            "early_bear": "熊市早期",
            "mid_bear": "熊市中段",
            "late_bear": "熊市晚期",
        }
        return (f"📊 当前处于 {labels.get(band, band)},系统按此调整做多/做空门槛\n"
                f"🔍 9 档:底部累积期 → 牛市早/中/晚期 → 顶部派发期 → 熊市早/中/晚期")

    if key == "crowding":
        if score is None:
            return ("📊 衍生品拥挤度未能计算\n"
                    "🔍 ≥6 = 极度拥挤(仓位收紧 70%);4-5 = 偏拥挤(× 85%);≤3 = 正常")
        if score >= 6:
            return (f"📊 拥挤度 {score}/8,极度拥挤,反向挤压风险增加\n"
                    f"🔍 ≥6 = 极度拥挤(仓位收紧 70%);4-5 = 偏拥挤(× 85%);≤3 = 正常")
        if score >= 4:
            return (f"📊 拥挤度 {score}/8,偏拥挤,仓位上限轻度下调(× 85%)\n"
                    f"🔍 ≥6 = 极度拥挤;4-5 = 偏拥挤;≤3 = 正常")
        return (f"📊 拥挤度 {score}/8,正常,不收紧仓位\n"
                f"🔍 ≥6 = 极度拥挤;4-5 = 偏拥挤;≤3 = 正常")

    if key == "macro_headwind":
        if score is None:
            return ("📊 宏观逆风未能计算\n"
                    "🔍 ≤-5 = 强逆风(仓位收紧 70%);-4~-2 = 轻度逆风(× 85%);≥-1 = 中性或顺风")
        if score <= -5:
            return (f"📊 宏观强逆风({score} 分),建议仓位上限收紧到 70%\n"
                    f"🔍 ≤-5 = 强逆风;-4~-2 = 轻度逆风;≥-1 = 中性或顺风")
        if score <= -2:
            return (f"📊 宏观轻度逆风({score} 分),建议仓位上限轻度下调(× 85%)\n"
                    f"🔍 ≤-5 = 强逆风;-4~-2 = 轻度逆风;≥-1 = 中性或顺风")
        return (f"📊 宏观中性或顺风({score} 分),建议仓位上限不做修正\n"
                f"🔍 ≤-5 = 强逆风;-4~-2 = 轻度逆风;≥-1 = 中性或顺风")

    if key == "event_risk":
        if score is None:
            return ("📊 事件风险未能计算\n"
                    "🔍 ≥8 = 高(只允许埋伏单,仓位 × 70%);4-7 = 中等(× 85%);<4 = 低")
        if score >= 8:
            return (f"📊 未来 72 小时事件密度高({score} 分),系统强制只允许埋伏单\n"
                    f"🔍 ≥8 = 高(只埋伏单,仓位 × 70%);4-7 = 中等(× 85%);<4 = 低")
        if score >= 4:
            return (f"📊 未来 72 小时事件密度中等({score} 分),仓位上限轻度下调(× 85%)\n"
                    f"🔍 ≥8 = 高;4-7 = 中等;<4 = 低")
        return (f"📊 未来 72 小时事件密度低({score} 分),正常\n"
                f"🔍 ≥8 = 高;4-7 = 中等;<4 = 低")

    if key == "band_position":
        labels = {"early": "趋势初段", "mid": "趋势中段",
                  "late": "趋势末段", "exhausted": "衰竭期"}
        return (f"📊 当前波段位置:{labels.get(band, band or '波段位置不明')}\n"
                f"🔍 初段 = 扩展比 < 50%;中段 = 50-100%;末段 = 100-138%;衰竭 = > 138%")

    return str(data)


# ============================================================
# 链上 primary
# ============================================================

def _emit_onchain_primary(
    onchain: dict[str, Any], klines_1d: Any, today: str,
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []

    # MVRV Z-Score
    series = onchain.get("mvrv_z_score") if isinstance(onchain, dict) else None
    val, ts = _latest(series)
    pct = _percentile_180d(series, val)
    cards.append(_make_card(
        card_id=f"onchain_mvrv_z_{today}",
        category="onchain", tier="primary",
        name="MVRV Z 分数", name_en="MVRV Z-Score",
        current_value=round(val, 3) if val is not None else None,
        value_unit="",
        historical_percentile=pct,
        captured_at_bjt=ts,
        plain_interpretation=(
            (f"📊 当前 {val:.2f},过去 180 天 {pct:.0f}% 分位,处于历史偏高区,链上估值偏高\n"
             f"🔍 > 6 顶部派发期;2 ~ 4 牛市中段;-0.5 ~ 2 牛市早期;< -0.5 底部累积期"
             ) if val is not None and pct is not None and pct >= 70
            else (f"📊 当前 {val:.2f},过去 180 天 {pct:.0f}% 分位,处于历史偏低区,链上估值偏低\n"
                  f"🔍 > 6 顶部派发期;2 ~ 4 牛市中段;-0.5 ~ 2 牛市早期;< -0.5 底部累积期"
                  ) if val is not None and pct is not None and pct <= 30
            else (f"📊 当前 {val:.2f},处于价值与高估之间的过渡区\n"
                  f"🔍 > 6 顶部派发期;2 ~ 4 牛市中段;-0.5 ~ 2 牛市早期;< -0.5 底部累积期"
                  ) if val is not None
            else "📊 数据不足\n🔍 > 6 顶部派发期;2 ~ 4 牛市中段;-0.5 ~ 2 牛市早期;< -0.5 底部累积期"
        ),
        strategy_impact="📍 链上市场估值的 Z 分数:衡量当前市值相对长期实现市值的偏离程度。是判断长周期位置(累积/牛市/派发)的核心指标之一。",
        impact_direction=_impact_direction_from_value(
            val, bear_above=2.0, bull_below=-0.5,
        ),
        impact_weight=0.9,
        linked_layer="L2", source="Glassnode",
    ))

    # NUPL
    series = onchain.get("nupl") if isinstance(onchain, dict) else None
    val, ts = _latest(series)
    pct = _percentile_180d(series, val)
    cards.append(_make_card(
        card_id=f"onchain_nupl_{today}",
        category="onchain", tier="primary",
        name="未实现盈亏比例 NUPL", name_en="NUPL",
        current_value=round(val, 3) if val is not None else None,
        historical_percentile=pct,
        captured_at_bjt=ts,
        plain_interpretation=(
            (f"📊 当前 {val:.2f},整体持仓处于盈利状态(Belief 区间)\n"
             f"🔍 > 0.75 = 极度狂热(Euphoria,历史顶);0.5-0.75 = Belief;0-0.5 = 希望与忧虑交织;< 0 = 投降(Capitulation,历史底)"
             ) if val is not None and 0.5 <= val < 0.75
            else (f"📊 当前 {val:.2f},市场处于 Euphoria 区间,历史顶部信号\n"
                  f"🔍 > 0.75 = 极度狂热;0.5-0.75 = Belief;0-0.5 = 希望与忧虑;< 0 = 投降"
                  ) if val is not None and val >= 0.75
            else (f"📊 当前 {val:.2f},市场处于 Capitulation 区间,历史底部信号\n"
                  f"🔍 > 0.75 = 极度狂热;0.5-0.75 = Belief;0-0.5 = 希望与忧虑;< 0 = 投降"
                  ) if val is not None and val <= 0
            else (f"📊 当前 {val:.2f},市场处在希望与忧虑交织区间(0-0.5)\n"
                  f"🔍 > 0.75 = 极度狂热;0.5-0.75 = Belief;0-0.5 = 希望与忧虑;< 0 = 投降"
                  ) if val is not None
            else "📊 数据不足\n🔍 > 0.75 = 极度狂热;0.5-0.75 = Belief;0-0.5 = 希望与忧虑;< 0 = 投降"
        ),
        strategy_impact="📍 链上整体未实现盈亏比例:衡量市场上 BTC 持有者整体处于盈利还是亏损,以及程度如何。是判断长周期位置的核心指标。",
        impact_direction=_impact_direction_from_value(
            val, bear_above=0.65, bull_below=0.0,
        ),
        impact_weight=0.9,
        linked_layer="L2", source="Glassnode",
    ))

    # LTH Supply 90 日变化
    series = onchain.get("lth_supply") if isinstance(onchain, dict) else None
    change_90d = _pct_change(series, 90)
    _, ts = _latest(series)
    cards.append(_make_card(
        card_id=f"onchain_lth_supply_90d_change_{today}",
        category="onchain", tier="primary",
        name="长期持有者供应 90 日变化", name_en="LTH Supply 90d Change",
        current_value=round(change_90d, 2) if change_90d is not None else None,
        value_unit="%",
        captured_at_bjt=ts,
        plain_interpretation=(
            (f"📊 长期持有者过去 90 天净增持 {change_90d:.1f}%,底部吸筹中(底部信号)\n"
             f"🔍 > +2% = 净增持(底部吸筹);±2% = 稳定;< -3% = 净减持(顶部派发)"
             ) if change_90d is not None and change_90d > 2
            else (f"📊 长期持有者过去 90 天净减持 {change_90d:.1f}%,顶部派发中(顶部信号)\n"
                  f"🔍 > +2% = 净增持;±2% = 稳定;< -3% = 净减持"
                  ) if change_90d is not None and change_90d < -3
            else (f"📊 长期持有者 90 日变化 {change_90d:.1f}%,持仓相对稳定\n"
                  f"🔍 > +2% = 净增持(吸筹);±2% = 稳定;< -3% = 净减持(派发)"
                  ) if change_90d is not None
            else "📊 数据不足(需 90 天历史)\n🔍 > +2% = 净增持;±2% = 稳定;< -3% = 净减持"
        ),
        strategy_impact="📍 长期持有者(持有 ≥ 155 天)的总持仓在过去 90 天的变化。增持往往伴随底部吸筹,减持往往伴随顶部派发。",
        impact_direction=_impact_direction_from_value(
            change_90d, bull_above=2, bear_below=-3,
        ),
        impact_weight=0.85,
        linked_layer="L2", source="Glassnode",
    ))

    # Exchange Net Flow 7 日均
    series = onchain.get("exchange_net_flow") if isinstance(onchain, dict) else None
    val, ts = _latest(series)
    # 7 日均
    avg7 = None
    if series is not None:
        try:
            s = series.dropna()
            if len(s) >= 7:
                avg7 = float(s.iloc[-7:].mean())
        except Exception:
            pass
    cards.append(_make_card(
        card_id=f"onchain_exchange_flow_7d_{today}",
        category="onchain", tier="primary",
        name="交易所净流入 7 日均", name_en="Exchange Net Flow 7d Avg",
        current_value=round(avg7, 2) if avg7 is not None else None,
        value_unit="BTC",
        captured_at_bjt=ts,
        plain_interpretation=(
            (f"📊 7 日均净流入 {avg7:.0f} BTC,大量币流入交易所,供应压力增加\n"
             f"🔍 > +500 BTC = 流入压力大(偏空);±500 BTC = 平稳;< -500 BTC = 流出强,持币意愿增强(偏多)"
             ) if avg7 is not None and avg7 > 500
            else (f"📊 7 日均净流出 {-avg7:.0f} BTC,大量币离开交易所,持币意愿增强\n"
                  f"🔍 > +500 BTC = 流入压力大;±500 BTC = 平稳;< -500 BTC = 流出强(偏多)"
                  ) if avg7 is not None and avg7 < -500
            else (f"📊 交易所净流量 {avg7:.0f} BTC/日,平稳\n"
                  f"🔍 > +500 BTC = 流入压力大;±500 BTC = 平稳;< -500 BTC = 流出强"
                  ) if avg7 is not None
            else "📊 数据不足\n🔍 > +500 BTC = 流入压力大;±500 BTC = 平稳;< -500 BTC = 流出强(偏多)"
        ),
        strategy_impact="📍 BTC 流入交易所的速度(扣减流出)。币流入 = 卖压可能增加;流出 = 持币意愿强、潜在多头。这是修正方向判断信心的辅助指标。",
        impact_direction=_impact_direction_from_value(
            avg7, bear_above=500, bull_below=-500,
        ),
        impact_weight=0.7,
        linked_layer="L2", source="Glassnode",
    ))

    # BTC 距 ATH 跌幅(从 klines_1d 推,不靠 Glassnode)
    drawdown_pct, ts = _btc_drawdown_from_ath(klines_1d)
    cards.append(_make_card(
        card_id=f"price_drawdown_from_ath_{today}",
        category="price_structure", tier="primary",
        name="距 ATH 跌幅", name_en="Drawdown from ATH",
        current_value=round(drawdown_pct, 2) if drawdown_pct is not None else None,
        value_unit="%",
        captured_at_bjt=ts,
        plain_interpretation=(
            (f"📊 当前距离历史最高价 {drawdown_pct:.1f}%,深度回撤,价值区\n"
             f"🔍 > -5% = 相对高位;-5% ~ -20% = 中段回调;< -20% = 深度回撤(可能进入熊市早期)"
             ) if drawdown_pct is not None and drawdown_pct < -20
            else (f"📊 当前距离历史高点 {drawdown_pct:.1f}%,相对高位,接近顶部\n"
                  f"🔍 > -5% = 相对高位;-5% ~ -20% = 中段回调;< -20% = 深度回撤"
                  ) if drawdown_pct is not None and drawdown_pct > -5
            else (f"📊 距历史高点跌幅 {drawdown_pct:.1f}%,中段回调区\n"
                  f"🔍 > -5% = 相对高位;-5% ~ -20% = 中段回调;< -20% = 深度回撤"
                  ) if drawdown_pct is not None
            else "📊 数据不足(需 K 线历史)\n🔍 > -5% = 相对高位;-5% ~ -20% = 中段回调;< -20% = 深度回撤"
        ),
        strategy_impact="📍 当前价格距离历史最高点的跌幅。配合 MVRV-Z 和 NUPL 用于判断长周期位置(深度回撤往往是熊市早期的辅助信号)。",
        impact_direction=_impact_direction_from_value(
            drawdown_pct, bull_below=-20,
        ),
        impact_weight=0.6,
        linked_layer="L2", source="Binance klines",
    ))

    # Reserve Risk
    series = onchain.get("reserve_risk") if isinstance(onchain, dict) else None
    val, ts = _latest(series)
    pct = _percentile_180d(series, val)
    cards.append(_make_card(
        card_id=f"onchain_reserve_risk_{today}",
        category="onchain", tier="primary",
        name="储备风险 Reserve Risk", name_en="Reserve Risk",
        current_value=round(val, 6) if val is not None else None,
        historical_percentile=pct,
        captured_at_bjt=ts,
        plain_interpretation=(
            (f"📊 当前 {val:.4f},储备风险偏高,长期持有者倾向抛售(顶部信号)\n"
             f"🔍 < 0.002 = 历史底部区间(惜售,买入性价比高);0.002 ~ 0.02 = 正常;> 0.02 = 顶部区间(抛售意愿高)"
             ) if val is not None and val > 0.02
            else (f"📊 当前 {val:.4f},储备风险偏低,长期持有者惜售(底部信号,买入性价比高)\n"
                  f"🔍 < 0.002 = 历史底部区间;0.002 ~ 0.02 = 正常;> 0.02 = 顶部区间"
                  ) if val is not None and val < 0.002
            else (f"📊 当前 {val:.4f},储备风险处于正常区间\n"
                  f"🔍 < 0.002 = 历史底部区间;0.002 ~ 0.02 = 正常;> 0.02 = 顶部区间"
                  ) if val is not None
            else "📊 数据不足\n🔍 < 0.002 = 历史底部区间;0.002 ~ 0.02 = 正常;> 0.02 = 顶部区间"
        ),
        strategy_impact="📍 长期持有者抛售意愿与价格的比值,反映底部信号强度。极低值常出现在历史大底,极高值常出现在大顶。",
        impact_direction=_impact_direction_from_value(val, bear_above=0.02, bull_below=0.002),
        impact_weight=0.7,
        linked_layer="L2", source="Glassnode",
    ))
    return cards


def _btc_drawdown_from_ath(klines_1d: Any) -> tuple[Optional[float], Optional[str]]:
    if klines_1d is None or not isinstance(klines_1d, pd.DataFrame) or len(klines_1d) < 5:
        return None, None
    try:
        closes = klines_1d["close"].astype(float)
        ath = closes.max()
        current = float(closes.iloc[-1])
        if ath <= 0:
            return None, None
        dd = (current / ath - 1.0) * 100.0
        ts = _to_bjt(klines_1d.index[-1])
        return dd, ts
    except Exception:
        return None, None


# ============================================================
# 衍生品 primary
# ============================================================

def _emit_derivatives_primary(
    derivatives: dict[str, Any], today: str,
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []

    # 资金费率当前值
    series = derivatives.get("funding_rate") if isinstance(derivatives, dict) else None
    val, ts = _latest(series)
    pct = _percentile_180d(series, val)
    cards.append(_make_card(
        card_id=f"derivatives_funding_rate_current_{today}",
        category="derivatives", tier="primary",
        name="资金费率 · 当前", name_en="Funding Rate Current",
        current_value=round(val * 100, 4) if val is not None else None,
        value_unit="%",
        historical_percentile=pct,
        captured_at_bjt=ts,
        plain_interpretation=(
            (f"📊 当前 {val*100:.4f}%,资金费率过热,多头杠杆累积,反向挤压风险升高\n"
             f"🔍 > 0.03% 连续 3 次 = 多头过度拥挤(警告);-0.01% ~ 0.01% = 正常;< -0.05% = 空头过度拥挤(反弹信号)"
             ) if val is not None and val > 0.0003
            else (f"📊 当前 {val*100:.4f}%,资金费率深度为负,空头拥挤,反弹挤压潜在\n"
                  f"🔍 > 0.03% 连续 3 次 = 多头过度拥挤;-0.01% ~ 0.01% = 正常;< -0.05% = 空头过度拥挤"
                  ) if val is not None and val < -0.0002
            else (f"📊 当前 {val*100:.4f}%,资金费率中性,情绪平衡\n"
                  f"🔍 > 0.03% 连续 3 次 = 多头过度拥挤;-0.01% ~ 0.01% = 正常;< -0.05% = 空头过度拥挤"
                  ) if val is not None
            else "📊 数据不足\n🔍 > 0.03% 连续 3 次 = 多头过度拥挤;-0.01% ~ 0.01% = 正常;< -0.05% = 空头过度拥挤"
        ),
        strategy_impact="📍 永续合约多空双方互付的费率。正值=多头付空头(多头愿意为多头仓位付溢价),负值=空头付多头。极端值反映市场情绪和拥挤度。",
        impact_direction=_impact_direction_from_value(val, bear_above=0.0003, bull_below=-0.0002),
        impact_weight=0.9,
        linked_layer="L4", source="CoinGlass",
    ))

    # 资金费率 30 日分位(就是上面 percentile)
    cards.append(_make_card(
        card_id=f"derivatives_funding_rate_30d_pctile_{today}",
        category="derivatives", tier="primary",
        name="资金费率 · 30 日分位", name_en="Funding Rate 30d Percentile",
        current_value=round(pct, 1) if pct is not None else None,
        value_unit="分位",
        captured_at_bjt=ts,
        plain_interpretation=(
            (f"📊 资金费率在过去 30 日的 {pct:.0f}% 分位,历史高位\n"
             f"🔍 > 85 分位 = 历史极高(过热,反向挤压风险);15-85 分位 = 正常;< 15 分位 = 历史极低(可能空头拥挤)"
             ) if pct is not None and pct >= 85
            else (f"📊 资金费率在过去 30 日 {pct:.0f}% 分位,历史正常区间\n"
                  f"🔍 > 85 分位 = 历史极高;15-85 = 正常;< 15 = 历史极低"
                  ) if pct is not None
            else "📊 数据不足\n🔍 > 85 分位 = 历史极高;15-85 = 正常;< 15 = 历史极低"
        ),
        strategy_impact="📍 当前资金费率在过去 30 天的相对位置。> 85 分位通常意味着多头过度拥挤,常与短期顶部相关。",
        impact_direction=_impact_direction_from_value(pct, bear_above=85),
        impact_weight=0.8,
        linked_layer="L4", source="CoinGlass",
    ))

    # OI 24h 变化率
    series = derivatives.get("open_interest") if isinstance(derivatives, dict) else None
    change_24h = _pct_change(series, 1)  # 按日频数据,1 row = 1 天
    val_oi, ts_oi = _latest(series)
    cards.append(_make_card(
        card_id=f"derivatives_oi_24h_change_{today}",
        category="derivatives", tier="primary",
        name="未平仓合约 24h 变化", name_en="OI 24h Change",
        current_value=round(change_24h, 2) if change_24h is not None else None,
        value_unit="%",
        captured_at_bjt=ts_oi,
        plain_interpretation=(
            (f"📊 OI 过去 24 小时增加 {change_24h:.1f}%,杠杆快速累积,反向挤压风险升高\n"
             f"🔍 > +15% 24h = 杠杆快速累积(警告);±15% = 正常;< -15% = 大量平仓(可能去杠杆)"
             ) if change_24h is not None and change_24h > 15
            else (f"📊 OI 24h 变化 {change_24h:+.1f}%,杠杆水平稳定\n"
                  f"🔍 > +15% = 快速累积;±15% = 正常;< -15% = 大量平仓"
                  ) if change_24h is not None
            else "📊 数据不足(需至少 2 日 OI 数据)\n🔍 > +15% = 快速累积;±15% = 正常;< -15% = 大量平仓"
        ),
        strategy_impact="📍 OI(未平仓合约)= 永续合约持仓总量。24 小时快速累积往往意味着杠杆扩张、拥挤度上升;快速下降则可能是去杠杆。",
        impact_direction=_impact_direction_from_value(change_24h, bear_above=15),
        impact_weight=0.7,
        linked_layer="L4", source="CoinGlass",
    ))

    # 多空比(Top Accounts)
    series = None
    if isinstance(derivatives, dict):
        # 不能用 `a or b`:pd.Series 的 bool 会报 ambiguous。显式 None 检查。
        for k in ("long_short_ratio", "long_short_ratio_top",
                  "long_short_ratio_global"):
            v = derivatives.get(k)
            if v is not None:
                series = v
                break
    val, ts = _latest(series)
    cards.append(_make_card(
        card_id=f"derivatives_top_long_short_ratio_{today}",
        category="derivatives", tier="primary",
        name="大户多空比", name_en="Top Long/Short Ratio",
        current_value=round(val, 3) if val is not None else None,
        captured_at_bjt=ts,
        plain_interpretation=(
            (f"📊 大户多空比 {val:.2f},多头占比极高,多头拥挤(反向挤压风险)\n"
             f"🔍 > 2.5 = 多头过度拥挤;0.7 ~ 2.0 = 正常区间;< 0.5 = 空头过度拥挤"
             ) if val is not None and val > 2.5
            else (f"📊 大户多空比 {val:.2f},多空相对均衡\n"
                  f"🔍 > 2.5 = 多头过度拥挤;0.7 ~ 2.0 = 正常区间;< 0.5 = 空头过度拥挤"
                  ) if val is not None
            else "📊 数据不足\n🔍 > 2.5 = 多头过度拥挤;0.7 ~ 2.0 = 正常;< 0.5 = 空头过度拥挤"
        ),
        strategy_impact="📍 大户(高净值合约账户)中持有多头仓位 / 持有空头仓位的比值。极端值往往是反向信号,因为聪明钱的拥挤往往不持续。",
        impact_direction=_impact_direction_from_value(val, bear_above=2.5),
        impact_weight=0.6,
        linked_layer="L4", source="CoinGlass",
    ))

    return cards


# ============================================================
# 技术指标 primary
# ============================================================

def _emit_price_tech_primary(
    l1: dict[str, Any], klines_1d: Any, today: str,
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []

    # ADX-14(1D)—— Sprint 2.6-C:layer1 直接暴露 adx_14_1d,不再回退计算
    adx = l1.get("adx_14_1d")
    ts = _to_bjt(klines_1d.index[-1]) if isinstance(klines_1d, pd.DataFrame) and len(klines_1d) > 0 else None
    cards.append(_make_card(
        card_id=f"price_adx_14_1d_{today}",
        category="price_structure", tier="primary",
        name="ADX-14(1D)", name_en="ADX-14 Daily",
        current_value=round(adx, 2) if adx is not None else None,
        captured_at_bjt=ts,
        plain_interpretation=(
            (f"📊 ADX={adx:.1f},≥25 存在明确趋势\n"
             f"🔍 ≥ 25 = 有效趋势;20-25 = 趋势过渡区;< 20 = 无趋势(震荡市)"
             ) if adx is not None and adx >= 25
            else (f"📊 ADX={adx:.1f},趋势强度不足,处于震荡市\n"
                  f"🔍 ≥ 25 = 有效趋势;20-25 = 过渡区;< 20 = 无趋势"
                  ) if adx is not None
            else "📊 数据不足(需至少 20 天 1D K 线)\n🔍 ≥ 25 = 有效趋势;20-25 = 过渡区;< 20 = 无趋势"
        ),
        strategy_impact="📍 ADX(平均方向指数)= 衡量趋势强度的经典指标(不分方向)。≥ 25 表示有明显趋势,< 20 表示无趋势(震荡市)。",
        impact_direction=_impact_direction_from_value(adx, bull_above=25),
        impact_weight=0.85,
        linked_layer="L1", source="Binance klines",
    ))

    # ATR 百分位 —— Sprint 2.6-C:layer1 直接暴露 atr_percentile_180d
    atr_pct = l1.get("atr_percentile_180d")
    cards.append(_make_card(
        card_id=f"price_atr_percentile_180d_{today}",
        category="price_structure", tier="primary",
        name="ATR 180 日分位", name_en="ATR 180d Percentile",
        current_value=round(atr_pct, 1) if atr_pct is not None else None,
        value_unit="分位",
        captured_at_bjt=ts,
        plain_interpretation=(
            (f"📊 波动率在历史 {atr_pct:.0f}% 分位,极端波动(警告)\n"
             f"🔍 < 30 分位 = 低波动;30-60 = 正常;60-85 = 偏高;≥ 85 = 极端波动"
             ) if atr_pct is not None and atr_pct > 85
            else (f"📊 波动率在历史 {atr_pct:.0f}% 分位,偏低,行情趋稳\n"
                  f"🔍 < 30 = 低波动;30-60 = 正常;60-85 = 偏高;≥ 85 = 极端"
                  ) if atr_pct is not None and atr_pct < 20
            else (f"📊 波动率 {atr_pct:.0f}% 分位,正常区间\n"
                  f"🔍 < 30 = 低波动;30-60 = 正常;60-85 = 偏高;≥ 85 = 极端"
                  ) if atr_pct is not None
            else "📊 数据不足(需 180 天)\n🔍 < 30 = 低波动;30-60 = 正常;60-85 = 偏高;≥ 85 = 极端"
        ),
        strategy_impact="📍 ATR(平均真实波幅)在过去 180 天的相对位置。决定系统给止损价时使用的 ATR 倍数。极端波动会让止损放宽。",
        impact_direction="neutral",
        impact_weight=0.7,
        linked_layer="L1", source="Binance klines",
    ))

    # 多周期方向一致性
    alignment = l1.get("tf_alignment") or l1.get("multi_tf_alignment")
    alignment_value = None
    alignment_direction = "neutral"
    if isinstance(alignment, dict):
        alignment_value = alignment.get("score") or alignment.get("aligned")
        direction = alignment.get("direction")
        if direction == "up":
            alignment_direction = "bullish"
        elif direction == "down":
            alignment_direction = "bearish"
    cards.append(_make_card(
        card_id=f"price_tf_alignment_4h_1d_1w_{today}",
        category="price_structure", tier="primary",
        name="多周期方向一致性", name_en="4H/1D/1W Alignment",
        current_value=alignment_value if alignment_value is not None else "n/a",
        captured_at_bjt=ts,
        plain_interpretation=(
            ("📊 4H、1D、1W 三个周期方向一致,趋势强度高\n"
             "🔍 三周期一致 = 趋势确立(强信号);两周期一致 = 弱信号;三周期分歧 = 无趋势"
             ) if alignment and alignment_value
            else ("📊 数据不足或各周期方向分歧\n"
                  "🔍 三周期一致 = 趋势确立;两周期一致 = 弱信号;三周期分歧 = 无趋势")
        ),
        strategy_impact="📍 4H、1D、1W 三个时间周期的趋势方向是否一致。三周期方向一致是真趋势的最重要信号之一。",
        impact_direction=alignment_direction,
        impact_weight=0.85,
        linked_layer="L1", source="Binance klines",
    ))
    return cards


# Sprint 2.6-C:_compute_adx_latest / _compute_atr_percentile 已删除。
# 这两个函数原本是 layer1 数据缺失时的本地回退,但前者写死 return None(从未真算)、
# 后者重复了 layer1 已有的 ATR 计算。layer1_regime 现在直接暴露 adx_14_1d /
# atr_percentile_180d 顶层字段,本文件直接 l1.get(...) 读取。
# 按 CLAUDE.md §X 工程纪律:被替代的旧代码必须删除。


# ============================================================
# 宏观 primary
# ============================================================

def _emit_macro_primary(macro: dict[str, Any], today: str) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []

    dxy = macro.get("dxy") if isinstance(macro, dict) else None
    dxy_20d = _pct_change(dxy, 20)
    val, ts = _latest(dxy)
    cards.append(_make_card(
        card_id=f"macro_dxy_20d_change_{today}",
        category="macro", tier="primary",
        name="美元指数 DXY 20 日变化", name_en="DXY 20d Change",
        current_value=round(dxy_20d, 2) if dxy_20d is not None else None,
        value_unit="%",
        captured_at_bjt=ts,
        plain_interpretation=(
            (f"📊 美元指数 20 日变化 +{dxy_20d:.1f}%,美元强势,对 BTC 等风险资产逆风\n"
             f"🔍 > +2% = 美元强势(对风险资产逆风);±2% = 中性;< -2% = 美元弱势(对风险资产顺风)"
             ) if dxy_20d is not None and dxy_20d > 2
            else (f"📊 美元指数 20 日变化 {dxy_20d:.1f}%,美元弱势,对 BTC 等风险资产顺风\n"
                  f"🔍 > +2% = 美元强势(逆风);±2% = 中性;< -2% = 美元弱势(顺风)"
                  ) if dxy_20d is not None and dxy_20d < -2
            else (f"📊 美元指数 20 日变化 {dxy_20d:+.1f}%,中性\n"
                  f"🔍 > +2% = 美元强势(逆风);±2% = 中性;< -2% = 美元弱势(顺风)"
                  ) if dxy_20d is not None
            else "📊 数据不足(需 20 天 DXY)\n🔍 > +2% = 美元强势(逆风);±2% = 中性;< -2% = 美元弱势(顺风)"
        ),
        strategy_impact="📍 DXY(美元指数,衡量美元相对一篮子货币的强弱)的 20 日变化。美元强势通常压制风险资产(BTC、纳指、黄金)。",
        impact_direction=_impact_direction_from_value(dxy_20d, bear_above=2, bull_below=-2),
        impact_weight=0.8,
        linked_layer="L5", source="Yahoo Finance",
    ))

    vix = macro.get("vix") if isinstance(macro, dict) else None
    val, ts = _latest(vix)
    cards.append(_make_card(
        card_id=f"macro_vix_current_{today}",
        category="macro", tier="primary",
        name="VIX 恐慌指数", name_en="VIX",
        current_value=round(val, 2) if val is not None else None,
        captured_at_bjt=ts,
        plain_interpretation=(
            (f"📊 VIX={val:.1f},极端恐慌,风险资产承压\n"
             f"🔍 < 15 = 平静;15-25 = 正常;25-35 = 偏高(警惕);> 35 = 极端恐慌(危机信号)"
             ) if val is not None and val > 35
            else (f"📊 VIX={val:.1f},风险意识偏高,市场谨慎\n"
                  f"🔍 < 15 = 平静;15-25 = 正常;25-35 = 偏高;> 35 = 极端"
                  ) if val is not None and val > 25
            else (f"📊 VIX={val:.1f},市场情绪平静\n"
                  f"🔍 < 15 = 平静;15-25 = 正常;25-35 = 偏高;> 35 = 极端"
                  ) if val is not None
            else "📊 数据不足\n🔍 < 15 = 平静;15-25 = 正常;25-35 = 偏高;> 35 = 极端"
        ),
        strategy_impact="📍 VIX(标普 500 期权波动率,俗称恐慌指数)。> 25 通常意味着市场避险情绪上升,风险资产承压;> 35 是危机级别。",
        impact_direction=_impact_direction_from_value(val, bear_above=25),
        impact_weight=0.85,
        linked_layer="L5", source="Yahoo Finance",
    ))
    return cards


# ============================================================
# 链上 reference
# ============================================================

def _emit_onchain_reference(onchain: dict[str, Any], today: str) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    _ref_specs = [
        ("mvrv", "onchain_mvrv", "MVRV 比率", "MVRV Ratio",
         "📍 市值 / 实现市值。衡量平均持币者整体盈亏。< 1 = 整体亏损(底部区间);> 3.7 = 历史顶部信号。",
         "🔍 < 1 = 底部区间;1 ~ 2 = 牛市早期;2 ~ 3 = 牛市中段;> 3.7 = 顶部"),
        ("realized_price", "onchain_realized_price", "实现价格",
         "Realized Price",
         "📍 全市场所有 BTC 上一次链上转移时的平均价格,代表全市场的平均成本价。",
         "🔍 价格跌破实现价格 = 整体亏损,常见于熊市底部"),
        ("lth_realized_price", "onchain_lth_realized_price", "LTH 实现价格",
         "LTH Realized Price",
         "📍 长期持有者(持有 ≥ 155 天)的平均成本价。",
         "🔍 LTH 成本是关键支撑,跌破常意味着持币信仰动摇"),
        ("sth_realized_price", "onchain_sth_realized_price", "STH 实现价格",
         "STH Realized Price",
         "📍 短期持有者(持有 < 155 天)的平均成本价。",
         "🔍 牛市中跌破 STH 成本常是回调买点;熊市中跌破常是继续下跌信号"),
        ("sopr", "onchain_sopr", "SOPR", "SOPR",
         "📍 已花费产出利润比。> 1 = 整体盈利卖出;< 1 = 亏损卖出(常见底部信号)。",
         "🔍 > 1.05 = 大量获利了结;1 = 平衡;< 0.95 = 投降式抛售(底部信号)"),
        ("sopr_adjusted", "onchain_asopr", "aSOPR",
         "Adjusted SOPR",
         "📍 调整后的 SOPR,排除 1 小时内的交易(去噪声)。比 SOPR 更稳定。",
         "🔍 > 1 = 盈利卖出主导;= 1 = 关键支撑/阻力位;< 1 = 投降"),
        ("puell_multiple", "onchain_puell_multiple", "Puell Multiple",
         "Puell Multiple",
         "📍 矿工日收入 / 365 日均收入。极高 = 矿工抛压高(顶部);极低 = 矿工惜售(底部)。",
         "🔍 > 4 = 历史顶部区间;0.5 ~ 4 = 正常;< 0.5 = 历史底部区间"),
    ]
    for key, card_slug, name_cn, name_en, impact_desc, threshold_desc in _ref_specs:
        series = onchain.get(key) if isinstance(onchain, dict) else None
        val, ts = _latest(series)
        pct = _percentile_180d(series, val)
        cards.append(_make_card(
            card_id=f"{card_slug}_{today}",
            category="onchain", tier="reference",
            name=name_cn, name_en=name_en,
            current_value=round(val, 4) if val is not None else None,
            historical_percentile=pct,
            captured_at_bjt=ts,
            plain_interpretation=(
                f"📊 当前 {val:.3f},过去 180 天 {pct:.0f}% 分位\n{threshold_desc}"
                if val is not None and pct is not None
                else f"📊 当前 {val:.3f}\n{threshold_desc}" if val is not None
                else f"📊 数据不足\n{threshold_desc}"
            ),
            strategy_impact=impact_desc,
            impact_direction="neutral",
            impact_weight=0.4,
            linked_layer="L2", source="Glassnode",
        ))
    return cards


# ============================================================
# 衍生品 reference
# ============================================================

def _emit_derivatives_reference(
    derivatives: dict[str, Any], today: str,
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []

    # 资金费率 7 日均
    series = derivatives.get("funding_rate") if isinstance(derivatives, dict) else None
    avg7 = None
    _, ts = _latest(series)
    if series is not None:
        try:
            s = series.dropna()
            if len(s) >= 7:
                avg7 = float(s.iloc[-7:].mean())
        except Exception:
            pass
    cards.append(_make_card(
        card_id=f"derivatives_funding_rate_7d_avg_{today}",
        category="derivatives", tier="reference",
        name="资金费率 7 日均", name_en="Funding Rate 7d Avg",
        current_value=round(avg7 * 100, 4) if avg7 is not None else None,
        value_unit="%",
        captured_at_bjt=ts,
        plain_interpretation=(
            f"📊 过去 7 天的平均资金费率 {avg7 * 100:.4f}%\n"
            f"🔍 看 7 日均比看实时值更稳定:持续偏正 = 多头持续付溢价;持续偏负 = 空头持续付溢价"
            if avg7 is not None
            else "📊 数据不足\n🔍 7 日均反映短期情绪倾向是多还是空"
        ),
        strategy_impact="📍 资金费率的 7 天移动平均,过滤短期噪声,看出持续的情绪倾向。比单点值更能反映趋势性拥挤。",
        impact_direction="neutral", impact_weight=0.3,
        linked_layer="L4", source="CoinGlass",
    ))

    # 资金费率 Z-score
    zscore = None
    if series is not None:
        try:
            s = series.dropna()
            if len(s) >= 90:
                mean = float(s.iloc[-90:].mean())
                std = float(s.iloc[-90:].std())
                if std > 0:
                    zscore = (float(s.iloc[-1]) - mean) / std
        except Exception:
            pass
    cards.append(_make_card(
        card_id=f"derivatives_funding_rate_zscore_90d_{today}",
        category="derivatives", tier="reference",
        name="资金费率 Z 分数 · 90 日",
        name_en="Funding Rate Z-Score 90d",
        current_value=round(zscore, 2) if zscore is not None else None,
        captured_at_bjt=ts,
        plain_interpretation=(
            (f"📊 Z={zscore:.2f},极端水平,资金费率显著偏离过去 90 天均值\n"
             f"🔍 |Z| > 2 = 极端;|Z| 1-2 = 偏高;|Z| < 1 = 正常"
             ) if zscore is not None and abs(zscore) > 2
            else (f"📊 Z={zscore:.2f},正常区间内\n🔍 |Z| > 2 = 极端;|Z| 1-2 = 偏高;|Z| < 1 = 正常"
                  ) if zscore is not None
            else "📊 数据不足(需 90 天)\n🔍 |Z| > 2 = 极端;|Z| 1-2 = 偏高;|Z| < 1 = 正常"
        ),
        strategy_impact="📍 当前资金费率相对过去 90 天分布的标准化偏离。极端 Z 值是反向交易的辅助信号。",
        impact_direction="neutral", impact_weight=0.3,
        linked_layer="L4", source="CoinGlass",
    ))

    # OI 绝对值
    oi_series = derivatives.get("open_interest") if isinstance(derivatives, dict) else None
    val, ts = _latest(oi_series)
    cards.append(_make_card(
        card_id=f"derivatives_oi_current_{today}",
        category="derivatives", tier="reference",
        name="未平仓合约 · 当前", name_en="Open Interest",
        current_value=round(val, 2) if val is not None else None,
        captured_at_bjt=ts,
        plain_interpretation=(
            f"📊 OI 当前规模 {val:,.0f}\n"
            f"🔍 单看绝对值意义有限,主要看与历史水平的对比 + 变化速度"
            if val is not None
            else "📊 数据不足\n🔍 OI 绝对值需要配合变化率判断"
        ),
        strategy_impact="📍 OI(未平仓合约)= 永续合约市场上所有未平仓的多空合约总规模。配合 24h 变化率才能判断杠杆累积速度。",
        impact_direction="neutral", impact_weight=0.3,
        linked_layer="L4", source="CoinGlass",
    ))

    # 清算(liquidation)— 不能用 `a or b`,pd.Series bool 报 ambiguous
    # Sprint 2.6-C:DerivativesDAO.get_all_metrics 把 liquidation_total/long/short
    # 作为独立 key,优先用 liquidation_total(代表 24h 总清算)。
    # 兼容旧名 'liquidation' / 'liquidation_24h' 仅作 fallback。
    liq_series = None
    if isinstance(derivatives, dict):
        for k in ("liquidation_total", "liquidation", "liquidation_24h"):
            v = derivatives.get(k)
            if v is not None:
                liq_series = v
                break
    val, ts = _latest(liq_series)
    cards.append(_make_card(
        card_id=f"derivatives_liquidation_24h_{today}",
        category="derivatives", tier="reference",
        name="24h 清算总额", name_en="Liquidation 24h",
        current_value=round(val, 2) if val is not None else None,
        value_unit="USD",
        captured_at_bjt=ts,
        plain_interpretation=(
            f"📊 过去 24 小时全市场清算总额 ${val:,.0f}\n"
            f"🔍 极端单日清算(数十亿美元)常伴随急涨急跌的反向行情结束"
            if val is not None
            else "📊 数据不足\n🔍 极端清算事件是去杠杆信号"
        ),
        strategy_impact="📍 过去 24 小时被强制平仓的合约总额(美元)。极端值往往是市场情绪反转的信号(瀑布式清算后常出现反弹)。",
        impact_direction="neutral", impact_weight=0.4,
        linked_layer="L4", source="CoinGlass",
    ))

    # 多空比变化率(24h 变化)— 同上
    lsr_series = None
    if isinstance(derivatives, dict):
        for k in ("long_short_ratio", "long_short_ratio_top",
                  "long_short_ratio_global"):
            v = derivatives.get(k)
            if v is not None:
                lsr_series = v
                break
    lsr_24h_change = _pct_change(lsr_series, 1)
    val, ts = _latest(lsr_series)
    cards.append(_make_card(
        card_id=f"derivatives_lsr_change_24h_{today}",
        category="derivatives", tier="reference",
        name="多空比 24h 变化", name_en="LSR 24h Change",
        current_value=round(lsr_24h_change, 2) if lsr_24h_change is not None else None,
        value_unit="%",
        captured_at_bjt=ts,
        plain_interpretation=(
            f"📊 大户多空比 24h 变化 {lsr_24h_change:+.1f}%\n"
            f"🔍 短时间剧烈变化常意味着大户立场转变,值得留意"
            if lsr_24h_change is not None
            else "📊 数据不足\n🔍 短时间剧烈变化常反映大户情绪转向"
        ),
        strategy_impact="📍 大户多空比的 24 小时变化速度。跟踪大户情绪变化的快慢,配合绝对值看是趋势性还是噪声。",
        impact_direction="neutral", impact_weight=0.3,
        linked_layer="L4", source="CoinGlass",
    ))

    # 全交易所加权资金费率(若有)
    series_agg = derivatives.get("funding_rate_aggregated") if isinstance(derivatives, dict) else None
    val, ts = _latest(series_agg)
    cards.append(_make_card(
        card_id=f"derivatives_funding_rate_aggregated_{today}",
        category="derivatives", tier="reference",
        name="全交易所资金费率", name_en="Funding Rate (All Exchanges)",
        current_value=round(val * 100, 4) if val is not None else None,
        value_unit="%",
        captured_at_bjt=ts,
        plain_interpretation=(
            f"📊 全市场加权资金费率 {val*100:.4f}%\n"
            f"🔍 看跨交易所平均比单家更有代表性"
            if val is not None
            else "📊 数据不足(只有币安数据可用)\n🔍 看跨交易所平均比单家更有代表性"
        ),
        strategy_impact="📍 多家交易所资金费率的加权平均,跨交易所拥挤度的参考指标。",
        impact_direction="neutral", impact_weight=0.3,
        linked_layer="L4", source="CoinGlass",
    ))

    return cards


# ============================================================
# 价格技术 reference
# ============================================================

def _emit_price_tech_reference(klines_1d: Any, today: str) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    if klines_1d is None or not isinstance(klines_1d, pd.DataFrame) or len(klines_1d) < 20:
        # 4 张占位
        for name_en, name_cn in [
            ("MA-20", "MA 20"), ("MA-60", "MA 60"),
            ("MA-120", "MA 120"), ("MA-200", "MA 200"),
        ]:
            cards.append(_make_card(
                card_id=f"price_{name_en.lower().replace('-', '_')}_{today}",
                category="price_structure", tier="reference",
                name=name_cn, name_en=name_en,
                linked_layer="L1", source="Binance klines",
                plain_interpretation=("📊 数据不足(需至少 20 天 K 线)\n"
                                      "🔍 价格在均线上方 = 支撑;在下方 = 阻力"),
                strategy_impact=f"📍 {name_cn}(均线)。价格相对均线的位置反映该周期内的趋势倾向。",
            ))
        return cards
    closes = klines_1d["close"].astype(float)
    current = float(closes.iloc[-1])
    ts = _to_bjt(klines_1d.index[-1])
    for period, name_cn in [(20, "MA 20"), (60, "MA 60"),
                            (120, "MA 120"), (200, "MA 200")]:
        if len(closes) >= period:
            ma = float(closes.tail(period).mean())
            diff_pct = (current / ma - 1.0) * 100.0
            direction = "bullish" if diff_pct > 0 else "bearish"
            if diff_pct > 0:
                interp = (
                    f"📊 当前价格高于 {name_cn} {diff_pct:.1f}%\n"
                    f"🔍 价格在 {name_cn} 上方 = 该周期均线对价格构成支撑"
                )
            else:
                interp = (
                    f"📊 当前价格低于 {name_cn} {-diff_pct:.1f}%\n"
                    f"🔍 价格在 {name_cn} 下方 = 该周期均线对价格构成阻力"
                )
        else:
            ma = None
            diff_pct = None
            direction = "neutral"
            interp = (f"📊 数据不足(需 {period} 天,当前仅 {len(closes)} 天)\n"
                      f"🔍 价格在均线上方 = 支撑;在下方 = 阻力")
        cards.append(_make_card(
            card_id=f"price_ma_{period}_{today}",
            category="price_structure", tier="reference",
            name=name_cn, name_en=f"MA-{period}",
            current_value=round(ma, 2) if ma is not None else None,
            captured_at_bjt=ts,
            plain_interpretation=interp,
            strategy_impact=(f"📍 {name_cn}(过去 {period} 个交易日的算术平均价)。"
                             f"价格相对均线的位置反映该周期内的趋势倾向。"),
            impact_direction=direction, impact_weight=0.4,
            linked_layer="L1", source="Binance klines",
        ))
    return cards


# ============================================================
# 宏观 reference
# ============================================================

def _emit_macro_reference(macro: dict[str, Any], today: str) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []

    us10y = macro.get("us10y") if isinstance(macro, dict) else None
    us10y_30d = _pct_change(us10y, 30)
    val, ts = _latest(us10y)
    cards.append(_make_card(
        card_id=f"macro_us10y_30d_change_{today}",
        category="macro", tier="reference",
        name="美国 10 年期国债收益率 30 日变化", name_en="US10Y 30d Change",
        current_value=round(us10y_30d, 2) if us10y_30d is not None else None,
        value_unit="%",
        captured_at_bjt=ts,
        plain_interpretation=(
            f"📊 美国 10 年期国债收益率 30 日变化 {us10y_30d:+.2f}%\n"
            f"🔍 > +30bp(基点)= 利率快速上行(对风险资产逆风);±30bp = 正常;< -30bp = 快速下行(顺风)"
            if us10y_30d is not None
            else "📊 数据不足\n🔍 > +30bp = 利率上行(逆风);±30bp = 正常;< -30bp = 利率下行(顺风)"
        ),
        strategy_impact="📍 US10Y(美国 10 年期国债收益率)= 全球风险资产定价的无风险利率基准。快速上升通常压制风险资产估值。",
        impact_direction=_impact_direction_from_value(us10y_30d, bear_above=0.3),
        impact_weight=0.6,
        linked_layer="L5", source="Yahoo / FRED",
    ))

    nasdaq = macro.get("nasdaq") if isinstance(macro, dict) else None
    nasdaq_20d = _pct_change(nasdaq, 20)
    val, ts = _latest(nasdaq)
    cards.append(_make_card(
        card_id=f"macro_nasdaq_20d_change_{today}",
        category="macro", tier="reference",
        name="纳指 20 日变化", name_en="Nasdaq 20d Change",
        current_value=round(nasdaq_20d, 2) if nasdaq_20d is not None else None,
        value_unit="%",
        captured_at_bjt=ts,
        plain_interpretation=(
            f"📊 纳指过去 20 日变化 {nasdaq_20d:+.2f}%\n"
            f"🔍 > +5% = 风险偏好上升(对 BTC 顺风);±5% = 中性;< -5% = 风险情绪恶化(对 BTC 逆风)"
            if nasdaq_20d is not None
            else "📊 数据不足\n🔍 > +5% = 顺风;±5% = 中性;< -5% = 逆风"
        ),
        strategy_impact="📍 美股纳指(科技股权重高)的 20 日表现。BTC 与纳指相关性较高,纳指强弱常领先反映风险偏好。",
        impact_direction=_impact_direction_from_value(nasdaq_20d, bear_below=-5, bull_above=5),
        impact_weight=0.6,
        linked_layer="L5", source="Yahoo Finance",
    ))

    # 简化相关性(从 l5 或 macro_headwind composite 里读)
    cards.append(_make_card(
        card_id=f"macro_btc_nasdaq_corr_60d_{today}",
        category="macro", tier="reference",
        name="BTC-纳指 60 日相关性", name_en="BTC-Nasdaq 60d Correlation",
        current_value=None,
        captured_at_bjt=None,
        plain_interpretation=("📊 由宏观逆风指数计算;> 0.7 时系统会加大宏观信号权重\n"
                              "🔍 BTC 与纳指相关性高 = 同涨同跌,宏观权重增加;相关性低 = 独立行情"),
        strategy_impact="📍 BTC 与美股纳指过去 60 天的滚动相关系数。相关性高时,纳指变化对 BTC 影响放大。",
        impact_direction="neutral", impact_weight=0.4,
        linked_layer="L5", source="derived",
    ))
    cards.append(_make_card(
        card_id=f"macro_btc_gold_corr_60d_{today}",
        category="macro", tier="reference",
        name="BTC-黄金 60 日相关性", name_en="BTC-Gold 60d Correlation",
        current_value=None,
        captured_at_bjt=None,
        plain_interpretation=("📊 数据采集尚未接入(后续 sprint 启用)\n"
                              "🔍 BTC 与黄金正相关 = 数字黄金叙事强;负相关 = 风险资产属性强"),
        strategy_impact="📍 BTC 与黄金过去 60 天的相关系数,用于跟踪BTC 的数字黄金叙事强度。",
        impact_direction="neutral", impact_weight=0.2,
        linked_layer="L5", source="derived",
    ))
    return cards


# ============================================================
# 事件 reference
# ============================================================

def _emit_events_reference(events: list[Any], today: str) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    # 按类型找最近一个
    target_types = ("fomc", "cpi", "nfp")
    type_labels = {"fomc": "FOMC 利率决议", "cpi": "CPI 通胀数据", "nfp": "非农就业数据"}
    seen: dict[str, dict[str, Any]] = {}
    for ev in events or []:
        if not isinstance(ev, dict):
            continue
        t = (ev.get("event_type") or "").lower()
        if t in target_types and t not in seen:
            seen[t] = ev
    event_descriptions = {
        "fomc": "📍 FOMC = 美联储议息会议,决定基准利率。是月度级别最重要的宏观事件之一,常引发风险资产剧烈波动。",
        "cpi": "📍 CPI = 美国消费者物价指数,衡量通胀。CPI 数据会直接影响美联储加息预期和市场风险情绪。",
        "nfp": "📍 NFP = 美国非农就业数据(每月第一个周五公布)。反映美国就业市场强弱,影响美联储政策预期。",
    }
    for t in target_types:
        ev = seen.get(t)
        label = type_labels[t]
        hours_to = ev.get("hours_to") if ev else None
        cards.append(_make_card(
            card_id=f"event_{t}_next_{today}",
            category="events", tier="reference",
            name=f"下次{label}", name_en=f"Next {t.upper()}",
            current_value=(round(hours_to, 1) if hours_to is not None else None),
            value_unit="小时",
            captured_at_bjt=datetime.now(_BJT).strftime("%Y-%m-%d %H:%M (BJT)"),
            data_fresh=True,
            plain_interpretation=(
                (f"📊 距离下次 {label} 还有 {hours_to:.0f} 小时\n"
                 f"🔍 < 24h = 高风险窗口(系统降档);24-48h = 中等风险;48-72h = 低风险;> 72h = 无影响"
                 ) if hours_to is not None
                else (f"📊 未来 72 小时内无 {label}\n"
                      f"🔍 < 24h = 高风险窗口;24-48h = 中等;48-72h = 低;> 72h = 无影响")
            ),
            strategy_impact=event_descriptions[t],
            impact_direction=("bearish" if hours_to is not None and hours_to < 48 else "neutral"),
            impact_weight=0.5,
            linked_layer="L4", source="Event calendar",
        ))
    return cards
