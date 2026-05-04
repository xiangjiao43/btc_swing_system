"""
no_opportunity_narrator.py — Sprint 2.7-no-opp + Sprint 1.5m 重写。

为 8 种"AI 未被触发"场景生成 4 段交易员 brief:
  【结构】当前 3-5 个关键因子的值 + 历史位置(picker 选)
  【解读】多空力量对比 / 因子共振或矛盾,2-3 句
  【关键】1 个最影响判断的信号 + 它的含义
  【结论】系统为什么这样判断 + 改变条件

输入:
  facts(_extract_facts 的输出)+ state(完整 strategy_state)
输出:
  dict 与 AI 真触发时 _validate_and_enforce_constraints 输出 100% 兼容,
  含 narrative / primary_drivers / counter_arguments / what_would_change_mind

设计原则(对齐建模 §2.5):
- 100% 模板 + factor_picker 规则化打分,**禁 AI**
- 文字风格遵循 docs/style_guide_human_readable.md 交易员叙事
- 8 种场景共用 picker;每场景按自己的核心论据生成不同 narrative

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

from .factor_picker import pick_key_factors

logger = logging.getLogger(__name__)


# 7 种 active 场景枚举(Sprint 1.10-K-A commit 12 §X:删 SCENARIO_COLD_START 常量,
# commit 11 删 _gen_cold_start + commit 12 grep 0 import 后清理)
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
    # Sprint 1.10-J commit 6 §X:删 SCENARIO_COLD_START 路由
    # (v1.4 §11.2 删 cold_start;cold_start_warming_up 永远 False)
    # SCENARIO_COLD_START + _gen_cold_start 函数留 1.10-K 跟 SCENARIO_POST_PROTECTION
    # 一起整删(narrator 改造一次到位)
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
    """生成完整 4 段 narrative(【结构】【解读】【关键】【结论】)。"""
    scenario = detect_scenario(facts, state)
    fn = _SCENARIO_GENERATORS.get(scenario, _gen_grade_none)
    out = fn(facts, state)
    # 统一兜底:确保 schema 合规(≥3 drivers / ≥2 counters / ≥3 conditions)
    return _ensure_schema_minimums(out, scenario)


def _ensure_schema_minimums(
    out: dict[str, Any], scenario: str,
) -> dict[str, Any]:
    """填充少于 schema 要求的字段(防 picker 选不出足够时的边界场景)。"""
    drivers = list(out.get("primary_drivers") or [])
    while len(drivers) < 3:
        drivers.append({
            "text": f"场景={scenario};picker 数据不足,使用兜底论据",
            "evidence_ref": None,
        })
    out["primary_drivers"] = drivers[:5]

    counters = list(out.get("counter_arguments") or [])
    while len(counters) < 2:
        counters.append(
            {"text": "系统纪律可能比实际市场风险更严格,部分机会会被错过"}
        )
    out["counter_arguments"] = counters[:3]

    conds = list(out.get("what_would_change_mind") or [])
    while len(conds) < 3:
        conds.append("5 层证据全部 health_status=healthy + L3 grade ∈ {A, B, C}")
    out["what_would_change_mind"] = conds[:5]

    return out


# ============================================================
# 共用 helper:4 段拼接 + drivers 格式化
# ============================================================

def _make_4section_narrative(
    structure: str, interpretation: str, key: str, conclusion: str,
) -> str:
    """按【结构】【解读】【关键】【结论】4 段格式拼接 narrative。"""
    return (
        f"【结构】{structure}\n\n"
        f"【解读】{interpretation}\n\n"
        f"【关键】{key}\n\n"
        f"【结论】{conclusion}"
    )


def _factors_to_drivers(
    picked: list[dict[str, Any]], top_k: int = 3,
) -> list[dict[str, Any]]:
    """把 picker 选出的 top-K 因子转成 primary_drivers 列表(每条含数值)。"""
    drivers: list[dict[str, Any]] = []
    for f in picked[:top_k]:
        ctx = f.get("context") or ""
        ctx_str = f"({ctx})" if ctx else ""
        interp = f.get("interpretation") or ""
        text = (
            f"{f.get('name')}: {f.get('current_value')} {ctx_str} {interp}"
        ).strip()
        drivers.append({
            "text": text,
            "evidence_ref": f.get("evidence_ref"),
        })
    return drivers


def _structure_sentence(picked: list[dict[str, Any]], max_n: int = 5) -> str:
    """从 picker 列表构造【结构】段:列出 3-5 个因子的当前值 + 历史位置。"""
    if not picked:
        return "当前 5 层证据数据不足,无法给出量化结构快照。"
    parts: list[str] = []
    for f in picked[:max_n]:
        ctx = f.get("context") or ""
        ctx_str = f"({ctx})" if ctx else ""
        parts.append(
            f"{f.get('name')} {f.get('current_value')}{ctx_str}".strip()
        )
    return "、".join(parts) + "。"


def _interpretation_sentence(picked: list[dict[str, Any]]) -> str:
    """构造【解读】段:挑前 3 个因子的 interpretation 串成多空对比。"""
    interps = [f.get("interpretation") or "" for f in picked[:3]
               if f.get("interpretation")]
    if not interps:
        return "各因子信号偏弱,多空力量未明朗。"
    return ";".join(interps) + "。"


def _key_sentence(picked: list[dict[str, Any]]) -> str:
    """挑 picker 第一个(信号最强)做【关键】。"""
    if not picked:
        return "无单一突出信号。"
    f = picked[0]
    interp = f.get("interpretation") or ""
    return (
        f"{f.get('name')} {f.get('current_value')} 是当前最强信号 — {interp}。"
    ).strip()


# ============================================================
# 8 个场景生成函数
# ============================================================

# Sprint 1.10-K-A commit 11 §X(v1.4 §11.2):_gen_cold_start 函数整删
# (50 行)。死代码:detect_scenario(1.10-J commit 6)已断 cold_start_warming_up
# 输入条件,SCENARIO_COLD_START 永远不被路由,_gen_cold_start 0 caller。
# SCENARIO_COLD_START 常量先保留,等 commit 12 测试合理化时 grep 0 import 后再决定。


def _gen_extreme_event(
    facts: dict[str, Any], state: dict[str, Any],
) -> dict[str, Any]:
    l5 = (state.get("evidence_reports") or {}).get("layer_5") or {}
    event_details = l5.get("extreme_event_details") or {}
    event_name = event_details.get("event_name") or "极端宏观事件"
    severity = event_details.get("severity") or "high"

    picked = pick_key_factors(state, n=3, scenario=SCENARIO_EXTREME_EVENT)

    structure = (
        f"L5 检测到 {event_name}(严重度 {severity}),触发硬性保护。"
        f"次要论据:{_structure_sentence(picked, max_n=3)}"
        if picked else
        f"L5 检测到 {event_name}(严重度 {severity}),触发硬性保护。"
    )
    interpretation = (
        "极端事件下风险资产相关性会失常 — BTC 跟纳指、黄金、DXY 的"
        "60d 相关都可能瞬间反转,常规策略框架失效。"
    )
    key = "保护态是兜底纪律,任何评级 / 信心都不能覆盖,直到事件主体影响消退。"
    conclusion = (
        "等极端事件检测转 false + VIX 回落 < 25 + DXY/US10Y 趋势止稳 → "
        "状态机从保护态进入重评期,届时重新走完整 5 层证据。"
    )

    drivers = [{
        "text": f"极端事件 {event_name} 检测=true,严重度 {severity}",
        "evidence_ref": None,
    }]
    drivers.extend(_factors_to_drivers(picked, top_k=2))

    return {
        "narrative": _make_4section_narrative(
            structure, interpretation, key, conclusion,
        ),
        "primary_drivers": drivers[:5],
        "counter_arguments": [
            {"text": "极端事件后偶尔有 V 形反弹,系统会错过 — 这是有意识的代价"},
            {"text": "如已有持仓,需手动评估是否减仓 / 平仓,系统不自动出场"},
        ],
        "what_would_change_mind": [
            "极端事件检测转为 false(事件主体影响消退)",
            "VIX 回落到 25 以下,DXY / US10Y 趋势止稳",
            "状态机从保护态进入重评期(POST_PROTECTION_REASSESS)",
        ],
    }


def _gen_protection(
    facts: dict[str, Any], state: dict[str, Any],
) -> dict[str, Any]:
    risks = state.get("risks") or {}
    protection_reason = risks.get("protection_reason") or "风险层强制触发"
    picked = pick_key_factors(state, n=3, scenario=SCENARIO_PROTECTION)

    structure = (
        f"状态机进入保护态,触发原因:{protection_reason}。"
        f"市场快照:{_structure_sentence(picked, max_n=3)}"
        if picked else
        f"状态机进入保护态,触发原因:{protection_reason}。"
    )
    interpretation = (
        "保护态期间所有新开仓被冻结;持仓只能减或平,不能扩仓。"
        "进入保护态需要人工确认才能完全恢复(防止系统抖动)。"
    )
    key = "保护态优先级高于一切机会评级,触发条件解除前不放宽。"
    conclusion = (
        "等触发条件恢复 + 数据完整度回到健康 + 极端事件检测=false 持续"
        "至少一个 4H 周期 → 状态机迁移到重评期。"
    )

    drivers = [{
        "text": f"状态机=PROTECTION,原因:{protection_reason}",
        "evidence_ref": None,
    }]
    drivers.extend(_factors_to_drivers(picked, top_k=2))

    return {
        "narrative": _make_4section_narrative(
            structure, interpretation, key, conclusion,
        ),
        "primary_drivers": drivers[:5],
        "counter_arguments": [
            {"text": "保护态可能比实际风险情况更严格,某些机会会被错过"},
            {"text": "如数据已恢复但保护态仍未解除,需用户手动复查触发原因"},
        ],
        "what_would_change_mind": [
            "事件结束 + 数据完整度恢复到健康阈值",
            "极端事件检测=false 持续至少一个 4H 周期",
            "状态机迁移到重评期(POST_PROTECTION_REASSESS)",
        ],
    }


def _gen_fallback_degraded(
    facts: dict[str, Any], state: dict[str, Any],
) -> dict[str, Any]:
    fl = facts.get("fallback_level") or "level_2"
    fl_label = {
        "level_2": "L2 中等降级", "level_3": "L3 严重降级",
        "l2": "L2 中等降级", "l3": "L3 严重降级",
        2: "L2 中等降级", 3: "L3 严重降级",
    }.get(fl, str(fl))

    # 找哪些层 freshness 异常
    er = state.get("evidence_reports") or {}
    stale_layers: list[str] = []
    for lname in ("layer_1", "layer_2", "layer_3", "layer_4", "layer_5"):
        layer = er.get(lname) or {}
        fresh = layer.get("data_freshness")
        if isinstance(fresh, dict):
            status = fresh.get("status")
            if status in ("yellow", "red"):
                stale_layers.append(f"{lname}={status}")
        elif fresh in ("yellow", "red"):
            stale_layers.append(f"{lname}={fresh}")

    stale_str = "、".join(stale_layers) if stale_layers else "未识别具体层"
    picked = pick_key_factors(state, n=3, scenario=SCENARIO_FALLBACK_DEGRADED)

    structure = (
        f"数据采集异常:{fl_label}。陈旧层:{stale_str}。"
        f"picker 在数据降级下信号已下调({len(picked)} 个候选)。"
    )
    interpretation = (
        "基础数据不可信时,任何决策都不可靠 — funding / OI / MVRV / DXY 等"
        "因子值此刻不能直接当真,可能是 0、可能是上次的快照。"
    )
    key = (
        "数据降级是系统自我保护,优于'用错误数据做错误决策'。"
        "降级期间 picker 已自动给所有候选 -30 分,反映信号不可信。"
    )
    conclusion = (
        "等数据源恢复(Glassnode/CoinGlass/Yahoo Finance/FRED 全部 200 OK)"
        " + 数据完整度回到健康阈值并稳定 1 个完整运行周期 → 自动回到正常模式。"
    )

    drivers = [
        {"text": f"降级状态:{fl_label}", "evidence_ref": None},
        {"text": f"陈旧层:{stale_str}", "evidence_ref": None},
        {"text": "降级模式下硬性观望,持仓由系统单独评估", "evidence_ref": None},
    ]

    return {
        "narrative": _make_4section_narrative(
            structure, interpretation, key, conclusion,
        ),
        "primary_drivers": drivers,
        "counter_arguments": [
            {"text": "降级期间市场可能正常运行,系统会错过常规机会"},
            {"text": "降级持续超过 24 小时需用户手动检查数据采集器状态"},
        ],
        "what_would_change_mind": [
            "数据源恢复(Glassnode / CoinGlass / Yahoo Finance / FRED 全部 200 OK)",
            "降级状态自动回到正常等级(level_0 / level_1)",
            "数据完整度回到健康阈值并稳定 1 个完整运行周期",
        ],
    }


def _gen_post_protection(
    facts: dict[str, Any], state: dict[str, Any],
) -> dict[str, Any]:
    picked = pick_key_factors(state, n=4, scenario=SCENARIO_POST_PROTECTION)

    structure = (
        f"刚从保护态退出,需观察至少一个完整 4H 周期。"
        f"重评期市场新结构:{_structure_sentence(picked, max_n=4)}"
        if picked else
        "刚从保护态退出,需观察至少一个完整 4H 周期(数据快照仍在重建)。"
    )
    interpretation = _interpretation_sentence(picked) if picked else \
        "重评期内市场结构需要新的 4H bar 验证,不能直接套保护态前的判断。"
    key = (
        "重评期硬性禁止新开仓 — 防止保护态结束后立刻反弹诱多 / 诱空。"
        "持仓只能持有 / 减仓 / 离场。"
    )
    conclusion = (
        "重评期 4H 周期满 + 5 层证据齐备且健康 + 机会层重新出现 A/B/C 级 → "
        "状态机自动迁移到无持仓状态,可重新规划机会。"
    )

    drivers = _factors_to_drivers(picked, top_k=3)
    if not drivers:
        drivers = [
            {"text": "刚从保护态退出,重评期内只持仓不开新", "evidence_ref": None},
            {"text": "重评期硬性禁止新开仓(防止保护态结束诱多/诱空)",
             "evidence_ref": None},
            {"text": "需观察至少一个完整 4H 周期", "evidence_ref": None},
        ]

    return {
        "narrative": _make_4section_narrative(
            structure, interpretation, key, conclusion,
        ),
        "primary_drivers": drivers[:5],
        "counter_arguments": [
            {"text": "重评期内可能出现真实机会,系统会错过 — 为系统稳健付出的代价"},
            {"text": "重评期到期后系统会重新评估全套证据,届时给出明确方向"},
        ],
        "what_would_change_mind": [
            "重评期 4H 周期满 + 5 层证据齐备且健康",
            "状态机自动迁移到无持仓状态(可重新规划新机会)",
            "机会层重新出现高 / 中等级机会触发开仓入口",
        ],
    }


def _gen_permission_restricted(
    facts: dict[str, Any], state: dict[str, Any],
) -> dict[str, Any]:
    perm = facts.get("l3_permission")
    perm_label = {
        "watch": "仅观察",
        "protective": "保护性减仓",
        "hold_only": "仅持仓不开新",
    }.get(perm, "受限")

    # picker 选触发 permission 收紧的因子(scenario hint)
    picked = pick_key_factors(state, n=5, scenario=SCENARIO_PERMISSION_RESTRICTED)

    structure = _structure_sentence(picked, max_n=5)
    interpretation = _interpretation_sentence(picked)
    key = _key_sentence(picked) if picked else \
        "L4 风险归并 + L5 宏观 + 拥挤度 + 事件风险 中至少一项告警。"
    conclusion = (
        f"系统按建模 §4.5.6 取最严档({perm_label}),不允许新开仓。"
        f"等收紧因素逐项解除 — 触发档位降回正常 → permission 自动放宽。"
    )

    drivers = _factors_to_drivers(picked, top_k=3)
    if len(drivers) < 3:
        drivers.append({
            "text": f"当前 permission={perm_label},硬性禁止开新仓",
            "evidence_ref": None,
        })

    # counter_arguments:挑战当前判断的真实信号
    counter_args = _build_counter_arguments(picked)

    return {
        "narrative": _make_4section_narrative(
            structure, interpretation, key, conclusion,
        ),
        "primary_drivers": drivers[:5],
        "counter_arguments": counter_args,
        "what_would_change_mind": _build_change_conditions(picked, perm),
    }


def _gen_position_cap_zero(
    facts: dict[str, Any], state: dict[str, Any],
) -> dict[str, Any]:
    picked = pick_key_factors(state, n=5, scenario=SCENARIO_POSITION_CAP_ZERO)

    structure = _structure_sentence(picked, max_n=5)
    interpretation = (
        f"L4 仓位上限合成结果 = 0%(整体风险 critical 或多个收紧乘数累乘"
        "穿透 15% 硬下限)。"
    )
    if picked:
        interpretation += _interpretation_sentence(picked)

    key = _key_sentence(picked) if picked else \
        "L4 风险等级 critical 是关键开关,强制保护现金。"
    conclusion = (
        "等整体风险等级从 critical 回到 elevated 或 high + "
        "拥挤度 / 事件风险 / 宏观逆风至少一个回到中性 → 仓位上限合成 ≥ 15% 硬下限,"
        "重新允许开仓。"
    )

    drivers = _factors_to_drivers(picked, top_k=3)
    if len(drivers) < 3:
        drivers.append({
            "text": "L4 position_cap=0%,触发 critical 例外",
            "evidence_ref": None,
        })

    return {
        "narrative": _make_4section_narrative(
            structure, interpretation, key, conclusion,
        ),
        "primary_drivers": drivers[:5],
        "counter_arguments": [
            {"text": "极端风险评估可能过于保守,某些机会会被完全屏蔽"},
            {"text": "用户可参考风险标签了解具体收紧因子"},
        ],
        "what_would_change_mind": _build_change_conditions(
            picked, perm=None, cap_zero=True,
        ),
    }


def _gen_grade_none(
    facts: dict[str, Any], state: dict[str, Any],
) -> dict[str, Any]:
    """最常见场景:状态机=FLAT + grade=none + permission=watch 等。"""
    picked = pick_key_factors(state, n=5, scenario=SCENARIO_GRADE_NONE)

    structure = _structure_sentence(picked, max_n=5)
    interpretation = _interpretation_sentence(picked) if picked else \
        "5 层证据未达到机会触发组合(stance + grade + permission 任一未达)。"
    key = _key_sentence(picked) if picked else \
        "L3 机会层判定为 none,任何方向都缺信心。"

    # L3 升级条件(若有)
    es = state.get("evidence_summary") or state.get("evidence_reports") or {}
    l3 = es.get("layer_3") or {}
    rt = l3.get("rule_trace") or {}
    upgrade_conds = rt.get("upgrade_conditions") or []
    cond_str = (
        ",或者 ".join(upgrade_conds[:2]) if upgrade_conds else
        "做多信心 ≥ 0.55(牛市早期门槛)或做空 ≥ 0.75 + 趋势状态稳定"
    )
    conclusion = (
        f"系统按纪律保持观望 — '错过'比'做错'便宜。"
        f"判断会改变当:{cond_str}。"
    )

    drivers = _factors_to_drivers(picked, top_k=3)
    if not drivers:
        drivers = [
            {"text": "L1/L2/L5 证据组合未达开仓门槛", "evidence_ref": None},
            {"text": "stance_confidence 未达动态门槛", "evidence_ref": None},
            {"text": "L3 grade=none(规则层判档,无 AI 介入)",
             "evidence_ref": None},
        ]

    counter_args = _build_counter_arguments(picked)

    if upgrade_conds and len(upgrade_conds) >= 3:
        change_conds = list(upgrade_conds)[:5]
    else:
        change_conds = _build_change_conditions(picked, perm=None)

    return {
        "narrative": _make_4section_narrative(
            structure, interpretation, key, conclusion,
        ),
        "primary_drivers": drivers[:5],
        "counter_arguments": counter_args,
        "what_would_change_mind": change_conds,
    }


# ============================================================
# counter_arguments / change_conditions 构造器
# ============================================================

def _build_counter_arguments(
    picked: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """构造"挑战当前判断的真实信号"。每条含具体数值或事实。"""
    out: list[dict[str, Any]] = []
    # 找潜在反转信号:如 LSR 24h 大幅变化 / SOPR < 1 / OI 缩
    for f in picked:
        name = f.get("name") or ""
        val = f.get("current_value") or ""
        if "LSR" in name or "多空比 24h 变化" in name:
            out.append({
                "text": f"{name} {val} 是潜在反转信号:如 OI 同步缩,"
                        "可能是空头平仓非加仓",
            })
        elif "SOPR" in name and "0.99" in str(val) or "SOPR" in name:
            out.append({
                "text": f"{name} {val} < 1 说明在割肉,空头力竭可能临近",
            })
        elif "未平仓合约 24h 变化" in name:
            out.append({
                "text": f"{name} {val} 与价格方向若背离,可能预示假突破",
            })
        if len(out) >= 2:
            break

    # 兜底:至少 2 条
    if len(out) < 2:
        out.extend([
            {"text": "权限收紧期间可能错过真实机会(系统设计代价)"},
            {"text": "用户可手动检查 L4 风险层 + L5 宏观 + 拥挤度因子,确认收紧具体原因"},
        ])
    return out[:3]


def _build_change_conditions(
    picked: list[dict[str, Any]],
    perm: str | None = None,
    cap_zero: bool = False,
) -> list[str]:
    """构造"改变判断的具体可观测条件"。每条带数值阈值。"""
    conds: list[str] = []

    # 从 picked 因子构造对应的"反转条件"
    for f in picked[:3]:
        name = f.get("name") or ""
        if "资金费率" in name and "30 日分位" not in name:
            conds.append("funding 收敛到 ±0.1% 以内(杠杆消退)")
        elif "30 日分位" in name:
            conds.append("funding 30d 分位回到 25-75 中性区")
        elif "多空比" in name:
            conds.append("LSR 持续 > 1.2 + OI 同步上升(空头确认翻多)")
        elif "未平仓合约" in name:
            conds.append("OI 24h 变化连续 3 根稳定 ±2% 以内(持仓稳定)")
        elif name == "crowding":
            conds.append("拥挤度回到正常档(评分 ≤ 6)")
        elif name == "macro_headwind":
            conds.append("宏观逆风评分 ≥ -1(顺风或中性) + DXY 20d 变化转负")
        elif name == "event_risk":
            conds.append("未来 72h 内 FOMC / CPI / NFP / PCE 全部安全度过")
        elif "SOPR" in name:
            conds.append("SOPR 回到 ≥ 1(市场停止割肉)持续 ≥ 3 个 daily bar")
        elif "MVRV" in name:
            conds.append("MVRV-Z 回到中性区(0.5-3)")

    # 通用兜底
    if perm in ("watch", "protective", "hold_only"):
        if "整体风险等级" not in " ".join(conds):
            conds.append("L4 整体风险等级回到低 / 适中(目前偏高或高)")
    if cap_zero:
        conds.append("L4 整体风险从 critical 回到 elevated 或 high")
    if not conds:
        conds = [
            "做多信心 ≥ 0.55(牛市早期门槛)或做空 ≥ 0.75",
            "趋势状态稳定(不再处于「过渡期」或「混乱态」)",
            "波段位置出现「初段」或「中段」,长周期判断明确",
        ]
    # 去重
    seen: set[str] = set()
    deduped: list[str] = []
    for c in conds:
        if c not in seen:
            seen.add(c)
            deduped.append(c)
    # 最少 3 条
    while len(deduped) < 3:
        deduped.append("5 层证据全部 health_status=healthy + L3 grade ∈ {A, B, C}")
    return deduped[:5]


# Sprint 1.10-K-A commit 11 §X:删 SCENARIO_COLD_START key
# (_gen_cold_start 已删,无 handler;detect_scenario 永远不返此 scenario,注册无意义)
_SCENARIO_GENERATORS = {
    SCENARIO_EXTREME_EVENT: _gen_extreme_event,
    SCENARIO_PROTECTION: _gen_protection,
    SCENARIO_FALLBACK_DEGRADED: _gen_fallback_degraded,
    SCENARIO_POST_PROTECTION: _gen_post_protection,
    SCENARIO_PERMISSION_RESTRICTED: _gen_permission_restricted,
    SCENARIO_POSITION_CAP_ZERO: _gen_position_cap_zero,
    SCENARIO_GRADE_NONE: _gen_grade_none,
}
