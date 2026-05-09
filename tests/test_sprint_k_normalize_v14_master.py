"""Sprint K — normalize_state v1.4 master(mode + new_thesis)端到端单测。

修前症状(2026-05-09 16:31 BJT 真实 strategy_run):
  - layer_cards[5].label = "未知"(_master_card_v13 没识别 v1.4 mode)
  - state.summary_card.action_state_label = "空仓观察"(state_transition 不存在
    时 action_state 默认 FLAT)
  - state.trade_plan 不存在(前端 cards 全 -)
  - state.main_strategy 不存在(顶部状态条全 -)

修后:5 处全部正确。
"""
from __future__ import annotations

from src.web_helpers.normalize_state import normalize_state


_REAL_V14_STATE = {
    "schema_version": "v14",
    "layers": {
        "l1": {"regime": "transition_up", "regime_stability": "stable",
               "volatility_regime": "normal", "narrative": "L1 ..."},
        "l2": {"stance": "bullish", "phase": "early",
               "stance_confidence_tier": "medium", "narrative": "L2 ..."},
        "l3": {"opportunity_grade": "B", "execution_permission": "cautious_open",
               "anti_pattern_flags": [], "narrative": "L3 ..."},
        "l4": {"risk_tier": "moderate", "position_cap_pct": 72.0,
               "hard_invalidation_levels": [
                   {"price": 78125.0, "type": "ema_20_break",
                    "description": "EMA-20 短期支撑",
                    "distance_from_current_pct": -2.57},
                   {"price": 75503.0, "type": "ema_50_break",
                    "description": "EMA-50 中期支撑",
                    "distance_from_current_pct": -5.84},
                   {"price": 74868.0, "type": "swing_low",
                    "description": "swing low(4 月 29 日)",
                    "distance_from_current_pct": -6.63},
               ], "narrative": "L4 ..."},
        "l5": {"macro_stance": "supportive", "headwind_score": 20,
               "narrative": "L5 ..."},
        "master": {
            "mode": "new_thesis",
            "new_thesis": {
                "direction": "long",
                "confidence_score": 68,
                "core_logic": "BTC 上升趋势确立...",
                "execution_permission": "cautious_open",
                "entry_orders": [
                    {"price": 78125, "size_pct": 25},
                    {"price": 76800, "size_pct": 20},
                    {"price": 82500, "size_pct": 20},
                ],
                "stop_loss": {"price": 74868, "size_pct": 100},
                "take_profit": [
                    {"price": 85000, "size_pct": 30},
                    {"price": 88000, "size_pct": 30},
                    {"price": 92000, "size_pct": 40},
                ],
                "break_conditions": [
                    "1D 收盘跌破 74868",
                    "DXY 突破 120 持续 3 天",
                    "L5 极端事件触发",
                ],
            },
            "narrative": "L1-L5 层间齐心看多...",
            "one_line_summary": "L1-L5 层间齐心看多,等回踩 EMA-20 分批做多",
            "counter_arguments": ["价格仍在 EMA-200 下方 2.8%"],
        },
    },
    "context_summary": {},
    "validator": {"passed": True},
}


# ============================================================
# 修前症状回归 — 4 个核心断言
# ============================================================

def test_master_label_translates_v14_mode():
    """Bug D:label 不再 '未知',而是 '准备开仓(新 thesis)'。"""
    out = normalize_state(_REAL_V14_STATE, run_mode="ai_orchestrator")
    master_card = next(c for c in out["layer_cards"] if c["layer"] == "master")
    assert master_card["label"] != "未知"
    assert master_card["label"] == "准备开仓(新 thesis)"


def test_summary_card_action_state_label_for_new_thesis_long():
    """Bug A 关联:action_state_label 不再 '空仓观察' (FLAT 默认),
    应是 '准备做多(还没开)'。"""
    out = normalize_state(_REAL_V14_STATE, run_mode="ai_orchestrator")
    assert out["summary_card"]["action_state_label"] == "准备做多(还没开)"


def test_main_strategy_block_built_for_v14():
    """Bug A:state.main_strategy 必须存在(顶部状态条用)。"""
    out = normalize_state(_REAL_V14_STATE, run_mode="ai_orchestrator")
    ms = out.get("main_strategy")
    assert ms is not None
    assert ms["action_state"] == "LONG_PLANNED"
    assert ms["lifecycle_phase"] == "准备做多(还没开)"
    assert ms["opportunity_grade"] == "B"
    assert ms["execution_permission"] == "cautious_open"


def test_trade_plan_built_from_new_thesis():
    """Bug B:state.trade_plan 必须存在(前端 cards tp() 读)。"""
    out = normalize_state(_REAL_V14_STATE, run_mode="ai_orchestrator")
    tp = out.get("trade_plan")
    assert tp is not None
    assert len(tp["entry_zones"]) == 3
    assert tp["entry_zones"][0]["price_low"] == 78125
    assert tp["entry_zones"][0]["allocation_pct"] == 25
    assert tp["stop_loss"] == 74868
    assert len(tp["take_profit_plan"]) == 3
    assert tp["take_profit_plan"][0]["price"] == 85000
    assert tp["confidence_tier"] == "medium"  # 68 → medium
    assert tp["confidence_score"] == 68
    assert tp["max_position_size_pct"] == 72.0


