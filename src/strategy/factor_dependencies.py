"""src/strategy/factor_dependencies.py — Sprint E Step 1(2026-05-09)

「因子粒度 stale 降级」的依赖映射表 — 每个因子标"依赖哪些数据源",数据
源 stale → 因子 stale,sub-agent prompt 不引用 stale 因子具体数值。

数据源 4 个(沿用 Sprint A 的 EXPECTED_SOURCES):
  - binance_kline:        K 线 1h/4h/1d/1w → price_candles
  - coinglass_derivatives: 资金费率 / OI / 多空比 / 清算 → derivatives_snapshots
  - glassnode_onchain:    MVRV / NUPL / LTH / 实现价格 / 交易所净流 → onchain_metrics
  - fred_macro:           DXY / VIX / SP500 / Nasdaq / US10Y → macro_metrics

# ============================================================
# 设计:三层映射
# ============================================================

(1) **INDICATOR_DEPENDENCIES** — `computed_indicators` 字典里每个 key 的来源
    (来自 src/ai/context_builder.py:682 那个聚合)。
(2) **COMPOSITE_FACTOR_DEPENDENCIES** — state_builder 5 个 composite factor
    的来源(每个 composite 引用多个原始因子,deps = 并集)。
(3) **CARD_PREFIX_DEPENDENCIES** — `card_id` 前缀 → 来源(emitter 已有
    'onchain_*' / 'derivatives_*' / 'price_*' / 'macro_*' / 'composite_*'
    / 'events_*' 等约定;前缀映射可处理大量动态生成的 card_id)。

# ============================================================
# 用法
# ============================================================

  factor_is_stale(card_id_or_key, source_stale_map) → bool
  card_id_to_sources(card_id) → tuple[str, ...]
  get_factor_freshness(card_ids, source_stale_map) → dict[card_id → bool]

source_stale_map 由 src/data/freshness.py 的 compute_all_freshness() 派生:
  {source: f.is_stale for f in compute_all_freshness(conn)}

# ============================================================
# 不确定项 / 留 Sprint F 决定
# ============================================================

- `events_calendar_72h`(L5)是本地 YAML 种子,不依赖网络数据源 — 标 ()
  (空 deps);AI 看 ✅(永远 fresh)
- `extreme_event_flags`(L5)依赖 price_candles + onchain + macro 综合判断,
  保守策略:任一上游 stale → flag 不可信。这里映射成
  ('binance_kline', 'glassnode_onchain', 'fred_macro')
- 已知名字暂没标的 → CARD_PREFIX_DEPENDENCIES 未命中时返回 ()(空 deps,
  默认视为 fresh,留前缀新增时手动补)
"""

from __future__ import annotations

from typing import Iterable


# ============================================================
# Source 常量(对齐 src/data/freshness.py:EXPECTED_SOURCES)
# ============================================================

SRC_BINANCE_KLINE = "binance_kline"
SRC_COINGLASS_DERIV = "coinglass_derivatives"
SRC_GLASSNODE_ONCHAIN = "glassnode_onchain"
SRC_FRED_MACRO = "fred_macro"


# ============================================================
# (1) INDICATOR_DEPENDENCIES — `computed_indicators` 每 key 的来源
#     来自 src/ai/context_builder.py:682(每条 key 对应一行 grep 验证)
# ============================================================

