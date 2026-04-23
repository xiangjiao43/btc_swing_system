# Sprint 1.6 — 6 个组合因子(TruthTrend / BandPosition / CyclePosition / Crowding / MacroHeadwind / EventRisk)

**日期**:2026-04-23
**对应建模章节**:§3.8

---

## ⚠️ Triggers for Human Attention

### 1. 输出 schema:schemas.yaml 和用户任务描述**有字段命名冲突**,我按 schemas.yaml 为权威

- schemas.yaml `truth_trend_output` 字段:`score / band / items_triggered / regime_switch_first_week / confidence`
- 用户任务描述字段:`status / direction / strength / score_breakdown / confidence_tier / computation_method / health_status / notes`

我的处理:**产出 union**(两套字段都在输出里),以 schemas.yaml 为核心,额外加 `computation_method / health_status / notes / direction / confidence_tier / diagnostics` 作为运行时元信息。Sprint 1.7+ 的 evidence 层可按 schemas.yaml 字段消费,若需要更人读的 status 也能取到。

类似情况存在于其他 5 个 factor。**建议后续用户明确 schemas.yaml 作为唯一真相**;我已按此推进。

### 2. CyclePosition 的"投票"实现按**band-level 计票**

建模 §3.8.4 原文:
> 三主指标各自映射候选档 → 通过 aux 检查的候选档进入投票池 → 三票一致 → 0.85,两票一致 → 0.60

这可以解读为"**每指标选一个主票**"或"**band 级计票**(每个 band 被多少指标列在候选里)"。实践发现:
- MVRV Z = 1.0 单独看只匹配 early_bull
- NUPL = 0.15 既匹配 early_bull 也匹配 mid_bear(range 重叠)

若用"每指标主票",NUPL 可能选 mid_bear(范围顺序靠后),造成"3 个独立票中 2 个 early_bull、1 个 mid_bear"→ 2 票一致 → 0.60。
若用"**band 级计票**",early_bull 在 3 个候选集中都出现 → 3 票 → 0.85。

后者更贴近建模的"三票一致"本意(不同指标从不同角度都支持同一 band)。我采用后者。

**编码期建议**:Sprint 1.10+ 的 backtest 对比旧系统时如有差异,优先检查投票算法。

### 3. CyclePosition 加了 `trend` 约束过滤

thresholds.yaml bands 里 `mid_bear.mvrv_z: { range: [-0.5, 2], trend: down }`。我实现 `_series_trend(series, lookback=30)` 判断近 30 天的 delta 均值方向(> 0 up / < 0 down / flat)。只有方向匹配才算候选。

**假设**:trend: down 要求 series 趋势确实在下行(通过最近 30 天 diff 均值)。若建模意图不同(例如"价格路径向下穿越该档"),需调整。当前实现是 Sprint 1.6 合理推断。

### 4. `late_bear` 的 `trend_stabilizing_check_required`

实现:近 30 天 MVRV Z 的一阶差均值 > 0 视为"已企稳",从候选池剔除 late_bear。
- `stabilizing_check_result = True` → 已企稳 → late_bear **不在**候选
- `stabilizing_check_result = False` → 仍在下跌 → late_bear **可以**在候选
- `stabilizing_check_result = None` → 数据不足 → 不做过滤(保守不剔除)

若建模意图是反向(企稳才算 late_bear),告诉我。

### 5. `last_stable_cycle_position` 固定返回 None(Sprint 1.12 再接)

按用户指令:"state_history_dao 没数据返回 None"。现在 `_lookup_last_stable(dao)` 无条件返回 None,**不查 DAO**。Sprint 1.12+ 需:
- 接入 `StrategyStateDAO.get_recent_states(...)` 找最近一次非 unclear 的 `cycle_position`
- 注意 M17 纪律:last_stable 只用于展示/审计,**不进当前决策**

### 6. Crowding:2 项**已跳过**(v1 数据未采集)

跳过清单:
- `basis_high`:`basis_annualized` 指标未接入(Sprint 1.4 未覆盖,后续从 CoinGlass 补端点)
- `put_call_low`:`put_call_ratio` 同上

