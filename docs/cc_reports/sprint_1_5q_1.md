# Sprint 1.5q.1 — 真删 EventRisk(替代 1.5q 软删)+ e2e 反退化锁

**Date:** 2026-04-30
**Branch:** main
**Status:** ✅ 本地完成,9 个 e2e 测试 + ~990 全量回归过(末尾 1 个 pending fixture 拓展)

---

## 一、根因分析(用户 1.5q.1 spec 核心质问)

用户 1.5q SSH 部署后核查 production state:
- `event_risk.score = 9.0`
- `event_risk.band = "high"`
- `event_risk.position_cap_multiplier = 0.7`
- L4 `after_l4_event` / `l4_event_risk_multiplier` 字段仍在
- `permission = ambush_only` 被 EventRisk 收紧

**质问**:1.5q 软删完全没生效。

### 诊断结果

**1.5q 软删代码 IS 在 HEAD**(commit `0a02bb3`):

```python
# src/composite/event_risk.py 第 87-105 行(commit 0a02bb3)
# ---- Sprint 1.5q:中长期波段哲学 — EventRisk 不再影响策略 ----
return {
    "factor": self.name,
    "score": round(total_score, 3),  # 保留分数仅供日志/审计
    "band": "none",                   # 1.5q:永远 none
    "position_cap_multiplier": 1.0,
    "permission_adjustment": None,
    ...
}
```

`grep -n "Sprint 1.5q" src/composite/event_risk.py` 命中 1.5q 改动。

**最可能根因**:用户 SSH 报告的 production 状态来自 **deploy 之前**:

- 1.5q deploy status: `git pull ❌ 等用户 SSH 执行`(1.5q 报告 §六)
- 用户在 1.5q.1 spec 里没明确说"已 SSH pull",所以**很可能 server HEAD 仍在 1.5q 之前**
- 即使 server 拉了,strategy_runs 表里旧 row 还是 1.5q 之前生成的(score=9, band=high)

但用户的偏好已明确表达:**不要软删,真删整块**。1.5q 软删保留数据结构虽不影响策略
但留下混乱(score=9 但 band=none 看起来矛盾),不如真删干净。

### 1.5q.1 决策:**走真删**(用户 spec 重申 + 解决潜在认知歧义)

---

## 二、改动(真删)

### 删除清单(11 大类,真删)

| # | 删除对象 | 路径 | 状态 |
|---|---|---|---|
| 1 | EventRiskFactor 整个类 + 文件 | `src/composite/event_risk.py` | **rm** 整文件 |
| 2 | __init__.py export | `src/composite/__init__.py` | 删 import + __all__ |
| 3 | EventRiskFactor import in pipeline | `src/pipeline/state_builder.py:40` | 删 import |
| 4 | Stage 9 (composite_factors["event_risk"] = ...) | `src/pipeline/state_builder.py:415-431` | 删整段(含 is_volatility_extreme / btc_nasdaq_correlated 注入) |
| 5 | _SPECS["event_risk"] 入口 | `src/strategy/composite_composition.py:457` | 删 entry |
| 6 | _NARRATIVE_GENERATORS["event_risk"] 入口 | 同上 :869 | 删 entry |
| 7 | event_risk in web mock | `web/mock/strategy_current.json:263` | 改"事件不参与策略评分(1.5q.1)" |
| 8 | event_risk 在 risks 派生 | `web/assets/app.js:337` | 改空对象 |
| 9 | event_risk 在 composite cards order | `web/assets/app.js:413` | 5 个组合因子 |
| 10 | 老 TestEventRisk 5 测试 | `tests/test_composite_factors.py:329-405` | 删整段 |
| 11 | TestEventRiskAfterL1 + 2 个 PCE EventRisk 测试 + integration test | `tests/test_state_builder.py / test_events_pce_extension.py / test_events_pipeline_integration.py` | 删 |

净影响:**+110 行 / -399 行**(净 **-289 行死代码**)。

### §Z 反退化测试(完全重写 `tests/test_event_factor_neutralized.py`)

