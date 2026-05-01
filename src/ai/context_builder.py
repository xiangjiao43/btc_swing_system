"""src/ai/context_builder.py — Sprint 1.9-A.2 v1.3 context 构造层。

从 DB 数据(klines / derivatives / onchain / macro / events)构造给 6 个 AI
agent 的 context dict。所有 helper 都是**纯计算函数**(铁律 2:系统精确算,
AI 看)。**不引入任何规则结论标签**(铁律 1)。

11 个类型 A helper(纯客观计算):
  1. compute_emas_1d              — EMA-20/50/200 (1d series + current)
  2. compute_emas_4h              — EMA-20/50 (4h series + current)
  3. compute_adx_14               — ADX-14 series + current + 5d avg
  4. compute_atr_features         — ATR-14 series + current + 180d 分位
  5. detect_swing_points          — Swing 高低点(zigzag,depth=5)
  6. compute_lth_sth_changes      — LTH/STH supply 30d/90d %change + realized price
  7. compute_exchange_flow_features — 交易所净流 30d sum/max/series
  8. compute_funding_features     — funding 现值 + 90d z + 30d max + series
  9. compute_oi_features          — open interest 现值 + 90d z + series
  10. compute_price_features      — current_close + max_drawdown_60d + ema_50_slope_30d
  11. compute_macro_features      — 9 类宏观因子的 current + 30d/90d %change
  12. compute_btc_macro_corr_60d  — BTC vs 任一 macro series 的 60d 相关系数

聚合方法:
  ContextBuilder(conn).build_full_context() → 一次性构造完整 context
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import numpy as np
import pandas as pd

from ..data.storage.dao import (
    BTCKlinesDAO,
    DerivativesDAO,
    EventsCalendarDAO,
    MacroDAO,
    OnchainDAO,
    StrategyStateDAO,
)


logger = logging.getLogger(__name__)


# ============================================================
# 类型 A helpers — 纯客观计算
# ============================================================

def compute_emas_1d(klines_1d: pd.DataFrame) -> dict[str, Any]:
    """EMA-20/50/200 (1d). 输出 series(对齐 klines index)+ current 值。"""
    if klines_1d is None or klines_1d.empty or "close" not in klines_1d.columns:
        return {
            "ema_20_series": None, "ema_50_series": None, "ema_200_series": None,
            "ema_20_current": None, "ema_50_current": None, "ema_200_current": None,
        }
    close = klines_1d["close"].astype(float)
    ema_20 = close.ewm(span=20, adjust=False).mean()
    ema_50 = close.ewm(span=50, adjust=False).mean()
    ema_200 = close.ewm(span=200, adjust=False).mean()
    return {
        "ema_20_series": ema_20,
        "ema_50_series": ema_50,
        "ema_200_series": ema_200,
        "ema_20_current": float(ema_20.iloc[-1]),
        "ema_50_current": float(ema_50.iloc[-1]),
        "ema_200_current": float(ema_200.iloc[-1]),
    }


def compute_emas_4h(klines_4h: pd.DataFrame) -> dict[str, Any]:
    """EMA-20/50 (4h). 输出 series + current。"""
    if klines_4h is None or klines_4h.empty or "close" not in klines_4h.columns:
        return {
            "ema_20_4h_series": None, "ema_50_4h_series": None,
            "ema_20_4h_current": None, "ema_50_4h_current": None,
        }
    close = klines_4h["close"].astype(float)
    ema_20 = close.ewm(span=20, adjust=False).mean()
    ema_50 = close.ewm(span=50, adjust=False).mean()
    return {
        "ema_20_4h_series": ema_20,
        "ema_50_4h_series": ema_50,
        "ema_20_4h_current": float(ema_20.iloc[-1]),
        "ema_50_4h_current": float(ema_50.iloc[-1]),
    }


def compute_adx_14(klines_1d: pd.DataFrame) -> dict[str, Any]:
    """ADX-14 (Wilder smoothing). 输出 series + current + 5d avg。"""
    if (klines_1d is None or klines_1d.empty
            or not {"high", "low", "close"}.issubset(klines_1d.columns)
            or len(klines_1d) < 30):
        return {
            "adx_series": None, "adx_current": None, "adx_5d_avg": None,
        }
    df = klines_1d[["high", "low", "close"]].astype(float).copy()
    df["prev_close"] = df["close"].shift(1)
    df["tr"] = df[["high", "low", "prev_close"]].apply(
        lambda r: max(
            r["high"] - r["low"],
            abs(r["high"] - r["prev_close"]) if pd.notna(r["prev_close"]) else 0,
            abs(r["low"] - r["prev_close"]) if pd.notna(r["prev_close"]) else 0,
        ),
        axis=1,
    )
    df["up"] = df["high"] - df["high"].shift(1)
    df["down"] = df["low"].shift(1) - df["low"]
    df["+dm"] = np.where((df["up"] > df["down"]) & (df["up"] > 0), df["up"], 0.0)
    df["-dm"] = np.where((df["down"] > df["up"]) & (df["down"] > 0), df["down"], 0.0)

    period = 14
    df["tr_smooth"] = df["tr"].ewm(alpha=1.0 / period, adjust=False).mean()
    df["+dm_smooth"] = df["+dm"].ewm(alpha=1.0 / period, adjust=False).mean()
    df["-dm_smooth"] = df["-dm"].ewm(alpha=1.0 / period, adjust=False).mean()
    df["+di"] = 100 * df["+dm_smooth"] / df["tr_smooth"].replace(0, np.nan)
    df["-di"] = 100 * df["-dm_smooth"] / df["tr_smooth"].replace(0, np.nan)
    df["dx"] = 100 * abs(df["+di"] - df["-di"]) / (df["+di"] + df["-di"]).replace(0, np.nan)
    df["adx"] = df["dx"].ewm(alpha=1.0 / period, adjust=False).mean()
    adx = df["adx"]
    return {
        "adx_series": adx,
        "adx_current": float(adx.iloc[-1]) if pd.notna(adx.iloc[-1]) else None,
        "adx_5d_avg": (
            float(adx.iloc[-5:].mean()) if len(adx) >= 5 and adx.iloc[-5:].notna().all()
            else None
        ),
    }


def compute_atr_features(klines_1d: pd.DataFrame) -> dict[str, Any]:
    """ATR-14 series + current + 180d 分位百分比。"""
    if (klines_1d is None or klines_1d.empty
            or not {"high", "low", "close"}.issubset(klines_1d.columns)
            or len(klines_1d) < 14):
        return {
            "atr_14_series": None, "atr_14_current": None,
            "atr_180d_percentile": None, "atr_180d_pct_series": None,
        }
    df = klines_1d[["high", "low", "close"]].astype(float).copy()
    df["prev_close"] = df["close"].shift(1)
    df["tr"] = df[["high", "low", "prev_close"]].apply(
        lambda r: max(
            r["high"] - r["low"],
            abs(r["high"] - r["prev_close"]) if pd.notna(r["prev_close"]) else 0,
            abs(r["low"] - r["prev_close"]) if pd.notna(r["prev_close"]) else 0,
        ),
        axis=1,
    )
    atr = df["tr"].ewm(alpha=1.0 / 14, adjust=False).mean()
    current = float(atr.iloc[-1]) if pd.notna(atr.iloc[-1]) else None

    # 180d 分位:窗口内排名百分位
    pct_series = atr.rolling(180, min_periods=30).apply(
        lambda x: (x.rank(pct=True).iloc[-1] * 100) if len(x) > 0 else np.nan,
        raw=False,
    )
    pct_current = (
        float(pct_series.iloc[-1]) if pd.notna(pct_series.iloc[-1]) else None
    )
    return {
        "atr_14_series": atr,
        "atr_14_current": current,
        "atr_180d_percentile": pct_current,
        "atr_180d_pct_series": pct_series,
    }


def detect_swing_points(
    klines_1d: pd.DataFrame, *, depth: int = 5,
) -> list[dict[str, Any]]:
    """zigzag 算法:depth 根 K 线内的局部高/低点。

    返回 list of {"date": Timestamp, "type": "high"|"low", "price": float}。
    """
    if (klines_1d is None or klines_1d.empty
            or not {"high", "low"}.issubset(klines_1d.columns)
            or len(klines_1d) < 2 * depth + 1):
        return []
    high = klines_1d["high"].astype(float)
    low = klines_1d["low"].astype(float)
    points: list[dict[str, Any]] = []
    for i in range(depth, len(klines_1d) - depth):
        window_h = high.iloc[i - depth:i + depth + 1]
        window_l = low.iloc[i - depth:i + depth + 1]
        ts = klines_1d.index[i]
        if high.iloc[i] == window_h.max() and high.iloc[i] > high.iloc[i - 1]:
            points.append({
                "date": ts, "type": "high", "price": float(high.iloc[i]),
            })
        elif low.iloc[i] == window_l.min() and low.iloc[i] < low.iloc[i - 1]:
            points.append({
                "date": ts, "type": "low", "price": float(low.iloc[i]),
            })
    return points


def compute_lth_sth_changes(onchain: dict[str, Any]) -> dict[str, Any]:
    """LTH/STH supply 30d/90d %change + realized price 现值。

    onchain dict 形如 {metric_name: pd.Series}(time-indexed)。
    """
    out: dict[str, Any] = {
        "lth_supply_30d_pct_change": None,
        "lth_supply_90d_pct_change": None,
        "sth_supply_30d_pct_change": None,
        "sth_supply_90d_pct_change": None,
        "lth_realized_price_current": None,
        "sth_realized_price_current": None,
    }
    if not isinstance(onchain, dict):
        return out
    for src_name, prefix in (("lth_supply", "lth"), ("sth_supply", "sth")):
        s = onchain.get(src_name)
        if s is None or len(s) < 2:
            continue
        s = s.dropna().astype(float)
        if len(s) < 2:
            continue
        latest = float(s.iloc[-1])
        if len(s) >= 30:
            then = float(s.iloc[-30])
            if then > 0:
                out[f"{prefix}_supply_30d_pct_change"] = (latest - then) / then * 100
        if len(s) >= 90:
            then = float(s.iloc[-90])
            if then > 0:
                out[f"{prefix}_supply_90d_pct_change"] = (latest - then) / then * 100
    for src_name, key in (
        ("lth_realized_price", "lth_realized_price_current"),
        ("sth_realized_price", "sth_realized_price_current"),
    ):
        s = onchain.get(src_name)
        if s is not None and len(s) > 0:
            try:
                out[key] = float(s.dropna().iloc[-1])
            except (IndexError, ValueError):
                pass
    return out


def compute_exchange_flow_features(onchain: dict[str, Any]) -> dict[str, Any]:
    """exchange_net_flow 30d sum + max outflow + series。"""
    out: dict[str, Any] = {
        "exchange_net_flow_30d_sum": None,
        "exchange_net_flow_30d_max_outflow": None,
        "exchange_net_flow_30d_series": None,
    }
    if not isinstance(onchain, dict):
        return out
    s = onchain.get("exchange_net_flow")
    if s is None or len(s) == 0:
        return out
    s = s.dropna().astype(float)
    if len(s) == 0:
        return out
    last_30 = s.iloc[-30:] if len(s) >= 30 else s
    out["exchange_net_flow_30d_sum"] = float(last_30.sum())
    out["exchange_net_flow_30d_max_outflow"] = float(last_30.min())
    out["exchange_net_flow_30d_series"] = last_30
    return out


def compute_funding_features(derivatives: dict[str, Any]) -> dict[str, Any]:
    """funding_rate 现值 + 90d z-score + 30d max + 30d series。"""
    out: dict[str, Any] = {
        "funding_rate_current": None,
        "funding_rate_z_score_90d": None,
        "funding_rate_30d_max": None,
        "funding_rate_30d_series": None,
    }
    if not isinstance(derivatives, dict):
        return out
    s = derivatives.get("funding_rate")
    if s is None or len(s) == 0:
        return out
    s = s.dropna().astype(float)
    if len(s) == 0:
        return out
    out["funding_rate_current"] = float(s.iloc[-1])
    if len(s) >= 30:
        out["funding_rate_30d_max"] = float(s.iloc[-30:].max())
        out["funding_rate_30d_series"] = s.iloc[-30:]
    if len(s) >= 90:
        last_90 = s.iloc[-90:]
        mu = last_90.mean()
        sigma = last_90.std()
        if sigma > 0:
            out["funding_rate_z_score_90d"] = float(
                (s.iloc[-1] - mu) / sigma
            )
    return out


def compute_oi_features(derivatives: dict[str, Any]) -> dict[str, Any]:
    """open_interest 现值 + 90d z-score + 30d series。"""
    out: dict[str, Any] = {
        "open_interest_current": None,
        "open_interest_z_score_90d": None,
        "open_interest_30d_series": None,
    }
    if not isinstance(derivatives, dict):
        return out
    s = derivatives.get("open_interest")
    if s is None or len(s) == 0:
        return out
    s = s.dropna().astype(float)
    if len(s) == 0:
        return out
    out["open_interest_current"] = float(s.iloc[-1])
    if len(s) >= 30:
        out["open_interest_30d_series"] = s.iloc[-30:]
    if len(s) >= 90:
        last_90 = s.iloc[-90:]
        mu = last_90.mean()
        sigma = last_90.std()
        if sigma > 0:
            out["open_interest_z_score_90d"] = float(
                (s.iloc[-1] - mu) / sigma
            )
    return out


def compute_price_features(klines_1d: pd.DataFrame) -> dict[str, Any]:
    """current_close + max_drawdown 60d + ema_50_slope_30d。"""
    out: dict[str, Any] = {
        "current_close": None,
        "max_drawdown_60d_pct": None,
        "ema_50_slope_30d": None,
    }
    if klines_1d is None or klines_1d.empty or "close" not in klines_1d.columns:
        return out
    close = klines_1d["close"].astype(float)
    out["current_close"] = float(close.iloc[-1])
    if len(close) >= 60:
        last_60 = close.iloc[-60:]
        peak = last_60.cummax()
        drawdown = (last_60 - peak) / peak * 100
        out["max_drawdown_60d_pct"] = float(drawdown.min())
    if len(close) >= 80:
        ema_50 = close.ewm(span=50, adjust=False).mean()
        if len(ema_50) >= 31:
            slope = (ema_50.iloc[-1] - ema_50.iloc[-31]) / ema_50.iloc[-31] * 100
            out["ema_50_slope_30d"] = float(slope)
    return out


def compute_macro_features(macro: dict[str, Any]) -> dict[str, Any]:
    """9 类 macro 因子的 current + 30d_change_pct + 90d_change_pct。

    支持的因子(键名 = DAO metric_name):
      dxy, us10y(or dgs10), us2y, vix, nasdaq, m2(or global_m2),
      fed_balance_sheet, btc_dominance, etf_flow
    """
    out: dict[str, Any] = {}
    if not isinstance(macro, dict):
        return out

    # 别名映射:DAO 的 metric_name → 输出字段前缀
    aliases = {
        "dxy": "dxy",
        "us10y": "us10y", "dgs10": "us10y",     # 同义
        "us2y": "us2y",
        "vix": "vix",
        "nasdaq": "nasdaq",
        "m2": "m2", "global_m2": "m2",
        "fed_balance_sheet": "fed_balance",
        "btc_dominance": "btc_dominance",
        "etf_flow": "etf_flow",
    }
    for src, prefix in aliases.items():
        s = macro.get(src)
        if s is None or len(s) == 0:
            continue
        s = s.dropna().astype(float)
        if len(s) == 0:
            continue
        latest = float(s.iloc[-1])
        out[f"{prefix}_current"] = latest
        if len(s) >= 30:
            then = float(s.iloc[-30])
            if then != 0:
                out[f"{prefix}_30d_change_pct"] = (latest - then) / then * 100
        if len(s) >= 90:
            then = float(s.iloc[-90])
            if then != 0:
                out[f"{prefix}_90d_change_pct"] = (latest - then) / then * 100

    # vix 30d 均值 + 90d max(L5 prompt 显式需要)
    s = macro.get("vix")
    if s is not None and len(s) > 0:
        s = s.dropna().astype(float)
        if len(s) >= 30:
            out["vix_30d_avg"] = float(s.iloc[-30:].mean())
        if len(s) >= 90:
            out["vix_90d_max"] = float(s.iloc[-90:].max())

    # us10y 30d_change_bps + us2y/10y spread
    for src, prefix in (("us10y", "us10y"), ("dgs10", "us10y")):
        s = macro.get(src)
        if s is None or len(s) == 0:
            continue
        s = s.dropna().astype(float)
        if len(s) >= 30:
            bps = (float(s.iloc[-1]) - float(s.iloc[-30])) * 100
            out["us10y_30d_change_bps"] = bps
        break

    s10 = macro.get("us10y") or macro.get("dgs10")
    s2 = macro.get("us2y")
    if s10 is not None and s2 is not None and len(s10) > 0 and len(s2) > 0:
        try:
            spread = (float(s10.dropna().iloc[-1])
                      - float(s2.dropna().iloc[-1])) * 100
            out["yield_curve_2_10_spread_bps"] = spread
        except Exception:
            pass

    # ETF flow 30d sum + 7d sum(L5 prompt 期望 etf_flow_30d_sum_usd)
    s = macro.get("etf_flow")
    if s is not None and len(s) > 0:
        s = s.dropna().astype(float)
        if len(s) >= 30:
            out["etf_flow_30d_sum_usd"] = float(s.iloc[-30:].sum())
        if len(s) >= 7:
            out["etf_flow_7d_sum_usd"] = float(s.iloc[-7:].sum())

    return out


def compute_btc_macro_corr_60d(
    klines_1d: pd.DataFrame, macro: dict[str, Any], *, key: str = "nasdaq",
) -> Optional[float]:
    """BTC 与 macro[key] 60d 相关系数(对齐日期 + Pearson)。"""
    if (klines_1d is None or klines_1d.empty
            or "close" not in klines_1d.columns):
        return None
    if not isinstance(macro, dict):
        return None
    s_macro = macro.get(key)
    if s_macro is None or len(s_macro) < 60:
        return None
    btc = klines_1d["close"].astype(float)
    if len(btc) < 60:
        return None

    # 对齐 date 索引
    try:
        btc_idx = btc.copy()
        btc_idx.index = pd.to_datetime(btc_idx.index, utc=True).normalize()
        macro_idx = s_macro.copy().astype(float)
        macro_idx.index = pd.to_datetime(macro_idx.index, utc=True).normalize()
        btc_idx = btc_idx[~btc_idx.index.duplicated(keep="last")]
        macro_idx = macro_idx[~macro_idx.index.duplicated(keep="last")]
        df = pd.concat([btc_idx, macro_idx], axis=1, join="inner").dropna()
        if len(df) < 60:
            return None
        df = df.iloc[-60:]
        # pct_change Pearson
        a = df.iloc[:, 0].pct_change().dropna()
        b = df.iloc[:, 1].pct_change().dropna()
        df2 = pd.concat([a, b], axis=1, join="inner").dropna()
        if len(df2) < 30:
            return None
        return float(df2.corr().iloc[0, 1])
    except Exception as e:
        logger.warning("compute_btc_macro_corr_60d failed: %s", e)
        return None


# ============================================================
# ContextBuilder 主类
# ============================================================

class ContextBuilder:
    """从 SQLite DB 构造 6 个 AI agent 共需的 context dict。

    用法:
        from src.ai.context_builder import ContextBuilder
        ctx = ContextBuilder(conn).build_full_context()
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        klines_lookback: int = 365,
        macro_lookback_days: int = 365,
        events_window_hours: int = 72,
    ) -> None:
        self.conn = conn
        self.klines_lookback = klines_lookback
        self.macro_lookback_days = macro_lookback_days
        self.events_window_hours = events_window_hours

    # ------------------------------------------------------------------
    # Public 主入口
    # ------------------------------------------------------------------

    def build_full_context(
        self, *, now_utc: Optional[str] = None,
    ) -> dict[str, Any]:
        """一次性构造完整 context(给 Orchestrator.run_full_a 用)。"""
        klines_1d = BTCKlinesDAO.get_recent_as_df(
            self.conn, "1d", limit=self.klines_lookback,
        )
        klines_4h = BTCKlinesDAO.get_recent_as_df(
            self.conn, "4h", limit=self.klines_lookback,
        )
        derivatives = DerivativesDAO.get_all_metrics(
            self.conn, lookback_days=self.macro_lookback_days,
        )
        onchain = OnchainDAO.get_all_metrics(
            self.conn, lookback_days=self.macro_lookback_days,
        )
        macro = MacroDAO.get_all_metrics(
            self.conn, lookback_days=self.macro_lookback_days,
        )
        events_72h = EventsCalendarDAO.get_upcoming_within_hours(
            self.conn, hours=self.events_window_hours, now_utc=now_utc,
        )
        events_count_72h = len(events_72h)

        # 类 A 计算
        ema1d = compute_emas_1d(klines_1d)
        ema4h = compute_emas_4h(klines_4h)
        adx = compute_adx_14(klines_1d)
        atr = compute_atr_features(klines_1d)
        swing = detect_swing_points(klines_1d, depth=5)
        lth_sth = compute_lth_sth_changes(onchain)
        ex_flow = compute_exchange_flow_features(onchain)
        funding = compute_funding_features(derivatives)
        oi = compute_oi_features(derivatives)
        price = compute_price_features(klines_1d)
        macro_feats = compute_macro_features(macro)
        btc_corr_60d = compute_btc_macro_corr_60d(klines_1d, macro, key="nasdaq")

        # computed_indicators 聚合(L1+L2+L4 共用)
        computed_indicators = {
            **{k: v for k, v in ema1d.items() if not k.endswith("_series")},
            **{k: v for k, v in ema4h.items() if not k.endswith("_series")},
            "adx_14_1d_current": adx["adx_current"],
            "adx_14_1d_5d_avg": adx["adx_5d_avg"],
            "atr_14_1d_current": atr["atr_14_current"],
            "atr_180d_percentile": atr["atr_180d_percentile"],
            **{k: v for k, v in lth_sth.items()},
            "exchange_net_flow_30d_sum": ex_flow["exchange_net_flow_30d_sum"],
            "exchange_net_flow_30d_max_outflow":
                ex_flow["exchange_net_flow_30d_max_outflow"],
            "funding_rate_current": funding["funding_rate_current"],
            "funding_rate_z_score_90d": funding["funding_rate_z_score_90d"],
            "funding_rate_30d_max": funding["funding_rate_30d_max"],
            "open_interest_current": oi["open_interest_current"],
            "open_interest_z_score_90d": oi["open_interest_z_score_90d"],
            "current_close": price["current_close"],
            "max_drawdown_60d_pct": price["max_drawdown_60d_pct"],
            "ema_50_slope_30d": price["ema_50_slope_30d"],
            "swing_5_recent": [
                {"date": str(p["date"]), "type": p["type"], "price": p["price"]}
                for p in (swing[-5:] if len(swing) >= 5 else swing)
            ],
            "swing_high_3_recent": [
                p["price"] for p in swing if p["type"] == "high"
            ][-3:],
            "swing_low_3_recent": [
                p["price"] for p in swing if p["type"] == "low"
            ][-3:],
        }

        # 历史:上一次 strategy_run + 各层 AI 输出占位(1.9-A 还没建 AIOutputsDAO)
        previous_strategy_run = StrategyStateDAO.get_latest_state(self.conn)
        current_state = (
            (previous_strategy_run or {}).get("action_state")
            or "FLAT"
        )

        # 类型 D — orchestrator 内部映射(多在 Orchestrator 内算,这里只摆位置)
        return {
            # 原始 series + DAO dump(给 chart 渲染 + helper 复用)
            "klines_1d": klines_1d,
            "klines_4h": klines_4h,
            "derivatives": derivatives,
            "onchain": onchain,
            "macro": macro,

            # 类型 A 派生 series + dict
            "ema_20_1d": ema1d["ema_20_series"],
            "ema_50_1d": ema1d["ema_50_series"],
            "ema_200_1d": ema1d["ema_200_series"],
            "ema_20_4h": ema4h["ema_20_4h_series"],
            "ema_50_4h": ema4h["ema_50_4h_series"],
            "adx_14_1d": adx["adx_series"],
            "atr_14_1d": atr["atr_14_series"],
            "atr_180d_pct_1d": atr["atr_180d_pct_series"],
            "swing_points_1d": swing,
            "funding_rate_series": funding["funding_rate_30d_series"],
            "open_interest_series": oi["open_interest_30d_series"],
            "exchange_net_flow_series":
                ex_flow["exchange_net_flow_30d_series"],

            # 给 6 个 agent 直接用的字段
            "computed_indicators": computed_indicators,
            "computed_macro_indicators": macro_feats,
            "btc_macro_corr_60d": btc_corr_60d,
            "current_close": price["current_close"],

            # 事件 + 类 B 预览(L3 risk_preview 在此组装)
            "events_calendar_72h": events_72h,
            "events_count_72h": events_count_72h,
            "risk_preview": build_risk_preview(
                funding_z=funding["funding_rate_z_score_90d"],
                oi_z=oi["open_interest_z_score_90d"],
                events_count_72h=events_count_72h,
            ),

            # 状态机 + 历史(类型 C)
            "current_state": current_state,
            "previous_strategy_run": previous_strategy_run,
            # previous_l1-l5 占位:1.9-A 暂无 AIOutputsDAO,均为 None
            "previous_l1": None, "previous_l2": None, "previous_l3": None,
            "previous_l4": None, "previous_l5": None,
        }


# ============================================================
# 类型 B — risk_preview 派生(纯客观,3 字段)
# ============================================================

def build_risk_preview(
    *,
    funding_z: Optional[float],
    oi_z: Optional[float],
    events_count_72h: int,
) -> dict[str, Any]:
    """L3 风险预览 — 仅 3 个客观字段(铁律 1)。

    L3 prompt v3 删除了 crowding_level / event_risk_active / macro_warning_count
    (规则结论标签),只保留这 3 个客观值。
    """
    return {
        "funding_rate_z_score_90d": funding_z,
        "open_interest_z_score_90d": oi_z,
        "events_count_72h": int(events_count_72h),
    }
