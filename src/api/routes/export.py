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

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    now_bjt = datetime.now(_BJT).strftime("%Y-%m-%d %H:%M BJT")

    lines: list[str] = []
    lines.append("# BTC 系统数据快照（供外部 AI 分析）")
    lines.append("")
    lines.append(f"生成时间：{now_utc}  ／  {now_bjt}")
    lines.append("")
    lines.append(
        f"新鲜度总览：总 {total} | 新鲜 {fresh} | ⚠️STALE {stale} | "
        f"❌缺失 {missing} | 事件 {len(events)}"
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
            lines.append(
                f"- {zh_name}: {val_str} ｜ 数据时间: {ts_str} ｜ {tag} ｜ {layer_tag}{detail_str}"
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

from fastapi import APIRouter, Request  # noqa: E402
from fastapi.responses import PlainTextResponse  # noqa: E402

router = APIRouter(prefix="/export", tags=["export"])


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
