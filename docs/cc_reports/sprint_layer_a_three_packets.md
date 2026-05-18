# Sprint Layer A 数据包重构(4 包 → 3 包)

**日期**:2026-05-17
**触发**:用户指令(无对应 modeling.md §8 Layer A 章节,以指令为准)
**目标**:把 Layer A 数据包从混乱的 4 包(technical / onchain / liquidity_macro / risk)重构为清晰的 3 包(price_structure / onchain / macro_flow);补入 hash_rate 与整体 SOPR;剥离"假风险包",改为顶层 data_quality 元信息;补 ma_200w 乖离率派生字段。

---

## 1. 改动文件清单

| 文件 | 改动概要 |
|---|---|
| `src/data/collectors/glassnode.py` | 新增 `_PATH_HASH_RATE = /v1/metrics/mining/hash_rate_mean` 常量、`fetch_hash_rate()` 方法、`collect_and_save_all` task list 注册。源标记 `glassnode_layer_a` |
| `src/ai/spot_cycle_context_builder.py` | 核心改动:① 重构 `build_layer_a_cycle_adjudicator_context` 为 3 包 + 顶层 `data_quality` ② 计算 `ma_200w_deviation_pct = (current_close/ma_200w - 1) * 100` ③ 把 `hash_rate` 接入 `available.onchain_valuation` 与 `cycle_evidence_summary.valuation` ④ 把 `sopr`(`sopr_adjusted` 的整体 SOPR 别名)接入 `holder_behavior` ⑤ 把 `realized_price/sth_realized_price/lth_realized_price` 从 technical 移到 onchain_packet ⑥ 删除 risk_packet 整段逻辑 ⑦ 删除 `_packet` 输出里的 `data_quality` 子段(改为顶层) ⑧ 更新 `_packet_summary` 适配新 packet_id ⑨ schema_version → `layer_a_single_cycle_adjudicator_v2_three_packets` ⑩ `_A1_CORE_FACTORS` / `_FACTOR_SOURCE` 加 `hash_rate` / `sopr` / `ma_200w_deviation_pct` |
| `src/ai/orchestrator.py` | model_note 文字"四个"→"三个(price_structure / onchain / macro_flow)" |
| `src/ai/spot_strategy_normalizer.py` | compat_a4.human_summary 文字"deterministic risk_packet"→"deterministic data_quality 元信息" |
| `web/assets/app.js` | 两处 packet specs 改名:`technical/liquidity_macro/risk` → `price_structure/onchain/macro_flow`(4 → 3);第二处同时把 `pkt.data_quality` 改读顶层 `s.data_quality` |
| `tests/test_layer_a_spot_context_builder.py` | 测试名 `..._four_packets` → `..._three_packets`,断言改 3 包 + 顶层 `data_quality.coverage_ratio` 存在 + 老 packet 名字符串不出现 |
| `tests/test_layer_a_spot_normalize.py` | fixture `data_packets` 字典换 3 包名 |
| `tests/test_web_modules_1_2_3.py` | 断言 P1/P2/P3/AI(去掉 P4)+ 新中文 packet 标题 |

## 2. 不动的东西(按用户指令)

- `prompts/layer_a_cycle_adjudicator.txt` 不改(prompt 重写是下一个独立步骤;**当前 prompt 文字与代码 packet 名不一致** — 见下方 §5 风险提示)
- `normalize_a1..a5` / `build_a1_cycle_stage_context` 反拆五段输出的逻辑不动(下一个独立步骤)
- `config/state_machine.yaml` 不动
- `a5_spot_adjudicator` 承袭逻辑不动
- `thresholds.yaml.observation_category` 不动
- `run_full_a` 不动
- Layer B 任何代码不动
- 衍生品因子(funding/OI/LSR/liquidation)继续在 `_LAYER_B_CONTEXT_FACTORS` 集合里,**未进入** Layer A 任一数据包

## 3. 重构后的 3 个数据包字段清单

dry run 在本地 stale DB 上跑出来的结构(`schema_version = layer_a_single_cycle_adjudicator_v2_three_packets`):

### price_structure_packet — 价格结构数据包(8 字段)

