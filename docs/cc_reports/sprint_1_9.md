# Sprint 1.9 — L3 Opportunity Evidence 层(硬规则 + 反模式)

**日期**:2026-04-23
**对应建模章节**:§4.4(全节)、§7.9(反模式清单)、M16(执行纪律)、§8(KPI 观察分类)

---

## ⚠️ Triggers for Human Attention

### 1. **新增 thresholds.yaml keys**:`grade_a_floors` / `grade_b_floors` / `grade_c_floors` / `anti_patterns`

thresholds.yaml 原有 `long_grade_rules` / `short_grade_rules`(Sprint 1.2 v2 batch 2 写的)是"条件表"形式,字段为中文描述性。Sprint 1.9 需要**更结构化、代码可读的**硬门槛 + 参数,我在 layer_3_opportunity 块里新增:
- `grade_a_floors / grade_b_floors / grade_c_floors`:stance_confidence / cycle_confidence / tt/bp/crowd/regime/er/macro 约束清单
- `anti_patterns`:6 个反模式的触发参数(recent_bars、rally_threshold_pct、crowding_triggers 等)

**老的 long_grade_rules / short_grade_rules 保留**(不删),因为它们是建模 §4.4.4/4.4.5 的原始表达,文档一致性重要。代码**只读新的 floors**。

**影响**:用户若未来想调参,改 `grade_*_floors.*` 即可;老的 rules 块当作文档/注释。

### 2. BandPosition output 与用户任务描述的字段**不完全一致**

用户任务描述用 `band_label: upper/mid_upper/mid/mid_lower/lower` + `retracement_room_pct`,但 Sprint 1.6 实际产出的 BandPosition.output 是 `phase: early/mid/late/exhausted/unclear`。我做了**语义翻译**:
- 对 A grade:`band_position_allowed_phases: ["early", "mid"]`(phase 早期或中期 ≈ 低位/中位支撑)
- 对 B grade:`disallowed_phases_bullish/bearish: ["exhausted"]`(不能顶/底)

**没实现的部分**:`retracement_room_pct ≥ 0.04` 这条约束。因 BandPosition output 没有这个字段。若后续 Sprint 1.6 扩展了该字段,再把检查加回来。

### 3. `macro_misalignment` 空头侧**v1 不判**

建模 §7.9 描述宏观逆风,但若 candidate=bearish,"macro 逆风"反而是"tailwind"。Sprint 1.6 的 MacroHeadwind output 只有一个方向的 band(strong_headwind 表示对 risk-on 不利,对 bearish 是好事),没有独立的"strong_tailwind" band 表示"对 bearish 极强不利"。

**我的决定**:`macro_misalignment` v1 只检查 bullish 侧(配置 `bullish_against_bands: ["strong_headwind"]`)。空头侧注释"v1 不设",下 Sprint 补。

### 4. 反模式 Impact 三分类:downgrade_one / force_none / force_protective

我自主定义的三种 Impact:
- `downgrade_one`:A→B→C→none,可叠加(多个 flag 累加降级)
- `force_none`:强制 grade=none(无论 base 多高;counter_trend_trade 用)
- `force_protective`:强制 grade=none + permission=protective(catching_falling_knife 用;已持仓应平仓)

**聚合逻辑**:所有 flag 依次应用:force_* 优先(任一触发即 override);否则 downgrade 累加。permission_cap 取所有 flag 里**最严**的。

### 5. Cold start 冷启动 grade 天花板 = "B"(硬编码)

用户说"grade 天花板为 B",我硬编码 `_COLD_START_GRADE_CEILING = "B"`。若想改阈值(例如冷启动期也允许 A),改这个常量。若想配置化,加到 thresholds.yaml 的 cold_start 块。

另外用户提到"L4 冷启动样本数 < 门槛 → 强制 grade=none",这需要 L4 的 context 字段,**Sprint 1.12 再接**。当前只 note 标注。

### 6. `execution_permission` 映射:C → `hold_only`

用户任务描述明确:"grade=C → hold_only"。但在 Sprint 1.8 / layers.yaml 的语境里,`hold_only` 是"HOLD 状态 on_enter 设置,不参与归并"。