# ============================================================
# 主裁卡 supporting_data 完整性
# ============================================================

def test_master_card_supporting_data_v14_fields():
    out = normalize_state(_REAL_V14_STATE, run_mode="ai_orchestrator")
    master_card = next(c for c in out["layer_cards"] if c["layer"] == "master")
    sd = master_card["supporting_data"]
    assert sd["trade_direction"]["value"] == "long"
    assert sd["stop_loss"]["value"] == 74868
    assert len(sd["entry_orders"]["value"]) == 3
    assert len(sd["take_profit"]["value"]) == 3
    assert len(sd["break_conditions"]["value"]) == 3
    assert sd["mode"]["value"] == "准备开仓(新 thesis)"


def test_master_card_secondary_labels_v14():
    out = normalize_state(_REAL_V14_STATE, run_mode="ai_orchestrator")
    master_card = next(c for c in out["layer_cards"] if c["layer"] == "master")
    secondary = [s for s in master_card["secondary_labels"] if s]
    joined = " | ".join(secondary)
    assert "做多" in joined
    assert "信心 68" in joined


def test_master_card_confidence_normalized_to_0_1():
    out = normalize_state(_REAL_V14_STATE, run_mode="ai_orchestrator")
    master_card = next(c for c in out["layer_cards"] if c["layer"] == "master")
    assert abs(master_card["confidence"] - 0.68) < 1e-6


# ============================================================
# 各 mode 的 action_state 推导 + label 文案
# ============================================================

def test_evaluate_existing_long_label():
    state = {
        **_REAL_V14_STATE,
        "layers": {
            **_REAL_V14_STATE["layers"],
            "master": {
                "mode": "evaluate_existing",
                "new_thesis": {"direction": "long"},
                "narrative": "持仓评估中",
            },
        },
    }
    out = normalize_state(state, run_mode="ai_orchestrator")
    assert out["summary_card"]["action_state_label"] == "持有多单"
    assert out["main_strategy"]["action_state"] == "LONG_HOLD"


def test_silent_cooldown_label():
    state = {
        **_REAL_V14_STATE,
        "layers": {
            **_REAL_V14_STATE["layers"],
            "master": {"mode": "silent_cooldown", "narrative": "静默冷却"},
        },
    }
    out = normalize_state(state, run_mode="ai_orchestrator")
    assert "静默冷却" in out["summary_card"]["action_state_label"]
    assert out["main_strategy"]["action_state"] == "FLAT"


def test_protection_mode_label():
    state = {
        **_REAL_V14_STATE,
        "layers": {
            **_REAL_V14_STATE["layers"],
            "master": {"mode": "protection", "narrative": "保护中"},
        },
    }
    out = normalize_state(state, run_mode="ai_orchestrator")
    assert out["main_strategy"]["action_state"] == "PROTECTION"


def test_no_master_mode_falls_back_to_v13():
    """无 mode 无 new_thesis 字段 → 走 v1.3 路径(state_transition)。"""
    state = {
        **_REAL_V14_STATE,
        "layers": {
            **_REAL_V14_STATE["layers"],
            "master": {
                "state_transition": {"to_state": "LONG_HOLD"},
                "trade_plan": {"action": "hold"},
                "narrative": "v1.3 路径",
            },
        },
    }
    out = normalize_state(state, run_mode="ai_orchestrator")
    assert out["summary_card"]["action_state_label"] == "持有多单"
    master_card = next(c for c in out["layer_cards"] if c["layer"] == "master")
    assert master_card["label"] == "持有多单"
    # v1.3 路径不该派生 trade_plan(原 trade_plan 在 raw 里)
    assert "trade_plan" not in out


# ============================================================
# 信心 tier 阈值
# ============================================================

def test_confidence_tier_high():
    state = {
        **_REAL_V14_STATE,
        "layers": {
            **_REAL_V14_STATE["layers"],
            "master": {
                "mode": "new_thesis",
                "new_thesis": {
                    **_REAL_V14_STATE["layers"]["master"]["new_thesis"],
                    "confidence_score": 80,
                },
                "narrative": "x",
            },
        },
    }
    out = normalize_state(state, run_mode="ai_orchestrator")
    assert out["trade_plan"]["confidence_tier"] == "high"


def test_confidence_tier_low():
    state = {
        **_REAL_V14_STATE,
        "layers": {
            **_REAL_V14_STATE["layers"],
            "master": {
                "mode": "new_thesis",
                "new_thesis": {
                    **_REAL_V14_STATE["layers"]["master"]["new_thesis"],
                    "confidence_score": 40,
                },
                "narrative": "x",
            },
        },
    }
    out = normalize_state(state, run_mode="ai_orchestrator")
    assert out["trade_plan"]["confidence_tier"] == "low"
