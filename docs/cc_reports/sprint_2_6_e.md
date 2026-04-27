# Sprint 2.6-E — L5 AI 接入(严格按建模 §6.8)

**Date:** 2026-04-27
**Branch:** main
**Status:** ✅ 3 个 commit 全完成

---

## 一、设计依据

严格对齐 `docs/modeling.md §6.8`(终稿,verbatim):
- **System Prompt** 一字不改
- **Layer5Output schema** 8 字段全部实现
- `adjustment_guidance` 接入 §4.5.5 step 4(position_cap multiplier)+
  §4.5.6 permission 归并

CLAUDE.md 第一行:"docs/modeling.md 是项目唯一权威蓝本,任何代码改动都必须严格对齐它"。
本 sprint 是 §6.8 实施状态行所要求的"具体实施排在 Sprint 2.6"的兑现。

---

## 二、Triggers(偏离 spec 的自主决策)

1. **L5 AI 不直接参与 L4 同一轮 position_cap 计算**:§3.2.1 顺序硬规则
   "L1→L2→L3→L4→L5" 决定了 L4 跑完才轮到 L5。L4 step 4 用的是 composite.macro_headwind 的
   规则分,不能等到 L5 AI 跑完再用。
   
   **解决**:新增 Stage 13b — `apply_l5_ai_loopback(layer_4_output, layer_5_output)`,
   在 L5 完成后 patch L4 output(重算 step 4 multiplier + 走 hard floor gate +
   permission 一档移)。这样既不破坏 §3.2.1 顺序,又让 L5 AI 的判断流入最终
   position_cap / permission。审计字段标 `l5_ai_override_applied=true`。

2. **AI 失败时 macro_headwind_score = 0.0**:对齐 §6.8 实施状态行原文
   "当前过渡期使用规则化 fallback,产出 macro_headwind_score = 0.0,
   等价于无宏观信号"。规则路径不会"伪装"AI 输出。

3. **composite.macro_headwind 不动**:它仍然按规则跑(给 L4 第一轮用),
   L5 AI 的覆盖通过 Stage 13b 的 loopback 实现。这避免了 composite 层与 evidence 层
   职责模糊。

---

## 三、Commits

| commit | 摘要 |
|---|---|
| `5ea0c5c` | feat(ai): MacroL5Adjudicator (§6.8 verbatim System Prompt + Layer5Output) |
| `0c05dca` | feat(layer5): AI-assisted macro analysis (rule-based fallback) + L4 loopback |
| (本)     | docs(reports): sprint_2_6_e complete |

---

## 四、改动清单

### Commit 1 `5ea0c5c`:`src/ai/macro_l5_adjudicator.py`(新建)+ 16 测试

- `_SYSTEM_PROMPT`:**逐字复制** modeling §6.8 的 System Prompt 终稿
- `MacroL5Adjudicator.adjudicate(facts) → Optional[dict]`
- 解析路径:
  1. 调 `client.messages.create(system=_SYSTEM_PROMPT, messages=[user_prompt])`,T=0.2
  2. JSON 解析失败 → 重试 1 次,T=0.0
  3. schema 校验失败 → 也重试
  4. 任何最终失败 → 返回 `None`(layer5_macro 退回规则)
- `_validate_layer5_output(parsed)`:严格校验
  - `macro_stance` ∈ {risk_on/risk_neutral/risk_off/extreme_risk_off}
  - `macro_trend` ∈ {improving/stable/deteriorating/volatile}
  - `macro_headwind_score` ∈ [-10, +10]
  - `adjustment_guidance.stance_modifier` ∈ {strong_support/support/neutral/challenge/strong_challenge}
  - `adjustment_guidance.position_cap_multiplier` ∈ [0.5, 1.1]
  - `adjustment_guidance.permission_adjustment` ∈ {tighten/neutral/loosen}
- `_meta` 字段记录:model / tokens / latency / attempts(供审计)

### Commit 2 `0c05dca`:layer5_macro + layer4_risk + state_builder + 10 测试

#### `src/evidence/layer5_macro.py`
- `_compute_specific` 末尾新增 AI 路径:
  - `data_completeness >= 50%` → 调 `MacroL5Adjudicator`
  - AI 成功 → overlay §6.8 schema 字段(8 个 + macro_headwind_score)+
    `computation_method = "ai_assisted"`
  - AI 失败 / completeness < 50% → 保留规则路径,§6.8 字段填占位
    (`macro_headwind_score=0.0`, `adjustment_guidance` neutral)
- `_insufficient` 早返回路径同步加 §6.8 占位(防下游 KeyError)
- 新增 `_try_call_l5_ai(rule_output, events_72h)` 助手:
  - 构造 facts dict(传 structured_macro / 规则路径环境 / 72h 事件)
  - 调 adjudicator,任何异常 → return None

