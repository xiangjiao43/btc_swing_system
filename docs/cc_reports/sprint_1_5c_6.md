# Sprint 1.5c.6 — L5 AI 路径不要用空 dict 覆盖规则路径 structured_macro

**Date:** 2026-04-29
**Branch:** main
**Status:** ✅ 完成,4 个新测试 + 802/802 全量回归过

---

## 一、问题

1.5c.4 / 1.5c.5 修了 `_build_structured_macro_rule` helper 字段名 mismatch,
但 SSH 验证 structured_macro 仍然 `{}`。

**真相**:layer5_macro 当前走 AI 路径(`computation_method=ai_assisted`),
helper 在规则路径填好的 `structured_macro` 被 AI 返回的空 dict 直接覆盖。

证据(SSH 实测):
```
computation_method: ai_assisted
structured_macro: {}
notes: ['L5 AI assisted (§6.8); macro_headwind_score from AI']
```

AI prompt v0 阶段没要求填 `structured_macro`,所以 AI 返回 `{}` 也合规。
但 layer5_macro 老 update 是无条件覆盖:

```python
rule_output.update({
    ...
    "structured_macro": ai_out["structured_macro"],   # ← 即便 = {}
    ...
})
```

把规则路径填好的 DXY/US10Y/VIX/btc_nasdaq_corr 一并清空。

违反建模 §2.5 双轨原则:**规则数据是基础,AI 是修饰**。

---

## 二、改动

### 任务 A:`src/evidence/layer5_macro.py`

把 AI 成功后的 update 拆开:
- 其他字段(macro_stance / trend / score / tags / event_summaries / extreme_event /
  adjustment_guidance / computation_method)照旧覆盖
- **`structured_macro` 单独处理:merge 而非 replace**
  - AI 返回非空 dict → `{**base_sm, **ai_sm}`(AI 覆盖同名 key,新增 key 加入)
  - AI 返回 `{}` 或 None → 保留规则路径已填的产物

```python
ai_sm = ai_out.get("structured_macro") or {}
if isinstance(ai_sm, dict) and ai_sm:
    base_sm = rule_output.get("structured_macro") or {}
    rule_output["structured_macro"] = {**base_sm, **ai_sm}
# else:保留 rule_output["structured_macro"](即 _build_structured_macro_rule 填的)
```

---

## 三、测试

`tests/test_l5_ai_path_preserves_rule_macro.py`(4 测试):

| 测试 | 验证 |
|---|---|
| `test_ai_empty_structured_macro_preserves_rule_path` | **关键反退化**:AI 返回 `sm={}`(模拟生产实测)→ 规则路径填的 DXY/US10Y/VIX/btc_nasdaq_corr 4 类全保留 |
| `test_ai_with_structured_macro_merges` | AI 返回 `{AI_only_key, DXY=ai_overrides}` → 规则路径 US10Y/VIX/corr 仍在,DXY 被 AI 覆盖,新增 AI_only_key |
| `test_rule_path_alone_when_ai_disabled` | `_try_call_l5_ai` 返回 None → `computation_method=rule_based`,sm 仍含 4 类 |
| `test_pillars_l5_ok_after_ai_empty_sm_path` | 集成:AI 返回 `sm={}` + ai_assisted 路径 → `_pillars_l5` 仍 ok + interp 含 DXY 数值 |

测试用 `unittest.mock.patch` mock `_try_call_l5_ai`,真跑 `Layer5Macro.compute`
(120 天数据)。fixture `_ai_response_with_empty_sm` 直接拷贝生产实测的 AI 输出
形态(structured_macro={} 等关键字段)。

**回归**:全量 `pytest tests/` = **802 passed, 1 skipped, 4.93s**(798 + 4 新)。

---

## 四、用户验证脚本(SSH 部署后)

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service
sleep 5

.venv/bin/python -c "
import sqlite3, json
conn = sqlite3.connect('data/btc_strategy.db')
row = conn.execute(
    'SELECT full_state_json FROM strategy_runs '
    'ORDER BY reference_timestamp_utc DESC LIMIT 1'
).fetchone()
state = json.loads(row[0])
l5 = state['evidence_reports']['layer_5']
print('computation_method:', l5.get('computation_method'))
sm = l5.get('structured_macro') or {}
print('structured_macro keys:', list(sm.keys()))
for k, v in sm.items():
    print(f'  {k}: {v}')
for p in l5.get('pillars') or []:
    if 'structured_macro' in str(p.get('id', '')):
        print(f'pillar status: {p.get(\"status\")}')
        print(f'pillar interp: {p.get(\"interpretation\")}')
"
# 预期(走 ai_assisted 路径但 sm 仍保留规则路径产物):
# computation_method: ai_assisted
# structured_macro keys: ['DXY', 'US10Y', 'VIX', 'btc_nasdaq_corr', 'data_completeness_pct']
# pillar status: ok
# pillar interp: DXY=99.x; US10Y=4.x; VIX=18.02; BTC-NDX corr=0.44
SSH
```

---

## 五、§X / §Y / §Z 自检

### §X(只改 update 一项,其他逻辑不动)
- 不重写 `Layer5Macro.compute` 主流程
- 不动 `_build_structured_macro_rule`(字段名已在 1.5c.5 修正)
- 不动 AI prompt / `_try_call_l5_ai`
- 仅把 `update({"structured_macro": ...})` 一项改为 merge 语义

### §Y
本 commit 立即 push。

### §Z 端到端断言
- mock `_try_call_l5_ai` 真跑 `Layer5Macro.compute` 120 天 + 真 `_pillars_l5`
- 4 测试覆盖 3 种 AI 返回(空 sm / 部分 sm / None)+ 1 个 e2e pillars
- 关键反退化 guard `test_ai_empty_structured_macro_preserves_rule_path`:
  老 bug 复现条件(AI 返回 sm={})下,断言规则路径产物仍在

### 同类风险扫描
1. **AI 返回 sm 全是字符串** — 例 `"DXY": "rising"` 这种;merge 后会覆盖
   规则路径的 dict `{trend, magnitude_30d_pct, latest}`。`_pillars_l5` 同时
   兼容 dict / 字符串(else 分支 `pieces.append(f"{k}={v}")`)
2. **AI 返回非 dict 的 sm** — `isinstance(ai_sm, dict)` 守卫,非 dict 直接保留规则路径
3. **AI 失败 → ai_out=None** — 走 else 分支(老逻辑),保留规则路径 100% 不动
4. **double 加 note** — 不改 notes append 逻辑;同一次 run 只追加一次 "L5 AI assisted"

---

## 六、改动文件

| 文件 | 改动 |
|---|---|
| `src/evidence/layer5_macro.py` | AI update 把 structured_macro 一项改为 merge 语义(其他字段不变) |
| `tests/test_l5_ai_path_preserves_rule_macro.py` | 新文件 4 测试 |

---

## 七、未覆盖项

- 1.5c 系列(.0/.1/.2/.3/.4/.5/.6)修了用户截图所有 missing
- L5 AI prompt 是否未来要求 AI 主动填 structured_macro:留 v0.5 sprint 决定;
  当前 merge 语义同时兼容"AI 不填"和"AI 主动填"两种 timeline
