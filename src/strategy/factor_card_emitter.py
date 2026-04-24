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
         "趋势强度综合判定,影响 L1.regime_confidence"),
        ("band_position", "band_position", "波段位置综合指数",
         "BandPosition", "L2",
         "当前波段阶段(early/mid/late/exhausted),影响 L2.phase"),
        ("cycle_position", "cycle_position", "长周期位置",
         "CyclePosition", "L2",
         "BTC 在多年周期中的位置(9 档),影响做多做空动态门槛"),
        ("crowding", "crowding", "拥挤度指数",
         "Crowding", "L4",
         "衍生品是否极端拥挤,影响 position_cap(≥6 时 × 0.7)"),
        ("macro_headwind", "macro_headwind", "宏观逆风指数",
         "MacroHeadwind", "L5",
         "宏观对风险资产顺风/逆风,≤-5 时 position_cap × 0.7"),
        ("event_risk", "event_risk", "风险事件密度",
         "EventRisk", "L4",
         "72h 内事件加权风险,≥8 时 position_cap × 0.7 + permission 降档"),
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
        return "数据不足(该组合因子未能产出)"
    score = data.get("score")
    band = data.get("band") or data.get("phase") or data.get("cycle_position")

    if key == "truth_trend":
        if score is None:
            return "趋势强度未能计算(数据不足)"
        if score >= 6:
            return f"当前 ADX + 均线 + 多周期一致性综合 {score} 分,属于真趋势。"
        if score >= 4:
            return f"当前趋势信号 {score} 分,弱趋势,谨慎跟进。"
        return f"当前趋势信号 {score} 分,无趋势,以区间思路为主。"

    if key == "cycle_position":
        if band is None or band == "unclear":
            return "长周期位置不明朗,三主指标未形成共识。"
        labels = {
            "accumulation": "累积期(底部吸筹)",
            "early_bull": "牛市早期",
            "mid_bull": "牛市中段",
            "late_bull": "牛市晚期",
            "distribution": "顶部分发期",
            "early_bear": "熊市早期",
            "mid_bear": "熊市中段",
            "late_bear": "熊市晚期",
        }
        return f"当前处于 {labels.get(band, band)},门槛按此调整。"

    if key == "crowding":
        if score is None:
            return "衍生品拥挤度未能计算。"
        if score >= 6:
            return f"拥挤度 {score}/8,极度拥挤,反向挤压风险增加。"
        if score >= 4:
            return f"拥挤度 {score}/8,偏拥挤,仓位乘数 × 0.85。"
        return f"拥挤度 {score}/8,正常。"

    if key == "macro_headwind":
        if score is None:
            return "宏观逆风未能计算。"
        if score <= -5:
            return f"宏观强逆风({score}),仓位上限 × 0.7。"
        if score <= -2:
            return f"宏观轻度逆风({score}),仓位上限 × 0.85。"
        return f"宏观中性或顺风({score})。"

    if key == "event_risk":
        if score is None:
            return "事件风险未能计算。"
        if score >= 8:
            return f"72h 事件密度高({score}),仓位 × 0.7 + 权限降档。"
        if score >= 4:
            return f"72h 事件密度中等({score}),仓位 × 0.85。"
        return f"72h 事件密度低({score}),正常。"

    if key == "band_position":
        labels = {"early": "早期", "mid": "中期", "late": "晚期", "exhausted": "衰竭期"}
        return f"当前波段位置:{labels.get(band, band or '未知')}。"

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
            f"市场估值偏高,过去 180 天 {pct}% 分位" if val is not None and pct and pct >= 70
            else f"市场估值偏低,过去 180 天 {pct}% 分位" if val is not None and pct and pct <= 30
            else f"MVRV Z={val:.2f}" if val is not None else "数据不足"
        ),
        strategy_impact="CyclePosition 主裁决因子:>2 偏分发期,<-0.5 偏累积期",
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
            "整体持仓处于盈利状态(Belief 区间)" if val is not None and 0.5 <= val < 0.75
            else "市场 Euphoria 区间,历史顶部信号" if val is not None and val >= 0.75
            else "市场 Capitulation 区间,历史底部信号" if val is not None and val <= 0
            else f"NUPL={val:.2f}" if val is not None else "数据不足"
        ),
        strategy_impact="CyclePosition 主裁决:>0.65 分发期,<0 累积期",
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
            f"长期持有者过去 90 天净增持 {change_90d:.1f}%,底部吸筹中" if change_90d is not None and change_90d > 2
            else f"长期持有者过去 90 天净减持 {change_90d:.1f}%,顶部分发中" if change_90d is not None and change_90d < -3
            else f"LTH 供应 90 日变化 {change_90d:.1f}%,稳定" if change_90d is not None
            else "数据不足(需 90 天历史)"
        ),
        strategy_impact="CyclePosition 主裁决因子:>+2% 增持 / <-3% 减持",
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
            f"7 日均净流入 {avg7:.0f} BTC,供应压力增加" if avg7 is not None and avg7 > 500
            else f"7 日均净流出 {-avg7:.0f} BTC,持币意愿增强" if avg7 is not None and avg7 < -500
            else f"交易所净流量 {avg7:.0f} BTC/日,平稳" if avg7 is not None
            else "数据不足"
        ),
        strategy_impact="ExchangeMomentum 修正 L2.stance_confidence(× 1.05 或 × 0.95)",
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
            f"当前距离历史最高价 {drawdown_pct:.1f}%,深度回撤" if drawdown_pct is not None and drawdown_pct < -20
            else f"当前距离 ATH {drawdown_pct:.1f}%,相对高位" if drawdown_pct is not None and drawdown_pct > -5
            else f"距 ATH 跌幅 {drawdown_pct:.1f}%" if drawdown_pct is not None
            else "数据不足(需 K 线历史)"
        ),
        strategy_impact="CyclePosition 辅助:>20% 跌幅是 early_bear 辅助条件",
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
            f"储备风险偏高({val:.4f}),长期持有者倾向抛售" if val is not None and val > 0.02
            else f"储备风险偏低({val:.4f}),长期持有者惜售" if val is not None and val < 0.002
            else f"Reserve Risk={val:.4f}" if val is not None
            else "数据不足"
        ),
        strategy_impact="底部信号:<0.002 是历史底部区间,买入性价比高",
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
            "资金费率过热,多头杠杆累积,反向挤压风险升高" if val is not None and val > 0.0003
            else "资金费率深度为负,空头拥挤,反向挤压潜在" if val is not None and val < -0.0002
            else "资金费率中性" if val is not None else "数据不足"
        ),
        strategy_impact="Crowding 主因子,>0.03% 且连续 3 次 → +2 分",
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
            f"资金费率在过去 30 日的 {pct:.0f}% 分位,历史高位" if pct is not None and pct >= 85
            else f"资金费率在过去 30 日 {pct:.0f}% 分位" if pct is not None
            else "数据不足"
        ),
        strategy_impact="Crowding 主因子,>85 分位 → +2 分",
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
            f"OI 24h +{change_24h:.1f}%,杠杆快速累积" if change_24h is not None and change_24h > 15
            else f"OI 24h {change_24h:.1f}%,正常" if change_24h is not None
            else "数据不足(需至少 2 日 OI)"
        ),
        strategy_impact="Crowding 主因子,>+15% → +1 分",
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
            f"大户多头占比极高({val:.2f}),多头拥挤" if val is not None and val > 2.5
            else f"大户多空比 {val:.2f}" if val is not None else "数据不足"
        ),
        strategy_impact="Crowding 主因子,>2.5 → +1 分",
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

    # ADX-14(1D)—— 如果 L1 已算过直接读
    adx = l1.get("adx_14_1d") or l1.get("adx_1d")
    if adx is None:
        adx = _compute_adx_latest(klines_1d)
    ts = _to_bjt(klines_1d.index[-1]) if isinstance(klines_1d, pd.DataFrame) and len(klines_1d) > 0 else None
    cards.append(_make_card(
        card_id=f"price_adx_14_1d_{today}",
        category="price_structure", tier="primary",
        name="ADX-14(1D)", name_en="ADX-14 Daily",
        current_value=round(adx, 2) if adx is not None else None,
        captured_at_bjt=ts,
        plain_interpretation=(
            f"ADX={adx:.1f}≥25,存在明确趋势" if adx is not None and adx >= 25
            else f"ADX={adx:.1f},震荡市" if adx is not None
            else "数据不足(需 20+ 天)"
        ),
        strategy_impact="TruthTrend 主因子,≥25 → +2 分",
        impact_direction=_impact_direction_from_value(adx, bull_above=25),
        impact_weight=0.85,
        linked_layer="L1", source="Binance klines",
    ))

    # ATR 百分位
    atr_pct = l1.get("atr_percentile_180d") or l1.get("atr_pct")
    if atr_pct is None:
        atr_pct = _compute_atr_percentile(klines_1d)
    cards.append(_make_card(
        card_id=f"price_atr_percentile_180d_{today}",
        category="price_structure", tier="primary",
        name="ATR 180 日分位", name_en="ATR 180d Percentile",
        current_value=round(atr_pct, 1) if atr_pct is not None else None,
        value_unit="分位",
        captured_at_bjt=ts,
        plain_interpretation=(
            f"波动率在历史 {atr_pct:.0f}% 分位,极端波动" if atr_pct is not None and atr_pct > 85
            else f"波动率在历史 {atr_pct:.0f}% 分位,偏低" if atr_pct is not None and atr_pct < 20
            else f"波动率 {atr_pct:.0f}% 分位,正常" if atr_pct is not None
            else "数据不足(需 180 天)"
        ),
        strategy_impact="L1.volatility_regime 主因子,决定 stop_loss ATR 倍数",
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
            "4H/1D/1W 方向一致,趋势强度高"
            if alignment and alignment_value
            else "数据不足或各周期方向分歧"
        ),
        strategy_impact="TruthTrend 主因子,三周期一致 → +3 分",
        impact_direction=alignment_direction,
        impact_weight=0.85,
        linked_layer="L1", source="Binance klines",
    ))
    return cards