另外,`funding_rate_percentile_high` 需要 30 天历史;数据不足时同样 skip。

输出的 `items_skipped` 字段列出原因,不抛错、不 FAIL verdict。

### 7. MacroHeadwind `driver_breakdown` 字段非 schemas.yaml 定义

schemas.yaml 定义了 `score / band / position_cap_multiplier / correlation_amplified / items_triggered`。我额外加了 `driver_breakdown`(每个触发 item 的详细 drive 说明)+ `data_completeness_pct`,便于诊断。不影响 schemas 合规。

### 8. EventRisk `contributing_events` 字段结构

schemas.yaml 只说 `contributing_events: list`。我定义了结构:
```
{
  name, type, hours_to, base_weight, distance_multiplier,
  vol_bonus_applied, us_corr_bonus_applied, effective_score
}
```
这是合理外延,审计/debug 友好。

### 9. EventRisk 的 `is_volatility_extreme` / `btc_nasdaq_correlated` 由外部注入

这两个值不能由 EventRisk 自己算(需要 L1 的输出或 MacroHeadwind 的输出)。当前 context 约定:
- `context["is_volatility_extreme"]`: bool,默认 False
- `context["btc_nasdaq_correlated"]`: bool,默认 False

Sprint 1.7+ 的 pipeline 调用方负责按 L1 的 volatility_regime 和 MacroHeadwind.correlation_amplified 填入这两个字段。

### 10. Volume 字段命名一致性

Tests 构造的 context 用 `volume_btc` / `volume_usdt` 列,这是 Sprint 1.2 v2 修复后 KlineRow 的字段名。factors 里暂未有消费 volume 的逻辑(TruthTrend 预期有 "volume_btc 趋势"但 thresholds.yaml `truth_trend_scoring.items` 只定义了 5 项,不含 volume trend)。

如果后续 thresholds.yaml 加 `volume_trend` item,需要同步到 truth_trend.py 的 handler 映射。

---

## 1. 变更清单

| 文件 | 行数 | 说明 |
|---|---|---|
| `src/composite/_base.py` | 112 | CompositeFactorBase + load_thresholds + helpers |
| `src/composite/truth_trend.py` | 177 | 5 项评分 |
| `src/composite/band_position.py` | 207 | 价格几何 4 维评分 |
| `src/composite/cycle_position.py` | 280 | 九档投票 + trend/aux/stabilizing 过滤 |
| `src/composite/crowding.py` | 163 | 7 项(实现 4 项 + 1 反向,skip 2 项) |
| `src/composite/macro_headwind.py` | 203 | 5 项 + BTC-Nasdaq 相关性加权 |
| `src/composite/event_risk.py` | 138 | 事件类型 × 距离权重 + 2 类 bonus |
| `src/composite/__init__.py` | 24 | 统一导出 |
| `tests/test_composite_factors.py` | 345 | 23 tests,**全部通过** |

---

## 2. Pytest 结果

```
23 passed in 0.34s
```

分布:
- TestTruthTrend × 4
- TestBandPosition × 3
- TestCyclePosition × 4
- TestCrowding × 3
- TestMacroHeadwind × 4
- TestEventRisk × 5

**每个因子**都覆盖:
- 正常路径(强信号 → 明确 band)
- 部分/全部数据缺失 → `health_status ∈ {degraded, insufficient_data}`
- 输出字段完整性

---

## 3. 架构关键决策

### 3.1 CompositeFactorBase 共享基类

```python
class CompositeFactorBase:
    name: ClassVar[str] = ""
    thresholds_key: ClassVar[str] = ""
    
    def __init__(self):
        self.full_thresholds = _load_thresholds_full()  # lru_cached
        self.scoring_config = self.full_thresholds.get(self.thresholds_key, {})
    
    def compute(self, context): ...
    def _insufficient(self, reason, **extra): ...
    def _threshold(self, path, default): ...
```

每个 factor 子类:
1. 声明 `name` + `thresholds_key`
2. 实现 `compute(context)`
3. 遇到数据缺失时返回 `self._insufficient(reason, **partial_output)`
4. 通过 `self.scoring_config` 读自己的评分块,通过 `self._threshold(path)` 读跨块配置

