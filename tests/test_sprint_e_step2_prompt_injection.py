"""Sprint E Step 2 — sub-agent prompt 因子状态注入端到端测试。"""
from __future__ import annotations

from src.ai.agents.l1_regime_analyst import L1RegimeAnalyst
from src.ai.agents.l2_direction_analyst import L2DirectionAnalyst
from src.ai.agents.l3_opportunity_analyst import L3OpportunityAnalyst
from src.ai.agents.l4_risk_analyst import L4RiskAnalyst
from src.ai.agents.l5_macro_analyst import L5MacroAnalyst
from src.strategy.factor_dependencies import (
    SRC_BINANCE_KLINE,
    SRC_COINGLASS_DERIV,
    SRC_FRED_MACRO,
    SRC_GLASSNODE_ONCHAIN,
    format_factor_status_block,
)


# ============================================================
# 1. format_factor_status_block 输出格式
# ============================================================

def test_format_block_l2_partial_stale_glassnode():
    stale_map = {SRC_GLASSNODE_ONCHAIN: True, SRC_BINANCE_KLINE: False,
                 SRC_COINGLASS_DERIV: False, SRC_FRED_MACRO: False}
    hours = {SRC_GLASSNODE_ONCHAIN: 67.5}
    block = format_factor_status_block(2, stale_map, source_hours_map=hours)
    # L2 关心 K 线 + Glassnode indicators
    assert "===== L2 因子状态" in block
    assert "❌" in block
    assert "✅" in block
    assert "Glassnode 链上" in block
    assert "67.5 小时" in block
    assert "纪律" in block
    assert "禁止" in block


def test_format_block_l1_all_fresh_no_discipline_line():
    """L1 全新鲜 → 块只有 ✅ 行,无 ❌,无纪律段。"""
    stale_map = {s: False for s in (SRC_BINANCE_KLINE, SRC_COINGLASS_DERIV,
                                     SRC_GLASSNODE_ONCHAIN, SRC_FRED_MACRO)}
    block = format_factor_status_block(1, stale_map)
    assert "✅" in block
    assert "❌" not in block
    assert "纪律" not in block


def test_format_block_l3_no_direct_indicators_returns_empty():
    stale_map = {s: True for s in (SRC_BINANCE_KLINE, SRC_GLASSNODE_ONCHAIN)}
    block = format_factor_status_block(3, stale_map)
    assert block == ""  # L3 LAYER_RELEVANT_INDICATORS 是空 tuple


def test_format_block_l5_fred_stale():
    stale_map = {SRC_FRED_MACRO: True, SRC_BINANCE_KLINE: False,
                 SRC_COINGLASS_DERIV: False, SRC_GLASSNODE_ONCHAIN: False}
    hours = {SRC_FRED_MACRO: 96.0}
    block = format_factor_status_block(5, stale_map, source_hours_map=hours)
    assert "❌" in block
    assert "FRED 宏观" in block
    assert "96.0 小时" in block


# ============================================================
# 2. 5 个 agent _build_user_prompt 注入(无 stale_map → 向后兼容)
# ============================================================

def test_l1_prompt_no_freshness_block_when_context_missing():
    """orchestrator 没装配 source_stale_map → prompt 不破,不含因子状态段。"""
    agent = L1RegimeAnalyst(client=None)
    prompt = agent._build_user_prompt({
        "klines_1d_30d_close": [],
        "computed_indicators": {"adx_14_1d_current": 22.5},
    })
    assert "===== L1 输入数据 =====" in prompt
    assert "因子状态" not in prompt


def test_l1_prompt_includes_factor_status_when_stale_map_present():
    agent = L1RegimeAnalyst(client=None)
    prompt = agent._build_user_prompt({
        "klines_1d_30d_close": [],
        "computed_indicators": {"adx_14_1d_current": 22.5},
        "source_stale_map": {SRC_BINANCE_KLINE: True,
                             SRC_GLASSNODE_ONCHAIN: False,
                             SRC_COINGLASS_DERIV: False,
                             SRC_FRED_MACRO: False},
        "source_hours_map": {SRC_BINANCE_KLINE: 4.0},
    })
    assert "===== L1 因子状态" in prompt
    assert "❌" in prompt
    assert "Binance K 线" in prompt
    assert "禁止" in prompt
    # 同时输入数据段也仍存在
    assert "===== L1 输入数据 =====" in prompt
    # 顺序:freshness 块在前,数据段在后
    assert prompt.index("L1 因子状态") < prompt.index("L1 输入数据")


