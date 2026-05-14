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
    """账户与执行里的虚拟账户显示用户指定的 9 个字段。"""
    start = html.find('id="region-virtual-account"')
    end = html.find('id="region-position-summary"')
    card = html[start:end]
    for label in (
        "初始资金",
        "权益",
        "现金",
        "历史收益率",
        "盈利/回撤",
        "日收益",
        "周收益",
        "月收益",
        "年收益",
    ):
        assert label in card
    assert "PnL" not in card


def test_module_1_alpine_binds_virtual_account(html):
    """Alpine x-text 引用 virtualAccount.total_equity / initial_capital。"""
    assert 'virtualAccount.total_equity' in html
    assert 'virtualAccount.initial_capital' in html
    assert 'virtualAccount.available_cash' in html


def test_module_1_displays_returns(html):
    assert 'accountReturns.total_pct' in html
    for field in (
        "accountReturns.daily_pct",
        "accountReturns.weekly_pct",
        "accountReturns.monthly_pct",
        "accountReturns.yearly_pct",
    ):
        assert field in html
    assert "text-emerald-600 dark:text-emerald-400" in html
    assert "text-rose-600 dark:text-rose-400" in html


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
    assert "挂单 / thesis" in html


def test_module_2_displays_thesis_fields(html):
    """挂单 / thesis 小卡只保留失效条件和精简挂单表。"""
    start = html.find('id="region-active-thesis"')
    end = html.find('id="region-thesis-timeline"')
    card = html[start:end]
    assert "失效条件" in card
    assert "待触发挂单" in card
    assert "等待入场区" not in card
    assert "thesis_id" not in card
    assert "阶段" not in card


def test_module_2_no_active_placeholder(html):
    """无 active thesis → 占位提示。"""
    assert "当前无 active thesis" in html


def test_module_2_60d_capped_warning(html):
    """60 天上限不在首屏重复展示,核心 thesis 信息归入挂单 / thesis。"""
    assert "挂单 / thesis" in html


def test_module_2_alpine_binds_active_thesis(html):
    start = html.find('id="region-active-thesis"')
    end = html.find('id="region-thesis-timeline"')
    card = html[start:end]
    assert "swingInvalidationPlan()" in card
    assert "activeThesis.thesis_id" not in card
    assert "activeThesis.lifecycle_stage" not in card
    assert "cardEntryZones()" not in card


# ============================================================
# 3. 模块 3:挂单 + 持仓状态
# ============================================================

def test_module_3_orders_position_section_exists(html):
    assert 'id="region-orders-position"' in html
    assert "待触发挂单" in html
    start = html.find('id="region-active-thesis"')
    end = html.find('id="region-thesis-timeline"')
    card = html[start:end]
    assert 'id="region-orders-position"' in card


def test_module_3_displays_position_summary(html):
    """当前持仓固定展示 9 个持仓快照字段。"""
    start = html.find('id="region-position-summary"')
    end = html.find('id="region-active-thesis"')
    card = html[start:end]
    for label in (
        "方向",
        "仓位",
        "入场均价",
        "当前价格",
        "浮盈",
        "止损",
        "目标",
        "持仓时长",
        "状态",
    ):
        assert label in card
    assert "当前无持仓 / 等待入场信号" not in card
    for helper in (
        "positionDirectionLabel()",
        "positionSizeLabel()",
        "positionEntryPriceLabel()",
        "positionCurrentPriceLabel()",
        "positionPnlLabel()",
        "positionStopLossLabel()",
        "positionTargetsLabel()",
        "positionHoldingDurationLabel()",
        "positionStatusLabel()",
    ):
        assert helper in card
    for virtual_label in ("权益", "现金", "历史收益率", "初始资金"):
        assert virtual_label not in card


