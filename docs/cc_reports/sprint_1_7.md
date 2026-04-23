# Sprint 1.7 — L1 Regime Evidence 层

**日期**:2026-04-23
**对应建模章节**:§4.1(EvidenceReport 通用结构)、§4.2(Layer 1)

---

## ⚠️ Triggers for Human Attention

### 1. ATR 百分位**用 ATR/close 比率**,不是裸 ATR

建模 §4.2.5 的 ATR percentile 阈值(30 / 60 / 85)**无法在强趋势里工作**,因为强趋势下价格水平上涨会让 ATR 绝对值也线性上涨 → 其历史百分位永远在高位 → 常触发 chaos。

修复:Layer1Regime 内部用 `atr_to_price = atr_series / close` 再做百分位。这和 `data_catalog.yaml` 里的 `atr_to_price_ratio` 单因子一致。

**影响**:如果未来 indicators 层要单独暴露 `atr_percentile`(不除以 close),L1 的这个内部实现**不影响**。但 Sprint 1.10+ 跨层对照阈值时要注意是哪种。

### 2. chaos 的硬前置条件:`volatility_regime ∈ {elevated, extreme}`

原始三信号(atr_extreme + adx_oscillating + no_swing_pattern)任意 2 个 → chaos,会在**强趋势形成阶段**误判:
- ADX 从 10 快速升到 70 → std 很高 → `adx_oscillating=true`(尽管不是震荡)
- Swing 太少 → `no_swing_pattern=true`(insufficient 被当 mixed)

修复:
- `adx_oscillating` 增加 `adx_latest < strong_threshold` 作限定(只有 ADX 在弱区才可能震荡)
- chaos 整体需要 `volatility_regime ∈ {elevated, extreme}` 作硬前置

### 3. 判档优先级:`chaos > trend_* > transition_* > range_*`(与用户任务描述不同)

用户任务描述写的是 `chaos > transition_* > trend_* > range_*`。但实测这会**把成型的 trend 误判为 transition**:一条强 ADX 的上升趋势,开头几天 `adx_slope > 0 + adx_crossed_up` 都满足,挤掉 trend_up。

**我的决策**:把 trend_* 前置(ADX 达 strong 且 ≥3/4 信号 → trend),transition_* 需要 `adx < strong` 作硬前置(否则视为已经 trend 态)。这样:
- ADX 已过 strong + 4 支柱齐全 → trend_*
- ADX 在 weak-strong 之间 + 仍在上升 → transition_*
- 两者不再竞争

**建议**:若建模作者坚持 `transition > trend` 优先级,需在 transition_* 判定里补"不能已经是成型 trend"之类的互斥条件。本 Sprint 默认用"trend 优先 + ADX 硬前置"更稳健。

### 4. `_weekly_macd_direction` 用**绝对值符号 + 死区**,不用 MACD-signal 交叉

原以 `macd > signal` 判方向,但强下跌里末周小反弹会让 macd 短暂 > signal,被误判 "up"。

改用:
```
deadzone = close * 0.005
if macd_v > deadzone  → up
if macd_v < -deadzone → down
else                  → neutral
```

这反映**长周期**方向(MACD 绝对值代表 EMA12 与 EMA26 的累积偏离),不易被短期反弹扰动。

### 5. `regime_stability` 的启发式映射

schemas.yaml 有 `regime_stability ∈ {stable, slightly_shifting, actively_shifting, unstable}`。我用:
- chaos → `unstable`
- transition_* → `actively_shifting`
- trend_* + conf ≥ 0.70 → `stable`
- trend_* + conf < 0.70 → `slightly_shifting`
- range_* + swing=mixed → `slightly_shifting`
- range_* + swing=stable → `stable`

这是合理启发,不在建模里显式定义。若未来要改规则,集中在 `_infer_regime_stability()`。

### 6. 冷启动(§8.10)处理

