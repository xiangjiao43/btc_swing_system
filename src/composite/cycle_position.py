"""
cycle_position.py — CyclePosition 组合因子(建模 §3.8.4,v1.2 九档完整化)

输入:
  - onchain.mvrv_z_score:      time-indexed pd.Series
  - onchain.nupl:              同
  - onchain.lth_supply:        同(算 90d 变化百分比)
  - klines_1d:                 pd.DataFrame(算 ath_drawdown_pct)
  - state_history_dao:         optional, 查 last_stable(Sprint 1.6 返回 None)

决策流程:
  1. 三主指标(mvrv_z, nupl, lth_90d_chg)各自按 thresholds.yaml
     cycle_position_decision.bands 匹配候选档
  2. 每个候选档检查 aux 条件(时间 / 跌幅)
  3. 通过 aux 的候选进入投票池
  4. 三票一致 → conf=0.85
  5. 两票一致 → conf=0.60
  6. 池空或全不一致 → unclear + conf=0.30(M17:不允许维持上一次档位)

output(对齐 schemas.yaml cycle_position_output):
  cycle_position, cycle_confidence, voting_pool, voting_breakdown,
  aux_conditions_passed, last_stable_cycle_position,
  halving_window_active, mvrv_z_stabilizing_check_result
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import pandas as pd

from ._base import CompositeFactorBase, reduce_metadata


logger = logging.getLogger(__name__)


# 九档顺序(与 schemas.yaml cycle_position enum 对齐)
_BAND_ORDER = [
    "accumulation", "early_bull", "mid_bull", "late_bull",
    "distribution", "early_bear", "mid_bear", "late_bear",
    "unclear",
]


class CyclePositionFactor(CompositeFactorBase):
    name = "cycle_position"
    thresholds_key = "cycle_position_decision"

    def compute(self, context: dict[str, Any]) -> dict[str, Any]:
        onchain = context.get("onchain") or {}
        klines_1d: Optional[pd.DataFrame] = context.get("klines_1d")
        state_history_dao = context.get("state_history_dao")

        mvrv_z_series = onchain.get("mvrv_z_score")
        nupl_series = onchain.get("nupl")
        lth_series = onchain.get("lth_supply")

        # ---- 核心值提取 ----
        mvrv_z = _last_value(mvrv_z_series)
        nupl = _last_value(nupl_series)
        lth_90d_chg = _pct_change_90d(lth_series)
        ath_drawdown = _ath_drawdown_pct(klines_1d)

        # 诊断结构
        diagnostics = {
            "mvrv_z": mvrv_z, "nupl": nupl,
            "lth_90d_chg": lth_90d_chg, "ath_drawdown": ath_drawdown,
        }

        # ---- 配置读取 ----
        bands_cfg: dict[str, Any] = self.scoring_config.get("bands", {})
        voting_cfg = self.scoring_config.get("voting") or {}
        three_agree = float(voting_cfg.get("three_agree_confidence", 0.85))
        two_agree = float(voting_cfg.get("two_agree_confidence", 0.60))
        empty_pool = float(voting_cfg.get("empty_pool_confidence", 0.30))

        # ---- 各指标近期趋势(用于匹配 bands 里的 trend 约束)----
        # bands 里 early_bear / mid_bear 等带 trend: down 的档位,要求该
        # 指标确实在下行。这里简化:最近 N 天 delta 均值的符号。
        mvrv_trend = _series_trend(mvrv_z_series, lookback=30)
        nupl_trend = _series_trend(nupl_series, lookback=30)
        lth_trend = _series_trend(lth_series, lookback=30)

        # ---- 候选匹配(传入 trend 供 bands 的 trend 约束过滤)----
        mvrv_candidates = _match_bands(mvrv_z, "mvrv_z", bands_cfg, trend=mvrv_trend)
        nupl_candidates = _match_bands(nupl, "nupl", bands_cfg, trend=nupl_trend)
        lth_candidates = _match_bands(lth_90d_chg, "lth_90d_chg", bands_cfg, trend=lth_trend)

        # late_bear 的"未企稳"检查
        stabilizing_check_result: Optional[bool] = None
        stabilizing_need = bands_cfg.get("late_bear", {}).get(
            "trend_stabilizing_check_required", False
        )
        if stabilizing_need:
            stabilizing_check_result = _is_mvrv_z_stabilizing(mvrv_z_series)
            # "未企稳" 才保留 late_bear 候选;已企稳则从 3 个候选集里剔除
            if stabilizing_check_result is True:  # stabilized → remove late_bear
                mvrv_candidates = [b for b in mvrv_candidates if b != "late_bear"]
                nupl_candidates = [b for b in nupl_candidates if b != "late_bear"]
                lth_candidates = [b for b in lth_candidates if b != "late_bear"]

        # ---- 辅助条件检查(每档 aux):筛候选 ----
        aux_passed: dict[str, dict[str, bool]] = {}
        for cand_set_name, cand_list in [
            ("mvrv_z", mvrv_candidates),
            ("nupl", nupl_candidates),
            ("lth_90d_chg", lth_candidates),
        ]:
            aux_passed[cand_set_name] = {}
            for b in list(cand_list):
                ok = _aux_passes(b, bands_cfg, ath_drawdown=ath_drawdown,
                                 state_history_dao=state_history_dao)
                aux_passed[cand_set_name][b] = ok

        def _filter(cands: list[str], set_name: str) -> list[str]:
            return [b for b in cands if aux_passed[set_name].get(b, True)]

        mvrv_candidates = _filter(mvrv_candidates, "mvrv_z")
        nupl_candidates = _filter(nupl_candidates, "nupl")
        lth_candidates = _filter(lth_candidates, "lth_90d_chg")

        # 建模 §3.8.4 的投票规则(band 级计票):
        # 对每个候选 band,统计有多少个指标把它列入候选集。
        # 三指标全列 → three_agree;两指标列 → two_agree;其他 → unclear。
        per_indicator: dict[str, set[str]] = {
            "mvrv_z": set(mvrv_candidates),
            "nupl": set(nupl_candidates),
            "lth_90d_chg": set(lth_candidates),
        }
        all_candidate_bands: set[str] = set().union(*per_indicator.values())

        band_counts: dict[str, int] = {
            b: sum(1 for s in per_indicator.values() if b in s)
            for b in all_candidate_bands
        }

        # ---- 投票决议 ----
        cycle: str
        conf: float
        if not band_counts:
            cycle = "unclear"
            conf = empty_pool
        else:
            # 取票数最高的 band;并列时按 _BAND_ORDER 取最早(更保守)
            max_count = max(band_counts.values())
            top_bands = [b for b, c in band_counts.items() if c == max_count]
            top_band = next((b for b in _BAND_ORDER if b in top_bands), top_bands[0])
            if max_count == 3:
                cycle, conf = top_band, three_agree
            elif max_count == 2:
                cycle, conf = top_band, two_agree
            else:
                # 每 band 最多 1 票(三指标各投一个不同 band) → unclear
                cycle, conf = "unclear", empty_pool

        # voting_breakdown:展示每个指标对 top_band 的投票情况(便于审计)
        voting_breakdown = {
            "mvrv_z_candidate": cycle if cycle in per_indicator["mvrv_z"]
                                else _first(mvrv_candidates),
            "nupl_candidate": cycle if cycle in per_indicator["nupl"]
                              else _first(nupl_candidates),
            "lth_candidate": cycle if cycle in per_indicator["lth_90d_chg"]
                             else _first(lth_candidates),
        }
        voting_pool = [b for b in (
            voting_breakdown["mvrv_z_candidate"],
            voting_breakdown["nupl_candidate"],
            voting_breakdown["lth_candidate"],
        ) if b]

        # ---- 减半窗口修正 ----
        halving_active = _is_halving_window_active(klines_1d)
        if halving_active:
            penalty = float(self.scoring_config.get(
                "halving_confidence_penalty", 0.15
            ))
            conf = max(0.0, round(conf - penalty, 4))

        # ---- last_stable 查询(Sprint 1.6 硬编码返回 None)----
        last_stable: Optional[str] = _lookup_last_stable(state_history_dao)

        return {
            "factor": self.name,
            "cycle_position": cycle,
            "cycle_confidence": round(conf, 4),
            "voting_pool": voting_pool,
            "voting_breakdown": voting_breakdown,
            "aux_conditions_passed": aux_passed,
            "last_stable_cycle_position": last_stable,
            "halving_window_active": halving_active,
            "mvrv_z_stabilizing_check_result": stabilizing_check_result,
            **reduce_metadata(
                health_status=_health_status(mvrv_z, nupl, lth_90d_chg),
                notes=_build_notes(mvrv_z, nupl, lth_90d_chg, ath_drawdown),
            ),
            "diagnostics": diagnostics,
        }


# ============================================================
# 辅助函数
# ============================================================

def _last_value(series: Optional[pd.Series]) -> Optional[float]:
    if series is None:
        return None
    if not isinstance(series, pd.Series):
        return None
    clean = series.dropna()
    if clean.empty:
        return None
    return float(clean.iloc[-1])


def _pct_change_90d(series: Optional[pd.Series]) -> Optional[float]:
    """90 天前值 → 当前值的百分比变化。数据不足返回 None。"""
    if series is None or not isinstance(series, pd.Series) or len(series.dropna()) < 90:
        return None
    clean = series.dropna()
    current = float(clean.iloc[-1])
    past = float(clean.iloc[-90])
    if past == 0:
        return None
    return (current - past) / past


def _ath_drawdown_pct(klines: Optional[pd.DataFrame]) -> Optional[float]:
    """BTC 距 窗口内 ATH 的跌幅百分比。数据不足返回 None。"""
    if klines is None or klines.empty or "close" not in klines.columns:
        return None
    close = klines["close"].dropna()
    if close.empty:
        return None
    ath = float(close.max())
    current = float(close.iloc[-1])
    if ath <= 0:
        return None
    return (ath - current) / ath


def _in_range(value: float, rng: Any, trend: Optional[str] = None) -> bool:
    """
    rng 可以是 {range: [lo, hi], trend: ...} 或 [lo, hi] 直接。
    None 边界代表无限(lo=None 即 -inf,hi=None 即 +inf)。
    """
    if isinstance(rng, dict):
        bounds = rng.get("range", [None, None])
    else:
        bounds = rng
    if not isinstance(bounds, list) or len(bounds) != 2:
        return False
    lo, hi = bounds
    if lo is not None and value < float(lo):
        return False
    if hi is not None and value > float(hi):
        return False
    return True


def _match_bands(value: Optional[float], metric_name: str,
                 bands_cfg: dict[str, Any],
                 trend: Optional[str] = None) -> list[str]:
    """
    单指标按所有 band 的范围做匹配,返回命中的 band 列表。
    value is None → []。
    若 band 的 metric_spec 含 `trend` 约束(如 'down'),仅在
    series 的实际 trend 匹配时才算命中。
    metric_name ∈ {mvrv_z, nupl, lth_90d_chg}。
    """
    if value is None:
        return []
    hits: list[str] = []
    for band_name, band_cfg in bands_cfg.items():
        if band_name == "unclear":
            continue
        if not isinstance(band_cfg, dict):
            continue
        metric_spec = band_cfg.get(metric_name)
        if metric_spec is None:
            continue
        if not _in_range(value, metric_spec):
            continue
        # Trend 约束检查
        if isinstance(metric_spec, dict) and "trend" in metric_spec:
            required = metric_spec["trend"]
            if trend is None or trend != required:
                continue
        hits.append(band_name)
    return hits


def _first(items: list[str]) -> Optional[str]:
    return items[0] if items else None


def _series_trend(series: Optional[pd.Series], lookback: int = 30) -> Optional[str]:
    """
    简化趋势判断:近 lookback 天的一阶差均值符号。
      > 0 → "up";< 0 → "down";否则 "flat"。
    数据不足返回 None。
    """
    if series is None or not isinstance(series, pd.Series):
        return None
    clean = series.dropna()
    if len(clean) < lookback + 1:
        return None
    recent = clean.tail(lookback)
    diff = recent.diff().dropna()
    if diff.empty:
        return None
    m = float(diff.mean())
    # 小容忍区间:相对于 series 标准差的 1% 死区
    tolerance = float(recent.std(ddof=0)) * 0.01 if recent.std(ddof=0) > 0 else 0.0
    if m > tolerance:
        return "up"
    if m < -tolerance:
        return "down"
    return "flat"


def _aux_passes(band: str, bands_cfg: dict[str, Any],
                *, ath_drawdown: Optional[float],
                state_history_dao: Any = None) -> bool:
    """
    检查 band 的 aux_* 条件是否通过。
      - aux_min_ath_drawdown_pct: 需要 ath_drawdown ≥ 该值
      - aux_min_drawdown_duration_days / aux_min_days_since_last_* :
        需要 state_history_dao 查询;暂按 True 处理(Sprint 1.12 对接)
    """
    cfg = bands_cfg.get(band, {})
    if not isinstance(cfg, dict):
        return True
    if "aux_min_ath_drawdown_pct" in cfg:
        required = float(cfg["aux_min_ath_drawdown_pct"])
        if ath_drawdown is None or ath_drawdown < required:
            return False
    # 其他 aux 条件(需历史数据)暂 pass:Sprint 1.12 实现
    # aux_min_days_since_last_distribution / aux_min_days_since_last_accumulation
    # aux_min_drawdown_duration_days
    return True


def _is_mvrv_z_stabilizing(series: Optional[pd.Series]) -> Optional[bool]:
    """
    近 30 天 MVRV Z 一阶差均值 > 0 → 企稳(返回 True)。
    数据不足返回 None(视为"未知",调用方按 conservative 处理)。
    """
    if series is None or not isinstance(series, pd.Series):
        return None
    clean = series.dropna()
    if len(clean) < 30:
        return None
    recent = clean.tail(30)
    diff_mean = recent.diff().dropna().mean()
    if pd.isna(diff_mean):
        return None
    return bool(diff_mean > 0)


def _is_halving_window_active(klines: Optional[pd.DataFrame]) -> bool:
    """
    减半窗口判断:简化版 —— 目前硬编码 "2024-04-20 ± 6 月" 和 "2028 附近"。
    Sprint 1.12+ 读 config/event_calendar.yaml 的 halving_events 块。
    """
    if klines is None or klines.empty:
        return False
    try:
        latest = klines.index[-1]
        if isinstance(latest, pd.Timestamp):
            last_dt = latest
        else:
            last_dt = pd.Timestamp(latest)
        # 最近一次减半:2024-04-20
        last_halving = pd.Timestamp("2024-04-20", tz="UTC")
        if last_dt.tzinfo is None:
            last_dt = last_dt.tz_localize("UTC")
        diff_days = abs((last_dt - last_halving).total_seconds()) / 86400.0
        return diff_days <= 180  # 约 6 个月
    except Exception:
        return False


def _lookup_last_stable(state_history_dao: Any) -> Optional[str]:
    """
    Sprint 1.6 占位:state_history_dao 即便传入也返回 None。
    Sprint 1.12+ 对接真实历史查询,查 StrategyStateDAO 最近一次非 unclear 的 cycle_position。
    """
    return None


def _health_status(*values: Optional[float]) -> str:
    nonnull = sum(1 for v in values if v is not None)
    if nonnull == 0:
        return "insufficient_data"
    if nonnull < len(values):
        return "degraded"
    return "healthy"


def _build_notes(mvrv, nupl, lth_chg, ath) -> list[str]:
    notes = []
    if mvrv is None:
        notes.append("mvrv_z_score missing")
    if nupl is None:
        notes.append("nupl missing")
    if lth_chg is None:
        notes.append("lth_supply 90d change unavailable (need ≥90 days history)")
    if ath is None:
        notes.append("ath_drawdown unavailable (klines_1d missing)")
    return notes