def test_module_3_displays_pending_orders_table(html):
    """挂单 / thesis 内部待触发挂单表:类型 / 价格 / 仓位。"""
    start = html.find('id="region-active-thesis"')
    end = html.find('id="region-thesis-timeline"')
    card = html[start:end]
    assert "待触发挂单" in card
    assert "ordersPending.items" in card
    assert "o.order_type" in card
    assert "o.price" in card
    assert "o.size_pct" in card
    assert "距当前" not in card
    assert "distanceFromLive(o.price)" not in card
    assert len(re.findall(r"<th\b", card)) == 3


def test_module_3_no_active_placeholder(html):
    assert "无待触发挂单" in html


# ============================================================
# 4. 风格硬约束(audit-card / font-mono / 不引新 JS)
# ============================================================

def test_modules_use_swing_container_style(html):
    """Layer B 子模块不再是分散一级 audit-card,统一归入波段策略大卡片。"""
    assert re.search(
        r'id="region-layer-b-swing"\s+class="audit-card"', html,
    ), "波段策略大模块缺 audit-card class"
    for region in ("region-virtual-account", "region-active-thesis", "region-orders-position"):
        assert not re.search(
            rf'id="{region}"\s+class="audit-card"', html,
        ), f"{region} 不应继续作为分散一级 audit-card"


def test_modules_use_font_mono_for_numbers(html):
    """数字字段用 font-mono + tabular-nums(等宽字体审计感)。"""
    # 至少新模块含 font-mono(全文 grep)
    cnt = html.count("font-mono")
    assert cnt >= 15, f"font-mono 用得太少({cnt}),v1.4 §9.1 风格未对齐"


def test_top_market_overview_uses_dual_layer_summary(html):
    """顶部行情卡片右侧改为大周期 / 波段 / 系统状态三块摘要。"""
    start = html.find('id="top-market-overview"')
    end = html.find("<!-- 🩺 系统自检", start)
    top = html[start:end]
    assert "BTC 现价" in top
    assert "采集 " in top
    for label in ("大周期策略", "波段策略", "系统状态"):
        assert label in top
    for helper in (
        "topSpotActionSummary()",
        "topSpotStageSummary()",
        "topSpotUpdatedAt()",
        "topSwingStatusSummary()",
        "topSwingActionSummary()",
        "topSwingUpdatedAt()",
        "topSystemStatusSummary()",
        "topDataStatusSummary()",
        "topFallbackSummary()",
    ):
        assert helper in top


def test_top_market_overview_removed_old_repeated_fields(html):
    """顶部不再重复展示下方模块已有的老字段。"""
    start = html.find('id="top-market-overview"')
    end = html.find("<!-- 🩺 系统自检", start)
    top = html[start:end]
    for old in ("生命周期", "机会 / 许可", "观察类别", "下次运行", "数据 / Fallback"):
        assert old not in top


def test_top_market_overview_js_helpers_declared(js):
    for helper in (
        "topSpotActionSummary()",
        "topSpotStageSummary()",
        "topSpotUpdatedAt()",
        "topSwingStatusSummary()",
        "topSwingActionSummary()",
        "topSwingUpdatedAt()",
        "topSystemStatusSummary()",
        "topDataStatusSummary()",
        "topFallbackSummary()",
        "compactTimestamp(v)",
    ):
        assert helper in js
    for fallback in ("return '暂无'", "return '未知'", "'无 fallback'"):
        assert fallback in js


def test_existing_12_cards_not_removed(html):
    """§X:不删现有 12 卡 + 五层分析 6 卡 — 验证现有 region 仍在。"""
    # Layer A / Layer B 波段策略 / region-layer-cards / region-4 / region-5
    for region in (
        "region-layer-a-spot",
        "region-layer-b-swing",
        "region-layer-cards",
        "region-4",
        "region-5",
    ):
        assert f'id="{region}"' in html, f"现有 {region} 被误删!"


