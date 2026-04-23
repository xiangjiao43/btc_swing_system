# 批 6 详细报告 — 跨文件不一致修复 + 3 个历史场景测试快照

**日期**:2026-04-23
**Sprint**:1 前置工作 · 优化三(测试快照) + 前置清理
**对应建模文档章节**:§10.7(M26 可交易性验收)、§3.8(组合因子)、§4.2-§4.6(五层证据)

---

## ⚠️ Triggers for Human Attention

> 以下是本批次需要人类注意的决策点,可直接摘录给审阅者。

### 1. 跨文件修复:2 个枚举漂移已 resolved,1 个是"未冲突的记账事项"

**已修改的文件**:
| 文件 | 修改 |
|---|---|
| `config/layers.yaml` | `layer_3_opportunity.output_enums.execution_permission` 从 6 值扩到 7 值(补 `no_chase`);`permission_participates_in_merging` 同步加 `no_chase: true` |
| `config/thresholds.yaml` | `layer_4_risk.execution_permission_merging.severity_rank` 从 5 值扩到 6 值(插入 `no_chase` 在 `ambush_only` 和 `cautious_open` 之间) |
| `config/schemas.yaml` | `consistency_notes` 两处 `resolution` 改为 `resolved_in_batch_6`,`observed_count` 更新 |

**未改(原本就无冲突)**:
- `outcome_type` 命名风格差异(建模用"A perfect"短语 / schemas 用 `A_perfect` snake):仅 schemas.yaml 使用此枚举,其他 config 无引用,不算冲突
- `freshness_class` 批 3 已自主增加 `event` 值,layers.yaml 已一致

### 2. K 线数据是**种子化构造**,非真实历史

3 个场景的 `raw_data.json.klines_1d.series`(每个 180 行)都是用 numpy seed 生成的 GBM-like 合成序列,**价格终点**校准到目标日期的真实历史价(±$0):
- scenario_main_bull: end @ $11,400(2020-10-15 真实历史约 $11,400,吻合)
- scenario_main_bear: end @ $38,000(2022-05-01 真实历史约 $38,000,吻合)
- scenario_ranging:    end @ $30,500(2023-07-01 真实历史约 $30,500,吻合)

**含义**:
- 指标计算(ADX / ATR / MA / SWING / 多 TF 一致性)会有真实历史的**形态近似**,但具体数值(例如 ADX 读数 27 vs 真实历史的 23.5)不严格匹配
- 因此 `expected_evidence_outputs.json` 使用**范围而非点值**,例如 `truth_trend_score_range: [5, 7]`

**潜在风险**:如果 Sprint 1 的单元测试用**点值断言**(assert == 某具体数),会因 seed 漂移失败。**应该用范围断言**:`assert value in range`。

**升级路径**:Sprint 1 完成后,用 `scripts/backfill_data.py` 从 Binance 拉真实历史 180 天 K 线,**替换种子构造的部分**保留 derivatives / onchain / macro 的手工值(那些都是公开快照,可替换但本文件中的值与真实历史精确度未逐一核对)。

### 3. 链上 / 衍生品 / 宏观快照是"**语义校准**",不是"**真实抓取**"

3 个 scenarios 的 `derivatives_snapshot` / `onchain_snapshot` / `macro_snapshot` 是我**按建模规则反推**构造的(让 MVRV Z 落在正确档位、让 funding rate 触发正确的 crowding 分数等)。我**没有**调用任何真实 API 校对,建模文档里"2022-05-01 funding rate 是多少"也没有写。

**含义**:
- 数据是"能触发预期证据层输出的合理值",不是"历史上那一天真实发生的值"
- `source_note` 字段在每个 snapshot 里明确标注了"constructed / estimated"

**升级路径**:Sprint 1 时如果能拉到真实历史(Glassnode、Coinglass 都有历史 API),可以把这些 snapshot 值替换成真实值,并校对 expected_evidence_outputs 是否还成立。

### 4. `observation_category` 在 scenario_ranging 和 scenario_main_bull 的分类有**歧义**

两个场景在 observation_category 边界上都可能落在不同值。我在 expected_evidence_outputs.json 做了标注:

- **scenario_main_bull**(2020-10-15):按 §4.7.3 的严格规则,**opportunity_grade = B 不落在 watchful 条件的 `grade ∈ {C, none}` 集合内**,也不落在 disciplined 条件。这是 **§4.7.3 规则表不完备的一个边界情况**。我的处理是在 expected 里标注 `watchful`(实用选择)+ flag "Sprint 1 verify rule completeness"。
- **scenario_ranging**(2023-07-01):如果 stance 输出 `neutral`,会触发 disciplined 的 `l2_stance_equals: neutral` 条件;如果弱 `bullish`,触发 watchful。两种都合法。

**建议**:Sprint 1 时补齐 observation_classifier 规则的**完备性检查**(给每种 `{regime, stance, grade, risk}` 组合必须有归属),如果有 gap 就定义兜底("undefined" 或 "watchful")。

### 5. 建模文档里发现的"规则不完备"问题

**(a) §4.7.3 observation_classifier 规则覆盖不全**
如 Trigger 4 所述,`grade = B/A` 的情况既不在 watchful(要求 `grade ∈ {C, none}`)也不在 disciplined(各条件与 grade 无关,但 regime 为 trend_up 时不触发)的交集里。这是建模文档的一个规则缺口。

**(b) cycle_position_decision.bands 的辅助条件 `aux_min_days_since_last_accumulation` 的语义**
scenario_ranging 时 early_bull 档位的辅助条件需要"距上次 accumulation ≥ 60 天"。但系统刚启动(或冷启动期)时,**没有"上次 accumulation"的历史**,这条件如何判断?建模未说明。Sprint 1 实现时建议:冷启动期间该辅助条件默认 pass(不作否决)。

**(c) scenario_main_bear 的 crowding 分数和 L3 grade A 判定有循环依赖**
short A 级要求 `crowding_score ≥ 6`。但 crowding 计算时空头拥挤(funding 负 + 基差低 + PCR 高)的赋分规则没有明确在 §3.8.3 列出(§3.8.3 只说"多头拥挤,空头对称")。**对称是否完全镜像**(funding > -0.03% 连续 3 次 → +2)?这一点需要 Sprint 1 实现时明确。

### 6. 可能与建模意图不完全一致的点

**(a) `raw_data.json` 的 K 线字段命名**
建模 §10.4 的 SQL `price_candles` 表用 `open_time_utc` / `open` / `high` / `low` / `close` / `volume`。我的 JSON 里用了 `volume_btc`(明确单位)而不是 `volume`。Sprint 1 时如果代码期望 `volume`,需要 rename 或加 alias。

**(b) onchain_snapshot 字段命名 vs data_catalog 的 single_factors**
data_catalog 里单因子叫 `lth_supply_90d_change`(无单位后缀),我在 fixture 里叫 `lth_supply_90d_change_pct`(带 `_pct`)。类似还有 `ath_drawdown_from_ath_pct` vs `ath_drawdown`。**命名差异不影响决策,但 Sprint 1 测试代码需要在这两者间 map**。

**(c) 组合因子的 output 字段建模没展开**
`composite_factors_schemas.*.output` 的具体字段我在 schemas.yaml 里自主定义(如 `band, position_cap_multiplier, correlation_amplified` 等)。fixture 里预期输出引用了这些字段;如果 Sprint 1 实现的组合因子 output 字段名不同,测试会失败。**建议先按 schemas.yaml 定义实现**,保持一致。

---

## 1. 产出概览

### Part A:修改

| 文件 | 修改量 |
|---|---|
| `config/layers.yaml` | +3 行(+`no_chase` 等) |
| `config/thresholds.yaml` | +2 行(插入 `no_chase` + 注释) |
| `config/schemas.yaml` | ~4 行(consistency_notes 标 resolved) |

### Part B:新增

