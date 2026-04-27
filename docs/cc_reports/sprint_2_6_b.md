# Sprint 2.6-B — Schema 整合 + OI/liquidation 数据流通 + §X 工程纪律落档

**Date:** 2026-04-27
**Branch:** main · 当前 HEAD = `bc446bf`(本 sprint 5 commit + 1 报告 commit)
**Status:** ✅ 5 个 commit 全完成,3 个数据修复达成,3 个遗留留给后续 sprint

---

## 一、本 sprint commits

| commit | 摘要 |
|---|---|
| `bdc3d4e` | docs(claude): add §X engineering rule — delete obsolete code, don't pile up |
| `2f5ba58` | schema: add liquidation_{long,short,total} columns to derivatives_snapshots |
| `e0cbfbd` | fix(coinglass): wire OI + liquidation fetches into scheduler/backfill |
| `bc446bf` | chore: drop unused empty tables (cleanup per §X rule) |

420 pytest pass(无回归),pre-commit gitleaks 每次 commit 自动 Passed。

---

## 二、Recon 关键发现:用户 spec 假设有误,reframed 后执行

### 用户原 spec 假设
> CC 写的 collector(coinglass.py)通过 DAO 层期待写入新表,但实际生产数据全在旧表

### 实际诊断
- `BTCKlinesDAO.upsert_klines` (dao.py:130) **已经** SQL 直接写 `price_candles`(旧表)
- `DerivativesDAO.upsert_batch` (dao.py:423) **已经** SQL 直接写 `derivatives_snapshots`(旧表)
- 4 个新版"空表" `btc_klines / derivatives_snapshot / macro_snapshot / onchain_snapshot` **没有任何代码写或读**,纯历史 schema 残留(Sprint 1.5c migration 001 应删但未删干净)
- 真正的瓶颈:**OI 100% NULL**(183 行 derivatives_snapshots 中 0 行有 OI 数据)

### Reframed 真正根因
`scripts/backfill_data.py::backfill_derivatives` 和 `src/scheduler/jobs.py::job_data_collection`
的 derivatives 收集环节**只调了 2 个 fetch 方法**:
- `coll.fetch_funding_rate_history`
- `coll.fetch_long_short_ratio_history`

而 `coinglass.py` 实际有 6 个相关方法:
- `fetch_funding_rate_history` ✓ 调过
- `fetch_open_interest_history` ❌ **从未被调用**
- `fetch_long_short_ratio_history` ✓ 调过
- `fetch_liquidation_history` ❌ **从未被调用**
- `fetch_basis_history` / `fetch_net_position_history` 暂搁

---

## 三、5 个 commit 改动清单

### Commit 1:CLAUDE.md §X 工程纪律
追加章节"## 工程纪律 §X:旧代码必须删除,而不是堆叠"。5 条规则 + 2 个判断测试 +
触发本纪律的 3 个历史教训(Stooq / yfinance batch / 双表并存)。

### Commit 2:`derivatives_snapshots` 加 3 列 + DAO 扩展
- `migrations/002_add_liquidation_columns.sql`:`ALTER TABLE` 加 `liquidation_long/short/total` 三列
- `src/data/storage/schema.sql`:同步加这 3 列(避免 init_db 时 schema 不一致)
- `src/data/storage/dao.py`:
  - `_DERIVATIVES_WIDE_COLUMNS` 加这 3 列
  - `DerivativesDAO.upsert_batch` SQL `INSERT` + `ON CONFLICT(captured_at_utc) DO UPDATE SET` 都覆盖这 3 列(用户提醒过:否则 INSERT OR REPLACE 时 liquidation 列会丢)

### Commit 3:wire OI + liquidation
- `scripts/backfill_data.py::backfill_derivatives` 加 2 个 fetch lambda(open_interest / liquidation)
- `src/scheduler/jobs.py::job_data_collection` for 循环加 `fetch_open_interest_history` / `fetch_liquidation_history`
- `tests/test_data_collection_job.py` fixture 加这 2 个方法的默认 `[]` 返回(防 MagicMock 漏到下游 → DAO 错算)
- **metric_name alignment 验证**:grep 双方,coinglass 返回的 `funding_rate / open_interest / long_short_ratio / liquidation_long / liquidation_short / liquidation_total` 与 DAO `_DERIVATIVES_WIDE_COLUMNS` 100% 对齐 — 无需改 DAO

