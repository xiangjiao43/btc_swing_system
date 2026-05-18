"""Build Layer A spot-cycle context.

The builder only reads existing market data.  It does not use Layer B grades,
does not create thesis data, and does not invent unavailable factors.
"""

from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pandas as pd

from .context_builder import (
    compute_btc_macro_corr_60d,
    compute_emas_1d,
    compute_exchange_flow_features,
    compute_funding_features,
    compute_lth_sth_changes,
    compute_macro_features,
    compute_oi_features,
    compute_price_features,
    compute_tf_alignment,
)
from .spot_cycle_stage_state import (
    OFFICIAL_CYCLE_STAGES,
    normalize_stage,
    previous_official_stage,
)
from ..data.storage.dao import (
    BTCKlinesDAO,
    DerivativesDAO,
    EventsCalendarDAO,
    MacroDAO,
    OnchainDAO,
)


_FACTOR_SOURCE = {
    "mvrv_z_score": "glassnode_onchain",
    "mvrv": "glassnode_onchain",
    "nupl": "glassnode_onchain",
    "realized_price": "glassnode_onchain",
    "lth_realized_price": "glassnode_onchain",
    "sth_realized_price": "glassnode_onchain",
    "lth_supply": "glassnode_onchain",
    "sth_supply": "glassnode_onchain",
    "percent_supply_in_profit": "glassnode_onchain",
    "percent_supply_in_loss": "glassnode_onchain_derived",
    "exchange_balance": "glassnode_onchain",
    "exchange_net_position_change": "glassnode_onchain_derived",
    "lth_sopr": "glassnode_layer_a",
    "sth_sopr": "glassnode_layer_a",
    "rhodl_ratio": "glassnode_layer_a",
    "reserve_risk": "glassnode_layer_a",
    "puell_multiple": "glassnode_layer_a",
    "lth_net_position_change": "glassnode_layer_a",
    "hash_rate": "glassnode_layer_a",
    "sopr": "glassnode_display",
    "ma_200w_deviation_pct": "coinglass_derivatives_derived",
    "exchange_net_flow": "glassnode_onchain",
    "sopr_adjusted": "glassnode_onchain",
    "hodl_waves": "glassnode_onchain",
    "cdd": "glassnode_onchain",
    "ssr": "glassnode_onchain",
    "funding_rate": "coinglass_derivatives",
    "open_interest": "coinglass_derivatives",
    "long_short_ratio": "coinglass_derivatives",
    "liquidation_total": "coinglass_derivatives",
    "etf_flow": "coinglass_derivatives",
    "btc_dominance": "coinglass_derivatives",
    "dxy": "fred_macro",
    "dgs10": "fred_macro",
    "us10y": "fred_macro",
    "us2y": "fred_macro",
    "real_yield": "fred_macro",
    "fed_funds_rate": "fred_macro",
    "cpi": "fred_macro",
    "core_cpi": "fred_macro",
    "m2": "fred_macro",
    "fed_balance_sheet": "fred_macro",
    "vix": "fred_macro",
    "nasdaq": "fred_macro",
    "monthly_ohlc_structure": "coinglass_derivatives_derived",
    "major_support_resistance_zones": "coinglass_derivatives_derived",
    "hodl_waves_1y_plus_aggregate": "glassnode_onchain_derived",
}

_UNAVAILABLE_MODEL_FACTORS: dict[str, str] = {}

_A1_CORE_FACTORS = {
    "current_close", "ath_drawdown_pct", "ma_200d", "ma_200w",
    "ma_200w_deviation_pct",
    "realized_price", "sth_realized_price", "lth_realized_price",
    "mvrv_z_score", "mvrv", "nupl", "rhodl_ratio", "reserve_risk",
    "puell_multiple", "lth_sopr", "sth_sopr", "sopr", "lth_supply",
    "sth_supply", "lth_net_position_change", "percent_supply_in_profit",
    "percent_supply_in_loss", "hodl_waves", "hodl_waves_1y_plus_aggregate",
    "cdd", "exchange_balance", "exchange_net_position_change",
    "hash_rate",
    "monthly_ohlc_structure", "major_support_resistance_zones",
}
_A2_A4_BACKGROUND_FACTORS = {
    "etf_flow", "exchange_net_flow", "exchange_net_flow_30d_sum",
    "etf_flow_7d_sum_usd", "etf_flow_30d_sum_usd", "real_yield",
    "fed_funds_rate", "us2y", "dxy", "vix", "nasdaq",
    "btc_nasdaq_corr_60d", "cpi", "core_cpi", "m2",
    "fed_balance_sheet", "events_count",
}
_LAYER_B_CONTEXT_FACTORS = {
    "funding_rate", "funding_rate_z_score_90d", "open_interest",
    "open_interest_z_score_90d", "long_short_ratio", "liquidation_total",
    "btc_dominance",
}
_CRITICAL_MODEL_FACTORS = {
    "mvrv_z_score", "mvrv", "nupl", "rhodl_ratio", "reserve_risk",
    "puell_multiple", "lth_sopr", "sth_sopr", "lth_net_position_change",
    "hodl_waves_1y_plus_aggregate", "cdd", "exchange_balance",
    "monthly_ohlc_structure", "major_support_resistance_zones",
}

# FRED 的 CPI / Core CPI 是月度宏观数据。它们的“最新一期”天然不会每天更新，
# 不能因为 fred_macro 这类源级 freshness 短暂过期就把已有数值判成不可用。
_MONTHLY_FRED_FACTORS = {"cpi", "core_cpi"}
_MACRO_METRIC_ALIASES = {
    "cpi": ("cpi", "cpiaucsl", "CPIAUCSL"),
    "core_cpi": ("core_cpi", "cpilfesl", "CPILFESL"),
}


def _series_latest(series: Any) -> tuple[Optional[float], Optional[str]]:
    if series is None:
        return None, None
    try:
        s = series.dropna().astype(float)
        if len(s) == 0:
            return None, None
        ts = s.index[-1]
        ts_s = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        return float(s.iloc[-1]), ts_s
    except Exception:
        return None, None


def _pct_change(series: Any, periods: int) -> Optional[float]:
    try:
        s = series.dropna().astype(float)
        if len(s) <= periods:
            return None
        prev = float(s.iloc[-periods - 1])
        cur = float(s.iloc[-1])
        if prev == 0:
            return None
        return (cur / prev - 1.0) * 100.0
    except Exception:
        return None


def _series_latest_delta(series: Any, periods: int = 1) -> tuple[Optional[float], Optional[str]]:
    if series is None:
        return None, None
    try:
        s = series.dropna().astype(float)
        if len(s) <= periods:
            return None, None
        ts = s.index[-1]
        ts_s = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        return float(s.iloc[-1] - s.iloc[-periods - 1]), ts_s
    except Exception:
        return None, None


def _latest_series_timestamp(*series_items: Any) -> Optional[str]:
    latest: Optional[pd.Timestamp] = None
    for series in series_items:
        try:
            s = series.dropna()
            if len(s) == 0:
                continue
            ts = pd.to_datetime(s.index[-1], utc=True)
            if latest is None or ts > latest:
                latest = ts
        except Exception:
            continue
    return latest.isoformat() if latest is not None else None


