# Sprint 2.6-I — LTH/STH realized price 重新接入(路径 B 精确加权)

**Date:** 2026-04-27
**Branch:** main
**Status:** ✅ 4 个 commit 全完成

---

## 一、背景

Sprint 2.6-F.3 基于"endpoint 不存在"删除了 `fetch_lth_realized_price` /
`fetch_sth_realized_price`。后续调研(metadata endpoint 实测)发现:

1. alphanode 中转支持 Glassnode **Tier 3 / Premium / institutional**(treasuries、
   account-based、entity_adjusted、breakdowns 全部 200 OK 验证过)
2. 没有独立的 lth/sth_realized_price endpoint(F.3 这点正确)
3. **但** 通过 `/v1/metrics/breakdowns/price_realized_usd_by_age` +
   `/v1/metrics/breakdowns/supply_by_age` 客户端 supply 加权聚合可得

用户决定走精确加权(路径 B),非简单代表桶近似(路径 A)。

---

## 二、Commits

| commit | 摘要 |
|---|---|
| `f8b9af2` | feat(glassnode): LTH/STH realized price via age-bucket weighted aggregation |
| `666b49d` | test(glassnode): end-to-end DB-count assertion for LTH/STH realized price |
| `da6b069` | test(emitter): verify LTH/STH realized price cards revive with seeded data |
| (本)     | docs(reports): sprint_2_6_i complete |

511 pytest pass(F.3 后 491 → I 后 511,新增 20:11 unit + 2 e2e + 2 emitter render + 5 wiring 调整)。

---

## 三、Triggers(偏离 spec 的自主决策)

1. **使用 `/breakdowns/supply_by_age` 而非 `marketcap_realized_usd_by_age`**:
   spec 写"或 supply_by_age 也行,先 metadata 列表确认"。metadata 实测
   `supply_by_age` 在列,直接用更直观(supply 做 supply 加权,不需要先除以 price)。

2. **emitter 卡定义未改**:F.3 当时只删了 collector 层,**没** 删 emitter 卡定义
   (factor_card_emitter.py:1088-1095 一直保留)。复用比重写更对齐 §X。
   Commit 3 是端到端验证测试,no code change。

3. **3m_6m 桶归 STH** 是用户 spec 明文要求的简化处理(桶中点 135 天 < 155 天阈值),
   docstring 注明。`more_10y` 桶 spec 没列出但显然属 LTH,加进去(在 metadata 中存在)。

4. **实例级 HTTP 缓存** 共享 2 次 fetch:`fetch_lth_realized_price` 与
   `fetch_sth_realized_price` 都会触发 `_fetch_lth_sth_realized_price(since_days)`,
   缓存键 `(since_days,)` 让两个公开函数总共只发 2 次 HTTP 而非 4 次。

---

## 四、路径 B 加权公式(请用户对照建模复核)

### 桶分组(155 天切分,行业惯例)

| 分组 | 桶集合 | 时长范围 |
|---|---|---|
| **STH** | `24h`, `1d_1w`, `1w_1m`, `1m_3m`, `3m_6m` | < 6 个月(含 90-180 天的 3m_6m 桶,简化) |
| **LTH** | `6m_12m`, `1y_2y`, `2y_3y`, `3y_5y`, `5y_7y`, `7y_10y`, `more_10y` | ≥ 6 个月 |
| **不参与** | `aggregated` | 全市场聚合,与 LTH/STH 互斥 |

### 加权公式(每个时间点)

```
LTH_realized_price[t] = Σ(price_bucket[t,b] × supply_bucket[t,b])  /  Σ(supply_bucket[t,b])
                        b ∈ LTH_BUCKETS
STH_realized_price[t] 同公式,b ∈ STH_BUCKETS
```

### 数据源

| Endpoint | 用途 | 实测 |
|---|---|---|
| `/v1/metrics/breakdowns/price_realized_usd_by_age` | 各桶的 realized price (USD) | 200 ✓ |
| `/v1/metrics/breakdowns/supply_by_age` | 各桶的 supply (BTC) | 200 ✓ |

### 边界处理(代码 docstring 详细)

- **某 bucket price 或 supply 缺**:跳过该 bucket,其他 bucket 正常加权
- **bucket supply ≤ 0**:跳过(避免噪声)
- **某 ts 全 LTH 桶都缺**:该 ts 不出 LTH 行(STH 仍可能出)
- **price 与 supply 时间戳不重合**:只 join 共同 ts

`source` 字段标 `glassnode_derived_breakdown_by_age`(与原生 endpoint 区分,审计便利)。

---

## 五、F.3 → I 对照表