INDICATOR_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    # ---- EMA(K 线 1d / 4h)→ binance_kline ----
    "ema_20_1d_current": (SRC_BINANCE_KLINE,),
    "ema_50_1d_current": (SRC_BINANCE_KLINE,),
    "ema_200_1d_current": (SRC_BINANCE_KLINE,),
    "ema_20_4h_current": (SRC_BINANCE_KLINE,),
    "ema_50_4h_current": (SRC_BINANCE_KLINE,),
    "ema_200_4h_current": (SRC_BINANCE_KLINE,),
    "ema_20_1d_slope_5d": (SRC_BINANCE_KLINE,),
    "ema_50_1d_slope_5d": (SRC_BINANCE_KLINE,),
    "ema_50_slope_30d": (SRC_BINANCE_KLINE,),
    # ---- ADX / ATR / 价格位置(K 线 1d)----
    "adx_14_1d_current": (SRC_BINANCE_KLINE,),
    "adx_14_1d_5d_avg": (SRC_BINANCE_KLINE,),
    "atr_14_1d_current": (SRC_BINANCE_KLINE,),
    "atr_180d_percentile": (SRC_BINANCE_KLINE,),
    "price_position_in_90d_range": (SRC_BINANCE_KLINE,),
    "current_close": (SRC_BINANCE_KLINE,),
    "max_drawdown_60d_pct": (SRC_BINANCE_KLINE,),
    "swing_5_recent": (SRC_BINANCE_KLINE,),
    "swing_high_3_recent": (SRC_BINANCE_KLINE,),
    "swing_low_3_recent": (SRC_BINANCE_KLINE,),
    # ---- LTH/STH(Glassnode 一手)→ glassnode_onchain ----
    "lth_realized_price_current": (SRC_GLASSNODE_ONCHAIN,),
    "sth_realized_price_current": (SRC_GLASSNODE_ONCHAIN,),
    "lth_realized_price": (SRC_GLASSNODE_ONCHAIN,),
    "sth_realized_price": (SRC_GLASSNODE_ONCHAIN,),
    "lth_mvrv": (SRC_GLASSNODE_ONCHAIN,),
    "sth_mvrv": (SRC_GLASSNODE_ONCHAIN,),
    # ---- 交易所净流(Glassnode)----
    "exchange_net_flow_30d": (SRC_GLASSNODE_ONCHAIN,),
    "exchange_net_flow_30d_sum": (SRC_GLASSNODE_ONCHAIN,),
    "exchange_net_flow_30d_max_outflow": (SRC_GLASSNODE_ONCHAIN,),
    # ---- 衍生品(CoinGlass)→ coinglass_derivatives ----
    "funding_rate_current": (SRC_COINGLASS_DERIV,),
    "funding_rate_z_score_90d": (SRC_COINGLASS_DERIV,),
    "funding_rate_30d_max": (SRC_COINGLASS_DERIV,),
    "open_interest_current": (SRC_COINGLASS_DERIV,),
    "open_interest_z_score_90d": (SRC_COINGLASS_DERIV,),
    # ---- 宏观(FRED)→ fred_macro(L5 用 computed_macro_indicators,
    #      具体 key 在 macro_feats,运行时动态;此处只覆盖少数已知名)----
    "dxy_current": (SRC_FRED_MACRO,),
    "vix_current": (SRC_FRED_MACRO,),
    "sp500_current": (SRC_FRED_MACRO,),
    "nasdaq_current": (SRC_FRED_MACRO,),
    "us10y_current": (SRC_FRED_MACRO,),
}


# ============================================================
# (2) COMPOSITE_FACTOR_DEPENDENCIES — state_builder 5 个 composite
# ============================================================

COMPOSITE_FACTOR_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "truth_trend":    (SRC_BINANCE_KLINE,),                       # K 线趋势真实性
    "band_position":  (SRC_BINANCE_KLINE,),                       # 90d 价格波段位置
    "cycle_position": (SRC_GLASSNODE_ONCHAIN,),                   # MVRV / NUPL / LTH
    "crowding":       (SRC_COINGLASS_DERIV,),                     # 资金费率 / OI / 多空比
    "macro_headwind": (SRC_FRED_MACRO,),                          # DXY / VIX
    "event_risk":     (),                                          # 本地 yaml,无数据源
}


# ============================================================
# (3) CARD_PREFIX_DEPENDENCIES — emitter card_id 前缀 → 来源
# ============================================================

CARD_PREFIX_DEPENDENCIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("onchain_",     (SRC_GLASSNODE_ONCHAIN,)),
    ("derivatives_", (SRC_COINGLASS_DERIV,)),
    ("price_tech_",  (SRC_BINANCE_KLINE,)),
    ("price_",       (SRC_BINANCE_KLINE,)),
    ("kline_",       (SRC_BINANCE_KLINE,)),
    ("macro_",       (SRC_FRED_MACRO,)),
    ("events_",      ()),                                          # 本地 yaml
    # composite_<name>_<date> 走 _composite_card_to_sources 单独处理
)


# ============================================================
# Per-layer 关心的 indicator key 子集(prompt 注入时用,缺失时全枚举)
# 来自 src/ai/agents/prompts/l*.txt 的 prompt schema 描述 + context_builder
# ============================================================

