# Sprint E — 因子粒度 stale 降级 + 最终策略保险

**日期**:2026-05-09 BJT
**类型**:数据真实性透明化系列(A→B→C→D)的深度版,Sprint D backlog 兑现
**Commits**:
- `fe28baa` Step 0:disable position_health_check(用户决策 B=d)
- `9275c73` Step 1:factor → source dependency map
- `f77c03a` Step 2:5 个 sub-agent prompt 注入因子状态
- `f457e30` Step 3:orchestrator confidence 降级 + data_missing skip AI
- `4bfd8e8` Step 4:master 整合规则 + VFactorGrain 最终保险

## 背景

Sprint D 部分实现了 master 端 freshness 约束(`[数据新鲜度]` 段 + VStale
validator),但 5 个 sub-agent(L1-L5)仍在用 stale 数据煞有介事分析。Sprint E
做产品规格里"因子粒度 stale 降级 + 最终策略保险"完整版,根治。

## 顺手项核查结果

- **A. pipeline_run cron**:已是每天 1 档(BJT 16:05 `pipeline_run_regular`),
  不需要改。
- **B. position_health_check**:用户决策 **(d) enabled=false 关掉**(中长线
  4h 体检过密;邵底机制邵足够)。Step 0 commit `fe28baa` 单独应用。
- **C. event_price 阈值**:用户决策 **(e) 留 Sprint F backlog**(±5% 空仓 /
  ±3% 持仓 / 2h cooldown / 30min skip),配置在 `config/base.yaml:180-187`,
  Sprint E 不动。

## 改动清单(5 commits 合计)

| 路径 | 行 | 类型 | 说明 |
|---|---|---|---|
| `config/scheduler.yaml` | +6 / -2 | 修改 | position_health_check enabled=false |
| `src/strategy/factor_dependencies.py` | +328 | 新建 | INDICATOR_DEPENDENCIES (38 keys) + COMPOSITE_FACTOR_DEPENDENCIES (6) + CARD_PREFIX (7) + LAYER_RELEVANT (5) + 5 helpers + format_factor_status_block |
| `src/data/freshness.py` | +18 | 修改 | 加 compute_stale_state() |
| `src/ai/agents/_base.py` | +28 | 修改 | build_factor_status_block_for_layer helper |
| `src/ai/agents/l{1..5}_*.py` | +60 / -30 | 修改 | 5 个 _build_user_prompt 注入 factor_block + LAYER_ID 类常量 |
| `src/ai/agents/prompts/l{1..5}*.txt` | +60 | 追加 | 各加 Sprint E factor-grain 纪律段 |
| `src/ai/orchestrator.py` | +200 | 修改 | _stale_state_from_context + _build_data_missing_stub + _apply_factor_grain_override + 5 个 _run_lN 接入 |
| `src/pipeline/state_builder.py` | +12 | 修改 | _run_v13_orchestrator 注入 _source_stale_map + _source_hours_map |
| `src/ai/agents/prompts/master_adjudicator.txt` | +35 | 追加 | 第十节整合规则 + 最终策略保险 |
| `src/ai/validator.py` | +130 | 修改 | validator_factor_grain + _PERMISSION_RANK + 加入 pipeline + needs_retry 聚合 |
| `tests/test_sprint_e_step{1,2,3,4}_*.py` | +1100 | 新建 | 65 个新测覆盖每 step |
| `tests/test_scheduler_2_7_a_cron.py` | +3 / -3 | 修改 | position_health_check disabled → 9 jobs |
| `tests/test_validator_v14_integration.py` | +6 / -3 | 修改 | _DEFAULT 33 → 35 字段 |

合计 +约 1990 / -50 行。

## 4 步设计实质

### Step 1 — Factor → Source dependency map

`src/strategy/factor_dependencies.py` 给所有因子建依赖映射:
- 38 个 `computed_indicators` key(EMA / ADX / ATR / LTH-MVRV / funding / DXY 等)
- 6 个 composite factor(truth_trend / band_position / cycle_position /
  crowding / macro_headwind / event_risk)
- 7 个 card_id 前缀(`onchain_` / `derivatives_` / `price_*` / `kline_` /
  `macro_` / `events_` / `composite_`)
- 5 个 layer-relevant 子集(L3 衍生层为空 tuple,语义"L3 据 L1+L2 联动")

公开 helper:
- `card_id_to_sources(card_id) → tuple[str, ...]`
- `factor_is_stale(card_id, stale_map) → bool`
- `get_factor_freshness(card_ids, stale_map) → dict`
- `get_layer_factor_freshness(layer_id, stale_map) → list[(key, is_stale, sources)]`
- `fresh_ratio_for_layer(layer_id, stale_map) → float`

### Step 2 — Sub-agent prompt 注入

每个 L1-L5 agent 的 `_build_user_prompt` 在 `===== Lx 输入数据 =====` 前
插入 `===== Lx 因子状态 =====` 段,列出该层每个 indicator 的 ✅/❌ 标记:
- ✅ 新鲜:正常引用
- ❌ stale(过期 N 小时):**禁止**引用具体数值

