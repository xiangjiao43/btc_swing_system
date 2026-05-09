"""Sprint K++ — hard_invalidation_levels filter 单测。

筛选规则(用户决策):
1. 真正 stop_loss(is_active_stop_loss=True)→ 必显示
2. rank 紧邻(rank = sl_rank - 1)且 price 距任何 entry_order > 1% → 显示
3. 其他全部隐藏:
   - rank 1 弱预警 + 价位与 entry 重叠 → 隐藏
   - long thesis 的 swing_high / key_resistance / prior_high_break → 隐藏
   - short thesis 的 swing_low / key_support / prior_low_break → 隐藏
   - rank 3 中除 active 外的其他 → 隐藏

预期 5/9 真实 long thesis 输出:只剩 EMA-50 75503 + swing_low 74868 两条,
EMA-20 78125(跟 entry 1 同价 + 弱预警) 与 swing_high 71999.9(向上反向 type)
全部隐藏。
"""
from __future__ import annotations

from src.web_helpers.normalize_state import (
    _classify_hard_invalidation_levels,
    _filter_hard_invalidation_levels,
    normalize_state,
)


_LONG_LEVELS = [
    {"price": 78125.0, "type": "ema_20_break"},   # rank 1
    {"price": 75503.0, "type": "ema_50_break"},   # rank 2
    {"price": 74868.0, "type": "swing_low"},      # rank 3 ← active
    {"price": 71999.9, "type": "swing_high"},     # rank 3
]


def _classify_long():
    return _classify_hard_invalidation_levels(
        _LONG_LEVELS, active_stop_loss_price=74868.0,
    )


# ============================================================
# 用户主诉:5/9 真实 long thesis 输出过滤后只剩 2 条
# ============================================================

def test_long_thesis_filter_drops_ema_20_collision_and_swing_high():
    """long + entry=78125 → 隐藏 EMA-20(同价位)+ swing_high(向上反向)。

    最终只剩 EMA-50 75503 (rank 2 紧邻) + swing_low 74868 (rank 3 active)。
    """
    out = _filter_hard_invalidation_levels(
        _classify_long(),
        direction="long",
        entry_prices=[78125.0, 76800.0, 82500.0],
    )
    assert len(out) == 2
    prices = [x["price"] for x in out]
    assert 78125.0 not in prices              # EMA-20 跟 entry 重叠
    assert 71999.9 not in prices              # swing_high 反向
    assert prices == [75503.0, 74868.0]       # rank 升序


def test_long_thesis_filter_keeps_active_stop_loss():
    out = _filter_hard_invalidation_levels(
        _classify_long(),
        direction="long",
        entry_prices=[78125.0, 76800.0, 82500.0],
    )
    sl = [x for x in out if x.get("is_active_stop_loss")]
    assert len(sl) == 1
    assert sl[0]["price"] == 74868.0
    assert sl[0]["type"] == "swing_low"


def test_long_thesis_filter_keeps_ema_50_warning():
    out = _filter_hard_invalidation_levels(
        _classify_long(),
        direction="long",
        entry_prices=[78125.0, 76800.0, 82500.0],
    )
    warnings = [x for x in out if not x.get("is_active_stop_loss")]
    assert len(warnings) == 1
    assert warnings[0]["price"] == 75503.0
    assert warnings[0]["type_label"] == "EMA-50"
    assert warnings[0]["severity_label"] == "中预警"


# ============================================================
# rank 紧邻规则
# ============================================================

def test_filter_drops_rank_1_when_sl_is_rank_3():
    """rank 1 EMA-20 不是 sl_rank-1=2 紧邻 → 即使距 entry > 1% 也不显示。"""
    levels = [
        {"price": 90000.0, "type": "ema_20_break"},   # rank 1, 远离 entry
        {"price": 75000.0, "type": "swing_low"},      # rank 3 ← active
    ]
    out = _filter_hard_invalidation_levels(
        _classify_hard_invalidation_levels(levels, 75000.0),
        direction="long", entry_prices=[80000.0],
    )
    assert len(out) == 1   # 只有 active stop_loss
    assert out[0]["price"] == 75000.0


def test_filter_keeps_rank_2_warning_far_from_entries():
    """rank 2 距 entry > 1% → 显示。"""
    levels = [
        {"price": 78000.0, "type": "ema_50_break"},   # rank 2
        {"price": 75000.0, "type": "swing_low"},      # rank 3 ← active
    ]
    out = _filter_hard_invalidation_levels(
        _classify_hard_invalidation_levels(levels, 75000.0),
        direction="long", entry_prices=[82000.0],     # 78000 vs 82000: 4.88%
    )
    assert len(out) == 2
    assert {x["price"] for x in out} == {78000.0, 75000.0}


# ============================================================
# entry 距离 1% 阈值
# ============================================================

def test_filter_drops_warning_within_1pct_of_entry():
    """rank 2 但距 entry < 1% → 隐藏(避免视觉与 entry 重叠)。"""
    levels = [
        {"price": 78000.0, "type": "ema_50_break"},
        {"price": 75000.0, "type": "swing_low"},
    ]
    out = _filter_hard_invalidation_levels(
        _classify_hard_invalidation_levels(levels, 75000.0),
        direction="long", entry_prices=[78500.0],   # 78000 vs 78500: 0.64%
    )
    assert len(out) == 1   # 只剩 active(78000 距 entry 0.64% < 1% 隐藏)


