# Sprint 1.5j — LSR alias 去重 + klines_1h pre_flight 阈值对齐

**Date:** 2026-04-30
**Branch:** main
**Status:** ✅ 本地完成,15 个新测试 + 880/880 全量回归过

---

## 一、根因(用户 SSH 真 DB 复检)

### Bug 1:LSR 24h 变化网页显示 0.0%(应 -13.04%)

DerivativesDAO 数据流:
```
collector → upsert_batch (alias 双写主列 + extras['long_short_ratio'])
         → _explode_row 主列 emit 1 行 + extras emit 1 行(同 ts 同值)
         → get_all_metrics 返回 series 末两行 = 同 daily bar
         → _pct_change(series, 1) = 0.80 / 0.80 - 1 = 0%  ❌
```

SSH 验证:
```
DerivativesDAO.get_all_metrics 返回 long_short_ratio:
  total rows: 360,unique timestamps: 180  ← 每 ts 出现 2 次
```

### Bug 2:klines_1h pre_flight 长期 degraded

1.5g 把 derivatives 改成 captured_at + 30h,但 klines_1h 仍 inserted_at +
10min。1h cron 抖动 1 分钟就直接判 stale → alerts 表噪音 + degraded_stages
持续报警。

**建模锚点**:
- §3.6.1 K 线 cadence:1h K 线 = 每小时一根新 bar
- §3.2.3 数据新鲜度阈值表:价格类容忍 30 分钟级别延迟

---

## 二、改动

### 任务 A:`src/data/storage/dao.py::DerivativesDAO.get_all_metrics`

末尾 `df[~df.index.duplicated(keep="last")]` 去重。

**为什么选 get_all_metrics 末尾去重而不是 _explode_row 不重复 emit**:
- 通用兜底,同时保护 funding_rate / open_interest 未来若有 alias 双写
- 不动 collector / upsert_batch 写入路径,影响面最小
- keep='last' 让后写覆盖前写(extras 比主列后 emit,值漂移时取后者)

### 任务 B:klines_1h captured_at + 2h 阈值

1. **新增** `BTCKlinesDAO.get_latest_captured_at_by_timeframe`
   返回 `{tf: max(open_time_utc)}`
2. `_query_metric_inserted_at` 暴露 `klines_captured_by_tf` 字段
3. `_PREFLIGHT_THRESHOLDS_SEC.klines_1h` 双 trigger 都改 10min → 2h
4. `_latest_iso_for_group(klines_1h)` 改 captured-first + inserted fallback

口径决策表:

| group | 旧 | 1.5g/1.5j | 阈值 |
|---|---|---|---|
| klines_1h | inserted_at | **open_time(captured)** | **2h**(原 10min) |
| derivatives | inserted_at | **captured_at**(1.5g) | 30h(1.5g) |
| klines_1d_4h | inserted_at | inserted_at(暂留) | 30h |
| onchain / macro | inserted_at | inserted_at | 30h / 10min |

---

## 三、测试

### `tests/test_lsr_alias_dedup.py`(4 测试,Task A)

| 测试 | 验证 |
|---|---|
| `test_get_all_metrics_lsr_no_duplicate_ts` | alias 双写 → series 每 ts 1 行 |
| **`test_lsr_24h_pct_change_uses_distinct_days`** | **关键反退化**:`_pct_change(series, 1)` ≈ -13.04% (±0.05) |
| `test_get_all_metrics_no_alias_no_change` | 无双写场景 dedup 是 no-op |
| `test_dedup_keeps_last_value_per_ts` | 同 ts 双写值不同 → keep last |

### `tests/test_pre_flight_klines_1h_threshold.py`(11 测试,Task B)

| 测试 | 验证 |
|---|---|
| 阈值表 | `_PREFLIGHT_THRESHOLDS_SEC.klines_1h == 2h`(双 trigger) |
| 反退化 | `> 10 * 60` |
| `_latest_iso_for_group` | captured 优先 / 缺失 fallback / 全空 None |
| `_evaluate_freshness` | -1.5h 通过 / -3h 失败 / -119min 边界通过 / 8h 档同 2h |
| DAO 端到端 | `get_latest_captured_at_by_timeframe` 返回 max open_time |

### 修复老测试

`tests/test_state_builder_pre_flight.py::test_evaluate_freshness_klines_1h_stale_for_regular`
原断言 11 分钟前 stale(老 10min 阈值);改成 3h 前 stale + 双字段
(`klines_by_tf` + `klines_captured_by_tf`)对齐新口径。

### 全量回归

```
880 passed, 1 skipped, 6.54s
```

(865 baseline + 4 LSR + 11 klines = 880)

---

## 四、改动文件