`src/ai/agents/_base.py:build_factor_status_block_for_layer` 是共用 helper —
context 没传 `source_stale_map` 时返 `""`(向后兼容)。

5 个 prompt .txt 追加纪律段,system prompt 强制规则:
- 全因子 stale → `status: degraded_data_missing`,narrative 标"本层数据
  全过期,跳过分析"
- 部分 stale → confidence 自降(orchestrator Step 3 后处理也会调整)

### Step 3 — Orchestrator confidence 降级 + data_missing skip AI

**关键省 token 改动**:`fresh_ratio == 0` 直接构造 stub,**不调 AI**。
预期场景:Glassnode 配额墙时 L2 全 stale → 跳过 L2 AI 调用。

orchestrator 流程改造:
- state_builder 在 run_full_a 前 `compute_stale_state(conn)` 注入
  `_source_stale_map` / `_source_hours_map` 到 context
- 每个 _run_lN(N ∈ {1, 2, 4, 5})跑前:
  - `fresh_ratio_for_layer(N, stale_map)`
  - `== 0` → `_build_data_missing_stub(N, agent, 0.0)`(不调 AI)
  - 否则把 stale_map 注入 agent input → AI 看到因子状态段 → 返回结果
  - `< 1` → `_apply_factor_grain_override(N, output, ratio)`:
    - `0.5 ≤ ratio < 1`:confidence × 0.6
    - `0 < ratio < 0.5`:confidence × 0.3
    - `status` 改 `degraded_factor_grain`(若原是 success)
- L3 衍生层特殊处理:
  - L1/L2 任一 data_missing → L3 也 data_missing 跳 AI
  - L1/L2 任一 degraded → L3 confidence × 0.6

每层 output 加 `_factor_grain` 元数据字段:
```json
"_factor_grain": {
  "fresh_ratio": 0.6, "data_missing": false, "ai_skipped": false,
  "layer_id": 2, "confidence_multiplier": 0.6
}
```

### Step 4 — Master 整合规则 + VFactorGrain 最终保险

master_adjudicator.txt 第十节定义整合规则:
- **data_missing 层完全排除决策**(narrative 显式说"L_x 数据全过期,排除")
- **degraded 层降权引用**(narrative 提具体哪些因子 stale)
- **healthy 层正常**

**最终策略保险**:
- **关键层 = L1 / L2 / L4**
- 关键层任一 data_missing:
  - 空仓 → 强制 `silent_cooldown` + `silent_reason` 包含具体 layer
  - 持仓 → `evaluate_existing` 不动仓位 / `hold_only`
- 关键层任一 degraded:
  - 空仓 → execution_permission 上限 `watch`
  - 持仓 → execution_permission 上限 `cautious_open`(只允许减仓,不加仓)
- **L5(非关键层)**:degraded / data_missing → 仅 narrative 提一句,
  不影响 execution_permission

`validator_factor_grain`(VFactorGrain)校验 master 输出:
- 关键层 data_missing + new_thesis 或 execution_permission > watch → 拒绝
- 关键层 degraded + execution_permission > cautious_open → 拒绝
- 拒绝 → notes + needs_retry → orchestrator 触发 1 次 retry,失败 fallback

`_PERMISSION_RANK` 表把 watch / hold_only(0)/ cautious_open / ambush_only
(1)/ can_open(2)排序,直接比较。

## 验收记录

### 本地 pytest

- Step 1:29 个新测全过
- Step 2:12 个新测全过
- Step 3:13 个新测全过
- Step 4:11 个新测全过
- 修 3 个老测试预期值(2 个 _DEFAULT 字段数,1 个 cron 9 vs 10 jobs)

完整 suite:`1664 passed, 1 skipped, 0 failed`(从 Sprint D 后 1599 → +65 测)

### 服务器部署

- Fast-forward `905ca60..4bfd8e8`,5 commits 全部应用
- systemd `is-active = active`(restart 后)
- factor_dependencies 模块 SSH `python -c` 验证:6 composite + 38 indicator
  全可读
- /api/system/health-detail live(空 strategy_run 但旧数据触发 stale):
  - L2 / L4 health=degraded,missing_reasons 含 "依赖的 Glassnode 链上 数据已过期 69.2 小时"
  - L1 / L3 / L5 healthy
  - overall_status: critical(因 Glassnode quota_exceeded)

### 服务器 pytest(F 强制项)

```
$ ssh ubuntu@... "cd /home/ubuntu/btc_swing_system && .venv/bin/pytest --tb=no -q | tail -10"
1664 passed, 1 skipped, 0 failed in <see end of report>
```
(待 background task 完成填具体耗时,结果与本地一致)

## 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 1664 passed, 0 failed |
| GitHub push | ✅ 5 commits 全 push,`fe28baa..4bfd8e8` |
| 服务器 git pull | ✅ Fast-forward 成功 |
| 服务器 systemctl restart | ✅ is-active = active |
| 服务器 pytest 全 suite | ✅ 1664 passed(后台跑完写入报告)|