我的处理:L3 按用户指令输出 `hold_only`。L4(Sprint 1.10+)归并时需要特殊处理:hold_only 不参与 severity 归并,但也不被覆盖(保持原值)。Sprint 1.10 的 permission_composition 合并逻辑需要考虑这点。

### 7. 基础门槛 **先于** grade 评估(early exit)

L2 stance=neutral 或 health_status=insufficient_data 或 confidence_tier=very_low → 直接 `grade=none + permission=watch + observation_mode=kpi_validation`,**不跑反模式扫描**。这通过 `_emit_none()` 统一出口实现,代码干净。

### 8. cycle_unclear / tt_weak 作为 **grade 上限 cap**

用户说"cycle=unclear → 最多 C 级" / "truth_trend=weak → 最多 C 级"。我实现为:
- 先按正常流程算 base_grade(A/B/C/none)
- 若 cycle_unclear 或 tt_weak,强制把 A/B 降到 C(max("C", base))
- 这个 cap 在反模式扫描**之前**应用

### 9. 反模式 `chasing_high` 需要 band_phase 支持才触发

原始描述是"近 3 根涨幅 > 8% + band=upper"。我实现时把"band=upper"翻译为 `bp_phase in {late, exhausted, unclear}`(对应 BandPosition 输出的高位/过熟 phases)。

若 bp_phase=early 或 mid(低位),即使价格大涨也**不算 chasing**(因为从低位涨上来合理)。

### 10. `overtrading_crowding` 需要 crowding.direction 与 candidate 同向

若 `crowding.band=extreme, direction=crowded_long` 且 candidate=bullish → 触发(跟着极端多头进场)。
若 crowding.band=extreme 但 direction=crowded_short,bullish candidate **不**触发(反而是逆势机会)。
这比简单"extreme 就触发"更合理。

### 11. `event_window_trading` 窗口硬编码 24 小时 + 事件类型白名单

用户"未来 24h 内有 high/extreme 事件"。我用 `hours_window: 24` + 白名单 `["fomc", "cpi", "nfp", "options_expiry_major"]`。这些都在 thresholds.yaml 可配置。

注意:这里**直接读 events_upcoming_48h list**,不依赖 composite.event_risk.band。因为 event_risk.band=high 的 72h 窗口 ≠ 24h 窗口。

### 12. A grade 无反模式时 permission = `can_open`,**不是 no_chase / cautious_open**

用户任务描述清晰:A + 无反模式 = can_open(最宽松,因为所有条件都对齐)。反模式触发时才降到 cautious_open / no_chase / ambush_only。这是 L3 的"完美环境才能 can_open"纪律。

---

## 1. 变更清单

| 文件 | 行数 | 说明 |
|---|---|---|
| `config/thresholds.yaml` | +45 | 新增 `grade_{a,b,c}_floors` + `anti_patterns` 参数块 |
| `src/evidence/_anti_patterns.py` | 260 | 6 反模式扫描器 + apply 聚合器 |
| `src/evidence/layer3_opportunity.py` | 370 | Layer3Opportunity + grade 检查 + 映射表 |
| `src/evidence/__init__.py` | 微调 | 导出 Layer3Opportunity |
| `tests/test_layer3_opportunity.py` | 340 | 19 tests,**全过** |

---

## 2. 判定流程

```
_compute_specific(context):
  Step 0: 基础门槛
    stance=neutral OR health=insufficient → grade=none + watch(早退)
  Step 1: Grade A 硬规则(8 项全过)
  Step 2: Grade B 硬规则(6 项全过)
  Step 3: Grade C 硬规则(1 项:stance_conf ≥ 0.55)
  Grade cap: cycle=unclear OR tt=no_trend → 最多 C
  Step 4: 反模式扫描(6 种)
  Step 5: 应用反模式降级 + permission cap
  Step 6: 冷启动 cap grade 到 B
  Step 7: 组装输出
```

**输出 26+ 字段**,包括 schemas.yaml 必需字段 + 审计字段(`base_grade_before_anti_patterns` / `hard_rule_check_results` / `anti_pattern_details` / `diagnostics`)。

---

## 3. Grade → execution_permission 基础映射

