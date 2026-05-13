"""tests/test_sprint_1_7_factor_deletions.py — Sprint 1.7 §X 反退化锁。

Sprint 1.7 缩减版真删 3 个 Layer B 噪音因子(原 spec 11 个,7 个被 L 层引用留 1.8):
- reserve_risk(无 L 层引用)
- puell_multiple(无 L 层引用)
- sopr(aSOPR=sopr_adjusted 在 1.6 已替代)

2026-05 Layer A 大周期现货策略重新验证 reserve_risk / puell_multiple 官方
endpoint,并作为只读周期因子恢复采集。它们仍不能回到 Layer B factor_card_emitter
或 Layer B 交易约束。

§X 反退化锁(防止未来回退或意外恢复):
- collector 方法不存在
- _PATH_* 常量不存在
- _GLASSNODE_FETCHERS / _ONCHAIN_EXPECTED_METRICS_TODAY 不含
- factor_card_emitter 不 emit
- catalog 不包含
- sopr_adjusted (aSOPR) 完整保留(关键反退化)

§Z 端到端:GlassnodeCollector 类 import 不破,glassnode 模块 reload 干净。
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
import yaml


_REPO_ROOT = Path(__file__).resolve().parent.parent
_GLASSNODE_PY = _REPO_ROOT / "src" / "data" / "collectors" / "glassnode.py"
_EMITTER_PY = _REPO_ROOT / "src" / "strategy" / "factor_card_emitter.py"
_CATALOG_YAML = _REPO_ROOT / "config" / "data_catalog.yaml"


@pytest.fixture
def glassnode_module():
    """每次测试 reload 干净的 src.data.collectors.glassnode 模块。"""
    import src.data.collectors.glassnode as g
    return importlib.reload(g)


# ============================================================
# A. Collector 方法 + 路径常量已删
# ============================================================

def test_fetch_reserve_risk_method_is_layer_a_only(glassnode_module):
    cg = glassnode_module.GlassnodeCollector
    assert hasattr(cg, "fetch_reserve_risk")
    assert cg._PATH_RESERVE_RISK.endswith("/indicators/reserve_risk")


def test_fetch_puell_multiple_method_is_layer_a_only(glassnode_module):
    cg = glassnode_module.GlassnodeCollector
    assert hasattr(cg, "fetch_puell_multiple")
    assert cg._PATH_PUELL_MULTIPLE.endswith("/indicators/puell_multiple")


def test_no_fetch_sopr_method(glassnode_module):
    """注意区分 fetch_sopr 与 fetch_sopr_adjusted(aSOPR 必须保留)。"""
    cg = glassnode_module.GlassnodeCollector
    assert not hasattr(cg, "fetch_sopr"), (
        "Sprint 1.7:fetch_sopr 必须删除"
    )


def test_fetch_sopr_adjusted_still_exists(glassnode_module):
    """关键反退化:aSOPR(=sopr_adjusted)1.6 升级 primary,1.7 保留。"""
    cg = glassnode_module.GlassnodeCollector
    assert hasattr(cg, "fetch_sopr_adjusted"), (
        "fetch_sopr_adjusted 必须保留(aSOPR primary)"
    )


def test_no_path_constants(glassnode_module):
    cg = glassnode_module.GlassnodeCollector
    for attr in ("_PATH_PUELL", "_PATH_SOPR"):
        assert not hasattr(cg, attr), (
            f"Sprint 1.7:{attr} 必须删除"
        )
    assert hasattr(cg, "_PATH_RESERVE_RISK")
    assert hasattr(cg, "_PATH_PUELL_MULTIPLE")
    # aSOPR 路径常量必须保留
    assert hasattr(cg, "_PATH_SOPR_ADJUSTED")


# ============================================================
# B. scheduler/jobs.py registration 不含
# ============================================================

def test_glassnode_fetchers_no_deleted_names():
    from src.scheduler.jobs import _GLASSNODE_FETCHERS
    for fn in ("fetch_sopr",):
        assert fn not in _GLASSNODE_FETCHERS, (
            f"Sprint 1.7:_GLASSNODE_FETCHERS 应不含 {fn}"
        )
    assert "fetch_reserve_risk" in _GLASSNODE_FETCHERS
    assert "fetch_puell_multiple" in _GLASSNODE_FETCHERS
    # 1.6 新加 + 保留的 aSOPR 应在
    assert "fetch_sopr_adjusted" in _GLASSNODE_FETCHERS
    assert "fetch_sth_supply" in _GLASSNODE_FETCHERS  # 1.6 新加


# Sprint C(2026-05-08):删除 test_expected_metrics_today_no_deleted_names —
# `_ONCHAIN_EXPECTED_METRICS_TODAY` 常量已删除(Sprint C 改为"任一一手 row + quota
# 短路"语义)。等价覆盖在 _GLASSNODE_FETCHERS 测试已存在。


# ============================================================
# C. factor_card_emitter 不 emit
# ============================================================

def test_emitter_does_not_emit_deleted_cards():
    """emit_factor_cards 调用栈中不应再出现 onchain_reserve_risk_ /
    onchain_puell_multiple_ / onchain_sopr_ 三种 card_id 模板。"""
    src = _EMITTER_PY.read_text(encoding="utf-8")
    # active card_id 字符串(emit 调用)— 排除注释
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        # 这三种 card_id 模板不该出现在活跃代码
        assert "onchain_reserve_risk_" not in line, (
            f"Sprint 1.7:active line 仍含 reserve_risk card:{line!r}"
        )
        assert "onchain_puell_multiple_" not in line, (
            f"Sprint 1.7:active line 仍含 puell card:{line!r}"
        )
        # sopr 卡(注意区分 onchain_asopr_)
        if "onchain_sopr_" in line and "onchain_sopr_adjusted" not in line \
                and "onchain_asopr" not in line:
            # 单独 "onchain_sopr_" 仍存在
            pytest.fail(
                f"Sprint 1.7:active line 仍含 SOPR card(非 aSOPR):{line!r}"
            )


def test_emitter_still_has_asopr_card():
    """关键反退化:aSOPR 卡(1.6 升级 primary + reference 镜像)必须保留。"""
    src = _EMITTER_PY.read_text(encoding="utf-8")
    # 1.6 加的 primary 镜像
    assert "onchain_asopr_primary_" in src
    # 1.5 之前 reference 卡 id
    assert "onchain_asopr" in src


# ============================================================
# D. data_catalog.yaml 不包含已删因子
# ============================================================

def test_catalog_no_deleted_source_entries():
    with open(_CATALOG_YAML, "r", encoding="utf-8") as f:
        catalog = yaml.safe_load(f)
    sources = catalog.get("sources") or []
    source_names = [s.get("name") for s in sources if isinstance(s, dict)]
    for name in ("glassnode_sopr",):
        assert name not in source_names, (
            f"Sprint 1.7:sources 应不含 {name}"
        )
    assert "glassnode_reserve_risk" in source_names
    assert "glassnode_puell_multiple" in source_names
    # aSOPR source 保留
    assert "glassnode_sopr_adjusted" in source_names


def test_catalog_no_deleted_factor_entries():
    with open(_CATALOG_YAML, "r", encoding="utf-8") as f:
        catalog = yaml.safe_load(f)
    factors = catalog.get("single_factors") or []
    factor_names = [f.get("name") for f in factors if isinstance(f, dict)]
    for name in ("sopr", "reserve_risk", "puell_multiple"):
        assert name not in factor_names, (
            f"Sprint 1.7:single_factors 应不含 {name}"
        )
    # asopr 1.6 升级 primary 必须保留
    assert "asopr" in factor_names


def test_catalog_asopr_still_primary():
    """1.6 升级断言:asopr.role_in_v1 = 'primary'(1.7 删 sopr 不影响 aSOPR)。"""
    with open(_CATALOG_YAML, "r", encoding="utf-8") as f:
        catalog = yaml.safe_load(f)
    asopr = next(
        f for f in catalog["single_factors"] if f.get("name") == "asopr"
    )
    assert asopr["role_in_v1"] == "primary"


# ============================================================
# E. 端到端 import 干净 + emit_factor_cards 不崩
# ============================================================

def test_emit_factor_cards_does_not_emit_deleted_factors():
    """端到端:跑 emit_factor_cards 不再产出 reserve_risk / puell / sopr 卡。"""
    import pandas as pd
    from src.strategy.factor_card_emitter import emit_factor_cards

    # 故意提供这 3 个 series,看 emitter 还会不会用
    def _series(value, ts="2026-04-30T00:00:00Z"):
        return pd.Series([value], index=pd.to_datetime([ts], utc=True))

    state = {
        "evidence_reports": {"layer_1": {}},
        "composite_factors": {},
        "factor_cards": [],
    }
    context = {
        "onchain": {
            "reserve_risk": _series(0.005),  # 即使提供也不应产卡
            "puell_multiple": _series(1.2),
            "sopr": _series(1.01),
            "sopr_adjusted": _series(1.012),  # aSOPR 仍应产卡
        },
        "derivatives": {},
        "macro": {},
        "klines_1d": None,
    }
    cards = emit_factor_cards(state, context)
    card_ids = {c["card_id"] for c in cards}
    # 反退化:被删的 3 种 card_id 模板都不应出现
    for cid in card_ids:
        assert "reserve_risk" not in cid, (
            f"Sprint 1.7:emit 仍产 reserve_risk 卡:{cid}"
        )
        assert "puell_multiple" not in cid, (
            f"Sprint 1.7:emit 仍产 puell 卡:{cid}"
        )
        # sopr_adjusted / asopr 不算 sopr
        if "sopr" in cid and "asopr" not in cid \
                and "sopr_adjusted" not in cid:
            pytest.fail(f"emit 仍产原始 SOPR 卡:{cid}")
    # 关键反退化:aSOPR 卡仍应在
    assert any("asopr" in cid for cid in card_ids), (
        "aSOPR 卡必须保留(1.6 升级 primary)"
    )