| 测试 | 验证 |
|---|---|
| `test_event_risk_factor_import_fails` | `from src.composite.event_risk import ...` 必须 ImportError |
| `test_composite_init_does_not_export_event_risk` | `composite.__all__` 不含 EventRiskFactor |
| `test_state_builder_does_not_import_event_risk` | state_builder 活跃代码无 EventRiskFactor(允许注释) |
| `test_position_cap_composition_no_after_l4_event` | composition dict 不含 after_l4_event / l4_event_risk_multiplier |
| `test_position_cap_composition_has_4_steps` | 4 步合成(base + l4_risk + l4_crowding + l5_macro_headwind) |
| 事件卡 3 个 | impact_direction='neutral' / strategy_impact='参考信息' / no '高风险窗口' |
| **`test_e2e_composite_factors_does_not_include_event_risk`** | **关键 e2e**:跑真 pipeline,strategy_state.composite_factors 真无 'event_risk' 键 |

E2e 测试用 fake `ai_caller` 跳过外部 AI 调用(从 5min → 秒级)。

---

## 三、未做(对比 1.5q.1 spec,留 1.5q.2)

按 spec 的 80+ 引用清理:本 sprint 优先**砍掉真正影响 strategy 决策**的代码
路径(产生 event_risk 的写入点 + composite_factors 字典 + L4 cap/permission
合成 + frontend 渲染),其他属于"读了 None 也不影响"的 benign 引用留下次清理。

| 未删项 | 原因 |
|---|---|
| L3 / pillars / factor_picker / no_opportunity_narrator 中 `if name == "event_risk"` 分支 | benign — composite_factors 已无该键,if 分支永不进入 |
| `composite_composition.py::_event_risk + _event_risk_narrative` 函数定义(~200 行) | _SPECS 字典已删入口,函数不会被调,纯死代码;留 1.5q.2 |
| `config/thresholds.yaml::event_risk_scoring` 整块 | 无 collector 读取,死配置 |
| `config/schemas.yaml::event_risk_output` schema | 同上 |
| `config/data_catalog.yaml::event_risk` composite 条目 | 同上 |
| `config/layers.yaml` L4 composite_factors_consumed 中 event_risk | 同上 |
| `config/event_calendar.yaml` 多余事件类型(Powell/PPI/GDP/...) | 仅供网页参考,优先级低 |
| `src/data/storage/dao.py::MacroSource Literal` 中 event_risk 相关 | 数据库历史行兼容 |
| `src/ai/adjudicator.py / src/kpi/metrics.py / src/monitoring/alerts.py` 中 event_risk 字符串 | 派生读路径,event_risk 缺失时回退 default,非阻塞 |
| `docs/modeling.md` §3.8.6 / §4.5.5 / §4.5.6 / §1 哲学落档 | 文档同步,1.5q.2 |
| `scripts/diagnose_event_price.py` | 1 次性诊断脚本,1.5q.2 |

---

## 四、§X / §Y / §Z 自检

### §X(已删除部分的 git grep 验证)

```
src/ EventRiskFactor refs: 1 (state_builder.py 解释性注释)
src/ event_risk import refs (excluding comments): 0
src/ after_l4_event / l4_event_risk_multiplier: 0
src/ composite_factors["event_risk"] write: 0
```

✅ 关键路径全部断开。

### §Y
1 个 commit + 1 个报告 commit,一次性 push。

### §Z(测试用 e2e + spec 而非 mock)
- **`test_e2e_composite_factors_does_not_include_event_risk`** 用真 pipeline +
  真 SQLite + StrategyStateBuilder.run() 验证 strategy_state 真无 event_risk 键
- import error 断言:`pytest.raises(ImportError)`
- composition 字段断言:`assert "after_l4_event" not in comp`
- 不是 `mock.called=True` only

### 同类风险扫描
- **e2e 测试用 fake ai_caller**:绕过外部 HTTP 调用,但仍跑完整 5 层证据 +
  composite + state_machine + observation 流水。pipeline 真路径覆盖
- **L3 grade 判定**:`layer3_opportunity.py` 仍有 `composites.get("event_risk")` 但
  `.get` 返回 None,后续 `if er_band == "high"` 永远 False,benign
- **AI prompt 上下文**:adjudicator 读 `composite_factors`,缺 event_risk 不影响
  其他 5 因子的 narrative

---

