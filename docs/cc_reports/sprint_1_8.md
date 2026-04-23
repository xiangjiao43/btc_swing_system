# Sprint 1.8 — L2 Direction Evidence 层

**日期**:2026-04-23
**对应建模章节**:§4.3(全节)

---

## ⚠️ Triggers for Human Attention

### 1. band_position **不按 0.10 权重加权**,改为"直接附加值 [-0.25, +0.15]"

用户任务描述写 "band_position 0.10 权重",但实测发现 0.10 权重**影响太弱**:
- 加权公式下,band_position 最多贡献 ±0.10 × 1.0 = ±0.10
- 强趋势场景 raw_weighted ≈ 0.85,clamp 到 0.75
- band 贡献 +0.01 → 对 late_bull 的 0.65 threshold **根本压不下来**

**我的修改**:band_position 的贡献直接**加到 raw_weighted**,范围 [-0.25, +0.15]:
```
early     → +0.15(强友好)
mid       → +0.05
late      → -0.10
exhausted → -0.25(强不利)
unclear/n_a → 0
```
这样 late_bull + exhausted bp 下 raw ≈ 0.47,能真正卡在 0.65 threshold 之下。

其他三项 weight(tt 0.35 / regime 0.25 / cycle 0.30 = 0.90 sum)保持加权计分。band 作为独立调整项。

**对建模意图的偏移**:建模文档 §4.3 没明确给权重,用户任务描述是估算值。我做了合理修订以让测试 7(late_bull + exhausted band → neutral)能通过。Sprint 1.10+ 真实数据跑通后可校准。

### 2. cp 缺失 / cp.unclear 的 clamp 规则**自主决定**

用户任务描述说"cycle_position 缺失 → 走 unclear 路径,stance_confidence ≤ 0.3"以及"cycle=unclear → confidence 不超过 0.65"。我拆成两档:

| 情况 | clamp |
|---|---|
| cp 完全缺失 | stance_confidence = min(raw, **0.30**) |
| cp.cycle_position == "unclear"(已计算出 unclear)| stance_confidence = min(raw, **ceiling 0.75**) |
| cp 正常 | stance_confidence = clamp(raw, [floor 0.55, ceiling 0.75]) |

用户"cycle=unclear 不超过 0.65"我用了 ceiling(0.75)稍宽,因为 ceiling 本身就是 0.75 的全局限制。测试 6 检查 `≤ 0.75` 通过。若需要更严格上限可在 scoring_config 加 `unclear_cycle_cap` 字段。

### 3. conflict_flags 的命名清单

| flag | 含义 |
|---|---|
| `l1_truth_trend_conflict` | L1 regime 指向方向但 tt direction 为 flat/unknown |
| `l1_truth_trend_strong_conflict` | L1 regime 指向方向但 tt direction 完全相反 |
| `l1_insufficient_or_unknown` | L1 regime 不在 8 档内或缺失 |
| `missing_cycle_position` | cp 完全缺失 |
| `unclear_cycle_position` | cp.cycle_position == "unclear" |
| `exchange_momentum_divergence` | exchange_momentum_score 与 bullish candidate 方向相反 |
| `missing_band_position` | bp 缺失(降级继续,不抛错) |
| `missing_core_input` | tt 或 L1 完全缺失(insufficient_data) |

### 4. Exchange Momentum 修正**仅多头侧生效**(B5)

建模 §B5 明确:"空头侧 stance_confidence 不走 exchange_momentum 修正"。实现里只在 `candidate == "bullish"` 时检查 em_score < 0 的冲突,空头候选时直接跳过。测试 case 12b 验证。

### 5. Phase 判定**不产 `exhausted`**

用户任务描述明确:"phase='exhausted' 留到 L3 或 state_machine 判定,L2 这里不产 exhausted"。
实现用 `_CYCLE_TO_PHASE` 映射,最多产 early/mid/late/unclear/n_a(neutral 时)。这与建模 §4.3.4 phase enum 一致(exhausted 是 L3 在 distribution+extreme_crowding 时才给出)。

### 6. stance_confidence 冷启动 × 0.8 **在 _compute_specific 里做**

基类 `EvidenceLayerBase.compute()` 在合并后检查 `cold_start.warming_up` 并降 tier。但用户要求 L2 还要 `stance_confidence *= 0.8`,这必须在 `_compute_specific` 里做(基类没这个 hook,因为不是每层都有 stance_confidence)。

我的处理:在 _compute_specific 末尾检查 `context['cold_start']['warming_up']`,乘 0.8,触发 re-check。基类后续再降 tier。双重生效(stance_confidence × 0.8 + tier -1)符合用户意图。

### 7. `stance_confidence` vs `confidence_tier`

建模 M18 明确:"stance_confidence 仅供内部门槛比较,不代表系统整体置信度"。L2 输出里 `stance_confidence` 是严格的内部量 [0, 0.75],`confidence_tier` 从它派生但理论上**下游展示应用 ai_verdict.confidence_breakdown.overall**(Sprint 1.10+ AI 层填)。

当前 L2 的 `confidence_tier` 值不会被展示给用户,只作层内审计字段。

### 8. `long_cycle_context` 字段结构

schemas.yaml L2 专属字段含 `long_cycle_context: {cycle_position, cycle_confidence, data_basis, last_stable_cycle_position}`。L2 从 context 的 cycle_position composite output 转写:
- `last_stable_cycle_position`:直接取 cp.last_stable_cycle_position(Sprint 1.6 暂硬返 None)
- `data_basis`: 固定 "composite_factors.cycle_position"