| 字段 | 来源 |
|---|---|
| `btc_price` | binance 日 K(via alphanode CoinGlass) |
| `ath_drawdown_pct` | 由日 K 衍生 |
| `ma_200d` | 由日 K 计算 |
| `ma_200w` | 由周 K(rolling 200)计算 |
| `ma_200w_deviation_pct` | **新增**:`(current_close/ma_200w - 1) * 100`,单位 `%` |
| `weekly_structure` | 周线结构(13/52w 涨跌幅 + bars_available) |
| `monthly_ohlc_structure` | 月线 OHLC 结构标签 |
| `major_support_resistance_zones` | 关键支撑/阻力区(原 risk_packet 的 `near_long_term_resistance` 副本已删除,本字段是唯一权威) |

### onchain_packet — 链上估值与持有者数据包(24 字段)

| 字段 | 来源 |
|---|---|
| `mvrv_z_score` / `mvrv` / `nupl` / `rhodl_ratio` / `reserve_risk` / `puell_multiple` | Glassnode |
| `hash_rate` | **新增**:Glassnode `/v1/metrics/mining/hash_rate_mean` |
| `percent_supply_in_profit` | Glassnode |
| `realized_price` / `sth_realized_price` / `lth_realized_price` | **移入**:本次从 technical 迁来(链上成本数据,本属链上估值) |
| `sopr` | **新增**:`sopr_adjusted` 别名(整体 SOPR;sopr_adjusted 是行业标准的"整体 SOPR") |
| `lth_sopr` / `sth_sopr` | Glassnode |
| `lth_supply` / `sth_supply` / `lth_supply_90d_pct_change` / `sth_supply_90d_pct_change` / `lth_net_position_change` | Glassnode |
| `percent_supply_in_loss` | Glassnode 衍生(`1 - profit`) |
| `hodl_waves_1y_plus_aggregate` / `cdd` | Glassnode |
| `exchange_balance` / `exchange_net_position_change` | Glassnode |

### macro_flow_packet — 资金流与宏观背景数据包(13 字段)

| 字段 | 来源 |
|---|---|
| `etf_flow_7d_sum_usd` / `etf_flow_30d_sum_usd` | coinglass_derivatives |
| `exchange_net_flow_30d_sum` | Glassnode 衍生 |
| `real_yield` / `fed_funds_rate` / `us2y` / `dxy` / `vix` / `nasdaq` / `m2` / `fed_balance_sheet` / `cpi` / `core_cpi` | FRED |

### 顶层 `data_quality`(原 risk_packet 解构后挂这里)

```json
{
  "confidence_cap": "low",
  "confidence_cap_reason": "Layer A 已接入因子可用率低于 50%",
  "critical_unavailable_count": 0,
  "stale_factor_count": 0,
  "missing_integrated_factor_count": 45,
  "coverage_ratio": 0.3571,
  "unavailable_factors": [],
  "coverage_notes": ["..."],
  "data_quality_notes": ["..."]
}
```

## 4. dry run 真实值取得情况

| 字段 | 本地 dry run 取到值? | 原因 |
|---|---|---|
| `ma_200w_deviation_pct` 计算式 | **结构正确,值 None** | 本机 `data/btc_strategy.db` 是 2026-05-15 的 stale snapshot,K 线和 onchain 表里无新数据 — 与重构无关 |
| `hash_rate` | **结构正确,值 None** | 同上;另外本机 `.env` 没设 `GLASSNODE_API_KEY`,即使有数据也跑不出 |
| `sopr`(整体)| **结构正确,值 None** | 同上;不过 `sopr_adjusted` 在 collector 注册表里已存在(line 753),只需 production 上正常跑就有值 |

**Glassnode `hash_rate_mean` 端点真实性独立验证**:在本机直接调 `fetch_hash_rate()`,alphanode 中转返回 `HTTP 422 missing x-key header`(而不是 404)→ 端点存在、alphanode 中转支持,只是本机没 key。**生产端跑 collect_and_save_all 后,hash_rate 会正常进 DB**。

## 5. 风险提示(用户需要注意)