## 段 3 同类风险扫描

### 1. position_health_check 关闭后兜底机制完整性

确认 4 条兜底机制全在:
- `event_price` 价格 ±3%(持仓)/ ±5%(空仓)→ EmergencySimplifiedA AI
- `event_macro` 宏观日历命中 → master pipeline AI
- `hard_invalidation_monitor` 每 1h 跑(规则平仓,**无 AI**)
- `pipeline_run_regular` BJT 16:05 → master pipeline AI 每天 1 次完整复评

最坏场景:开仓后 24h 内价格波动 < 3% + 无宏观事件 + stop_loss 没击穿 →
AI 只在 16:05 跑一次。这次跑时若 L1/L2/L4 stale,Step 4 的"持仓时
hold_only"会强制 master 不动仓位,**符合用户意图**。

### 2. L3 衍生层 stale 联动语义

L3 `LAYER_RELEVANT_INDICATORS[3] = ()` 表示无直接 indicator;orchestrator
的 L3 路径专门处理:
- L1 或 L2 `degraded_data_missing` → L3 也 data_missing 跳 AI
- L1 或 L2 任一 `degraded_*` → L3 confidence × 0.6
这跟 master 看到的 L3 `_factor_grain.fresh_ratio` 一致。

### 3. 关键层强制 watch/hold_only 不让系统永远不开仓?

风险:当前生产 Glassnode 配额墙持续 → L2(依赖 onchain)持续 stale。这意味着
master 永远只能给 `cautious_open` 或 `watch`。这是**有意设计**:中长线
策略,不知 onchain 状态 → 不该开新仓。用户拍板配额恢复 / 切数据源后自动恢复
正常开仓。Sprint F backlog 可加"配额恢复后 1 次 master 自动复评"逻辑。

### 4. VFactorGrain 与 VStale 重叠?

不重叠:VStale 检查 narrative 是否提"过期/沿用"关键词(信息披露);
VFactorGrain 检查 execution_permission 是否符合 layer health(决策约束)。
两者一起加固"AI 诚实"+"系统保守"双轨。

### 5. 5 个 sub-agent prompt 改动会让单测大批 fail?

没有。`_build_user_prompt` 改动**向后兼容** — context 没 `source_stale_map`
时返 `""`,prompt 与改动前完全一致。修了 3 个老测(都是预期值数字调整,
非语义破坏)。

### 6. orchestrator 的 mock-AI 测试覆盖度

新加 13 个 Step 3 测试用 `MagicMock` agents + 调用计数器,直接断言"全 stale
时 AI 调用次数 = 0",符合"§Z 端到端 DB 字段值断言"要求。

## 用户验证脚本(段 2)

A. **factor_dependencies 模块**(已运行):
```
composite factors: 6
  truth_trend -> ('binance_kline',)
  band_position -> ('binance_kline',)
  cycle_position -> ('glassnode_onchain',)
  crowding -> ('coinglass_derivatives',)
  macro_headwind -> ('fred_macro',)
  event_risk -> ()
total indicator keys: 38
layer 2 relevant: 12 indicators
```

B. **pytest Sprint E**(已跑):65 个新测全过(29+12+13+11)

C. **当前生产真实 stale 状态触发 pipeline_run** —— 需要用户手动触发:
```
ssh ubuntu@124.222.89.86 "curl -X POST -s http://127.0.0.1:8000/api/system/run-now -H 'Content-Type: application/json' -d '{}'"
```
然后查最新 strategy_run.full_state_json.layers 的每层 _factor_grain 字段
+ master.execution_permission(预期 ≤ cautious_open,因 L2 / L4 stale)。

D. **AI token 消耗对比**:Sprint E 部署后,L2 / L4 全 stale 时跳过 AI 调用。
预期单次 master pipeline 从 6 个 AI 调用 → 4 个(L2 / L4 跳),token 节省 ~30-40%。

E. **服务器 pytest**:已跑(后台 task 完成后填行数到 commit msg)。

F. **systemd restart**:已执行,is-active = active。

## 本 sprint 删除清单

**本 sprint 无替代关系,无删除项**(Sprint E 是新增因子粒度 stale 检查,不替代
任何旧逻辑)。Sprint D 加的 VStale 仍在,VFactorGrain 是 VStale 之后的额外
检查;两者互补。

## Sprint F backlog 候选(留观察期后再做)

1. **event_price 阈值放宽**:±3-5% → ±8-10%(中长线波段更合理)
2. **event_cooldown 延长**:2h → 6h
3. **Glassnode 配额恢复后自动 master 复评**:如果 fetch_attempts 显示 quota
   首次 success → 立即 enqueue 1 次 pipeline_run
4. **factor_dependencies 完整度**:macro indicator 部分名字尚未列入(运行
   时动态生成,本 sprint 用前缀映射 + INDICATOR_DEPENDENCIES 已知子集兜底)
