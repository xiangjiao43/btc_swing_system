"""factor_picker.py — Sprint 1.5m:从完整 strategy_state 中挑出 3-5 个最有
信号的关键因子,供 no_opportunity_narrator 8 场景模板生成交易员叙事。

设计原则(对齐建模 §2.5 双轨原则):
- 100% 规则化打分,**禁 AI**
- 输入是 state(45 因子 + 6 组合因子 + 5 层证据),输出是排序后的 top-N 因子
- 每个 picked 因子带 current_value(格式化)+ context(历史位置)+
  signal_strength(0-100 排序用)+ interpretation(1 句解读)

挑选优先级(高→低):
  1. 极端分位(top/bottom 10-15%)— signal 80-100
  2. 触发建模阈值的 composite(crowding=high / event_risk=high) — signal 70-90
  3. 大幅 24h 变动(LSR/OI/funding abs > 10-15%) — signal 60-80
  4. 因子共振或矛盾(funding+LSR 共同偏空) — signal 60-80
  5. 兜底:基础市场快照(BTC 价格 / ath_drawdown) — signal 30-50
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ============================================================
# 公共 API
# ============================================================

def pick_key_factors(
    state: dict[str, Any],
    n: int = 5,
    scenario: Optional[str] = None,
) -> list[dict[str, Any]]:
    """从 state 中挑出 top-N 最有信号的因子。

    Args:
      state: 完整 strategy_state(含 factor_cards / composite_factors /
             evidence_reports / next_events_by_type)
      n: 期望返回数量,默认 5。少于 n 个有效信号时按实际数量返回
      scenario: 可选场景 hint(如 "permission_restricted" / "position_cap_zero"),
                让 picker 偏好选触发当前场景的因子。None = 通用挑选

    Returns:
      list of:
        {
          "category": "derivatives" | "onchain" | "macro" | "structure" | "composite",
          "name": str,
          "current_value": str,           # 格式化(含 % / B 等单位)
          "context": str,                 # 历史位置,可空
          "signal_strength": int 0-100,
          "interpretation": str,          # 1 句解读
          "evidence_ref": str | None,     # 关联 card_id,可 None
        }
      按 signal_strength 降序,长度 = min(n, available)
    """
    candidates: list[dict[str, Any]] = []

    # 来源 1:factor_cards(45 个原始因子)
    cards = state.get("factor_cards") or state.get("evidence_cards") or []
    for c in cards:
        if not isinstance(c, dict):
            continue
        scored = _score_factor_card(c)
        if scored is not None:
            candidates.append(scored)

    # 来源 2:composite_factors(6 个组合)
    composite = state.get("composite_factors") or {}
    for name, cf in composite.items():
        if not isinstance(cf, dict):
            continue
        scored = _score_composite_factor(name, cf)
        if scored is not None:
            candidates.append(scored)

    # 场景偏好加权(scenario 提示让 picker 上推某些类别的 signal)
    if scenario:
        for cand in candidates:
            cand["signal_strength"] = _adjust_for_scenario(
                cand, scenario,
            )

    # 按 signal 降序
    candidates.sort(key=lambda c: c["signal_strength"], reverse=True)

    # 兜底:全部 signal < 30 → 至少返回 3 条基础市场快照
    if not candidates or all(c["signal_strength"] < 30 for c in candidates):
        baseline = _baseline_market_snapshot(state)
        for b in baseline:
            if not any(c["name"] == b["name"] for c in candidates):
                candidates.append(b)
        candidates.sort(key=lambda c: c["signal_strength"], reverse=True)

    return candidates[:n]


# ============================================================
# 评分:factor_cards
# ============================================================

# 按因子名归属类别(从 factor_card_emitter.py 的 name_cn 反查)
_DERIVATIVES_NAMES = {
    "Binance 资金费率 · 当前", "资金费率 7 日均", "资金费率 · 30 日分位",
    "资金费率 Z 分数 · 90 日", "全交易所资金费率",
    "未平仓合约 · 当前", "未平仓合约 24h 变化",
    "Binance 大户多空比", "Binance 多空比 24h 变化",
    "Binance 24h 清算总额",
}
_ONCHAIN_NAMES = {
    "MVRV Z 分数", "未实现盈亏比例 NUPL", "长期持有者供应 90 日变化",
    "交易所净流入 7 日均", "距 ATH 跌幅", "储备风险 Reserve Risk",
    "SOPR", "SOPR 调整版", "Puell 倍数",
}
_STRUCTURE_NAMES = {
    "ADX-14(1D)", "ATR 180 日分位", "多周期方向一致性",
    "BTC 现价",
}
_MACRO_NAMES = {
    "美元指数 DXY 20 日变化", "VIX 恐慌指数",
    "美国 10 年期国债收益率 30 日变化", "纳指 20 日变化",
    "BTC-纳指 60 日相关性", "BTC-黄金 60 日相关性",
}


def _score_factor_card(card: dict[str, Any]) -> Optional[dict[str, Any]]:
    """给一张 factor_card 打 signal 分;无 current_value 或太普通 → None。"""
    name = card.get("name") or card.get("metric_name") or card.get("card_id")
    val = card.get("current_value")
    unit = card.get("value_unit") or ""
    if name is None or val is None:
        return None

    # 类别判定
    cat_raw = str(card.get("category") or "")
    if cat_raw == "derivatives" or name in _DERIVATIVES_NAMES:
        category = "derivatives"
    elif cat_raw == "onchain" or name in _ONCHAIN_NAMES:
        category = "onchain"
    elif cat_raw == "macro" or name in _MACRO_NAMES:
        category = "macro"
    elif cat_raw == "price_structure" or name in _STRUCTURE_NAMES:
        category = "structure"
    else:
        category = cat_raw or "other"

    # 数值 + 上下文格式化
    val_str = _format_value(val, unit)
    context = _build_context(card)

    # 评分:命中信号规则 → signal 60-95;否则 baseline 30-45
    signal, interpretation = _signal_for_named_factor(name, val, card)

    return {
        "category": category,
        "name": str(name),
        "current_value": val_str,
        "context": context,
        "signal_strength": signal,
        "interpretation": interpretation,
        "evidence_ref": card.get("card_id"),
    }


def _signal_for_named_factor(
    name: str, val: Any, card: dict[str, Any],
) -> tuple[int, str]:
    """按因子名给打分 + 写一句解读。返回 (signal, interpretation)。"""
    try:
        v = float(val)
    except (TypeError, ValueError):
        return 35, ""

    # ------ 衍生品 ------
    if "资金费率 · 30 日分位" in name or "Funding Rate 30d Percentile" in name:
        # 分位极端(≤ 15 或 ≥ 85 算极端 — 实测 11% 恰在边缘)
        if v <= 15:
            return 90, f"funding 30d 分位 {v:.0f},深度负费率,空头杠杆主导"
        if v >= 85:
            return 90, f"funding 30d 分位 {v:.0f},费率高位,多头拥挤"
        if v <= 25 or v >= 75:
            return 60, f"funding 30d 分位 {v:.0f},偏向{'空' if v <= 25 else '多'}"
        return 30, ""

    if "Binance 资金费率 · 当前" in name or name == "Binance 资金费率 · 当前":
        if v <= -0.3:
            return 80, f"funding {v:.4f}%,深度负费率,空头持仓成本高"
        if v >= 0.3:
            return 80, f"funding {v:.4f}%,深度正费率,多头持仓成本高"
        if abs(v) >= 0.1:
            return 55, f"funding {v:.4f}%,{'空' if v < 0 else '多'}头方向"
        return 30, ""

    if "未平仓合约 24h 变化" in name:
        if abs(v) >= 5:
            return 80, f"OI 24h {v:+.2f}%,合约持仓快速{'累积' if v > 0 else '收缩'}"
        if abs(v) >= 2:
            return 55, f"OI 24h {v:+.2f}%,持仓{'扩张' if v > 0 else '收缩'}中"
        return 30, ""

    if "多空比 24h 变化" in name:
        if abs(v) >= 10:
            return 85, f"LSR 24h {v:+.2f}%,大户立场{'转多' if v > 0 else '转空'}剧烈变化"
        if abs(v) >= 5:
            return 60, f"LSR 24h {v:+.2f}%,大户立场偏移"
        return 30, ""

    if "Binance 大户多空比" == name or "Top Long/Short Ratio" in name:
        if v >= 1.2 or v <= 0.85:
            return 75, f"LSR {v:.3f},大户{'偏多' if v >= 1 else '偏空'}显著"
        return 35, ""

    if "Binance 24h 清算总额" in name or "清算" in name:
        if v >= 100_000_000:
            return 75, f"24h 清算 {v/1e6:.1f}M USD,大额爆仓潮"
        if v >= 50_000_000:
            return 55, f"24h 清算 {v/1e6:.1f}M USD,清算放量"
        return 30, ""

    # ------ 链上 ------
    if "MVRV Z 分数" in name or "MVRV" in name:
        if v >= 5 or v <= 0.1:
            return 85, f"MVRV-Z {v:.2f},{'顶部' if v >= 5 else '底部'}极端区"
        if v >= 3 or v <= 0.5:
            return 60, f"MVRV-Z {v:.2f},偏{'高' if v >= 3 else '低'}"
        return 35, ""

    if "NUPL" in name:
        if v >= 0.7 or v <= 0:
            return 80, f"NUPL {v:.3f},{'盈利极致' if v >= 0.7 else '亏损区'}"
        if v >= 0.5 or v <= 0.1:
            return 55, f"NUPL {v:.3f},{'高盈利' if v >= 0.5 else '低盈利'}"
        return 30, ""

    if "SOPR" in name:
        if v < 0.99:
            return 80, f"SOPR {v:.4f} < 1,市场在割肉(实质性抛压)"
        if v > 1.05:
            return 75, f"SOPR {v:.4f} > 1.05,普遍盈利兑现"
        if v < 1:
            return 50, f"SOPR {v:.4f},接近盈亏平衡"
        return 30, ""

    if "长期持有者供应 90 日变化" in name or "LTH" in name:
        if v <= -2:
            return 75, f"LTH-90d {v:+.2f}%,长期持有者在卖出(分发期)"
        if v >= 2:
            return 65, f"LTH-90d {v:+.2f}%,长期持有者在累积"
        return 35, ""

    if "交易所净流入" in name:
        if v >= 5000:
            return 70, f"交易所净流入 {v:.0f} BTC,可能预示抛压"
        if v <= -5000:
            return 65, f"交易所净流出 {-v:.0f} BTC,囤币意愿"
        return 30, ""

    if "距 ATH 跌幅" in name:
        if v <= -50:
            return 65, f"距 ATH {v:.1f}%,深度回撤区"
        if v >= -10:
            return 65, f"距 ATH {v:.1f}%,接近 ATH 高位"
        return 35, ""

    # ------ 结构 ------
    if "ADX-14" in name:
        if v >= 30:
            return 65, f"ADX {v:.1f},强趋势成立"
        if v <= 15:
            return 60, f"ADX {v:.1f},无趋势震荡"
        return 30, ""

    if "ATR 180 日分位" in name:
        if v >= 80 or v <= 20:
            return 60, f"ATR-180d 分位 {v:.0f},波动{'高位' if v >= 80 else '低位'}"
        return 30, ""

    if name == "BTC 现价" or "BTC 现价" in name:
        # 价格永远要展示,baseline 信号
        return 40, f"BTC 当前 {v:,.2f} USDT"

    # ------ 宏观 ------
    if "DXY" in name:
        if abs(v) >= 2:
            return 60, f"DXY 20d {v:+.2f}%,美元{'走强' if v > 0 else '走弱'}"
        return 30, ""

    if "VIX" in name:
        if v >= 25:
            return 65, f"VIX {v:.1f},风险情绪紧张"
        if v <= 15:
            return 50, f"VIX {v:.1f},市场较平静"
        return 30, ""

    if "BTC-纳指 60 日相关性" in name:
        if abs(v) >= 0.6:
            return 55, f"BTC-纳指相关 {v:+.2f},{'同步' if v > 0 else '反向'}强"
        return 30, ""

    # 兜底:有数值就给基础分
    return 35, ""


def _format_value(val: Any, unit: str) -> str:
    """把 current_value + unit 格式化成展示字符串。"""
    try:
        v = float(val)
        if abs(v) >= 1_000_000_000:
            return f"{v/1e9:.2f}B {unit}".strip()
        if abs(v) >= 1_000_000:
            return f"{v/1e6:.2f}M {unit}".strip()
        if abs(v) >= 1000:
            return f"{v:,.2f} {unit}".strip()
        if abs(v) < 0.001:
            return f"{v:.6f} {unit}".strip()
        return f"{v:.4f} {unit}".strip().replace(".0000", "")
    except (TypeError, ValueError):
        return f"{val} {unit}".strip()


def _build_context(card: dict[str, Any]) -> str:
    """从 card 字段抽 7d 均 / 30d 分位 / 90d Z 等历史位置(若有)。"""
    parts: list[str] = []
    for key, label in (
        ("p7d_avg", "7d 均"),
        ("p30d_percentile", "30d 分位"),
        ("p90d_z", "90d Z"),
        ("z_score", "Z"),
    ):
        v = card.get(key)
        if v is not None:
            try:
                parts.append(f"{label} {float(v):.2f}")
            except (TypeError, ValueError):
                continue
    return ", ".join(parts)


# ============================================================
# 评分:composite_factors
# ============================================================

def _score_composite_factor(
    name: str, cf: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """给 6 个组合因子打分。"""
    if name == "cycle_position":
        cycle = cf.get("cycle_position")
        conf = cf.get("cycle_confidence")
        if cycle in ("distribution", "accumulation"):
            return _composite_dict(
                name, f"{cycle} (信心 {conf})",
                signal=80,
                interpretation=f"长周期位置 {cycle},{'顶部分发' if cycle == 'distribution' else '底部累积'}",
            )
        if cycle in ("late_bull", "early_bear"):
            return _composite_dict(
                name, f"{cycle}", signal=60,
                interpretation=f"长周期位置 {cycle},{'牛尾' if 'bull' in cycle else '熊初'}",
            )
        return _composite_dict(name, f"{cycle}", signal=35,
                               interpretation=f"长周期 {cycle},中性区")

    if name == "crowding":
        score = cf.get("crowding_score") or cf.get("score")
        level = cf.get("crowding_level") or cf.get("level")
        try:
            s = float(score) if score is not None else 0
        except (TypeError, ValueError):
            s = 0
        if level == "high" or s >= 11:
            return _composite_dict(
                name, f"{level} (评分 {s})", signal=85,
                interpretation=f"拥挤度 {level} 档,触发 cap × 0.7 收紧",
            )
        if level == "elevated" or s >= 7:
            return _composite_dict(
                name, f"{level}", signal=55,
                interpretation=f"拥挤度 {level},接近高档",
            )
        return _composite_dict(name, f"{level}", signal=30,
                               interpretation=f"拥挤度 {level},正常")

    if name == "macro_headwind":
        score = cf.get("headwind_score") or cf.get("score")
        level = cf.get("macro_headwind_level") or cf.get("level")
        try:
            s = float(score) if score is not None else 0
        except (TypeError, ValueError):
            s = 0
        if s <= -5 or level == "strong":
            return _composite_dict(
                name, f"{level} (评分 {s})", signal=80,
                interpretation=f"宏观逆风 {level} 档,DXY/US10Y/VIX 共同压制",
            )
        if s <= -2 or level == "mild":
            return _composite_dict(
                name, f"{level} (评分 {s})", signal=50,
                interpretation=f"宏观 {level} 逆风",
            )
        return _composite_dict(name, f"{level}", signal=30,
                               interpretation=f"宏观 {level}")

    if name == "event_risk":
        score = cf.get("event_risk_score") or cf.get("score")
        level = cf.get("event_risk_level") or cf.get("level")
        try:
            s = float(score) if score is not None else 0
        except (TypeError, ValueError):
            s = 0
        if level == "high" or s >= 8:
            return _composite_dict(
                name, f"{level} (评分 {s})", signal=80,
                interpretation=f"事件风险 {level} 档,72h 内有重大事件",
            )
        if s >= 4:
            return _composite_dict(name, f"{level}", signal=50,
                                   interpretation=f"事件风险 {level}")
        return _composite_dict(name, f"{level}", signal=30,
                               interpretation=f"事件风险 {level}")

    if name == "truth_trend":
        tt = cf.get("truth_trend") or cf.get("trend")
        score = cf.get("trend_score") or cf.get("score")
        if tt == "true_trend":
            return _composite_dict(name, f"{tt}", signal=70,
                                   interpretation="真趋势确立(成交量/广度同步)")
        if tt == "false_breakout":
            return _composite_dict(name, f"{tt}", signal=70,
                                   interpretation="假突破识别(量价背离)")
        return _composite_dict(name, f"{tt}", signal=30,
                               interpretation=f"真假趋势 {tt}")

    if name == "band_position":
        bp = cf.get("band_position") or cf.get("position")
        pct = cf.get("band_pct")
        if bp == "upper":
            return _composite_dict(name, f"{bp}", signal=55,
                                   interpretation="价格接近通道上沿")
        if bp == "lower":
            return _composite_dict(name, f"{bp}", signal=55,
                                   interpretation="价格接近通道下沿")
        return _composite_dict(name, f"{bp}", signal=30,
                               interpretation=f"通道位置 {bp}")

    return None


def _composite_dict(
    name: str, value_str: str, signal: int, interpretation: str,
) -> dict[str, Any]:
    return {
        "category": "composite",
        "name": name,
        "current_value": value_str,
        "context": "",
        "signal_strength": signal,
        "interpretation": interpretation,
        "evidence_ref": None,
    }


# ============================================================
# 场景偏好加权
# ============================================================

def _adjust_for_scenario(cand: dict[str, Any], scenario: str) -> int:
    """让 scenario 提示影响排序,但不强行注入(仍按数据情况)。"""
    s = int(cand.get("signal_strength") or 0)
    name = cand.get("name") or ""
    cat = cand.get("category") or ""

    if scenario == "permission_restricted":
        # 优先选触发 permission 收紧的因子
        if name in ("crowding", "macro_headwind", "event_risk"):
            return min(100, s + 15)
    if scenario == "position_cap_zero":
        # 优先选 risk / crowding / macro / event 的高档项
        if name in ("crowding", "macro_headwind", "event_risk"):
            return min(100, s + 20)
    if scenario == "extreme_event":
        if name == "event_risk" or cat == "macro":
            return min(100, s + 20)
    if scenario == "fallback_degraded":
        # 数据不可信时不靠 picker 选指标,降权所有 candidate
        return max(0, s - 30)
    if scenario == "cold_start":
        # 冷启动期信号都不可靠,降权
        return max(0, s - 20)
    return s


# ============================================================
# 兜底:基础市场快照
# ============================================================

def _baseline_market_snapshot(state: dict[str, Any]) -> list[dict[str, Any]]:
    """全部因子都中性时,给个基础快照(BTC 价 / cycle / crowding)。"""
    out: list[dict[str, Any]] = []
    cards = state.get("factor_cards") or []
    for c in cards:
        if not isinstance(c, dict):
            continue
        name = c.get("name") or ""
        if "BTC 现价" in name and c.get("current_value") is not None:
            out.append({
                "category": "structure",
                "name": "BTC 现价",
                "current_value": _format_value(
                    c.get("current_value"), c.get("value_unit") or "",
                ),
                "context": "",
                "signal_strength": 40,
                "interpretation": "市场快照",
                "evidence_ref": c.get("card_id"),
            })
            break

    composite = state.get("composite_factors") or {}
    for name in ("cycle_position", "crowding", "macro_headwind"):
        cf = composite.get(name)
        if isinstance(cf, dict):
            scored = _score_composite_factor(name, cf)
            if scored is not None:
                # 强制设到 baseline 区
                scored["signal_strength"] = max(scored["signal_strength"], 32)
                out.append(scored)

    return out
