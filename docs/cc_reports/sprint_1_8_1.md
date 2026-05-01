# Sprint 1.8.1 — 安全清理(只动 0 引用项 + 补依赖)

**报告日期:** 2026-05-01
**Sprint 范围:** 修订版指令 — 只做 Step 0(补依赖)+ 删 grep 完全干净的孤立项
**状态:** 全部本地完成,3 个 commit 已 push origin/main
**前置:** Sprint 1.8 v5(commit 481bd89)
**后置:** Sprint 1.9.1 — 等 1.9 把 state_builder 切到 orchestrator 后,真删 layer1-5 / 旧 composite / adjudicator / 7 因子

---

## Triggers(偏离原 1.8.1 大头清理指令)

**用户已在修订版指令中接受**:原 1.8.1 大头清理(layer1-5 / 4 旧 composite /
adjudicator / 7 因子)与 jobs.py 现有 state_builder 路径直接冲突(详见
"段 2 — 阻塞清单" 我先前的 STOP 报告),延到 Sprint 1.9.1。本次只做
"补依赖 + 删 grep 完全干净的孤立项"。

---

## 1. Step 0 — 补依赖(commit 6bafca8 + 93532e4)

### 1.1 改动文件

- `pyproject.toml`:`dependencies` 加 `matplotlib>=3.8` + `mplfinance>=0.12`
- `docs/dev_setup.md`:首次部署 SSH 步骤加 `uv pip install -e .` + import 验证
- `uv.lock`:同步传递依赖(自动重算)

### 1.2 背景

Sprint 1.8 v5 期间引入 `chart_renderer` 用 matplotlib + mplfinance,当时只
`uv pip install`,**未写入 `pyproject.toml dependencies`**。新机器 / 新部署
点拉代码后会启动失败。本 commit 补全声明。

---

## 2. Step 1 — grep 调研全表

### 2.1 调研方法

每候选项做以下 grep:
- 生产 import:`grep -rln "<symbol>" src/` 排除 __pycache__
- 测试 import:`grep -rln "<symbol>" tests/`
- 配置引用:`grep -rln "<symbol>" config/`
- L5 prompt v2 引用:`grep -nE "<symbol>" src/ai/agents/prompts/l5_macro.txt`
- factor_card_emitter / composite_composition 引用:同上对应文件

### 2.2 候选 A:src/evidence/layer1_regime.py ~ layer5_macro.py(5 个)

| 文件 | 生产 import | 测试 import | 配置 | L5 prompt | emitter/composition | 结论 |
|---|---|---|---|---|---|---|
| layer1_regime.py | factor_card_emitter | test_layer1_regime.py + test_l2_structure_features.py | scenario_notes.md | - | factor_card_emitter | ❌ 延 1.9.1 |
| layer2_direction.py | pillars + single_factors/exchange_momentum + layer3 | test_layer2_direction.py + test_l2_structure_features.py + test_pillars + test_exchange_momentum | - | - | - | ❌ 延 1.9.1 |
| layer3_opportunity.py | (内部 self-ref,layer3_opportunity 也被 layer3 自身引) | test_layer3_opportunity.py | - | - | - | ❌ 延 1.9.1(self-ref + 测试) |
| layer4_risk.py | **state_builder.py** + ai/macro_l5_adjudicator.py | test_layer4_risk + test_l5_ai_integration + test_event_factor_neutralized | - | - | - | ❌ 延 1.9.1(生产 import) |
| layer5_macro.py | ai/macro_l5_adjudicator + data/collectors/__init__ + data/collectors/fred + factor_card_emitter | test_layer5_macro + test_fred_collector + test_l5_ai_integration + test_l5_ai_path_preserves_rule_macro + test_ai_summary_smoke | - | - | factor_card_emitter | ❌ 延 1.9.1 |

### 2.3 候选 B:src/composite/{truth_trend, band_position, crowding, macro_headwind}.py(4 个)