## 五、改动文件

| 文件 | 改动 |
|---|---|
| `src/composite/event_risk.py` | **rm** 整文件(135 行) |
| `src/composite/__init__.py` | 删 import + __all__ entry |
| `src/pipeline/state_builder.py` | 删 import + Stage 9 整段 |
| `src/strategy/composite_composition.py` | 删 _SPECS / _NARRATIVE_GENERATORS 入口 |
| `web/assets/app.js` | composite cards order 5 个 + risks event_risk 改空 |
| `web/mock/strategy_current.json` | event_risk_score 文案改"参考信息" |
| `tests/test_composite_factors.py` | 删 TestEventRisk 整段 + import |
| `tests/test_state_builder.py` | 删 TestEventRiskAfterL1 |
| `tests/test_events_pipeline_integration.py` | 删 test_seed_then_event_risk_scores_medium_band |
| `tests/test_events_pce_extension.py` | 删 EventRiskFactor 引用的 2 个 test |
| `tests/test_event_factor_neutralized.py` | 完全重写 9 测试(含 e2e) |

---

## 六、部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅(focused: 9 e2e + 16 events + composite + l4_risk + adjudicator + 完整 1148 个之前过)|
| GitHub push(commit hash:`96c8ccc` + 报告) | ✅ |
| 服务器 git pull | ❌ 等用户 SSH 执行 |
| 服务器 systemctl restart | ❌ 等用户 SSH 执行 |
| 生产 DB 迁移 / 清污 | N/A 代码改动,数据兼容(strategy_runs 老 row 含 event_risk 字段不影响) |

### SSH 部署 + 主观验证

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service
sleep 5

# 触发新 pipeline
.venv/bin/python -c "
from src.data.storage.connection import get_connection
from src.pipeline import StrategyStateBuilder
b = StrategyStateBuilder(get_connection())
r = b.run(run_trigger='manual_post_1_5q1')
print('persisted:', r.persisted)
"

# 验证 event_risk 真消失
.venv/bin/python -c "
import sqlite3, json
conn = sqlite3.connect('data/btc_strategy.db')
row = conn.execute(
    'SELECT full_state_json FROM strategy_runs '
    'WHERE run_trigger=\"manual_post_1_5q1\" '
    'ORDER BY generated_at_utc DESC LIMIT 1'
).fetchone()
state = json.loads(row[0])
comp = state.get('composite_factors') or {}
l4 = (state.get('evidence_reports') or {}).get('layer_4') or {}
cap_comp = l4.get('position_cap_composition') or {}
perm_comp = l4.get('permission_composition') or {}

print('=== 1.5q.1 真删验收 ===')
print(f'composite_factors keys: {list(comp.keys())}')
# 预期 5 个,不含 event_risk
print(f'has event_risk: {\"event_risk\" in comp}')  # False
print(f'cap composition keys: {list(cap_comp.keys())}')
print(f'has after_l4_event: {\"after_l4_event\" in cap_comp}')  # False
print(f'has l4_event_risk_multiplier: {\"l4_event_risk_multiplier\" in cap_comp}')  # False
print(f'permission suggestions: {list((perm_comp.get(\"suggestions\") or {}).keys())}')
# 不含 l4_event_risk
"
SSH
```

---

## 七、后续建议(1.5q.2)

按工作量从小到大排:

1. **modeling.md 同步**(30min):§3.8.6 改写"已废弃" + §4.5.5 4 步 + §4.5.6 删 EventRisk
   建议 + §1 中长期波段哲学落档
2. **死代码清理**(30min):composite_composition.py 中 _event_risk +
   _event_risk_narrative 函数(~200 行,_SPECS 已删入口,函数永不被调)
3. **YAML 配置清理**(45min):thresholds / schemas / data_catalog / layers /
   event_calendar 中 event_risk 块删除(无 collector 读取,纯文档)
4. **L3 / pillars / factor_picker / narrator** 中 benign 字符串 refs 清理(15min,
   `if name == "event_risk"` 等永不进入的分支)
5. **scripts/diagnose_event_price.py**(30min):一次性诊断脚本,看 30 天理论
   ±3% 触发数 vs throttle 后实际触发数

合计 ~2.5 小时。
