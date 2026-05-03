"""src/ai/validator.py — Sprint 1.8 Task C 主裁输出硬约束校验器。

对齐建模 v1.2 §6.5 + v1.3 主裁 prompt §13 H1-H10。

校验主裁(MasterAdjudicator)输出符合 10 条硬约束。违反时:
- 强制覆盖输出值(让最终输出始终合法)
- 记录 violations 列表(包含 rule / detail / auto_fix)
- 在 notes 标记 'ai_overridden_<rule>'

返回 {validated_output, violations, passed}。
"""

from __future__ import annotations

from typing import Any


HOLDING_STATES = {
    "LONG_HOLD", "LONG_TRIM", "SHORT_HOLD", "SHORT_TRIM",
    "LONG_OPEN", "SHORT_OPEN",
}

# H7 非法迁移(必须经 FLIP_WATCH)
ILLEGAL_TRANSITIONS = {
    ("LONG_EXIT", "SHORT_PLANNED"),
    ("LONG_EXIT", "LONG_PLANNED"),
    ("SHORT_EXIT", "LONG_PLANNED"),
    ("SHORT_EXIT", "SHORT_PLANNED"),
}


class AdjudicatorValidator:
    """对齐建模 v1.2 §6.5 + v1.3 主裁 prompt §13 H1-H10 硬约束。

    用法:
        v = AdjudicatorValidator()
        result = v.validate(master_output, l1, l2, l3, l4, l5, current_state)
        if result['passed']:
            ...  # 主裁输出无违反
        else:
            for vio in result['violations']:
                ...  # 记录 vio['rule'] / vio['detail'] / vio['auto_fix']
        final_output = result['validated_output']  # 修正后版本
    """

    def validate(
        self,
        master_output: dict[str, Any],
        l1_output: dict[str, Any],
        l2_output: dict[str, Any],
        l3_output: dict[str, Any],
        l4_output: dict[str, Any],
        l5_output: dict[str, Any],
        current_state: str,
    ) -> dict[str, Any]:
        """返回 {validated_output, violations, passed}。"""
        violations: list[dict[str, str]] = []
        # 深复制相关字段,避免 mutate 调用方
        validated = _deep_copy_dict(master_output)

        # H1: opportunity_grade 三重封闭(主裁不直接输出 grade,但
        # narrative 中不应误引用与 L3 不同的 grade — 软校验,记录但
        # 不强制覆盖文本)
        l3_grade = l3_output.get("opportunity_grade")
        narrative = validated.get("narrative", "") or ""
        # 简化:只检查是否在 narrative 中错误地把 grade 写成与 L3 不一致的等级
        # (例:L3=A 但 narrative 说"机会等级 B")
        if l3_grade and isinstance(narrative, str):
            for g in ("A", "B", "C", "none"):
                if g == l3_grade:
                    continue
                # 中文模式:"机会等级 X" / "grade X" / "X 级机会"
                patterns = [
                    f"机会等级 {g}",
                    f"grade {g}",
                    f"{g} 级机会",
                ]
                if any(p in narrative for p in patterns):
                    violations.append({
                        "rule": "H1",
                        "detail": (
                            f"narrative 引用 grade={g} 与 L3 grade={l3_grade} 不符"
                        ),
                        "auto_fix": "保留 narrative,在 notes 标记不一致",
                    })
                    validated.setdefault("notes", []).append(
                        "ai_overridden_H1_grade_inconsistent"
                    )
                    break

        # H2: stop_loss 必须从 L4.hard_invalidation_levels 中选
        # 1.8.2-I:master 在 FLAT 状态下可能输出 trade_plan: null,setdefault 不会覆盖 None
        trade_plan = validated.get("trade_plan") or {}
        validated["trade_plan"] = trade_plan
        stop_loss = trade_plan.get("stop_loss")
        l4_levels = l4_output.get("hard_invalidation_levels", []) or []
        l4_prices = []
        for lvl in l4_levels:
            if isinstance(lvl, dict) and "price" in lvl:
                try:
                    l4_prices.append(float(lvl["price"]))
                except (TypeError, ValueError):
                    pass
        if stop_loss is not None:
            try:
                stop_loss_f = float(stop_loss)
                if stop_loss_f not in l4_prices:
                    violations.append({
                        "rule": "H2",
                        "detail": (
                            f"stop_loss {stop_loss_f} 不在 L4 "
                            f"hard_invalidation_levels {l4_prices} 中"
                        ),
                        "auto_fix": (
                            f"使用 L4 第一个止损位 "
                            f"{l4_prices[0] if l4_prices else None}"
                        ),
                    })
                    if l4_prices:
                        trade_plan["stop_loss"] = l4_prices[0]
                    else:
                        trade_plan["stop_loss"] = None
                    validated.setdefault("notes", []).append(
                        "ai_overridden_H2"
                    )
            except (TypeError, ValueError):
                pass

        # H3: position_cap_final.value ≥ 0.15
        # 1.8.2-I:同上,master 可能输出 position_cap_final: null
        pcf = validated.get("position_cap_final") or {}
        validated["position_cap_final"] = pcf
        try:
            cap_value = float(pcf.get("value", 0))
        except (TypeError, ValueError):
            cap_value = 0.0
        if cap_value < 0.15:
            violations.append({
                "rule": "H3",
                "detail": (
                    f"position_cap_final.value {cap_value} < 0.15 硬下限"
                ),
                "auto_fix": "强制为 0.15",
            })
            pcf["value"] = 0.15
            # 1.8.2-I:同上,pcf 可能含 composition: null
            comp = pcf.get("composition") or {}
            pcf["composition"] = comp
            comp["after_hard_floor"] = 0.15
            validated.setdefault("notes", []).append("ai_overridden_H3")

        # H4: extreme_event_detected=true → state 必须 PROTECTION
        if l5_output.get("extreme_event_detected") is True:
            # 1.8.2-I:同上,master 可能输出 state_transition: null
            st = validated.get("state_transition") or {}
            validated["state_transition"] = st
            to_state = st.get("to_state")
            if to_state != "PROTECTION":
                violations.append({
                    "rule": "H4",
                    "detail": (
                        f"L5 extreme_event=true 但 to_state={to_state},"
                        f"非 PROTECTION"
                    ),
                    "auto_fix": "强制 to_state=PROTECTION + action=protective",
                })
                st["to_state"] = "PROTECTION"
                trade_plan["action"] = "protective"
                validated.setdefault("notes", []).append("ai_overridden_H4")

        # H5: L1=chaos → action 必须 watch/hold/protective/exit
        if l1_output.get("regime") == "chaos":
            action = trade_plan.get("action")
            if action in ("open", "add"):
                violations.append({
                    "rule": "H5",
                    "detail": f"L1=chaos 但 action={action},不允许开仓",
                    "auto_fix": "强制 action=watch",
                })
                if current_state in HOLDING_STATES:
                    trade_plan["action"] = "hold"
                else:
                    trade_plan["action"] = "watch"
                validated.setdefault("notes", []).append("ai_overridden_H5")

        # H6: L3=none → action 必须 watch/hold(不能开仓)
        if l3_output.get("opportunity_grade") == "none":
            action = trade_plan.get("action")
            if action in ("open", "add"):
                violations.append({
                    "rule": "H6",
                    "detail": f"L3=none 但 action={action},不允许开仓",
                    "auto_fix": "强制 action=watch / hold",
                })
                if current_state in HOLDING_STATES:
                    trade_plan["action"] = "hold"
                else:
                    trade_plan["action"] = "watch"
                validated.setdefault("notes", []).append("ai_overridden_H6")

        # H7: 状态迁移合法路径(禁止 EXIT 直跳 PLANNED)
        st = validated.setdefault("state_transition", {})
        from_s = st.get("from_state")
        to_s = st.get("to_state")
        if (from_s, to_s) in ILLEGAL_TRANSITIONS:
            violations.append({
                "rule": "H7",
                "detail": (
                    f"非法迁移 {from_s} → {to_s}(必须经 FLIP_WATCH)"
                ),
                "auto_fix": "强制 to_state=FLIP_WATCH",
            })
            st["to_state"] = "FLIP_WATCH"
            validated.setdefault("notes", []).append("ai_overridden_H7")

        # H8: position_size_pct ≤ position_cap_final.value
        try:
            cap_value = float(pcf.get("value", 0))
        except (TypeError, ValueError):
            cap_value = 0.0
        size_pct = trade_plan.get("position_size_pct")
        if size_pct is not None and cap_value > 0:
            try:
                size_pct_f = float(size_pct)
                if size_pct_f > cap_value + 1e-9:
                    violations.append({
                        "rule": "H8",
                        "detail": (
                            f"position_size_pct {size_pct_f} > "
                            f"position_cap {cap_value}"
                        ),
                        "auto_fix": f"强制 position_size_pct={cap_value}",
                    })
                    trade_plan["position_size_pct"] = cap_value
                    validated.setdefault("notes", []).append(
                        "ai_overridden_H8"
                    )
            except (TypeError, ValueError):
                pass

        # H9: counter_arguments ≥ 1 条
        counters = validated.get("counter_arguments")
        if not counters or not isinstance(counters, list) or len(counters) == 0:
            violations.append({
                "rule": "H9",
                "detail": "counter_arguments 为空,违反诚实纪律",
                "auto_fix": "添加默认 placeholder",
            })
            validated["counter_arguments"] = [
                "[Validator 注:主裁未提供反向论证,这是建模硬要求 H9 违反]"
            ]
            validated.setdefault("notes", []).append("ai_overridden_H9")

        # H10: confidence ≤ data_completeness/100 × min(L1-L5 confidence)
        try:
            master_conf = float(validated.get("confidence", 0))
        except (TypeError, ValueError):
            master_conf = 0.0
        try:
            data_pct = (
                float(validated.get("data_completeness_pct", 100)) / 100.0
            )
        except (TypeError, ValueError):
            data_pct = 1.0
        l_confs = []
        for layer_out in (l1_output, l2_output, l3_output,
                          l4_output, l5_output):
            try:
                c = float(layer_out.get("confidence", 1.0))
                l_confs.append(c)
            except (TypeError, ValueError):
                l_confs.append(1.0)
        max_allowed = data_pct * min(l_confs) if l_confs else 1.0
        # 1% 浮点容差(避免 round 抖动触发)
        if master_conf > max_allowed + 0.01:
            violations.append({
                "rule": "H10",
                "detail": (
                    f"confidence {master_conf} > {max_allowed:.4f} "
                    f"(data×min(L1-L5))"
                ),
                "auto_fix": f"强制 confidence={round(max_allowed, 2)}",
            })
            validated["confidence"] = round(max_allowed, 2)
            validated.setdefault("notes", []).append("ai_overridden_H10")

        return {
            "validated_output": validated,
            "violations": violations,
            "passed": len(violations) == 0,
        }


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