def test_l2_prompt_glassnode_stale_block():
    agent = L2DirectionAnalyst(client=None)
    prompt = agent._build_user_prompt({
        "computed_indicators": {"lth_mvrv": 1.5},
        "source_stale_map": {SRC_GLASSNODE_ONCHAIN: True,
                             SRC_BINANCE_KLINE: False,
                             SRC_COINGLASS_DERIV: False,
                             SRC_FRED_MACRO: False},
        "source_hours_map": {SRC_GLASSNODE_ONCHAIN: 67.5},
    })
    assert "===== L2 因子状态" in prompt
    # L2 关心 LTH-MVRV 等 Glassnode indicator → ❌
    assert "❌" in prompt
    assert "LTH-MVRV" in prompt
    assert "67.5 小时" in prompt


def test_l3_prompt_no_factor_block_for_derivative_layer():
    """L3 衍生层 — block 是空(LAYER_RELEVANT_INDICATORS[3]=())。"""
    agent = L3OpportunityAnalyst(client=None)
    prompt = agent._build_user_prompt({
        "l1_output": {"status": "success"},
        "source_stale_map": {SRC_BINANCE_KLINE: True},
    })
    assert "===== L3 因子状态" not in prompt
    assert "===== L3 输入数据 =====" in prompt


def test_l4_prompt_derivatives_stale_block():
    agent = L4RiskAnalyst(client=None)
    prompt = agent._build_user_prompt({
        "computed_indicators": {"funding_rate_current": 0.0001},
        "source_stale_map": {SRC_COINGLASS_DERIV: True,
                             SRC_BINANCE_KLINE: False,
                             SRC_GLASSNODE_ONCHAIN: False,
                             SRC_FRED_MACRO: False},
        "source_hours_map": {SRC_COINGLASS_DERIV: 5.0},
    })
    assert "===== L4 因子状态" in prompt
    assert "❌" in prompt
    assert "CoinGlass 衍生品" in prompt
    assert "资金费率" in prompt


def test_l5_prompt_macro_stale_block():
    agent = L5MacroAnalyst(client=None)
    prompt = agent._build_user_prompt({
        "computed_macro_indicators": {"dxy": 105.5},
        "source_stale_map": {SRC_FRED_MACRO: True,
                             SRC_BINANCE_KLINE: False,
                             SRC_COINGLASS_DERIV: False,
                             SRC_GLASSNODE_ONCHAIN: False},
        "source_hours_map": {SRC_FRED_MACRO: 96.0},
    })
    assert "===== L5 因子状态" in prompt
    assert "❌" in prompt
    assert "FRED 宏观" in prompt


# ============================================================
# 3. prompt .txt 含 Sprint E 纪律段
# ============================================================

def test_all_5_prompts_contain_sprint_e_discipline():
    """5 个 .txt 都加了 Sprint E factor-grain stale 纪律段。"""
    from pathlib import Path
    prompts_dir = (
        Path(__file__).parent.parent
        / "src" / "ai" / "agents" / "prompts"
    )
    for fname in (
        "l1_regime.txt", "l2_direction.txt", "l3_opportunity.txt",
        "l4_risk.txt", "l5_macro.txt",
    ):
        text = (prompts_dir / fname).read_text(encoding="utf-8")
        assert "Sprint E factor-grain" in text, f"{fname} 缺纪律段"


# ============================================================
# 4. 5 个 agent 都有 LAYER_ID 类常量
# ============================================================

def test_all_5_agents_have_layer_id():
    assert L1RegimeAnalyst.LAYER_ID == 1
    assert L2DirectionAnalyst.LAYER_ID == 2
    assert L3OpportunityAnalyst.LAYER_ID == 3
    assert L4RiskAnalyst.LAYER_ID == 4
    assert L5MacroAnalyst.LAYER_ID == 5