| 目录 / 文件 | 行数 / 大小 |
|---|---|
| `tests/fixtures/scenario_main_bull_2020_10_15/raw_data.json` | 40 KB |
| `tests/fixtures/scenario_main_bull_2020_10_15/expected_evidence_outputs.json` | 8 KB |
| `tests/fixtures/scenario_main_bull_2020_10_15/scenario_notes.md` | 4 KB |
| `tests/fixtures/scenario_main_bear_2022_05_01/raw_data.json` | 40 KB |
| `tests/fixtures/scenario_main_bear_2022_05_01/expected_evidence_outputs.json` | 8 KB |
| `tests/fixtures/scenario_main_bear_2022_05_01/scenario_notes.md` | 4 KB |
| `tests/fixtures/scenario_ranging_2023_07_01/raw_data.json` | 40 KB |
| `tests/fixtures/scenario_ranging_2023_07_01/expected_evidence_outputs.json` | 8 KB |
| `tests/fixtures/scenario_ranging_2023_07_01/scenario_notes.md` | 8 KB |
| **小计** | **160 KB,9 文件** |

还删除了 `tests/fixtures/.gitkeep`(因为该目录现在有实际内容)。

---

## 2. 场景一览

| Scenario | 日期 | 收盘价 | 预期 regime | 预期 grade | M26 要求 |
|---|---|---|---|---|---|
| main_bull | 2020-10-15 | $11,400 | transition_up | B(可能 A) | 至少一次 A/B long_planned 触发 |
| main_bear | 2022-05-01 | $38,000 | trend_down | A(可能 B) | 至少一次 short 或 long_exit 触发 |
| ranging | 2023-07-01 | $30,500 | range_mid | none | 总状态迁移 ≤ 8(不被震荡打脸) |

### 每个场景文件结构

```
tests/fixtures/scenario_xxx_YYYY_MM_DD/
├── raw_data.json                      # 180 天 K 线 + 衍生品/链上/宏观快照 + 事件
├── expected_evidence_outputs.json     # 五层 + 6 组合因子的预期输出(用范围)
└── scenario_notes.md                  # 历史背景 / 为何选此日期 / 预期 M26 结果
```

### raw_data.json 包含字段

- `scenario_label`, `scenario_reference_date_bjt`, `scenario_reference_timestamp_utc`, `source_note`
- `klines_1d.series`:180 行 OHLCV(每行 open/high/low/close/volume_btc + open_time_utc)
- `derivatives_snapshot`:15 字段(funding / OI / long_short / basis / PCR / liquidation / liq_cluster)
- `onchain_snapshot`:15 字段(MVRV Z / NUPL / LTH / exchange flow / drawdown + 7 display)
- `macro_snapshot`:11 字段(DXY / US10Y / VIX / nasdaq / gold + 相关性)
- `events_near_reference_date`:前后 ≤ 7 天的事件(FOMC/NFP/CPI/options)
- `computed_from_klines_hint`:ATH / drawdown 计算提示

### expected_evidence_outputs.json 包含字段

- `expected_layer_1_regime` ~ `expected_layer_5_macro`(五层)
- `expected_composite_factors_output`(6 组合因子)
- `expected_observation_category`
- `expected_m26_acceptance_result`
- `validation_notes`

每个预期值有 `reasoning` 字段,引用建模章节或 thresholds 规则,解释**为什么此场景应输出此值**。

---

## 3. 自主决策汇总

| 编号 | 决策 | 理由 |
|---|---|---|
| A | K 线用 seeded numpy GBM 构造,终点 pin 到真实历史价 | 避免调用外部 API,保证测试可复现,价格形态"像"真实历史 |
| B | derivatives/onchain/macro 快照用手工构造 | 按建模规则反推能触发预期证据层输出的数值 |
| C | expected 值用**范围**而非点值 | seed 漂移会让点值断言易碎,范围更稳健 |
| D | 每个 expected 字段加 `reasoning` 说明 | 便于 Sprint 1 调试时定位"差一档是 L2 的错还是 L3 的错" |
| E | scenario_notes.md 写完整的 M26 验收分析 | 让 reviewer 可以跳过 JSON 只读 md 就理解场景意图 |
| F | K 线字段用 `volume_btc` 而非 `volume` | 明确单位,避免"volume 到底是 USDT 还是 BTC"的歧义 |
| G | 事件列表用 `events_near_reference_date`(前后 7 天) | EventRisk 的 72h 窗口 + 扩展观察 |
| H | observation_category 标注为"可能值 + 原因"而非硬断言 | 该规则在两个场景下有边界模糊(见 Trigger 4) |
| I | 场景目录命名 `scenario_<type>_<date>` | 便于 glob 匹配 + 字典序排序 |
| J | 在 `raw_data.json` 顶部加 `source_note` 字段 | 透明说明数据来源(合成 vs 真实),避免被误用 |
| K | 删除 `tests/fixtures/.gitkeep` | 目录已有文件,占位符冗余 |

