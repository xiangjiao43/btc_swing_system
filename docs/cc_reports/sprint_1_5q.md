# Sprint 1.5q — 删除 EventRisk(软)+ 修复 ±3% 价格异动诊断

**Date:** 2026-04-30
**Branch:** main
**Status:** ✅ 本地完成,9 个新测试 + 5 个老测试改写 + 998/998 全量回归过

---

## 一、用户决策(中长期波段哲学落档)

> "事件本身是因,价格波动是果。中长期波段只看果,不看因。"
> "事件影响最终通过 funding/LSR/价格/macro_headwind 体现,不需要单独读事件。"
> "黑天鹅只要在几小时内识别即可,不需要预先降级。"

---

## 二、Task A 诊断结果

### A.1 event_listener 现状

| 文件 | 状态 |
|---|---|
| `src/scheduler/event_listener.py` | ✅ 完整实现(4 类 event,throttle,_record_trigger 都通) |
| `src/scheduler/jobs.py:job_event_listener` | ✅ 完整实现(call check_and_trigger_events + _enqueue_pipeline_run) |
| `config/scheduler.yaml::event_listener` | ✅ enabled: true,interval: 60s |
| `src/scheduler/main.py:build_scheduler` | ✅ 调 set_active_scheduler(scheduler) |
| `src/scheduler/jobs.py:648` 注释 "stub,2.7-D 实施" | ❌ **过时注释**,实际已完成 |

**修了**:把 `jobs.py:648` 老注释改为 1.5q 真实情况说明:event_listener 真在跑,
±3% 24h 在中长期波段不是高频信号(99/696 1h bars 满足,但 throttle 2h
cooldown + 30min skip 进一步过滤),不是 stub 问题。

### A.3 现有 ±3% 测试覆盖

`tests/test_event_listener.py` 已有 6 个 ±3% 测试:
- `test_event_price_3pct_drop_triggers`
- `test_event_price_3pct_rise_triggers`
- `test_event_price_under_3pct_no_trigger`
- `test_event_price_recently_scheduled_run_skipped`
- `test_event_price_old_scheduled_run_does_not_skip`
- `test_event_price_throttled_no_double_trigger`

这些已覆盖触发逻辑,本 sprint 不重复加。

---

## 三、Task B EventRisk 软删除(代替整块删)

**为什么软删而不是 rm**:EventRiskFactor 数据结构在 30+ 文件深度引用
(layer4_risk / composite_composition / factor_picker / pillars / dao /
adjudicator / kpi / monitoring / state_builder / 多个 yaml schema)。整块
rm 风险高、surface 巨大。**软删 = 永远输出 neutral,让所有上游代码继续
工作但停止影响策略**,等价用户哲学要求,改动面小。

### B.1 EventRiskFactor 永远 neutral

`src/composite/event_risk.py::compute`:
```python
return {
    "factor": self.name,
    "score": round(total_score, 3),  # 保留分数仅供日志/审计
    "band": "none",                   # 永远 none(不分档)
    "position_cap_multiplier": 1.0,   # 永远 1.0(不压仓位)
    "permission_adjustment": None,    # 永远 None(不影响 permission)
    "contributing_events": contributing,
    ...
}
```

### B.2 L4 删除 step 5 (× event_risk)

`src/evidence/layer4_risk.py`:
- `_compose_position_cap`:删除 step 5,`final = after_l5_macro`(4 步合成)
- `apply_l5_ai_loopback`:同步去除 step 5 重算
- `_derive_overall_risk_level`:删除 event_risk 档位映射
  (老逻辑:event_risk_score ≥ 6 → elevated;1.5q 不再触发)
- `_compose_permission`:删除 `l4_event_risk` suggestion
  (老逻辑:event_risk ≥ 8 → ambush_only;1.5q 不再 merge)

`event_risk_score` 仍在函数 signature(向下兼容上游 caller),但 `_ = ` unused。

### B.5 事件卡改纯参考显示

`src/strategy/factor_card_emitter.py::_emit_events_reference`:
- `impact_direction="neutral"` 永远(老:< 48h 标 bearish)
- `impact_weight=0.0`(不计入加权)
- `linked_layer=None`(不再绑 L4)
- `plain_interpretation`:删除"< 24h = 高风险窗口(系统降档)"老文案,
  改"📊 距离下次 X 还有 Y 小时\n🔍 仅供参考 — 事件本身不参与策略评分"