def _tail(series: Any, n: int = 30) -> list[dict[str, Any]]:
    try:
        s = series.dropna().astype(float).iloc[-n:]
        return [
            {"timestamp": idx.isoformat() if hasattr(idx, "isoformat") else str(idx),
             "value": float(v)}
            for idx, v in s.items()
        ]
    except Exception:
        return []


def _round(v: Any, digits: int = 4) -> Any:
    if isinstance(v, float) and math.isfinite(v):
        return round(v, digits)
    return v


def _compact_factor(v: Any) -> dict[str, Any]:
    """Return only the fields A1 needs for stage classification."""
    if not isinstance(v, dict):
        return {"value": v}
    out = {
        "value": v.get("actual_value"),
        "status": v.get("status"),
    }
    freshness = v.get("freshness") if isinstance(v.get("freshness"), dict) else {}
    if freshness:
        out["is_stale"] = bool(freshness.get("is_stale"))
        hours = freshness.get("hours_since_last_success")
        if hours is not None:
            out["hours_since_last_success"] = hours
    for key in ("as_of", "captured_at_utc", "fetched_at_utc"):
        if v.get(key):
            out[key] = v.get(key)
    return {k: val for k, val in out.items() if val is not None}


def _build_monthly_ohlc_structure(klines_1d: Any) -> tuple[Optional[str], Optional[str], dict[str, Any]]:
    """Derive a compact monthly structure from existing daily candles.

    This is deterministic and only feeds Layer A / raw factor display.  It does
    not create a trading signal by itself.
    """
    if klines_1d is None or getattr(klines_1d, "empty", True):
        return None, None, {"reason": "insufficient_daily_klines"}
    required = {"open", "high", "low", "close"}
    if not required.issubset(set(klines_1d.columns)):
        return None, None, {"reason": "missing_ohlc_columns"}
    try:
        daily = klines_1d[list(required)].dropna().astype(float)
        if len(daily) < 180:
            return None, None, {
                "reason": "insufficient_monthly_history",
                "daily_bars_available": int(len(daily)),
            }
        monthly = daily.resample("ME").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
        }).dropna()
        if len(monthly) < 6:
            return None, None, {
                "reason": "insufficient_monthly_history",
                "months_available": int(len(monthly)),
            }
        close_m = monthly["close"]
        latest_close = float(close_m.iloc[-1])
        change_3m = _pct_change(close_m, 3)
        change_6m = _pct_change(close_m, 6)
        ma_6m = float(close_m.rolling(6).mean().iloc[-1])
        recent_high_12m = float(monthly["high"].iloc[-12:].max())
        recent_low_12m = float(monthly["low"].iloc[-12:].min())

        if change_3m is not None and change_6m is not None and change_3m > 8 and change_6m > 12:
            trend = "up"
            label = "上行"
        elif (
            (change_3m is not None and change_3m > 3)
            or (change_6m is not None and change_6m > 8)
            or latest_close > ma_6m
        ):
            trend = "recovering"
            label = "修复中"
        elif change_3m is not None and change_6m is not None and change_3m < -8 and change_6m < -12:
            trend = "down"
            label = "下行"
        else:
            trend = "sideways"
            label = "震荡"

        if latest_close >= recent_high_12m * 0.97:
            location = "near_12m_high"
        elif latest_close <= recent_low_12m * 1.08:
            location = "near_12m_low"
        else:
            location = "between_major_range"

        return trend, close_m.index[-1].isoformat(), {
            "monthly_trend": trend,
            "price_location": location,
            "display_value": label,
            "latest_month_close": _round(latest_close, 2),
            "three_month_change_pct": _round(change_3m, 2),
            "six_month_change_pct": _round(change_6m, 2),
            "months_available": int(len(monthly)),
        }
    except Exception as exc:
        return None, None, {"reason": f"derive_error:{type(exc).__name__}"}


def _build_major_support_resistance(
    klines_1w: Any,
    klines_1d: Any,
    current_close: Any,
) -> tuple[Optional[str], Optional[str], dict[str, Any]]:
    if current_close is None:
        return None, None, {"reason": "missing_current_close"}
    try:
        price = float(current_close)
    except (TypeError, ValueError):
        return None, None, {"reason": "invalid_current_close"}

    source_df = klines_1w if klines_1w is not None and not getattr(klines_1w, "empty", True) else klines_1d
    source_name = "1w" if source_df is klines_1w else "1d"
    if source_df is None or getattr(source_df, "empty", True):
        return None, None, {"reason": "missing_price_structure"}
    if not {"high", "low"}.issubset(set(source_df.columns)):
        return None, None, {"reason": "missing_high_low_columns"}
    try:
        df = source_df[["high", "low", "close"]].dropna().astype(float).iloc[-156:]
        if len(df) < 26:
            return None, None, {
                "reason": "insufficient_support_resistance_history",
                "bars_available": int(len(df)),
            }
        highs = df["high"]
        lows = df["low"]
        swing_high = highs[(highs.shift(1) < highs) & (highs.shift(-1) < highs)]
        swing_low = lows[(lows.shift(1) > lows) & (lows.shift(-1) > lows)]
        support_candidates = swing_low[swing_low < price]
        resistance_candidates = swing_high[swing_high > price]
        nearest_support = (
            float(support_candidates.max())
            if len(support_candidates) else float(lows.iloc[-52:].min())
        )
        nearest_resistance = (
            float(resistance_candidates.min())
            if len(resistance_candidates) else float(highs.iloc[-52:].max())
        )
        if nearest_support >= price:
            nearest_support = None
        if nearest_resistance <= price:
            nearest_resistance = None
        if nearest_support is None and nearest_resistance is None:
            return None, None, {
                "reason": "no_major_levels_detected",
                "bars_available": int(len(df)),
            }

        support_text = f"{nearest_support:,.0f}" if nearest_support is not None else "-"
        resistance_text = f"{nearest_resistance:,.0f}" if nearest_resistance is not None else "-"
        value = f"支撑 {support_text} / 阻力 {resistance_text}"
        ts = df.index[-1].isoformat() if hasattr(df.index[-1], "isoformat") else str(df.index[-1])
        return value, ts, {
            "nearest_major_support": _round(nearest_support, 2),
            "nearest_major_resistance": _round(nearest_resistance, 2),
            "support_distance_pct": _round((price / nearest_support - 1.0) * 100.0, 2)
            if nearest_support else None,
            "resistance_distance_pct": _round((nearest_resistance / price - 1.0) * 100.0, 2)
            if nearest_resistance else None,
            "source_timeframe": source_name,
            "bars_available": int(len(df)),
        }
    except Exception as exc:
        return None, None, {"reason": f"derive_error:{type(exc).__name__}"}


