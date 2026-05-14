"""tests/test_web_modules_1_2_3.py — Sprint 1.10-I commit 4 渲染测试。

覆盖 web/index.html 模块 1+2+3 + app.js Alpine state(BeautifulSoup 解析,
不做浏览器 E2E,留 1.10-L 真用户验证)。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parent.parent
_INDEX_HTML = _REPO_ROOT / "web" / "index.html"
_APP_JS = _REPO_ROOT / "web" / "assets" / "app.js"


@pytest.fixture(scope="module")
def html() -> str:
    return _INDEX_HTML.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def js() -> str:
    return _APP_JS.read_text(encoding="utf-8")


# ============================================================
# 1. 模块 1:虚拟账户面板
# ============================================================

def test_module_1_virtual_account_section_exists(html):
    assert 'id="region-virtual-account"' in html
    assert "audit-card" in html  # 复用现有风格
    assert "虚拟账户" in html


def test_module_1_displays_total_equity_and_initial(html):
    """模块 1 必须含总资产 + 初始资金 + 总收益 + 日/周/月/年 + 可用/持仓。"""
    assert "总资产" in html
    assert "初始资金" in html
    assert "总收益" in html
    assert "日 / 周" in html
    assert "月 / 年" in html
    assert "可用 / 持仓" in html


def test_module_1_alpine_binds_virtual_account(html):
    """Alpine x-text 引用 virtualAccount.total_equity / initial_capital。"""
    assert 'virtualAccount.total_equity' in html
    assert 'virtualAccount.initial_capital' in html
    assert 'virtualAccount.available_cash' in html


def test_module_1_displays_returns(html):
    assert 'accountReturns.total_pct' in html
    assert 'accountReturns.daily_pct' in html
    assert 'accountReturns.weekly_pct' in html
    assert 'accountReturns.monthly_pct' in html
    assert 'accountReturns.yearly_pct' in html


def test_module_1_sparkline_svg(html):
    """30 天资金曲线 sparkline(D1=c 纯 SVG polyline,不引 Chart.js)。"""
    assert "30 天资金曲线" in html
    assert "<svg" in html
    assert "polyline" in html
    assert ":points=\"sparklinePoints(accountHistory)\"" in html


def test_module_1_no_chartjs_dependency(html):
    """硬约束:不引入 Chart.js / D3 / lightweight-charts 等新 JS 库。"""
    assert "chart.js" not in html.lower()
    assert "d3.js" not in html.lower()
    assert "lightweight-charts" not in html.lower()


def test_module_1_cold_start_placeholder(html):
    """无 virtual_account 数据 → 显示冷启动占位。"""
    assert "virtual_account 未初始化" in html


# ============================================================
# 2. 模块 2:当前 thesis 卡
# ============================================================

def test_module_2_active_thesis_section_exists(html):
    assert 'id="region-active-thesis"' in html
    assert "当前 thesis" in html


def test_module_2_displays_thesis_fields(html):
    """thesis_id / direction / confidence_score / lifecycle_stage / core_logic /
    last_assessment / break_conditions。"""
    assert "thesis_id" in html
    assert "方向" in html
    assert "置信度" in html
    assert "阶段" in html
    assert "core_logic" in html
    assert "最近评估" in html
    assert "break_conditions" in html
    assert "失效条件" in html


def test_module_2_no_active_placeholder(html):
    """无 active thesis → 占位提示。"""
    assert "当前无 active thesis" in html


def test_module_2_60d_capped_warning(html):
    """is_60d_capped=true → 警示提示。"""
    assert "activeThesis.is_60d_capped" in html
    assert "60 天上限" in html


def test_module_2_alpine_binds_active_thesis(html):
    assert "activeThesis.thesis_id" in html
    assert "activeThesis.direction" in html
    assert "activeThesis.confidence_score" in html
    assert "activeThesis.lifecycle_stage" in html
    assert "activeThesis.core_logic" in html
    assert "activeThesis.break_conditions" in html


# ============================================================
# 3. 模块 3:挂单 + 持仓状态
# ============================================================

def test_module_3_orders_position_section_exists(html):
    assert 'id="region-orders-position"' in html
    assert "挂单 + 持仓" in html


def test_module_3_displays_position_summary(html):
    """持仓摘要:方向 / BTC 数量 / 均价。"""
    assert "持仓摘要" in html
    assert "BTC 数量" in html
    assert "均价" in html
    assert "positionSummary.direction" in html
    assert "positionSummary.btc_amount" in html
    assert "positionSummary.avg_entry_price" in html


def test_module_3_displays_pending_orders_table(html):
    """待触发挂单表:类型 / 价格 / 仓位 / 距当前。"""
    assert "待触发挂单" in html
    assert "ordersPending.items" in html
    assert "o.order_type" in html
    assert "o.price" in html
    assert "o.size_pct" in html
    assert "distanceFromLive(o.price)" in html


def test_module_3_no_active_placeholder(html):
    assert "当前无 active thesis,无挂单" in html


# ============================================================
# 4. 风格硬约束(audit-card / font-mono / 不引新 JS)
# ============================================================

def test_modules_use_audit_card_class(html):
    """3 个新模块都用 .audit-card class(风格统一)。"""
    # 模块 1
    assert re.search(
        r'id="region-virtual-account"\s+class="audit-card"', html,
    ), "模块 1 缺 audit-card class"
    # 模块 2
    assert re.search(
        r'id="region-active-thesis"\s+class="audit-card"', html,
    ), "模块 2 缺 audit-card class"
    # 模块 3
    assert re.search(
        r'id="region-orders-position"\s+class="audit-card"', html,
    ), "模块 3 缺 audit-card class"


def test_modules_use_font_mono_for_numbers(html):
    """数字字段用 font-mono + tabular-nums(等宽字体审计感)。"""
    # 至少新模块含 font-mono(全文 grep)
    cnt = html.count("font-mono")
    assert cnt >= 15, f"font-mono 用得太少({cnt}),v1.4 §9.1 风格未对齐"


def test_existing_12_cards_not_removed(html):
    """§X:不删现有 12 卡 + 五层分析 6 卡 — 验证现有 region 仍在。"""
    # region-1(AI 策略建议) / Layer A / Layer B 波段策略 / region-layer-cards(五层分析) / region-4 / region-5
    for region in (
        "region-1",
        "region-layer-a-spot",
        "region-layer-b-swing",
        "region-layer-cards",
        "region-4",
        "region-5",
    ):
        assert f'id="{region}"' in html, f"现有 {region} 被误删!"


def test_module_position_between_strategy_and_layers(html):
    """波段策略内部顺序:当前 thesis → AI 策略建议 → 虚拟账户 → 挂单 + 持仓 → 五层分析。"""
    pos_layer_a = html.find('id="region-layer-a-spot"')
    pos_swing = html.find('id="region-layer-b-swing"')
    pos_thesis = html.find('id="region-active-thesis"')
    pos_strategy = html.find('id="region-1"')
    pos_va = html.find('id="region-virtual-account"')
    pos_orders = html.find('id="region-orders-position"')
    pos_layers = html.find('id="region-layer-cards"')
    pos_raw = html.find('id="region-4"')
    assert pos_layer_a < pos_swing < pos_raw, (
        "模块顺序错:必须大周期策略 → 波段策略 → 原始数据因子"
    )
    assert pos_swing < pos_thesis < pos_strategy < pos_va < pos_orders < pos_layers < pos_raw, (
        "波段策略内部顺序错:必须 当前 thesis → AI 策略建议 → 虚拟账户 → 挂单 + 持仓 → 五层分析"
    )


def test_swing_strategy_wrapper_static_contract(html):
    """Layer B 波段模块作为统一大模块展示,不重复拆成多个一级入口。"""
    assert html.count('id="region-layer-b-swing"') == 1
    assert "波段策略" in html
    assert "Layer B · 波段仓" in html
    assert "波段策略更新时间" in html
    assert "判断 BTC 中长线波段;可做多、可做空;创建 thesis、管理虚拟账户和挂单持仓" in html
    assert html.count('id="region-active-thesis"') == 1
    assert html.count('id="region-virtual-account"') == 1
    assert html.count('id="region-orders-position"') == 1
    assert html.count('id="region-layer-cards"') == 1


def test_system_health_three_column_layer_order(html):
    """系统自检内部固定为 Layer A 五层 → Layer B 五层 → 数据源。"""
    pos_layer_a = html.find("Layer A 五层")
    pos_layer_b = html.find("Layer B 五层")
    pos_sources = html.find('class="subheading mb-1.5">数据源')
    assert pos_layer_a != -1
    assert pos_layer_b != -1
    assert pos_sources != -1
    assert pos_layer_a < pos_layer_b < pos_sources
    assert "layerAHealthItems()" in html
    assert "dataSourcesFreshness" in html


def test_system_health_layer_b_and_badge_kept(html):
    """Layer B 自检名称和系统自检 badge 仍保留,只是在前面新增 Layer A 列。"""
    assert "系统自检" in html
    assert "selfCheckBadgeClass()" in html
    assert "selfCheckBadgeLabel()" in html
    assert "systemHealth?.evidence_layers" in html
    assert "layerHealthGlyph(layer.health)" in html


def test_swing_strategy_js_helpers_declared(js):
    assert "swingStrategyUpdatedAt()" in js
    assert "layerAHealthItems()" in js
    for label in ("A1", "A2", "A3", "A4", "A5"):
        assert label in js
    for label in (
        "大周期阶段",
        "链上与宏观",
        "现货策略机会",
        "现货风险",
        "大周期主裁",
    ):
        assert label in js
    assert "暂无 Layer A 输出" in js
    assert "Layer A validator 有 warning / violation" in js


def test_module_position_legacy_expectation_removed(html):
    """旧的一级分散顺序不再成立;Layer B 模块统一收纳到波段策略容器。"""
    pos_layer_a = html.find('id="region-layer-a-spot"')
    pos_va = html.find('id="region-virtual-account"')
    pos_thesis = html.find('id="region-active-thesis"')
    assert not (html.find('id="region-1"') < pos_layer_a < pos_va < pos_thesis), (
        "旧顺序不应继续存在:当前 thesis / 虚拟账户已经归入波段策略内部"
    )


def test_layer_a_spot_module_static_contract(html):
    assert html.count('id="region-layer-a-spot"') == 1
    assert "大周期策略" in html
    assert "大周期策略更新时间" in html
    assert "spotLayerCards()" in html
    assert "暂无大周期策略，本 run 尚未记录 Layer A 输出。" in html
    assert 'src="/assets/app.js?v=layer-b-swing-health-layout-20260514"' in html


# ============================================================
# 5. app.js Alpine state + helpers
# ============================================================

def test_js_v14_state_fields_declared(js):
    """Alpine state 含 5 模块字段。"""
    for field in (
        "virtualAccount:", "accountReturns:", "accountHistory:",
        "activeThesis:", "positionSummary:", "ordersPending:",
    ):
        assert field in js, f"缺 Alpine state 字段:{field}"


def test_layer_a_spot_js_renders_strategy_or_fallback(js):
    assert "layer_a_spot_strategy" in js
    assert "spotStrategy()" in js
    assert "spotStrategyFallbackText()" in js
    assert "spotStrategyUpdatedAt()" in js
    assert "暂无大周期策略，本 run 尚未记录 Layer A 输出。" in js
    assert "spotFinalAdvice()" in js
    assert "spotFinalSummary()" in js
    assert "spotCardSummary(card)" in js
    assert "compactSpotText(v, maxLen = 96)" in js


def test_layer_a_spot_summary_is_compact_and_trader_like(html, js):
    """Layer A 首页只展示短结论,长证据继续放在折叠详情里。"""
    assert "交易员结论:" in js
    assert "spotFinalAdvice()" in html
    assert "spotFinalSummary()" in html
    assert "spotCardSummary(card)" in html
    assert ':title="card.summary || \'-\'"' in html
    assert "查看详细 ▼" in html
    assert "数据质量备注" in html


def test_js_refresh_v14_modules_function(js):
    """_refreshV14Modules 函数定义 + 5 个 fetch URL。"""
    assert "_refreshV14Modules" in js
    assert "/api/account/current" in js
    assert "/api/account/returns" in js
    assert "/api/account/history?days=30" in js
    assert "/api/theses/active" in js
    assert "/api/orders/pending" in js


def test_js_init_calls_v14_modules_refresh(js):
    """init() 末尾调 _refreshV14Modules + setInterval 5 分钟。"""
    assert "_refreshV14Modules()" in js
    assert "_v14ModulesTimer" in js


def test_js_sparkline_helper_pure_svg(js):
    """sparklinePoints 函数纯计算 polyline 字符串(无新依赖)。"""
    assert "sparklinePoints" in js
    # polyline points 格式 "x1,y1 x2,y2 ..."
    assert "points" in js.lower()


def test_js_format_helpers(js):
    """formatUsd / distanceFromLive helpers。"""
    assert "formatUsd" in js
    assert "distanceFromLive" in js


def test_js_no_new_dependencies(js):
    """硬约束:不引入新 JS 库(仍只用 Alpine + Tailwind CDN)。"""
    assert "import" not in js[:200]  # 不在文件头加 import
    assert "require(" not in js
    assert "Chart" not in js  # 不引 Chart.js


# ============================================================
# 6. 现有 audit-card CSS class 仍在
# ============================================================

def test_styles_audit_card_unchanged():
    css = (_REPO_ROOT / "web" / "assets" / "styles.css").read_text(encoding="utf-8")
    assert ".audit-card" in css
    assert ".dark .audit-card" in css
    # 不引入新设计语言(无 fancy gradient / shadow)
    assert "box-shadow:" not in css or "audit-card { box-shadow:" not in css