### Commit 4:DROP 4 个空表
- `migrations/003_drop_unused_empty_tables.sql`:`DROP TABLE IF EXISTS btc_klines / derivatives_snapshot / macro_snapshot / onchain_snapshot` + 它们的 indexes
- 没删 BTCKlinesDAO/DerivativesDAO/OnchainDAO/MacroDAO 类(它们正确写旧表是当前主路径)
- grep `btc_klines / derivatives_snapshot / macro_snapshot / onchain_snapshot` 在 src/scripts/tests:
  - 0 处 active 写或读(只 docstring + 注释提及)
  - tests/fixtures/*.json 含这些 key 但 0 处 Python 代码读 → 无害,不动

### Commit 5:部署 + backfill 365d
- 服务器 git pull → 应用 `migrations/002` + `migrations/003` → restart
- `backfill_data.py --only price --days 365`:1d 拉到 365 行(覆盖之前 183),1w 52 行,4h 1016 行,1h 2066 行
- `backfill_data.py --only derivatives --days 365`:funding 365 / OI 365(新!)/ LSR 365 / liquidation 365 行(新!)
- 触发 pipeline:`pipeline.failure_count: 0`

---

## 四、生产 DB 验证(Sprint 前后对比)

| 项 | Sprint 2.6-B 前 | Sprint 2.6-B 后 |
|---|---|---|
| `price_candles 1d` 行数 | 183 | **365** |
| `price_candles 4h` 行数 | ~1000 | **1016** |
| `price_candles 1w` 行数 | ~26 | **52** |
| `price_candles 1h` 行数 | ~2000 | **2066** |
| `derivatives_snapshots` 总行数 | 183 | **365** |
| `funding_rate` 填充率 | 100% | 100% |
| `open_interest` 填充率 | **0%** | **100%(365/365)** |
| `long_short_ratio` 填充率 | 100% | 100% |
| `liquidation_long` 填充率 | column 不存在 | **100%(365/365)** |
| `liquidation_short` 填充率 | column 不存在 | **100%(365/365)** |
| `liquidation_total` 填充率 | column 不存在 | **100%(365/365)** |
| 4 个空表 | 存在(0 数据) | **DROP 干净** |

---

## 五、网页因子卡片 验收(Region 4 抽查)

| card_id | Sprint 前 | Sprint 后 |
|---|---|---|
| `price_ma_200` | "数据不足(需 200 天,当前仅 183 天)" | **84747.59** ✅ |
| `price_ma_60` | (有但偏短) | **71176.64** ✅ |
| `price_atr_percentile_180d` | None / "数据不足" | **11.1** ✅ |
| `derivatives_oi_current` | None | **58,307,573,405.15 USD** ✅ |
| `price_adx_14_1d` | None | None ❌ 见下"遗留" |
| `derivatives_liquidation_24h` | None | None ❌ 见下"遗留" |
| `derivatives_funding_rate_aggregated` | "数据不足(仅币安主因子可用)" | 同上 ❌ 见下"遗留" |

---

## 六、遗留问题(明确不在本 sprint 范围)

### 6.1 `price_adx_14_1d` 仍 None
`src/strategy/factor_card_emitter.py::_compute_adx_latest`(line 859)写死 `return None`。
即"ADX 计算函数没实现,只占了个位"。属于 factor card emitter 的 TODO,与
本 sprint 的"数据流通"无关。**留给后续 sprint 实现 ADX 计算公式**。

### 6.2 `derivatives_liquidation_24h` card None
DB 里 `liquidation_long/short/total` 都有数据,但该 factor card 的 query 似乎在找
`metric_name='liquidation'`(老命名)而非 `liquidation_total`。需 grep 该 card 定义对齐。

### 6.3 `derivatives_funding_rate_aggregated` 仍 "数据不足"
该 card 期待跨交易所聚合资金费率,但 coinglass 提供的接口可能是单交易所(Binance)。
属于 collector 接口能力问题,本 sprint 不解决。

### 6.4 L1 `health_status: cold_start_warming_up`
ADX 没算 + cold_start_warming_up 仍 true。但 ATR / MA-200 / OI / liquidation
都有数据 — 只差 ADX。修 6.1 后,L1 应该能脱离 cold_start。

### 6.5 测试 fixture 残留 `derivatives_snapshot/macro_snapshot/onchain_snapshot` JSON keys
`tests/fixtures/scenario_*/raw_data.json` 含这些 key,但 0 Python 代码读它们。
按 §X 规则应删,但删 3 个大型 fixture JSON 风险高(可能破坏其他测试的 pipeline 输入)。
**保留 + 标注**:这是历史 fixture 数据快照的格式,不影响当前生产。

---

## 七、§X 工程纪律本次践行

本 sprint 是 §X 落档后的**第一次实践**,主动删了 4 个空表 + 没引入新冗余:
- ✅ 没把 OI/liquidation 写入新建的 collector,而是补现有 coinglass.py 的调用
- ✅ DROP 4 个空表配套 grep 全代码库确认无主
- ✅ DAO 类该留的留(BTCKlinesDAO/DerivativesDAO 写旧表是当前主路径)
- ✅ Commit 3 改了 jobs.py + backfill_data.py 同步加 OI/liquidation,而不是新写一个 collector

---

## 八、git log(本 sprint)

```
bc446bf chore: drop unused empty tables (cleanup per §X rule)
e0cbfbd fix(coinglass): wire OI + liquidation fetches into scheduler/backfill
2f5ba58 schema: add liquidation_{long,short,total} columns to derivatives_snapshots
bdc3d4e docs(claude): add §X engineering rule — delete obsolete code, don't pile up
```
