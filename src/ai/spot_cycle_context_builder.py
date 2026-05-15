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
}

_UNAVAILABLE_MODEL_FACTORS = {
    "market_cap_realized_cap": "not_found",
    "liveliness": "config_only",
    "stablecoin_supply_liquidity": "not_found",
    "monthly_structure_1m": "not_found",
    "major_support_resistance": "ai_derived_not_precomputed_for_layer_a",
    "unemployment": "deprecated_candidate",
    "futures_basis_premium": "deprecated_candidate",
    "options_iv_skew": "not_found",
    "liquidation_heatmap_levels": "not_found",
}

_A1_CORE_FACTORS = {
    "current_close", "ath_drawdown_pct", "ma_200d", "ma_200w",
    "realized_price", "sth_realized_price", "lth_realized_price",
    "mvrv_z_score", "mvrv", "nupl", "rhodl_ratio", "reserve_risk",
    "puell_multiple", "lth_sopr", "sth_sopr", "lth_supply",
    "sth_supply", "lth_net_position_change", "percent_supply_in_profit",
    "percent_supply_in_loss", "hodl_waves", "cdd", "exchange_balance",
    "exchange_net_position_change",
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
    "hodl_waves", "cdd", "exchange_balance",
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


def _compact_stage_history(previous: dict[str, Any]) -> list[dict[str, Any]]:
    if not previous:
        return []
    a1 = previous.get("a1_cycle_stage") if isinstance(previous.get("a1_cycle_stage"), dict) else {}
    a5 = previous.get("a5_spot_adjudicator") if isinstance(previous.get("a5_spot_adjudicator"), dict) else {}
    transition = previous.get("stage_transition") if isinstance(previous.get("stage_transition"), dict) else {}
    item = {
        "generated_at": previous.get("generated_at_bjt") or previous.get("generated_at_utc"),
        "official_stage": (
            a1.get("official_cycle_stage") or a1.get("cycle_stage")
            or a5.get("cycle_stage")
        ),
        "raw_stage": a1.get("raw_stage_assessment") or a1.get("cycle_stage"),
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
                "weekly_structure": ps.get("weekly_structure") if isinstance(ps.get("weekly_structure"), dict) else {},
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
                "percent_supply_in_profit": _compact_factor(ov.get("percent_supply_in_profit")),
            },
            "holder_behavior": {
                "lth_sopr": _compact_factor(ohb.get("lth_sopr")),
                "sth_sopr": _compact_factor(ohb.get("sth_sopr")),
                "lth_supply": _compact_factor(hb.get("lth_supply")),
                "sth_supply": _compact_factor(hb.get("sth_supply")),
                "lth_supply_90d_pct_change": _compact_factor(hb.get("lth_supply_90d_pct_change")),
                "sth_supply_90d_pct_change": _compact_factor(hb.get("sth_supply_90d_pct_change")),
                "lth_net_position_change": _compact_factor(ohb.get("lth_net_position_change")),
                "percent_supply_in_profit": _compact_factor(ohb.get("percent_supply_in_profit")),
                "percent_supply_in_loss": _compact_factor(ohb.get("percent_supply_in_loss")),
                "hodl_waves": _compact_factor(hb.get("hodl_waves")),
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

        available = {
            "price_structure": {
                "current_close": _factor("current_close", current_close, source="coinglass_derivatives", stale_map=stale_map, hours_map=hours_map),
                "ath_drawdown_pct": _factor("ath_drawdown", ath_drawdown, source="coinglass_derivatives", stale_map=stale_map, hours_map=hours_map),
                "ma_200d": _factor("ma_200d", ma_200d, source="coinglass_derivatives", stale_map=stale_map, hours_map=hours_map),
                "ma_200w": _factor("ma_200w", ma_200w, source="coinglass_derivatives", stale_map=stale_map, hours_map=hours_map),
                "weekly_structure": weekly_structure,
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
            },
            "holder_behavior": {
                "lth_supply": metric("lth_supply"),
                "sth_supply": metric("sth_supply"),
                "lth_supply_90d_pct_change": _factor("lth_supply", lth_sth.get("lth_supply_90d_pct_change"), stale_map=stale_map, hours_map=hours_map),
                "sth_supply_90d_pct_change": _factor("sth_supply", lth_sth.get("sth_supply_90d_pct_change"), stale_map=stale_map, hours_map=hours_map),
                "sopr_adjusted": metric("sopr_adjusted"),
                "hodl_waves": metric("hodl_waves"),
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
