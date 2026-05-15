# Layer A A1 仍缺关键数据只读审计报告

## 1. 任务目标

本轮只审计 Layer A A1「大周期阶段判断」还缺哪些真正有价值的数据。

本轮没有改代码、没有改 prompt、没有改数据逻辑、没有跑完整 pipeline、没有真实交易。

审计口径很窄：不列已经接入且正常进入 A1 的数据，不列更适合 Layer B 的短线衍生品数据，不泛泛罗列所有可能因子，只列“仍缺失、且会影响 A1 大周期阶段判断质量”的数据。

## 2. A1 当前输入核实方式

读取和核实过的关键文件：

- `AGENTS.md`
- `config/data_catalog.yaml`
- `config/data_sources.yaml`
- `src/ai/spot_cycle_context_builder.py`
- `src/ai/agents/prompts/a1_spot_cycle.txt`
- `src/ai/spot_cycle_stage_state.py`
- `src/ai/spot_strategy_normalizer.py`
- `src/pipeline/layer_a_spot_runner.py`
- `src/data/collectors/glassnode.py`
- `src/data/collectors/fred.py`
- `src/data/collectors/coinglass.py`
- `src/data/storage/dao.py`
- `src/data/storage/schema.sql`
- `scripts/check_glassnode_health.py`
- `docs/codex_reports/layer_a_five_stage_state_machine_and_factor_finalization.md`
- `docs/codex_reports/audit_layer_a_a1_cycle_stage_model_and_transition_logic.md`
- `docs/codex_reports/fix_layer_a_a1_timeout_by_context_pruning.md`

只读查询方式：

- 使用 `LatestLayerASpotStrategyDAO.get_latest()` 读取最近 Layer A 状态。
- 使用 `SpotCycleContextBuilder(...).build_spot_cycle_context()` 构建当前 Layer A context。
- 使用 `build_a1_cycle_stage_context()` 核实 A1 实际轻量输入。
- 只读查询 SQLite 中 `onchain_metrics` / `macro_metrics` 的候选指标存在情况。

最近本地 Layer A 摘要：

- run_id：`b8dbdea5945245a2827f90dabfc2dded`
- generated_at_bjt：`2026-05-15 13:43:34 BJT`
- status：`success`
- A1 official_stage：`accumulation`
- A1 raw_stage：`accumulation`
- A5 action：`hold`

## 3. A1 当前真实输入简述

A1 现在不是吃完整网页数据，也不是吃完整 Layer B 数据。它吃的是轻量 context：

- `stage_model`
- `cycle_evidence_summary`
- `recent_stage_history`
- `instructions`

A1 轻量 context 里的核心组：

- `price_position`
- `valuation`
- `holder_behavior`
- `flows`
- `macro`
- `data_quality`

当前 A1 已经覆盖的关键类型包括：

- 价格：BTC price、ATH drawdown、200D、200W、周线结构、realized price、STH/LTH realized price
- 估值：MVRV Z、MVRV、NUPL、RHODL、Reserve Risk、Puell、盈利供给比例
- 持有人：LTH/STH SOPR、LTH/STH supply、LTH net position change、盈利/亏损供给、HODL Waves 字段、CDD 字段
- 资金流：exchange balance、exchange net position change、exchange net flow 30d、ETF 7d/30d
- 宏观：real yield、Fed funds、US2Y、DXY、VIX、Nasdaq、M2、Fed balance sheet、CPI/Core CPI

所以本轮不重复建议补 MVRV、NUPL、RHODL、Reserve Risk、Puell、LTH/STH SOPR、M2、Fed balance sheet、Fed funds、Real Yield、US2Y、200D、200W 这些已经进入 A1 的数据。

## 4. 仍缺失且值得补的数据清单