def test_module_position_between_strategy_and_layers(html):
    """波段策略内部顺序:摘要区 → 账户与执行 → 主裁摘要 → L1-L5 卡片。"""
    pos_layer_a = html.find('id="region-layer-a-spot"')
    pos_swing = html.find('id="region-layer-b-swing"')
    pos_summary = html.find('id="region-swing-summary"')
    pos_account = html.find('id="region-swing-account-execution"')
    pos_adjudicator = html.find('id="region-swing-adjudicator-summary"')
    pos_layers = html.find('id="region-layer-cards"')
    pos_raw = html.find('id="region-4"')
    assert pos_layer_a < pos_swing < pos_raw, (
        "模块顺序错:必须大周期策略 → 波段策略 → 原始数据因子"
    )
    assert pos_swing < pos_summary < pos_account < pos_layers < pos_adjudicator < pos_raw, (
        "波段策略内部顺序错:必须 摘要区 → 账户与执行 → 主裁摘要 → L1-L5 卡片"
    )


def test_swing_strategy_wrapper_static_contract(html):
    """Layer B 波段模块作为统一大模块展示,不重复拆成多个一级入口。"""
    assert html.count('id="region-layer-b-swing"') == 1
    assert "波段策略" in html
    assert "Layer B · 波段仓" in html
    assert "波段策略更新时间" in html
    assert "判断 BTC 中长线波段;可做多、可做空;创建 thesis、管理虚拟账户和挂单持仓" in html
    assert html.count('id="region-swing-summary"') == 1
    assert html.count('id="region-swing-account-execution"') == 1
    for label in ("当前状态", "方向", "机会等级", "主裁动作", "置信度"):
        assert label in html
    summary_start = html.find('id="region-swing-summary"')
    summary_end = html.find('id="region-swing-account-execution"')
    summary = html[summary_start:summary_end]
    for label in ("机会等级", "主裁动作", "置信度"):
        assert label in summary
    for label in ("虚拟账户", "当前持仓", "挂单 / thesis", "交易员结论"):
        assert label in html
    assert "账户与执行" in html
    assert "AI 主裁结论" not in html
    assert "五层分析" not in html
    assert "L1-L5 + 主裁" not in html
    assert "每层 AI 独立分析" not in html
    assert html.count('id="region-swing-adjudicator-summary"') == 1
    assert html.count('id="region-active-thesis"') == 1
    assert html.count('id="region-virtual-account"') == 1
    assert html.count('id="region-orders-position"') == 1
    assert html.count('id="region-layer-cards"') == 1


def test_swing_account_execution_contains_required_blocks(html):
    pos_account = html.find('id="region-swing-account-execution"')
    pos_va = html.find('id="region-virtual-account"')
    pos_position = html.find('id="region-position-summary"')
    pos_thesis = html.find('id="region-active-thesis"')
    pos_orders = html.find('id="region-orders-position"')
    pos_layers = html.find('id="region-layer-cards"')
    assert pos_account < pos_va < pos_position < pos_thesis < pos_orders < pos_layers
    for label in ("虚拟账户", "当前持仓", "挂单 / thesis"):
        assert label in html
    assert "账户与执行" in html


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
    assert "swingCurrentStatus()" in js
    assert "swingDirection()" in js
    assert "swingMasterAction()" in js
    assert "swingConfidenceScore()" in js
    assert "swingAdjudicatorAdvice()" in js
    assert "swingAdjudicatorSummary()" in js
    assert "swingAdjudicatorCard()" in js
    assert "swingInvalidationPlan()" in js
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


def test_current_position_js_helpers_declared(js):
    """当前持仓卡片只读现有数据,并提供 no-position fallback。"""
    for helper in (
        "positionHasFilledEntry()",
        "positionDirectionLabel()",
        "positionDirectionClass()",
        "positionSizeLabel()",
        "positionEntryPriceLabel()",
        "positionCurrentPriceLabel()",
        "positionPnlParts()",
        "positionPnlLabel()",
        "positionPnlClass()",
        "positionStopLossLabel()",
        "positionTargetsLabel()",
        "positionHoldingDurationLabel()",
        "positionStatusLabel()",
    ):
        assert helper in js
    assert "return 'none';" in js
    assert "return '等待入场信号';" in js
    assert "d === 'long'" in js
    assert "d === 'short'" in js
    assert "text-emerald-600 dark:text-emerald-400" in js
    assert "text-rose-600 dark:text-rose-400" in js


