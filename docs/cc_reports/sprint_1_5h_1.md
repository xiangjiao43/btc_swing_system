# Sprint 1.5h.1 — 实施 1.5h 审计档 1 + 档 2 删除

**Date:** 2026-04-29
**Branch:** main
**Status:** ✅ 28 个 commit + 865/865 全量回归过

---

## 一、依据

1.5h 审计档 1 (26 项) + 档 2 (2 类) 由用户逐条 ✅ 后实施。
档 1 #23 用户改判为"改不删"(保留计数器,加 summary log);其他全删。

每个改动单独 commit,按用户要求"粒度 1 commit = 1 项",方便回滚。

---

## 二、本 sprint 删除清单(28 项,28 个 commit)

| # | commit | 删除对象 | 路径 / 位置 | 验证 |
|---|---|---|---|---|
| 1 | 5004d4a | `import traceback` | scripts/check_coinglass_endpoints.py:19 | git grep 0 引用 |
| 2 | 6579b59 | `_CLIENT_DEFAULT_MODEL` alias | src/ai/summary.py:24 | git grep 0 引用 |
| 3 | fd8d33a | `get_thresholds_block` 函数 | src/composite/_base.py:45 | git grep 0 引用 |
| 4 | 21b7c36 | `extract_raw` 函数 | src/data/collectors/_field_extractors.py:151 | git grep 0 引用 |
| 5 | a423abc | `_series_from_df` 函数 | src/strategy/factor_card_emitter.py:251 | git grep 0 引用 |
| 6 | ddc01d1 | `compute_adjudicator_distribution` 方法 | src/kpi/collector.py:134 | `_compute_decision` 仍在 line 113 用,保留 |
| 7 | a84ea0f | `BTCKlinesDAO.get_latest_kline` | src/data/storage/dao.py:205 | git grep 0 引用 |
| 8 | fd99fb9 | `_MetricLongTableDAO.get_at`(父类) | src/data/storage/dao.py:333 | Onchain/Macro 子类都没用 |
| 9 | 1eccb22 | `DerivativesDAO.get_at` | src/data/storage/dao.py:606 | git grep 0 引用 |
| 10 | 4463081 | `EventsCalendarDAO.get_next_event` | src/data/storage/dao.py:763 | `get_next_events_by_type` 才是真用版本 |
| 11 | 9e59d85 | `StrategyStateDAO.get_state` + docstring | src/data/storage/dao.py:1020 | docstring 同步移除 get_state 列项 |
| 12 | 65806d9 | `StrategyStateDAO.get_latest_with_state_in` | src/data/storage/dao.py:1051 | git grep 0 引用 |
| 13 | 2b990e0 | `FallbackLogDAO.count_recent_at_level` | src/data/storage/dao.py:1283 | git grep 0 引用 |
| 14 | 47540fd | `FallbackLogDAO.count_consecutive_level_1_ending_at` | src/data/storage/dao.py:1316 | git grep 0 引用 |
| 15 | 2a46179 | `FallbackLogDAO.get_by_stage_frequency` | src/data/storage/dao.py:1320 | git grep 0 引用 |
| 16 | 6dca26e | `RunMetadataDAO.get_run` | src/data/storage/dao.py:1456 | git grep 0 引用 |
| 17 | 6e96f5f | `RunMetadataDAO.get_recent_runs` | src/data/storage/dao.py:1456 | git grep 0 引用 |
| 18 | bbe40b1 | `SwingType` Literal + Literal import | src/indicators/structure.py:14 | git grep 0 引用 |
| 19 | b5d5ecc | `val_oi` tuple unpack → `_` | src/strategy/factor_card_emitter.py:1003 | 只 `ts_oi` 真用 |
| 20 | 79135fe | `loosened` 局部变量 | src/evidence/layer4_risk.py:636 | 同时合并掉旧 merge 注释 |
| 21 | 71deac5 | `headwind_val` 局部变量 | src/evidence/plain_reading.py:301 | 赋值后没读 |
| 22 | ede4103 | `active_tags` 局部变量 | src/evidence/pillars.py:461 | 赋值后没读 |
| 23 | 2cab89c | **改不删**: `rejected_hourly` 加 summary log | src/data/storage/dao.py:upsert_batch | 用户决策:保留计数 + batch 末加 "rejected N rows" warn |
| 24 | 649a3c3 | `_attach_ai` test helper | tests/test_adjudicator.py:78 | git grep 0 引用 |
| 25 | d0504de | `_klines_trending_down` test helper | tests/test_composite_factors.py:62 | git grep 0 引用 |
| 26 | 6c3f185 | `_build_ranging_at` test helper | tests/test_layer1_regime.py:69 | git grep 0 引用 |
| T2.1 | 9a17cdc | `sm1`-`sm5`/`sm7` unused unpack → `_` | tests/test_lifecycle_e2e_reversal.py | sm6 line 298 真用,保留 |
| T2.2 | 45286e9 | `primary` loop var → `_` | tests/test_fred_collector.py:16 | 风格 |

