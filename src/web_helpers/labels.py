"""src/web_helpers/labels.py — Sprint 1.8.2-A i18n 翻译表 v0。

锁定:用户硬约束,字典里每个 key/value 严格按下面写,不要擅自修改文案。
1.8.2-A 改文案需用户审定后另起 commit。

金融术语保留英文(OI / funding / EMA / ADX / ATR / RSI 等)— **不在本表**;
枚举值翻译成中文人话 — **本表覆盖**。
"""

from __future__ import annotations

from typing import Any


# ============================================================
# L1 — 市场状态层
# ============================================================

L1_REGIME = {
    "trend_up": "上升趋势(明确向上)",
    "trend_down": "下降趋势(明确向下)",
    "transition_up": "上行过渡(方向偏多但还没确立)",
    "transition_down": "下行过渡(方向偏空但还没确立)",
    "range_high": "区间震荡 - 高位(在区间顶部附近横盘)",
    "range_mid": "区间震荡 - 中位(在区间中段横盘)",
    "range_low": "区间震荡 - 低位(在区间底部附近横盘)",
    "chaos": "混乱失序(波动极端,方向不明)",
    "unclear_insufficient": "数据不足,无法判断",
}

L1_VOLATILITY = {
    "low": "波动低",
    "normal": "波动正常",
    "elevated": "波动偏高",
    "extreme": "波动极端",
}


# ============================================================
# L2 — 方向结构层
# ============================================================

L2_STANCE = {
    "bullish": "看多",
    "bearish": "看空",
    "neutral": "方向不明",
}

L2_PHASE = {
    "early": "趋势初段",
    "mid": "趋势中段",
    "late": "趋势末段",
    "exhausted": "趋势衰竭(可能要反转)",
    "unclear": "阶段不明",
    "n_a": "不适用(震荡市无 phase)",
    "na": "不适用",  # 容错
}


# ============================================================
# L3 — 机会执行层
# ============================================================

L3_OPPORTUNITY_GRADE = {
    "A": "A 级机会(非常好)",
    "B": "B 级机会(尚可)",
    "C": "C 级机会(一般,谨慎)",
    "none": "无机会(不开仓)",
    "None": "无机会(不开仓)",  # 容错
}

L3_EXECUTION_PERMISSION = {
    "active_open": "可以主动开仓",
    "cautious_open": "谨慎开仓",
    "watch": "观望(暂不开)",
    "no_open": "禁止开仓",
    "protective": "保护模式(只减仓不加仓)",
}


# ============================================================
# L4 — 风险评估层
# ============================================================

L4_RISK_TIER = {
    "low": "低风险",
    "moderate": "中等风险",
    "elevated": "风险偏高",
    "extreme": "极端风险",
}


# ============================================================
# L5 — 宏观背景层
# ============================================================

L5_MACRO_STANCE = {
    "supportive": "宏观顺风(对 BTC 有利)",
    "neutral": "宏观中性",
    "headwind": "宏观逆风(对 BTC 不利)",
    "extreme_event": "宏观极端事件(罕见,需警惕)",
}


# ============================================================
# Master — 14 档状态机 + trade_plan.action
# ============================================================

MASTER_STATE = {
    "FLAT": "空仓观察",
    "LONG_PLANNED": "准备做多(还没开)",
    "LONG_OPEN": "已开多仓(初次入场)",
    "LONG_HOLD": "持有多单",
    "LONG_TRIM": "多单减仓中",
    "LONG_EXIT": "多单清仓",
    "SHORT_PLANNED": "准备做空(还没开)",
    "SHORT_OPEN": "已开空仓",
    "SHORT_HOLD": "持有空单",
    "SHORT_TRIM": "空单减仓中",
    "SHORT_EXIT": "空单清仓",
    "PROTECTION": "保护模式(极端事件,只清仓不开新仓)",
    # Sprint 1.10-J commit 4b §X(E.1.a 网页层脱钩):
    # 删 FLIP_WATCH / POST_PROTECTION_REASSESS label(v1.4 §11.2);
    # state_machine 内部 _from_FLIP_WATCH / _from_POST_PROTECTION_REASSESS
    # 主体留 1.10-K 整删(架构级改造)。底层若仍输出这两档,前端会显示
    # raw 字符串(graceful degradation,不挂)。
}

MASTER_MODE = {
    # v1.4 master output `mode` 枚举(src/ai/agents/master_adjudicator.py)
    # — Sprint K 加,前端显示主裁卡 label 与顶部状态条用
    "new_thesis": "准备开仓(新 thesis)",
    "evaluate_existing": "评估持仓(已有 thesis)",
    "silent_cooldown": "静默冷却(数据降级 / 不开新仓)",
    "protection": "保护模式(极端事件强制减仓)",
    "fallback_l1": "降级 L1(主裁失败,走单层兜底)",
    "fallback_l2": "降级 L2(主裁连续失败)",
    "fallback_l3": "降级 L3(深度兜底)",
}

MASTER_ACTION = {
    "open": "开仓",
    "add": "加仓",
    "trim": "减仓",
    "exit": "清仓",
    "hold": "持有",
    "watch": "观望",
    "protect": "保护(强制减仓 / 全清)",
    "protective": "保护(强制减仓 / 全清)",  # 容错(orchestrator 可能写成 protective)
}


# ============================================================
# anti_pattern 5 类(true 时显示)
# ============================================================

ANTI_PATTERN_LABELS = {
    "chasing_top": "⚠️ 追高(价格 7 天涨幅过大,接近近期高点)",
    "catching_falling_knife": "⚠️ 抄底过早(价格 7 天大跌,可能未见底)",
    "false_breakout": "⚠️ 假突破(价格突破后回落)",
    "liquidation_cascade": "⚠️ 清算瀑布(大额爆仓,资金费率急转)",
    "exhaustion_signal": "⚠️ 力竭信号(新高新低但成交量不配合)",
    # v1.3 §3.3.3 实际命名(anti_pattern_signals.py)
    "is_extending_late_phase": "⚠️ 趋势末段追单(phase 已 late/exhausted)",
    "is_against_long_cycle": "⚠️ 与长周期反向(stance vs cycle 反向)",
    "is_chasing_breakout_no_pullback": "⚠️ 突破追单无回踩",
    "is_failing_at_resistance": "⚠️ 在阻力位反复测试失败",
    "is_after_extreme_event_no_reset": "⚠️ 极端事件后未充分整理",
}


# ============================================================
# extreme_event 5 类(true 时显示)
# ============================================================

EXTREME_EVENT_LABELS = {
    "flash_crash_detected_24h": "🚨 闪崩(24h 内 1 小时跌幅 > 8%)",
    "stablecoin_depeg_active": "🚨 稳定币脱锚(USDT/USDC < 0.985)",
    "geopolitical_conflict_active": "🚨 地缘冲突激活",
    "major_bank_crisis_signal": "🚨 银行业危机信号",
    "regulatory_crackdown_recent": "🚨 监管打击近期发生",
}


# ============================================================
# 主入口 helper
# ============================================================

def translate(table: dict[str, Any], key: Any, default: str = "未知") -> str:
    """从指定字典查 key,找不到返回 default(不抛异常)。

    Args:
        table: 翻译表(L1_REGIME / L2_STANCE 等)
        key: 枚举值(如 "trend_up" / "bullish" / "FLAT")
        default: 找不到时的回退值,默认 "未知"
    Returns:
        中文翻译字符串
    """
    if key is None:
        return default
    return table.get(key, default)
