# 批 5 详细报告 — schemas.yaml(优化一:字段唯一真相来源)

**日期**:2026-04-23
**Sprint**:1 前置工作 · 优化一(Schemas 契约)
**对应建模文档章节**:§4.1、§4.2.4-§4.7.2、§3.8、§6.2-§6.4、§6.9、§7.2、§8.2-§8.3

---

## ⚠️ Triggers for Human Attention

> 以下是本批次需要人类注意的决策点,可直接摘录给审阅者。

### 1. 发现 4 处跨文件枚举不一致(schemas.yaml 已做权威声明,未改动其他文件)

按你的规则"不一致以 schemas.yaml 为准,标注而不静默修改",schemas.yaml 的 `consistency_notes` 段登记了:

| 不一致项 | 其他文件现状 | 建议处理 |
|---|---|---|
| `execution_permission` 7 值 vs `layers.yaml` 6 值(缺 `no_chase`) | [layers.yaml](../../config/layers.yaml) `layer_3_opportunity.output_enums.execution_permission` 6 值 | 批 6 或后续时在 layers.yaml 补 `no_chase` |
| `execution_permission` 严格度排序缺 `no_chase` | [thresholds.yaml](../../config/thresholds.yaml) `layer_4_risk.execution_permission_merging.severity_rank` 5 值 | 把 `no_chase` 插在 `ambush_only` 和 `cautious_open` 之间 |
| `outcome_type` 命名风格 | 建模 §8.3 用单字母代号(A perfect)+ 冒号描述,`schemas.yaml` 展开为 `A_perfect / B_good_suboptimal / ...`(下划线 snake) | 以 schemas.yaml 的 snake 风格为准 |
| `freshness_class` 增加了 `event` 值 | `layers.yaml` 已有(批 3 自主决策) | 无冲突,已对齐 |

**为什么不静默改**:你在本批指令里明确说"发现不一致,以建模文档为准,并在 schemas.yaml 里标注"。所以只标注不改,留给你或审阅者决定。

### 2. 建模文档里"无展开内容"的枚举,我拟定了合理值

以下枚举**建模文档未展开**,我按合理拟定补齐;**需人类复核**:

- `failure_mode`(§8.3 归因用):建模只说"failure_mode",没列值。我定了 `[data_gap, rule_mismatch, ai_error, validator_reject, manual_override, n_a]`。如果后续复盘场景有新 mode,加到这里。
- `lifecycle_stage`:建模 §7.2 Block 6 列了 5 个值(`just_opened / holding / partial_trimmed / preparing_exit / flip_watching`)但没明确叫 stage,我把这组合并为 `lifecycle_stage` 枚举。
- `validation_result_status`:建模 §6.4 没有枚举名,只说"passed / failed / fallback_applied";我命名为 `validation_result_status`。

### 3. `execution_permission` 新增的 `no_chase` 严格度位置我是推测的

建模 §4.5.5 只说 `no_chase: 保留计算值(不抬升,不压低)`,没明示它在严格度序列里的位置。我基于语义("不追但也不禁")推测放在 `ambush_only` 和 `cautious_open` 之间,形成:
```
最严 ← protective > watch > ambush_only > no_chase > cautious_open > can_open → 最宽
```
**建议编码期在 validator 里做一次实际路径检验**:如果归并时 `no_chase` 的位置产生反直觉结果,调整这个顺序。

### 4. `position_cap_composition` 字段顺序我加了一个未在建模示例里的步骤

建模 §4.5.5 的示例是 5 步:`base → after_l4_risk → after_l4_crowding → after_l5_macro → after_l4_event → final`。我在 schemas.yaml 里额外加了一个可选字段 `after_l1_volatility`(L1 volatility_regime = extreme 时的 × 0.5 步骤),因为 §2.4 把它列为软否决但 §4.5.5 的审计示例没展示它。**我的处理是标 required: false**,代码层有此步骤时填,否则省略。如果你觉得应该合并到某一步(例如 after_l4_risk 之前),通知我改。