def test_module_position_legacy_expectation_removed(html):
    """旧的一级分散顺序不再成立;Layer B 模块统一收纳到波段策略仪表盘。"""
    pos_swing = html.find('id="region-layer-b-swing"')
    pos_account = html.find('id="region-swing-account-execution"')
    pos_va = html.find('id="region-virtual-account"')
    pos_layers = html.find('id="region-layer-cards"')
    assert 'id="region-1"' not in html
    assert pos_swing < pos_account < pos_va < pos_layers, (
        "旧顺序不应继续存在:虚拟账户等执行信息必须先进入账户与执行小节"
    )


def test_redundant_ai_adjudicator_block_removed(html, js):
    """独立 AI 主裁结论大块已删除,五层分析里的主裁卡片仍由 layer_cards 展示。"""
    assert 'id="region-1"' not in html
    assert "AI 主裁结论" not in html
    assert "swing_master_detail" not in html
    for label in ("信心指数", "入场区间", "止损价", "止盈分批", "仓位上限", "当前浮盈", "距离止损", "分级失效位"):
        assert label not in html
    assert "swingTraderConclusion()" not in js
    assert "swingTraderReason()" not in js
    assert "swingExecutionPlan()" not in js
    assert 'id="region-layer-cards"' in html


def test_layer_b_five_layer_header_replaced_by_adjudicator_summary(html, js):
    """波段策略不再显示五层分析标题栏,改为主裁交易员摘要框。"""
    assert 'id="region-swing-adjudicator-summary"' in html
    assert 'x-text="swingAdjudicatorAdvice()"' in html
    assert 'x-text="swingAdjudicatorSummary()"' in html
    assert "五层分析" not in html
    assert "L1-L5 + 主裁" not in html
    assert "每层 AI 独立分析" not in html
    assert "交易员结论：主裁 AI 降级，系统使用 fallback。" in js
    assert "swingAdjudicatorCard()" in js


def test_swing_strategy_inner_cards_restore_original_borders(html):
    """波段策略内部小模块恢复截图状态的边框卡片。"""
    for region in (
        "region-swing-summary",
        "region-swing-account-execution",
        "region-virtual-account",
        "region-position-summary",
        "region-active-thesis",
        "region-swing-adjudicator-summary",
        "region-layer-cards",
    ):
        pos = html.find(f'id="{region}"')
        assert pos != -1, f"{region} 缺失"
        snippet = html[pos:pos + 220]
        assert "border border-slate-200" in snippet
        assert "bg-slate-50" not in snippet
        assert "dark:bg-slate-900" not in snippet
    assert "lg:grid-cols-3" in html
    assert 'id="region-layer-b-swing" class="audit-card"' in html


def test_swing_summary_restores_full_five_cards(html):
    """波段策略顶部摘要恢复 5 个摘要块。"""
    start = html.find('id="region-swing-summary"')
    end = html.find('id="region-swing-account-execution"')
    summary = html[start:end]
    for label in ("当前状态", "方向", "机会等级", "主裁动作", "置信度"):
        assert label in summary
    assert "md:grid-cols-5" in summary
    assert summary.count("rounded border border-slate-200") >= 5


def test_layer_a_spot_module_static_contract(html):
    assert html.count('id="region-layer-a-spot"') == 1
    assert "大周期策略" in html
    assert "大周期策略更新时间" in html
    assert "spotLayerCards()" in html
    assert "暂无大周期策略，本 run 尚未记录 Layer A 输出。" in html
    assert 'src="/assets/app.js?v=layer-b-swing-dashboard-20260514"' in html


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
    """formatUsd helper。"""
    assert "formatUsd" in js
    assert "distanceFromLive" not in js


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