def _compact_stage_history(previous: dict[str, Any]) -> list[dict[str, Any]]:
    if not previous:
        return []
    a1 = previous.get("a1_cycle_stage") if isinstance(previous.get("a1_cycle_stage"), dict) else {}
    a5 = previous.get("a5_spot_adjudicator") if isinstance(previous.get("a5_spot_adjudicator"), dict) else {}
    transition = previous.get("stage_transition") if isinstance(previous.get("stage_transition"), dict) else {}
    official_stage = (
        a1.get("official_cycle_stage") or a1.get("cycle_stage")
        or a5.get("cycle_stage")
    )
    raw_stage = a1.get("raw_stage_assessment") or a1.get("cycle_stage")
    item = {
        "generated_at": previous.get("generated_at_bjt") or previous.get("generated_at_utc"),
        "official_stage": normalize_stage(official_stage, default="bull_bear_transition"),
        "raw_stage": normalize_stage(raw_stage, default="bull_bear_transition"),
        "transition_status": transition.get("transition_status")
        or a1.get("transition_status"),
        "confirmation_count": transition.get("confirmation_count")
        or a1.get("confirmation_count"),
        "confirmation_required": transition.get("confirmation_required")
        or a1.get("confirmation_required"),
        "action": a5.get("spot_action"),
    }
    return [{k: v for k, v in item.items() if v not in (None, "", [])}]


def build_a1_cycle_stage_context(context: dict[str, Any]) -> dict[str, Any]:
    """Build the tiny context used only by A1.

    A2/A4/A5 can still inspect the full Layer A context.  A1 only needs slow
    cycle evidence and previous-stage state; giving it the full factor tree has
    caused provider timeouts.
    """
    spot_ctx = context.get("spot_cycle_context") if isinstance(context, dict) else None
    if not isinstance(spot_ctx, dict):
        spot_ctx = context if isinstance(context, dict) else {}
    available = spot_ctx.get("available_factors") if isinstance(spot_ctx.get("available_factors"), dict) else {}
    previous = spot_ctx.get("previous_layer_a_state") if isinstance(spot_ctx.get("previous_layer_a_state"), dict) else {}
    coverage = spot_ctx.get("factor_coverage") if isinstance(spot_ctx.get("factor_coverage"), dict) else {}
    unavailable = spot_ctx.get("unavailable_factors") if isinstance(spot_ctx.get("unavailable_factors"), list) else []

    ps = available.get("price_structure") if isinstance(available.get("price_structure"), dict) else {}
    ov = available.get("onchain_valuation") if isinstance(available.get("onchain_valuation"), dict) else {}
    hb = available.get("holder_behavior") if isinstance(available.get("holder_behavior"), dict) else {}
    ohb = available.get("onchain_holder_behavior") if isinstance(available.get("onchain_holder_behavior"), dict) else {}
    flows = available.get("exchange_and_flows") if isinstance(available.get("exchange_and_flows"), dict) else {}
    macro = available.get("macro") if isinstance(available.get("macro"), dict) else {}
    liquidity = available.get("macro_liquidity") if isinstance(available.get("macro_liquidity"), dict) else {}
    inflation = available.get("macro_inflation_rates") if isinstance(available.get("macro_inflation_rates"), dict) else {}

    return {
        "stage_model": {
            "allowed_stages": list(OFFICIAL_CYCLE_STAGES),
            "previous_official_stage": previous_official_stage(previous),
            "transition_rules_summary": (
                "相邻阶段需连续2次确认;跨2级以上需连续3次确认;数据质量异常时只 pending。"
            ),
        },
        "cycle_evidence_summary": {
            "price_position": {
                "btc_price": _compact_factor(ps.get("current_close")),
                "ath_drawdown_pct": _compact_factor(ps.get("ath_drawdown_pct")),
                "ma_200d": _compact_factor(ps.get("ma_200d")),
                "ma_200w": _compact_factor(ps.get("ma_200w")),
                "ma_200w_deviation_pct": _compact_factor(ps.get("ma_200w_deviation_pct")),
                "weekly_structure": ps.get("weekly_structure") if isinstance(ps.get("weekly_structure"), dict) else {},
                "monthly_ohlc_structure": _compact_factor(ps.get("monthly_ohlc_structure")),
                "major_support_resistance_zones": _compact_factor(ps.get("major_support_resistance_zones")),
                "realized_price": _compact_factor(ov.get("realized_price")),
                "sth_realized_price": _compact_factor(ov.get("sth_realized_price")),
                "lth_realized_price": _compact_factor(ov.get("lth_realized_price")),
            },
            "valuation": {
                "mvrv_z_score": _compact_factor(ov.get("mvrv_z_score")),
                "mvrv": _compact_factor(ov.get("mvrv")),
                "nupl": _compact_factor(ov.get("nupl")),
                "rhodl_ratio": _compact_factor(ov.get("rhodl_ratio")),
                "reserve_risk": _compact_factor(ov.get("reserve_risk")),
                "puell_multiple": _compact_factor(ov.get("puell_multiple")),
                "hash_rate": _compact_factor(ov.get("hash_rate")),
                "percent_supply_in_profit": _compact_factor(ov.get("percent_supply_in_profit")),
            },
            "holder_behavior": {
                "sopr": _compact_factor(hb.get("sopr")),
                "lth_sopr": _compact_factor(ohb.get("lth_sopr")),
                "sth_sopr": _compact_factor(ohb.get("sth_sopr")),
                "lth_supply": _compact_factor(hb.get("lth_supply")),
                "sth_supply": _compact_factor(hb.get("sth_supply")),
                "lth_supply_90d_pct_change": _compact_factor(hb.get("lth_supply_90d_pct_change")),
                "sth_supply_90d_pct_change": _compact_factor(hb.get("sth_supply_90d_pct_change")),
                "lth_net_position_change": _compact_factor(ohb.get("lth_net_position_change")),
                "percent_supply_in_profit": _compact_factor(ohb.get("percent_supply_in_profit")),
                "percent_supply_in_loss": _compact_factor(ohb.get("percent_supply_in_loss")),
                "hodl_waves_1y_plus_aggregate": _compact_factor(hb.get("hodl_waves_1y_plus_aggregate")),
                "cdd": _compact_factor(hb.get("cdd")),
            },
            "flows": {
                "exchange_balance": _compact_factor(ohb.get("exchange_balance") or flows.get("exchange_balance")),
                "exchange_net_position_change": _compact_factor(ohb.get("exchange_net_position_change")),
                "exchange_net_flow_30d_sum": _compact_factor(flows.get("exchange_net_flow_30d_sum")),
                "etf_flow_7d_sum_usd": _compact_factor(flows.get("etf_flow_7d_sum_usd")),
                "etf_flow_30d_sum_usd": _compact_factor(flows.get("etf_flow_30d_sum_usd")),
            },
            "macro": {
                "real_yield": _compact_factor(inflation.get("real_yield") or liquidity.get("real_yield")),
                "fed_funds_rate": _compact_factor(liquidity.get("fed_funds_rate")),
                "us2y": _compact_factor(liquidity.get("us2y") or macro.get("us2y")),
                "dxy": _compact_factor(macro.get("dxy")),
                "vix": _compact_factor(macro.get("vix")),
                "nasdaq": _compact_factor(macro.get("nasdaq")),
                "m2": _compact_factor(liquidity.get("m2")),
                "fed_balance_sheet": _compact_factor(liquidity.get("fed_balance_sheet")),
                "cpi": _compact_factor(inflation.get("cpi")),
                "core_cpi": _compact_factor(inflation.get("core_cpi")),
            },
            "data_quality": {
                "confidence_cap": coverage.get("confidence_cap"),
                "confidence_cap_reason": coverage.get("confidence_cap_reason"),
                "critical_unavailable_count": coverage.get("critical_unavailable_count"),
                "stale_factor_count": coverage.get("stale_factor_count"),
                "missing_integrated_factor_count": coverage.get("missing_integrated_factor_count"),
                "coverage_ratio": coverage.get("coverage_ratio"),
                "coverage_notes": (coverage.get("coverage_notes") or [])[:6],
                "data_quality_notes": (spot_ctx.get("data_quality_notes") or [])[:6],
                "unavailable_factors": [
                    {
                        "factor": item.get("factor"),
                        "project_status": item.get("project_status"),
                    }
                    for item in unavailable[:12]
                    if isinstance(item, dict)
                ],
            },
        },
        "recent_stage_history": _compact_stage_history(previous),
        "instructions": {
            "do_not_output_trade_execution": True,
            "do_not_use_short_term_derivatives_as_stage_driver": True,
            "do_not_repeat_all_metrics": True,
        },
    }


