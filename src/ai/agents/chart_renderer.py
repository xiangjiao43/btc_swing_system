"""src/ai/agents/chart_renderer.py — Sprint 1.8 v5(图+数值,无规则结论标签)。

为 6 个 AI agent 渲染分析图表(base64 PNG),让 AI 视觉识别走势形状。
设计哲学(对齐 prompts/_README.md):
- 图为人类交易员视角(K 线 + EMA + 副图指标 + Swing 标注)
- 不在图上画判断结论(如 trend_up/bullish 文字标签)
- AI 看图 + 客观数值自己综合判断,不靠规则预先打的标签

依赖:matplotlib + mplfinance(已 uv pip install)
"""

from __future__ import annotations

import base64
import io
import logging
from typing import Any, Optional

import matplotlib

# 非交互后端(服务器无 display);必须在 import pyplot 前设
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import mplfinance as mpf  # noqa: E402
import pandas as pd  # noqa: E402


logger = logging.getLogger(__name__)


class ChartRenderer:
    """渲染 base64 PNG 图表给 AI agent 输入。

    每个 agent 一个 render_*_chart 方法。返回值是 PNG 文件的 base64
    字符串(用于 anthropic API 多模态 image content)。
    """

    @staticmethod
    def render_l1_chart(
        klines_1d: pd.DataFrame,
        *,
        ema_20: Optional[pd.Series] = None,
        ema_50: Optional[pd.Series] = None,
        ema_200: Optional[pd.Series] = None,
        adx: Optional[pd.Series] = None,
        atr_180d_pct: Optional[pd.Series] = None,
        swing_points: Optional[list[dict[str, Any]]] = None,
        days: int = 180,
    ) -> Optional[str]:
        """L1 Regime 用图。返回 base64 PNG 字符串(失败返回 None)。

        Args:
          klines_1d: pd.DataFrame,index=DatetimeIndex(UTC),
                     columns 至少含 open/high/low/close
          ema_20 / ema_50 / ema_200: 三条 EMA 序列(index 对齐 klines_1d)
          adx: ADX-14 序列
          atr_180d_pct: ATR-14 在过去 180 天的相对位置百分比序列(0-100)
          swing_points: list of {"date": Timestamp/str, "type": "high"|"low",
                                  "price": float}
          days: 取最近多少天(默认 180)

        图规格:
          - 主图(高 5 in):K 线 + 3 EMA(蓝/橙/红)+ Swing(red ▼ / green ▲)
          - 副图 1(高 1.5 in):ADX-14 + 25 阈值参考线
          - 副图 2(高 1.0 in):ATR-180d 分位百分比折线
          - 总图 12 × 8.5 in,DPI 100 → 1200 × 850 px
        """
        if klines_1d is None or klines_1d.empty:
            logger.warning("render_l1_chart: klines_1d empty/None")
            return None

        try:
            df = _prepare_ohlc_df(klines_1d, days=days)
        except Exception as e:
            logger.warning("render_l1_chart: prepare df failed: %s", e)
            return None

        if df.empty or len(df) < 5:
            logger.warning(
                "render_l1_chart: insufficient bars (%d)", len(df),
            )
            return None

        # 主图:K 线 + EMA 叠加
        addplots: list[Any] = []
        for ema_series, color, name in (
            (ema_20, "#1f77b4", "EMA-20"),
            (ema_50, "#ff7f0e", "EMA-50"),
            (ema_200, "#d62728", "EMA-200"),
        ):
            if ema_series is None:
                continue
            try:
                aligned = _align_to_index(ema_series, df.index)
                if aligned.notna().sum() >= 2:
                    addplots.append(mpf.make_addplot(
                        aligned, color=color, width=1.2,
                    ))
            except Exception as e:
                logger.warning("render_l1_chart EMA %s skip: %s", name, e)

        # Swing 标注
        if swing_points:
            try:
                swing_high_y, swing_low_y = _build_swing_markers(
                    df, swing_points,
                )
                if swing_high_y.notna().sum() > 0:
                    addplots.append(mpf.make_addplot(
                        swing_high_y, type="scatter", marker="v",
                        color="#d62728", markersize=80,
                    ))
                if swing_low_y.notna().sum() > 0:
                    addplots.append(mpf.make_addplot(
                        swing_low_y, type="scatter", marker="^",
                        color="#2ca02c", markersize=80,
                    ))
            except Exception as e:
                logger.warning("render_l1_chart swing markers skip: %s", e)

        # 副图 1:ADX
        adx_panel = None
        if adx is not None:
            try:
                adx_aligned = _align_to_index(adx, df.index)
                if adx_aligned.notna().sum() >= 2:
                    addplots.append(mpf.make_addplot(
                        adx_aligned, panel=1, color="#7f7f7f",
                        width=1.0, ylabel="ADX-14",
                    ))
                    # 25 阈值参考线(常量 series)
                    threshold_25 = pd.Series(
                        [25] * len(df), index=df.index, dtype=float,
                    )
                    addplots.append(mpf.make_addplot(
                        threshold_25, panel=1, color="#999999",
                        width=0.6, linestyle="--",
                    ))
                    adx_panel = 1
            except Exception as e:
                logger.warning("render_l1_chart adx skip: %s", e)

        # 副图 2:ATR 180d 分位
        atr_panel = None
        if atr_180d_pct is not None:
            try:
                atr_aligned = _align_to_index(atr_180d_pct, df.index)
                if atr_aligned.notna().sum() >= 2:
                    panel_idx = 2 if adx_panel is not None else 1
                    addplots.append(mpf.make_addplot(
                        atr_aligned, panel=panel_idx, color="#9467bd",
                        width=1.0, ylabel="ATR 180d %",
                    ))
                    atr_panel = panel_idx
            except Exception as e:
                logger.warning("render_l1_chart atr skip: %s", e)

        # panel ratio
        panel_ratios: tuple[float, ...]
        if adx_panel is not None and atr_panel is not None:
            panel_ratios = (5.0, 1.5, 1.0)
        elif adx_panel is not None or atr_panel is not None:
            panel_ratios = (5.0, 1.5)
        else:
            panel_ratios = (5.0,)

        try:
            buf = io.BytesIO()
            mpf.plot(
                df,
                type="candle",
                style="charles",
                addplot=addplots if addplots else None,
                panel_ratios=panel_ratios,
                figsize=(12, 8.5),
                figratio=(12, 8.5),
                figscale=1.0,
                returnfig=False,
                savefig=dict(fname=buf, dpi=100, bbox_inches="tight"),
                title=f"BTC 1d  ({df.index[0].date()} → {df.index[-1].date()})",
                ylabel="Price (USDT)",
            )
            buf.seek(0)
            png_bytes = buf.read()
            buf.close()
        except Exception as e:
            logger.warning("render_l1_chart plot failed: %s", e)
            plt.close("all")
            return None

        plt.close("all")
        return base64.b64encode(png_bytes).decode("ascii")


    @staticmethod
    def render_l2_chart(
        klines_1d: pd.DataFrame,
        klines_4h: Optional[pd.DataFrame] = None,
        *,
        ema_20_1d: Optional[pd.Series] = None,
        ema_50_1d: Optional[pd.Series] = None,
        ema_20_4h: Optional[pd.Series] = None,
        ema_50_4h: Optional[pd.Series] = None,
        swing_points_1d: Optional[list[dict[str, Any]]] = None,
        key_levels: Optional[dict[str, float]] = None,
        days_1d: int = 90,
        days_4h_in_bars: int = 180,  # 30 天 × 6 bar/天 = 180
    ) -> Optional[str]:
        """L2 Direction 用图。返回 base64 PNG 字符串(失败返回 None)。

        图规格:
          - 主图(高 5 in):1d K 线 90 天 + EMA-20(蓝)/EMA-50(橙)+
            Swing(red ▼ / green ▲)+ key_levels 水平线
          - 副图(高 2.5 in):4h K 线 30 天 + EMA-20(蓝)/EMA-50(橙)
          - 总图 12 × 8.5 in,DPI 100 → 1200×850 px

        key_levels:可选 dict {"nearest_support": float, "nearest_resistance":
          float, "major_support": float, "major_resistance": float}。
          画为水平线(支撑实线绿,阻力实线红)。
        """
        if klines_1d is None or klines_1d.empty:
            logger.warning("render_l2_chart: klines_1d empty/None")
            return None

        try:
            df_1d = _prepare_ohlc_df(klines_1d, days=days_1d)
        except Exception as e:
            logger.warning("render_l2_chart prepare 1d failed: %s", e)
            return None
        if df_1d.empty or len(df_1d) < 5:
            logger.warning("render_l2_chart: 1d insufficient (%d)", len(df_1d))
            return None

        # 主图叠加
        addplots: list[Any] = []
        for ema_series, color, name in (
            (ema_20_1d, "#1f77b4", "EMA-20-1d"),
            (ema_50_1d, "#ff7f0e", "EMA-50-1d"),
        ):
            if ema_series is None:
                continue
            try:
                aligned = _align_to_index(ema_series, df_1d.index)
                if aligned.notna().sum() >= 2:
                    addplots.append(mpf.make_addplot(
                        aligned, color=color, width=1.2,
                    ))
            except Exception as e:
                logger.warning("render_l2_chart EMA %s skip: %s", name, e)

        if swing_points_1d:
            try:
                swing_high_y, swing_low_y = _build_swing_markers(
                    df_1d, swing_points_1d,
                )
                if swing_high_y.notna().sum() > 0:
                    addplots.append(mpf.make_addplot(
                        swing_high_y, type="scatter", marker="v",
                        color="#d62728", markersize=80,
                    ))
                if swing_low_y.notna().sum() > 0:
                    addplots.append(mpf.make_addplot(
                        swing_low_y, type="scatter", marker="^",
                        color="#2ca02c", markersize=80,
                    ))
            except Exception as e:
                logger.warning("render_l2_chart swing skip: %s", e)

        # key_levels 水平线 — 用常量 series 实现
        if key_levels:
            for level_name, color in (
                ("nearest_support", "#2ca02c"),
                ("major_support", "#1a661a"),
                ("nearest_resistance", "#d62728"),
                ("major_resistance", "#7d1414"),
            ):
                v = key_levels.get(level_name)
                if v is None:
                    continue
                try:
                    line = pd.Series(
                        [float(v)] * len(df_1d), index=df_1d.index, dtype=float,
                    )
                    addplots.append(mpf.make_addplot(
                        line, color=color, width=0.8,
                        linestyle="--" if "major" in level_name else "-",
                    ))
                except (TypeError, ValueError):
                    continue

        # 4h 副图 — 用副 panel 画 K 线
        df_4h = None
        panel_ratios: tuple[float, ...] = (5.0,)
        if klines_4h is not None and not klines_4h.empty:
            try:
                df_4h_full = _prepare_ohlc_df(klines_4h, days=999)  # 不裁剪
                if len(df_4h_full) > days_4h_in_bars:
                    df_4h = df_4h_full.iloc[-days_4h_in_bars:]
                else:
                    df_4h = df_4h_full
            except Exception as e:
                logger.warning("render_l2_chart 4h prepare skip: %s", e)
                df_4h = None

        # 4h 副图改用 mpf 子图(panel=1)— 但 mpf addplot 只画线,
        # 4h K 线无法直接画副图。简化:把 4h close 作为线图画在副图。
        if df_4h is not None and not df_4h.empty:
            try:
                close_4h = df_4h["Close"].rename("close_4h")
                # 用整数 x 索引,放副图(panel=1)
                # 由于 mpf 限制,副图 series 必须对齐主图索引;
                # 我们改为把最近 30 天 4h close 重新采样到 1d 频率
                close_4h_resampled = close_4h.resample("1D").last()
                close_4h_aligned = _align_to_index(
                    close_4h_resampled, df_1d.index,
                )
                if close_4h_aligned.notna().sum() >= 2:
                    addplots.append(mpf.make_addplot(
                        close_4h_aligned, panel=1, color="#7f7f7f",
                        width=1.0, ylabel="4h close (1d resample)",
                    ))
                    # 4h EMA-20 / 50(同样 1d 重采样)
                    for ema_4h, color_, name_ in (
                        (ema_20_4h, "#1f77b4", "EMA-20-4h"),
                        (ema_50_4h, "#ff7f0e", "EMA-50-4h"),
                    ):
                        if ema_4h is None:
                            continue
                        try:
                            ema_4h_resampled = ema_4h.resample("1D").last()
                            ema_4h_aligned = _align_to_index(
                                ema_4h_resampled, df_1d.index,
                            )
                            if ema_4h_aligned.notna().sum() >= 2:
                                addplots.append(mpf.make_addplot(
                                    ema_4h_aligned, panel=1, color=color_,
                                    width=1.0,
                                ))
                        except Exception:
                            continue
                    panel_ratios = (5.0, 2.5)
            except Exception as e:
                logger.warning("render_l2_chart 4h panel skip: %s", e)

        try:
            buf = io.BytesIO()
            mpf.plot(
                df_1d,
                type="candle",
                style="charles",
                addplot=addplots if addplots else None,
                panel_ratios=panel_ratios,
                figsize=(12, 8.5),
                figratio=(12, 8.5),
                figscale=1.0,
                returnfig=False,
                savefig=dict(fname=buf, dpi=100, bbox_inches="tight"),
                title=(
                    f"BTC L2 1d 90d + 4h 30d  ({df_1d.index[0].date()}"
                    f" → {df_1d.index[-1].date()})"
                ),
                ylabel="Price (USDT)",
            )
            buf.seek(0)
            png_bytes = buf.read()
            buf.close()
        except Exception as e:
            logger.warning("render_l2_chart plot failed: %s", e)
            plt.close("all")
            return None

        plt.close("all")
        return base64.b64encode(png_bytes).decode("ascii")


    @staticmethod
    def render_l4_chart(
        klines_1d: pd.DataFrame,
        *,
        ema_50: Optional[pd.Series] = None,
        ema_200: Optional[pd.Series] = None,
        key_levels: Optional[dict[str, float]] = None,
        atr_14: Optional[pd.Series] = None,
        funding_rate: Optional[pd.Series] = None,
        open_interest: Optional[pd.Series] = None,
        exchange_net_flow: Optional[pd.Series] = None,
        days: int = 90,
    ) -> Optional[str]:
        """L4 Risk 用图。返回 base64 PNG 字符串(失败返回 None)。

        图规格:
          - 主图(高 4 in):1d K 线 90 天 + EMA-50(橙)/EMA-200(红)+
            key_levels 水平线(支撑绿/阻力红)+ ±2*ATR 波动带(灰色填充)
          - 副图 1(高 1.5 in):funding_rate 30 天 + ±0.01% 警戒线
          - 副图 2(高 1.5 in):open_interest 30 天 + 30 日均线
          - 副图 3(高 1.5 in):exchange_net_flow 30 天柱状图
            (流入红/流出绿)
          - 总图 12×8.5 in,DPI 100 → 1200×850 px

        任何副图缺数据时静默跳过,不让总图失败。
        """
        if klines_1d is None or klines_1d.empty:
            logger.warning("render_l4_chart: klines_1d empty/None")
            return None

        try:
            df = _prepare_ohlc_df(klines_1d, days=days)
        except Exception as e:
            logger.warning("render_l4_chart prepare df failed: %s", e)
            return None
        if df.empty or len(df) < 5:
            logger.warning("render_l4_chart: insufficient bars (%d)", len(df))
            return None

        addplots: list[Any] = []

        # 主图:EMA-50 / EMA-200
        for ema_series, color, name in (
            (ema_50, "#ff7f0e", "EMA-50"),
            (ema_200, "#d62728", "EMA-200"),
        ):
            if ema_series is None:
                continue
            try:
                aligned = _align_to_index(ema_series, df.index)
                if aligned.notna().sum() >= 2:
                    addplots.append(mpf.make_addplot(
                        aligned, color=color, width=1.2,
                    ))
            except Exception as e:
                logger.warning("render_l4_chart EMA %s skip: %s", name, e)

        # ±2 ATR 波动带(以 close 为中线)
        if atr_14 is not None:
            try:
                atr_aligned = _align_to_index(atr_14, df.index)
                if atr_aligned.notna().sum() >= 2:
                    upper = df["Close"] + 2 * atr_aligned
                    lower = df["Close"] - 2 * atr_aligned
                    addplots.append(mpf.make_addplot(
                        upper, color="#999999", width=0.6, linestyle=":",
                    ))
                    addplots.append(mpf.make_addplot(
                        lower, color="#999999", width=0.6, linestyle=":",
                    ))
            except Exception as e:
                logger.warning("render_l4_chart ATR band skip: %s", e)

        # key_levels 水平线
        if key_levels:
            for level_name, color in (
                ("nearest_support", "#2ca02c"),
                ("major_support", "#1a661a"),
                ("nearest_resistance", "#d62728"),
                ("major_resistance", "#7d1414"),
            ):
                v = key_levels.get(level_name)
                if v is None:
                    continue
                try:
                    line = pd.Series(
                        [float(v)] * len(df), index=df.index, dtype=float,
                    )
                    addplots.append(mpf.make_addplot(
                        line, color=color, width=0.8,
                        linestyle="--" if "major" in level_name else "-",
                    ))
                except (TypeError, ValueError):
                    continue

        # 副图分配:funding(panel 1) / oi(panel 2) / flow(panel 3)
        next_panel = 1
        funding_panel = oi_panel = flow_panel = None

        if funding_rate is not None:
            try:
                fr_aligned = _align_to_index(funding_rate, df.index)
                if fr_aligned.notna().sum() >= 2:
                    addplots.append(mpf.make_addplot(
                        fr_aligned, panel=next_panel, color="#9467bd",
                        width=1.0, ylabel="Funding",
                    ))
                    # ±0.01% 警戒线
                    upper_warn = pd.Series(
                        [0.0001] * len(df), index=df.index, dtype=float,
                    )
                    lower_warn = pd.Series(
                        [-0.0001] * len(df), index=df.index, dtype=float,
                    )
                    addplots.append(mpf.make_addplot(
                        upper_warn, panel=next_panel, color="#999999",
                        width=0.6, linestyle="--",
                    ))
                    addplots.append(mpf.make_addplot(
                        lower_warn, panel=next_panel, color="#999999",
                        width=0.6, linestyle="--",
                    ))
                    funding_panel = next_panel
                    next_panel += 1
            except Exception as e:
                logger.warning("render_l4_chart funding skip: %s", e)

        if open_interest is not None:
            try:
                oi_aligned = _align_to_index(open_interest, df.index)
                if oi_aligned.notna().sum() >= 2:
                    addplots.append(mpf.make_addplot(
                        oi_aligned, panel=next_panel, color="#1f77b4",
                        width=1.0, ylabel="OI",
                    ))
                    oi_ma30 = oi_aligned.rolling(30, min_periods=5).mean()
                    if oi_ma30.notna().sum() >= 2:
                        addplots.append(mpf.make_addplot(
                            oi_ma30, panel=next_panel, color="#999999",
                            width=0.8, linestyle="--",
                        ))
                    oi_panel = next_panel
                    next_panel += 1
            except Exception as e:
                logger.warning("render_l4_chart OI skip: %s", e)

        if exchange_net_flow is not None:
            try:
                flow_aligned = _align_to_index(exchange_net_flow, df.index)
                if flow_aligned.notna().sum() >= 2:
                    # 用 bar 形式画(净流入红 / 净流出绿);mpf addplot 支持
                    # type='bar',颜色按符号在外部处理:简化为单色折线
                    addplots.append(mpf.make_addplot(
                        flow_aligned, panel=next_panel, type="bar",
                        color="#7f7f7f", ylabel="ExNetFlow",
                    ))
                    flow_panel = next_panel
                    next_panel += 1
            except Exception as e:
                logger.warning("render_l4_chart exchange flow skip: %s", e)

        # panel ratio:主图 4.0 + 各副图 1.5
        sub_panel_count = sum(
            1 for p in (funding_panel, oi_panel, flow_panel) if p is not None
        )
        if sub_panel_count == 3:
            panel_ratios: tuple[float, ...] = (4.0, 1.5, 1.5, 1.5)
        elif sub_panel_count == 2:
            panel_ratios = (4.0, 1.5, 1.5)
        elif sub_panel_count == 1:
            panel_ratios = (4.0, 1.5)
        else:
            panel_ratios = (4.0,)

        try:
            buf = io.BytesIO()
            mpf.plot(
                df,
                type="candle",
                style="charles",
                addplot=addplots if addplots else None,
                panel_ratios=panel_ratios,
                figsize=(12, 8.5),
                figratio=(12, 8.5),
                figscale=1.0,
                returnfig=False,
                savefig=dict(fname=buf, dpi=100, bbox_inches="tight"),
                title=(
                    f"BTC L4 Risk 1d {days}d  "
                    f"({df.index[0].date()} → {df.index[-1].date()})"
                ),
                ylabel="Price (USDT)",
            )
            buf.seek(0)
            png_bytes = buf.read()
            buf.close()
        except Exception as e:
            logger.warning("render_l4_chart plot failed: %s", e)
            plt.close("all")
            return None

        plt.close("all")
        return base64.b64encode(png_bytes).decode("ascii")