### 5. 建模文档中发现的互相矛盾/不清晰之处(3 处)

**(a) `overall_data_health_status` 三值 vs `health_status` 四值**
- §4.1 通用结构列 `health_status: healthy / degraded / insufficient_data / error`(4 值)
- §7.2 Block 2 列 `overall_status: healthy / degraded / critical`(3 值,"critical" 而非 "insufficient_data/error")
- 我的处理:两个独立枚举 `health_status`(layer 级)和 `overall_data_health_status`(data_health block 级),分别定义。但 `critical` vs `error` 的区别不明,运行时需要人工确认。

**(b) stop_loss 字段结构在不同地方描述不同**
- §7.2 Block 5 描述为 `struct (price 来自 L4, type, invalidation_desc, reasoning, linked_to_l4_invalidation_id)`
- §6.3 AIAdjudicatorOutput 的 trade_plan 只列 `trade_plan` 而没展开
- §4.5.4 的 hard_invalidation 契约说 stop_loss 是"表层复制"
- 我的处理:建 `stop_loss_struct` 在 `common_types.structures`,含 5 个字段(price/type/invalidation_desc/reasoning/linked_to_l4_invalidation_id),并在 strategy_state 和 ai_adjudicator_output 都引用同一结构。

**(c) `impact_weight` 的 range 不明**
- §7.2 Block 8(evidence_cards)没给 `impact_weight` 的数值范围
- 我的处理:拍了 `[0.0, 1.0]`。如果实际使用是 1-5 或其他范围,改这里。

### 6. 可能与建模意图不完全一致的点

**(a) `M22 prolonged_watch_warning` 我没在 schemas 里单独建字段**
你在指令里列了 M22。我查建模,M22 对应的是 `thresholds.kpi_tracker.prolonged_watch.critical_runs` 和 `forced_human_runs`,这是**KPI 阈值**,不是 StrategyState 字段。在 StrategyState 里它只表现为 `block_10_risks.active_alerts` 里的一条 `alert_type: prolonged_watch`。所以 schemas 没单独建字段,只在 `risk_tag` 和 `active_alert` 枚举里间接覆盖。**如果你希望 prolonged_watch 作为独立字段暴露(例如 block_4_main_strategy 加一个 prolonged_watch_days 数字),请告知。**

**(b) `last_stable_cycle_position`(M17)放在 `long_cycle_context` 嵌套字典里**
schemas.yaml 的 L2 layer_2_direction_schema.specific_fields.long_cycle_context 是个 dict 类型(没展开字段),`last_stable_cycle_position` 在 description 里提及。更严格的做法是展开 long_cycle_context 的四字段(cycle_position / cycle_confidence / data_basis / last_stable_cycle_position)。我没展开,因为建模 §4.3.4 本身也是用一句"{cycle_position, cycle_confidence, data_basis, last_stable_cycle_position(展示用)}"描述。**如果 Sprint 1 时需要 Pydantic model 细化,展开成独立结构也行。**

---

## 1. 产出概览

| 文件 | 行数 | 大小 |
|---|---|---|
| `config/schemas.yaml` | 1477 | 41.5 KB |

**覆盖统计**:

| 维度 | 数量 |
|---|---|
| 顶层块 | 17 |
| `common_types.enums`(枚举定义) | 41 |
| `common_types.structures`(共享嵌套结构) | 11 |
| `strategy_state` 业务块 | 12 |
| 组合因子 output schema | 6 |
| 程序校验规则 | 9 |
| Fallback 级别 | 3 |
| 叶子字段总数 | 1506 |

---

## 2. schemas.yaml 顶层结构