def _compact_packet_metric(v: Any) -> Any:
    if not isinstance(v, dict):
        return v
    out = _compact_factor(v)
    if v.get("value_unit"):
        out["value_unit"] = v.get("value_unit")
    for key in (
        "monthly_trend", "price_location", "nearest_major_support",
        "nearest_major_resistance", "support_distance_pct",
        "resistance_distance_pct", "source_timeframe", "bars_available",
        "buckets_used",
    ):
        if v.get(key) is not None:
            out[key] = v.get(key)
    return out


def _packet_status(metrics: dict[str, Any], data_quality: dict[str, Any] | None = None) -> str:
    statuses: list[str] = []
    for value in metrics.values():
        if isinstance(value, dict) and "status" in value:
            statuses.append(str(value.get("status") or "missing"))
        elif value not in (None, "", {}, []):
            statuses.append("available")
    if not statuses:
        return "unavailable"
    if any(s == "available" for s in statuses) and any(s in {"missing", "stale", "unavailable"} for s in statuses):
        return "partial"
    if all(s == "available" for s in statuses):
        cap = str((data_quality or {}).get("confidence_cap") or "high")
        return "partial" if cap == "low" else "available"
    if any(s == "stale" for s in statuses):
        return "partial"
    return "unavailable"


def _packet_summary(packet_id: str, metrics: dict[str, Any]) -> str:
    def val(name: str) -> Any:
        item = metrics.get(name)
        return item.get("value") if isinstance(item, dict) else item

    if packet_id == "price_structure_packet":
        price = val("btc_price")
        drawdown = val("ath_drawdown_pct")
        deviation = val("ma_200w_deviation_pct")
        monthly = val("monthly_ohlc_structure")
        if price is not None:
            return (
                f"BTC 当前约 {price}，ATH 回撤 {drawdown if drawdown is not None else '-'}%，"
                f"200WMA 乖离 {deviation if deviation is not None else '-'}%，"
                f"月线结构 {monthly or '暂无'}。"
            )
        return "价格周期结构数据不足，需等待 K 线和长期结构恢复。"
    if packet_id == "onchain_packet":
        mvrv = val("mvrv")
        nupl = val("nupl")
        rhodl = val("rhodl_ratio")
        return f"链上估值摘要：MVRV {mvrv if mvrv is not None else '-'}，NUPL {nupl if nupl is not None else '-'}，RHODL {rhodl if rhodl is not None else '-'}。"
    if packet_id == "macro_flow_packet":
        real_yield = val("real_yield")
        fed = val("fed_funds_rate")
        m2 = val("m2")
        return f"宏观流动性摘要：实际利率 {real_yield if real_yield is not None else '-'}，联邦基金利率 {fed if fed is not None else '-'}，M2 {m2 if m2 is not None else '-'}。"
    return "数据包摘要不足。"


def _packet(
    packet_id: str,
    title: str,
    metrics: dict[str, Any],
    *,
    data_quality: dict[str, Any] | None = None,
    notes: list[Any] | None = None,
) -> dict[str, Any]:
    compact_metrics = {
        key: _compact_packet_metric(value)
        for key, value in metrics.items()
        if value not in (None, "", [])
    }
    out: dict[str, Any] = {
        "packet_id": packet_id,
        "title": title,
        "status": _packet_status(compact_metrics, data_quality=data_quality),
        "summary": _packet_summary(packet_id, compact_metrics),
        "key_metrics": compact_metrics,
    }
    trimmed_notes = [n for n in (notes or []) if n][:5]
    if trimmed_notes:
        out["notes"] = trimmed_notes
    return out