**§X 第 7 条自检**(每条都做了):
- ✅ 每项删前 `git grep <name>` 确认 0 引用
- ✅ 测试 / 配置 / docstring 同步更新(#11 改了 StrategyStateDAO docstring)
- ✅ 删后无残留 import / type alias

---

## 三、回归

```
865 passed, 1 skipped, 8.17s
```

与 1.5h commit `6cb236a` 时基线一致(865/865),0 break。

---

## 四、§X / §Y / §Z 自检

### §X
- 本 sprint 总计删除 ~190 行死代码 + 1 项改进(#23)
- 严格按 audit 档 1 + 档 2 用户决策清单实施,无超范围动作
- StrategyStateDAO docstring §988 同步更新(原列 "get_state",已移除)

### §Y
28 个 commit 一次性 push 到 GitHub origin/main(下条日志)。

### §Z
- 全量 pytest 通过,与 1.5h 基线一致
- 每个删除单独 commit,可独立回滚(git revert <hash>)
- 没有跨 sprint 影响:audit 档 3 false positive 全保留

---

## 五、改动文件汇总

| 文件 | 删除行数 | commit |
|---|---|---|
| `scripts/check_coinglass_endpoints.py` | -1 | #1 |
| `src/ai/summary.py` | net 0(改 alias) | #2 |
| `src/composite/_base.py` | -13 | #3 |
| `src/data/collectors/_field_extractors.py` | -8 | #4 |
| `src/strategy/factor_card_emitter.py` | -7 | #5, #19 |
| `src/kpi/collector.py` | -6 | #6 |
| `src/data/storage/dao.py` | -158, +6 | #7-17, #11 docstring, #23 +log |
| `src/indicators/structure.py` | -3 | #18 |
| `src/evidence/layer4_risk.py` | -2 | #20 |
| `src/evidence/plain_reading.py` | -1 | #21 |
| `src/evidence/pillars.py` | -1 | #22 |
| `tests/test_adjudicator.py` | -8 | #24 |
| `tests/test_composite_factors.py` | -5 | #25 |
| `tests/test_layer1_regime.py` | -10 | #26 |
| `tests/test_lifecycle_e2e_reversal.py` | net 0(rename) | T2.1 |
| `tests/test_fred_collector.py` | net 0(rename) | T2.2 |

**净影响**:总共 -218 行,+10 行,16 个文件。

---

## 六、未覆盖 / 风险提示

- **档 3**(13 类 false positive)按 1.5h 决议**全保留**:FastAPI route
  handler / Pydantic 字段 / dataclass 字段 / `@patch` 注入参数 / sqlite3
  row_factory / pytest marker 等
- **本 sprint 删除集中在 `src/data/storage/dao.py`**(11 个未用 DAO 方法)。
  如果未来 v0.6 需要"按 timestamp 查 derivatives"等场景再补,建议直接
  复用 `get_latest` / `get_series` 或新写命名更明确的方法
- **未来 sprint 起 §X 第 7 条自检会被 CC 主动应用**(audit 不会再大批量
  累积),报告必带"本 sprint 删除清单"段

---

## 七、部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 865 passed, 1 skipped, 8.17s |
| GitHub push(commit hash:5004d4a..45286e9, 28 个 commit) | ✅ 一次性 push 全部 |
| 服务器 git pull | ❌ 等用户 SSH 执行 |
| 服务器 systemctl restart | ❌ 等用户 SSH 执行 |
| 生产 DB 迁移 / 清污 | N/A 本 sprint 不动 schema、不动数据 |

### SSH 部署命令(用户执行)

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service
sleep 5
sudo systemctl status btc-strategy.service | head -20
SSH
```

无需特殊验证,纯死代码删除 + 单个改进 (#23 summary log),功能不变。
