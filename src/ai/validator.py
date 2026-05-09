"""src/ai/validator.py — Sprint 1.10-E Validator 24 条(v1.4 §3.4)。

D1=a 决策:原地重写,删除 v1.3 H1-H10 旧实施(class AdjudicatorValidator +
HOLDING_STATES + ILLEGAL_TRANSITIONS + 14 档迁移检查)。

新接口:
  validate_master_output(master_output, context) → (validated, constraint_activations)

24 条 Validator 模块级函数(每个签名相同):
  validator_<n>_<name>(master_output, context) → (modified_output, activations)

V24(meta)在 collect_meta_activations 实现:汇总 V1-V23 触发记录。

constraint_activations dict 写入 strategy_runs.constraint_activations_json
(migration 011),周复盘 AI(1.10-H)消费评估硬约束过严 / 过松。

Sprint 1.10-F 增加:
- V8/V9/V11/V21 失败标 `validator_<n>_needs_retry`(orchestrator 触发同 run 重试 1 次)
- V21 提供 `validator_21_retry_hint`(D3=b,塞 master prompt)
- V22 升级:从 strategy_runs.retry_log_json 滑动 72h 检测(D2=a)
  辅助 helper:count_master_failures_in_window()
- collect_meta_activations 聚合 needs_retry 决策 + retry_hints
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Optional


def _deep_copy_dict(d: Any) -> Any:
    """递归浅复制 dict / list,基本类型直接返回。"""
    if isinstance(d, dict):
        return {k: _deep_copy_dict(v) for k, v in d.items()}
    if isinstance(d, list):
        return [_deep_copy_dict(v) for v in d]
    return d


# ============================================================
# Sprint 1.10-E:Validator V1-V24(v1.4 §3.4)
# ============================================================
# 对齐 docs/modeling.md b25cfe6(v1.4)§3.4(7 类 24 条)
#
# 设计:
# - 每个 V<n> 是模块级纯函数 (master_output, context) → (modified_output, activations)
# - activations dict 累计后写入 strategy_runs.constraint_activations_json(V24 meta)
# - 旧 AdjudicatorValidator class(H1-H10)保留至 commit 4 删除(本 commit 双体系)
#
# 用户决策(D1=a / D2=c / D3=a / D4=a)落地:
# - D1 = a:原地重写 src/ai/validator.py(orchestrator import 不变)
# - D2 = c:V12 evidence_ref 轻量校验(非空 list[str]),严校验留 1.10-L
# - D3 = a:V13 字符串匹配(每条 evidence 含 input 字段名/数值 token)
# - D4 = a:V21 只识别(写 activations),重试机制留 1.10-F


# ----------------------------------------------------------------
# 资金安全类(V1-V5,继承 v1.3 + 微调)
# ----------------------------------------------------------------

def _extract_level_price(x: Any) -> Optional[float]:
    """从 hard_invalidation_levels 单元素抽 price。

    v1.4 L4 schema 输出 list of dict({price, type, description, distance_pct});
    历史/单测可能传 list of float。兼容两种,保留 dict 元信息(由调用者处理)。
    None / 解析失败返 None。
    """
    if x is None:
        return None
    if isinstance(x, dict):
        p = x.get("price")
        if p is None:
            return None
        try:
            return float(p)
        except (TypeError, ValueError):
            return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def validator_1_stop_loss(
    master_output: dict[str, Any], context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """V1:stop_loss 必须从 hard_invalidation_levels 选(§3.4.1)。

    失败处理:强制覆盖为 hard_invalidation_levels[0].price,notes 添加
    `stop_loss_overridden_by_validator`。

    Sprint J:兼容 v1.4 L4 schema(list of dict {price, type, ...})与
    历史 list of float — 通过 _extract_level_price 抽 price 字段。

    Returns: (modified_output, {validator_1_stop_loss_overridden: bool})
    """
    out = dict(master_output)
    activations = {"validator_1_stop_loss_overridden": False}
    new_thesis = out.get("new_thesis") or {}
    if not new_thesis:
        return out, activations
    sl_obj = new_thesis.get("stop_loss") or {}
    sl_price = sl_obj.get("price")
    levels = context.get("l4_hard_invalidation_levels") or []
    if sl_price is None or not levels:
        return out, activations
    levels_floats = [
        p for p in (_extract_level_price(x) for x in levels) if p is not None
    ]
    if not levels_floats:
        return out, activations
    if not any(abs(float(sl_price) - lv) < 1e-6 for lv in levels_floats):
        new_thesis = dict(new_thesis)
        new_thesis["stop_loss"] = {"price": levels_floats[0],
                                    "size_pct": sl_obj.get("size_pct", 100)}
        out["new_thesis"] = new_thesis
        activations["validator_1_stop_loss_overridden"] = True
        notes = list(out.get("notes") or [])
        notes.append("stop_loss_overridden_by_validator")
        out["notes"] = notes
    return out, activations


def validator_2_position_cap(
    master_output: dict[str, Any], context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """V2:max_position_size_pct ≤ position_cap_base(§3.4.1)。

    失败:强制 cap,notes 添加 `position_capped_by_validator`。
    """
    out = dict(master_output)
    activations = {"validator_2_position_capped": False}
    cap_base = context.get("l4_position_cap_base")
    if cap_base is None:
        return out, activations
    cap_base = float(cap_base)
    new_thesis = out.get("new_thesis") or {}
    entry_orders = list(new_thesis.get("entry_orders") or [])
    if not entry_orders:
        return out, activations
    # max size_pct(单笔)
    max_size = max(float(o.get("size_pct") or 0) / 100.0 for o in entry_orders)
    if max_size > cap_base + 1e-9:
        # 按比例 cap 每个 entry order
        ratio = cap_base / max_size
        new_orders = [
            {**o, "size_pct": round(float(o["size_pct"]) * ratio, 4)}
            for o in entry_orders
        ]
        new_thesis = dict(new_thesis)
        new_thesis["entry_orders"] = new_orders
        out["new_thesis"] = new_thesis
        activations["validator_2_position_capped"] = True
        notes = list(out.get("notes") or [])
        notes.append("position_capped_by_validator")
        out["notes"] = notes
    return out, activations


def validator_3_entry_size_normalized(
    master_output: dict[str, Any], context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """V3:mode=new_thesis 时 entry_orders 总 size_pct ≤ 100(§3.4.1)。

    失败:按比例缩到 100,notes 添加 `entry_size_normalized`。
    """
    out = dict(master_output)
    activations = {"validator_3_entry_size_normalized": False}
    if out.get("mode") != "new_thesis":
        return out, activations
    new_thesis = out.get("new_thesis") or {}
    entry_orders = list(new_thesis.get("entry_orders") or [])
    if not entry_orders:
        return out, activations
    total = sum(float(o.get("size_pct") or 0) for o in entry_orders)
    if total > 100.0 + 1e-9:
        ratio = 100.0 / total
        new_orders = [
            {**o, "size_pct": round(float(o["size_pct"]) * ratio, 4)}
            for o in entry_orders
        ]
        new_thesis = dict(new_thesis)
        new_thesis["entry_orders"] = new_orders
        out["new_thesis"] = new_thesis
        activations["validator_3_entry_size_normalized"] = True
        notes = list(out.get("notes") or [])
        notes.append("entry_size_normalized")
        out["notes"] = notes
    return out, activations


def validator_4_protection_blocked(
    master_output: dict[str, Any], context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """V4:PROTECTION 状态不允许新 thesis / 不允许 trade_plan(§3.4.1)。

    失败:强制 mode=silent_cooldown,trade_plan 强制 null。
    """
    out = dict(master_output)
    activations = {"validator_4_protection_blocked": False}
    if not bool(context.get("in_protection")):
        return out, activations
    if out.get("mode") == "new_thesis":
        out["mode"] = "silent_cooldown"
        out["silent_reason"] = "PROTECTION 状态强制 silent_cooldown(Validator 4)"
        out.pop("new_thesis", None)
        activations["validator_4_protection_blocked"] = True
        notes = list(out.get("notes") or [])
        notes.append("protection_blocked_new_thesis")
        out["notes"] = notes
    return out, activations


# 5 类 grade-permission 合法表(§3.4.1 V5)
_GRADE_PERMISSION_LEGAL = {
    "A": {"can_open", "cautious_open"},
    "B": {"cautious_open", "ambush_only"},
    "C": {"ambush_only"},          # C 级强制 ambush_only(继承 v1.3)
    "none": set(),                  # none 不允许创建 thesis
}


def validator_5_grade_permission_lock(
    master_output: dict[str, Any], context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """V5:grade 与 thesis 创建 / execution_permission 对应关系强制(§3.4.1)。

    - grade=none → 不允许创建 thesis(强制 silent_cooldown)
    - grade=A → permission ∈ {can_open, cautious_open}
    - grade=B → permission ∈ {cautious_open, ambush_only}
    - grade=C → permission = ambush_only
    失败:覆盖 permission(C 强制 ambush_only),或强制 silent。
    """
    out = dict(master_output)
    activations = {"validator_5_grade_permission_lock": False}
    if out.get("mode") != "new_thesis":
        return out, activations
    grade = (context.get("l3_grade") or "none").upper() if isinstance(
        context.get("l3_grade"), str) else "none"
    if grade.lower() == "none":
        # 强制 silent
        out["mode"] = "silent_cooldown"
        out["silent_reason"] = "L3 grade=none 不允许创建 thesis(Validator 5)"
        out.pop("new_thesis", None)
        activations["validator_5_grade_permission_lock"] = True
        notes = list(out.get("notes") or [])
        notes.append("permission_overridden_for_grade_none")
        out["notes"] = notes
        return out, activations
    legal = _GRADE_PERMISSION_LEGAL.get(grade, set())
    if not legal:
        return out, activations
    new_thesis = out.get("new_thesis") or {}
    perm = new_thesis.get("execution_permission")
    if perm not in legal:
        new_thesis = dict(new_thesis)
        # C 级强制 ambush_only;其他取 legal 中第一个
        target = "ambush_only" if grade == "C" else sorted(legal)[0]
        new_thesis["execution_permission"] = target
        out["new_thesis"] = new_thesis
        activations["validator_5_grade_permission_lock"] = True
        notes = list(out.get("notes") or [])
        notes.append(f"permission_overridden_for_grade_{grade}")
        out["notes"] = notes
    return out, activations


# ----------------------------------------------------------------
# thesis 主线锁类(V6-V9,v1.4 新增)
# ----------------------------------------------------------------

def validator_6_thesis_lock(
    master_output: dict[str, Any], context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """V6:有 active_thesis 时 mode 必须是 evaluate_existing 或 silent_cooldown(§3.4.2)。

    失败:强制 mode=evaluate_existing,丢弃 new_thesis 内容。
    """
    out = dict(master_output)
    activations = {"validator_6_thesis_lock": False}
    has_active = context.get("active_thesis") is not None
    if has_active and out.get("mode") == "new_thesis":
        out["mode"] = "evaluate_existing"
        out.pop("new_thesis", None)
        # 给一个最小 thesis_assessment,用 mostly 保守
        if "thesis_assessment" not in out:
            out["thesis_assessment"] = {
                "still_valid": "mostly",
                "which_break_triggered": None,
                "reasoning": "Validator 6 thesis_lock 强制覆盖,master 试图出 new_thesis 但有 active",
                "stop_loss_adjustment": None,
                "objective_evidence": ["master_overridden_by_validator_6"],
            }
        activations["validator_6_thesis_lock"] = True
        notes = list(out.get("notes") or [])
        notes.append("master_new_thesis_blocked_by_validator_6_active_thesis_exists")
        out["notes"] = notes
    return out, activations


def validator_7_invalidation_check(
    master_output: dict[str, Any], context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """V7:still_valid=invalidated 时必须填 which_break_triggered + 必须是
    active_thesis.break_conditions 中已客观触发的某条(§3.4.2)。

    失败:降级为 weakened,notes 添加 `invalidation_rejected_no_break_triggered`。
    """
    out = dict(master_output)
    activations = {"validator_7_invalidation_check": False}
    if out.get("mode") != "evaluate_existing":
        return out, activations
    ta = out.get("thesis_assessment") or {}
    if ta.get("still_valid") != "invalidated":
        return out, activations
    which = ta.get("which_break_triggered")
    active_thesis = context.get("active_thesis") or {}
    breaks = active_thesis.get("break_conditions") or []
    # 检查 which 是否在 break_conditions 中(允许子串匹配,AI 可能精简表达)
    matched = False
    if which and isinstance(which, str):
        matched = any(
            isinstance(b, str) and (b == which or which in b or b in which)
            for b in breaks
        )
    if not matched:
        # 降级
        ta = dict(ta)
        ta["still_valid"] = "weakened"
        out["thesis_assessment"] = ta
        activations["validator_7_invalidation_check"] = True
        notes = list(out.get("notes") or [])
        notes.append("invalidation_rejected_no_break_triggered")
        out["notes"] = notes
    return out, activations


# 主观词汇黑名单(V8 客观性检测,启发式)
_SUBJECTIVE_KEYWORDS = (
    "情绪", "感觉", "可能", "也许", "似乎", "好像", "应该", "建议",
    "趋势反转", "宏观恶化", "市场转空", "市场转多",
)


def _is_objective_break(condition: str) -> bool:
    """启发式:含数字 / 价格 / 指标名 / 'L1-L5' / 时间窗口 → 客观;
    含主观词 → 主观。
    """
    if not isinstance(condition, str) or not condition.strip():
        return False
    s = condition
    # 含主观词 → 拒
    if any(kw in s for kw in _SUBJECTIVE_KEYWORDS):
        return False
    # 含数字 → 客观可判定
    import re
    if re.search(r"\d", s):
        return True
    # 含 L1-L5 / 触发 / 收盘 / 突破 等结构化词 → 客观
    structured = ("L1", "L2", "L3", "L4", "L5", "extreme_event",
                  "break", "1D 收盘", "1H 收盘", "4H 收盘", "突破",
                  "跌破", "持续")
    if any(kw in s for kw in structured):
        return True
    return False


def validator_8_break_objectivity(
    master_output: dict[str, Any], context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """V8:new_thesis 时 break_conditions 必须 ≥ 3 条且全部客观可判定(§3.4.2)。

    Sprint 1.10-F:失败 → 标 needs_retry,orchestrator 触发同 run 重试 1 次。
    """
    out = dict(master_output)
    activations = {"validator_8_break_objectivity": False}
    if out.get("mode") != "new_thesis":
        return out, activations
    new_thesis = out.get("new_thesis") or {}
    breaks = new_thesis.get("break_conditions") or []
    if len(breaks) < 3 or not all(_is_objective_break(b) for b in breaks):
        activations["validator_8_break_objectivity"] = True
        activations["validator_8_needs_retry"] = True
        notes = list(out.get("notes") or [])
        notes.append("v8_break_objectivity_violation_needs_retry")
        out["notes"] = notes
    return out, activations


def validator_9_break_distance(
    master_output: dict[str, Any], context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """V9:new_thesis 时 break_conditions 距当前距离合理性(§3.4.2)。

    - 价格类 break:距当前 ≤ 20%
    - 指标类(DXY/VIX 等):≤ 15%
    - 事件类(L5/macro):不限
    失败:重试 1 次(留 1.10-F),本 sprint 只识别 + 标 activations。
    """
    out = dict(master_output)
    activations = {"validator_9_break_distance": False}
    if out.get("mode") != "new_thesis":
        return out, activations
    new_thesis = out.get("new_thesis") or {}
    breaks = new_thesis.get("break_conditions") or []
    current_btc = context.get("current_btc_price")
    violation = False
    import re
    for b in breaks:
        if not isinstance(b, str):
            continue
        # 事件类:不限距离
        if any(kw in b for kw in ("L5", "extreme_event", "事件",
                                    "FOMC", "CPI", "NFP")):
            continue
        # 价格类:含 BTC 价位(5 位数字 60000-200000 范围)
        m = re.search(r"\b(\d{5,6})\b", b)
        if m and current_btc:
            price_in_break = float(m.group(1))
            if 50000 <= price_in_break <= 200000:
                # 价格类 break
                dist_pct = abs(price_in_break - current_btc) / current_btc
                if dist_pct > 0.20:
                    violation = True
                    continue
        # 指标类(DXY/VIX 等):距当前 ≤ 15%(本 sprint 简化:无 DXY 当前值传入则跳过)
        # 留 1.10-L 真 API 时加详细
    if violation:
        activations["validator_9_break_distance"] = True
        activations["validator_9_needs_retry"] = True
        notes = list(out.get("notes") or [])
        notes.append("v9_break_distance_violation_needs_retry")
        out["notes"] = notes
    return out, activations


# ----------------------------------------------------------------
# grade 封闭类(V10-V11,v1.4 强化)
# ----------------------------------------------------------------

def validator_10_grade_lock(
    master_output: dict[str, Any], context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """V10:master 输出的 opportunity_grade 必须严格等于 L3 输出(§3.4.3)。

    失败:覆盖为 L3 给的,notes 添加 `grade_overridden_to_l3`。

    注:v1.4 master 输出 schema 不强制有 opportunity_grade 字段(只在 narrative
    用),但若 master 输出 narrative 隐含改 grade(如 new_thesis.confidence_score
    超出 L3 grade 范围)→ 触发本 V10。本 sprint 简化版:只检查 confidence_score 范围。
    """
    out = dict(master_output)
    activations = {"validator_10_grade_lock": False}
    if out.get("mode") != "new_thesis":
        return out, activations
    grade = context.get("l3_grade")
    if grade is None:
        return out, activations
    grade = grade.upper() if isinstance(grade, str) else None
    new_thesis = out.get("new_thesis") or {}
    score = new_thesis.get("confidence_score")
    if score is None:
        return out, activations
    score = int(score)
    # v1.4 §3.3.6:A→80-100, B→60-80, C→40-60, none→不创建
    expected_ranges = {"A": (80, 100), "B": (60, 80), "C": (40, 60)}
    rng = expected_ranges.get(grade)
    if rng and not (rng[0] <= score <= rng[1]):
        # 覆盖到 grade 中位
        new_thesis = dict(new_thesis)
        new_thesis["confidence_score"] = (rng[0] + rng[1]) // 2
        out["new_thesis"] = new_thesis
        activations["validator_10_grade_lock"] = True
        notes = list(out.get("notes") or [])
        notes.append(f"grade_overridden_to_l3_{grade}")
        out["notes"] = notes
    return out, activations


def validator_11_direction_lock(
    master_output: dict[str, Any], context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """V11:mode=evaluate_existing 时,master 不能改 active_thesis.direction(§3.4.3)。

    失败:重试 1 次(留 1.10-F),本 sprint 只识别 + 标 activations。
    注意:thesis_assessment schema 不直接含 direction,本检查针对 narrative
    含 'flip' / '反向' 等 hint 的简化检测。生产严校验留 1.10-L。
    """
    out = dict(master_output)
    activations = {"validator_11_direction_lock": False}
    if out.get("mode") != "evaluate_existing":
        return out, activations
    active_thesis = context.get("active_thesis") or {}
    if not active_thesis:
        return out, activations
    direction = active_thesis.get("direction")
    if direction not in ("long", "short"):
        return out, activations
    # 检测 narrative 含相反方向的明示(简化启发式)
    narrative = (out.get("narrative") or "")
    one_line = (out.get("one_line_summary") or "")
    text = narrative + " " + one_line
    opposite_words = {
        "long": ("做空", "翻空", "反手做空", "卖出"),
        "short": ("做多", "翻多", "反手做多", "买入"),
    }
    if any(w in text for w in opposite_words.get(direction, ())):
        activations["validator_11_direction_lock"] = True
        activations["validator_11_needs_retry"] = True
        notes = list(out.get("notes") or [])
        notes.append("v11_direction_change_attempt_needs_retry")
        out["notes"] = notes
    return out, activations


# ----------------------------------------------------------------
# evidence 真实性类(V12,本 sprint 轻量;V13/V14 在 commit 3)
# ----------------------------------------------------------------

def validator_12_evidence_real(
    master_output: dict[str, Any], context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """V12:evidence_ref 必须在 evidence_cards 真实存在(§3.4.4)。

    **D2=c 决策**:本 sprint 只做轻量校验(non-empty list[str]),
    严校验(每条 ref 真在 evidence_cards 中)留 1.10-L 端到端 sprint。

    失败处理(本 sprint):删除非法项,notes 添加 `missing_evidence_ref`。
    """
    out = dict(master_output)
    activations = {"validator_12_evidence_real": False}
    refs = out.get("evidence_ref")
    if refs is None:
        return out, activations
    if not isinstance(refs, list):
        out["evidence_ref"] = []
        activations["validator_12_evidence_real"] = True
        notes = list(out.get("notes") or [])
        notes.append("missing_evidence_ref_not_a_list")
        out["notes"] = notes
        return out, activations
    # 删除非 str / 空 str
    cleaned = [r for r in refs if isinstance(r, str) and r.strip()]
    if len(cleaned) != len(refs):
        out["evidence_ref"] = cleaned
        activations["validator_12_evidence_real"] = True
        notes = list(out.get("notes") or [])
        notes.append("missing_evidence_ref_invalid_items_removed")
        out["notes"] = notes
    return out, activations


# ----------------------------------------------------------------
# evidence 真实性 / 信心质量(V13-V17,§3.4.4-§3.4.5)
# ----------------------------------------------------------------

def _objective_evidence_tokens_from_context(context: dict) -> set[str]:
    """提取 input context 中可能在 objective_evidence 引用的字段名 / 数值 token。

    D3=a 字符串匹配:每条 evidence 必须含 input 中某字段名或数值。
    """
    tokens: set[str] = set()
    # 字段名(常见)
    field_names = (
        "DXY", "VIX", "L1", "L2", "L3", "L4", "L5",
        "regime", "stance", "grade", "funding", "OI", "open_interest",
        "stop_loss", "BTC", "EMA", "ATR", "ADX", "MVRV", "NUPL",
        "thesis", "break_conditions",
    )
    tokens.update(field_names)
    # 从 layer outputs 提取数值
    for layer_key in ("l1_output", "l2_output", "l3_output", "l4_output", "l5_output"):
        layer = context.get(layer_key) or {}
        if isinstance(layer, dict):
            for v in layer.values():
                if isinstance(v, (int, float)):
                    # 截短到 4 位有效数字
                    tokens.add(str(v))
                    tokens.add(str(int(v)))
                elif isinstance(v, str) and v:
                    tokens.add(v)
    # 从 active_thesis 提取
    at = context.get("active_thesis") or {}
    if isinstance(at, dict):
        for v in at.values():
            if isinstance(v, (int, float)):
                tokens.add(str(v))
                tokens.add(str(int(v)))
            elif isinstance(v, str) and v:
                tokens.add(v)
    # 从 current_position 提取
    cp = context.get("current_position") or {}
    if isinstance(cp, dict):
        for v in cp.values():
            if isinstance(v, (int, float)):
                tokens.add(str(v))
                tokens.add(str(int(v)))
    # current_btc_price
    cbp = context.get("current_btc_price")
    if cbp is not None:
        tokens.add(str(cbp))
        tokens.add(str(int(cbp)))
    return tokens


def validator_13_objective_evidence(
    master_output: dict[str, Any], context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """V13:objective_evidence 必须引用 input 真实字段值(D3=a 字符串匹配,§3.4.4)。

    每条 evidence 必须含 input context 中某个字段名或数值 token。
    失败:删除该项,notes 添加 `missing_objective_evidence_token`(本 sprint 不重试,
    严校验 + 重试留 1.10-F + 1.10-L)。
    """
    out = dict(master_output)
    activations = {"validator_13_objective_evidence": False}
    # 收集 master_output 中所有 objective_evidence(可能在 thesis_assessment / new_thesis / 顶层)
    candidates = []
    if isinstance(out.get("thesis_assessment"), dict):
        oe = out["thesis_assessment"].get("objective_evidence") or []
        if isinstance(oe, list):
            candidates.extend([("thesis_assessment", i, e) for i, e in enumerate(oe)])
    if isinstance(out.get("new_thesis"), dict):
        oe = out["new_thesis"].get("objective_evidence") or []
        if isinstance(oe, list):
            candidates.extend([("new_thesis", i, e) for i, e in enumerate(oe)])
    if not candidates:
        return out, activations

    tokens = _objective_evidence_tokens_from_context(context)
    invalid_count = 0
    for path, idx, e in candidates:
        if not isinstance(e, str) or not e.strip():
            invalid_count += 1
            continue
        if not any(tok in e for tok in tokens if tok):
            invalid_count += 1

    if invalid_count > 0:
        activations["validator_13_objective_evidence"] = True
        notes = list(out.get("notes") or [])
        notes.append(
            f"v13_objective_evidence_token_missing_{invalid_count}_items"
        )
        out["notes"] = notes
    return out, activations


def validator_14_counter_argument(
    master_output: dict[str, Any], context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """V14:narrative 必须含至少 1 条 counter_arguments(强制自我审查,§3.4.4)。

    失败:notes 添加 `missing_counter_argument`,不强制覆盖(留 master AI 重试)。
    """
    out = dict(master_output)
    activations = {"validator_14_counter_argument": False}
    counters = out.get("counter_arguments")
    if not isinstance(counters, list) or len([
        c for c in counters if isinstance(c, str) and c.strip()
        or isinstance(c, dict) and c.get("text")
    ]) < 1:
        activations["validator_14_counter_argument"] = True
        notes = list(out.get("notes") or [])
        notes.append("missing_counter_argument")
        out["notes"] = notes
    return out, activations


def validator_15_confidence_cap(
    master_output: dict[str, Any], context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """V15:confidence ≤ data_completeness × historical_precedent_match(§3.4.5)。

    Fallback Level 1+ 时 confidence 必须 < 0.7。
    失败:cap 到合法值,notes 添加 `confidence_capped`。
    """
    out = dict(master_output)
    activations = {"validator_15_confidence_capped": False, "validator_15_capped_value": None}
    # 提取 confidence(thesis_assessment / new_thesis / 顶层)
    confidence = None
    confidence_path = None
    if isinstance(out.get("new_thesis"), dict):
        c = out["new_thesis"].get("confidence_score")
        if c is not None:
            try:
                confidence = float(c) / 100.0  # 0-100 → 0-1
                confidence_path = ("new_thesis", "confidence_score", True)  # 保留 0-100
            except (ValueError, TypeError):
                pass
    if confidence is None:
        return out, activations

    dc = float(context.get("data_completeness") or 1.0)  # 0-1
    hpm = float(context.get("historical_precedent_match") or 1.0)
    fallback_level = context.get("fallback_level")
    cap_max = dc * hpm
    if fallback_level and str(fallback_level) in ("level_1", "level_2", "level_3"):
        # 严格 < 0.7,cap 到 0.699(避免 round 边界 0.6999... → 0.70)
        cap_max = min(cap_max, 0.699)

    if confidence > cap_max + 1e-9:
        new_conf = cap_max
        if confidence_path[2]:  # 0-100 范围
            new_conf_val = round(new_conf * 100, 2)
        else:
            new_conf_val = round(new_conf, 4)
        if confidence_path[0] == "new_thesis":
            new_thesis = dict(out["new_thesis"])
            new_thesis[confidence_path[1]] = new_conf_val
            out["new_thesis"] = new_thesis
        activations["validator_15_confidence_capped"] = True
        activations["validator_15_capped_value"] = new_conf_val
        notes = list(out.get("notes") or [])
        notes.append("confidence_capped_by_validator_15")
        out["notes"] = notes
    return out, activations


def validator_16_change_mind(
    master_output: dict[str, Any], context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """V16:what_would_change_mind 必须 ≥ 3 条且全部客观可判定(§3.4.5)。

    失败:重试 1 次(留 1.10-F),本 sprint 只标 activations。
    """
    out = dict(master_output)
    activations = {"validator_16_change_mind": False}
    items = out.get("what_would_change_mind") or []
    valid = [i for i in items if isinstance(i, str) and i.strip()
             and _is_objective_break(i)]
    if len(valid) < 3:
        activations["validator_16_change_mind"] = True
        notes = list(out.get("notes") or [])
        notes.append(f"what_would_change_mind_insufficient_{len(valid)}_objective")
        out["notes"] = notes
    return out, activations


def validator_17_stop_tightening(
    master_output: dict[str, Any], context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """V17:weakened 状态 stop_loss 收紧上限(§3.4.5)。

    - 同一 thesis 内最多收紧 2 次
    - 新 stop_loss 距离不能高于初始 stop 距离的 50%
    失败:拒绝收紧,notes 添加 `stop_tightening_capped`。
    """
    out = dict(master_output)
    activations = {"validator_17_stop_tightening": False}
    if out.get("mode") != "evaluate_existing":
        return out, activations
    ta = out.get("thesis_assessment") or {}
    if ta.get("still_valid") != "weakened":
        return out, activations
    new_stop = ta.get("stop_loss_adjustment")
    if new_stop is None:
        return out, activations

    # 检查 1:历史收紧次数(从 context 读)
    tightening_count = int(context.get("stop_tightening_count_so_far") or 0)
    if tightening_count >= 2:
        ta = dict(ta)
        ta["stop_loss_adjustment"] = None
        out["thesis_assessment"] = ta
        activations["validator_17_stop_tightening"] = True
        notes = list(out.get("notes") or [])
        notes.append("stop_tightening_capped_already_2_times")
        out["notes"] = notes
        return out, activations

    # 检查 2:新 stop 距离不超过初始 50%
    initial_stop = context.get("initial_stop_loss_price")
    initial_avg = context.get("active_thesis_avg_price")
    if initial_stop is not None and initial_avg is not None:
        initial_dist = abs(float(initial_avg) - float(initial_stop)) / float(initial_avg)
        new_dist = abs(float(initial_avg) - float(new_stop)) / float(initial_avg)
        if new_dist < initial_dist * 0.5:
            # 收紧过多
            ta = dict(ta)
            ta["stop_loss_adjustment"] = None
            out["thesis_assessment"] = ta
            activations["validator_17_stop_tightening"] = True
            notes = list(out.get("notes") or [])
            notes.append("stop_tightening_capped_distance_below_50pct_initial")
            out["notes"] = notes
    return out, activations


# ----------------------------------------------------------------
# 系统级反复横跳类(V18-V20,FuseMonitor 包装,§3.4.6)
# ----------------------------------------------------------------

def validator_18_14d_fuse(
    master_output: dict[str, Any], context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """V18:14 天反复横跳熔断(§3.4.6)。

    包装 FuseMonitor.check_14d_fuse 结果(由调用方传 fuse_state 入 context):
    - 14d 内 thesis 完整周期 ≥ 2 → in_thesis_cycle_fuse(强制 FLAT 14 天)
    - 14d 内通道 C ≥ 2 → channel_c_disabled
    - 已在熔断期 + master 试图 new_thesis → 拒绝创建
    """
    out = dict(master_output)
    activations = {"validator_18_14d_fuse_active": False}
    fuse_state = context.get("fuse_state") or {}
    in_fuse = bool(fuse_state.get("in_thesis_cycle_fuse")) or bool(
        fuse_state.get("in_14d_fuse"),
    )
    if not in_fuse:
        return out, activations
    activations["validator_18_14d_fuse_active"] = True
    if out.get("mode") == "new_thesis":
        out["mode"] = "silent_cooldown"
        out["silent_reason"] = "14 天熔断期,拒绝创建 thesis(Validator 18)"
        out.pop("new_thesis", None)
        notes = list(out.get("notes") or [])
        notes.append("v18_14d_fuse_blocked_new_thesis")
        out["notes"] = notes
    return out, activations


def validator_19_60d_cap(
    master_output: dict[str, Any], context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """V19:60 天 thesis 上限(§3.4.6)。

    包装 FuseMonitor.check_60d_cap 结果(由调用方传 thesis_60d_capped 入 context)。
    失败处理:挂单仍按 thesis 触发(由 1.10-C 实施),但不允许新加仓 / 调整 stop。
    本 V19 检测:active_thesis.is_60d_capped → 标 activations,后续 master 不允许
    出现 stop_loss_adjustment(由 V17 已部分覆盖)。
    """
    out = dict(master_output)
    activations = {"validator_19_60d_cap": False}
    active_thesis = context.get("active_thesis") or {}
    if not active_thesis.get("is_60d_capped"):
        return out, activations
    activations["validator_19_60d_cap"] = True
    # 60d-capped 时若 master 试图 stop_loss_adjustment → 拒
    if out.get("mode") == "evaluate_existing":
        ta = out.get("thesis_assessment") or {}
        if ta.get("stop_loss_adjustment") is not None:
            ta = dict(ta)
            ta["stop_loss_adjustment"] = None
            out["thesis_assessment"] = ta
            notes = list(out.get("notes") or [])
            notes.append("v19_60d_cap_blocked_stop_adjustment")
            out["notes"] = notes
    return out, activations


def validator_20_consecutive_fuse(
    master_output: dict[str, Any], context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """V20:连续 2 次 14 天熔断 → review_pending(§3.4.6)。

    包装 FuseMonitor.check_consecutive_fuse 结果(由调用方传入 context)。
    本 V20 检测:consecutive_fuse_triggered=True → 标 activations。
    实际"进 review_pending"动作由 1.10-C review_pending.enter_review_pending 完成。
    """
    out = dict(master_output)
    activations = {"validator_20_consecutive_fuse": False}
    if not bool(context.get("consecutive_fuse_triggered")):
        return out, activations
    activations["validator_20_consecutive_fuse"] = True
    notes = list(out.get("notes") or [])
    notes.append("v20_consecutive_fuse_triggers_review_pending")
    out["notes"] = notes
    return out, activations


# ----------------------------------------------------------------
# master AI 软抗拒识别(V21-V22,§3.4.7)
# ----------------------------------------------------------------

def validator_21_soft_resistance(
    master_output: dict[str, Any], context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """V21:master AI 软抗拒识别(§3.4.7)。

    触发条件(全部满足):
    - active_thesis is None
    - cooldown_state.in_cooldown=False
    - fuse_state.in_14d_fuse=False
    - L3 grade ∈ {A, B, C}
    - master 输出 mode='silent_cooldown'(应该出 new_thesis)

    **D4=a 决策**:本 sprint 只识别(标 activations),重试机制留 1.10-F。
    """
    out = dict(master_output)
    activations = {"validator_21_soft_resistance": False}
    if out.get("mode") != "silent_cooldown":
        return out, activations
    if context.get("active_thesis") is not None:
        return out, activations
    cd = context.get("cooldown_state") or {}
    if cd.get("in_cooldown"):
        return out, activations
    fs = context.get("fuse_state") or {}
    if fs.get("in_14d_fuse") or fs.get("in_thesis_cycle_fuse"):
        return out, activations
    grade = context.get("l3_grade")
    if not isinstance(grade, str) or grade.upper() not in ("A", "B", "C"):
        return out, activations
    # 满足创建条件但 silent → 软抗拒
    activations["validator_21_soft_resistance"] = True
    activations["validator_21_needs_retry"] = True
    # D3=b:retry hint 文本(orchestrator 第二次调 master 时塞 prompt)
    activations["validator_21_retry_hint"] = (
        f"V21 软抗拒检测:active_thesis=None + cooldown=False + 14d_fuse=False + "
        f"L3 grade={grade} ∈ {{A,B,C}},应该出 new_thesis 而非 silent_cooldown。"
        f"请重新评估,若证据齐备且 risk_breakdown 在阈值内,务必输出 mode=new_thesis。"
    )
    notes = list(out.get("notes") or [])
    notes.append("v21_soft_resistance_detected_needs_retry")
    out["notes"] = notes
    return out, activations


def validator_22_3day_fail(
    master_output: dict[str, Any], context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """V22:master AI 滑动 72h 内 ≥ 3 次失败 → review_pending(§3.4.7)。

    Sprint 1.10-F D2=a + sliding 72h:
    - 优先用 context["master_failures_in_72h"](由 orchestrator 通过
      count_master_failures_in_window() 从 strategy_runs.retry_log_json 查询)
    - 兼容老字段 master_consecutive_failures(向后兼容,1.10-G 删)

    本 sprint 只识别(标 activations + needs_review_pending),
    review_pending 实际进入由调用方(orchestrator / scheduler)触发。
    """
    out = dict(master_output)
    activations = {"validator_22_3day_fail": False}
    fails_72h = context.get("master_failures_in_72h")
    if fails_72h is None:
        # 向后兼容旧字段
        fails_72h = int(context.get("master_consecutive_failures") or 0)
    if int(fails_72h) >= 3:
        activations["validator_22_3day_fail"] = True
        activations["validator_22_needs_review_pending"] = True
        activations["validator_22_failures_count"] = int(fails_72h)
        notes = list(out.get("notes") or [])
        notes.append("v22_3day_fail_triggers_review_pending")
        out["notes"] = notes
    return out, activations


# ----------------------------------------------------------------
# conflict_resolution(V23,§3.4.8)
# ----------------------------------------------------------------

def validator_23_conflict_resolution(
    master_output: dict[str, Any], context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """V23:必须输出 conflict_resolution 字段(可"无层间矛盾",§3.4.8)。

    失败:notes 添加 `conflict_resolution_missing`,不强制覆盖(留 master 重试)。

    注:v1.4 §3.3.6 的 master output schema 没有 conflict_resolution 顶层字段,
    本 V23 检测 narrative 含 "层间" / "冲突" / "矛盾" / "一致" 等关键词作 proxy。
    严校验留 1.10-L。
    """
    out = dict(master_output)
    activations = {"validator_23_conflict_missing": False}
    narrative = out.get("narrative") or ""
    one_line = out.get("one_line_summary") or ""
    text = narrative + " " + one_line
    keywords = ("层间", "矛盾", "冲突", "一致", "齐心", "分歧", "对齐")
    if not any(k in text for k in keywords):
        activations["validator_23_conflict_missing"] = True
        notes = list(out.get("notes") or [])
        notes.append("conflict_resolution_missing")
        out["notes"] = notes
    return out, activations


# ----------------------------------------------------------------
# Sprint E Step 4:VFactorGrain — 关键层 data_missing / degraded 时
# master 必须给保守策略
# ----------------------------------------------------------------

_KEY_LAYER_IDS: tuple[int, ...] = (1, 2, 4)  # L1 regime / L2 direction / L4 risk
_NON_KEY_LAYER_IDS: tuple[int, ...] = (5,)   # L5 仅 narrative 提及

_PERMISSION_RANK: dict[str, int] = {
    "watch":         0,
    "hold_only":     0,   # alias of watch for new positions
    "cautious_open": 1,
    "ambush_only":   1,
    "can_open":      2,
}


def _layer_data_missing(layer_output: dict[str, Any] | None) -> bool:
    if not isinstance(layer_output, dict):
        return False
    fg = layer_output.get("_factor_grain") or {}
    if fg.get("data_missing") is True:
        return True
    return str(layer_output.get("status") or "").endswith("data_missing")


def _layer_degraded(layer_output: dict[str, Any] | None) -> bool:
    if not isinstance(layer_output, dict):
        return False
    fg = layer_output.get("_factor_grain") or {}
    ratio = fg.get("fresh_ratio")
    if isinstance(ratio, (int, float)) and 0 < ratio < 1:
        return True
    status = str(layer_output.get("status") or "")
    return status.startswith("degraded") and not status.endswith("data_missing")


def validator_factor_grain(
    master_output: dict[str, Any], context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Sprint E Step 4:关键层(L1/L2/L4)data_missing 或 degraded → master
    必须给保守策略;否则标 needs_retry。

    检测维度:
      - 关键层任一 data_missing → execution_permission 必须 ∈ {watch, hold_only}
        (空仓 = silent_cooldown 或 watch;持仓 = hold_only / 不动仓位)
      - 关键层任一 degraded → execution_permission 不得高于 cautious_open
      - 持仓 + 关键层 data_missing → mode 必须不是 new_thesis(应是
        evaluate_existing 不动仓位 或 silent_cooldown)
    """
    out = dict(master_output)
    activations = {
        "validator_factor_grain_violation": False,
        "validator_factor_grain_reason": None,
    }

    layer_outputs = {
        1: context.get("l1_output"),
        2: context.get("l2_output"),
        3: context.get("l3_output"),
        4: context.get("l4_output"),
        5: context.get("l5_output"),
    }
    key_data_missing = [
        lid for lid in _KEY_LAYER_IDS if _layer_data_missing(layer_outputs.get(lid))
    ]
    key_degraded = [
        lid for lid in _KEY_LAYER_IDS if _layer_degraded(layer_outputs.get(lid))
    ]
    if not key_data_missing and not key_degraded:
        return out, activations

    mode = out.get("mode", "")
    has_active = context.get("active_thesis") is not None

    # 取 effective execution_permission(可能在 trade_plan / new_thesis 内)
    new_thesis = out.get("new_thesis") or {}
    perm = (
        new_thesis.get("execution_permission")
        or out.get("execution_permission")
        or ""
    )
    perm_rank = _PERMISSION_RANK.get(perm, 99)

    # ---- 关键层 data_missing 强约束 ----
    if key_data_missing:
        if not has_active and mode == "new_thesis":
            activations["validator_factor_grain_violation"] = True
            activations["validator_factor_grain_needs_retry"] = True
            activations["validator_factor_grain_reason"] = (
                f"key layer(s) {key_data_missing} data_missing 但 master 仍 new_thesis"
            )
        if perm and perm_rank > _PERMISSION_RANK["watch"]:
            activations["validator_factor_grain_violation"] = True
            activations["validator_factor_grain_needs_retry"] = True
            activations["validator_factor_grain_reason"] = (
                f"key layer(s) {key_data_missing} data_missing 但 "
                f"execution_permission='{perm}' > watch"
            )

    # ---- 关键层 degraded 软约束 ----
    if key_degraded and perm and perm_rank > _PERMISSION_RANK["cautious_open"]:
        activations["validator_factor_grain_violation"] = True
        activations["validator_factor_grain_needs_retry"] = True
        activations["validator_factor_grain_reason"] = (
            f"key layer(s) {key_degraded} degraded 但 "
            f"execution_permission='{perm}' > cautious_open"
        )

    if activations["validator_factor_grain_violation"]:
        notes = list(out.get("notes") or [])
        notes.append("factor_grain_master_violation_needs_retry")
        out["notes"] = notes

    return out, activations