| 文件 | 改动 |
|---|---|
| `src/data/storage/dao.py` | get_all_metrics 末尾 dedup;BTCKlinesDAO 新增 get_latest_captured_at_by_timeframe |
| `src/pipeline/state_builder.py` | _query_metric_inserted_at 暴露 klines_captured_by_tf;阈值 10min→2h;_latest_iso_for_group klines_1h captured-first |
| `tests/test_lsr_alias_dedup.py` | **新文件** 4 测试 |
| `tests/test_pre_flight_klines_1h_threshold.py` | **新文件** 11 测试 |
| `tests/test_state_builder_pre_flight.py` | 1 老测试改写适配新阈值 |

---

## 五、§X / §Y / §Z 自检

### §X(本 sprint 删除清单)

**本 sprint 无替代关系,无删除项。** 理由:纯修 bug + 加新方法 + 调阈值,
无旧实现被替代。

git grep 自检:
- ✅ `git grep _DERIVATIVES_LSR_ALIASES` → 仅原 2 处(定义 + upsert_batch
  使用),无副本
- ✅ `git grep "klines_1h.*\* 3600"` → 仅 state_builder.py:1238/1251
  双 trigger entry,单一阈值定义来源

### §Y
2 个 commit + 报告 commit,一次性 push 到 GitHub。

### §Z(端到端断言数值)
- LSR `_pct_change(series, 1)` 断言 ≈ -13.04% (±0.05 容差)
- klines_1h captured_at -1.5h 断言 not in failed
- klines_1h captured_at -3h 断言 in failed
- DAO `get_latest_captured_at_by_timeframe` 断言 SQL MAX 结果

### 同类风险扫描
- **funding_rate / open_interest 是否也有 alias 双写**:vulture 看不到,
  但 `_DERIVATIVES_LSR_ALIASES` 是 LSR 专属,其他 metric 无 alias 列表 →
  当前不会双写,但 dedup 兜底也不会引入 regression
- **klines_1d_4h 是否需要同样改 captured-first**:暂留(daily/4h cadence
  慢,inserted_at 直观),如果未来发现 cron 抖动也产生 stale 误报再改
- **fallback 路径(captured 为 None)**:迁移期或异常时仍走 inserted_at,
  阈值 2h 也合理(每小时 cron 应在 2h 内成功)

---

## 六、部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 880 passed, 1 skipped, 6.54s |
| GitHub push(commit hash:`2c8e7e2..d0d2e25` + report) | ✅ 一次性 push |
| 服务器 git pull | ❌ 等用户 SSH 执行 |
| 服务器 systemctl restart | ❌ 等用户 SSH 执行 |
| 生产 DB 迁移 / 清污 | N/A 本 sprint 不动 schema、不动数据 |

### SSH 验证脚本(用户执行)

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service
sleep 5

# 1. LSR 去重验证
.venv/bin/python -c "
from src.data.storage.connection import get_connection
from src.data.storage.dao import DerivativesDAO
conn = get_connection()
m = DerivativesDAO.get_all_metrics(conn, lookback_days=10)
s = m['long_short_ratio'].dropna()
unique_ts = len(set(s.index))
print(f'rows={len(s)}, unique_ts={unique_ts}, '
      f'{\"OK\" if len(s) == unique_ts else \"FAIL\"}')
"
# 预期:rows == unique_ts

# 2. pipeline pre_flight klines_1h 不再 degraded
.venv/bin/python -c "
from src.data.storage.connection import get_connection
from src.pipeline import StrategyStateBuilder
b = StrategyStateBuilder(get_connection())
r = b.run(run_trigger='manual_post_1_5j')
print('degraded_stages:', r.degraded_stages)
"
# 预期:不含 'pre_flight.klines_1h'

# 3. 网页 LSR 24h 数值
curl -s -u admin:Y_RhcxeApFa0H- http://localhost/api/strategy/current \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
cards = d.get('state', {}).get('factor_cards') or []
for c in cards:
    if '多空比 24h' in c.get('name', ''):
        print(f'{c[\"name\"]}: current={c[\"current_value\"]}')
"
# 预期:current ≈ -13.04(不再 0.0)
SSH
```

---

## 七、未覆盖 / 留 v0.6

- `ai_summary` degraded 的 `OPENAI_API_KEY not set` 错误信号清理(本 sprint
  没扫,留 1.5j.1)
- `klines_1d_4h` captured-first 改造(本 sprint 暂留 inserted_at,daily
  cadence 慢,inserted_at 仍直观)
- 历史已写入 DB 的 LSR 重复行**不需要**清理(get_all_metrics 末尾 dedup
  在读路径兜底,DB 多 1 行 extras 不影响其他逻辑)
