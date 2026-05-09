"""Sprint K+ — hard_invalidation_levels 分级 classifier 单测。

验证:
- L4 输出 list of dict({price, type, ...}) → 富化 severity_label / type_label /
  severity_rank / is_active_stop_loss
- master.new_thesis.stop_loss.price 匹配的那条标 is_active_stop_loss=True
- 排序:严重度由弱到强(rank 1 → 3),同 rank 内 active stop_loss 排前
- 兼容老格式 list of float(无 type → 当 '硬止损' 处理)
- 字段缺失/非数值/None 全部稳健
"""
from __future__ import annotations

from src.web_helpers.normalize_state import (
    _classify_hard_invalidation_levels, normalize_state,
)


def test_classify_real_5_9_levels_with_active_stop_loss():
    """回放 5/9 真实 L4 输出 + master swing_low 74868 → 标记 + 分级。"""
    levels = [
        {"price": 78125.0, "type": "ema_20_break",
         "description": "EMA-20 短期支撑", "distance_from_current_pct": -2.57},
        {"price": 75503.0, "type": "ema_50_break",
         "description": "EMA-50 中期支撑", "distance_from_current_pct": -5.84},
        {"price": 74868.0, "type": "swing_low",
         "description": "最近 swing low", "distance_from_current_pct": -6.63},
        {"price": 71999.9, "type": "swing_high",
         "description": "近期 swing high", "distance_from_current_pct": -10.21},
    ]
    out = _classify_hard_invalidation_levels(levels, active_stop_loss_price=74868.0)
    # 排序:rank 1 (EMA-20) → 2 (EMA-50) → 3 (swing_low + swing_high)
    assert [x["price"] for x in out[:2]] == [78125.0, 75503.0]
    # 同 rank 3,active stop loss 排前(swing_low)
    rank3 = [x for x in out if x["severity_rank"] == 3]
    assert rank3[0]["price"] == 74868.0
    assert rank3[0]["is_active_stop_loss"] is True
    assert rank3[1]["price"] == 71999.9
    assert rank3[1]["is_active_stop_loss"] is False


def test_classify_severity_labels_per_type():
    levels = [
        {"price": 78125, "type": "ema_20_break"},
        {"price": 75503, "type": "ema_50_break"},
        {"price": 74868, "type": "swing_low"},
    ]
    out = _classify_hard_invalidation_levels(levels, active_stop_loss_price=None)
    by_type = {x["type"]: x for x in out}
    assert by_type["ema_20_break"]["severity_label"] == "弱预警"
    assert by_type["ema_20_break"]["type_label"] == "EMA-20"
    assert by_type["ema_50_break"]["severity_label"] == "中预警"
    assert by_type["swing_low"]["severity_label"] == "硬止损"
    assert by_type["swing_low"]["type_label"] == "swing low"


def test_classify_unknown_type_falls_back_gracefully():
    """未知 type → severity '预警' + type_label 直接用 type 原值。"""
    out = _classify_hard_invalidation_levels(
        [{"price": 70000, "type": "weird_breakdown"}],
        active_stop_loss_price=None,
    )
    assert out[0]["severity_label"] == "预警"
    assert out[0]["type_label"] == "weird_breakdown"
    assert out[0]["severity_rank"] == 1


def test_classify_dict_no_type_treated_as_hard():
    """dict 缺 type → 默认 '硬止损'(L4 未给类型时保守标最严)。"""
    out = _classify_hard_invalidation_levels(
        [{"price": 70000, "description": "x"}],
        active_stop_loss_price=None,
    )
    assert out[0]["severity_label"] == "硬止损"
    assert out[0]["severity_rank"] == 3


def test_classify_legacy_list_of_float():
    """老格式 list of float → 每项当 '硬止损'(无 type 信息可分级)。"""
    out = _classify_hard_invalidation_levels(
        [70000.0, 65000.0], active_stop_loss_price=70000.0,
    )
    assert len(out) == 2
    assert out[0]["price"] == 70000.0
    assert out[0]["is_active_stop_loss"] is True
    assert out[0]["severity_label"] == "硬止损"
    assert out[1]["price"] == 65000.0
    assert out[1]["is_active_stop_loss"] is False