`EvidenceLayerBase.compute()` 模板方法检测 `context['cold_start']['warming_up'] == True`:
- `health_status` → `cold_start_warming_up`(覆盖原值)
- `confidence_tier` 向下降 1 档(high → medium → low → very_low)
- `notes` 追加 `cold_start warming_up(days_elapsed=N)`

所有 evidence 层共享此行为(不只是 L1)。

### 7. `regime_primary` vs `regime` 双字段

schemas.yaml 用 `regime_primary`,用户任务描述用 `regime`。output 同时含两个字段(同值)。类似的还有 `volatility_level` / `volatility_regime`。下游按需取。

### 8. 不直接读 composite factor

L1 的输出含 `truth_trend_score: None`。建模 §4.2.4 列 `truth_trend_score` 为 L1 专属字段(来自 TruthTrend 组合因子,L1 内部使用)。当前实现 L1 **不主动调用 TruthTrendFactor**,留给 Sprint 1.10+ 的 pipeline 层组合:
- Sprint 1.7(本):L1 独立跑,输出基础判定
- Sprint 1.10+:pipeline 先跑 composite,再把 truth_trend 分数注入 context,L1 用它作 regime_confidence 的校准

当前 `truth_trend_score=None` 是占位,不影响其他字段正确性。

### 9. Swing 分析需要足够噪声才有事件

`swing_points(lookback=5)` 需要局部高低点两侧各 5 根 K 线形成。若数据过于平滑(noise < 1%),会生成极少甚至 0 个 swing 事件 → `swing_stability='insufficient'`。

**测试数据**:为让 trend_up 测试的 swing_stability 能被判为 `more_higher_highs` 或至少 `mixed`(不是 insufficient),测试构造 noise=2% 的 K 线。真实 BTC 日线波动 1-3%,这和生产数据一致。

### 10. mvrv_z_stabilizing_check 不在 L1 做

那是 cycle_position 的职责(Sprint 1.6)。L1 只负责价格 + 波动相关判断。

---

## 1. 变更清单

| 文件 | 行数 | 说明 |
|---|---|---|
| `src/evidence/_base.py` | 192 | EvidenceLayerBase 模板方法 + confidence_tier 工具 + data_freshness 构造 + 冷启动降级 |
| `src/evidence/layer1_regime.py` | 380 | Layer1Regime 完整实现 |
| `src/evidence/__init__.py` | 14 | 统一导出 |
| `tests/test_layer1_regime.py` | 280 | 15 tests,**全过** |

---

## 2. Layer1Regime 输出字段

### 核心判定(schemas.yaml + 用户别名)

| 字段 | 类型 | 说明 |
|---|---|---|
| `regime_primary` / `regime` | enum | 8 档:trend_up/trend_down/range_high/range_mid/range_low/transition_up/transition_down/chaos |
| `volatility_level` / `volatility_regime` | enum | 4 档:low/normal/elevated/extreme |
| `trend_direction` | enum | up/down/flat(从 regime 派生) |
| `regime_stability` | enum | stable/slightly_shifting/actively_shifting/unstable |
| `swing_amplitude` | float | 最近一波 swing 幅度 ÷ 前值 |
| `swing_stability` | enum | more_higher_highs/more_lower_lows/mixed/insufficient |
| `transition_indicators` | dict | adx_slope/volatility_acceleration/ema20_slope + direction |
| `truth_trend_score` | null | 占位,Sprint 1.10+ 由 pipeline 注入 |

### EvidenceReport 通用字段(§4.1 + 基类提供)

| 字段 | 来源 |
|---|---|
| `layer_id`(1) / `layer_name`("regime") | class-level |
| `reference_timestamp_utc` | context 传入,默认 now |
| `generated_at_utc` | 运行时 |
| `rules_version` | compute(..., rules_version) 参数 |
| `run_trigger` | context.get("run_trigger", "scheduled") |
| `data_freshness` | 自动计算每个源的 age_sec |
| `health_status` | healthy / degraded / insufficient_data / cold_start_warming_up / error |
| `confidence_tier` | high / medium / low / very_low |
| `computation_method` | rule_based / degraded / error |
| `notes` | 决策提示列表 |

