"""Sprint J — V1 hard_invalidation_levels v1.4 dict 兼容单测。

§Z 端到端覆盖:
- v1.4 L4 schema:list of dict {price, type, description, distance_from_current_pct}
- v1.3 历史:list of float
- 混合 / 异常输入(None / 缺 price / 非数 string)

回放 2026-05-09 16:18 BJT 真实失败场景(详见
docs/cc_reports/manual_full_pipeline_run_2026_05_09.md):
   levels = [
       {price: 78142.0, type: "ema_20_break", description: "...",
        distance_from_current_pct: -2.76},
       {price: 75510.3, type: "ema_50_break", ...},
       {price: 74868.0, type: "swing_low", ...},
   ]
   master.new_thesis.stop_loss.price = 76000  # 不在 levels → 应覆盖为 78142.0
   修前:TypeError: float() argument must be ... not 'dict'
   修后:正常覆盖为 78142.0,activations=True
"""
from __future__ import annotations

import pytest

from src.ai.validator import _extract_level_price, validator_1_stop_loss


# ============================================================
# _extract_level_price 单元测
# ============================================================

def test_extract_dict_with_price():
    """v1.4 schema:{'price': 78142.0, 'type': 'ema_20_break', ...}"""
    assert _extract_level_price(
        {"price": 78142.0, "type": "ema_20_break",
         "description": "EMA-20 短期支撑", "distance_from_current_pct": -2.76},
    ) == 78142.0


def test_extract_float_legacy():
    """v1.3 历史:list of float 仍可解析(向后兼容)。"""
    assert _extract_level_price(78142.0) == 78142.0


def test_extract_int_coerced():
    """整数也行。"""
    assert _extract_level_price(78000) == 78000.0


def test_extract_string_numeric_coerced():
    """numeric string 兼容。"""
    assert _extract_level_price("78142.0") == 78142.0


def test_extract_dict_missing_price_returns_none():
    """dict 缺 price 字段 → None(skipped by V1)。"""
    assert _extract_level_price({"type": "ema_20", "description": "x"}) is None


def test_extract_none_returns_none():
    assert _extract_level_price(None) is None


def test_extract_dict_with_invalid_price_returns_none():
    """price 不能 float 化 → None。"""
    assert _extract_level_price({"price": "not-a-number"}) is None


def test_extract_random_object_returns_none():
    """对象既不是 dict 也不是 numeric → None。"""
    assert _extract_level_price(object()) is None


# ============================================================
# V1 v1.4 dict 输入(回放 2026-05-09 16:18 真实失败)
# ============================================================

_V14_LEVELS = [
    {"price": 78142.0, "type": "ema_20_break",
     "description": "EMA-20 短期支撑,跌破表示短线上升结构失效",
     "distance_from_current_pct": -2.76},
    {"price": 75510.3, "type": "ema_50_break",
     "description": "EMA-50 中期支撑,跌破表示中期上升趋势失效",
     "distance_from_current_pct": -6.04},
    {"price": 74868.0, "type": "swing_low",
     "description": "最近一个 swing low(4 月 29 日),跌破表示反弹结构破坏",
     "distance_from_current_pct": -6.83},
]


def test_v1_v14_dict_levels_no_override():
    """sl 价位精确匹配 levels[1].price → 不覆盖,不抛 TypeError。"""
    out, act = validator_1_stop_loss(
        {"new_thesis": {"stop_loss": {"price": 75510.3, "size_pct": 100}}},
        {"l4_hard_invalidation_levels": _V14_LEVELS},
    )
    assert not act["validator_1_stop_loss_overridden"]
    assert out["new_thesis"]["stop_loss"]["price"] == 75510.3


def test_v1_v14_dict_levels_override_to_first_price():
    """sl 不在 levels → 覆盖为 levels[0].price=78142.0(回放 16:18 失败)。"""
    out, act = validator_1_stop_loss(
        {"new_thesis": {"stop_loss": {"price": 76000.0, "size_pct": 100}}},
        {"l4_hard_invalidation_levels": _V14_LEVELS},
    )
    assert act["validator_1_stop_loss_overridden"]
    assert out["new_thesis"]["stop_loss"]["price"] == 78142.0
    assert "stop_loss_overridden_by_validator" in out["notes"]


def test_v1_v14_does_not_raise_typeerror():
    """显式 — 16:18 失败的核心症状是抛 TypeError;Sprint J 之后不应再抛。"""
    try:
        validator_1_stop_loss(
            {"new_thesis": {"stop_loss": {"price": 76000.0, "size_pct": 100}}},
            {"l4_hard_invalidation_levels": _V14_LEVELS},
        )
    except TypeError as e:
        pytest.fail(f"V1 still raises TypeError: {e}")


# ============================================================
# 向后兼容 list of float(老格式 / 单测桩)
# ============================================================

def test_v1_legacy_float_levels_no_override():
    """老格式 list[float] 仍走原有路径(回归测)。"""
    out, act = validator_1_stop_loss(
        {"new_thesis": {"stop_loss": {"price": 70000.0, "size_pct": 100}}},
        {"l4_hard_invalidation_levels": [70000.0, 67000.0]},
    )
    assert not act["validator_1_stop_loss_overridden"]


def test_v1_legacy_float_levels_override():
    out, act = validator_1_stop_loss(
        {"new_thesis": {"stop_loss": {"price": 65000.0, "size_pct": 100}}},
        {"l4_hard_invalidation_levels": [70000.0, 67000.0]},
    )
    assert act["validator_1_stop_loss_overridden"]
    assert out["new_thesis"]["stop_loss"]["price"] == 70000.0


# ============================================================
# 混合输入 / 异常元素
# ============================================================

def test_v1_mixed_dict_and_float():
    """levels 含 dict + float 混合(理论不该出现,但要稳健)。"""
    out, act = validator_1_stop_loss(
        {"new_thesis": {"stop_loss": {"price": 60000.0, "size_pct": 100}}},
        {"l4_hard_invalidation_levels": [
            {"price": 78142.0, "type": "ema_20_break"},
            75000.0,  # 老格式 float
        ]},
    )
    assert act["validator_1_stop_loss_overridden"]
    assert out["new_thesis"]["stop_loss"]["price"] == 78142.0


def test_v1_dict_missing_price_skipped():
    """levels 中 dict 缺 price → skip 该项,只用合法的。"""
    out, act = validator_1_stop_loss(
        {"new_thesis": {"stop_loss": {"price": 60000.0, "size_pct": 100}}},
        {"l4_hard_invalidation_levels": [
            {"type": "no_price_field"},   # 缺 price → skip
            {"price": 78142.0, "type": "ema_20_break"},
        ]},
    )
    assert act["validator_1_stop_loss_overridden"]
    assert out["new_thesis"]["stop_loss"]["price"] == 78142.0


def test_v1_all_levels_invalid_skip_override():
    """levels 全部解析失败 → 不覆盖(等同空 levels 路径)。"""
    out, act = validator_1_stop_loss(
        {"new_thesis": {"stop_loss": {"price": 60000.0, "size_pct": 100}}},
        {"l4_hard_invalidation_levels": [
            {"type": "no_price"},
            None,
            object(),
        ]},
    )
    assert not act["validator_1_stop_loss_overridden"]
    assert out["new_thesis"]["stop_loss"]["price"] == 60000.0
