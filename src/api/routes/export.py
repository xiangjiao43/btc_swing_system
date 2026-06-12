"""数据导出端点 — 把 SpotCycleContextBuilder + ContextBuilder 的数据
渲染成一份结构化 markdown，供外部 AI 分析使用。

本模块当前尚未注册到 src/api/app.py。可通过 CLI 调用 render_factors_markdown()
拿到样本，确认格式后再 include。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from src.ai.context_builder import ContextBuilder
from src.ai.spot_cycle_context_builder import SpotCycleContextBuilder
from src.strategy.local_indicators import (
    compute_mayer_multiple,
    compute_pi_cycle,
)

_BJT = timezone(timedelta(hours=8))

# 每个指标的"可接受新鲜度上限(天)"。超过则在 markdown 里打 ⚠️STALE。
# 按指标更新频率分档(用户指定):
#   - 日频(价格/衍生品/DXY/VIX/股指/收益率类)/ Glassnode 链上: 3 天
#   - 周度宏观(fed_balance_sheet H.4.1): 10 天
#   - 月频(CPI / Core CPI / M2 / PCE): 40 天
#   - 政策利率(fed_funds_rate): 45 天
_STALE_DAYS_DEFAULT = 3
_STALE_DAYS_BY_FACTOR: dict[str, int] = {
    "cpi": 40,
    "core_cpi": 40,
    "m2": 40,
    "pce": 40,
    "fed_funds_rate": 45,
    "fed_balance_sheet": 10,
    # ETF 仅交易日发布,5 天阈值跨越周末 + 1 工作日
    "etf_flow": 5,
    "etf_flow_7d_sum_usd": 5,
    "etf_flow_30d_sum_usd": 5,
}

# 抓取类因子 → (table, metric_name)。
# 这些因子从外部 API 直拉(Glassnode / CoinGlass / FRED),DB 有对应原始行。
# 行尾标 "抓取于 <BJT>",时间取该行的 inserted_at_utc。
#
# 不在此 dict 中的因子视为"本地计算类"(EMA / 均线 / Z-score / Pi Cycle 等),
# 标 "计算于 <render time BJT>"(渲染时刻)。
_DIRECT_FETCH_FACTORS: dict[str, tuple[str, str | None]] = {
    # —— onchain_metrics(metric_name 索引)——
    "mvrv_z_score": ("onchain_metrics", "mvrv_z_score"),
    "mvrv": ("onchain_metrics", "mvrv"),
    "nupl": ("onchain_metrics", "nupl"),
    "realized_price": ("onchain_metrics", "realized_price"),
    "lth_realized_price": ("onchain_metrics", "lth_realized_price"),
    "sth_realized_price": ("onchain_metrics", "sth_realized_price"),
    "lth_mvrv": ("onchain_metrics", "lth_mvrv"),
    "sth_mvrv": ("onchain_metrics", "sth_mvrv"),
    "percent_supply_in_profit": ("onchain_metrics", "percent_supply_in_profit"),
    "rhodl_ratio": ("onchain_metrics", "rhodl_ratio"),
    "reserve_risk": ("onchain_metrics", "reserve_risk"),
    "puell_multiple": ("onchain_metrics", "puell_multiple"),
    "hash_rate": ("onchain_metrics", "hash_rate"),
    "lth_supply": ("onchain_metrics", "lth_supply"),
    "sth_supply": ("onchain_metrics", "sth_supply"),
    "sopr_adjusted": ("onchain_metrics", "sopr_adjusted"),
    "cdd": ("onchain_metrics", "cdd"),
    "ssr": ("onchain_metrics", "ssr"),
    "lth_sopr": ("onchain_metrics", "lth_sopr"),
    "sth_sopr": ("onchain_metrics", "sth_sopr"),
    "lth_net_position_change": ("onchain_metrics", "lth_net_position_change"),
    "exchange_balance": ("onchain_metrics", "exchange_balance"),
    "exchange_net_flow": ("onchain_metrics", "exchange_net_flow"),
    "cvdd": ("onchain_metrics", "cvdd"),
    "atm_iv_1m": ("onchain_metrics", "atm_iv_1m"),
    "25delta_skew_1m": ("onchain_metrics", "25delta_skew_1m"),
    "max_pain_1m": ("onchain_metrics", "max_pain_1m"),
    # —— macro_metrics(metric_name 索引)——
    "dxy": ("macro_metrics", "dxy"),
    "us10y": ("macro_metrics", "us10y"),
    "us2y": ("macro_metrics", "us2y"),
    "real_yield": ("macro_metrics", "real_yield"),
    "fed_funds_rate": ("macro_metrics", "fed_funds_rate"),
    "cpi": ("macro_metrics", "cpi"),
    "core_cpi": ("macro_metrics", "core_cpi"),
    "m2": ("macro_metrics", "m2"),
    "fed_balance_sheet": ("macro_metrics", "fed_balance_sheet"),
    "vix": ("macro_metrics", "vix"),
    "nasdaq": ("macro_metrics", "nasdaq"),
    "fear_greed_index": ("macro_metrics", "fear_greed_index"),
    # —— derivatives_snapshots(宽表,共享 inserted_at_utc;metric_name 用 None 哨兵)——
    "funding_rate": ("derivatives_snapshots", None),
    "open_interest": ("derivatives_snapshots", None),
    "btc_dominance": ("derivatives_snapshots", None),
    "long_short_ratio": ("derivatives_snapshots", None),
    "liquidation_total": ("derivatives_snapshots", None),
    "etf_flow": ("derivatives_snapshots", None),
    # —— price_candles(只有 1d 收盘自己是"抓取",衍生 EMA/ADX/ATR/swing 都是"计算")——
    "current_close": ("price_candles_1d", None),
}


# 当天还没到触发时间的 cron → 这些因子归"待今日 cron"档,不算真异常。
# 映射 factor_key → (BJT hour, BJT minute)。取该 cron 的最晚一档(主+补救)。
_TODAY_PENDING_CRON_FACTORS: dict[str, tuple[int, int]] = {
    # batch3 独立 cron BJT 10:50
    "cvdd": (10, 50),
    "atm_iv_1m": (10, 50),
    "25delta_skew_1m": (10, 50),
    "max_pain_1m": (10, 50),
}

# FRED 月频源:每月只发布一次,当月没出新数据时 inserted_at_utc 不动。
# 这些归"月频源未发布"档,与"真异常"区分。
_MONTHLY_SOURCE_FACTORS: set[str] = {"cpi", "core_cpi", "m2", "pce"}


# 派生指标 → 基准 series 的 factor_key 映射。
# 派生指标自身没有 as_of(series 直接计算,不带时间戳),按基准的 as_of 判新鲜度。
_DERIVED_BASE: dict[str, str] = {
    "funding_rate_z_score_90d": "funding_rate",
    "open_interest_z_score_90d": "open_interest",
    "etf_flow_7d_sum_usd": "etf_flow",
    "etf_flow_30d_sum_usd": "etf_flow",
    "btc_nasdaq_corr_60d": "nasdaq",
    "exchange_net_flow_30d_sum": "exchange_net_flow",
    "lth_supply_90d_pct_change": "lth_supply",
    "sth_supply_90d_pct_change": "sth_supply",
}


# SpotCycle available_factors 子组 → 5 个章节
_SECTION_MAP = {
    "价格技术": ["price_structure"],
    "链上": [
        "onchain_valuation",
        "holder_behavior",
        "onchain_holder_behavior",
        "exchange_and_flows",
    ],
    "衍生品": ["market_context"],
    "宏观": ["macro"],
}

# 因子 → 用途标签(3 档:大周期 / 波段 / 通用)。
#
# 分类原则(用户 2026-06-08 定稿):
#   [大周期] — 链上估值 / 链上持有者 / 链上周期类(MVRV/NUPL/RHODL/Puell/
#              LTH/STH/SOPR/CDD/HODL Waves/SSR ...)
#            + 大周期价格择时(MA200d/MA200w/ATH 回撤/Pi Cycle/Mayer)
#            + 宏观货币"慢变量"(M2 / Fed Balance Sheet / Fed Funds /
#              CPI / Core CPI)— 季度~月度尺度,趋势影响 BTC 流动性大环境
#            + 收益率曲线 10Y-2Y(衰退信号,长周期)
#
#   [波段]   — 价格技术日内/4h(EMA20/50/200/ADX/ATR/swing/价位)
#            + 衍生品(funding/OI/long_short/liquidation/btc_dominance)
#            + 期权(若加入)
#
#   [通用]   — 宏观市场"快变量"(DXY / VIX / NASDAQ / 收益率 us10y/us2y/
#              real_yield / BTC-纳指相关)— 周内 / 月内尺度,既给大周期定背景
#              也给波段提供风险情绪输入
#            + 价格基准(current_close / tf_alignment)
#            + 资金流(交易所余额变化 30d 累计 / ETF 流量)— Layer A 估"长钱
#              动向"、Layer B 估"周内压力"
#
# 兜底:无显式映射 → [通用]
_LAYER_TAG_BIG = "[大周期]"
_LAYER_TAG_SWING = "[波段]"
_LAYER_TAG_BOTH = "[通用]"
_LAYER_TAG_MAP: dict[str, str] = {
    # ---- 价格技术 ----
    "current_close": _LAYER_TAG_BOTH,
    "ath_drawdown_pct": _LAYER_TAG_BIG,
    "ma_200d": _LAYER_TAG_BIG,
    "ma_200w": _LAYER_TAG_BIG,
    "ma_200w_deviation_pct": _LAYER_TAG_BIG,
    "monthly_ohlc_structure": _LAYER_TAG_BIG,
    "major_support_resistance_zones": _LAYER_TAG_BIG,
    "tf_alignment": _LAYER_TAG_BOTH,
    "ema_20_4h_current": _LAYER_TAG_SWING,
    "ema_50_4h_current": _LAYER_TAG_SWING,
    "ema_20_1d_current": _LAYER_TAG_SWING,
    "ema_50_1d_current": _LAYER_TAG_SWING,
    "ema_200_1d_current": _LAYER_TAG_SWING,
    "ema_50_slope_30d": _LAYER_TAG_SWING,
    "adx_14_1d_current": _LAYER_TAG_SWING,
    "adx_14_1d_5d_avg": _LAYER_TAG_SWING,
    "atr_14_1d_current": _LAYER_TAG_SWING,
    "atr_180d_percentile": _LAYER_TAG_SWING,
    "price_position_in_90d_range": _LAYER_TAG_SWING,
    "max_drawdown_60d_pct": _LAYER_TAG_SWING,
    "swing_high_3_recent": _LAYER_TAG_SWING,
    "swing_low_3_recent": _LAYER_TAG_SWING,
    # ---- 大周期估值/择时(新增本地算)----
    "pi_cycle_ratio": _LAYER_TAG_BIG,
    "mayer_multiple": _LAYER_TAG_BIG,
    # ---- 链上 / 估值 ----
    "mvrv_z_score": _LAYER_TAG_BIG,
    "mvrv": _LAYER_TAG_BIG,
    "nupl": _LAYER_TAG_BIG,
    "realized_price": _LAYER_TAG_BIG,
    "lth_realized_price": _LAYER_TAG_BIG,
    "sth_realized_price": _LAYER_TAG_BOTH,
    "lth_mvrv": _LAYER_TAG_BIG,
    "sth_mvrv": _LAYER_TAG_BIG,
    "percent_supply_in_profit": _LAYER_TAG_BIG,
    "rhodl_ratio": _LAYER_TAG_BIG,
    "reserve_risk": _LAYER_TAG_BIG,
    "puell_multiple": _LAYER_TAG_BIG,
    "hash_rate": _LAYER_TAG_BIG,
    # ---- 链上 / 持币者 ----
    "lth_supply": _LAYER_TAG_BIG,
    "sth_supply": _LAYER_TAG_BIG,
    "lth_supply_90d_pct_change": _LAYER_TAG_BIG,
    "sth_supply_90d_pct_change": _LAYER_TAG_BIG,
    "sopr_adjusted": _LAYER_TAG_BIG,
    "hodl_waves_1y_plus_aggregate": _LAYER_TAG_BIG,
    "cdd": _LAYER_TAG_BIG,
    "ssr": _LAYER_TAG_BIG,
    "lth_sopr": _LAYER_TAG_BIG,
    "sth_sopr": _LAYER_TAG_BIG,
    "lth_net_position_change": _LAYER_TAG_BIG,
    "percent_supply_in_loss": _LAYER_TAG_BIG,
    # ---- 链上 / 交易所流 ----
    "exchange_balance": _LAYER_TAG_BIG,
    "exchange_net_position_change": _LAYER_TAG_BIG,
    "exchange_net_flow": _LAYER_TAG_BIG,
    "exchange_net_flow_30d_sum": _LAYER_TAG_BOTH,
    "etf_flow": _LAYER_TAG_BOTH,
    "etf_flow_7d_sum_usd": _LAYER_TAG_BOTH,
    "etf_flow_30d_sum_usd": _LAYER_TAG_BOTH,
    # ---- 衍生品 / 市场情绪 ----
    "btc_dominance": _LAYER_TAG_SWING,
    "funding_rate": _LAYER_TAG_SWING,
    "funding_rate_z_score_90d": _LAYER_TAG_SWING,
    "open_interest": _LAYER_TAG_SWING,
    "open_interest_z_score_90d": _LAYER_TAG_SWING,
    "long_short_ratio": _LAYER_TAG_SWING,
    "liquidation_total": _LAYER_TAG_SWING,
    # ---- 宏观 ----
    # 宏观市场快变量(周内 / 月内尺度) → 通用
    "dxy": _LAYER_TAG_BOTH,
    "us10y": _LAYER_TAG_BOTH,
    "us2y": _LAYER_TAG_BOTH,
    "real_yield": _LAYER_TAG_BOTH,
    "vix": _LAYER_TAG_BOTH,
    "nasdaq": _LAYER_TAG_BOTH,
    "btc_nasdaq_corr_60d": _LAYER_TAG_BOTH,
    # 宏观货币慢变量(月度 / 季度尺度) → 大周期
    "fed_funds_rate": _LAYER_TAG_BIG,
    "cpi": _LAYER_TAG_BIG,
    "core_cpi": _LAYER_TAG_BIG,
    "m2": _LAYER_TAG_BIG,
    "fed_balance_sheet": _LAYER_TAG_BIG,
    "yield_curve_2_10_spread_bps": _LAYER_TAG_BIG,
    "fear_greed_index": _LAYER_TAG_BOTH,  # 极端区有大周期参考,日常波动有波段参考
    # 批 3
    "cvdd": _LAYER_TAG_BIG,
    "atm_iv_1m": _LAYER_TAG_SWING,
    "25delta_skew_1m": _LAYER_TAG_SWING,
    "max_pain_1m": _LAYER_TAG_SWING,
}

# 因子中文名 + 单位 + 排序权重(越小越靠前)
_FACTOR_META: dict[str, tuple[str, str, int]] = {
    # —— 价格技术 ——
    "current_close": ("BTC 现价", "USD", 1),
    "ath_drawdown_pct": ("距 ATH 跌幅", "%", 2),
    "ma_200d": ("MA200 (日)", "USD", 3),
    "ma_200w": ("MA200 (周)", "USD", 4),
    "ma_200w_deviation_pct": ("距 MA200W 偏离", "%", 5),
    "monthly_ohlc_structure": ("月线结构", "", 6),
    "major_support_resistance_zones": ("主要支撑/阻力", "", 7),
    "tf_alignment": ("多周期一致度", "", 8),
    # —— 链上 / 估值 ——
    "mvrv_z_score": ("MVRV-Z 分数", "", 20),
    "mvrv": ("MVRV", "", 21),
    "nupl": ("NUPL", "", 22),
    "realized_price": ("Realized Price", "USD", 23),
    "lth_realized_price": ("LTH Realized Price", "USD", 24),
    "sth_realized_price": ("STH Realized Price", "USD", 25),
    "lth_mvrv": ("LTH MVRV", "", 26),
    "sth_mvrv": ("STH MVRV", "", 27),
    "percent_supply_in_profit": ("盈利供给占比", "ratio", 28),
    "rhodl_ratio": ("RHODL Ratio", "", 29),
    "reserve_risk": ("Reserve Risk", "", 30),
    "puell_multiple": ("Puell Multiple", "", 31),
    "hash_rate": ("算力 Hash Rate", "TH/s", 32),
    # —— 链上 / 持币者 ——
    "lth_supply": ("LTH 持仓量", "BTC", 40),
    "sth_supply": ("STH 持仓量", "BTC", 41),
    "lth_supply_90d_pct_change": ("LTH 90d 持仓变化", "%", 42),
    "sth_supply_90d_pct_change": ("STH 90d 持仓变化", "%", 43),
    "sopr_adjusted": ("SOPR (Adjusted)", "", 44),
    "hodl_waves_1y_plus_aggregate": ("HODL 1y+ 占比", "%", 46),
    "cdd": ("CDD", "", 47),
    "ssr": ("SSR", "", 48),
    "lth_sopr": ("LTH SOPR", "", 49),
    "sth_sopr": ("STH SOPR", "", 50),
    "lth_net_position_change": ("LTH 净仓位变化", "BTC", 51),
    "percent_supply_in_loss": ("亏损供给占比", "ratio", 52),
    # —— 链上 / 交易所流 ——
    "exchange_balance": ("交易所余额", "BTC", 60),
    "exchange_net_position_change": ("交易所净持仓变化", "BTC", 61),
    "exchange_net_flow": ("交易所净流量", "BTC", 62),
    "exchange_net_flow_30d_sum": ("交易所 30d 累计净流量", "BTC", 63),
    "etf_flow": ("BTC ETF 日净流入", "USD", 64),
    "etf_flow_7d_sum_usd": ("BTC ETF 7d 累计净流入", "USD", 65),
    "etf_flow_30d_sum_usd": ("BTC ETF 30d 累计净流入", "USD", 66),
    # —— 衍生品 / 市场情绪 ——
    "btc_dominance": ("BTC Dominance", "%", 80),
    "funding_rate": ("资金费率", "", 81),
    "funding_rate_z_score_90d": ("资金费率 90d Z", "σ", 82),
    "open_interest": ("未平仓合约 OI", "USD", 83),
    "open_interest_z_score_90d": ("OI 90d Z", "σ", 84),
    "long_short_ratio": ("多空比", "", 85),
    "liquidation_total": ("24h 全网爆仓", "USD", 86),
    # —— 宏观 ——
    "dxy": ("美元指数 DXY", "", 100),
    "us10y": ("美 10y 国债收益率", "%", 101),
    "us2y": ("美 2y 国债收益率", "%", 102),
    "real_yield": ("10y TIPS 真实利率", "%", 103),
    "fed_funds_rate": ("联邦基金利率", "%", 104),
    "cpi": ("CPI (月度)", "", 105),
    "core_cpi": ("Core CPI (月度)", "", 106),
    "m2": ("M2 货币供应 (FRED, 单位:十亿 USD)", "", 107),
    "fed_balance_sheet": ("美联储资产负债表 (FRED, 单位:百万 USD)", "", 108),
    "vix": ("VIX 恐慌指数", "", 109),
    "nasdaq": ("纳斯达克指数", "", 110),
    "btc_nasdaq_corr_60d": ("BTC-纳指 60d 相关性", "ρ", 111),
    "yield_curve_2_10_spread_bps": ("收益率曲线(10Y-2Y)", "bps", 102),
    "fear_greed_index": ("Fear & Greed Index (CoinGlass)", "fg", 95),
    # 批 3(2026-06-08):4 个 Glassnode 精选指标
    "cvdd": ("CVDD (累积销毁币天美元化)", "USD", 19),  # 大周期估值/择时段
    "atm_iv_1m": ("ATM IV 1月 (Deribit, 年化)", "iv", 90),  # 衍生品段
    "25delta_skew_1m": (
        "25 Δ Skew 1月 (put IV - call IV;>0=put 贵=偏恐慌,<0=call 贵=偏 FOMO)",
        "skew", 91,
    ),
    "max_pain_1m": ("Max Pain 1月 (期权到期磁吸价位)", "USD", 92),
}

# 大周期估值/择时新增段(本地算)。单位用 "ratio2" 触发 2 位小数显示。
_CYCLE_VALUATION_META: dict[str, tuple[str, str, int]] = {
    "pi_cycle_ratio": ("Pi Cycle Ratio (SMA111/SMA350×2)", "ratio2", 1),
    "mayer_multiple": ("Mayer Multiple (close/SMA200)", "ratio2", 2),
}

# ContextBuilder.computed_indicators 中专属波段技术因子
_SWING_TECH_META: dict[str, tuple[str, str, int]] = {
    "ema_20_4h_current": ("4h EMA20", "USD", 9),
    "ema_50_4h_current": ("4h EMA50", "USD", 10),
    "ema_20_1d_current": ("1d EMA20", "USD", 11),
    "ema_50_1d_current": ("1d EMA50", "USD", 12),
    "ema_200_1d_current": ("1d EMA200", "USD", 13),
    "ema_50_slope_30d": ("EMA50 30d 斜率", "", 14),
    "adx_14_1d_current": ("ADX (14, 1d)", "", 15),
    "adx_14_1d_5d_avg": ("ADX 5d 均值", "", 16),
    "atr_14_1d_current": ("ATR (14, 1d)", "USD", 17),
    "atr_180d_percentile": ("ATR 180d 百分位", "pct", 18),
    "price_position_in_90d_range": ("90d 区间相对位置", "%", 19),
    "max_drawdown_60d_pct": ("60d 最大回撤", "%", 19),
    "swing_high_3_recent": ("最近 3 个 swing high", "USD", 19),
    "swing_low_3_recent": ("最近 3 个 swing low", "USD", 19),
}


def _short_date(ts: Any) -> str:
    if not ts:
        return "—"
    s = str(ts)
    return s[:10]


def _utc_str_to_bjt_pretty(utc_iso: Any) -> str:
    """ISO 字符串(UTC)→ "MM-DD HH:MM BJT"(去年份,窄屏友好)。"""
    if not utc_iso:
        return "—"
    s = str(utc_iso).replace("Z", "+00:00")
    try:
        dt_utc = datetime.fromisoformat(s)
    except ValueError:
        return str(utc_iso)[5:16]
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    return dt_utc.astimezone(_BJT).strftime("%m-%d %H:%M BJT")


def _lookup_fetch_at_utc(
    conn: sqlite3.Connection, factor_key: str,
) -> str | None:
    """查 _DIRECT_FETCH_FACTORS 对应行的 inserted_at_utc。

    返回 ISO UTC 字符串;不在 dict 中 / 行不存在 → None。
    """
    spec = _DIRECT_FETCH_FACTORS.get(factor_key)
    if spec is None:
        return None
    table, metric_name = spec
    if table == "onchain_metrics" or table == "macro_metrics":
        row = conn.execute(
            f"SELECT inserted_at_utc FROM {table} WHERE metric_name=? "
            "ORDER BY captured_at_utc DESC LIMIT 1",
            (metric_name,),
        ).fetchone()
    elif table == "derivatives_snapshots":
        row = conn.execute(
            "SELECT inserted_at_utc FROM derivatives_snapshots "
            "ORDER BY captured_at_utc DESC LIMIT 1"
        ).fetchone()
    elif table == "price_candles_1d":
        row = conn.execute(
            "SELECT inserted_at_utc FROM price_candles "
            "WHERE symbol='BTCUSDT' AND timeframe='1d' "
            "ORDER BY open_time_utc DESC LIMIT 1"
        ).fetchone()
    else:
        return None
    if row and row["inserted_at_utc"]:
        return str(row["inserted_at_utc"])
    return None


def _days_since(ts: Any) -> float | None:
    if not ts:
        return None
    s = str(ts)[:10]
    try:
        d = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    now = datetime.now(timezone.utc)
    return (now - d).total_seconds() / 86400.0


def _fresh_tag(factor_key: str, leaf: dict) -> str:
    status = leaf.get("status")
    if status == "missing" or leaf.get("actual_value") in (None, [], ""):
        return "❌缺失"

    ts = leaf.get("as_of") or leaf.get("fetched_at_utc")
    days = _days_since(ts)
    threshold = _STALE_DAYS_BY_FACTOR.get(factor_key, _STALE_DAYS_DEFAULT)
    if days is not None and days > threshold:
        return f"⚠️STALE ({days:.0f}d, 阈值 {threshold}d)"

    fresh = leaf.get("freshness") or {}
    if status == "stale" or fresh.get("is_stale"):
        return "⚠️STALE (source 标记)"
    return "新鲜"


_PCT_SIGNED_KEYS = {
    "ath_drawdown_pct",
    "ma_200w_deviation_pct",
    "lth_supply_90d_pct_change",
    "sth_supply_90d_pct_change",
    "max_drawdown_60d_pct",
    "ema_50_slope_30d",
}


def _fmt_scalar(v: Any, unit: str, factor_key: str = "") -> str:
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        if unit == "USD":
            if abs(v) >= 1e9:
                return f"${v / 1e9:.3f}B"
            if abs(v) >= 1e6:
                return f"${v / 1e6:.2f}M"
            if abs(v) >= 1e3:
                return f"${v:,.2f}"
            return f"${v:.4f}"
        if unit == "%":
            return f"{v:+.2f}%" if factor_key in _PCT_SIGNED_KEYS else f"{v:.2f}%"
        if unit == "ratio":
            return f"{v:.4f}"
        if unit == "ratio2":
            return f"{v:.2f}"
        if unit == "BTC":
            if abs(v) >= 1e3:
                return f"{v:,.0f} BTC"
            return f"{v:.4f} BTC"
        if unit == "TH/s":
            # Glassnode hash_rate 原始 = hash/s (~8e17)。换算到 EH/s = /1e18。
            if abs(v) >= 1e15:
                return f"{v / 1e18:.2f} EH/s"
            if abs(v) >= 1e9:
                return f"{v / 1e12:.2f} TH/s"
            return f"{v:,.0f} H/s"
        if unit == "σ":
            return f"{v:+.2f}σ"
        if unit == "ρ":
            return f"{v:+.3f}"
        if unit == "pct":
            return f"{v * 100:.1f}%" if abs(v) <= 1 else f"{v:.1f}%"
        if unit == "bps":
            return f"{v:+.0f} bps"
        if unit == "iv":
            # 隐含波动率(Glassnode 返回小数,如 0.35 = 35%)
            pct = v * 100.0 if abs(v) <= 5 else v
            return f"{pct:.1f}%"
        if unit == "skew":
            # 25 Δ Skew 已归一,显示带符号 + 语义辅助
            if v > 0.10:
                hint = "偏恐慌"
            elif v < -0.05:
                hint = "偏 FOMO"
            else:
                hint = "中性"
            return f"{v:+.3f} ({hint})"
        if unit == "fg":
            # Fear & Greed:0-24 极端恐惧 / 25-49 恐惧 / 50 中性 / 51-74 贪婪 / 75-100 极端贪婪
            v_int = int(round(v))
            if v_int <= 24:
                cls = "Extreme Fear 极端恐惧"
            elif v_int <= 49:
                cls = "Fear 恐惧"
            elif v_int == 50:
                cls = "Neutral 中性"
            elif v_int <= 74:
                cls = "Greed 贪婪"
            else:
                cls = "Extreme Greed 极端贪婪"
            return f"{v_int} ({cls})"
        # 默认数值
        if abs(v) >= 100:
            return f"{v:,.2f}"
        if abs(v) >= 1:
            return f"{v:.4f}"
        return f"{v:.6f}".rstrip("0").rstrip(".") or "0"
    return str(v)


def _fmt_value(v: Any, unit: str, factor_key: str = "") -> str:
    if v is None:
        return "—"
    if isinstance(v, list):
        if not v:
            return "—"
        return ", ".join(_fmt_scalar(x, unit, factor_key) for x in v)
    if isinstance(v, dict):
        return str(v)[:120]
    return _fmt_scalar(v, unit, factor_key)


def _walk_factors(available: dict) -> list[tuple[str, str, dict]]:
    """展开 available_factors 树成 [(group_key, factor_key, leaf_dict), ...]"""
    out: list[tuple[str, str, dict]] = []
    for group, sub in available.items():
        if not isinstance(sub, dict):
            continue
        for fkey, leaf in sub.items():
            if isinstance(leaf, dict) and "status" in leaf and "actual_value" in leaf:
                out.append((group, fkey, leaf))
    return out


def render_factors_markdown(conn: sqlite3.Connection) -> str:
    spot_ctx = SpotCycleContextBuilder(conn).build_spot_cycle_context()
    layer_b_ctx = ContextBuilder(conn).build_full_context()
    computed = layer_b_ctx["l1"]["computed_indicators"]
    events = (
        spot_ctx.get("available_factors", {})
        .get("event_risk", {})
        .get("events", [])
    )

    leaves = _walk_factors(spot_ctx.get("available_factors", {}))

    # K 线插入时间作为 swing-tech 因子的 as_of（这批指标全部基于 klines_1d/4h）
    cc_leaf = (
        spot_ctx.get("available_factors", {})
        .get("price_structure", {})
        .get("current_close", {})
    )
    kline_ts = cc_leaf.get("fetched_at_utc") or cc_leaf.get("as_of")

    for key in _SWING_TECH_META:
        if key not in computed:
            continue
        val = computed[key]
        leaves.append(
            (
                "__swing_tech__",
                key,
                {
                    "actual_value": val,
                    "status": "available" if val not in (None, [], "") else "missing",
                    "source": "derived_from_klines",
                    "as_of": kline_ts,
                    "freshness": {"is_stale": False},
                },
            )
        )

    # 批 3(2026-06-08):4 个 Glassnode 精选指标(全在 onchain_metrics)。
    # 分别归到 "大周期估值/择时"(cvdd) 和 "衍生品"(IV/Skew/MaxPain)章节。
    _BATCH3_GROUP_MAP = {
        "cvdd": "__cycle_valuation__",
        "atm_iv_1m": "market_context",
        "25delta_skew_1m": "market_context",
        "max_pain_1m": "market_context",
    }
    for m_name, group_key in _BATCH3_GROUP_MAP.items():
        row = conn.execute(
            "SELECT value, captured_at_utc FROM onchain_metrics "
            "WHERE metric_name=? ORDER BY captured_at_utc DESC LIMIT 1",
            (m_name,),
        ).fetchone()
        if row and row["value"] is not None:
            leaves.append(
                (
                    group_key,
                    m_name,
                    {
                        "actual_value": float(row["value"]),
                        "status": "available",
                        "source": "glassnode",
                        "as_of": row["captured_at_utc"],
                        "freshness": {"is_stale": False},
                    },
                )
            )

    # Fear & Greed Index(批 2 新增,CoinGlass 来源,存 macro_metrics)
    fg_row = conn.execute(
        "SELECT value, captured_at_utc FROM macro_metrics "
        "WHERE metric_name='fear_greed_index' "
        "ORDER BY captured_at_utc DESC LIMIT 1"
    ).fetchone()
    if fg_row and fg_row["value"] is not None:
        leaves.append(
            (
                "macro",
                "fear_greed_index",
                {
                    "actual_value": float(fg_row["value"]),
                    "status": "available",
                    "source": "coinglass",
                    "as_of": fg_row["captured_at_utc"],
                    "freshness": {"is_stale": False},
                },
            )
        )

    # 收益率曲线 10Y-2Y(已在 compute_macro_features 算好,从 L5 ctx 取)
    l5_macro = (layer_b_ctx.get("l5") or {}).get("computed_macro_indicators") or {}
    yc_bps = l5_macro.get("yield_curve_2_10_spread_bps")
    if yc_bps is not None:
        # 继承 us10y 的 as_of 作为新鲜度判定基准
        us10y_leaf = (
            spot_ctx.get("available_factors", {})
            .get("macro", {})
            .get("us10y", {})
        )
        leaves.append(
            (
                "macro",
                "yield_curve_2_10_spread_bps",
                {
                    "actual_value": yc_bps,
                    "status": "available",
                    "source": "fred_macro_derived",
                    "as_of": us10y_leaf.get("as_of") or us10y_leaf.get("fetched_at_utc"),
                    "freshness": {"is_stale": False},
                    "_derived_from": "us10y - us2y",
                },
            )
        )

    # 大周期估值/择时(本地算):Pi Cycle + Mayer Multiple
    pi = compute_pi_cycle(conn)
    if pi.get("status") == "available":
        leaves.append(
            (
                "__cycle_valuation__",
                "pi_cycle_ratio",
                {
                    "actual_value": pi["ratio"],
                    "status": "available",
                    "source": "derived_from_klines",
                    "as_of": pi["as_of"],
                    "freshness": {"is_stale": False},
                    "_detail": (
                        f"SMA-111={pi['sma_111']:.0f} / "
                        f"SMA-350×2={pi['sma_350x2']:.0f}"
                    ),
                },
            )
        )
    mm = compute_mayer_multiple(conn)
    if mm.get("status") == "available":
        leaves.append(
            (
                "__cycle_valuation__",
                "mayer_multiple",
                {
                    "actual_value": mm["mayer"],
                    "status": "available",
                    "source": "derived_from_klines",
                    "as_of": mm["as_of"],
                    "freshness": {"is_stale": False},
                    "_detail": (
                        f"close={mm['current_close']:.0f} / "
                        f"SMA-200={mm['sma_200']:.0f};参照 >2.4 偏高 / <1 偏低"
                    ),
                },
            )
        )

    # 去重(同 key 取第一次出现)+ 已知重复别名黑名单
    _DUP_ALIASES = {"sopr"}  # sopr 与 sopr_adjusted 走同一 DB series,渲染时只保留 sopr_adjusted
    seen: set[str] = set()
    deduped: list[tuple[str, str, dict]] = []
    for grp, k, leaf in leaves:
        if k in seen or k in _DUP_ALIASES:
            continue
        seen.add(k)
        deduped.append((grp, k, leaf))

    # 派生指标继承基准 series 的 as_of(本身没时间戳的派生计算用基准)
    base_ts_map: dict[str, str] = {}
    for _, k, leaf in deduped:
        ts = leaf.get("as_of") or leaf.get("fetched_at_utc")
        if ts:
            base_ts_map[k] = str(ts)
    for grp, k, leaf in deduped:
        if k in _DERIVED_BASE and not leaf.get("as_of"):
            base_key = _DERIVED_BASE[k]
            if base_key in base_ts_map:
                leaf["as_of"] = base_ts_map[base_key]
                leaf["_derived_from"] = base_key

    section_buckets: dict[str, list[tuple[str, dict]]] = {
        "价格技术": [],
        "大周期估值/择时": [],
        "链上": [],
        "衍生品": [],
        "宏观": [],
    }
    group_to_section: dict[str, str] = {}
    for sec, groups in _SECTION_MAP.items():
        for g in groups:
            group_to_section[g] = sec
    group_to_section["__swing_tech__"] = "价格技术"
    group_to_section["__cycle_valuation__"] = "大周期估值/择时"

    for grp, k, leaf in deduped:
        sec = group_to_section.get(grp)
        if sec is None:
            continue
        # 把 exchange_and_flows 里的 etf_* 移到衍生品组（语义对齐）
        if k.startswith("etf_"):
            sec = "衍生品"
        section_buckets[sec].append((k, leaf))

    all_meta: dict[str, tuple[str, str, int]] = {
        **_FACTOR_META,
        **_SWING_TECH_META,
        **_CYCLE_VALUATION_META,
    }
    for sec in section_buckets:
        section_buckets[sec].sort(
            key=lambda x: all_meta.get(x[0], (x[0], "", 9999))[2],
        )

    # 新鲜度统计(走 _fresh_tag 同一套规则,口径一致)
    total = sum(len(b) for b in section_buckets.values())
    fresh = stale = missing = 0
    for items in section_buckets.values():
        for k, leaf in items:
            tag = _fresh_tag(k, leaf)
            if tag.startswith("❌"):
                missing += 1
            elif tag.startswith("⚠️"):
                stale += 1
            else:
                fresh += 1

    now_utc_dt = datetime.now(timezone.utc)
    now_utc = now_utc_dt.strftime("%Y-%m-%d %H:%M UTC")
    now_bjt_dt = now_utc_dt.astimezone(_BJT)
    now_bjt = now_bjt_dt.strftime("%Y-%m-%d %H:%M BJT")
    render_compute_bjt = now_bjt  # 本地计算类的"计算于"取渲染时刻

    # 当天 BJT 0:00 阈值,用于"已抓取/未抓取"判定(UTC 比较)
    today_bjt_midnight_utc = now_bjt_dt.replace(
        hour=0, minute=0, second=0, microsecond=0,
    ).astimezone(timezone.utc)

    # 为每个 leaf 计算"更新时间"(UTC ISO) + 类型(fetched/computed)
    leaf_update_info: dict[str, dict[str, Any]] = {}
    fetched_today_count = 0
    # "未抓取" 分 3 类:待今日 cron / 月频源未发布 / 真异常
    pending_cron: list[tuple[str, str]] = []  # (zh_name, "10:50 档")
    monthly_pending: list[str] = []
    anomaly: list[str] = []
    total_count = 0
    for items in section_buckets.values():
        for k, leaf in items:
            total_count += 1
            fetched_utc = _lookup_fetch_at_utc(conn, k)
            if fetched_utc:
                kind = "fetched"
                update_utc = fetched_utc
            else:
                kind = "computed"
                update_utc = now_utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            leaf_update_info[k] = {
                "kind": kind,
                "update_utc": update_utc,
                "update_bjt": _utc_str_to_bjt_pretty(update_utc),
            }
            try:
                upd_dt = datetime.fromisoformat(
                    update_utc.replace("Z", "+00:00")
                )
                if upd_dt.tzinfo is None:
                    upd_dt = upd_dt.replace(tzinfo=timezone.utc)
            except ValueError:
                upd_dt = None
            if upd_dt is not None and upd_dt >= today_bjt_midnight_utc:
                fetched_today_count += 1
                continue
            zh_name = all_meta.get(k, (k, "", 9999))[0]
            # 分类未抓取项
            if k in _TODAY_PENDING_CRON_FACTORS:
                hr, mn = _TODAY_PENDING_CRON_FACTORS[k]
                # 当前 BJT 是否还没到 cron 时间?
                cron_today_bjt = now_bjt_dt.replace(
                    hour=hr, minute=mn, second=0, microsecond=0,
                )
                if now_bjt_dt < cron_today_bjt:
                    pending_cron.append((zh_name, f"{hr:02d}:{mn:02d} 档"))
                    continue
                # 已过 cron 时间仍未抓到 → 真异常
                anomaly.append(zh_name)
            elif k in _MONTHLY_SOURCE_FACTORS:
                monthly_pending.append(zh_name)
            else:
                anomaly.append(zh_name)

    lines: list[str] = []
    lines.append("# BTC 系统数据快照（供外部 AI 分析）")
    lines.append("")
    lines.append(f"生成时间：{now_utc}  ／  {now_bjt}")
    lines.append("")
    lines.append(
        f"新鲜度总览：总 {total} | 新鲜 {fresh} | ⚠️STALE {stale} | "
        f"❌缺失 {missing} | 事件 {len(events)}"
    )
    lines.append(
        f"当天抓取情况（BJT 0:00 起）：总 {total_count} | "
        f"已抓取 {fetched_today_count} | "
        f"待今日 cron {len(pending_cron)} | "
        f"月频源未发布 {len(monthly_pending)} | "
        f"真异常 {len(anomaly)}"
    )
    if pending_cron:
        # 按 cron 档分组(同档列在一起)
        by_slot: dict[str, list[str]] = {}
        for name, slot in pending_cron:
            by_slot.setdefault(slot, []).append(name)
        for slot, names in by_slot.items():
            lines.append(
                f"  待今日 cron（{slot}）：{', '.join(names)}"
            )
    if monthly_pending:
        lines.append(
            f"  月频源未发布（FRED 月度）：{', '.join(monthly_pending)}"
        )
    # 真异常那行始终显示(健康哨兵)
    lines.append(
        f"  真异常：{', '.join(anomaly) if anomaly else '（无）'}"
    )
    lines.append("")
    lines.append(
        "说明：每行格式 `指标名: 值 [单位] ｜ 数据时间: YYYY-MM-DD ｜ "
        "[新鲜/⚠️STALE/❌缺失]`。"
        "价格技术只给数值，不给 K 线形态描述；K 线形态由外部 AI 自行判读。"
    )
    lines.append("")
    lines.append("### 新鲜度说明（结构性滞后 vs 真异常）")
    lines.append("")
    lines.append(
        "- **FRED 宏观（DXY/VIX/纳指/收益率）**：美联储 H.10/H.15 每周一发布上周数据，"
        "平时滞后约 1 周属正常，**非故障**"
    )
    lines.append(
        "- **FRED 月频（CPI/Core CPI/M2/PCE）**：每月一次发布，月中滞后属正常"
    )
    lines.append(
        "- **联邦基金利率**：仅 FOMC 会议后变动，长期不变属正常"
    )
    lines.append(
        "- **Glassnode 链上**：通常 T+1；偶尔单 endpoint 滞后 2-4 天属上游问题"
    )
    lines.append(
        "- **ETF 流量**：仅交易日发布，周末 + 节假日无数据"
    )
    lines.append("")
    lines.append(
        "因此 ⚠️STALE 分两类：**结构性滞后**（上述情境，按节奏正常）"
        " vs **真异常**（日频数据超出周末/节假日仍未更新）。分析时请区分对待。"
    )
    lines.append("")

    for sec_name in ["价格技术", "大周期估值/择时", "链上", "衍生品", "宏观"]:
        lines.append(f"## {sec_name}")
        lines.append("")
        items = section_buckets[sec_name]
        if not items:
            lines.append("（无数据）")
            lines.append("")
            continue
        for k, leaf in items:
            zh_name, unit, _ = all_meta.get(k, (k, "", 9999))
            val_str = _fmt_value(leaf.get("actual_value"), unit, k)
            ts = leaf.get("as_of") or leaf.get("fetched_at_utc")
            ts_str = _short_date(ts)
            tag = _fresh_tag(k, leaf)
            layer_tag = _LAYER_TAG_MAP.get(k, _LAYER_TAG_BOTH)
            detail = leaf.get("_detail")
            detail_str = f"  （派生:{detail}）" if detail else ""
            upd = leaf_update_info.get(k) or {}
            kind = upd.get("kind", "computed")
            upd_bjt = upd.get("update_bjt") or render_compute_bjt
            upd_label = "抓取于" if kind == "fetched" else "计算于"
            lines.append(
                f"- {zh_name}: {val_str} ｜ 数据时间: {ts_str} ｜ {tag} ｜ "
                f"{layer_tag} ｜ {upd_label} {upd_bjt}{detail_str}"
            )
        lines.append("")

    lines.append("## 事件日历（未来 168h）")
    lines.append("")
    if events:
        for ev in events:
            name = ev.get("event_name") or ev.get("event_type") or "?"
            etype = ev.get("event_type") or ""
            utc_ts = ev.get("utc_trigger_time") or ev.get("date") or ""
            impact = ev.get("impact_level") or ""
            lines.append(
                f"- {name} [{etype}] ｜ 触发: {utc_ts} UTC ｜ 影响: {impact}"
            )
    else:
        lines.append("（未来 168h 无登记事件）")
    lines.append("")

    return "\n".join(lines)


__all__ = ["render_factors_markdown", "router"]


# ---------------------------------------------------------------------------
# FastAPI 路由
# ---------------------------------------------------------------------------

import re  # noqa: E402

import pandas as pd  # noqa: E402
from fastapi import APIRouter, HTTPException, Request  # noqa: E402
from fastapi.responses import (  # noqa: E402
    FileResponse,
    HTMLResponse,
    PlainTextResponse,
)
from pathlib import Path  # noqa: E402

router = APIRouter(prefix="/export", tags=["export"])

# 项目根目录(用于定位 packages/ + CSV)
_PROJECT_ROOT_FOR_PACK = Path(__file__).resolve().parent.parent.parent.parent
_PACKAGES_DIR = _PROJECT_ROOT_FOR_PACK / "packages"

# 5 CSV 新鲜度阈值(天) — 必须与 scripts/refresh_and_build.py 保持一致
_CSV_FRESHNESS_THRESHOLDS: dict[str, int] = {
    "btc_onchain_history.csv": 2,
    "btc_swing_deriv_4h.csv": 1,
    "btc_swing_deriv_1d.csv": 1,
    "btc_swing_macro.csv": 7,
    "btc_swing_options.csv": 2,
}

# 新增列(批 1+2+3)latest 行非空检查
_NEW_COLS_CHECK: dict[str, list[str]] = {
    "btc_onchain_history.csv": [
        "liveliness", "illiquid_supply_btc", "nrpl_usd",
        "lth_profit_btc", "lth_loss_btc", "sopr", "sopr_adjusted",
        "lth_nupl_ratio",
    ],
    "btc_swing_options.csv": [
        "est_leverage_ratio", "pcr_volume", "atm_iv_1w",
        "sth_mvrv", "sth_realized_price_usd",
    ],
}


@router.get(
    "/snapshot.md",
    response_class=PlainTextResponse,
    summary="导出当前数据快照（markdown，供外部 AI 分析）",
)
def get_snapshot_markdown(request: Request) -> PlainTextResponse:
    ctx = request.app.state.ctx
    conn = ctx.conn_factory()
    try:
        conn.row_factory = sqlite3.Row
        md = render_factors_markdown(conn)
    finally:
        conn.close()
    return PlainTextResponse(content=md, media_type="text/markdown; charset=utf-8")


def _build_pack_status(snapshot_md: str) -> dict[str, Any]:
    """轻量本地校验 + 包元数据,返回结构化 status 给 HTML 渲染。"""
    now_bjt = datetime.now(_BJT)
    today_bjt = now_bjt.date()
    today_str = today_bjt.strftime("%Y-%m-%d")

    # === 包元数据 ===
    pkg = _PACKAGES_DIR / f"analysis_package_{today_str}.zip"
    pkg_info: dict[str, Any] = {"exists": pkg.exists(), "path": str(pkg)}
    if pkg.exists():
        st = pkg.stat()
        pkg_info["size_kb"] = round(st.st_size / 1024, 1)
        pkg_info["built_at_bjt"] = datetime.fromtimestamp(
            st.st_mtime, tz=timezone.utc,
        ).astimezone(_BJT).strftime("%Y-%m-%d %H:%M BJT")

    # === 校验 a) CSV 新鲜度 ===
    csv_status: list[dict[str, Any]] = []
    gate_a_errors: list[str] = []
    for name, max_lag in _CSV_FRESHNESS_THRESHOLDS.items():
        p = _PROJECT_ROOT_FOR_PACK / name
        item: dict[str, Any] = {"name": name, "threshold_days": max_lag}
        if not p.exists():
            item["latest_date"] = "—"
            item["lag_days"] = None
            item["ok"] = False
            item["reason"] = "文件不存在"
            gate_a_errors.append(f"{name}: 不存在")
        else:
            try:
                df = pd.read_csv(p)
                latest_str = str(df["date"].max())[:10]
                latest = datetime.strptime(latest_str, "%Y-%m-%d").date()
                lag = (today_bjt - latest).days
                item["latest_date"] = latest_str
                item["lag_days"] = lag
                item["ok"] = lag <= max_lag
                if not item["ok"]:
                    item["reason"] = f"lag {lag}d > {max_lag}d"
                    gate_a_errors.append(
                        f"{name}: latest {latest_str} (lag {lag}d > 阈值 {max_lag}d)"
                    )
            except Exception as e:
                item["latest_date"] = "—"
                item["lag_days"] = None
                item["ok"] = False
                item["reason"] = f"读取异常 {type(e).__name__}"
                gate_a_errors.append(f"{name}: {type(e).__name__}: {e}")
        csv_status.append(item)

    # === 校验 b) 新增列非空 ===
    gate_b_errors: list[str] = []
    for csv_name, cols in _NEW_COLS_CHECK.items():
        p = _PROJECT_ROOT_FOR_PACK / csv_name
        if not p.exists():
            continue
        try:
            df = pd.read_csv(p).sort_values("date").reset_index(drop=True)
            if df.empty:
                gate_b_errors.append(f"{csv_name}: 空表")
                continue
            latest_row = df.iloc[-1]
            for col in cols:
                if col not in df.columns:
                    gate_b_errors.append(f"{csv_name}: 缺列 {col}")
                elif pd.isna(latest_row[col]):
                    gate_b_errors.append(f"{csv_name} 最新行 {col} 为空")
        except Exception as e:
            gate_b_errors.append(f"{csv_name}: {type(e).__name__}: {e}")

    # === 校验 c) snapshot 真异常 = 0 ===
    gate_c_errors: list[str] = []
    m = re.search(r"真异常\s+(\d+)", snapshot_md)
    if not m:
        gate_c_errors.append("snapshot 缺真异常统计行")
        anomaly_n = -1
        anomaly_detail = ""
    else:
        anomaly_n = int(m.group(1))
        detail_m = re.search(r"真异常：([^\n]+)", snapshot_md)
        anomaly_detail = detail_m.group(1).strip() if detail_m else ""
        if anomaly_n > 0:
            gate_c_errors.append(f"真异常 = {anomaly_n}: {anomaly_detail}")

    # === 校验 d) BTC 现价锚点 ===
    gate_d_errors: list[str] = []
    snap_price_m = re.search(r"BTC 现价: \$([\d,]+\.?\d*)", snapshot_md)
    csv_1d = _PROJECT_ROOT_FOR_PACK / "btc_swing_deriv_1d.csv"
    if not snap_price_m:
        gate_d_errors.append("snapshot 没找到 BTC 现价行")
    elif not csv_1d.exists():
        pass  # gate_a 已报
    else:
        try:
            snap_price = float(snap_price_m.group(1).replace(",", ""))
            df = pd.read_csv(csv_1d).sort_values("date").reset_index(drop=True)
            csv_close = float(df["close"].iloc[-1])
            rel = abs(snap_price - csv_close) / snap_price
            # 5% 容差(2026-06-12 由 1% 放宽):snapshot 现价 = HTTP 调用
            # 时刻实时值,CSV close = BJT 11:00 cron 截图,同一日内不同时刻。
            # BTC 盘中 2-4% 波动常态,5% 才是数据错乱门槛。
            if rel > 0.05:
                gate_d_errors.append(
                    f"snapshot ${snap_price:.2f} vs CSV ${csv_close:.2f} "
                    f"(差 {rel * 100:.2f}% > 5%)"
                )
        except Exception as e:
            gate_d_errors.append(f"锚点计算异常 {type(e).__name__}: {e}")

    # === 校验 e) snapshot 端点可用(本路由调用了 render,代表 endpoint OK)===
    gate_e_errors: list[str] = []
    if not snapshot_md or len(snapshot_md) < 100:
        gate_e_errors.append("snapshot 内容异常短或空")

    gates = [
        {"name": "a) CSV 新鲜度", "ok": not gate_a_errors, "errors": gate_a_errors},
        {"name": "b) 新增列非空", "ok": not gate_b_errors, "errors": gate_b_errors},
        {"name": "c) snapshot 真异常 = 0", "ok": not gate_c_errors,
         "errors": gate_c_errors, "anomaly_n": anomaly_n,
         "anomaly_detail": anomaly_detail},
        {"name": "d) BTC 现价锚点", "ok": not gate_d_errors, "errors": gate_d_errors},
        {"name": "e) snapshot 端点", "ok": not gate_e_errors, "errors": gate_e_errors},
    ]
    overall_ok = all(g["ok"] for g in gates)

    return {
        "today_str": today_str,
        "now_bjt_str": now_bjt.strftime("%Y-%m-%d %H:%M BJT"),
        "package": pkg_info,
        "csvs": csv_status,
        "gates": gates,
        "overall_ok": overall_ok,
    }


_PACK_STATUS_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BTC 分析包状态 — {today}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
        "Hiragino Sans GB", sans-serif; max-width: 860px; margin: 1.5em auto;
        padding: 0 1em; color: #222; line-height: 1.5; }}
  h1 {{ margin: 0 0 .2em; }}
  h2 {{ margin-top: 1.6em; border-bottom: 1px solid #eee; padding-bottom: .3em; }}
  .date {{ font-size: 1.15em; color: #555; margin-bottom: 1em; }}
  .banner {{ padding: 1em 1.2em; border-radius: 6px; font-size: 1.05em; margin: 1em 0; }}
  .banner.ok {{ background: #d4edda; color: #155724; border-left: 4px solid #28a745; }}
  .banner.fail {{ background: #f8d7da; color: #721c24; border-left: 4px solid #dc3545; }}
  table {{ border-collapse: collapse; width: 100%; margin: .8em 0; }}
  th, td {{ padding: .55em .8em; text-align: left; border-bottom: 1px solid #eee; }}
  th {{ background: #f7f7f7; font-weight: 600; }}
  .ok {{ color: #28a745; font-weight: 600; }}
  .fail {{ color: #dc3545; font-weight: 600; }}
  .pkg-box {{ background: #f7f7f7; padding: .8em 1em; border-radius: 6px; }}
  .download-btn {{
    display: inline-block; padding: .9em 2.2em; margin: 1em 0;
    background: #28a745; color: white !important; text-decoration: none;
    border-radius: 6px; font-size: 1.1em; font-weight: 600;
    box-shadow: 0 2px 4px rgba(0,0,0,.1);
  }}
  .download-btn:hover {{ background: #1e7e34; }}
  .download-btn.disabled {{
    background: #adb5bd; pointer-events: none; opacity: .6; cursor: not-allowed;
  }}
  ul.err {{ margin: .3em 0 .3em 1.2em; color: #721c24; }}
  ul.err li {{ font-family: monospace; font-size: .92em; }}
  footer {{ margin-top: 2em; color: #888; font-size: .88em; border-top: 1px solid #eee;
            padding-top: 1em; }}
  code {{ background: #f0f0f0; padding: .1em .3em; border-radius: 3px; font-size: .9em; }}
</style>
</head>
<body>
  <h1>📦 BTC 分析包状态</h1>
  <div class="date">📅 {today} (BJT)</div>

  {banner}

  <h2>分析包 zip</h2>
  {pkg_html}

  {download_btn}

  <h2>5 项校验</h2>
  <table>
    <thead><tr><th style="width:30%">校验项</th><th style="width:12%">状态</th><th>详情</th></tr></thead>
    <tbody>
      {gates_rows}
    </tbody>
  </table>

  <h2>CSV 新鲜度</h2>
  <table>
    <thead><tr><th>文件</th><th>最新数据</th><th>距今</th><th>阈值</th><th>状态</th></tr></thead>
    <tbody>
      {csv_rows}
    </tbody>
  </table>

  <footer>
    页面生成于 <code>{now_bjt}</code>。
    包由 cron BJT 11:00 自动构建;手动重建 SSH 服务器:
    <code>python3 scripts/refresh_and_build.py</code>。
    <br>下载接口:<code>/api/export/pack/today.zip</code> ·
    snapshot:<code>/api/export/snapshot.md</code>
  </footer>
</body>
</html>
"""