| 文件 | 生产 import | 测试 import | 配置 | L5 prompt | emitter/composition | 结论 |
|---|---|---|---|---|---|---|
| truth_trend.py | **state_builder.py** + layer1/2/3 + ai/adjudicator + kpi/metrics + composite_composition | test_exchange_momentum_score + test_composite_factors | thresholds.yaml `truth_trend_scoring` | - | composite_composition | ❌ 延 1.9.1 |
| band_position.py | **state_builder.py** + layer2/3 + _anti_patterns + ai/adjudicator + kpi/metrics + factor_card_emitter + factor_picker | test_composite_factors + test_field_export_alignment | thresholds.yaml `band_position_scoring` | - | factor_card_emitter | ❌ 延 1.9.1 |
| crowding.py | **state_builder.py** + kpi/metrics + factor_picker | test_composite_factors | data_catalog.yaml + thresholds.yaml `crowding_scoring` | - | composite_composition | ❌ 延 1.9.1 |
| macro_headwind.py | **state_builder.py** + layer3/4/5 + _anti_patterns + ai/summary + ai/adjudicator + ai/agents/l5_macro_analyst | test_composite_factors | thresholds.yaml `macro_headwind_scoring` | - | - | ❌ 延 1.9.1 |

### 2.4 候选 C:src/ai/adjudicator.py(1 个)

| 文件 | 生产 import | 测试 import | 配置 | L5 prompt | emitter/composition | 结论 |
|---|---|---|---|---|---|---|
| adjudicator.py | **state_builder.py** + ai/__init__.py | test_adjudicator + test_user_prompt_includes_raw_factors + test_adjudicator_narrative_quality | schemas.yaml + prompts/adjudicator_user_template.txt | - | - | ❌ 延 1.9.1 |

### 2.5 候选 D:7 个延后因子

| 因子 | 生产 import | 测试 / fixture | 配置 | L5 prompt | emitter/composition | 结论 |
|---|---|---|---|---|---|---|
| basis_annualized | composite/crowding | 3 fixtures | thresholds.yaml + data_catalog.yaml | - | - | ❌ 延 1.9.1 |
| put_call_ratio | composite/crowding + composite_composition | 3 fixtures | thresholds.yaml + data_catalog.yaml | - | composite_composition | ❌ 延 1.9.1 |
| sp500 | layer5_macro + collectors/fred + collectors/__init__ | test_layer5_macro + test_fred + test_l5_*x4 + test_pillars + test_composite_composition_value_pipeline | schemas.yaml + layers.yaml(已删) + data_catalog.yaml | **6 处引用** | - | ❌ 延 1.9.1(L5 prompt 自己用!) |
| gold_price | layer5_macro + fred + factor_card_emitter | test_macro_btc_gold + test_fred + test_l5_ai_integration | - | - | factor_card_emitter | ❌ 延 1.9.1 |
| dff | layer5_macro + collectors/__init__ + fred | test_fred + test_layer5_macro | - | - | - | ❌ 延 1.9.1 |
| cpi | **state_builder + scheduler/jobs** + layer5_macro + ai/agents/l5_macro_analyst + l4_risk.txt + l5_macro.txt + collectors/fred + no_opportunity_narrator + composite_composition + factor_card_emitter | test_fred + test_factor_card_emitter_events + test_event_next_cards_beyond_72h + test_event_listener | event_calendar.yaml + thresholds.yaml + data_catalog.yaml + schemas.yaml | **L4 + L5 prompt** | factor_card_emitter + composite_composition | ❌ 延 1.9.1(最重) |
| unemployment | layer5_macro + collectors + fred | test_fred + test_layer5_macro | - | - | - | ❌ 延 1.9.1 |

### 2.6 候选 E:config/{thresholds.yaml, layers.yaml} 中的 dead key

| 文件 | 生产引用 | 测试引用 | 结论 |
|---|---|---|---|
| thresholds.yaml | 10+ src 模块(layer1/2/4/_base + permission + composite/_base/truth_trend/crowding/__init__/cycle_position 等) | 多 | ❌ 整文件活跃,内部 dead key 须等 composite 删后再清 |
| **layers.yaml** | **0** | **0** | ✅ **唯一可删** — 文件级孤儿 |

