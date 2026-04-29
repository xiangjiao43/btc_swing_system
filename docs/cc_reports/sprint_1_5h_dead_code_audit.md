# Sprint 1.5h — 全局死代码 + 旧文件审计

**Date:** 2026-04-29
**Branch:** main
**Status:** ✅ 审计完成,**未删任何代码**(留 1.5h.1 用户拍板后实施)

---

## 一、扫描方法

1. `uv pip install vulture` → vulture 2.16
2. `vulture src/ scripts/ tests/ --min-confidence 80 --exclude tests/fixtures/`
   → 5 hits,完整结果在 `sprint_1_5h_vulture_raw.txt`
3. 补充 `--min-confidence 60` 扫描 → 100 hits(供过滤后筛真死)
4. 每个 ≥ 60% 候选用 `git grep` 跨 `*.py *.yaml *.html *.js` 复检
5. 排除 false positive(详见档 3 列表)

**总候选**:100 → **真死代码 26 项**(档 1)+ 2 项疑似(档 2)+ 大量
decorator/dataclass/route 误判(档 3)。

---

## 二、档 1:几乎肯定可删(26 项,1.5h.1 实施)

### 2.1 死 import(2 项)

| # | 路径 | 行 | 名称 | 验证 | 处置 |
|---|---|---|---|---|---|
| 1 | `scripts/check_coinglass_endpoints.py` | 19 | `import traceback` | git grep 仅声明行,无 `traceback.` 使用 | 删 import 行 |
| 2 | `src/ai/summary.py` | 24 | `DEFAULT_MODEL as _CLIENT_DEFAULT_MODEL` | git grep 仅声明行 | 删 alias |

### 2.2 死函数(4 项)

| # | 路径 | 行 | 名称 | 验证 | 处置 |
|---|---|---|---|---|---|
| 3 | `src/composite/_base.py` | 45 | `get_thresholds_block` | 0 ref(只 def) | 删函数 |
| 4 | `src/data/collectors/_field_extractors.py` | 151 | `extract_raw` | 0 ref(只 def) | 删函数 |
| 5 | `src/strategy/factor_card_emitter.py` | 251 | `_series_from_df` | 0 ref(只 def) | 删函数 |
| 6 | `src/kpi/collector.py` | 134 | `compute_adjudicator_distribution` | 0 ref(只 def) | 删方法 |

### 2.3 死 DAO 方法(11 项)

| # | 路径 | 行 | 类.方法 | 验证 |
|---|---|---|---|---|
| 7 | `src/data/storage/dao.py` | 205 | `BTCKlinesDAO.get_latest_kline` | 只 def |
| 8 | `src/data/storage/dao.py` | 347 | `OnchainDAO.get_at` | 只 def |
| 9 | `src/data/storage/dao.py` | 631 | `DerivativesDAO.get_at` | 只 def |
| 10 | `src/data/storage/dao.py` | 799 | `EventsCalendarDAO.get_next_event` | 只 def(`get_next_events_by_type` 才是真用) |
| 11 | `src/data/storage/dao.py` | 1070 | `StrategyStateDAO.get_state` | 只 def(docstring §988 列了它,实际无 caller) |
| 12 | `src/data/storage/dao.py` | 1115 | `StrategyStateDAO.get_latest_with_state_in` | 只 def |
| 13 | `src/data/storage/dao.py` | 1365 | `count_recent_at_level` | 只 def |
| 14 | `src/data/storage/dao.py` | 1411 | `count_consecutive_level_1_ending_at` | 只 def |
| 15 | `src/data/storage/dao.py` | 1434 | `get_by_stage_frequency` | 只 def |
| 16 | `src/data/storage/dao.py` | 1608 | `get_run` | 只 def |
| 17 | `src/data/storage/dao.py` | 1618 | `get_recent_runs` | 只 def |

**说明**:这一批是 DAO 层"未来可能用"的 getter 残留。建模 §3 没要求,
现有 pipeline / API 路由也不调用。删除时需同步更新对应类的 docstring(如
`StrategyStateDAO` §988 docstring 列出 "get_state" 要一起改)。

### 2.4 死类型别名(1 项)

| # | 路径 | 行 | 名称 | 验证 | 处置 |
|---|---|---|---|---|---|
| 18 | `src/indicators/structure.py` | 14 | `SwingType = Literal["high","low"]` | 0 ref | 删别名 |