### 3.2 Context 约定

所有 factor 接受同一个 context dict:
- `klines_1h / 4h / 1d / 1w`: pd.DataFrame
- `derivatives`: dict[metric_name → pd.Series]
- `onchain`: dict[metric_name → pd.Series]
- `macro`: dict[metric_name → pd.Series]
- `events_upcoming_48h`: list[dict]
- `state_history_dao`: optional
- `is_volatility_extreme`: bool(EventRisk 用)
- `btc_nasdaq_correlated`: bool(EventRisk 用)

Sprint 1.7+ 的 pipeline 负责从 DAO 构造 context 并传给每个 factor。

### 3.3 Thresholds 驱动评分

每个 factor 的 `points` 来自 thresholds.yaml,**不在代码里硬编码**。代码只决定"是否触发某 item",触发后加的分数从 config 读。

```python
points_map = {i["name"]: i["points"] for i in self.scoring_config["items"]}
if <condition>:
    if "item_name" in points_map:
        score += points_map["item_name"]
        items_triggered.append("item_name")
```

好处:调分不改代码;建模 bump rules_version 时对应 thresholds.yaml 改,代码不需要跟进(除非规则**新增了 item**)。

---

## 4. 自主决策汇总

| 编号 | 决策 | 理由 |
|---|---|---|
| A | 输出产 union(schemas.yaml 字段 + 用户描述字段) | 两方都不破坏;下游按需取 |
| B | CyclePosition 用 band-level 计票 | 更贴合建模"三票一致"本意 |
| C | trend 约束作为 range 检查的**附加过滤** | 避免 MVRV Z=1.0 同时匹配 early_bull 和 mid_bear |
| D | `_series_trend` 用 30d delta 均值,死区=1% std | 简单鲁棒;避免噪音触发 |
| E | late_bear 的 stabilizing_check:企稳 → 剔除 | 符合建模"未企稳"约束 |
| F | last_stable 硬返回 None(不触 DAO) | Sprint 1.12 专门对接 |
| G | Crowding 跳过的 2 项记 `items_skipped` 而非抛错 | 数据缺失是渐进式落地,不应 FAIL |
| H | MacroHeadwind 加 `driver_breakdown` / `data_completeness_pct` | 审计/debug 友好 |
| I | EventRisk `is_volatility_extreme` / `btc_nasdaq_correlated` 由 context 注入 | 跨 factor 依赖外部化;避免循环 |
| J | 所有 factor 用 `@lru_cache` 共享 thresholds 加载 | 进程内单例,避免重复 I/O |
| K | `_base.py` 暴露 `confidence_tier_from_value()` 统一分档 | schemas.yaml high/medium/low/very_low 统一 |
| L | 所有 factor output 加 `diagnostics` 字段展示中间量 | 单测 + Sprint 1.10 backtest 排查用 |
| M | `_BAND_ORDER` 作类级常量,确保枚举与 schemas.yaml 一致 | 并列 band 时按建模顺序取最早(保守) |

---

## 5. 验收

```
uv run pytest tests/test_composite_factors.py -v
==> 23 passed in 0.34s
```

跨模块(Sprint 1.5 indicators + Sprint 1.6 composite)联合:

```
uv run pytest tests/ -v
==> 53 passed(30 indicators + 23 composite)
```

---

## 6. Sprint 1.6 → Sprint 1.7+ 衔接

Composite 层完成后,下一步:

- **Sprint 1.7**:`src/evidence/layer1_regime.py` 等五层消费 composite factor 输出,组装 EvidenceReport
- **Sprint 1.8**:Observation Classifier(纯规则,读 L1-L5 输出)
- **Sprint 1.9**:状态机 + 生命周期管理
- **Sprint 1.10**:跑通 scenarios/ 下 3 个历史快照,M26 验收初版
- **Sprint 1.12**(用户指明):CyclePosition 对接真实 `last_stable` 查询(StrategyStateDAO)

**本 Sprint 独立可交付**:composite 输出 = 六个 Python dict;evidence 层可用。