def _render_pack_status_html(status: dict[str, Any]) -> str:
    overall_ok = status["overall_ok"]
    pkg = status["package"]

    # === Banner ===
    if overall_ok and pkg["exists"]:
        banner = (
            '<div class="banner ok">'
            '✅ <strong>今日数据正常,可下载分析包</strong>'
            '</div>'
        )
    elif not overall_ok:
        # 找出哪些 gate 失败
        failed = [g["name"] for g in status["gates"] if not g["ok"]]
        banner = (
            '<div class="banner fail">'
            f'🚨 <strong>今日数据异常,不建议下载</strong> — '
            f'未过校验项:{", ".join(failed)}'
            '</div>'
        )
    else:
        # 校验过但包还没生成
        banner = (
            '<div class="banner fail">'
            '⏳ <strong>校验通过,但今日包尚未生成</strong> — '
            '等 BJT 11:00 cron,或 SSH 服务器手动跑 refresh_and_build.py'
            '</div>'
        )

    # === Package box ===
    if pkg["exists"]:
        pkg_html = (
            '<div class="pkg-box">'
            f'✅ <strong>analysis_package_{status["today_str"]}.zip</strong><br>'
            f'生成时间:{pkg["built_at_bjt"]}<br>'
            f'大小:{pkg["size_kb"]} KB · 7 个文件 (5 CSV + snapshot + README)'
            '</div>'
        )
    else:
        pkg_html = (
            '<div class="pkg-box" style="background:#fdf2f2;">'
            f'⏳ 今日 zip ({status["today_str"]}) 尚未生成'
            '</div>'
        )

    # === Download button ===
    if overall_ok and pkg["exists"]:
        download_btn = (
            '<a href="/api/export/pack/today.zip" class="download-btn">'
            '⬇️ 下载今日分析包 (today.zip)'
            '</a>'
        )
    else:
        download_btn = (
            '<a href="#" class="download-btn disabled" '
            'title="数据异常 / 包未生成,不可下载">'
            '⬇️ 下载今日分析包 (不可用)'
            '</a>'
        )

    # === Gates rows ===
    gate_rows = []
    for g in status["gates"]:
        status_html = (
            '<span class="ok">✅ 通过</span>' if g["ok"]
            else '<span class="fail">❌ 失败</span>'
        )
        if g["ok"]:
            detail = "—"
        else:
            errs = "".join(f"<li>{_esc_html(e)}</li>" for e in g["errors"])
            detail = f'<ul class="err">{errs}</ul>'
        gate_rows.append(
            f'<tr><td>{_esc_html(g["name"])}</td><td>{status_html}</td><td>{detail}</td></tr>'
        )

    # === CSV rows ===
    csv_rows = []
    for c in status["csvs"]:
        latest = c["latest_date"]
        lag = "—" if c["lag_days"] is None else f"{c['lag_days']}d"
        threshold = f"≤ {c['threshold_days']}d"
        st_html = (
            '<span class="ok">✅</span>' if c["ok"]
            else f'<span class="fail">❌ {_esc_html(c.get("reason", "?"))}</span>'
        )
        csv_rows.append(
            f'<tr><td><code>{_esc_html(c["name"])}</code></td><td>{latest}</td>'
            f'<td>{lag}</td><td>{threshold}</td><td>{st_html}</td></tr>'
        )

    return _PACK_STATUS_HTML.format(
        today=status["today_str"],
        now_bjt=status["now_bjt_str"],
        banner=banner,
        pkg_html=pkg_html,
        download_btn=download_btn,
        gates_rows="\n      ".join(gate_rows),
        csv_rows="\n      ".join(csv_rows),
    )


