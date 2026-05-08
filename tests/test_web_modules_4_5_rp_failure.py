"""tests/test_web_modules_4_5_rp_failure.py — Sprint 1.10-I commit 5 渲染测试。

覆盖:
- 模块 4 thesis 历史时间线
- 模块 5 周复盘报告(D3=a 下拉切换 12 周 + 23 V 折叠表)
- review_pending 红色横幅(D2=a)+ 解除模态框(D4=b+c)
- 失败状态显示(§9.4 替换"无机会"模糊)
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
# 1. 模块 4:thesis 时间线
# ============================================================

def test_module_4_section_exists(html):
    assert 'id="region-thesis-timeline"' in html
    assert "thesis 历史时间线" in html


def test_module_4_table_columns(html):
    """thesis_id / 方向 / 置信度 / 状态 / 持续 / PnL% / 通道"""
    for col in ("thesis_id", "方向", "置信度", "状态", "持续", "PnL%", "通道"):
        assert col in html, f"模块 4 缺列:{col}"


def test_module_4_alpine_binds_theses_history(html):
    assert "thesesHistory" in html
    assert "t.thesis_id" in html
    assert "t.direction" in html
    assert "t.confidence_score" in html
    assert "t.final_realized_pnl_pct" in html
    assert "t.close_channel" in html


def test_module_4_position_after_layers(html):
    """模块 4 必须在 region-layer-cards 之后,region-4(原始因子)之前。"""
    pos_layers = html.find('id="region-layer-cards"')
    pos_timeline = html.find('id="region-thesis-timeline"')
    pos_region_4 = html.find('id="region-4"')
    assert pos_layers < pos_timeline < pos_region_4


# ============================================================
# 2. 模块 5:周复盘报告
# ============================================================

def test_module_5_section_exists(html):
    assert 'id="region-weekly-review"' in html
    assert "周复盘" in html


def test_module_5_dropdown_for_history(html):
    """D3=a:下拉切换 12 周历史。"""
    assert "weeklyReviewSelectedIdx" in html
    assert "weeklyReviewHistory" in html
    assert "(最新)" in html


def test_module_5_displays_performance_summary(html):
    """周表现摘要:runs / AI 失败 / PnL / 最大回撤。"""
    assert "周表现摘要" in html
    assert "performance_summary" in html
    assert "weekly_pnl_pct" in html
    assert "max_drawdown_pct" in html


def test_module_5_system_health_diagnosis_severity_colors(html):
    """severity = critical / warning / info 三色。"""
    assert "system_health_diagnosis" in html
    assert "critical" in html
    assert "warning" in html
    assert "border-rose-500" in html
    assert "border-amber-500" in html


def test_module_5_adjustment_recommendations_priority(html):
    """优先级 high / medium / low 三色。"""
    assert "adjustment_recommendations" in html
    assert "目标" in html
    assert "优先级" in html


def test_module_5_23_validators_collapsible_table(html):
    """折叠 <details> 含 23 V 评估表。"""
    assert "<details" in html
    assert "23 条 Validator 激活率表" in html
    assert "validatorKeys()" in html


def test_module_5_position_at_bottom_before_footer(html):
    pos_5 = html.find('id="region-weekly-review"')
    pos_footer = html.find("<!-- Footer")
    assert pos_5 < pos_footer
    assert pos_5 > 0


def test_module_5_no_active_placeholder(html):
    assert "暂无周复盘报告" in html


# ============================================================
# 3. review_pending 红色横幅 + 解除模态框
# ============================================================

def test_rp_red_banner_exists(html):
    """红色横幅 + show 条件 reviewPending.active。"""
    assert "review_pending 红色全局横幅" in html
    assert "reviewPending && reviewPending.active" in html
    assert "bg-rose-600" in html
    assert "🚨" in html
    assert "系统进入 review_pending" in html


def test_rp_modal_with_d4_b_c(html):
    """D4=b 模态框二次确认 + D4=c reason 输入。"""
    assert "rpModalOpen" in html
    assert "rpExitType" in html
    assert "rpReason" in html
    # 4 个 EXIT 选项
    assert "EXIT_A" in html
    assert "EXIT_B" in html
    assert "EXIT_C" in html
    assert "EXIT_D" in html
    # reason min 10 chars 提示
    assert "min 10 字符" in html
    assert "至少 10" in html


def test_rp_modal_disabled_when_reason_short(html):
    """rpReason < 10 chars → 确认按钮 disabled。"""
    assert "rpReason || ''" in html
    assert "trim().length < 10" in html


def test_rp_resolve_alpine_method(js):
    """resolveReviewPending Alpine 方法 + POST /api/review_pending/resolve。"""
    assert "resolveReviewPending" in js
    assert "/api/review_pending/resolve" in js
    assert "exit_type" in js
    assert "reason: reasonText" in js


def test_rp_health_fetch_in_modules_refresh(js):
    """_refreshV14Modules 拉 /api/health 写入 reviewPending。"""
    assert "/api/health" in js
    assert "review_pending" in js
    assert "this.reviewPending" in js


# ============================================================
# 4. 失败状态显示(§9.4 + §6.3.4)
# ============================================================

def test_failure_status_section_exists(html):
    """AI 失败状态 section + show 条件 aiFailureStatus()。"""
    assert "AI 失败状态显示" in html
    assert "aiFailureStatus()" in html
    assert "aiFailureDetail()" in html
    assert "⚠️" in html


def test_ai_failure_status_method(js):
    """aiFailureStatus 处理 retry_log_json 多种场景。"""
    assert "aiFailureStatus" in js
    # 5 类失败状态文本
    # v1.4.1 涂装(commit afterwards):占位符统一 em-dash → ASCII '-',
    # 此断言原 "AI 介入失败 — 请人工介入" 同步改 ASCII
    assert "AI 介入失败 - 请人工介入" in js
    assert "已接管" in js  # thesis_aware fallback
    assert "Master 已短路" in js
    assert "macro fallback" in js
    assert "重试中" in js


def test_ai_failure_status_data_source(js):
    """retry_log_json 是数据源(commit 1.10-F)。"""
    assert "retry_log" in js
    assert "failed_layers" in js
    assert "retry_exhausted" in js
    assert "retry_next_attempt" in js


# ============================================================
# 5. app.js Alpine state + helpers
# ============================================================

def test_js_module_4_state(js):
    assert "thesesHistory:" in js


def test_js_module_5_state(js):
    assert "weeklyReviewSelected:" in js
    assert "weeklyReviewHistory:" in js
    assert "weeklyReviewSelectedIdx:" in js


def test_js_rp_state(js):
    assert "reviewPending:" in js
    assert "rpModalOpen:" in js
    assert "rpExitType:" in js
    assert "rpReason:" in js


def test_js_thesis_timeline_helpers(js):
    assert "thesisDurationDays" in js
    assert "thesisStatusColor" in js


def test_js_validator_keys_23(js):
    """validatorKeys() 必须返 23 条 V key(对齐 input_builder)。"""
    assert "validatorKeys()" in js
    # 含全 23 条 V
    for n in range(1, 24):
        # at least find key like 'validator_N_'
        assert re.search(rf"validator_{n}_", js), f"缺 validator_{n}_"


def test_js_refresh_includes_4_new_endpoints(js):
    """_refreshV14Modules 拉 thesis history / weekly latest / weekly history / health。"""
    assert "/api/theses/history" in js
    assert "/api/review/weekly/latest" in js
    assert "/api/review/weekly/history" in js
    assert "/api/health" in js


def test_js_no_new_dependencies(js):
    """硬约束:不引入新 JS 库。"""
    assert "require(" not in js
    assert "Chart" not in js


# ============================================================
# 6. 风格硬约束 + 现有模块保留
# ============================================================

def test_audit_card_style_consistency(html):
    """新模块 4+5 + RP banner 都用 audit-card / 现有色系。"""
    assert re.search(
        r'id="region-thesis-timeline"\s+class="audit-card"', html,
    )
    assert re.search(
        r'id="region-weekly-review"\s+class="audit-card"', html,
    )


def test_existing_regions_preserved(html):
    """§X:不删现有 12 卡 + 五层 6 卡。"""
    for region in ("region-1", "region-layer-cards", "region-4", "region-5"):
        assert f'id="{region}"' in html


# ============================================================
# Sprint 1.10-L commit 8(P1 #4)— app.js 读 state_machine.thesis / system_state 镜像
# ============================================================

def test_app_js_reads_state_machine_system_state(js):
    """K-A commit 7 加的 state_machine.system_state 字段在 app.js 真消费。"""
    assert "system_state" in js, "app.js 应消费 state_machine.system_state 镜像"
    # 应有 RP fallback path
    assert "review_pending" in js
    assert "_from_state_machine_mirror" in js, (
        "fallback 标记字段应在 app.js"
    )


def test_app_js_reads_state_machine_thesis_dict(js):
    """K-A commit 7 加的 state_machine.thesis dict 字段在 app.js 真消费。"""
    # 三字段 direction / lifecycle_stage / status 引用都在
    assert "smThesis.direction" in js
    assert "smThesis.lifecycle_stage" in js
    assert "smThesis.status" in js


def test_app_js_smSystemState_review_pending_fallback(js):
    """smSystemState='review_pending' 时合成 RP 占位(fallback 1)。"""
    # 模式:smSystemState === 'review_pending' check
    assert "smSystemState === 'review_pending'" in js


def test_app_js_smThesis_fallback_when_activeThesis_null(js):
    """activeThesis null 时,从 smThesis 顶上(fallback 2)。"""
    # 模式:!this.activeThesis && smThesis check
    assert "!this.activeThesis && smThesis" in js


def test_app_js_main_path_preserved(js):
    """主路径不变:/api/theses/active 仍是 activeThesis 来源(fallback 仅补)。"""
    assert "/api/theses/active" in js
    assert "/api/health" in js
    # health.review_pending 主路径
    assert "health.review_pending" in js or "health && health.review_pending" in js