def _compute_adx_latest(klines_1d: Any) -> Optional[float]:
    try:
        from src.indicators.volatility import atr
    except Exception:
        return None
    try:
        # 用现成的 indicator?没有单独的 ADX indicator 函数;
        # 这里简单回退:若 L1 没提供就返回 None
        return None
    except Exception:
        return None


def _compute_atr_percentile(klines_1d: Any) -> Optional[float]:
    if klines_1d is None or not isinstance(klines_1d, pd.DataFrame) or len(klines_1d) < 30:
        return None
    try:
        from src.indicators.volatility import atr
        atr_series = atr(
            klines_1d["high"], klines_1d["low"], klines_1d["close"], period=14,
        ).dropna()
        if len(atr_series) < 30:
            return None
        atr_rel = atr_series / klines_1d["close"]
        atr_rel = atr_rel.dropna()
        if len(atr_rel) < 30:
            return None
        recent = atr_rel.iloc[-1]
        window = atr_rel.iloc[-180:] if len(atr_rel) > 180 else atr_rel
        pct = (window <= recent).sum() / len(window) * 100.0
        return round(float(pct), 1)
    except Exception:
        return None


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
            f"美元 20 日 +{dxy_20d:.1f}%,对风险资产逆风" if dxy_20d is not None and dxy_20d > 2
            else f"美元 20 日 {dxy_20d:.1f}%,对风险资产顺风" if dxy_20d is not None and dxy_20d < -2
            else f"美元 20 日 {dxy_20d:.1f}%,中性" if dxy_20d is not None
            else "数据不足(需 20 天 DXY)"
        ),
        strategy_impact="MacroHeadwind 主因子,>+2% → -2 分",
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
            f"VIX={val:.1f},极端恐慌,风险资产承压" if val is not None and val > 35
            else f"VIX={val:.1f},elevated 风险意识" if val is not None and val > 25
            else f"VIX={val:.1f},市场情绪平静" if val is not None
            else "数据不足"
        ),
        strategy_impact="MacroHeadwind 主因子,>25 → -2 分;极端事件检测",
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
         "市值 / 实现市值,<1 底部区间"),
        ("realized_price", "onchain_realized_price", "实现价格",
         "Realized Price", "平均成本价"),
        ("lth_realized_price", "onchain_lth_realized_price", "LTH 实现价格",
         "LTH Realized Price", "长期持有者成本价"),
        ("sth_realized_price", "onchain_sth_realized_price", "STH 实现价格",
         "STH Realized Price", "短期持有者成本价"),
        ("sopr", "onchain_sopr", "SOPR", "SOPR",
         ">1 整体盈利卖出,<1 亏损卖出"),
        ("sopr_adjusted", "onchain_asopr", "aSOPR",
         "Adjusted SOPR", "排除 1h 内交易的 SOPR"),
        ("puell_multiple", "onchain_puell_multiple", "Puell Multiple",
         "Puell Multiple", "矿工收入倍数,顶底信号"),
    ]
    for key, card_slug, name_cn, name_en, desc in _ref_specs:
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
                f"当前 {val:.3f},180 日分位 {pct:.0f}%" if val is not None and pct is not None
                else f"{name_en}={val:.3f}" if val is not None
                else "数据不足"
            ),
            strategy_impact=desc,
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
        plain_interpretation=(f"7 日均 {avg7 * 100:.4f}%" if avg7 is not None else "数据不足"),
        strategy_impact="衍生品趋势辅助",
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
            f"Z={zscore:.2f},极端水平" if zscore is not None and abs(zscore) > 2
            else f"Z={zscore:.2f}" if zscore is not None
            else "数据不足(需 90 天)"
        ),
        strategy_impact="资金费率极值警报",
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
        plain_interpretation=(f"OI = {val:,.0f}" if val is not None else "数据不足"),
        strategy_impact="配合 24h 变化率看杠杆累积速度",
        impact_direction="neutral", impact_weight=0.3,
        linked_layer="L4", source="CoinGlass",
    ))

    # 清算(liquidation)— 不能用 `a or b`,pd.Series bool 报 ambiguous
    liq_series = None
    if isinstance(derivatives, dict):
        for k in ("liquidation", "liquidation_24h"):
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
            f"24h 清算 ${val:,.0f}" if val is not None else "数据不足"
        ),
        strategy_impact="清算密度指数因子,极端爆仓事件信号",
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
            f"大户多空比 24h 变化 {lsr_24h_change:.1f}%" if lsr_24h_change is not None
            else "数据不足"
        ),
        strategy_impact="跟踪大户情绪变化速度",
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
            f"全市场加权费率 {val*100:.4f}%" if val is not None else "数据不足(仅币安主因子可用)"
        ),
        strategy_impact="跨交易所拥挤度参考",
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
                plain_interpretation="数据不足(需至少 20 天 K 线)",
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
            interp = (
                f"当前价格高于 {name_cn} {diff_pct:.1f}%" if diff_pct > 0
                else f"当前价格低于 {name_cn} {-diff_pct:.1f}%"
            )
        else:
            ma = None
            diff_pct = None
            direction = "neutral"
            interp = f"数据不足(需 {period} 天,当前仅 {len(closes)} 天)"
        cards.append(_make_card(
            card_id=f"price_ma_{period}_{today}",
            category="price_structure", tier="reference",
            name=name_cn, name_en=f"MA-{period}",
            current_value=round(ma, 2) if ma is not None else None,
            captured_at_bjt=ts,
            plain_interpretation=interp,
            strategy_impact="均线系统,组合判断趋势结构",
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
            f"10Y 30 日 {us10y_30d:+.2f}%" if us10y_30d is not None else "数据不足"
        ),
        strategy_impact="MacroHeadwind 因子,>+30bp → -2 分",
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
            f"纳指 20 日 {nasdaq_20d:+.2f}%" if nasdaq_20d is not None else "数据不足"
        ),
        strategy_impact="MacroHeadwind:<-5% 或 >+5% 各加 2 分",
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
        plain_interpretation="由 MacroHeadwind composite 计算;>0.7 时宏观权重 × 1.5",
        strategy_impact="MacroHeadwind 权重修正",
        impact_direction="neutral", impact_weight=0.4,
        linked_layer="L5", source="derived",
    ))
    cards.append(_make_card(
        card_id=f"macro_btc_gold_corr_60d_{today}",
        category="macro", tier="reference",
        name="BTC-黄金 60 日相关性", name_en="BTC-Gold 60d Correlation",
        current_value=None,
        captured_at_bjt=None,
        plain_interpretation="数字黄金叙事监测,Sprint 2.x 再接入",
        strategy_impact="叙事监测",
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
                f"距离下次 {label} {hours_to:.0f} 小时" if hours_to is not None
                else f"72 小时内无 {label}"
            ),
            strategy_impact="EventRisk 因子,48h 内事件加分并降档",
            impact_direction=("bearish" if hours_to is not None and hours_to < 48 else "neutral"),
            impact_weight=0.5,
            linked_layer="L4", source="Event calendar",
        ))
    return cards