| 顶层键 | 内容 |
|---|---|
| `consistency_notes` | 跨文件枚举一致性对照(4 项) |
| `common_types` | 41 枚举 + 11 共享结构 |
| `evidence_report_base` | 五层 EvidenceReport 通用字段(§4.1) |
| `layer_1_regime_schema` | L1 `extends evidence_report_base` + 11 specific_fields(§4.2.4) |
| `layer_2_direction_schema` | L2 + 11 specific_fields(§4.3.4) |
| `layer_3_opportunity_schema` | L3 + 8 specific_fields(§4.4.9) |
| `layer_4_risk_schema` | L4 + 10 specific_fields(§4.5.7) |
| `layer_5_macro_schema` | L5 + 9 specific_fields(§4.6.4) |
| `observation_classifier_output_schema` | §4.7.2 输出 4 字段 |
| `composite_factors_schemas` | 6 组合因子的 output(§3.8) |
| `strategy_state_schema` | 12 业务块完整字段(§7.2) |
| `ai_adjudicator_input_schema` | §6.2 输入契约 |
| `ai_adjudicator_output_schema` | §6.3 输出契约 |
| `program_validation_rules` | §6.4 9 条校验规则 + 各自 fallback 级别 |
| `fallback_state_schema` | 3 级 Fallback 下 StrategyState 的字段重写规则(§6.9) |
| `lifecycle_schema` | §8.2 StrategyLifecycle |
| `review_report_schema` | §8.3 ReviewReport 完整结构 |

---

## 3. v1.2 M 编号覆盖自检

| M 编号 | 字段落地位置 |
|---|---|
| M16 opportunity_grade 单一产出 | `layer_3_opportunity_schema.opportunity_grade` notes;`ai_adjudicator_output_schema.opportunity_grade` notes;validation rule 8 |
| M17 `last_stable_cycle_position` | `composite_factors_schemas.cycle_position_output.last_stable_cycle_position`;`layer_2_direction_schema.long_cycle_context.description` |
| M18 `stance_confidence` 内部量纪律 | `layer_2_direction_schema.stance_confidence.notes`;`strategy_state_schema.block_4.stance_confidence.notes` |
| M19 `position_cap_composition` 完整审计 | `strategy_state_schema.block_10_risks.position_cap_composition`(7 字段) |
| M20 `permission_composition` 归并审计 | `strategy_state_schema.block_10_risks.permission_composition`(7 字段) |
| M21 三类否决分类 | layers.yaml(批 3)+ 本文件 `common_types.enums` 注释 |
| M22 prolonged_watch 告警 | `active_alert.alert_type`(字符串白名单值)+ KPI 阈值在 thresholds.yaml(非 schema 字段,见 Triggers 6a) |
| M27 KPI | thresholds.yaml `kpi_tracker`(非 schema 字段) |
| M28 `observation_category` | `common_types.enums.observation_category` 4 值;`block_4_main_strategy`;`ai_adjudicator_input_schema` |
| M29 `reference_timestamp_utc` / `data_freshness` | `block_1_meta.reference_timestamp_utc`;`block_7_evidence_summary.*.data_freshness`;`common_types.structures.data_freshness_item` |
| M31 evidence_cards 摘要版 | `ai_adjudicator_input_schema.evidence_cards_summary.notes`;`block_8_evidence_cards` item_fields |
| M33 Fallback 三档 | `fallback_state_schema`(完整 3 级的 overrides) |
| M35 cold_start | `block_1_meta.cold_start`;`observation_category` 第四值 |
| M36 `rules_version` | `block_1_meta.rules_version`;`lifecycle_schema.rules_versions_used` |
| M37 `ai_model_actual` | `block_1_meta.ai_model_actual`;`block_9_ai_verdict.ai_model_actual` |
| M38 `run_trigger` | `common_types.enums.run_trigger` 8 值;`block_1_meta.run_trigger` |
| M39 时区存储规则 | 体现在 `event_window` 结构(event_time_us_east / bjt / utc + dst_active) |

---

## 4. 自主决策汇总