#### `src/evidence/layer4_risk.py::apply_l5_ai_loopback`(公开新 helper)
- 入参:`(layer_4_output, layer_5_output) → patched layer_4_output`
- AI 未启用 / 失败 → 原样返回(no-op)
- AI 成功:
  1. 用 L5 AI 的 `macro_headwind_score` 重算 step 4 multiplier
     (走现有 `_score_to_multiplier(score, _MACRO_BANDS)`)
  2. 重算 `after_l5_macro` → `after_l4_event` → `final_before_floor_gate`
  3. 重新走 `_apply_floor_gate`(用现有 permission)
  4. 应用 `adjustment_guidance.permission_adjustment`:
     - `tighten` → `_shift_permission(current, "tighter")`(下移一档)
     - `loosen` → `_shift_permission(current, "looser")`(上移一档)
     - clamp 到 7 档梯子边界
  5. 审计字段写回:
     - `l5_ai_override_applied = True`
     - `macro_headwind_score_used` / `macro_headwind_score_source = "l5_ai"`
     - `l5_macro_headwind_multiplier_pre_ai` / `l5_macro_headwind_multiplier`(更新后)
     - `execution_permission_l4_pre_l5_ai`(只在 permission 真变了才写)

#### `src/pipeline/state_builder.py`
- Stage 13b 新增:在 Stage 13(L5)之后,调 `apply_l5_ai_loopback(layer_4, layer_5)`
- 异常吞:loopback 失败不影响其他流程

### Commit 3(本提交):报告

---

## 五、§4.5.5 / §4.5.6 联动验证(测试覆盖)

| 场景 | AI 输入 | L4 patch 行为 | 测试 |
|---|---|---|---|
| AI 给 strong headwind score=-6 | macro_headwind_score=-6 | step 4 multiplier 落 0.7 桶 → cap 缩 30% | `test_loopback_applies_strong_headwind_multiplier` |
| AI permission_adjustment='tighten' + current=can_open | tighten | can_open → cautious_open | `test_loopback_tighten_shifts_permission_one_step` |
| AI permission_adjustment='loosen' + current=ambush_only | loosen | ambush_only → cautious_open | `test_loopback_loosen_shifts_permission_one_step` |
| permission ladder 边界 | tighter at protective | 不动(clamp) | `test_shift_permission_tighter_clamps_at_protective` |
| permission ladder 边界 | looser at can_open | 不动(clamp) | `test_shift_permission_looser_clamps_at_can_open` |
| AI 不可用 / 规则路径 | computation_method='rule_based' | loopback no-op | `test_loopback_noop_when_l5_not_ai_assisted` |

---

## 六、测试

```
$ python -m pytest tests/test_macro_l5_adjudicator.py tests/test_l5_ai_integration.py -q
26 passed in 1.02s

$ python -m pytest -q
484 passed, 1 skipped, 138 warnings in 97.01s
```

无回归(458 → 484,新增 26)。pre-commit gitleaks 每次 Passed。

---

## 七、待用户部署

```bash
ssh user@server
cd /path/to/btc_swing_system
git pull
sudo systemctl restart btc-strategy
.venv/bin/python scripts/run_pipeline_once.py 2>&1 | tail -15
# 验证 L5 AI 被触发(若 OPENAI_API_KEY 配置且 macro 数据完整 >= 50%)
.venv/bin/python -c "
from src import _env_loader
import requests, json
resp = requests.get('http://127.0.0.1:8000/api/strategy/current',
                    auth=('admin','Y_RhcxeApFa0H-'), timeout=10)
s = resp.json().get('state', {})
l5 = (s.get('evidence_reports') or {}).get('layer_5') or {}
print('=== L5 §6.8 Output ===')
for k in ('computation_method', 'macro_stance', 'macro_trend',
          'macro_headwind_score', 'adjustment_guidance'):
    print(f'  {k}: {l5.get(k)}')

l4 = (s.get('evidence_reports') or {}).get('layer_4') or {}
comp = l4.get('position_cap_composition') or {}
if comp.get('l5_ai_override_applied'):
    print('\\n=== L5 AI loopback applied to L4 ===')
    print(f'  macro_score_source: {comp.get(\"macro_headwind_score_source\")}')
    print(f'  step 4 multiplier (pre/post AI): {comp.get(\"l5_macro_headwind_multiplier_pre_ai\")} → {comp.get(\"l5_macro_headwind_multiplier\")}')
    print(f'  final position_cap: {l4.get(\"position_cap_pct\")}%')
"
```

---

## 八、§X / §Y 践行

- ✅ §X:无被替代的旧代码(layer5_macro 走 AI 后,规则路径作为 fallback 保留是设计要求,不算堆叠)
- ✅ §Y:每个 commit 立即 push

---

## 九、遗留(下个 sprint 候选)

1. **主 AI 裁决官读 L5 的 active_event_summaries**:目前 §6.8 输出的事件摘要给到了
   `evidence_reports.layer_5`,但 `src/ai/adjudicator.py` 的 user_prompt 里没显式引用。
   下个 sprint 把 active_event_summaries 加入主裁决官的 facts 注入。
2. **AI prompt 的 facts 进一步丰富**:目前传 structured_macro + events 简化版;
   可加最近 7d 的 OHLC 摘要 + onchain primary 5,让 AI 判断更全面。
3. **缓存 L5 AI 输出**:同 reference_timestamp 的 L5 AI 调用应缓存,
   避免同 run_id 多次裁决调用。当前 layer5_macro 每次 compute 都调一次。
4. **`_meta.tokens_in/out` 累计到日志/账单审计表**:用于成本可见性。
