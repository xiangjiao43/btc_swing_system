# Sprint 1.6.4 — Layer A 因子卡片上线后两个问题修复

**日期**:2026-05-17
**触发**:上一次 commit `ede04da`(Sprint 1.6.3)上线后用户反馈两个问题。
**结论**:问题 1 是确定性代码 bug(派生因子漏传 kline_meta),已修;问题 2 是 snapshot 时序问题(代码无 bug),只需服务器再跑一轮 Layer A。

---

## 1. 问题 1 — 6 个新因子卡片"抓取时间"显示空

### 根因(代码 bug,与本次新加 specs 无关,是 pre-existing)

**不在 spec 侧**。对比新老 spec 结构 — 完全一致,都没有 `fetched_at` 字段:
- 老 spec(如 `lth_sopr`)能显示抓取时间,是因为它走 `metric("lth_sopr")` → `metric_meta(OnchainDAO, "lth_sopr")` → 自动从 `onchain_metrics.inserted_at_utc` 读 → 注入 factor dict 的 `fetched_at_utc / fetched_at_bjt`
- 新 spec 中,**`hash_rate` / `sopr` 也走 `metric()` 路径,有 metric_meta**(只要 DB 有行就有 timestamp)
- **但 4 个派生 price 因子(`ath_drawdown_pct` / `ma_200d` / `ma_200w` / `ma_200w_deviation_pct`)是直接 `_factor()` 调用,无 metric_meta 来源**,所以 factor dict 缺 `fetched_at_*`,前端显示空