# ============================================================
# 内部 helper
# ============================================================

def _prepare_ohlc_df(klines: pd.DataFrame, *, days: int) -> pd.DataFrame:
    """规范化 K 线 DataFrame 给 mplfinance 用。

    要求:
    - index DatetimeIndex(UTC),按时间升序
    - columns 含 Open / High / Low / Close(标题大写,mplfinance 要求)
    - 取最近 days 天
    """
    df = klines.copy()
    # mplfinance 要求 columns 标题首字母大写
    rename_map = {}
    for col in df.columns:
        cl = str(col).lower()
        if cl in ("open", "high", "low", "close", "volume"):
            rename_map[col] = cl.capitalize()
    if rename_map:
        df = df.rename(columns=rename_map)

    # 必须含 OHLC
    required = {"Open", "High", "Low", "Close"}
    if not required.issubset(set(df.columns)):
        missing = required - set(df.columns)
        raise ValueError(f"klines missing OHLC columns: {missing}")

    # index 必须 datetime UTC
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, utc=True)
    else:
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")

    df = df.sort_index()
    if days and days > 0 and len(df) > days:
        df = df.iloc[-days:]
    return df


def _align_to_index(series: pd.Series, target_index: pd.DatetimeIndex) -> pd.Series:
    """把 series 对齐到 target_index;缺失值保持 NaN。"""
    s = series.copy()
    if not isinstance(s.index, pd.DatetimeIndex):
        s.index = pd.to_datetime(s.index, utc=True)
    elif s.index.tz is None:
        s.index = s.index.tz_localize("UTC")
    return s.reindex(target_index)