| data_name | 中文名 | 为什么 A1 需要 | 当前项目状态 | 推荐数据源 | 可能 endpoint / series | 接入难度 | 优先级 | 是否必须接入后才能信任 A1 | 备注 |
|---|---|---|---|---|---|---|---|---|---|
| `monthly_ohlc_structure` | 月线 OHLC / 月线收盘结构 | A1 是大周期阶段判断，月线比日线/周线更能过滤噪音。缺月线时，A1 容易把周线修复误读成牛市中期。 | not_configured | 现有 CoinGlass K 线本地重采样 | 由 1D/1W candles resample 为 1M；或 CoinGlass price history monthly 如中转支持 | low-medium | P0 | no | 当前 `_UNAVAILABLE_MODEL_FACTORS` 有 `monthly_structure_1m: not_found`，说明模型预留但未实现。 |
| `major_support_resistance_zones` | 长期关键支撑 / 阻力区 | 判断“吸筹、过渡、牛初、中期”需要知道价格是否突破长期关键位，尤其前高、前低、长期箱体上沿。 | not_configured | 本地规则化计算 | 基于 1W/1M swing high/low、cycle high/low、成交密集区近似 | medium | P0 | no | 当前标记为 `ai_derived_not_precomputed_for_layer_a`，说明没有规则化预计算，不能直接交给 A1 稳定使用。 |
| `hodl_waves_1y_plus_aggregate` | HODL Waves 长期持有结构聚合 | 判断底部吸筹、牛市中期、后期派发时，长期币龄筹码占比非常关键。缺它会削弱 A1 对“长期资金是否仍在锁仓”的判断。 | collected_but_not_in_a1 | Glassnode | `/v1/metrics/supply/hodl_waves`，聚合 `1y_2y + 2y_3y + 3y_5y + 5y_7y + 7y_10y + more_10y` | medium | P0 | no | collector 会展开成 `hodl_waves_<bucket>`，但 A1 当前读取的是 `hodl_waves` 聚合键；因此字段在 A1 里出现但实际缺值。 |
| `stablecoin_liquidity_proxy` | 稳定币流动性代理 | 稳定币供给和交易所稳定币余额能帮助判断风险资金是否有“可入场弹药”。缺它会让 A1 对牛熊过渡/牛初确认偏弱。 | source_unavailable | Glassnode / DeFiLlama / CoinMetrics，需先验证 | 可能是 stablecoin total supply、USDT/USDC supply trend、stablecoin exchange balance | medium-high | P1 | no | 当前 `_UNAVAILABLE_MODEL_FACTORS` 有 `stablecoin_supply_liquidity: not_found`。不应伪装成已可用。 |
| `net_liquidity_tga_rrp` | 美元净流动性：Fed balance sheet - TGA - RRP | 目前有 M2、Fed balance sheet、Fed funds、Real Yield，但没有 TGA/RRP 组成的净流动性。它对 BTC 大周期流动性环境很有价值。 | not_configured | FRED | TGA 可查 Treasury General Account 相关 FRED series；RRP 常见为 `RRPONTSYD`；公式本地计算 | medium | P1 | no | 不是替代现有 M2/Fed balance sheet，而是补足“净流动性”口径。 |
| `cdd_long_term_zscore` | CDD 长周期均值 / Z-score | 原始 CDD 很尖锐，A1 更需要长期均值或 Z-score 来识别老币大规模移动是否异常。 | collected_but_not_in_a1 | Glassnode + 本地派生 | `/v1/metrics/indicators/cdd` + 180d/365d 均值、Z-score | medium | P1 | no | `cdd` 字段已进 A1，但本地最新 snapshot 缺值；即便有原始 CDD，也建议补长期平滑口径，而不是让 A1看单点。 |
| `liveliness_or_dormancy` | Liveliness / Dormancy 老币活跃度 | 判断长期持有人是否从囤币转向分发。对区分牛市中期、后期、顶部过热有价值。 | configured_but_not_collected | Glassnode | `/v1/metrics/indicators/liveliness`；Dormancy 若中转支持可再验证 | medium | P1 | no | `liveliness` 在 catalog 是 delayed/config only，context 标记 `config_only`，还不是稳定输入。 |
| `cycle_anchor_dates` | 周期锚点：前高/前低/减半后天数 | A1 七阶段需要“离上一轮低点/ATH/减半多久”这种慢变量，避免只看当下指标。 | not_configured | 本地规则化计算 | 从价格历史推导 cycle high/low；减半日期可静态配置 | low-medium | P1 | no | 对防止阶段过早进入牛市中期有帮助，且不依赖付费 API。 |
| `realized_cap_hodl_waves` | Realized Cap HODL Waves | 比普通 HODL Waves 更强调不同币龄筹码的价值权重，有助于顶部/底部温度判断。 | source_unavailable | Glassnode，需验证套餐/中转 | `/v1/metrics/indicators/realized_cap_hodl_waves` 或同类 endpoint，需真实验证 | high | P2 | no | 价值高，但接口、套餐和中转支持不确定，不能作为近期 P0。 |
| `sopr_long_term_ma` | SOPR 长周期均线 / 平滑趋势 | LTH/STH SOPR 已有，但 A1 更适合看长期平滑趋势而不是单点，防止一天噪音影响阶段。 | collected_but_not_in_a1 | Glassnode + 本地派生 | `lth_sopr` / `sth_sopr` 90d/180d MA 或 Z-score | low-medium | P2 | no | 当前已有 LTH/STH SOPR 单点，建议作为质量提升，不是硬缺口。 |

## 5. P0 / P1 / P2 优先级

### P0：最优先补，最多 3 个

1. `monthly_ohlc_structure`：月线结构。
2. `major_support_resistance_zones`：长期关键支撑 / 阻力区。
3. `hodl_waves_1y_plus_aggregate`：HODL Waves 长期持有聚合。

这三个最直接影响 A1 对“吸筹 / 牛熊过渡 / 牛市初段 / 牛市中期”的判断。

### P1：应该补，最多 5 个