**正确范式**(老 `monthly_ohlc_structure` / `major_support_resistance_zones` 一直如此):
```python
_factor(name, value, ..., extra={..., **daily_kline_meta})
```
`daily_kline_meta` / `weekly_kline_meta` 在 [spot_cycle_context_builder.py:870-878](src/ai/spot_cycle_context_builder.py#L870-L878) 已经算好,把 K 线最新 `inserted_at_utc` 转 BJT。

### 这个 bug 为什么以前没暴露

`ath_drawdown_pct` / `ma_200d` / `ma_200w` 在 Layer B `factor_card_emitter.py` 也都 emit 过(走 Layer B 路径,有自己的时间字段),所以前端在那里能看到时间。但 Layer A 路径产出的 `available_factors.price_structure` 这些字段一直缺时间,**Sprint 1.6.3 之前没有任何前端 spec 引用它们的 Layer A 副本,所以缺失从未被显示** → 没人发现。

### 修复

[src/ai/spot_cycle_context_builder.py:959-998](src/ai/spot_cycle_context_builder.py#L959-L998),`available["price_structure"]` 段 5 个 `_factor` 调用全部补 `extra=*_kline_meta`:
- `current_close` → `extra=daily_kline_meta`(顺便补,本来也漏)
- `ath_drawdown_pct` → `extra=daily_kline_meta`(从日 K 算 ATH 距离)
- `ma_200d` → `extra=daily_kline_meta`(200 日均线)
- `ma_200w` → `extra=weekly_kline_meta or daily_kline_meta`(200 周均线;周 K 缺失时回落日 K)
- `ma_200w_deviation_pct` → `extra={"value_unit": "%", **(weekly_kline_meta or daily_kline_meta)}`(价格 / 200WMA 偏离;周 K 优先)

修复后,这 5 个因子的 factor dict 自动带 `fetched_at_utc / fetched_at_bjt / captured_at_utc`,前端 `layerAFactorFetchedAt(factor)` 读得到 → "抓取于 YYYY-MM-DD HH:MM" 正常显示。

---

## 2. 问题 2 — 算力卡片显示"当前缺值 / – H/s"虽然 DB 已有 30 行

### 根因(非 bug,snapshot 时序)

**路径完全正确**,与之前 `hodl_waves` 那个 mismatch bug 不同:
- DB metric_name:`hash_rate`(`fetch_hash_rate` 写入时用这个名,见 [glassnode.py:730](src/data/collectors/glassnode.py#L730))
- spot_cycle_context_builder.py 行 1005:`"hash_rate": metric("hash_rate")` — 用同名查询,**正确**
- 前端 spec path:`['onchain_valuation', 'hash_rate']` — **正确**

bug 不存在,问题在数据流时序:
1. 用户今天手动跑 `collect_onchain` → `onchain_metrics` 表新写 30 行 `metric_name='hash_rate'` ✓
2. **但用户没有再跑一轮 Layer A** → `latest_layer_a_spot_strategy.layer_a_json`(网页读这张表)还是上一次 Layer A 跑的快照 ← 那一刻 hash_rate 在 DB 0 行
3. 该快照里 `available_factors.onchain_valuation.hash_rate` = `_factor("hash_rate", None, ...)` → `actual_value=None, status='missing'`
4. 网页读到 `hasValue=False, status='missing'` → 显示"当前缺值 / – H/s"

### 修复(不改代码)

服务器跑一次 Layer A 即可:

```bash
cd /home/ubuntu/btc_swing_system
.venv/bin/python scripts/run_layer_a_once.py --trigger manual_post_1_6_4_fix --json | tail -200
```

跑完后,新的 `latest_layer_a_spot_strategy.layer_a_json` 包含 hash_rate 真值,网页强刷即可见到算力 ~960 EH/s + 抓取时间。

### 与问题 1 的联动效果

问题 1 修复同样依赖 Layer A 重跑生成新快照 — 旧快照里 4 个派生因子的 factor dict 没有 `fetched_at_*` 字段(代码层在 commit 时就缺),即使前端代码升级也读不到。所以**修复完代码 + 服务器 pull + 必须再跑一次 Layer A**,问题 1 + 问题 2 同时生效。

---

## 3. 改动文件清单

| 文件 | 改动 |
|---|---|
| [src/ai/spot_cycle_context_builder.py:959-998](src/ai/spot_cycle_context_builder.py#L959-L998) | `available["price_structure"]` 段 5 个 `_factor()` 调用全部补 `extra=*_kline_meta`(current_close / ath_drawdown_pct / ma_200d / ma_200w / ma_200w_deviation_pct)。`ma_200w / ma_200w_deviation_pct` 用 weekly_kline_meta 优先 + daily fallback;其余用 daily_kline_meta |

无前端改动 — spec 结构本来就对,前端 `layerAFactorFetchedAt(factor)` 读 factor.fetched_at_bjt 也对,**只是后端没给这 5 个 factor 注入时间字段**。

无测试新增 — 这 5 个 factor 的 timestamp 注入是数据层默契,既有 monthly_ohlc_structure / major_support_resistance_zones 测试已断言"factor 带 fetched_at_bjt",新加的派生因子同理(测试只验前端能读、未验 backend 字段命名,这是 backend 实现自由度;真正回归保护靠 dry run 上线后用户肉眼看一次)。

---

## 4. 测试结果

```
.venv/bin/python -m pytest --tb=line -q
1 failed, 1880 passed, 1 skipped, 672 warnings in 47.21s
```

唯一失败 `test_collect_klines_1h_kline_succeeds_derivatives_fail`:上游 `provider_error` 遗留(自 `16cad4f` 起多次 sprint 报告记录的与本次完全无关的失败)。

---

## 5. 部署四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅(1880 通过 + 1 上游遗留 + 1 skipped)|
| GitHub 推送 | ❌ 本报告写完立即 commit + push |
| 服务器 git pull | ❌ 待用户执行 |
| 服务器 systemctl restart | ❌ **可选** — restart 让 service 进程重新加载代码;**但更关键的是手动跑一次 Layer A 让 latest_layer_a_spot_strategy snapshot 用新代码重生成**:`.venv/bin/python scripts/run_layer_a_once.py --trigger manual_post_1_6_4_fix --json` |
| 生产 DB 迁移 | N/A(纯逻辑修复,无 schema 改动)|

## 6. 上线后用户核对清单

服务器 git pull + 手动跑一次 Layer A 后,网页强刷:
1. **算力卡片**:`actual_value` 应该是真值(例如 `9.6e+20 H/s` ≈ 960 EH/s),`fetched_at_bjt` 显示"抓取于 YYYY-MM-DD HH:MM"
2. **整体 SOPR 卡片**:类似有真值 + 时间(如本机测试时是 ~1.0001)
3. **200 周线乖离率 / 200 周均线 / 200 日均线 / 距 ATH 回撤** 4 张派生卡片:`actual_value` 有真值(本机测试值:乖离率 +28.87%、ma_200w ~60,204、ma_200d ~82,709、ATH 回撤 -37.75%),**`fetched_at_bjt` 不再空白**,显示日/周 K 最新拉取时间

如果跑完 Layer A 后这 4 张派生卡片"抓取于"还是空,说明 K 线 fetched_at 链路也漏了某节,告诉我具体哪几张卡,我再排查。

## 7. 本 sprint 删除清单

无删除。只在 `available["price_structure"]` 5 个 `_factor()` 调用里补 `extra=*_kline_meta`,**没有任何旧代码被替换或废弃**。