def _build_swing_markers(
    df: pd.DataFrame, swing_points: list[dict[str, Any]],
) -> tuple[pd.Series, pd.Series]:
    """把 Swing 高/低点列表映射成两个 Series(对齐 df.index,非命中位置 NaN)。

    swing_points 形如 [{"date": "2026-04-15", "type": "high", "price": 82100}, ...]
    """
    high_y = pd.Series([float("nan")] * len(df), index=df.index, dtype=float)
    low_y = pd.Series([float("nan")] * len(df), index=df.index, dtype=float)
    for sp in swing_points or []:
        if not isinstance(sp, dict):
            continue
        try:
            ts = pd.Timestamp(sp.get("date"), tz="UTC") \
                if not isinstance(sp.get("date"), pd.Timestamp) \
                else sp["date"]
            price = float(sp.get("price"))
            stype = str(sp.get("type", "")).lower()
        except (TypeError, ValueError):
            continue
        # 取 df.index 中最近的(常 1d 数据,索引点应直接命中)
        if ts not in df.index:
            # 找最近的同 date(忽略时间)
            same_date = df.index[df.index.normalize() == ts.normalize()]
            if len(same_date) == 0:
                continue
            ts = same_date[0]
        # ▼ 高点画在该 K 线高点之上 1%(避免覆盖 K 线)
        # ▲ 低点画在该 K 线低点之下 1%
        if stype == "high":
            high_y.loc[ts] = price * 1.01
        elif stype == "low":
            low_y.loc[ts] = price * 0.99
    return high_y, low_y