| 编号 | 决策 | 理由 |
|---|---|---|
| A | 顶层加 `consistency_notes` 段 | 按用户要求"标注不一致";把跨文件对照记录在权威文件里,便于后续复核 |
| B | 枚举命名用 `snake_case` 字面量(如 `A_perfect`) | 建模用描述性短语,YAML 里枚举值需可机读;snake_case 最安全 |
| C | 共享嵌套结构抽出到 `common_types.structures` | 多处(StrategyState Block 5 stop_loss、AIAdjudicatorOutput trade_plan、L4 hard_invalidation_levels)引用同一结构,避免重复 |
| D | `failure_mode` / `lifecycle_stage` / `validation_result_status` 拟定枚举值 | 建模未展开但字段确实需要枚举;给合理初值,Sprint 1 可校准 |
| E | `no_chase` 插入 severity 序列中段 | 语义"不追但不禁"最接近 ambush_only 和 cautious_open 之间 |
| F | `after_l1_volatility` 作为可选步骤加入 `position_cap_composition` | §2.4 软否决有此步但 §4.5.5 审计示例没展示;标 required: false |
| G | 两个 health 枚举并存(`health_status` 4 值 + `overall_data_health_status` 3 值) | 建模本身两处定义不同,按建模保留 |
| H | `impact_weight` 范围拍 [0.0, 1.0] | 建模未给;符合"归一化权重"的常见约定 |
| I | Fallback 三级用 "overrides" + "carried_from_previous_run" 两个子块表达 | 比单纯列字段更能表达"此级别下字段的**差异**",而非全量 |
| J | 程序校验规则列成独立顶层块(而非附到各字段) | 与字段正交;validator 实现时按此 9 条顺序跑 |
| K | 未展开 L2 `long_cycle_context` 嵌套字段 | 建模自身未展开,保持一致;Sprint 1 Pydantic 时可细化 |
| L | `evidence_cards.analysis` 字段同时在 block_8 出现,但标注 M31 摘要版规则 | 全量 analysis 存 DB,AI 输入用摘要,两个版本在 schema 里保留完整定义 |

---

## 5. 验证

```
schemas.yaml: OK
  top_keys (17): [consistency_notes, common_types, evidence_report_base,
                  layer_1_regime_schema, layer_2_direction_schema,
                  layer_3_opportunity_schema, layer_4_risk_schema,
                  layer_5_macro_schema, observation_classifier_output_schema,
                  composite_factors_schemas, strategy_state_schema,
                  ai_adjudicator_input_schema, ai_adjudicator_output_schema,
                  program_validation_rules, fallback_state_schema,
                  lifecycle_schema, review_report_schema]
  leaf_count: 1506
  common_types.enums: 41 enum definitions
  common_types.structures: 11
  strategy_state blocks: 12
  composite_factors: 6
  program_validation_rules: 9
  fallback levels: 3
```

全部 YAML 通过 PyYAML safe_load,无语法错误。

---

## 6. 下一步建议

1. **打通字段漂移** —— 按 `consistency_notes` 的 4 项,用 30 分钟修正 layers.yaml / thresholds.yaml,让全项目枚举值统一。
2. **生成 Pydantic model** —— Sprint 1 开始时,用脚本 `scripts/generate_pydantic_from_schemas.py` 读 schemas.yaml 生成 `src/schemas/*.py`。字段类型可直接翻译(string→str / number→float / datetime→datetime / enum→Literal / dict→BaseModel)。
3. **AI validator 字段白名单** —— `src/decision/validator.py` 启动时加载 schemas.yaml,用 `ai_adjudicator_output_schema` 校验 AI 输出。
4. **数据库 schema 对齐** —— `scripts/init_db.py` 按 `strategy_state_schema` 生成 `strategy_runs` 表的 JSON 字段结构提示(部分列直接,部分存 `full_state_json`)。

**优化一完成后的项目状态**:
- 批 1-4 的 9 个 config 文件 + 3 个 prompt 文件已就位
- 本批 schemas.yaml 是"字段契约"单一真相来源
- 建模文档 → schemas.yaml → 代码 Pydantic model 的链路打通

接下来只剩**优化三:3 个测试快照**(tests/fixtures/),以及 Sprint 1 代码落地。