1. `stablecoin_liquidity_proxy`
2. `net_liquidity_tga_rrp`
3. `cdd_long_term_zscore`
4. `liveliness_or_dormancy`
5. `cycle_anchor_dates`

这些主要提升宏观流动性、老币移动、周期时钟判断质量。

### P2：可选观察，最多 5 个

1. `realized_cap_hodl_waves`
2. `sopr_long_term_ma`

其余候选暂不建议进入 A1 主判断。

## 6. 不建议补入 A1 的数据

以下数据不建议补入 A1 主判断，原因是它们更适合 Layer B 波段、A4 风险或网页背景，不适合作为 BTC 大周期阶段驱动：

| 数据 | 原因 |
|---|---|
| funding rate | 短线杠杆拥挤，更适合 Layer B / A4 |
| open interest | 短线杠杆和波段风险，不适合 A1 定阶段 |
| liquidation / liquidation heatmap | 执行和风险层更有用，不适合大周期阶段 |
| long/short ratio | 情绪噪音大，偏短周期 |
| 24h derivatives changes | 对 A1 太短，不应用于阶段切换 |
| short-term momentum | 更适合 Layer B L2/L3 |
| 20D change | 可作背景，但不应驱动 A1 正式阶段 |
| options IV / skew | 当前项目 not_found，且更偏风险定价，不是 A1 必需 |
| futures basis / premium | 已标记 deprecated_candidate，更适合衍生品风险背景 |

## 7. 哪些缺口会影响 A1 大周期判断

最会影响 A1 的缺口是：

1. 月线结构：缺它时，A1 可能过度依赖日线/周线修复。
2. 长期支撑阻力：缺它时，A1 不容易判断是否真正突破长期箱体。
3. HODL Waves 长期聚合：缺它时，A1 对长期持有人锁仓/派发的判断不够稳定。
4. 稳定币/净流动性：缺它时，A1 对“牛熊过渡是否有流动性支持”判断偏弱。
5. CDD 平滑口径 / Liveliness：缺它时，A1 对老币移动和分发风险不够敏感。

## 8. 哪些缺口可能导致阶段过早进入牛市中期

最可能让 A1 过早进入 `mid_bull / 牛市中期` 的缺口：

1. 缺月线结构：周线转强可能被误判为大周期已经进入牛市中期。
2. 缺长期关键阻力：价格接近/刚突破重要阻力时，如果没有阻力区信息，AI 可能过早确认趋势。
3. 缺 HODL Waves 1y+：无法判断长期持有人是否仍在吸筹，还是已经进入更成熟的趋势持有。
4. 缺稳定币/净流动性：如果流动性没有同步扩张，仅靠链上估值和价格修复可能会偏乐观。
5. 缺 CDD / Liveliness 平滑指标：无法稳定识别老币是否开始移动或分发。

## 9. 当前 A1 不补这些数据是否还能用

结论：可以用于参考和辅助，但不建议单独用于真实交易决策。

原因：

- 当前 A1 已有很多关键数据，不是“瞎猜”。
- 但缺少月线结构、长期阻力、长期币龄聚合和净流动性，会影响阶段稳定性。
- 现在已经有状态机和连续确认机制，可以降低一天内乱跳风险。
- 但要让 A1 更像真正的大周期辅助交易模块，P0 数据仍建议优先补。

## 10. 下一步建议先补哪些

建议下一轮按低风险顺序补：

1. 先补 `monthly_ohlc_structure`：直接从现有 K 线重采样，不依赖新 API。
2. 再补 `major_support_resistance_zones`：用 1W/1M swing high/low 规则化计算，不让 AI 临场猜。
3. 再修 `hodl_waves_1y_plus_aggregate`：复用已有 Glassnode HODL Waves bucket 输出，聚合 1y+ 长期持有结构。

这三项都比新接一个复杂外部源更稳，也最能帮助 A1 判断是否过早进入牛市中期。

## 11. 是否改代码

否。

本轮只新增这份审计报告和只读查询摘要。

## 12. 是否影响 Layer B

否。

本轮没有改 Layer B L1-L5、Master、Validator、thesis、虚拟账户、开平仓逻辑。

## 13. 是否影响真实交易

否。

本轮没有真实交易、没有下单、没有改任何交易接口。

## 14. 实际运行命令

```bash
uv run python - <<'PY'
# 只读构建 Layer A context 与 A1 light context 摘要
PY
```

```bash
uv run python - <<'PY'
# 只读查询候选 onchain_metrics / macro_metrics 是否存在
PY
```

```bash
git diff --check
```

## 15. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | N/A，本轮只读报告 |
| GitHub push | 待提交后记录 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | N/A，本轮只读审计 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | N/A |

## 16. 用户后续命令

本轮只读审计，不需要部署和重启。

如果用户要同步报告到服务器代码库，才需要：

```bash
ssh ubuntu@124.222.89.86
cd /home/ubuntu/btc_swing_system
git pull --ff-only
```