| 资产 | F.3 后状态 | Sprint 2.6-I 后状态 |
|---|---|---|
| `_PATH_LTH_REALIZED_PRICE` 常量 | ❌ 删除 | ❌ 仍删除(那个 endpoint 真的 404) |
| `_PATH_STH_REALIZED_PRICE` 常量 | ❌ 删除 | ❌ 仍删除 |
| `_PATH_PRICE_REALIZED_BY_AGE` 常量 | (不存在) | ✅ 新增 |
| `_PATH_SUPPLY_BY_AGE` 常量 | (不存在) | ✅ 新增 |
| `_STH_BUCKETS / _LTH_BUCKETS` | (不存在) | ✅ 新增 |
| `fetch_lth_realized_price` 方法 | ❌ 删除 | ✅ 复活,实现完全不同(走 breakdowns 聚合) |
| `fetch_sth_realized_price` 方法 | ❌ 删除 | ✅ 复活,实现完全不同 |
| `_aggregate_lth_sth_realized_price` 类方法 | (不存在) | ✅ 新增,纯函数,11 单元测试覆盖 |
| `_fetch_breakdown_by_age` 内部 helper | (不存在) | ✅ 新增 |
| `collect_and_save_all` 注册项 | ❌ 删除 | ✅ 复活 |
| `jobs.py glassnode loop` 注册 | ❌ 删除 | ✅ 复活 |
| `backfill_data.py fetches dict` 注册 | ❌ 删除 | ✅ 复活 |
| factor_card_emitter `_ref_specs` 卡定义 | ✅ 一直保留(F.3 没删) | ✅ 沿用,no-op |
| F.3 测试断言 "方法已删" | ✅ 测试通过 | 🔄 翻转为"方法存在"(都通过) |

---

## 六、测试覆盖

```
$ python -m pytest tests/test_glassnode_lth_sth_aggregator.py \
                   tests/test_lth_sth_realized_price_e2e.py \
                   tests/test_lth_sth_realized_price_card_render.py \
                   tests/test_glassnode_collect_all.py \
                   tests/test_glassnode_3_new_metrics_actually_fetched.py -q
26 passed in 0.5s

$ python -m pytest -q
511 passed, 1 skipped, 138 warnings in 96.57s
```

### §Z 端到端 DB 行数断言(本次新增纪律)

`tests/test_lth_sth_realized_price_e2e.py`:mock `_request` 返回 fixture →
真 SQLite + 真 OnchainDAO + 真 backfill_onchain → SELECT COUNT(*) > 0 +
值在 BTC 价格区间 (5000-100000) + STH avg > LTH avg(年龄结构正确性 sanity)。

这是 F.1 / F.3 mock-only `.called=True` 测试的升级版 — `.called=True` 不等于
DB 真有数据。本次明确建立 §Z 模式。

---

## 七、用户验证脚本(部署后)

```bash
ssh user@124.222.89.86
cd /path/to/btc_swing_system
git pull
.venv/bin/python scripts/backfill_data.py --only onchain --days 365 2>&1 | \
  grep -E "lth_realized_price|sth_realized_price"
# 预期:看到两行 "[onchain.lth_realized_price] fetched=N upserted=N"

sqlite3 data/btc_strategy.db <<'SQL'
SELECT metric_name, COUNT(*) AS rows, MIN(value) AS min_v, MAX(value) AS max_v,
       MIN(captured_at_utc) AS first_ts, MAX(captured_at_utc) AS last_ts
FROM onchain_metrics
WHERE metric_name IN ('lth_realized_price','sth_realized_price')
GROUP BY metric_name;
SQL
# 预期:每个 metric_name 行数 200+(取决于 since_days),value 在 BTC 价格区间。
# STH avg 通常应 > LTH avg(短期持有者成本基线更高)。

sudo systemctl restart btc-strategy
.venv/bin/python scripts/run_pipeline_once.py
# 浏览器访问 http://124.222.89.86 → 链上 reference 区,
# 应看到 "LTH 实现价格" + "STH 实现价格" 两张卡 current_value 不再 None。
```

---

## 八、§X / §Y / §Z 践行

- ✅ §X:复用现有 emitter 卡定义(F.3 没删的部分);老 `_PATH_LTH_REALIZED_PRICE` /
  `_PATH_STH_REALIZED_PRICE` 常量真的不要(404 endpoint),不复活
- ✅ §Y:每个 commit 立即 push origin/main
- ✅ §Z 候选(本次明确建立):端到端测试必须断言 DB 行数 / 卡 current_value 真值,
  而不是光 mock 后 .called=True。已在 `test_lth_sth_realized_price_e2e.py` 和
  `test_lth_sth_realized_price_card_render.py` 模式化。

---

## 九、剩余风险与后续

1. **同类多入口风险残存**:`collect_and_save_all` / `jobs.py` / `backfill_data.py`
   三处独立维护各自的 fetch 列表。Sprint 2.6-F → F.1 → F.3 → F.4 → I 全部踩过这个坑。
   下个候选:把 jobs.py + backfill 改造为都调 `collect_and_save_all`,消除分叉。
   (估 1 hour,可能需要 collect_and_save_all 加 since_days 参数透传)
2. **`source` 字段值新增** `glassnode_derived_breakdown_by_age`:onchain_metrics 现在
   有 4 种 source 值(`glassnode_primary` / `glassnode_display` / `glassnode_derived_breakdown_by_age` / 历史遗留 `glassnode`)。
   schema CHECK 不约束 source,UI 也不展示 source — 不影响功能。如未来要做"数据源审计页面"
   可统一规范。
3. **HTTP 调用次数**:每次 backfill_onchain 多 2 次 HTTP(price_by_age + supply_by_age)。
   `since_days=365` 时一次 backfill 一共 ~14 次 HTTP,完全在 alphanode 配额内。生产
   每小时 scheduler 跑一次,since_days=7 时约 14 行/run,可以忽略。
4. **桶组合在 metadata 演变后可能不一致**:Glassnode 未来增加新桶(如 `15y_more`)
   不会自动归类。当前桶集合是 hardcoded class attrs。如未来增桶需手动维护
   `_STH_BUCKETS` / `_LTH_BUCKETS` 常量(单文件单一处)。