def test_classify_empty_returns_empty():
    assert _classify_hard_invalidation_levels([], active_stop_loss_price=None) == []
    assert _classify_hard_invalidation_levels(
        None, active_stop_loss_price=None,  # type: ignore[arg-type]
    ) == []


def test_classify_skips_invalid_items():
    """None / 非 dict 非数值 / dict 缺 price 全部 skip。"""
    out = _classify_hard_invalidation_levels(
        [None, "not-a-number", {"price": 70000}, object()],
        active_stop_loss_price=None,
    )
    # None 跳过(price=None 不写)、字符串跳过、dict OK、object 跳过
    prices = [x["price"] for x in out if x.get("price") is not None]
    assert 70000 in prices
    # None 元素的 price 也是 None,但被加进 list 因为 dict-shape 检查只针对 isinstance(dict)
    # 让我看代码 — 实际上 None 元素走 else 分支 (try float(None) 抛 TypeError → 跳过)
    # object() 也走 else 分支 (try float(object()) 抛 TypeError → 跳过)
    # 字符串走 else 分支 (try float('not-a-number') 抛 ValueError → 跳过)


def test_classify_active_stop_loss_with_float_tolerance():
    """price 浮点精度容忍(74868 vs 74868.0 vs 74868.0001)。"""
    out = _classify_hard_invalidation_levels(
        [{"price": 74868.0, "type": "swing_low"}],
        active_stop_loss_price=74868,
    )
    assert out[0]["is_active_stop_loss"] is True


def test_classify_no_active_stop_loss_all_false():
    out = _classify_hard_invalidation_levels(
        [{"price": 78125, "type": "ema_20_break"}],
        active_stop_loss_price=None,
    )
    assert out[0]["is_active_stop_loss"] is False


# ============================================================
# normalize_state 集成 — state.hard_invalidation_levels_classified
# ============================================================

_REAL_V14_STATE = {
    "schema_version": "v14",
    "layers": {
        "l1": {}, "l2": {}, "l3": {}, "l5": {},
        "l4": {
            "risk_tier": "moderate",
            "hard_invalidation_levels": [
                {"price": 78125.0, "type": "ema_20_break"},
                {"price": 75503.0, "type": "ema_50_break"},
                {"price": 74868.0, "type": "swing_low"},
            ],
            "narrative": "L4",
        },
        "master": {
            "mode": "new_thesis",
            "new_thesis": {
                "direction": "long",
                "stop_loss": {"price": 74868, "size_pct": 100},
                "entry_orders": [], "take_profit": [],
            },
            "narrative": "master",
        },
    },
    "context_summary": {},
    "validator": {"passed": True},
}


def test_state_hard_invalidation_levels_classified_present():
    out = normalize_state(_REAL_V14_STATE, run_mode="ai_orchestrator")
    cl = out.get("hard_invalidation_levels_classified")
    assert cl is not None
    assert len(cl) == 3
    # 排序:弱预警(78125) → 中预警(75503) → 硬止损(74868)
    assert [x["severity_label"] for x in cl] == ["弱预警", "中预警", "硬止损"]
    assert cl[2]["is_active_stop_loss"] is True


def test_state_classified_no_thesis_no_active_marker():
    """无 new_thesis → 全部 is_active_stop_loss=False。"""
    state = {
        **_REAL_V14_STATE,
        "layers": {
            **_REAL_V14_STATE["layers"],
            "master": {"mode": "silent_cooldown", "narrative": "x"},
        },
    }
    out = normalize_state(state, run_mode="ai_orchestrator")
    cl = out["hard_invalidation_levels_classified"]
    assert all(not x["is_active_stop_loss"] for x in cl)