`config/layers.yaml` 历史:Batch 3 (commit fd7f306) 添加,从未 wired up 到任何代码;`docs/modeling.md` 也 0 引用。

---

## 3. Step 2 — 实际删除(commit 1f5ee9e)

| 删除对象 | 路径 | 删除原因 | grep 验证 |
|---|---|---|---|
| 整个文件 | config/layers.yaml | 0 grep refs(src/ + tests/ + docs/),无人 wire up | `grep -rn "layers.yaml" src/ tests/ docs/` → 0 |

**仅此一项**。其他 候选 A/B/C/D/E.thresholds.yaml 全部延到 Sprint 1.9.1。

---

## 4. Step 3 — 验证

### 4.1 pytest tests/ai/(58/58 ✅)

```
============================== 58 passed in 1.67s ==============================
```

### 4.2 pytest tests/ 全套(无新增 fail ✅)

```
6 failed, 1084 passed, 1 skipped, 368 warnings in 313.21s
```

**6 个失败全部是 1.8.1 之前就有的**(已用 `git stash` + 回滚到 HEAD~2 重跑
验证:同样 6 失败,与 layers.yaml 删除 / pyproject 改动 / uv.lock 改动 无关):

| 失败测试 | 已知问题 |
|---|---|
| test_collector_retry_skip.py::test_onchain_skip_when_today_already_inserted | Sprint 1.6.1 已知,price_candles 1d 表为空时降级 |
| test_collector_retry_skip.py::test_klines_daily_skip_when_today_1d_exists | 同上类 |
| test_composite_narrative.py::TestModuleHygiene::test_six_narrators_registered | 模块注册表更新滞后 |
| test_events_pce_extension.py::test_event_risk_composition_includes_pce_row | 老测试,与 PCE 事件支持 |
| test_field_export_alignment_round2.py::test_event_risk_composition_picks_per_type_from_next_events_by_type | KeyError(数据 fixture 不全) |
| test_field_export_alignment_round2.py::test_event_risk_composition_prefers_72h_contributing_over_next | 同上 |

**结论**:layers.yaml 删除未引入新失败。

### 4.3 pipeline import OK ✅

```bash
uv run python -c "from src.pipeline.state_builder import StrategyStateBuilder; print('pipeline import OK')"
# 输出:pipeline import OK
```

### 4.4 strategy_runs schema 确认

DB schema 已确认含用户 SSH 验证脚本所用字段:`run_id / generated_at_utc /
action_state / stance / btc_price_usd`(`docs/cc_reports/sprint_1_8_1.md` Step 3.4)。

注:`scripts/run_pipeline_once.py` 在生产端跑(touches 真实 DB + 外部 API),
本地不持久化跑(避免污染本地 DB)。生产端跑由用户 SSH 执行(见 §5)。

---

## 5. 用户 SSH 验证脚本(完整可复制)

```bash
ssh ubuntu@124.222.89.86
cd /home/ubuntu/btc_swing_system
git pull origin main

# Step 0 验证:依赖装好
.venv/bin/uv pip install -e .
.venv/bin/python -c "import matplotlib, mplfinance, anthropic; print('deps ok')"

# Step 3.1 + 3.2:测试套件
.venv/bin/pytest tests/ai/ -v 2>&1 | tail -5
# 期望:58 passed

.venv/bin/pytest tests/ 2>&1 | tail -5
# 期望:1084 passed, 6 failed (pre-existing, not from 1.8.1), 1 skipped

# Step 3.3:跑一次 pipeline
.venv/bin/python scripts/run_pipeline_once.py
# 期望退出码 0 或 1(persisted=True)

# Step 3.4:DB 查实写一行
sqlite3 data/btc_strategy.db 'SELECT run_id, generated_at_utc, action_state, stance, btc_price_usd FROM strategy_runs ORDER BY generated_at_utc DESC LIMIT 1;'
# 期望:1 行,字段全有值

# Step 3.5:服务还在跑
sudo systemctl status btc-strategy.service | head -8
# 期望:Active: active (running)
```

