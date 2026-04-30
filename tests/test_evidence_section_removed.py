"""tests/test_evidence_section_removed.py — Sprint 1.5o §X 反退化。

1.5o 整块删除「五层证据推导细节」区(HTML + 配套 JS 渲染函数)。
本测试是反退化锁:确保未来不被恢复。

允许:Sprint 1.5o 解释性注释(标记已删除)。
禁止:任何活跃模板/函数定义/调用。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parent.parent
_INDEX_HTML = _REPO_ROOT / "web" / "index.html"
_APP_JS = _REPO_ROOT / "web" / "assets" / "app.js"


@pytest.fixture
def index_html() -> str:
    return _INDEX_HTML.read_text(encoding="utf-8")


@pytest.fixture
def app_js() -> str:
    return _APP_JS.read_text(encoding="utf-8")


# ============================================================
# HTML:已删除区不应作为活跃模板存在
# ============================================================

def test_no_active_evidence_section_template(index_html: str):
    """五层证据推导细节区整段不应作为活跃 <section> 存在。"""
    # region-2 的 <section id="region-2"> 整段必须删
    assert 'id="region-2"' not in index_html, \
        "region-2 五层证据区仍存在,1.5o 删除被回退"


def test_no_ai_analysis_title(index_html: str):
    """老标题"AI 分析过程·五层证据链"不应出现。"""
    assert "AI 分析过程" not in index_html


def test_no_layer_template_loop(index_html: str):
    """x-for="layer in orderedLayers()" 模板循环必须删。"""
    assert "orderedLayers()" not in index_html


def test_no_layer_chinese_name_calls(index_html: str):
    assert "layerChineseName" not in index_html


def test_no_chain_helper_calls_in_html(index_html: str):
    """positionCapChainText / permissionChainText 模板调用必须删。"""
    assert "positionCapChainText" not in index_html
    assert "permissionChainText" not in index_html


def test_no_layer_pillars_template(index_html: str):
    """L1-L5 三支柱 / 四角度 模板调用 layer.pillars 应不在活跃区。"""
    assert "(layer.pillars || [])" not in index_html


def test_no_evidence_section_japanese_brackets(index_html: str):
    """老模板的中文方括号标记如「这层回答」「分析的三个支柱」「综合结论」
    「给下游的建议」「人话解读」等必须删。"""
    for tag in (
        "【这层回答】", "【分析的三个支柱】", "【分析的三个角度】",
        "【四类分析】", "【综合结论】", "【给下游的建议】", "【人话解读】",
        "【规则匹配】", "【升档条件】", "【position_cap 合成链】",
        "【permission 归并】", "【macro_stance】",
    ):
        assert tag not in index_html, f"老模板标记 {tag} 仍存在"


# ============================================================
# JS:配套渲染函数定义必须删(0 处定义)
# ============================================================

_REMOVED_JS_FUNCTIONS = (
    "orderedLayers",
    "layerChineseName",
    "contributionLabel",
    "contributionClass",
    "freshnessLabel",
    "freshnessBadgeClass",
    "positionCapChainText",
    "permissionChainText",
    "_layer_verdict_from",
    "_confidence_numeric",
)


@pytest.mark.parametrize("fn_name", _REMOVED_JS_FUNCTIONS)
def test_no_removed_function_definition_in_js(app_js: str, fn_name: str):
    """函数定义"<name>(" 必须 0 处。允许出现在注释里(以 // 开头的行)。"""
    pattern = re.compile(rf"^\s*{re.escape(fn_name)}\s*\(", re.MULTILINE)
    matches = pattern.findall(app_js)
    assert len(matches) == 0, (
        f"{fn_name} 函数定义仍存在 ({len(matches)} 处),1.5o 删除被回退"
    )


def test_no_evidence_summary_loop_in_js(app_js: str):
    """旧 evidence_summary 派生的 5 层 for-of 循环必须删。"""
    # 关键签名:[[1,'layer_1'],[2,'layer_2'],...]
    assert "[[1,'layer_1']" not in app_js
    assert "[[1, 'layer_1']" not in app_js


def test_no_chain_text_logic_in_js(app_js: str):
    """L4 chain 文本化逻辑必须删(positionCapChainText / permissionChainText)。"""
    assert "l4_risk_multiplier" not in app_js
    assert "l4_crowding_multiplier" not in app_js
    assert "merged_before_buffer" not in app_js


# ============================================================
# 自检面板必须保留(数据健康信号唯一入口)
# ============================================================

def test_self_check_panel_still_exists(index_html: str):
    assert "🩺 系统自检" in index_html


# ============================================================
# Task B:自检面板必须永远展开(无 toggle)
# ============================================================

def test_self_check_panel_no_toggle_button(index_html: str):
    """1.5o Task B:删除 toggle 按钮和 selfCheckExpanded x-show 控制。"""
    assert "toggleSelfCheck()" not in index_html
    assert "selfCheckExpanded" not in index_html


def test_self_check_panel_no_toggle_in_js(app_js: str):
    """toggleSelfCheck / selfCheckExpanded / _selfCheckUserToggled 必须从
    JS 删除(永远展开,不需要状态)。"""
    assert "toggleSelfCheck" not in app_js
    assert "selfCheckExpanded" not in app_js
    assert "_selfCheckUserToggled" not in app_js


def test_self_check_panel_uses_glyphs(app_js: str):
    """1.5o:三段式视觉(● / ⚠ / ✗)替代纯圆点。"""
    assert "layerHealthGlyph" in app_js
    assert "sourceStatusGlyph" in app_js