1. **prompt 与代码不一致(已知,本 sprint 不修)**:`prompts/layer_a_cycle_adjudicator.txt` 仍然提到 `technical_packet` / `liquidity_macro_packet` / `risk_packet` 三个旧名字。生产端跑 Layer A 时,AI 看到的 JSON 是新的 3 包名,但 system prompt 让它"看 technical_packet"——AI 应该能凭结构推断,但理论上有解析风险。**强烈建议尽快做 prompt 重写步骤**。
2. **hash_rate 生产端首次跑需要等 Glassnode collector 跑过一次**:`hash_rate` 字段加入 `collect_and_save_all` 的 task list,服务器下一次 `glassnode_collect` job 执行后才会有数据。在此之前,onchain_packet 里 `hash_rate` 会是 missing 状态。
3. **`sopr` 别名与 `sopr_adjusted` 共存**:`available.holder_behavior` 里同时有 `sopr_adjusted`(原 key)和 `sopr`(新别名),指向同一个 DB metric。下一次重构如果决定弃用 `sopr_adjusted` 名,可删。
4. **本地 DB stale 无关本次重构**:本地 `data/btc_strategy.db` 最后更新 2026-05-15(用户已知),所有 dry run 字段值为 None 是这个原因。结构正确性已通过测试断言验证。
5. **`_packet` 的 `data_quality` 子段移除**:web/assets/app.js 已同步改读顶层 `s.data_quality`,但任何外部消费者(如有)读 `packet.data_quality` 会得到 None。本仓库内 grep 过,没有其他消费方。

## 6. 测试结果

```
.venv/bin/python -m pytest tests/test_layer_a_*.py tests/test_web_modules_1_2_3.py
======================= 91 passed, 12 warnings in 0.86s ========================

.venv/bin/python -m pytest --tb=line -q
1 failed, 1875 passed, 1 skipped, 672 warnings in 46.56s
```

唯一失败 `test_collect_klines_1h_kline_succeeds_derivatives_fail`:**与本次 Layer A 重构完全无关**,是上个 sprint commit `16cad4f` 把 `_classify_failure` 输出 `api_error` 改成 `provider_error` 后未同步更新的断言。同样的失败在 commit `2d2372f`(上次 Layer A 死代码清理 sprint)报告里已记录过。

## 7. 本 sprint 删除清单

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| `technical_packet` 构建块 | `spot_cycle_context_builder.py:622-639`(旧版) | 改名为 `price_structure_packet`,语义和字段同步重构 |
| `liquidity_macro_packet` 构建块 | `spot_cycle_context_builder.py:661-672`(旧版) | 改名为 `macro_flow_packet` |
| `risk_packet` 整段构建块 | `spot_cycle_context_builder.py:673-694`(旧版) | **彻底删除**:7 数据质量字段升级为顶层 `data_quality`;3 个"借用"字段(`etf_flow_7d / real_yield / fed_funds_rate`)在 `macro_flow_packet` 已存在,无需保留副本;`near_long_term_resistance` 是 `major_support_resistance_zones` 副本,已删 |
| `_packet()` 内的 `data_quality` 子段 | `spot_cycle_context_builder.py:589-598`(旧版) | 与顶层 `data_quality` 重复 |
| `_packet_summary("risk_packet", ...)` 分支 | `spot_cycle_context_builder.py:562-566`(旧版) | risk_packet 已删,无 callsite |
| `data_quality.notes` 一次性传入逻辑 | `_packet` notes 参数现按 packet 自定义 | 同上 |
| web/assets/app.js 第 4 个 packet spec (`['P4', '风险评估包', 'risk_packet']`) | `app.js:607`(旧版) | risk_packet 已删 |
| `dq = pkt.data_quality || {}` 包内读取 | `app.js:1386`(旧版) | 改为读顶层 `s.data_quality` |
| 测试断言 `"P4"` / `"风险评估包"` / `"风险"` | `test_web_modules_1_2_3.py:407, 413` | 同上 |

**自检 git grep**:
- `git grep -E "technical_packet|liquidity_macro_packet|risk_packet"` 在 src/ 中 = 0(只 prompts/layer_a_cycle_adjudicator.txt 还在,用户指令保留)
- `git grep "P4"` 在 web/ 和 tests/ = 0
- 没有"备用"/兼容"代码保留

## 8. 部署四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅(1875 通过 + 1 上游遗留失败 + 1 skipped;全部 91 个 Layer A + web 测试通过) |
| 本地 dry run 结构验证 | ✅(3 包结构正确、顶层 data_quality、所有新字段存在;实际值因本地 DB stale + 无 Glassnode key 全部为 None,与重构无关) |
| GitHub push | ❌ 待用户确认推送(commit 尚未创建,等用户先看本报告) |
| 服务器 git pull | ❌ 待用户执行 |
| 服务器 systemctl restart | ❌ 待用户执行(restart 后下一次 10:00 BJT Layer A job 会按新 3 包结构产出;若希望立即生效,可手动触发一次 collect → layer_a_spot_runner) |
| 生产 DB schema 迁移 | N/A(本次无 schema 变更;`hash_rate` 走 `onchain_metrics` 表已有列,无需迁移) |