def test_filter_keeps_warning_at_exact_1pct_boundary():
    """边界:1% 严格 > 才显示;= 1% 不显示。"""
    levels = [
        {"price": 76000.0, "type": "ema_50_break"},
        {"price": 75000.0, "type": "swing_low"},
    ]
    # entry = 76760 → 距 76000 = 760/76760 = 0.99% < 1% → 隐藏
    out = _filter_hard_invalidation_levels(
        _classify_hard_invalidation_levels(levels, 75000.0),
        direction="long", entry_prices=[76760.0],
    )
    assert all(x["price"] != 76000.0 for x in out)


# ============================================================
# direction-aware 过滤
# ============================================================

def test_short_thesis_drops_swing_low_keeps_swing_high():
    """short thesis:active stop = swing_high(上方止损),hide swing_low。"""
    levels = [
        {"price": 85000.0, "type": "ema_50_break"},   # rank 2
        {"price": 88000.0, "type": "swing_high"},     # rank 3 ← active(short)
        {"price": 70000.0, "type": "swing_low"},      # rank 3,反向
    ]
    out = _filter_hard_invalidation_levels(
        _classify_hard_invalidation_levels(levels, 88000.0),
        direction="short", entry_prices=[82000.0],
    )
    prices = [x["price"] for x in out]
    assert 88000.0 in prices
    assert 70000.0 not in prices    # swing_low 反向
    assert 85000.0 in prices        # rank 2 紧邻,距 entry 82000 = 3.66% > 1%


def test_long_thesis_drops_key_resistance_and_prior_high_break():
    """long:key_resistance + prior_high_break 同样反向(向上的失效),hide。"""
    levels = [
        {"price": 90000.0, "type": "key_resistance"},   # rank 2,向上
        {"price": 85000.0, "type": "prior_high_break"}, # rank 2,向上
        {"price": 75000.0, "type": "ema_50_break"},     # rank 2,中性 → keep
        {"price": 73000.0, "type": "swing_low"},        # rank 3 ← active
    ]
    out = _filter_hard_invalidation_levels(
        _classify_hard_invalidation_levels(levels, 73000.0),
        direction="long", entry_prices=[80000.0],
    )
    prices = [x["price"] for x in out]
    assert 73000.0 in prices
    assert 75000.0 in prices
    assert 90000.0 not in prices
    assert 85000.0 not in prices


# ============================================================
# 边界:无 active stop_loss + 老格式
# ============================================================

def test_filter_no_active_stop_loss_returns_max_rank_only():
    """无 stop_loss(silent_cooldown / 冷启动)→ 返 rank 最高的那条(避免空)。"""
    levels = [
        {"price": 78000, "type": "ema_50_break"},
        {"price": 75000, "type": "swing_low"},
    ]
    out = _filter_hard_invalidation_levels(
        _classify_hard_invalidation_levels(levels, active_stop_loss_price=None),
        direction=None, entry_prices=[],
    )
    assert len(out) == 1
    # classified 经 sort 后 rank 升序,最后一条 = rank 最高
    # rank 3 的 swing_low,active=False
    assert out[0]["price"] == 75000


def test_filter_empty_returns_empty():
    assert _filter_hard_invalidation_levels(
        [], direction="long", entry_prices=[]) == []


# ============================================================
# normalize_state 集成 — state.hard_invalidation_levels_filtered
# ============================================================

_REAL_V14_STATE = {
    "schema_version": "v14",
    "layers": {
        "l1": {}, "l2": {}, "l3": {}, "l5": {},
        "l4": {
            "risk_tier": "moderate",
            "hard_invalidation_levels": _LONG_LEVELS,
            "narrative": "L4",
        },
        "master": {
            "mode": "new_thesis",
            "new_thesis": {
                "direction": "long",
                "stop_loss": {"price": 74868, "size_pct": 100},
                "entry_orders": [
                    {"price": 78125, "size_pct": 25},
                    {"price": 76800, "size_pct": 20},
                    {"price": 82500, "size_pct": 20},
                ],
                "take_profit": [],
            },
            "narrative": "master",
        },
    },
    "context_summary": {},
    "validator": {"passed": True},
}


def test_normalize_state_filtered_field_present():
    out = normalize_state(_REAL_V14_STATE, run_mode="ai_orchestrator")
    f = out.get("hard_invalidation_levels_filtered")
    assert f is not None
    assert len(f) == 2
    assert [x["price"] for x in f] == [75503.0, 74868.0]


def test_normalize_state_classified_still_present():
    """筛选后 classified 仍透传(给将来 / 审计需要看全部时用)。"""
    out = normalize_state(_REAL_V14_STATE, run_mode="ai_orchestrator")
    cl = out.get("hard_invalidation_levels_classified")
    assert cl is not None
    assert len(cl) == 4   # 全部 4 条仍保留