LAYER_RELEVANT_INDICATORS: dict[int, tuple[str, ...]] = {
    1: (
        # L1 Regime:K 线趋势 / EMA 排列 / ADX / ATR 波动率
        "ema_20_1d_current", "ema_50_1d_current", "ema_200_1d_current",
        "ema_20_4h_current", "ema_50_4h_current", "ema_200_4h_current",
        "adx_14_1d_current", "adx_14_1d_5d_avg",
        "atr_14_1d_current", "atr_180d_percentile",
        "price_position_in_90d_range",
        "current_close", "max_drawdown_60d_pct",
    ),
    2: (
        # L2 方向结构:L1 全部 + LTH/STH 估值 + 交易所净流(链上侧)
        "ema_20_1d_current", "ema_50_1d_current", "ema_200_1d_current",
        "current_close",
        "swing_5_recent", "swing_high_3_recent", "swing_low_3_recent",
        "lth_realized_price_current", "sth_realized_price_current",
        "lth_mvrv", "sth_mvrv",
        "exchange_net_flow_30d_sum",
    ),
    3: (
        # L3 机会执行:衍生于 L1+L2,不直接消费 indicators
    ),
    4: (
        # L4 风险失效:衍生品 + 链上 net flow + ATR
        "funding_rate_current", "funding_rate_z_score_90d", "funding_rate_30d_max",
        "open_interest_current", "open_interest_z_score_90d",
        "exchange_net_flow_30d_sum", "exchange_net_flow_30d_max_outflow",
        "atr_14_1d_current",
    ),
    5: (
        # L5 宏观:DXY / VIX 等(具体 key 由 macro_feats 决定;此处列已知)
        "dxy_current", "vix_current", "sp500_current",
        "nasdaq_current", "us10y_current",
    ),
}


# ============================================================
# Public helpers
# ============================================================

def card_id_to_sources(card_id: str) -> tuple[str, ...]:
    """Card_id ('onchain_mvrv_z_20260508' / 'composite_truth_trend_...' / ...)
    映射到依赖数据源元组。

    顺序:
      1. composite_<name>_<date> → COMPOSITE_FACTOR_DEPENDENCIES
      2. CARD_PREFIX_DEPENDENCIES 前缀匹配
      3. INDICATOR_DEPENDENCIES 完全匹配(裸 key 名,无前缀)
      4. 未命中 → ()(默认 fresh,留警告)
    """
    if not card_id:
        return ()
    if card_id.startswith("composite_"):
        body = card_id[len("composite_"):]
        # 剥末尾 _YYYYMMDD(8 位)
        if len(body) > 9 and body[-9] == "_" and body[-8:].isdigit():
            body = body[:-9]
        return COMPOSITE_FACTOR_DEPENDENCIES.get(body, ())
    for prefix, sources in CARD_PREFIX_DEPENDENCIES:
        if card_id.startswith(prefix):
            return sources
    if card_id in INDICATOR_DEPENDENCIES:
        return INDICATOR_DEPENDENCIES[card_id]
    return ()


def factor_is_stale(
    card_id_or_key: str,
    source_stale_map: dict[str, bool],
) -> bool:
    """根据 card_id / indicator key 算依赖,任一 source stale → True。
    无依赖 (()) → False(本地数据 / 未知前缀视为 fresh)。
    """
    sources = card_id_to_sources(card_id_or_key)
    if not sources:
        sources = INDICATOR_DEPENDENCIES.get(card_id_or_key, ())
    if not sources:
        return False
    return any(source_stale_map.get(s, False) for s in sources)


def get_factor_freshness(
    card_ids: Iterable[str],
    source_stale_map: dict[str, bool],
) -> dict[str, bool]:
    """批量算 stale 状态;返回 {card_id: is_stale}。"""
    return {
        cid: factor_is_stale(cid, source_stale_map)
        for cid in card_ids
    }


def get_layer_factor_freshness(
    layer_id: int,
    source_stale_map: dict[str, bool],
) -> list[tuple[str, bool, tuple[str, ...]]]:
    """给一层(1-5),返回该层关心的每个 indicator 的 (key, is_stale, sources)。
    用于 sub-agent prompt 注入「因子状态」段。"""
    keys = LAYER_RELEVANT_INDICATORS.get(layer_id, ())
    out: list[tuple[str, bool, tuple[str, ...]]] = []
    for key in keys:
        sources = INDICATOR_DEPENDENCIES.get(key, ())
        is_stale = any(source_stale_map.get(s, False) for s in sources)
        out.append((key, is_stale, sources))
    return out


def fresh_ratio_for_layer(
    layer_id: int,
    source_stale_map: dict[str, bool],
) -> float:
    """该层 fresh 因子覆盖度(0.0 - 1.0)。L3 无直接 indicators → 返 1.0
    (L3 health 由上游 L1+L2 决定,本函数返 1 让 orchestrator 退回上游联动)。"""
    rows = get_layer_factor_freshness(layer_id, source_stale_map)
    if not rows:
        return 1.0
    fresh = sum(1 for _, is_stale, _ in rows if not is_stale)
    return fresh / len(rows)