def build_layer_a_cycle_adjudicator_context(context: dict[str, Any]) -> dict[str, Any]:
    """Build the official Layer A single-adjudicator input.

    Three packets are deterministic summaries:
      - price_structure_packet:价格结构(K 线/MA/200WMA 乖离/月线/支撑阻力)
      - onchain_packet:链上估值 + 持有者行为 + 算力/SOPR + 已实现价格 + 交易所流
      - macro_flow_packet:ETF/交易所净流 + 宏观流动性与利率

    The packets deliberately exclude Layer B L1-L5, thesis, virtual account,
    holdings, orders, raw factor cards, full debug JSON, and Layer B derivatives
    (funding / OI / LSR / liquidation).  Data quality is exposed as a top-level
    ``data_quality`` block (not mixed into any packet).

    The AI gets one compact decision brief, then the deterministic state machine
    and validator decide the official stage and final guardrails.
    """
    spot_ctx = context.get("spot_cycle_context") if isinstance(context, dict) else None
    if not isinstance(spot_ctx, dict):
        spot_ctx = context if isinstance(context, dict) else {}
    a1_ctx = build_a1_cycle_stage_context({"spot_cycle_context": spot_ctx})
    evidence = a1_ctx.get("cycle_evidence_summary") or {}
    price = evidence.get("price_position") if isinstance(evidence.get("price_position"), dict) else {}
    valuation = evidence.get("valuation") if isinstance(evidence.get("valuation"), dict) else {}
    holder = evidence.get("holder_behavior") if isinstance(evidence.get("holder_behavior"), dict) else {}
    flows = evidence.get("flows") if isinstance(evidence.get("flows"), dict) else {}
    macro = evidence.get("macro") if isinstance(evidence.get("macro"), dict) else {}
    data_quality = evidence.get("data_quality") if isinstance(evidence.get("data_quality"), dict) else {}

    price_structure_packet = _packet(
        "price_structure_packet",
        "价格结构数据包",
        {
            "btc_price": price.get("btc_price"),
            "ath_drawdown_pct": price.get("ath_drawdown_pct"),
            "ma_200d": price.get("ma_200d"),
            "ma_200w": price.get("ma_200w"),
            "ma_200w_deviation_pct": price.get("ma_200w_deviation_pct"),
            "weekly_structure": price.get("weekly_structure"),
            "monthly_ohlc_structure": price.get("monthly_ohlc_structure"),
            "major_support_resistance_zones": price.get("major_support_resistance_zones"),
        },
        data_quality=data_quality,
    )
    onchain_packet = _packet(
        "onchain_packet",
        "链上估值与持有者数据包",
        {
            **valuation,
            "realized_price": price.get("realized_price"),
            "sth_realized_price": price.get("sth_realized_price"),
            "lth_realized_price": price.get("lth_realized_price"),
            "sopr": holder.get("sopr"),
            "lth_sopr": holder.get("lth_sopr"),
            "sth_sopr": holder.get("sth_sopr"),
            "lth_supply": holder.get("lth_supply"),
            "sth_supply": holder.get("sth_supply"),
            "lth_supply_90d_pct_change": holder.get("lth_supply_90d_pct_change"),
            "sth_supply_90d_pct_change": holder.get("sth_supply_90d_pct_change"),
            "lth_net_position_change": holder.get("lth_net_position_change"),
            "percent_supply_in_loss": holder.get("percent_supply_in_loss"),
            "hodl_waves_1y_plus_aggregate": holder.get("hodl_waves_1y_plus_aggregate"),
            "cdd": holder.get("cdd"),
            "exchange_balance": flows.get("exchange_balance"),
            "exchange_net_position_change": flows.get("exchange_net_position_change"),
        },
        data_quality=data_quality,
    )
    macro_flow_packet = _packet(
        "macro_flow_packet",
        "资金流与宏观背景数据包",
        {
            "etf_flow_7d_sum_usd": flows.get("etf_flow_7d_sum_usd"),
            "etf_flow_30d_sum_usd": flows.get("etf_flow_30d_sum_usd"),
            "exchange_net_flow_30d_sum": flows.get("exchange_net_flow_30d_sum"),
            **macro,
        },
        data_quality=data_quality,
    )
    packets = {
        "price_structure_packet": price_structure_packet,
        "onchain_packet": onchain_packet,
        "macro_flow_packet": macro_flow_packet,
    }
    return {
        "schema_version": "layer_a_single_cycle_adjudicator_v2_three_packets",
        "stage_model": a1_ctx.get("stage_model") or {},
        "previous_official_stage": (a1_ctx.get("stage_model") or {}).get(
            "previous_official_stage"
        ),
        "recent_stage_history": a1_ctx.get("recent_stage_history") or [],
        "allowed_stage_transitions": {
            "allowed_stages": list(OFFICIAL_CYCLE_STAGES),
            "rules": [
                "只能相邻阶段自然迁移;跨级变化必须 pending 并连续确认。",
                "数据质量差、关键源异常或风险高时不能确认升级。",
                "AI 的阶段建议必须经过 deterministic state machine 才能成为 official_stage。",
            ],
        },
        "data_packets": packets,
        "data_quality": {
            "confidence_cap": data_quality.get("confidence_cap"),
            "confidence_cap_reason": data_quality.get("confidence_cap_reason"),
            "critical_unavailable_count": data_quality.get("critical_unavailable_count"),
            "stale_factor_count": data_quality.get("stale_factor_count"),
            "missing_integrated_factor_count": data_quality.get(
                "missing_integrated_factor_count"
            ),
            "coverage_ratio": data_quality.get("coverage_ratio"),
            "unavailable_factors": data_quality.get("unavailable_factors") or [],
            "coverage_notes": (data_quality.get("coverage_notes") or [])[:6],
            "data_quality_notes": (data_quality.get("data_quality_notes") or [])[:6],
        },
        "layer_a_boundaries": spot_ctx.get("layer_a_boundaries") or {
            "spot_only": True,
            "no_short": True,
            "no_leverage": True,
            "no_thesis": True,
            "no_virtual_account": True,
            "no_layer_b_grade": True,
        },
        "instructions": {
            "one_ai_call_only": True,
            "do_not_output_layer_b_trade_plan": True,
            "do_not_create_thesis": True,
            "do_not_use_virtual_account": True,
            "do_not_repeat_all_metrics": True,
            "use_official_stage_recommendation_as_recommendation_only": True,
        },
    }