### 2.5 死局部变量(5 项)

| # | 路径 | 行 | 名称 | 现象 |
|---|---|---|---|---|
| 19 | `src/strategy/factor_card_emitter.py` | 1009 | `val_oi, ts_oi = _latest(series)` | `val_oi` 整个函数都没读 → 改 `_, ts_oi = _latest(...)` |
| 20 | `src/evidence/layer4_risk.py` | 636 | `loosened = merge_permissions(merged, _A_GRADE_BUFFER_FLOOR)` | 算了不用,下行用 `final = _min_strict(...)` 重算 |
| 21 | `src/evidence/plain_reading.py` | 301 | `headwind_val = layer_5_output.get("macro_headwind_score")` | 赋值后没读 |
| 22 | `src/evidence/pillars.py` | 461 | `active_tags = l5.get("active_macro_tags") or []` | 赋值后没读 |
| 23a | `src/data/storage/dao.py` | 492 | `rejected_hourly = 0` | 计数器,只 ++,不读 / log /return |
| 23b | `src/data/storage/dao.py` | 503 | `rejected_hourly += 1` | 同上 |

**注意**:#19-22 直接删变量赋值即可。#23 的 `rejected_hourly` 删掉前
**应考虑**:1.5f-revised 加这个计数本意是让 hourly 拒绝可观测;现在
warn log 每行都打了,所以计数确实冗余。删除 OK,但建议在删除时改成
log 一次"summary: rejected N hourly rows"。

### 2.6 死 test helper(3 项)

| # | 路径 | 行 | 名称 | 验证 |
|---|---|---|---|---|
| 24 | `tests/test_adjudicator.py` | 78 | `_attach_ai` | 0 ref(test 文件内部都没调) |
| 25 | `tests/test_composite_factors.py` | 62 | `_klines_trending_down` | 0 ref |
| 26 | `tests/test_layer1_regime.py` | 69 | `_build_ranging_at` | 0 ref |

---

## 三、档 2:疑似可删,需用户决策(2 类)

### 3.1 测试中的命名 unused 变量

`tests/test_lifecycle_e2e_reversal.py:153/171/188/206/237/299`:
`sm1, lc1, st1 = _step(...)` 这种 7 元组解包,7 个 tick 都把 `sm{N}` 留着
没用。**风险低**(不影响测试逻辑),**建议**改为 `_, lc1, st1 = _step(...)`
保持可读性,但删不删都行 — 留给用户拍板。

### 3.2 测试中的 loop 变量名

`tests/test_fred_collector.py:16`:
```python
for primary, aliases in _METRIC_ALIASES.items():
    out.update(aliases)
```
`primary` 没用上 → 改为 `for _, aliases in ...`。**纯风格**,删不删都行。

---

## 四、档 3:看似未使用但是 entry point(不要机械删)

### 4.1 FastAPI route handler(13 个)
`src/api/routes/{alerts,data,evidence,fallback,health,lifecycle,market,pipeline,review,strategy,system}.py`
里所有 `def list_*` / `def get_*` / `def trigger_*` 都被
`@router.get(...)`/`@router.post(...)` 装饰,通过 FastAPI 路由调用,vulture
看不到。

### 4.2 FastAPI lifespan hook(3 个)
`src/api/app.py:_seed_events_on_startup_api / _start_scheduler / _stop_scheduler`
全是 `@app.on_event("startup"/"shutdown")` 装饰,生产路径走的就是它们。

### 4.3 Pydantic schema 字段(`src/api/models.py` 多个)
`uptime_seconds / db_accessible / preflight_alerts_24h / scheduler_running /
scheduler_jobs_count / created_at / failure_count / latest_timestamp_utc /
row_count` 等都是 Pydantic BaseModel 字段定义,FastAPI 通过反射序列化,
vulture 看不到。

### 4.4 dataclass 字段(`src/strategy/state_machine.py`)
`previous_state / transition_reason / matched_conditions /
minutes_since_entered / stable_in_state / on_enter_effects` 是 `@dataclass`
字段,通过 `asdict(self)` 全字段序列化,vulture 看不到。
同理 `src/data/storage/dao.py:82 volume_usdt`。