# ----------------------------------------------------------------
# Sprint D Item 3:stale_disclosure(VStale,§AI 诚实)
# ----------------------------------------------------------------

_STALE_KEYWORDS: tuple[str, ...] = (
    "过期", "沿用", "stale", "Stale", "STALE",
    "数据老", "数据旧", "数据滞后",
)


def validator_stale_disclosure(
    master_output: dict[str, Any], context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Sprint D Item 3:任一数据源 is_stale=true 时,master narrative 必须明
    确提到"过期"/"沿用"/"stale"等关键词;不提 → 标 needs_retry。

    数据来自 context["data_freshness_summary"]:list[dict],每行有 is_stale。
    silent_cooldown mode 不强制(本来就保守);其他 mode 强制。
    """
    out = dict(master_output)
    activations = {"validator_stale_disclosure_missing": False}

    rows = context.get("data_freshness_summary") or []
    has_stale = any(bool(r.get("is_stale")) for r in rows if isinstance(r, dict))
    if not has_stale:
        return out, activations

    if out.get("mode") == "silent_cooldown":
        # silent 已保守,不强制;但仍记录 stale 状态
        activations["validator_stale_disclosure_missing"] = False
        return out, activations

    narrative = (out.get("narrative") or "")
    one_line = (out.get("one_line_summary") or "")
    text = narrative + " " + one_line
    if not any(k in text for k in _STALE_KEYWORDS):
        activations["validator_stale_disclosure_missing"] = True
        activations["validator_stale_disclosure_needs_retry"] = True
        notes = list(out.get("notes") or [])
        notes.append("stale_disclosure_missing_needs_retry")
        out["notes"] = notes
    return out, activations


# ============================================================
# V24:Meta 约束(灵魂条款,§3.4.9)
# ============================================================

# V1-V23 应用顺序(自然顺序;V18 后跑也无害,silent_cooldown 后续检查自动跳过)
# Sprint D Item 3:加 VStale(stale 数据披露纪律)在 V23 之后跑
_VALIDATOR_PIPELINE = [
    ("V1",  validator_1_stop_loss),
    ("V2",  validator_2_position_cap),
    ("V3",  validator_3_entry_size_normalized),
    ("V4",  validator_4_protection_blocked),
    ("V5",  validator_5_grade_permission_lock),
    ("V6",  validator_6_thesis_lock),
    ("V7",  validator_7_invalidation_check),
    ("V8",  validator_8_break_objectivity),
    ("V9",  validator_9_break_distance),
    ("V10", validator_10_grade_lock),
    ("V11", validator_11_direction_lock),
    ("V12", validator_12_evidence_real),
    ("V13", validator_13_objective_evidence),
    ("V14", validator_14_counter_argument),
    ("V15", validator_15_confidence_cap),
    ("V16", validator_16_change_mind),
    ("V17", validator_17_stop_tightening),
    ("V18", validator_18_14d_fuse),
    ("V19", validator_19_60d_cap),
    ("V20", validator_20_consecutive_fuse),
    ("V21", validator_21_soft_resistance),
    ("V22", validator_22_3day_fail),
    ("V23", validator_23_conflict_resolution),
    ("VStale", validator_stale_disclosure),         # Sprint D Item 3
    ("VFactorGrain", validator_factor_grain),       # Sprint E Step 4
]


# v1.4 §3.4.9 全 28 字段 default(false / None)— 周复盘 AI 期望全字段都在
# 即使本次未触发 → 写 false / None,便于 SQL 查询过滤
_DEFAULT_ACTIVATIONS_V24 = {
    "validator_1_stop_loss_overridden": False,
    "validator_2_position_capped": False,
    "validator_3_entry_size_normalized": False,
    "validator_4_protection_blocked": False,
    "validator_5_grade_permission_lock": False,
    "validator_6_thesis_lock": False,
    "validator_7_invalidation_check": False,
    "validator_8_break_objectivity": False,
    "validator_9_break_distance": False,
    "validator_10_grade_lock": False,
    "validator_11_direction_lock": False,
    "validator_12_evidence_real": False,
    "validator_13_objective_evidence": False,
    "validator_14_counter_argument": False,
    "validator_15_confidence_capped": False,
    "validator_15_capped_value": None,
    "validator_16_change_mind": False,
    "validator_17_stop_tightening": False,
    "validator_18_14d_fuse_active": False,
    "validator_19_60d_cap": False,
    "validator_20_consecutive_fuse": False,
    "validator_21_soft_resistance": False,
    "validator_22_3day_fail": False,
    "validator_23_conflict_missing": False,
    # Sprint D Item 3:stale 数据披露纪律(_needs_retry 是临时聚合用,不持久化)
    "validator_stale_disclosure_missing": False,
    # Sprint E Step 4:因子粒度 — 关键层 stale 时 master 必须给保守策略
    "validator_factor_grain_violation": False,
    "validator_factor_grain_reason": None,
    # 额外 meta 字段(§3.4.9 末段)
    "position_cap_compressed": None,
    "thesis_lock_active": False,
    "in_cooldown": False,
    "cooldown_remaining_hours": 0,
    # Sprint 1.10-F:retry 决策聚合(供 orchestrator 决定是否同 run 重试 master)
    "validator_needs_retry": False,
    "validator_retry_hints": [],
    # V22:72h 内 master 失败次数(由 orchestrator 注入 context 后 V22 写回)
    "validator_22_failures_count": 0,
    "validator_22_needs_review_pending": False,
}


def collect_meta_activations(
    raw_activations: dict[str, Any],
    *,
    master_output: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """V24 meta(§3.4.9):汇总 V1-V23 触发记录 + 计算额外 meta 字段。

    Args:
        raw_activations: V1-V23 累计的 activations(dict 合并)
        master_output: 经 V1-V23 处理后的 output(用于额外 meta 字段提取)
        context: validator context

    Returns:
        完整 28 字段 dict,可直接写入 strategy_runs.constraint_activations_json
    """
    out = dict(_DEFAULT_ACTIVATIONS_V24)
    out.update(raw_activations)

    # 额外 meta:position_cap_compressed = master_output.new_thesis.entry_orders 实际 max size
    new_thesis = master_output.get("new_thesis") or {}
    eorders = new_thesis.get("entry_orders") or []
    if eorders:
        max_size = max(float(o.get("size_pct") or 0) for o in eorders) / 100.0
        out["position_cap_compressed"] = round(max_size, 4)

    # thesis_lock_active = active_thesis 不为 None
    out["thesis_lock_active"] = context.get("active_thesis") is not None

    # in_cooldown / cooldown_remaining_hours
    cd = context.get("cooldown_state") or {}
    out["in_cooldown"] = bool(cd.get("in_cooldown"))
    out["cooldown_remaining_hours"] = float(cd.get("cooldown_remaining_hours") or 0)

    # Sprint 1.10-F:聚合 V8/V9/V11/V21 needs_retry → 一个总开关
    # Sprint D Item 3:加 VStale needs_retry
    _per_v_retry_keys = (
        "validator_8_needs_retry",
        "validator_9_needs_retry",
        "validator_11_needs_retry",
        "validator_21_needs_retry",
        "validator_stale_disclosure_needs_retry",
        "validator_factor_grain_needs_retry",     # Sprint E Step 4
    )
    needs_retry = any(bool(raw_activations.get(k)) for k in _per_v_retry_keys)
    out["validator_needs_retry"] = needs_retry
    # 收集所有 retry hints(目前仅 V21 提供 hint;V8/V9/V11/VStale 用 notes 中的标识)
    hints: list[str] = []
    if raw_activations.get("validator_21_retry_hint"):
        hints.append(raw_activations["validator_21_retry_hint"])
    if raw_activations.get("validator_stale_disclosure_needs_retry"):
        hints.append(
            "stale 数据披露:narrative 必须含「过期」/「沿用」/「stale」关键词"
        )
    if raw_activations.get("validator_factor_grain_needs_retry"):
        reason = raw_activations.get("validator_factor_grain_reason") or ""
        hints.append(
            f"因子粒度保险:关键层 stale 必须给保守 execution_permission "
            f"(watch / cautious_open);{reason}"
        )
    out["validator_retry_hints"] = hints
    # 剥离 per-V 临时 _needs_retry / _retry_hint 字段(已聚合到 *_needs_retry /
    # *_retry_hints,不重复持久化到 constraint_activations_json)
    for k in _per_v_retry_keys:
        out.pop(k, None)
    out.pop("validator_21_retry_hint", None)

    return out


def validate_master_output(
    master_output: dict[str, Any],
    context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """统一 Validator 入口(v1.4 §3.4 全 24 条)。

    Args:
        master_output: master AI 原始输出 dict(含 mode 字段)
        context: dict 含
            - l1_output / l2_output / l3_output / l4_output / l5_output
            - l3_grade (str: 'A','B','C','none')
            - l4_hard_invalidation_levels (list[dict {price, type, description,
              distance_from_current_pct}] — v1.4 L4 schema;V1 兼容 list[float])
            - l4_position_cap_base (float)
            - active_thesis (None or dict, 含 break_conditions / direction / is_60d_capped)
            - current_position (None or dict)
            - cooldown_state (dict 含 in_cooldown / cooldown_remaining_hours)
            - fuse_state (dict 含 in_14d_fuse / in_thesis_cycle_fuse)
            - in_protection (bool)
            - consecutive_fuse_triggered (bool)
            - data_completeness / historical_precedent_match (float 0-1)
            - fallback_level (str or None)
            - master_consecutive_failures (int)
            - current_btc_price (float)
            - stop_tightening_count_so_far (int)
            - initial_stop_loss_price / active_thesis_avg_price (float)

    Returns:
        (validated_output, constraint_activations)
        - validated_output: 经 V1-V23 应用后的 master_output(可能被覆盖)
        - constraint_activations: V24 meta dict,28 字段
          可直接 json.dumps 后写入 strategy_runs.constraint_activations_json
    """
    output = dict(master_output)
    raw_activations: dict[str, Any] = {}
    for _name, v_func in _VALIDATOR_PIPELINE:
        output, act = v_func(output, context)
        raw_activations.update(act)
    constraint_activations = collect_meta_activations(
        raw_activations,
        master_output=output,
        context=context,
    )
    return output, constraint_activations


# ============================================================
# Sprint 1.10-F:V22 SQL 滑动窗口检测 helper(D2=a)
# ============================================================

def count_master_failures_in_window(
    conn: sqlite3.Connection,
    window_hours: int = 72,
    *,
    now_utc: Optional[datetime] = None,
) -> int:
    """从 strategy_runs 表统计滑动窗口内 master AI 失败次数(v1.4 §3.4.7)。

    判定 master 失败的条件:retry_log_json 含 'master_fail' 或
    'thesis_aware_fallback_applied':true 或 'master_failed' 字符串。

    Args:
        conn: SQLite 连接(已连真 DB / 测试用内存 DB)
        window_hours: 滑动窗口长度,默认 72h(v1.4 §3.4.7)
        now_utc: 评估时点(测试可注入),默认 datetime.now(timezone.utc)

    Returns:
        窗口内 master 失败的 strategy_runs 行数
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    window_start = (now_utc - timedelta(hours=window_hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    try:
        # 同时匹配新格式(thesis_aware_fallback_applied)和老式标记(master_fail / master_failed)
        row = conn.execute(
            """
            SELECT COUNT(*) FROM strategy_runs
            WHERE generated_at_utc >= ?
              AND retry_log_json IS NOT NULL
              AND (
                  retry_log_json LIKE '%thesis_aware_fallback_applied%true%'
                  OR retry_log_json LIKE '%master_fail%'
                  OR retry_log_json LIKE '%master_failed%'
              )
            """,
            (window_start,),
        ).fetchone()
        return int(row[0]) if row else 0
    except sqlite3.OperationalError:
        # 表 / 列不存在(极早期 / 测试 DB)→ 0
        return 0