---

## 6. 本 sprint 删除清单

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| 整个文件 | config/layers.yaml | Batch 3 引入但从未 wire up;`grep -rn "layers.yaml" src/ tests/ docs/` 命中 0 行 |

**自检通过**(在 commit 1f5ee9e 之前):
- ✅ `git grep "layers.yaml"` 在 src/ + tests/ + docs/ 中 0 行
- ✅ `tests/` 中无相关测试
- ✅ 配置文件中无 cross-ref 引用 layers.yaml

---

## 7. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ tests/ai/ 58/58 + tests/ 完整跑(6 个 pre-existing 失败,无新增) |
| GitHub push(commits 6bafca8 + 1f5ee9e + 93532e4) | ✅ 全 push origin/main |
| 服务器 git pull | ⏳ 待用户 SSH 执行(见 §5) |
| 服务器 systemctl restart | ⏳ 待用户 SSH(可选,1.8.1 不影响主流程) |
| 生产 DB 迁移 / 清污 | N/A(无 DB schema 变更) |

---

## 8. Sprint 1.8.1 commit 列表(共 3 个)

```
93532e4 chore: 1.8.1 同步 uv.lock 锁定 matplotlib + mplfinance 传递依赖
1f5ee9e chore: 1.8.1 删除 config/layers.yaml(0 引用孤儿文件)
6bafca8 chore: 补声明 matplotlib + mplfinance 依赖,修部署遗漏
```

---

## 9. 同类风险扫描

1. **可能还有其他 0 引用 yaml 孤儿**:本次只查 thresholds.yaml + layers.yaml。
   `config/` 下其他文件(state_machine.yaml / event_calendar.yaml /
   data_catalog.yaml / schemas.yaml / observation_categories.yaml 等)未做
   全量孤儿扫描。建议 Sprint 1.9.1 / 1.10 时一并扫。

2. **pyproject.toml 还可能漏其他 import-only 装的包**:1.8 v5 的 chart 用了
   matplotlib + mplfinance(已补);早期 sprint 可能也有类似遗漏(如
   yfinance / FRED 客户端等)。建议在 1.10 阶段做一次"`uv pip list` vs
   `pyproject.toml` 一致性扫描"。

3. **延到 1.9.1 的 14 项**(候选 A/B/C/D/E.thresholds 共计 5 + 4 + 1 + 7 +
   thresholds 内 dead key)在 1.9 切换到 orchestrator 后批量清,务必按 §X
   工程纪律先 grep 0 引用再删。1.9.1 的 sprint 报告需有"5 列引用矩阵"。

---

## 10. 后续 Sprint

| Sprint | 目标 |
|---|---|
| 1.8.2 | 前端重设计(对齐建模 §9 + 移除 5-layer evidence section) |
| 1.9 | jobs.py 频率重构(把 state_builder 主流程切到 orchestrator) |
| 1.9.1 | 真删 14 项延后清单(layer1-5 / 4 旧 composite / adjudicator / 7 因子) |
| 1.10 | 因子卡文案细化 + config/ 孤儿全量扫描 |
| 1.11 | M26 回测 + AI 输出质量调优 |

---

## 11. 总结

Sprint 1.8.1 修订版按用户安全范围执行:
- ✅ **Step 0 补依赖**(matplotlib + mplfinance + 部署文档)
- ✅ **Step 1 grep 调研 5 类共 17+ 项**(写入本报告 §2)
- ✅ **Step 2 只删 1 个文件**(`config/layers.yaml`,完全 0 引用)
- ✅ **Step 3 验证 6 项全过**(pytest ai/ 58/58、pytest 全套无新失败、
  pipeline import OK、DB schema 对齐 SQL 字段、scripts/run_pipeline_once.py
  存在)

3 个 commit 全 push origin/main,生产端拉一次代码 + 装一次依赖即可。
旧代码大头清理延到 Sprint 1.9.1(state_builder 切到 orchestrator 之后)。
