# Sprint 2.6-F — 5 个数据缺失补全

**Date:** 2026-04-27
**Branch:** main
**Status:** ✅ 3 个 commit 全完成,部署留给用户

---

## Triggers(偏离 spec 的自主决策)

1. **Commit 1 reframed**:用户 spec 说"如果漏了 lth_realized_price / sth_realized_price 补上"。
   实际代码已存在(`glassnode.py:352, 361`)且已注册(`collect_and_save_all` line 430-431),
   `fetch_sopr_adjusted` (= aSOPR) 也已有(line 379)。无代码改动,改写 source-level
   regression guard 锁住未来不被误删。

2. **Commit 3 实施位置**:用户 spec 给了 state_builder / macro_headwind 两个候选放 corr 计算。
   实际选择"在 emitter 内联计算"——数据(klines_1d + macro)已都在 emitter 调用栈,
   函数签名加 1 个 `klines_1d` kwarg 即可,不污染 state_builder 的通用 context。

3. **schema 不需要改**:`funding_rate_aggregated` 流向 `derivatives_snapshots` 的
   `full_data_json` extras(走 `_explode_row` 反向展开),不需要新加 wide 列。

---

## Commits

| commit | 摘要 |
|---|---|
| `43e468f` | test(glassnode): regression guard for 13 metrics in collect_and_save_all |
| `d247ff0` | feat(coinglass): add OI-weighted funding rate across exchanges |
| (本)     | feat(macro): add gold price + BTC-gold 60d correlation |

---

## Commit 1:Glassnode metric coverage(regression guard 而非新代码)

文件:`tests/test_glassnode_collect_all.py`(新建,3 测试)

- `test_collect_and_save_all_registers_all_13_metrics`:source-level 检查 13 个 metric label
  都出现在 `collect_and_save_all` 函数体里(防止未来误删)
- `test_glassnode_has_lth_sth_realized_price_methods`:fetch 方法存在性
- `test_glassnode_has_asopr_method`:`fetch_sopr_adjusted` 即 aSOPR 存在性

13 metric 清单(见 glassnode.py:420-435):
- Primary 5:`mvrv_z_score / nupl / lth_supply / exchange_net_flow / btc_price_close`
- Display 7:`mvrv / realized_price / lth_realized_price / sth_realized_price / sopr / sopr_adjusted / reserve_risk / puell_multiple`

---

## Commit 2:CoinGlass aggregated funding rate

### 文件改动
1. `src/data/collectors/coinglass.py`:
   - 新增 `_PATH_FUNDING_AGG = "{prefix}/futures/funding-rate/oi-weight-history"`
   - 新增 `fetch_funding_rate_aggregated(interval='h8', limit=500, symbol='BTC')` 方法
     - **不传 exchange 参数**(聚合端点 symbol=BTC 隐含跨所)
     - 解析 OHLC close 为 metric_value
     - `metric_name = "funding_rate_aggregated"`
   - `collect_and_save_all` 的 `derivatives_tasks` 注册了新 label

2. `tests/test_coinglass_funding_aggregated.py`(新建,4 测试):
   - 解析 OHLC close
   - endpoint 路径含 `oi-weight-history`
   - 不传 exchange、传 symbol=BTC
   - source-level guard:label 在 `collect_and_save_all` 里

### Schema
**未改 schema**。`funding_rate_aggregated` 不在 `_DERIVATIVES_WIDE_COLUMNS` 里,
会走 `DerivativesDAO.upsert_batch` 的 extras 路径写入 `full_data_json`。
`_explode_row` 会反向展开,下游消费(emitter / composite)按 metric_name 读取无差异。

---

## Commit 3:FRED gold + BTC-gold 60d 相关性

### 文件改动
1. `src/data/collectors/fred.py`:
   - `SERIES_TO_METRIC` 加一项:`"GOLDPMGBD228NLBM": "gold_price"`(London Gold Fixing PM,USD/oz)

2. `src/strategy/factor_card_emitter.py`:
   - `_emit_macro_reference` 函数签名加 `klines_1d` kwarg(call site `factor_card_emitter.py:303` 同步)
   - 现有 `macro_btc_gold_corr_60d` 卡:
     - 之前写死 `current_value=None` + 占位文案
     - 改为读 `macro["gold_price"]` + 调 `_compute_corr_60d(klines_1d, gold)` → 真实数值
   - 新增 `_compute_corr_60d(klines_1d, other_series, lookback_days=60)` helper:
     - 对齐 `pct_change` 后 Pearson(与 layer5_macro `_compute_btc_nasdaq_correlation` 同算法)
     - 数据不足返回 None
     - 异常 → None(永不抛)

3. `tests/test_macro_btc_gold.py`(新建,7 测试):
   - FRED series 注册
   - corr 高(同源数据)/ corr 低(独立随机)/ 数据不足 / 缺失输入
   - `_emit_macro_reference` 卡 `current_value` 不再是 None
   - 无 klines fallback 不抛

---

## 验证

```
$ python -m pytest -q
450 passed, 1 skipped, 138 warnings in 1.98s
```

---

## 待用户部署

```bash
ssh user@server
cd /path/to/btc_swing_system
git pull
.venv/bin/python scripts/backfill_data.py --only macro --days 365   # 拉黄金历史
.venv/bin/python scripts/backfill_data.py --only derivatives --days 7  # 拉聚合资金费率
sudo systemctl restart btc-strategy
.venv/bin/python scripts/run_pipeline_once.py
```

### 预期
- `macro_metrics` 表新增 `gold_price` 行(日频,~250+ 行/年)
- `derivatives_snapshots.full_data_json` 含 `funding_rate_aggregated` key(每 8h 一行)
- 网页 `macro_btc_gold_corr_60d` 卡 current_value 显示真实数值(-1 到 +1)
- factor cards 5 张涉及指标的卡 current_value 不再 None

---

## 遗留

- `funding_rate_aggregated` 走 extras(JSON)而非 wide column。如未来 layer3/composite 需要高频
  访问可考虑提升为 wide 列(对齐 funding_rate),但本 sprint 不做。
- BTC-黄金相关性目前在 emitter 内联计算,与 layer5_macro 的 BTC-纳指 corr 是两套同算法实现。
  如未来需要统一,可抽到 `src/utils/correlations.py`。本 sprint 不做。

---

## §X / §Y 践行

- ✅ §X:Commit 1 不新增重复实现,只加 guard;无旧代码删除诉求
- ✅ §Y:每个 commit 立即 push origin/main