def validator_1_stop_loss(
    master_output: dict[str, Any], context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """V1:stop_loss 必须从 hard_invalidation_levels 选(§3.4.1)。

    失败处理:强制覆盖为 hard_invalidation_levels[0],notes 添加
    `stop_loss_overridden_by_validator`。

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
    levels_floats = [float(x) for x in levels if x is not None]
    if not levels_floats:
        return out, activations
    if not any(abs(float(sl_price) - lv) < 1e-6 for lv in levels_floats):
        # 覆盖
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

    失败:**重试 1 次**(留 1.10-F),本 sprint 只识别 + 标 activations。
    """
    out = dict(master_output)
    activations = {"validator_8_break_objectivity": False}
    if out.get("mode") != "new_thesis":
        return out, activations
    new_thesis = out.get("new_thesis") or {}
    breaks = new_thesis.get("break_conditions") or []
    if len(breaks) < 3 or not all(_is_objective_break(b) for b in breaks):
        activations["validator_8_break_objectivity"] = True
        notes = list(out.get("notes") or [])
        notes.append("v8_break_objectivity_violation_retry_pending_1.10_f")
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
        notes = list(out.get("notes") or [])
        notes.append("v9_break_distance_violation_retry_pending_1.10_f")
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
        notes = list(out.get("notes") or [])
        notes.append("v11_direction_change_attempt_retry_pending_1.10_f")
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
    notes = list(out.get("notes") or [])
    notes.append(
        "v21_soft_resistance_detected_retry_pending_1.10_f"
    )
    out["notes"] = notes
    return out, activations


def validator_22_3day_fail(
    master_output: dict[str, Any], context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """V22:master AI 连续 3 天失败 → review_pending(§3.4.7)。

    本 sprint 只识别(标 activations),实际进入 review_pending 由调用方触发。
    """
    out = dict(master_output)
    activations = {"validator_22_3day_fail": False}
    if int(context.get("master_consecutive_failures") or 0) >= 3:
        activations["validator_22_3day_fail"] = True
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
