"""src/ai/extreme_event_detector.py — Sprint 1.9-A.3 v1.3 §3.3.5 极端事件 5 类 bool。

L5 prompt 期望输入 `extreme_event_flags` 5 类 bool:
  - flash_crash_detected_24h    ✅ 真实现(从 1d K 线计算 24h 跌幅)
  - stablecoin_depeg_active     ✅ 真实现(从 derivatives / macro 取 USDT/USDC)
  - geopolitical_conflict_active   ⏭️ 1.9-A 占位 False(1.10 接新闻源)
  - major_bank_crisis_signal       ⏭️ 1.9-A 占位 False(1.10 接金融数据)
  - regulatory_crackdown_recent    ⏭️ 1.9-A 占位 False(1.10 接监管事件源)

铁律对齐:
- 这 5 类 bool 是 v1.3 §3.3.5 显式定义的"系统给 AI 的触发信号"(类型 B),
  不是规则结论标签(L5 自己看 macro 数值还要做 B 类极端判断,详见 L5 prompt §6)。
- B 类(VIX 35+ / DXY 5%+ 等)由 L5 AI 看 computed_macro_indicators 自己识别,
  不在本 detector 范围。

"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pandas as pd

from ..data.storage.dao import BTCKlinesDAO, MacroDAO


logger = logging.getLogger(__name__)


# ============================================================
# 真实现:flash_crash_detected_24h
# ============================================================

def detect_flash_crash_24h(
    klines_1d: pd.DataFrame, *, threshold_pct: float = -8.0,
) -> bool:
    """24h 内 BTC 跌幅 > 8%(从 1d K 线最近一根的 high → low / 上根 close)。

    判据:
      drop_pct = min(
          (today.low - today.open) / today.open,
          (today.low - prev.close) / prev.close
      ) * 100
      drop_pct < -8% → True

    用 1d 数据是近似(理想是 1h 内 8%+);如果 1d K 线最低点比开盘 / 昨收
    跌 8%+,通常意味着盘中真发生了快速崩盘。
    """
    if (klines_1d is None or klines_1d.empty
            or len(klines_1d) < 2
            or not {"high", "low", "open", "close"}.issubset(klines_1d.columns)):
        return False
    today = klines_1d.iloc[-1]
    prev = klines_1d.iloc[-2]
    try:
        drop_from_open = (
            (float(today["low"]) - float(today["open"])) / float(today["open"]) * 100
        )
        drop_from_prev_close = (
            (float(today["low"]) - float(prev["close"])) / float(prev["close"]) * 100
        )
        worst = min(drop_from_open, drop_from_prev_close)
        return worst < threshold_pct
    except (ValueError, ZeroDivisionError, TypeError):
        return False


# ============================================================
# 真实现:stablecoin_depeg_active
# ============================================================

def detect_stablecoin_depeg(
    macro: dict[str, Any],
    *,
    threshold: float = 0.985,
) -> bool:
    """USDT 或 USDC 价格 < 0.985(脱锚 1.5%+)。

    数据源:macro DAO(metric_name='usdt_price' or 'usdc_price')。
    若 DB 没有这些 metric,返回 False(数据缺失不视为脱锚)。
    """
    if not isinstance(macro, dict):
        return False
    for stable_key in ("usdt_price", "usdc_price"):
        s = macro.get(stable_key)
        if s is None or len(s) == 0:
            continue
        try:
            current = float(s.dropna().iloc[-1])
            if current < threshold:
                return True
        except (IndexError, ValueError):
            continue
    return False


# ============================================================
# 占位 stub(1.10 接入数据源)
# ============================================================

def detect_geopolitical_conflict(conn: sqlite3.Connection) -> bool:
    """地缘冲突激活(战争升级 / 重大军事行动 / 制裁)。

    TODO Sprint 1.10: 接入数据源。可选方案:
      - 手动维护 config/extreme_events.yaml(用户每日校准)
      - 接 GDELT / ACLED 新闻 API
      - 接 SipriBank 地缘风险指数
    """
    return False


def detect_major_bank_crisis(conn: sqlite3.Connection) -> bool:
    """重大银行危机信号(SVB-style 倒闭 / TED spread 飙升 / 信用违约掉期 CDS 爆表)。

    TODO Sprint 1.10: 接入数据源。可选方案:
      - FRED TED spread series
      - SOFR 异常溢价
      - Bloomberg US 银行 ETF 单日跌幅
    """
    return False


def detect_regulatory_crackdown(conn: sqlite3.Connection) -> bool:
    """近期重大监管打击(SEC 起诉主要交易所 / 主流国家 BTC 禁令)。

    TODO Sprint 1.10: 接入数据源。可选方案:
      - 手动维护 config/regulatory_events.yaml
      - 接 SEC EDGAR API 监控关键词
      - 接 Coindesk regulatory news feed
    """
    return False


# ============================================================
# 主入口
# ============================================================

def detect_extreme_events(conn: sqlite3.Connection) -> dict[str, bool]:
    """主入口:返回 5 类 bool 给 L5 prompt 的 extreme_event_flags 字段。

    Args:
        conn: SQLite 连接(读 BTCKlinesDAO + MacroDAO)
    Returns:
        dict[str, bool] 含 5 个 key,顺序与 L5 prompt 一致。
    """
    # 取近期 K 线 + macro 给真实现的 2 类用
    try:
        klines_1d = BTCKlinesDAO.get_recent_as_df(conn, "1d", limit=10)
    except Exception as e:
        logger.warning("detect_extreme_events: klines_1d fetch failed: %s", e)
        klines_1d = None
    try:
        macro = MacroDAO.get_all_metrics(conn, lookback_days=10)
    except Exception as e:
        logger.warning("detect_extreme_events: macro fetch failed: %s", e)
        macro = {}

    return {
        "flash_crash_detected_24h":
            detect_flash_crash_24h(klines_1d) if klines_1d is not None else False,
        "stablecoin_depeg_active":
            detect_stablecoin_depeg(macro),
        "geopolitical_conflict_active":
            detect_geopolitical_conflict(conn),
        "major_bank_crisis_signal":
            detect_major_bank_crisis(conn),
        "regulatory_crackdown_recent":
            detect_regulatory_crackdown(conn),
    }
