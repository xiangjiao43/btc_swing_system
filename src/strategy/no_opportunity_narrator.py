"""
no_opportunity_narrator.py — Sprint 2.7-no-opp:
为 8 种"AI 未被触发"场景生成完整 4 段 narrative。

输入:
  facts(_extract_facts 的输出)+ state(完整 strategy_state)
输出:
  dict 结构与 AI 真触发时 _validate_and_enforce_constraints 输出 100% 兼容,
  含 narrative / primary_drivers / counter_arguments / what_would_change_mind

设计原则:
- 100% 模板,零 AI 调用
- 文字风格遵循 docs/style_guide_human_readable.md
- 输出 4 段都非空,长度合理
- 8 种场景共用一个生成器入口,内部按 scenario 分支

8 种场景对应 _check_hard_constraints 优先级:
  1. extreme_event(L5 极端事件)
  2. protection(状态机=PROTECTION)
  3. cold_start(冷启动期)
  4. fallback_degraded(数据降级 L2/L3)
  5. post_protection_reassess(从保护态退出)
  6. permission_restricted(L3 permission ∈ {watch/protective/hold_only})
  7. position_cap_zero(L4 仓位上限 = 0)
  8. grade_none(以上都不命中,但机会评级是 none)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# 8 种场景枚举
SCENARIO_COLD_START = "cold_start"
SCENARIO_EXTREME_EVENT = "extreme_event"
SCENARIO_PROTECTION = "protection"
SCENARIO_FALLBACK_DEGRADED = "fallback_degraded"
SCENARIO_POST_PROTECTION = "post_protection_reassess"
SCENARIO_PERMISSION_RESTRICTED = "permission_restricted"
SCENARIO_POSITION_CAP_ZERO = "position_cap_zero"
SCENARIO_GRADE_NONE = "grade_none"


def detect_scenario(facts: dict[str, Any], state: dict[str, Any]) -> str:
    """按 _check_hard_constraints 的优先级顺序识别场景。"""
    if facts.get("l5_extreme_event_detected"):
        return SCENARIO_EXTREME_EVENT
    if facts.get("state_machine_current") == "PROTECTION":
        return SCENARIO_PROTECTION
    if facts.get("cold_start_warming_up"):
        return SCENARIO_COLD_START
    fl = facts.get("fallback_level")
    if fl in ("level_2", "level_3", "l2", "l3", 2, 3):
        return SCENARIO_FALLBACK_DEGRADED
    if facts.get("state_machine_current") == "POST_PROTECTION_REASSESS":
        return SCENARIO_POST_PROTECTION
    perm = facts.get("l3_permission")
    if perm in ("watch", "protective", "hold_only"):
        return SCENARIO_PERMISSION_RESTRICTED
    cap = facts.get("l4_position_cap")
    if cap is not None and float(cap) <= 0.0:
        return SCENARIO_POSITION_CAP_ZERO
    return SCENARIO_GRADE_NONE


def generate_no_opportunity_narrative(
    facts: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    """生成完整 4 段 narrative,结构与 AI 真触发输出兼容。

    返回 dict 含:
      narrative: str(中文 3-5 句)
      primary_drivers: list[{text, evidence_ref}](≥3 条)
      counter_arguments: list[{text}](≥2 条)
      what_would_change_mind: list[str](≥3 条)
    """
    scenario = detect_scenario(facts, state)
    fn = _SCENARIO_GENERATORS.get(scenario, _gen_grade_none)
    return fn(facts, state)


# ============================================================
# 8 个场景生成函数
# ============================================================

def _gen_cold_start(facts: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    cold_start_meta = (state.get("meta") or {}).get("cold_start") or {}
    if not cold_start_meta:
        cold_start_meta = state.get("cold_start") or {}
    days_remaining = cold_start_meta.get("days_remaining")
    days_text = f"约 {days_remaining} 天" if days_remaining else "几天"

    narrative = (
        f"系统刚启动不久,数据基线还在建立中,这期间不参与任何开仓。"
        f"冷启动期满({days_text}后)开始,系统才能完整判断市场状态。"
        f"现阶段先把数据补齐、把指标算稳。"
    )
    return {
        "narrative": narrative,
        "primary_drivers": [
            {"text": "已开始采集链上、衍生品、宏观数据,数据池持续扩充中",
             "evidence_ref": None},
            {"text": "组合因子逐步上线计算(目前已可看到长周期位置、拥挤度等)",
             "evidence_ref": None},
            {"text": "冷启动期是系统纪律,不是判断保守 — 数据不全时强行决策风险更大",
             "evidence_ref": None},
        ],
        "counter_arguments": [
            {"text": "市场可能在冷启动期内出现大行情,系统会错过 — 这是设计上接受的代价"},
            {"text": "用户如果有强烈交易倾向,可参考下方各因子卡片自行判断,但系统不背书"},
        ],
        "what_would_change_mind": [
            "冷启动期天数计满(系统自动解除观察约束)",
            "ADX-14 / ATR 分位 / Swing 序列等关键指标全部就绪",
            "5 层证据全部输出健康状态(非冷启动)",
        ],
    }


def _gen_extreme_event(facts: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    narrative = (
        "已检测到极端宏观事件,系统强制进入保护流程,冻结所有新开仓。"
        "现阶段优先级是不亏钱,不是抓机会。"
        "等事件影响消化、宏观环境回归正常后,系统会从保护态退出,重新评估。"
    )
    return {
        "narrative": narrative,
        "primary_drivers": [
            {"text": "极端宏观事件检测=true,触发硬性保护机制",
             "evidence_ref": None},
            {"text": "极端事件期间风险资产相关性容易失常,常规策略不可靠",
             "evidence_ref": None},
            {"text": "保护态是系统兜底纪律,任何决策都不能覆盖",
             "evidence_ref": None},
        ],
        "counter_arguments": [
            {"text": "极端事件后偶尔有 V 形反弹,系统会错过 — 这是有意识的代价"},
            {"text": "如果用户已有持仓,需手动评估是否减仓 / 平仓,系统不会自动出场"},
        ],
        "what_would_change_mind": [
            "极端事件检测转为 false(事件主体影响消退)",
            "VIX 回落到 25 以下,DXY / US10Y 趋势止稳",
            "状态机从保护态进入重评期",
        ],
    }


def _gen_protection(facts: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    narrative = (
        "状态机当前处于保护态,所有新开仓被冻结。"
        "进入保护态可能是因为极端事件、严重数据问题或风险层强制触发。"
        "系统按建模 §5.5 走保护流程,等条件恢复后进入重评期。"
    )
    return {
        "narrative": narrative,
        "primary_drivers": [
            {"text": "状态机=保护态,所有新开仓硬性禁止", "evidence_ref": None},
            {"text": "保护态期间持仓只能减或平,不会扩仓", "evidence_ref": None},
            {"text": "进入保护态需要人工确认才能完全恢复(防止系统抖动)",
             "evidence_ref": None},
        ],
        "counter_arguments": [
            {"text": "保护态可能比实际风险情况更严格,某些机会会被错过"},
            {"text": "如果数据已恢复但保护态仍未解除,需用户手动复查触发原因"},
        ],
        "what_would_change_mind": [
            "事件结束 + 数据完整度恢复到健康阈值",
            "极端事件检测=false 持续至少一个 4H 周期",
            "状态机迁移到重评期(等观察期满后才能开新仓)",
        ],
    }


def _gen_fallback_degraded(facts: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    fl = facts.get("fallback_level") or "level_2"
    fl_label = {"level_2": "L2 中等降级", "level_3": "L3 严重降级",
                "l2": "L2 中等降级", "l3": "L3 严重降级",
                2: "L2 中等降级", 3: "L3 严重降级"}.get(fl, str(fl))
    narrative = (
        f"数据采集出现问题(降级状态:{fl_label}),系统已切换到降级保守模式。"
        "当基础数据不可信时,任何决策都不可靠 — 这时候保守观望是正确选择。"
        "等数据采集恢复正常后,系统会自动回到正常模式。"
    )
    return {
        "narrative": narrative,
        "primary_drivers": [
            {"text": "数据健康度告警,关键指标采集失败或延迟严重",
             "evidence_ref": None},
            {"text": "降级模式下硬性观望,持仓由系统单独评估",
             "evidence_ref": None},
            {"text": "数据降级是系统自我保护,优于用错误数据做错误决策",
             "evidence_ref": None},
        ],
        "counter_arguments": [
            {"text": "降级期间市场可能正常运行,系统会错过常规机会"},
            {"text": "如果降级持续超过 24 小时,需用户手动检查数据采集器状态"},
        ],
        "what_would_change_mind": [
            "数据源恢复(Glassnode / CoinGlass / Yahoo Finance / FRED 全部 200 OK)",
            "降级状态自动回到正常等级",
            "数据完整度回到健康阈值并稳定 1 个完整运行周期",
        ],
    }


def _gen_post_protection(facts: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    narrative = (
        "系统刚从保护态退出,进入重评期。"
        "重评期内强制只持仓不开新,即使有持仓也只能持有不能加仓,新仓必须等观察期满才能开。"
        "这是为了避免系统在事件刚平息时误判,过早重新激进。"
    )
    return {
        "narrative": narrative,
        "primary_drivers": [
            {"text": "刚从保护态退出,需观察至少一个完整 4H 周期",
             "evidence_ref": None},
            {"text": "重评期硬性禁止新开仓,只允许持有 / 减仓 / 离场 / 切换观察",
             "evidence_ref": None},
            {"text": "防止保护态结束后立刻反弹诱多 / 诱空",
             "evidence_ref": None},
        ],
        "counter_arguments": [
            {"text": "重评期内可能出现真实机会,系统会错过 — 这是为系统稳健性付出的代价"},
            {"text": "重评期到期后系统会重新评估全套证据,届时会给出明确方向"},
        ],
        "what_would_change_mind": [
            "重评期 4H 周期满 + 5 层证据齐备且健康",
            "状态机自动迁移到无持仓状态(可以重新规划新机会)",
            "机会层重新出现高 / 中等级机会触发开仓入口",
        ],
    }


def _gen_permission_restricted(facts: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    perm = facts.get("l3_permission")
    perm_label = {
        "watch": "仅观察,不开仓",
        "protective": "保护性减仓",
        "hold_only": "仅持仓不开新",
    }.get(perm, "受限")

    perm_chain = (state.get("evidence_reports") or {}).get("layer_4") or {}
    perm_chain = perm_chain.get("permission_chain") or {}
    suggestions = perm_chain.get("suggestions") or {}
    tightest_source = "风险层 + 宏观层综合归并(取最严档)"
    if suggestions:
        tightest_source = "风险层 + 宏观层归并(已识别多个收紧因素)"

    narrative = (
        f"执行许可被收紧到「{perm_label}」,系统不允许新开仓。"
        f"这是 {tightest_source} 的结果 — 风险层、拥挤度、宏观或事件中至少有一项在告警。"
        f"系统按建模 §4.5.6 取最严档执行,直到收紧因素解除。"
    )
    return {
        "narrative": narrative,
        "primary_drivers": [
            {"text": f"当前执行许可={perm_label},硬性禁止开新仓",
             "evidence_ref": None},
            {"text": "执行许可是多因子归并的结果,不是单一因素决定",
             "evidence_ref": None},
            {"text": "系统在风险因素解除前不会主动放宽,这是建模 §4.5.6 的硬纪律",
             "evidence_ref": None},
        ],
        "counter_arguments": [
            {"text": "权限收紧期间可能错过真实机会,这是系统设计的代价"},
            {"text": "用户可手动检查风险层 + 宏观层各因子,确认收紧的具体原因"},
        ],
        "what_would_change_mind": [
            "整体风险等级回到低 / 适中(目前可能偏高或高)",
            "拥挤度回到正常档(评分 ≤ 3)",
            "宏观逆风评分 ≥ -1(顺风或中性)+ 未来 72 小时内无 FOMC / CPI / NFP 重大事件",
        ],
    }


def _gen_position_cap_zero(facts: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    narrative = (
        "风险层把建议仓位上限压到 0%,系统不允许任何新开仓。"
        "通常是整体风险等级=critical 或多个收紧乘数累加导致硬触底。"
        "在风险因素解除前,系统强制保护现金。"
    )
    return {
        "narrative": narrative,
        "primary_drivers": [
            {"text": "建议仓位上限=0%,硬性禁止仓位 > 0", "evidence_ref": None},
            {"text": "风险层乘数累乘后小于 15% 硬下限,触发 critical 例外",
             "evidence_ref": None},
            {"text": "现金为王是当前最稳健选择", "evidence_ref": None},
        ],
        "counter_arguments": [
            {"text": "极端风险评估可能过于保守,某些机会会被完全屏蔽"},
            {"text": "用户可参考风险标签了解具体收紧因子"},
        ],
        "what_would_change_mind": [
            "整体风险等级从 critical 回到 high 或 elevated",
            "拥挤度 / 事件风险 / 宏观逆风至少一个回到中性档",
            "建议仓位上限合成结果 ≥ 15% 硬下限",
        ],
    }


def _gen_grade_none(facts: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """最复杂场景:综合 L1-L5 各层状态做"为什么没机会"的解释。"""
    es = state.get("evidence_summary") or state.get("evidence_reports") or {}
    l1 = es.get("layer_1") or {}
    l2 = es.get("layer_2") or {}
    l3 = es.get("layer_3") or {}
    l5 = es.get("layer_5") or {}

    l1_regime = l1.get("regime") or l1.get("regime_primary")
    l1_human = {
        "trend_up": "上升趋势已确立",
        "trend_down": "下跌趋势已确立",
        "transition_up": "趋势在转向多头但还没站稳",
        "transition_down": "趋势在转向空头但还没站稳",
        "range_high": "高位震荡",
        "range_mid": "中位震荡",
        "range_low": "低位震荡",
        "chaos": "市场失序",
        "unclear_insufficient": "市场状态数据不足",
    }.get(l1_regime, "市场状态不明")

    l2_stance = l2.get("stance")
    l2_human = {
        "bullish": "倾向看多",
        "bearish": "倾向看空",
        "neutral": "方向不明",
    }.get(l2_stance, "方向数据不足")

    l5_stance = l5.get("macro_stance") or l5.get("macro_environment")
    l5_human = {
        "risk_on": "宏观顺风",
        "risk_neutral": "宏观中性",
        "neutral": "宏观中性",
        "risk_off": "宏观逆风",
        "extreme_risk_off": "宏观极端避险",
        "unclear": "宏观环境不明",
    }.get(l5_stance, "宏观数据未就绪")

    narrative = (
        f"系统暂无符合开仓条件的机会。当前市场状态:{l1_human};方向判断:{l2_human};"
        f"宏观环境:{l5_human}。这种组合下,机会层判定为「无机会」,系统按纪律保持观望。"
        f"这不是判断保守,而是规则要求的最低开仓门槛没满足 — 错过比做错便宜。"
    )

    primary_drivers = [
        {"text": f"市场状态:{l1_human}", "evidence_ref": None},
        {"text": f"方向判断:{l2_human}(信心未达动态门槛)",
         "evidence_ref": None},
        {"text": f"宏观背景:{l5_human}", "evidence_ref": None},
    ]

    counter_arguments = [
        {"text": "长周期判断可能仍在支持(可参考下方组合因子卡片中的「长周期位置」)"},
        {"text": "短期波动可能给人错觉,但短期信号不能单独触发系统决策"},
    ]

    rt = l3.get("rule_trace") or {}
    upgrade_conds = rt.get("upgrade_conditions") or []
    if len(upgrade_conds) >= 3:
        what_would_change_mind = list(upgrade_conds)[:5]
    else:
        what_would_change_mind = [
            "做多信心达到 55% 以上(牛市早期门槛),或做空信心达到 75%",
            "趋势状态稳定(不再处于「过渡期」或「混乱态」)",
            "波段位置出现「初段」或「中段」,长周期判断明确(非「不明朗」)",
        ]

    return {
        "narrative": narrative,
        "primary_drivers": primary_drivers,
        "counter_arguments": counter_arguments,
        "what_would_change_mind": what_would_change_mind,
    }


_SCENARIO_GENERATORS = {
    SCENARIO_COLD_START: _gen_cold_start,
    SCENARIO_EXTREME_EVENT: _gen_extreme_event,
    SCENARIO_PROTECTION: _gen_protection,
    SCENARIO_FALLBACK_DEGRADED: _gen_fallback_degraded,
    SCENARIO_POST_PROTECTION: _gen_post_protection,
    SCENARIO_PERMISSION_RESTRICTED: _gen_permission_restricted,
    SCENARIO_POSITION_CAP_ZERO: _gen_position_cap_zero,
    SCENARIO_GRADE_NONE: _gen_grade_none,
}
