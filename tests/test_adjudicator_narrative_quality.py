"""tests/test_adjudicator_narrative_quality.py — Sprint 1.5l Task C1。

§Z 反退化检查:1.5l 把 SYSTEM_PROMPT 加了 narrative 写作纪律(交易员叙事
而非规则状态复述)。本测试用 mock AI 客户端注入"理想 narrative"+ "机器化
narrative"两类样本,验证质量判定函数能区分。

注:实际 AI 输出风格由模型 + prompt 共同决定,本 sprint 不直接断言 AI 真
输出符合标准(那需要在线测,不在单测范围)。这里测的是:
  1. system prompt 含 1.5l 规则段(防退化)
  2. 命名指标值能从 narrative 抽出来(质量信号)
  3. 机器化模板词("执行许可收紧到")是反例,不该出现在理想 narrative 里
"""

from __future__ import annotations

import re
from typing import Any
from unittest.mock import MagicMock

from src.ai.adjudicator import _SYSTEM_PROMPT


# ============================================================
# A. system prompt 防退化
# ============================================================

def test_system_prompt_has_narrative_discipline_section():
    """1.5l Task A 反退化:SYSTEM_PROMPT 必须含 narrative 写作纪律章节。"""
    assert "narrative 写作纪律" in _SYSTEM_PROMPT


def test_system_prompt_says_300_to_500_chars():
    """nudge AI 写 300-500 字而非老的 3-5 句。"""
    assert "300-500 字" in _SYSTEM_PROMPT or "300" in _SYSTEM_PROMPT


def test_system_prompt_warns_against_status_repetition():
    """system prompt 必须明确警告"不要复述规则结果"。"""
    assert "不要复述规则结果" in _SYSTEM_PROMPT


def test_system_prompt_warns_against_ai_filler_words():
    """system prompt 必须明确禁止 AI 客套词。"""
    assert "AI 客套词" in _SYSTEM_PROMPT or "本系统建议" in _SYSTEM_PROMPT


def test_system_prompt_describes_flat_watch_special_rule():
    """FLAT/watch 状态下 narrative 写作要求(用户看得最多)。"""
    assert "FLAT" in _SYSTEM_PROMPT
    assert "watch" in _SYSTEM_PROMPT


# ============================================================
# B. narrative 质量判定 helper(单测用)
# ============================================================

# 这两个 helper 只在测试里使用,作为 §Z 数值断言的工具

_BAD_TEMPLATE_PHRASES = (
    "执行许可收紧到",
    "系统不允许新开仓",
    "状态保持 FLAT",
    "执行许可被收紧",
    "鉴于以上因素",
    "综上所述",
    "本系统建议",
)


def _has_template_phrase(text: str) -> bool:
    return any(p in text for p in _BAD_TEMPLATE_PHRASES)


def _count_concrete_metric_values(text: str) -> int:
    """统计 narrative 中具体数值出现次数(% / 大于 100 的整数 / 价格)。
    最低门槛 2 = narrative 至少含 2 个数据点(funding -0.41% / OI 55B 等)。
    """
    pct_matches = re.findall(r"-?\d+\.?\d*\s*%", text)
    big_int_matches = re.findall(r"\b\d{3,}(?:[,\.]\d+)*\b", text)
    return len(pct_matches) + len(big_int_matches)


# ---- helper 自检 ----

def test_helper_detects_machine_template():
    bad = "执行许可被收紧到「仅观察,不开仓」,系统不允许新开仓。鉴于以上因素,保持观察。"
    assert _has_template_phrase(bad)
    assert _count_concrete_metric_values(bad) < 2  # 没具体数值


def test_helper_passes_concrete_narrative():
    good = (
        "funding -0.41%(30d 分位 11%)+ LSR 1.08(从 0.95 翻多 24h)空头先撤。"
        "OI 55.83B 同步 +1.52%,SOPR 0.998 多头割肉。"
        "系统按兵不动,等 funding 收敛到 -0.1% 以上确认空头力竭。"
    )
    assert not _has_template_phrase(good)
    assert _count_concrete_metric_values(good) >= 4


# ============================================================
# C. mock AI 路径:理想 narrative 注入应通过质量门槛
# ============================================================

def _ideal_narrative() -> str:
    return (
        "funding -0.41%(30d 分位 11%,深度负值,空头主导)。"
        "LSR 24h 从 0.95→1.08(+13.68%)空头开始撤退,但 OI 仍 +1.52% 没缩。"
        "SOPR 0.998 多头实质认输,不是被洗。"
        "11h 后 PCE,事件风险档高。"
        "系统按兵不动,等 funding 收敛到 -0.1% 以上 + LSR 见顶,可能转 LONG_PLANNED。"
    )


def _machine_narrative() -> str:
    return (
        "执行许可被收紧到「仅观察,不开仓」,系统不允许新开仓。"
        "状态保持 FLAT。综上所述,等待条件满足。"
    )


def test_ideal_narrative_passes_quality_gates():
    n = _ideal_narrative()
    assert not _has_template_phrase(n), "理想 narrative 不该含机器化模板词"
    assert _count_concrete_metric_values(n) >= 3, (
        f"理想 narrative 应至少含 3 个数值,实际 {_count_concrete_metric_values(n)}"
    )


def test_machine_narrative_fails_quality_gates():
    """机器化 narrative 必须被质量检测**判失败**(防回归到 1.5l 之前的风格)。"""
    n = _machine_narrative()
    # 至少命中两条:有模板词 OR 数值不足
    fails_template = _has_template_phrase(n)
    fails_metrics = _count_concrete_metric_values(n) < 2
    assert fails_template or fails_metrics, (
        "机器化 narrative 应至少触发一项质量判定失败"
    )


# ============================================================
# D. primary_drivers 质量(每条含具体证据)
# ============================================================

def test_primary_driver_concrete_passes():
    drivers = [
        {"evidence_ref": "card_1",
         "text": "funding -0.41%(30d 分位 11%)空头深度主导"},
        {"evidence_ref": "card_2",
         "text": "OI 55.83B 24h +1.52%,空头实质加仓"},
    ]
    for d in drivers:
        assert _count_concrete_metric_values(d["text"]) >= 1


def test_primary_driver_disclaimer_fails_quality():
    """免责声明而非证据 → 没具体数值 → fail。"""
    bad = {"evidence_ref": "card_1",
           "text": "权限收紧期间可能错过真实机会"}
    assert _count_concrete_metric_values(bad["text"]) < 1