def _esc_html(s: Any) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


@router.get(
    "/pack",
    response_class=HTMLResponse,
    summary="今日分析包状态门户(HTML 网页,含 5 项校验 + 下载按钮)",
)
def get_pack_status_page(request: Request) -> HTMLResponse:
    ctx = request.app.state.ctx
    conn = ctx.conn_factory()
    try:
        conn.row_factory = sqlite3.Row
        snapshot_md = render_factors_markdown(conn)
    finally:
        conn.close()
    status = _build_pack_status(snapshot_md)
    html = _render_pack_status_html(status)
    return HTMLResponse(content=html)


@router.get(
    "/pack/today.zip",
    summary="下载当天 AI 分析包 zip（5 CSV + snapshot + 2 prompts + README）",
)
def get_today_pack() -> FileResponse:
    """指向当天 packages/analysis_package_YYYY-MM-DD.zip(BJT 日期)。

    生成由 scripts/refresh_and_build.py 完成,cron BJT 11:00。
    """
    today_bjt = datetime.now(_BJT).strftime("%Y-%m-%d")
    pkg = _PACKAGES_DIR / f"analysis_package_{today_bjt}.zip"
    if not pkg.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                f"今日 package ({today_bjt}) 还未生成。"
                f"等 BJT 11:00 cron 跑完,或手动跑 "
                f"`python3 scripts/refresh_and_build.py`。"
            ),
        )
    return FileResponse(
        pkg,
        media_type="application/zip",
        filename=f"analysis_package_{today_bjt}.zip",
    )