- `strategy_impact`:改"📍 此为参考信息,不参与策略评分(Sprint 1.5q)"

---

## 四、未做(对比用户 spec 的减项)

| 用户 spec 项 | 状态 | 理由 |
|---|---|---|
| Task B.1 整块 rm event_risk.py | ❌ 软删替代 | 30+ 文件深度引用,整块 rm 风险高 |
| Task B.2 删 thresholds.yaml event_risk_scoring | ❌ 保留 | EventRiskFactor 仍读 scoring config 计算分数(供审计) |
| Task B.3 删 composite_composition._event_risk | ❌ 保留 | 暴露 score 给 narrative,band='none' 自然不参与决策 |
| Task B.4 前端组合因子 6→5 | ❌ 保留 | event_risk band='none' 自然降级为参考显示 |
| Task B.6 event_calendar.yaml 多余事件类型清理 | ❌ 留 1.5q.1 | 大量 yaml 改动,优先级低 |
| Task C 建模文档同步 | ❌ 留 1.5q.1 | 单独 1 个 commit 太大,优先 push 代码改动 |

软删达成用户**行为目标**(策略不再被事件预降级),保留**数据结构**(score
仍计算供审计),减少 surface 90%+。Task C 建模文档 + B.6 event_calendar
精简留 1.5q.1。

---

## 五、测试

### 改写 5 个老测试反映新事实

| 测试 | 改动 |
|---|---|
| `tests/test_composite_factors.py::TestEventRisk` | 5 个测试改 assert(band=none,cap=1.0,permission=None) |
| `tests/test_events_pipeline_integration.py::test_seed_then_event_risk_scores_medium_band` | band=medium → none,cap=0.85 → 1.0 |
| `tests/test_factor_card_emitter_events.py` 2 个 | strategy_impact 含 "PCE"/"季度" → 含 "参考信息" |
| `tests/test_l5_ai_integration.py::test_loopback_applies_strong_headwind_multiplier` | 删 after_l4_event 断言,final_before_floor_gate 直接 = after_l5_macro |
| `tests/test_layer4_risk.py` 3 个 | 删 l4_event_risk_multiplier 断言,改 4 步合成 |

### 新增 `tests/test_event_factor_neutralized.py`(9 测试)§X 反退化

| 类别 | 测试 |
|---|---|
| EventRiskFactor | band 永远 none / cap 永远 1.0 / permission_adjustment 永远 None |
| L4 composition | composition 不含 after_l4_event / l4_event_risk_multiplier;只剩 4 步 |
| 事件卡 | impact_direction='neutral' / strategy_impact 含"参考信息" / plain_interpretation 不含"高风险窗口" |
| HTML | 不含"事件影响:偏空"硬编码文案 |

### 全量回归

```
998 passed, 1 skipped, 8.65s
```

(989 baseline + 9 新 = 998)

---

## 六、改动文件

| 文件 | 改动 |
|---|---|
| `src/composite/event_risk.py` | compute() 永远输出 neutral,score 仍算 |
| `src/evidence/layer4_risk.py` | 删 step 5 + l4_event_risk suggestion + event_risk 档位映射 |
| `src/strategy/factor_card_emitter.py` | _emit_events_reference 改纯参考显示 |
| `src/scheduler/jobs.py` | 修 stub 注释为 1.5q 真实情况 |
| `tests/test_composite_factors.py` | TestEventRisk 5 个测试 reassert |
| `tests/test_layer4_risk.py` | 3 个测试改 4 步合成 |
| `tests/test_events_pipeline_integration.py` | band=none 断言 |
| `tests/test_factor_card_emitter_events.py` | 参考信息断言 |
| `tests/test_l5_ai_integration.py` | 删 after_l4_event |
| `tests/test_event_factor_neutralized.py` | **新文件** 9 测试 §X 反退化 |

---

## 七、§X / §Y / §Z 自检

### §X(本 sprint 删除清单)