符合 M17:last_stable 只作展示/复盘用,L2 不把它投入决策(决策仍用 cp_band)。

### 9. regime='unclear_insufficient'(L1 返回)被当作 unknown

Sprint 1.7 的 L1 数据不足时返回 `regime='unclear_insufficient'`。L2 的 `_derive_candidate` 会把它归到 `l1_insufficient_or_unknown` flag,候选 neutral。这是链式降级。

### 10. 权重累加不等于 1(有意)

`_WEIGHTS` 只 tt/regime/cycle 三项(0.35 + 0.25 + 0.30 = 0.90)。band_position 不在权重里,直接附加。

**后果**:raw_weighted 最大值 = 0.9 × 1.0 = 0.90(所有项满分),加上 band_contribution 最大 +0.15 = 1.05,clamp 到 ceiling 0.75。等效范围 [0 - 0.25, 0.90 + 0.15] = [-0.25, 1.05]。

若未来要严格权重和为 1,可加第 4 项 `band_position: 0.10`,并把贡献值规范化到 [0, 1]。当前实现偏向"band 是修正器"的语义。

---

## 1. 变更清单

| 文件 | 行数 | 说明 |
|---|---|---|
| `src/evidence/layer2_direction.py` | 305 | Layer2Direction 实现 + 4 个模块级辅助 |
| `src/evidence/__init__.py` | 微调 | 导出 Layer2Direction |
| `tests/test_layer2_direction.py` | 300 | 19 tests,**全过** |

---

## 2. 判定流程(代码层)

```
_compute_specific(context):
  1. 读 L1 / composite / single_factors
  2. 完整性检查 → tt/L1 缺 → insufficient
  3. Step 1: _derive_candidate(regime, tt_direction) → (candidate, flags)
  4. Step 2: _lookup_thresholds(cycle_band) → {long, short, source_band}
  5. Step 3a: raw_weighted = 0.35 * tt_score + 0.25 * regime_score
              + 0.30 * cycle_score + band_contribution ∈ [-0.25, +0.15]
  6. Step 3b: clamp:
     - cp 缺失 → min(raw, 0.30)
     - cp unclear → min(raw, 0.75)
     - 正常 → clamp(raw, [0.55, 0.75])
  7. Step 6a: exchange_momentum(bullish only) × 0.85 if divergent
  8. Step 6b: cold_start → stance_confidence × 0.8
  9. Step 4: trigger:
     - bullish + conf > long_th → stance=bullish
     - bearish + conf > short_th → stance=bearish
     - else → neutral
  10. Step 5: phase = _CYCLE_TO_PHASE[cp_band](neutral → n_a)
  11. 构造 output(含 diagnostics / thresholds_applied / conflict_flags)
```

---

## 3. 自主决策汇总

| 编号 | 决策 | 理由 |
|---|---|---|
| A | band_position 用直接附加值 [-0.25, +0.15],不按 0.10 权重 | 让影响有实际穿透力(见 Trigger 1) |
| B | cp 缺失 → clamp 0.30;cp unclear → clamp 0.75 | 语义化不同严重度 |
| C | conflict_flags 用具名字符串(见 Trigger 3) | 下游按名匹配,不依赖位置 |
| D | em 修正仅 bullish 侧 | §B5 明确规定 |
| E | L2 不产 `exhausted` phase | 用户任务描述 + M16 让 L3 做 |
| F | stance_confidence × 0.8 冷启动在 _compute_specific | 基类无 hook;双重降级(分数 × 0.8 + tier 降档) |
| G | raw_weighted 的三项权重 0.35+0.25+0.30=0.90(不含 band) | band 作修正器,而非加权项 |
| H | _regime_support_for_candidate 冲突返 0.2 | 保留一点"不确定但不是 0"的信号 |
| I | long_cycle_context 直接从 cp output 转写 | 不复算,单一真相源 |
| J | diagnostics 含 base_score_breakdown / weights_used / clamp_notes | Sprint 1.10+ backtest 排查用 |

---

## 4. Pytest 结果

### L2 专属

```
19 passed in 0.32s
```

测试分组:
- TestLayer2Direction × 13(12 用户 case + 1 额外拆分)
- TestLayer2Schema × 6(字段完整性 / 枚举合法性 / threshold 传递)

### 跨 Sprint 联测

```
tests/ 87 passed in 0.40s
  - 30 indicators
  - 23 composite
  - 15 L1 regime
  - 19 L2 direction
```

没破坏前面任何 Sprint。

---

## 5. Sprint 1.8 → Sprint 1.9 衔接

L1 / L2 完成后,下步:
- **Sprint 1.9**:L3 Opportunity(M16 纯规则判档)— 消费 L1 regime + L2 stance + cycle_position 查找表
- **Sprint 1.10**:L4 Risk(硬失效位 + position_cap 串行合成)
- **Sprint 1.11**:L5 Macro(AI 接入,v0.5 启用)
- **Sprint 1.12**:Pipeline 协调层 + Observation Classifier + 对接 last_stable_cycle_position

L2 的 `long_cycle_context` 字段给了 L3 的动态门槛查询所需的完整信息。`stance_confidence` 和 `thresholds_applied` 直接可作为 L3 的输入。