def _utc_iso_to_bjt_pretty(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        bjt = dt.astimezone(timezone(timedelta(hours=8)))
        return bjt.strftime("%Y-%m-%d %H:%M:%S (BJT)")
    except Exception:
        return value


def _factor(
    name: str,
    value: Any,
    *,
    timestamp: Optional[str] = None,
    source: Optional[str] = None,
    stale_map: Optional[dict[str, bool]] = None,
    hours_map: Optional[dict[str, float]] = None,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    source_key = source or _FACTOR_SOURCE.get(name)
    status = "available" if value is not None else "missing"
    is_stale = bool(stale_map.get(source_key)) if source_key and stale_map else False
    is_monthly_fred = source_key == "fred_macro" and name in _MONTHLY_FRED_FACTORS
    if status == "available" and is_monthly_fred:
        is_stale = False
    if status == "available" and is_stale:
        status = "stale"
    out = {
        "actual_value": _round(value),
        "status": status,
        "source": source_key,
        "freshness": {
            "is_stale": is_stale,
            "hours_since_last_success": (
                hours_map.get(source_key) if source_key and hours_map else None
            ),
        },
    }
    if is_monthly_fred:
        out["freshness"]["frequency"] = "monthly"
        out["freshness"]["monthly_latest_ok"] = status == "available"
    if timestamp:
        out["as_of"] = timestamp
    if extra:
        out.update(extra)
    return out


class SpotCycleContextBuilder:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        lookback_days: int = 730,
        events_window_hours: int = 168,
    ) -> None:
        self.conn = conn
        self.lookback_days = lookback_days
        self.events_window_hours = events_window_hours

    def build_spot_cycle_context(
        self,
        *,
        existing_context: Optional[dict[str, Any]] = None,
        now_utc: Optional[str] = None,
    ) -> dict[str, Any]:
        stale_map = dict((existing_context or {}).get("_source_stale_map") or {})
        hours_map = dict((existing_context or {}).get("_source_hours_map") or {})

        shared = (existing_context or {}).get("_shared") or {}
        klines_1d = shared.get("klines_1d")
        if klines_1d is None:
            klines_1d = BTCKlinesDAO.get_recent_as_df(self.conn, "1d", limit=self.lookback_days)
        klines_1w = BTCKlinesDAO.get_recent_as_df(self.conn, "1w", limit=260)

        derivatives = shared.get("derivatives")
        if derivatives is None:
            derivatives = DerivativesDAO.get_all_metrics(self.conn, lookback_days=self.lookback_days)
        onchain = shared.get("onchain")
        if onchain is None:
            onchain = OnchainDAO.get_all_metrics(self.conn, lookback_days=self.lookback_days)
        macro = shared.get("macro")
        if macro is None:
            macro = MacroDAO.get_all_metrics(self.conn, lookback_days=self.lookback_days)

        events = EventsCalendarDAO.get_upcoming_within_hours(
            self.conn, hours=self.events_window_hours, now_utc=now_utc,
        )

        ema1d = compute_emas_1d(klines_1d)
        price = compute_price_features(klines_1d)
        lth_sth = compute_lth_sth_changes(onchain)
        ex_flow = compute_exchange_flow_features(onchain)
        funding = compute_funding_features(derivatives)
        oi = compute_oi_features(derivatives)
        macro_features = compute_macro_features({**macro, **derivatives})
        btc_corr = compute_btc_macro_corr_60d(klines_1d, macro, key="nasdaq")
        tf_alignment = compute_tf_alignment(pd.DataFrame(), klines_1d, klines_1w)

        close = None
        if klines_1d is not None and not klines_1d.empty and "close" in klines_1d.columns:
            close = klines_1d["close"].astype(float)
        current_close = price.get("current_close")
        ath_drawdown = None
        ma_200d = ema1d.get("ema_200_current")
        ma_200w = None
        ma_200w_deviation_pct = None
        weekly_structure = {}
        if close is not None and len(close) > 0:
            ath = float(close.max())
            if ath > 0 and current_close is not None:
                ath_drawdown = (float(current_close) / ath - 1.0) * 100.0
        if klines_1w is not None and not klines_1w.empty and "close" in klines_1w.columns:
            wclose = klines_1w["close"].astype(float)
            if len(wclose) >= 200:
                ma_200w = float(wclose.rolling(200).mean().iloc[-1])
            weekly_structure = {
                "close_13w_change_pct": _pct_change(wclose, 13),
                "close_52w_change_pct": _pct_change(wclose, 52),
                "bars_available": int(len(wclose)),
            }
        if (
            ma_200w is not None and ma_200w > 0
            and current_close is not None
        ):
            ma_200w_deviation_pct = (float(current_close) / ma_200w - 1.0) * 100.0
        latest_kline_inserted = BTCKlinesDAO.get_latest_inserted_at_by_timeframe(self.conn)
        daily_kline_meta = {
            "fetched_at_utc": latest_kline_inserted.get("1d"),
            "fetched_at_bjt": _utc_iso_to_bjt_pretty(latest_kline_inserted.get("1d")),
        } if latest_kline_inserted.get("1d") else {}
        weekly_kline_meta = {
            "fetched_at_utc": latest_kline_inserted.get("1w"),
            "fetched_at_bjt": _utc_iso_to_bjt_pretty(latest_kline_inserted.get("1w")),
        } if latest_kline_inserted.get("1w") else {}
        monthly_structure_value, monthly_structure_ts, monthly_structure_extra = (
            _build_monthly_ohlc_structure(klines_1d)
        )
        sr_value, sr_ts, sr_extra = _build_major_support_resistance(
            klines_1w, klines_1d, current_close,
        )

        def metric_meta(dao: type[OnchainDAO] | type[MacroDAO], name: str) -> dict[str, Any]:
            row = dao.get_latest(self.conn, name)
            if not row:
                return {}
            fetched_at_utc = row.get("inserted_at_utc")
            captured_at_utc = row.get("captured_at_utc") or row.get("timestamp")
            out: dict[str, Any] = {}
            if fetched_at_utc:
                out["fetched_at_utc"] = fetched_at_utc
                out["fetched_at_bjt"] = _utc_iso_to_bjt_pretty(fetched_at_utc)
            if captured_at_utc:
                out["captured_at_utc"] = captured_at_utc
            return out

        def metric(name: str) -> dict[str, Any]:
            value, ts = _series_latest(onchain.get(name) if isinstance(onchain, dict) else None)
            return _factor(
                name, value, timestamp=ts, stale_map=stale_map, hours_map=hours_map,
                extra=metric_meta(OnchainDAO, name),
            )

        def dmetric(name: str) -> dict[str, Any]:
            value, ts = _series_latest(derivatives.get(name) if isinstance(derivatives, dict) else None)
            return _factor(name, value, timestamp=ts, stale_map=stale_map, hours_map=hours_map)

        def mmetric(name: str) -> dict[str, Any]:
            keys = _MACRO_METRIC_ALIASES.get(name, (name,))
            matched_key = next(
                (k for k in keys if isinstance(macro, dict) and k in macro),
                name,
            )
            value, ts = _series_latest(
                macro.get(matched_key) if isinstance(macro, dict) else None
            )
            return _factor(
                name, value, timestamp=ts, stale_map=stale_map, hours_map=hours_map,
                extra=metric_meta(MacroDAO, matched_key),
            )

        profit_value, profit_ts = _series_latest(
            onchain.get("percent_supply_in_profit") if isinstance(onchain, dict) else None
        )
        percent_supply_in_loss = (
            1.0 - profit_value
            if isinstance(profit_value, (int, float)) and 0 <= profit_value <= 1
            else None
        )
        exchange_balance_delta, exchange_balance_delta_ts = _series_latest_delta(
            onchain.get("exchange_balance") if isinstance(onchain, dict) else None
        )
        hodl_long_buckets = (
            "hodl_waves_1y_2y", "hodl_waves_2y_3y", "hodl_waves_3y_5y",
            "hodl_waves_5y_7y", "hodl_waves_7y_10y", "hodl_waves_more_10y",
        )
        hodl_long_value = 0.0
        hodl_long_have_any = False
        hodl_long_series = []
        hodl_latest_meta: dict[str, Any] = {}
        for bucket in hodl_long_buckets:
            series = onchain.get(bucket) if isinstance(onchain, dict) else None
            value, _ = _series_latest(series)
            if value is not None:
                hodl_long_value += float(value)
                hodl_long_have_any = True
                hodl_long_series.append(series)
                meta = metric_meta(OnchainDAO, bucket)
                if meta.get("fetched_at_utc") and (
                    not hodl_latest_meta.get("fetched_at_utc")
                    or meta["fetched_at_utc"] > hodl_latest_meta["fetched_at_utc"]
                ):
                    hodl_latest_meta = meta
        hodl_long_ts = _latest_series_timestamp(*hodl_long_series)
        hodl_long_pct = (hodl_long_value * 100.0) if hodl_long_have_any else None

        available = {
            "price_structure": {
                "current_close": _factor("current_close", current_close, source="coinglass_derivatives", stale_map=stale_map, hours_map=hours_map),
                "ath_drawdown_pct": _factor("ath_drawdown", ath_drawdown, source="coinglass_derivatives", stale_map=stale_map, hours_map=hours_map),
                "ma_200d": _factor("ma_200d", ma_200d, source="coinglass_derivatives", stale_map=stale_map, hours_map=hours_map),
                "ma_200w": _factor("ma_200w", ma_200w, source="coinglass_derivatives", stale_map=stale_map, hours_map=hours_map),
                "ma_200w_deviation_pct": _factor(
                    "ma_200w_deviation_pct", ma_200w_deviation_pct,
                    source="coinglass_derivatives_derived",
                    stale_map=stale_map, hours_map=hours_map,
                    extra={"value_unit": "%"},
                ),
                "weekly_structure": weekly_structure,
                "monthly_ohlc_structure": _factor(
                    "monthly_ohlc_structure",
                    monthly_structure_value,
                    timestamp=monthly_structure_ts,
                    source="coinglass_derivatives_derived",
                    stale_map=stale_map,
                    hours_map=hours_map,
                    extra={**monthly_structure_extra, **daily_kline_meta},
                ),
                "major_support_resistance_zones": _factor(
                    "major_support_resistance_zones",
                    sr_value,
                    timestamp=sr_ts,
                    source="coinglass_derivatives_derived",
                    stale_map=stale_map,
                    hours_map=hours_map,
                    extra={**sr_extra, **(weekly_kline_meta or daily_kline_meta)},
                ),
                "tf_alignment": tf_alignment,
            },
            "onchain_valuation": {
                "mvrv_z_score": metric("mvrv_z_score"),
                "mvrv": metric("mvrv"),
                "nupl": metric("nupl"),
                "realized_price": metric("realized_price"),
                "lth_realized_price": metric("lth_realized_price"),
                "sth_realized_price": metric("sth_realized_price"),
                "lth_mvrv": metric("lth_mvrv"),
                "sth_mvrv": metric("sth_mvrv"),
                "percent_supply_in_profit": metric("percent_supply_in_profit"),
                "rhodl_ratio": metric("rhodl_ratio"),
                "reserve_risk": metric("reserve_risk"),
                "puell_multiple": metric("puell_multiple"),
                "hash_rate": metric("hash_rate"),
            },
            "holder_behavior": {
                "lth_supply": metric("lth_supply"),
                "sth_supply": metric("sth_supply"),
                "lth_supply_90d_pct_change": _factor("lth_supply", lth_sth.get("lth_supply_90d_pct_change"), stale_map=stale_map, hours_map=hours_map),
                "sth_supply_90d_pct_change": _factor("sth_supply", lth_sth.get("sth_supply_90d_pct_change"), stale_map=stale_map, hours_map=hours_map),
                "sopr_adjusted": metric("sopr_adjusted"),
                "sopr": metric("sopr_adjusted"),
                "hodl_waves": metric("hodl_waves"),
                "hodl_waves_1y_plus_aggregate": _factor(
                    "hodl_waves_1y_plus_aggregate",
                    hodl_long_pct,
                    timestamp=hodl_long_ts,
                    source="glassnode_onchain_derived",
                    stale_map=stale_map,
                    hours_map=hours_map,
                    extra={
                        **hodl_latest_meta,
                        "value_unit": "%",
                        "buckets": list(hodl_long_buckets),
                        "buckets_used": int(len(hodl_long_series)),
                    },
                ),
                "cdd": metric("cdd"),
                "ssr": metric("ssr"),
            },
            "onchain_holder_behavior": {
                "lth_sopr": metric("lth_sopr"),
                "sth_sopr": metric("sth_sopr"),
                "lth_net_position_change": metric("lth_net_position_change"),
                "percent_supply_in_profit": metric("percent_supply_in_profit"),
                "percent_supply_in_loss": _factor(
                    "percent_supply_in_loss",
                    percent_supply_in_loss,
                    timestamp=profit_ts,
                    source="glassnode_onchain_derived",
                    stale_map=stale_map,
                    hours_map=hours_map,
                    extra=metric_meta(OnchainDAO, "percent_supply_in_profit"),
                ),
                "exchange_balance": metric("exchange_balance"),
                "exchange_net_position_change": _factor(
                    "exchange_net_position_change",
                    exchange_balance_delta,
                    timestamp=exchange_balance_delta_ts,
                    source="glassnode_onchain_derived",
                    stale_map=stale_map,
                    hours_map=hours_map,
                    extra=metric_meta(OnchainDAO, "exchange_balance"),
                ),
            },
            "exchange_and_flows": {
                "exchange_net_flow": metric("exchange_net_flow"),
                "exchange_net_flow_30d_sum": _factor("exchange_net_flow", ex_flow.get("exchange_net_flow_30d_sum"), stale_map=stale_map, hours_map=hours_map),
                "exchange_balance": metric("exchange_balance"),
                "etf_flow": dmetric("etf_flow"),
                "etf_flow_7d_sum_usd": _factor("etf_flow", macro_features.get("etf_flow_7d_sum_usd"), source="coinglass_derivatives", stale_map=stale_map, hours_map=hours_map),
                "etf_flow_30d_sum_usd": _factor("etf_flow", macro_features.get("etf_flow_30d_sum_usd"), source="coinglass_derivatives", stale_map=stale_map, hours_map=hours_map),
            },
            "macro": {
                "dxy": mmetric("dxy"),
                "us10y": mmetric("dgs10") if "dgs10" in macro else mmetric("us10y"),
                "us2y": mmetric("us2y"),
                "real_yield": mmetric("real_yield"),
                "fed_funds_rate": mmetric("fed_funds_rate"),
                "cpi": mmetric("cpi"),
                "core_cpi": mmetric("core_cpi"),
                "m2": mmetric("m2"),
                "fed_balance_sheet": mmetric("fed_balance_sheet"),
                "vix": mmetric("vix"),
                "nasdaq": mmetric("nasdaq"),
                "btc_nasdaq_corr_60d": _factor("nasdaq", btc_corr, source="fred_macro", stale_map=stale_map, hours_map=hours_map),
            },
            "macro_liquidity": {
                "us2y": mmetric("us2y"),
                "real_yield": mmetric("real_yield"),
                "fed_funds_rate": mmetric("fed_funds_rate"),
                "m2": mmetric("m2"),
                "fed_balance_sheet": mmetric("fed_balance_sheet"),
            },
            "macro_inflation_rates": {
                "real_yield": mmetric("real_yield"),
                "cpi": mmetric("cpi"),
                "core_cpi": mmetric("core_cpi"),
            },
            "market_context": {
                "btc_dominance": dmetric("btc_dominance"),
                "funding_rate": dmetric("funding_rate"),
                "funding_rate_z_score_90d": _factor("funding_rate", funding.get("funding_rate_z_score_90d"), source="coinglass_derivatives", stale_map=stale_map, hours_map=hours_map),
                "open_interest": dmetric("open_interest"),
                "open_interest_z_score_90d": _factor("open_interest", oi.get("open_interest_z_score_90d"), source="coinglass_derivatives", stale_map=stale_map, hours_map=hours_map),
                "long_short_ratio": dmetric("long_short_ratio"),
                "liquidation_total": dmetric("liquidation_total"),
            },
            "event_risk": {
                "events_window_hours": self.events_window_hours,
                "events": events,
                "events_count": len(events),
            },
        }

        unavailable = [
            {"factor": name, "project_status": status}
            for name, status in sorted(_UNAVAILABLE_MODEL_FACTORS.items())
        ]
        missing_notes = self._build_data_quality_notes(available, unavailable)
        factor_coverage = self._build_factor_coverage(available, unavailable)
        return {
            "schema_version": "layer_a_spot_cycle_context_v1",
            "built_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "layer_a_boundaries": {
                "spot_only": True,
                "no_short": True,
                "no_leverage": True,
                "no_thesis": True,
                "no_virtual_account": True,
                "no_layer_b_grade": True,
            },
            "available_factors": available,
            "factor_role_classification": self._build_factor_role_classification(
                available, unavailable,
            ),
            "unavailable_factors": unavailable,
            "factor_coverage": factor_coverage,
            "data_quality_notes": missing_notes,
            "series_samples": {
                "mvrv_z_score_tail": _tail(onchain.get("mvrv_z_score") if isinstance(onchain, dict) else None, 12),
                "nupl_tail": _tail(onchain.get("nupl") if isinstance(onchain, dict) else None, 12),
                "etf_flow_tail": _tail(derivatives.get("etf_flow") if isinstance(derivatives, dict) else None, 12),
                "btc_close_1d_tail": _tail(close, 12),
            },
        }

    @staticmethod
    def _build_factor_role_classification(
        available: dict[str, Any],
        unavailable: list[dict[str, str]],
    ) -> dict[str, list[dict[str, str]]]:
        rows: dict[str, list[dict[str, str]]] = {
            "a1_core": [],
            "a2_a4_background": [],
            "layer_b_context": [],
            "not_suitable_or_unavailable": [],
        }

        def add(role: str, name: str, group: str, status: str, reason: str) -> None:
            rows[role].append({
                "factor_name": name,
                "current_source": _FACTOR_SOURCE.get(name, "derived"),
                "current_status": status,
                "currently_enters": group,
                "recommended_class": {
                    "a1_core": "A",
                    "a2_a4_background": "B",
                    "layer_b_context": "C",
                    "not_suitable_or_unavailable": "D",
                }[role],
                "keep": "yes" if role != "not_suitable_or_unavailable" else "no_or_defer",
                "reason": reason,
            })

        def walk(group: str, obj: Any) -> None:
            if isinstance(obj, dict) and "status" in obj and "actual_value" in obj:
                name = str(obj.get("factor") or group.rsplit(".", 1)[-1])
                status = str(obj.get("status") or "missing")
                if name in _A1_CORE_FACTORS:
                    add("a1_core", name, group, status, "低频、长周期、估值或持有人结构核心因子")
                elif name in _A2_A4_BACKGROUND_FACTORS:
                    add("a2_a4_background", name, group, status, "背景/风险因子，可影响置信度，不单独决定阶段")
                elif name in _LAYER_B_CONTEXT_FACTORS:
                    add("layer_b_context", name, group, status, "短线或衍生品因子，更适合 Layer B 波段判断")
                else:
                    add("not_suitable_or_unavailable", name, group, status, "重复、噪音较高或暂不作为 A1 主因子")
                return
            if isinstance(obj, dict):
                for k, v in obj.items():
                    walk(f"{group}.{k}" if group else k, v)

        walk("", available)
        for item in unavailable:
            name = item.get("factor") or "unknown"
            add(
                "not_suitable_or_unavailable",
                name,
                "unavailable_factors",
                item.get("project_status") or "unavailable",
                "模型预留但本项目未稳定接入，不能伪装成 A1 可用数据",
            )
        return rows

    @staticmethod
    def _build_data_quality_notes(
        available: dict[str, Any], unavailable: list[dict[str, str]],
    ) -> list[str]:
        notes: list[str] = []
        missing: list[str] = []
        stale: list[str] = []

        def walk(prefix: str, obj: Any) -> None:
            if isinstance(obj, dict) and "status" in obj and "actual_value" in obj:
                if obj.get("status") == "missing":
                    missing.append(prefix)
                if obj.get("status") == "stale":
                    stale.append(prefix)
                return
            if isinstance(obj, dict):
                for k, v in obj.items():
                    walk(f"{prefix}.{k}" if prefix else k, v)

        walk("", available)
        if missing:
            notes.append("缺失已接入因子: " + ", ".join(missing[:12]))
        if stale:
            notes.append("存在过期因子: " + ", ".join(stale[:12]))
        if unavailable:
            notes.append(
                "模型预留但本项目未稳定接入的候选因子: "
                + ", ".join(x["factor"] for x in unavailable[:12])
            )
        return notes

    @staticmethod
    def _build_factor_coverage(
        available: dict[str, Any], unavailable: list[dict[str, str]],
    ) -> dict[str, Any]:
        counts = {"available": 0, "missing": 0, "stale": 0}

        def walk(obj: Any) -> None:
            if isinstance(obj, dict) and "status" in obj and "actual_value" in obj:
                status = str(obj.get("status") or "missing")
                if status in counts:
                    counts[status] += 1
                return
            if isinstance(obj, dict):
                for v in obj.values():
                    walk(v)

        walk(available)
        integrated_total = sum(counts.values())
        critical_missing = [
            item["factor"]
            for item in unavailable
            if item.get("factor") in _CRITICAL_MODEL_FACTORS
        ]
        critical_count = len(critical_missing)
        coverage_ratio = (
            counts["available"] / integrated_total if integrated_total else 0.0
        )
        if coverage_ratio < 0.5:
            confidence_cap = "low"
            cap_reason = "Layer A 已接入因子可用率低于 50%"
        elif counts["stale"] >= 5:
            confidence_cap = "medium"
            cap_reason = "5 个以上已接入 Layer A 因子过期"
        elif counts["missing"] >= 5:
            confidence_cap = "medium"
            cap_reason = "5 个以上已接入 Layer A 因子当前缺值"
        elif critical_count >= 10:
            confidence_cap = "medium"
            cap_reason = "10 个以上关键 Layer A 因子未稳定接入"
        elif critical_count >= 5:
            confidence_cap = "medium"
            cap_reason = "5 个以上关键 Layer A 因子未稳定接入"
        else:
            confidence_cap = "high"
            cap_reason = ""
        notes: list[str] = []
        if counts["missing"]:
            notes.append(f"{counts['missing']} 个已接入因子当前缺值")
        if counts["stale"]:
            notes.append(f"{counts['stale']} 个已接入因子当前过期")
        if critical_count:
            notes.append(f"{critical_count} 个关键候选因子未稳定接入")
        return {
            "available_factor_count": counts["available"],
            "missing_integrated_factor_count": counts["missing"],
            "stale_factor_count": counts["stale"],
            "total_integrated_factor_count": integrated_total,
            "coverage_ratio": round(coverage_ratio, 4),
            "total_unavailable_factors": len(unavailable),
            "critical_unavailable_count": critical_count,
            "critical_unavailable_factors": critical_missing,
            "confidence_cap": confidence_cap,
            "confidence_cap_reason": cap_reason,
            "coverage_notes": notes,
        }


def build_spot_cycle_context(
    conn: sqlite3.Connection,
    *,
    existing_context: Optional[dict[str, Any]] = None,
    now_utc: Optional[str] = None,
) -> dict[str, Any]:
    return SpotCycleContextBuilder(conn).build_spot_cycle_context(
        existing_context=existing_context, now_utc=now_utc,
    )