---

## 4. M26 可交易性验收(§10.7)覆盖映射

| 建模场景 | 对应 fixture | 预期结果 |
|---|---|---|
| 场景 1:2020-10 至 2021-04 主升浪 | `scenario_main_bull_2020_10_15` | 至少一次 LONG_PLANNED → LONG_OPEN → TP1 触发 |
| 场景 2:2022-04 至 2022-06 主跌浪 | `scenario_main_bear_2022_05_01` | LONG_EXIT 或 SHORT_PLANNED |
| 场景 3:2023-05 至 2023-09 震荡区 | `scenario_ranging_2023_07_01` | 累计状态迁移 ≤ 8 次 |

**注意**:fixture 只是一个**时点快照**。真实的 M26 验收需要**时间窗内多次运行**。fixture 验证的是"**在这个时点**,系统应该给出 A/B/C 类响应"。Sprint 1 的 `scripts/replay.py` 会读多个时点并验证时间窗总体表现。

---

## 5. 验证

```
scenario_main_bull_2020_10_15:
  klines: 180 rows; close=11400.0, first_date=2020-04-19, last_date=2020-10-15
  derivatives=15, onchain=15, macro=11, events=2
  expected regime: transition_up, grade: B, M26 pass: True

scenario_main_bear_2022_05_01:
  klines: 180 rows; close=38000.0, first_date=2021-11-03, last_date=2022-05-01
  derivatives=15, onchain=15, macro=11, events=3
  expected regime: trend_down, grade: A, M26 pass: True

scenario_ranging_2023_07_01:
  klines: 180 rows; close=30500.0, first_date=2023-01-03, last_date=2023-07-01
  derivatives=15, onchain=15, macro=11, events=3
  expected regime: range_mid, grade: none, M26 pass: True

ALL FIXTURES VALID
```

Part A 验证:
```
layers.execution_permission (7): [can_open, cautious_open, no_chase, ambush_only, watch, protective, hold_only]
thresholds.severity_rank (6): [protective, watch, ambush_only, no_chase, cautious_open, can_open]
PART A FIXES VERIFIED
```

---

## 6. 下一步

**Sprint 1 前置工作(优化一、二、三)全部完成**。项目状态:

```
btc_swing_system/
├── config/                    # 9 YAML + 3 prompt(批 1-5)
├── docs/
│   ├── modeling.md            # v1.2 建模文档
│   ├── PROJECT_LOG.md         # 项目决策日志
│   └── cc_reports/            # 批 1-6 报告(各自含 Triggers 段)
├── tests/fixtures/
│   ├── scenario_main_bull_2020_10_15/   # 3 文件
│   ├── scenario_main_bear_2022_05_01/   # 3 文件
│   └── scenario_ranging_2023_07_01/     # 3 文件
└── src/                       # 空骨架,等 Sprint 1 落地
```

**建议的 Sprint 1 起步路径**:
1. 生成 Pydantic model:`scripts/generate_pydantic_from_schemas.py` 读 schemas.yaml 输出 `src/schemas/*.py`
2. 实现 `src/data/proxy_client.py` + `src/data/collectors/binance.py`(最小数据管道)
3. 实现 `src/indicators/price_structure.py` 的基础函数(ADX / ATR / MA / swings)
4. 用 `tests/fixtures/scenario_*/raw_data.json` 做第一批单元测试,对照 expected 验证
5. 按 §10.5 的 v0.1 目标,跑通"数据 → L1 regime 输出"的完整链路
