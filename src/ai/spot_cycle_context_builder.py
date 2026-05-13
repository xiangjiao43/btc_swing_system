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

_CRITICAL_MODEL_FACTORS: set[str] = set()


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
            value, ts = _series_latest(macro.get(name) if isinstance(macro, dict) else None)
            return _factor(
                name, value, timestamp=ts, stale_map=stale_map, hours_map=hours_map,
                extra=metric_meta(MacroDAO, name),
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
