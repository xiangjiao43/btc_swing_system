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
        trade_plan = validated.setdefault("trade_plan", {})
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
        pcf = validated.setdefault("position_cap_final", {})
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
            comp = pcf.setdefault("composition", {})
            comp["after_hard_floor"] = 0.15
            validated.setdefault("notes", []).append("ai_overridden_H3")

        # H4: extreme_event_detected=true → state 必须 PROTECTION
        if l5_output.get("extreme_event_detected") is True:
            st = validated.setdefault("state_transition", {})
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