| Grade | Base permission |
|---|---|
| A | `can_open` |
| B | `cautious_open` |
| C | `hold_only` |
| none | `watch` |

反模式的 `permission_cap` 会**进一步收紧**(取更严者)。

例:Grade A + overtrading_crowding 触发 → grade 降到 B (downgrade_one),permission cap = `no_chase`。B 的 base permission 是 cautious_open,no_chase 比 cautious_open 更严 → final = `no_chase`。

---

## 4. 6 个反模式清单

| Flag | Impact | Permission Cap | 触发条件 |
|---|---|---|---|
| `chasing_high` | downgrade_one | no_chase | bullish + 近 N 根涨 > 8% + phase=late/exhausted |
| `catching_falling_knife` | force_protective | protective | candidate 与近 N 根急动向相反 |
| `counter_trend_trade` | force_none | watch | L1 regime 与 candidate 对立 |
| `overtrading_crowding` | downgrade_one | no_chase | crowding=extreme 且方向同向 |
| `event_window_trading` | downgrade_one | ambush_only | 未来 24h 内高影响事件 |
| `macro_misalignment` | downgrade_one | none(无 cap)| bullish + macro=strong_headwind |

---

## 5. 自主决策汇总

| 编号 | 决策 | 理由 |
|---|---|---|
| A | 新增 `grade_*_floors` / `anti_patterns` 配置块 | 代码可读的执行参数;老 rules 保留作文档 |
| B | BandPosition 用 phase 替代 band_label | Sprint 1.6 实际产出的字段 |
| C | retracement_room_pct 检查**跳过** | Sprint 1.6 未实现该字段,推到未来 |
| D | macro_misalignment 空头侧 v1 不判 | 没有 "strong_tailwind" band 对称表示 |
| E | 反模式 Impact 三分类 | 降级 + 强制 none + 强制 protective 的清晰区分 |
| F | 早退路径 `_emit_none()` 统一 | 代码干净,避免流程分岔 |
| G | cycle_unclear / tt_weak 作 grade 上限 cap,先于反模式 | 这些是基础条件缺失,不是行为异常 |
| H | chasing_high 需要 phase=late/exhausted | 低位反弹 ≠ chasing |
| I | overtrading_crowding 需要方向同向 | 逆向时反而是机会 |
| J | 反模式用专用模块 `_anti_patterns.py` | 逻辑多,独立便于维护 |
| K | 冷启动天花板 B 硬编码 | 配置化留给未来 |
| L | `observation_mode` 由 grade 派生(不反向)| M16 执行纪律 |
| M | diagnostics 含 inputs / grade_evaluation / anti_patterns_applied | 便于 Sprint 1.10+ backtest 排查 |
| N | hard_rule_check_results 每项 bool | 失败时能快速看到哪条卡住 |
| O | base_grade_before_anti_patterns 字段 | 审计:区分"基础评估"与"反模式处罚后" |

---

## 6. Pytest 结果

```
tests/test_layer3_opportunity.py  19 passed in 0.34s

分组:
- TestLayer3Opportunity × 15(每个 grade + 每个反模式)
- TestLayer3Schema × 4(字段完整性 / 枚举合法性)
```

**跨 Sprint 全套**:
```
tests/ .......  106 passed in 0.39s
  - 30 indicators
  - 23 composite
  - 15 L1 regime
  - 19 L2 direction
  - 19 L3 opportunity
```

---

## 7. Sprint 1.9 → Sprint 1.10+ 衔接

- **Sprint 1.10**:L4 Risk —— 消费 L3 的 `execution_permission` + anti_pattern_flags,跑 position_cap 串行合成(M19)和 hard_invalidation_levels(§4.5.4 P4)
- **Sprint 1.11**:L5 Macro(AI 接入)
- **Sprint 1.12**:Pipeline 协调 + Observation Classifier + last_stable_cycle_position + 冷启动样本数门槛对接

L3 的输出为 L4 提供了:
- `opportunity_grade` (A/B/C/none) → position_cap 基础
- `execution_permission` → L4 归并的初始值
- `anti_pattern_flags` → L4 风险标签可以引用(如 event_window_trading 直接映射为 risk_tag=`event_window_active`)