### 4.5 `@patch` 装饰器注入参数
`tests/test_ai_summary.py:171/185/198 mock_sleep` 是
`@patch("...time.sleep")` 把 mock 注入到方法参数,pytest 调用,vulture
看不到。

### 4.6 pytest 收集 marker
`tests/test_ai_summary_smoke.py:20 pytestmark` 是 pytest 全局 marker,
框架反射,vulture 看不到。

### 4.7 sqlite3.Connection.row_factory
所有 `tests/*.py` 中 `conn.row_factory = sqlite3.Row` 都被 sqlite3 C 扩展
内部读取,vulture 看不到 → 全部 false positive。

### 4.8 collector script body 引用
`scripts/test_glassnode_collector.py:76 primary` 实际在 line 84
(`for m in primary`)使用,vulture 行错位误判。

---

## 五、扫描中没发现的潜在死代码区域

### 5.1 整文件级别(没有 0-import 的文件)
`grep -L "^from\|^import" src/**/*.py` 没找到独立"死文件";
所有 src/ 下文件都被某处 import。

### 5.2 旧 schema 表
migration 003 已彻底删 `btc_klines / derivatives_snapshot` 等(不是
`derivatives_snapshots` 那张活的),无残留。

### 5.3 `*old* / *legacy* / *deprecated* / *_v1*` 文件名
`find` 0 命中(除假阳性如 `cold_start.py / macro_btc_gold.py /
test_pre_flight_derivatives_threshold.py`)。

### 5.4 `DEPRECATED` 注释 marker
`git grep -l "DEPRECATED\|deprecated_"` 0 命中。

---

## 六、自检 §X / §Y / §Z

### §X(本 sprint **不删**)
本 sprint 任务就是审计,产物是档 1 清单。1.5h.1 才实施删除。
档 1 清单**不再继续接外部审计**,以后所有 sprint 必须自带"本 sprint 删除清单"。

### §Y
本 commit 立即 push。

### §Z(审计正确性证据)
- vulture raw 输出已 commit(`sprint_1_5h_vulture_raw.txt`)
- 每个档 1 候选都附 git grep 验证摘要
- 档 3 false positive 给出**机制级理由**(decorator / dataclass / sqlite3
  C 扩展),不是凭直觉拍

---

## 七、改动文件

| 文件 | 改动 |
|---|---|
| `docs/cc_reports/sprint_1_5h_vulture_raw.txt` | **新文件** vulture 80% 原始输出 |
| `docs/cc_reports/sprint_1_5h_dead_code_audit.md` | **新文件** 本审计报告 |
| `CLAUDE.md` | §X 加 6/7 条 + 协议加部署 + 删除清单段(见 sprint 1.5h §B 改动) |

---

## 八、本 sprint 删除清单

**本 sprint 无替代关系,无删除项。**

理由:1.5h 任务就是产出审计清单本身,**不实施删除**。删除工作在
1.5h.1 由用户审完档 1 后逐条确认实施,届时 1.5h.1 报告必带"本 sprint
删除清单"段(列档 1 中 ✅ 通过审定的项)。

---

## 九、部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅(本 sprint 仅审计 + 改 CLAUDE.md/docs,无代码改动) |
| GitHub push(commit hash:见 commit) | ✅ |
| 服务器 git pull | N/A(本 sprint 无运行时改动) |
| 服务器 systemctl restart | N/A |
| 生产 DB 迁移 / 清污 | N/A |

---

## 十、用户验收 checklist

请逐条标 ✅/❌ 后回复,作为 1.5h.1 实施输入:

- [ ] 档 1 #1-2 死 import(2 项)同意删
- [ ] 档 1 #3-6 死函数(4 项)同意删
- [ ] 档 1 #7-17 死 DAO 方法(11 项)同意删 / 部分保留(可指定哪几个保留为"未来 v0.6 预留 API")
- [ ] 档 1 #18 SwingType 同意删 / 保留(若计划在 indicators 重构中用)
- [ ] 档 1 #19-23 死局部变量(6 处)同意删
- [ ] 档 1 #24-26 死 test helper(3 项)同意删
- [ ] 档 2 测试 unused tuple 解包(sm1-sm7 / primary)同意改为 `_` / 不改
- [ ] 档 3 全部不动(确认理解机制级 false positive)