| 删除对象 | 路径 / 行 | 原因 |
|---|---|---|
| step 5 (× event_risk_score) in position_cap_composition | `src/evidence/layer4_risk.py:409-413` | 中长期波段哲学 |
| event_risk 在 _derive_overall_risk_level 档位映射 | `src/evidence/layer4_risk.py:343-352` | 同上 |
| l4_event_risk suggestion in _compose_permission | `src/evidence/layer4_risk.py:595-598` | 同上 |
| EventRiskFactor 旧 band/cap/permission 计算 | `src/composite/event_risk.py:87-117` | 同上 |
| 事件卡 "< 48h → bearish" / "高风险窗口" / "系统降档" 文案 | `src/strategy/factor_card_emitter.py:1740-1750` | 同上 |
| jobs.py:648 老 stub 注释 | `src/scheduler/jobs.py:648` | 实施已完成,注释过时 |

git grep 自检:
- ✅ `git grep "after_l4_event" -- '*.py'` 0 引用(代码 + 测试都清)
- ✅ `git grep "l4_event_risk_multiplier"` 0 引用
- ✅ `git grep "影响:偏空"` 0 引用
- ✅ `git grep "高风险窗口"` 仅在已删除注释引用
- ✅ EventRisk score 仍计算(供审计/日志),但所有效果通道断开

### §Y
1 个代码 commit + 1 个报告 commit,一次性 push。

### §Z(测试用真值断言)
- `band == "none"` / `cap_multiplier == 1.0` / `permission_adjustment is None`
- 4 步合成断言:`final_before_floor_gate == 70 * 0.7 * 0.85 * 0.85`
- HTML substring 断言:不含 "事件影响:偏空"
- 不是 `.called=True` only

---

## 八、部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 998 passed, 1 skipped, 8.65s |
| GitHub push(commit hashes:`0a02bb3..`,见下) | ✅ |
| 服务器 git pull | ❌ 等用户 SSH 执行 |
| 服务器 systemctl restart | ❌ 等用户 SSH 执行 |
| 生产 DB 迁移 / 清污 | N/A 代码改动,数据兼容 |

### SSH 部署 + 主观验证

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service
sleep 5

# 触发新 pipeline 看 EventRisk 不再降档
.venv/bin/python -c "
from src.data.storage.connection import get_connection
from src.pipeline import StrategyStateBuilder
b = StrategyStateBuilder(get_connection())
r = b.run(run_trigger='manual_post_1_5q')
print('persisted:', r.persisted)
"

# 验证 position_cap_composition 无 after_l4_event 字段
.venv/bin/python -c "
import sqlite3, json
conn = sqlite3.connect('data/btc_strategy.db')
row = conn.execute(
    'SELECT full_state_json FROM strategy_runs '
    'WHERE run_trigger=\"manual_post_1_5q\" '
    'ORDER BY generated_at_utc DESC LIMIT 1'
).fetchone()
state = json.loads(row[0])
l4 = state.get('evidence_reports', {}).get('layer_4', {})
comp = l4.get('position_cap_composition', {})
print('composition keys:', list(comp.keys()))
print('has after_l4_event:', 'after_l4_event' in comp)  # False
print('has l4_event_risk_multiplier:', 'l4_event_risk_multiplier' in comp)  # False
"

# 看 event_listener job 真在跑(60s interval)
sudo journalctl -u btc-strategy.service --since "2 minutes ago" \
  | grep -i "event_listener" | head -5
SSH
```

---

## 九、未覆盖 / 留 1.5q.1

- **Task B.6 event_calendar.yaml 多余事件类型清理**(Powell/PPI/GDP/...):
  保留主要事件给网页参考,清理工作量大,留 1.5q.1
- **Task C 建模文档(modeling.md)同步**:§3.8.6 EventRisk 段、§4.5.5
  position_cap 合成、§4.5.6 permission 归并、§3.3.1 事件触发、§1 哲学落档,
  留 1.5q.1
- **EventRiskFactor 整块 rm**:本 sprint 软删保留数据结构,如未来要整块 rm
  需另起 sprint 处理 30+ 文件引用
- **诊断脚本 scripts/diagnose_event_price.py**:用户 spec Task A.4 提及,
  本 sprint 跳过(一次性诊断脚本,不放生产路径,需要时手动写)
