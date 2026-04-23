"""
crowding.py — Crowding 组合因子(建模 §3.8.3,v1.2 限定 L4 使用)

7 项评分(thresholds.yaml crowding_scoring.items):
  funding_rate_high_3x / funding_rate_percentile_high / oi_spike /
  top_long_short_extreme / basis_high / put_call_low / upward_liquidation_density
v1 实现其中能通过现有 DAO 数据算的(funding / oi / long_short / liquidation 4 项),
剩余 2 项(basis / put_call)数据未接入,记 items_skipped 列表。

output(对齐 schemas.yaml crowding_output):
  score, direction, band, position_cap_multiplier, items_triggered
  + items_skipped / computation_method / health_status / notes
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from ._base import CompositeFactorBase, reduce_metadata


class CrowdingFactor(CompositeFactorBase):
    name = "crowding"
    thresholds_key = "crowding_scoring"

    def compute(self, context: dict[str, Any]) -> dict[str, Any]:
        derivatives = context.get("derivatives") or {}
        thresholds_l4 = self.full_thresholds.get("layer_4_risk", {}) \
            .get("crowding_thresholds", {})

        items_cfg = self.scoring_config.get("items") or []
        points_map = {i["name"]: float(i.get("points", 0))
                      for i in items_cfg if "name" in i}

        score = 0.0
        items_triggered: list[str] = []
        items_skipped: list[str] = []

        # ---- 指标 1: funding_rate 极端(连续 3 次 > 0.03%)----
        fr_series: Optional[pd.Series] = derivatives.get("funding_rate")
        funding_extreme_threshold = float(
            thresholds_l4.get("funding_rate_extreme_pct", 0.0003)
        )
        funding_consec_required = int(
            thresholds_l4.get("funding_rate_extreme_consecutive", 3)
        )
        if fr_series is not None and not fr_series.empty and len(fr_series) >= funding_consec_required:
            last_n = fr_series.dropna().tail(funding_consec_required)
            if len(last_n) >= funding_consec_required:
                all_extreme = (last_n.abs() > funding_extreme_threshold).all()
                if all_extreme:
                    name = "funding_rate_high_3x"
                    if name in points_map:
                        score += points_map[name]
                        items_triggered.append(name)
        elif fr_series is None:
            items_skipped.append("funding_rate_high_3x (no funding_rate data)")

        # ---- 指标 2: funding_rate_30d_percentile > 85 ----
        # 我们没有现成的百分位;从 funding_rate 90 天数据算
        if fr_series is not None and not fr_series.empty and len(fr_series) >= 30:
            last_val = float(fr_series.dropna().iloc[-1])
            pct = (fr_series.dropna().tail(30) < last_val).sum() / min(30, len(fr_series.dropna()))
            pct_threshold = float(
                thresholds_l4.get("funding_rate_30d_percentile_alert", 85)
            ) / 100.0
            if pct > pct_threshold:
                name = "funding_rate_percentile_high"
                if name in points_map:
                    score += points_map[name]
                    items_triggered.append(name)
        elif fr_series is None:
            items_skipped.append("funding_rate_percentile_high (no funding_rate data)")

        # ---- 指标 3: OI 24h 变化 > +15% ----
        oi_series: Optional[pd.Series] = derivatives.get("open_interest")
        oi_change_threshold = float(
            thresholds_l4.get("oi_change_24h_alert_pct", 0.15)
        )
        if oi_series is not None and len(oi_series.dropna()) >= 2:
            clean = oi_series.dropna()
            oi_now = float(clean.iloc[-1])
            oi_prev = float(clean.iloc[-2])
            if oi_prev > 0:
                chg = (oi_now - oi_prev) / oi_prev
                if abs(chg) > oi_change_threshold:
                    name = "oi_spike"
                    if name in points_map:
                        score += points_map[name]
                        items_triggered.append(name)
        elif oi_series is None:
            items_skipped.append("oi_spike (no open_interest data)")

        # ---- 指标 4: 大户多空比 > 2.5 ----
        ls_series: Optional[pd.Series] = derivatives.get("long_short_ratio")
        ls_threshold = float(thresholds_l4.get("long_short_ratio_alert", 2.5))
        if ls_series is not None and not ls_series.empty:
            ls_latest = float(ls_series.dropna().iloc[-1]) if not ls_series.dropna().empty else None
            if ls_latest is not None and ls_latest > ls_threshold:
                name = "top_long_short_extreme"
                if name in points_map:
                    score += points_map[name]
                    items_triggered.append(name)
        elif ls_series is None:
            items_skipped.append("top_long_short_extreme (no long_short_ratio data)")

        # ---- 指标 5: basis 年化 > 20% —— v1 skip(未接入) ----
        items_skipped.append("basis_high (v1: basis_annualized not collected)")

        # ---- 指标 6: PCR < 0.5 —— v1 skip ----
        items_skipped.append("put_call_low (v1: put_call_ratio not collected)")

        # ---- 指标 7: upward_liquidation_density(-1 反向减分) ----
        liq_long_series: Optional[pd.Series] = derivatives.get("liquidation_long")
        liq_short_series: Optional[pd.Series] = derivatives.get("liquidation_short")
        if liq_long_series is not None and liq_short_series is not None:
            llong = float(liq_long_series.dropna().iloc[-1]) if not liq_long_series.dropna().empty else 0.0
            lshort = float(liq_short_series.dropna().iloc[-1]) if not liq_short_series.dropna().empty else 0.0
            # 上方清算密集 ≈ 多头清算大于空头(当前 rally 后遭清算说明上方聚集)
            if llong > lshort * 1.5 and llong > 0:
                name = "upward_liquidation_density"
                if name in points_map:
                    score += points_map[name]
                    items_triggered.append(name)
        else:
            items_skipped.append("upward_liquidation_density (no liquidation data)")

        # ---- 方向判定(基于 funding 正负 + long_short)----
        direction = _infer_direction(fr_series, ls_series)

        # ---- 输出 band ----
        bands = self.scoring_config.get("output_bands", {})
        extreme_th = float(bands.get("crowded_extreme_at_or_above", 6))
        mild_th = float(bands.get("crowded_mild_at_or_above", 4))
        if score >= extreme_th:
            band = "extreme"
            cap_multiplier = 0.7
        elif score >= mild_th:
            band = "mild"
            cap_multiplier = 0.85
        else:
            band = "normal"
            cap_multiplier = 1.0

        # 空头 crowding 对称 & direction 修正
        if direction == "normal":
            band_display = "normal"
        else:
            band_display = band

        # health_status
        health = "healthy" if not items_skipped else "degraded"
        if len(items_skipped) >= 5:
            health = "insufficient_data"

        return {
            "factor": self.name,
            "score": score,
            "direction": (
                "crowded_long" if direction == "long"
                else "crowded_short" if direction == "short"
                else "normal"
            ),
            "band": band_display,
            "position_cap_multiplier": cap_multiplier,
            "items_triggered": items_triggered,
            "items_skipped": items_skipped,
            **reduce_metadata(health_status=health),
        }


# ============================================================
# 辅助
# ============================================================

def _infer_direction(fr_series: Optional[pd.Series],
                     ls_series: Optional[pd.Series]) -> str:
    """funding 正 + long_short > 1 → long;反之 short;不确定 → normal。"""
    fr_sign = 0
    if fr_series is not None and not fr_series.dropna().empty:
        fr_latest = float(fr_series.dropna().iloc[-1])
        fr_sign = 1 if fr_latest > 0 else (-1 if fr_latest < 0 else 0)

    ls_sign = 0
    if ls_series is not None and not ls_series.dropna().empty:
        ls_latest = float(ls_series.dropna().iloc[-1])
        ls_sign = 1 if ls_latest > 1.0 else (-1 if ls_latest < 1.0 else 0)

    # 两者同号 → 强方向;否则 normal
    if fr_sign > 0 and ls_sign > 0:
        return "long"
    if fr_sign < 0 and ls_sign < 0:
        return "short"
    return "normal"