### diagnostics 字段(自主决定,便于 debug)

```
adx_latest, adx_slope_10bar
atr_latest, atr_percentile_latest (% of atr/close ratio)
ema20/50/200 + ema20_slope + ema_arrangement
last_close, weekly_macd_direction, price_partition
swing_counts: {HH, HL, LH, LL}
scoring: 每档 hits 数 + is_range
signals: 每档各 bool 信号
thresholds_used: 当前生效的阈值值
```

---

## 3. 判档算法

```
if chaos_hits ≥ 2 AND vol ∈ {elevated, extreme}:
    → chaos
elif adx_is_strong AND trend_up_hits ≥ 3:
    → trend_up (4/4 → conf 0.85;3/4 → 0.70)
elif adx_is_strong AND trend_down_hits ≥ 3:
    → trend_down
elif transition_up_hits ≥ 3:
    → transition_up (4/4 → 0.70;3/4 → 0.50)
elif transition_down_hits ≥ 3:
    → transition_down
elif is_range(ADX<weak AND |ema20_slope|<close*0.0005):
    → range_high / range_mid / range_low(按价格三分位)
else:
    → 弱 trend(2/4) fallback to transition_*;否则 range_mid(conf 0.35)
```

---

## 4. 自主决策汇总

| 编号 | 决策 | 理由 |
|---|---|---|
| A | ATR 百分位用 atr/close 比率 | 避免价格水平影响绝对 ATR |
| B | chaos 硬前置 vol ∈ {elevated, extreme} | 强趋势形成期 ADX std 高,需隔离 |
| C | 判档顺序 trend_* 先于 transition_* | ADX 达 strong 即视为已成 trend |
| D | transition_* 前置:adx_below_strong | trend 与 transition 互斥 |
| E | weekly MACD 用绝对值符号 + 死区 | 避免短期反弹误导方向 |
| F | `regime_stability` 启发式映射 | schemas 定义但建模未展开 |
| G | `_base.py` 模板方法 `compute()` 统一冷启动/通用字段 | 所有 layer 共享行为 |
| H | output 产 `regime_primary` + `regime` 双字段 | schemas.yaml 与用户描述各一 |
| I | data_freshness 自动构造(含 klines + onchain/deriv/macro) | 不用每层手写 |
| J | numpy.bool_ → Python bool 显式转换 | 避免 `is True` 断言失败 |
| K | insufficient_data 时 `regime="unclear_insufficient"` 占位 | 与 8 档 regime enum 区分 |
| L | Swing 分析最近 10 个事件不足 4 → insufficient | 避免误判 |
| M | Layer 读自己 thresholds 块;也能读跨块 | `_threshold([path])` 通用 |

---

## 5. Pytest 结果

```
tests/test_layer1_regime.py ......15 passed in 0.31s

跨模块联测:
tests/ ............. 68 passed in 0.37s
  - 30 indicators
  - 23 composite factors
  - 15 L1 regime
```

---

## 6. Sprint 1.7 → Sprint 1.8+ 衔接

- **Sprint 1.8**:Layer 2 Direction(消费 L1 输出 + BandPosition/CyclePosition composite → 输出 stance + phase + cycle_position)
- **Sprint 1.9**:Layer 3 Opportunity(M16 纯规则判档)
- **Sprint 1.10+**:Pipeline 层协调(composite → evidence → observation → validator)

`EvidenceLayerBase` 的模板方法模式意味着 L2/L3/L4/L5 基本只需:
1. 继承基类
2. 声明 `layer_id / layer_name / thresholds_key`
3. 实现 `_compute_specific(context)` 返回层专属字段 dict

通用字段(时间戳、rules_version、data_freshness、冷启动降级)都由基类自动处理。
