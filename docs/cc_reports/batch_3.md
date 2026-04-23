# 批 3 详细报告 — state_machine.yaml + layers.yaml

**日期**:2026-04-23
**Sprint**:1 前置工作 · 优化二 · 第 3 批
**对应建模文档章节**:§5(状态机)、§4.1-§4.7(五层证据)、§3.2(数据时序契约)、§2.4(否决分类)

---

## 1. 产出概览

| 文件 | 行数 | 叶子字段 |
|---|---|---|
| `config/state_machine.yaml` | 668 | 406 |
| `config/layers.yaml`        | 545 | 319 |
| **小计**                    | 1213 | 725 |

**同批次产生的小改动**:
- `config/thresholds.yaml`:从 `layer_4_risk.execution_permission_merging` 下**移除 `permission_enum`**,替换为指向 `layers.yaml → layer_3_opportunity.output_enums.execution_permission` 的注释。理由见 §3.1。

---

## 2. `state_machine.yaml` 结构

### 2.1 顶层分块

| 块 | 作用 | 条目数 |
|---|---|---|
| `states` | 14 状态的元信息(description / category / is_position_state / is_terminal / default_permission) | 14 |
| `categories` | 状态分组,便于代码做集合判断 | 6 组 |
| `transitions` | 迁移规则 | 35 条 |
| `on_enter_effects` | 进入副作用(§5.5 动作序列) | 14 状态 |
| `flip_watch_cooldown` | 动态冷却(§5.3,M14) | 1 块 |
| `disciplines` | 三条核心纪律(§5.4) | 3 条 |
| `timeframes` | 主/辅助周期 + 白名单/禁用模块(§5.6,§4.4.8) | 4 子块 |

### 2.2 35 条迁移路径分布

- **FLAT 出口**:2(→ LONG_PLANNED / SHORT_PLANNED)
- **LONG 侧**:10(PLANNED → OPEN / 过期;OPEN → HOLD / EXIT;HOLD → TRIM / EXIT;TRIM → HOLD / TRIM / EXIT;EXIT → FLIP_WATCH / FLAT)
- **SHORT 侧**:10(LONG 侧完整镜像)
- **FLIP_WATCH 出口**:3(→ SHORT_PLANNED / LONG_PLANNED / FLAT)
- **PROTECTION 进出**:2(* → PROTECTION;PROTECTION → POST_PROTECTION_REASSESS)
- **POST_PROTECTION_REASSESS 出口**:6(LONG_HOLD / SHORT_HOLD / LONG_EXIT / SHORT_EXIT / FLIP_WATCH / FLAT)
- **其他**:2(SHORT_PLANNED → FLAT 过期等)

### 2.3 迁移条件的 YAML 可表达性处理

建模 §5.2 的条件中有大量**运行时状态依赖**的判断(比如"entry_zone 已 1H 收盘确认"、"所有仓位已平"、"thesis 已失效"),无法用 YAML 枚举表达。处理方式(**自主决策 A**):每条迁移包含两类条件字段 ——
- `enumerable_conditions`:可 YAML 表达的离散条件(AND 语义),代码层直接求合取
- `runtime_conditions`:字符串列表,每个字符串对应 `src/strategy/runtime_conditions.py` 中一个同名函数

这个形式与 `thresholds.yaml` 里 L3 的 `long_grade_rules` / `short_grade_rules` 保持一致,代码层能复用同一套解释器。

### 2.4 `on_enter_effects` 的动作粒度

**自主决策 B**:只声明动作名,**不带参数**。例如 `FLIP_WATCH` 的副作用序列:
```
- archive_previous_lifecycle
- record_flip_watch_start_time
- compute_and_lock_flip_watch_effective_bounds
- reset_position_cap_to_default
```
动作名对应 `src/strategy/on_enter_actions.py` 中同名函数;函数内部所需的数字(例如 default position_cap = 70)从 `base.yaml` / `thresholds.yaml` 取。
**理由**:YAML 擅长表达结构,不擅长表达副作用逻辑;保留可读清单即可。如果带参数会出现"参数散两处"的反模式。

### 2.5 `POST_PROTECTION_REASSESS` 六出口的判定

**自主决策 C**:建模 §5.2 未展开六出口的具体判据。本 YAML 只登记**合法出口白名单**,具体判定委托 `src/strategy/lifecycle_manager.py::post_protection_decide()` 函数。迁移条件的 `runtime_conditions` 写为 `post_protection_decide_returns_long_hold` 等形式,由该函数返回具体目标。
**理由**:建模没展开是**有意**留给运行时判断的(涉及残留仓位、方向、盈亏等复杂组合),YAML 拍板反而越权。

### 2.6 FLIP_WATCH 冷却公式

按建模 §5.3 M14 完整落地:
- 基础:18 / 96 小时
- 4 条乘数(2 条 cycle_position 档 + 2 条 volatility_regime)
- 硬界限:8 / 168 小时(夹断上下限)
- `freeze_on_entry: true`(周期内不变)
- `auto_tuning_enabled: false`(复盘不自动反哺)

---

## 3. `layers.yaml` 结构

### 3.1 为什么 `layers.yaml` 是枚举的归宿(而不是 `thresholds.yaml`)

**自主决策 D**:批 2 微调时我把 `permission_enum` 加在了 `thresholds.yaml`,在批 3 时移除并统一落到 `layers.yaml`。
**理由**:
- `thresholds.yaml` 承载"数字"(ADX 阈值、乘数、评分权重),`layers.yaml` 承载"结构"(枚举、布尔规则、执行顺序、否决分类)
- 分工清晰的好处:后续 `schemas.yaml`(优化一任务)用 Pydantic 生成时,枚举只读一个来源,不用处理重复
- `execution_permission` 是 L3 的输出字段,按"谁输出谁登记"原则应归在 `layer_3_opportunity.output_enums`

### 3.2 顶层分块

| 块 | 作用 |
|---|---|
| `evidence_report_common` | §4.1 通用 EvidenceReport:computation_method / health_status / confidence_tier / contribution 枚举 |
| `execution_order` | §3.2.1 M30 L1→L5 强制顺序 + 上游失败下游短路 |
| `freshness_thresholds_sec` | §3.2.3 M29 四类数据新鲜度阈值(秒) |
| `stale_data_policy` | §3.2.4 Stale 数据处理规则 |
| `veto_classification` | §2.4 M21 三类否决显式分类 |
| `layer_1_regime` | L1 结构契约 |
| `layer_2_direction` | L2 结构契约 + M18 stance_confidence 纪律 |
| `layer_3_opportunity` | L3 结构契约 + M16 三重封闭 + P5 1H 访问边界 |
| `layer_4_risk` | L4 结构契约 + §4.5.4 hard_invalidation 唯一权威 |
| `layer_5_macro` | L5 结构契约 + AI 置信度降级 + 四类数据处理 |
| `observation_classifier` | §4.7 M28 三类规则 + 冷启动第四标签 + 纪律 |

### 3.3 跨文件引用惯例:`thresholds_ref`

**自主决策 E**:`layers.yaml` 里有 5-10 处需要引用 `thresholds.yaml` 的数字(例如 observation_classifier 的持续天数)。采用 `thresholds_ref: <key.path>` 字符串的形式,代码层 resolve。
**理由**:显式依赖利于后续做一次性校验,避免数字散落在两处。成本是需要一个轻量的 path resolver,代码一次性投资。

每层的 `thresholds_ref` 字段指向 `thresholds.yaml` 中对应顶层 key(例如 `layer_1_regime` → `thresholds.layer_1_regime`),方便代码层批量加载。

### 3.4 新鲜度阈值:秒数而非文字

建模 §3.2.3 表格写"> 30 分钟"、"> 6 小时"。YAML 里转化成秒(`1800` / `21600` / `129600` / `172800` / `86400`),便于代码直接比对 `current_time - data_captured_at` 的秒数差。
新增了一个 `event: 86400`(建模文档里没有;事件日历 24 小时刷新一次),作为兜底。

### 3.5 Observation Classifier 规则形式

§4.7.3 的规则用结构化 YAML 表达:
```yaml
conditions:
  - l1_regime_in: [chaos, transition_up, transition_down]
  - l1_volatility_regime_equals: extreme
  ...
```
每个条件是一个 **单键字典**,代码按 key 分发到对应比较函数(`_in`、`_equals`、`_at_or_above` 等)。`not_matching: disciplined` 表达"不属于 disciplined"的负条件。
持续性检查(possibly_suppressed 需持续 ≥ 7 天)用 `persistence_required: true` + `persistence_ref` 指向 thresholds 的天数,避免重复。

### 3.6 Layer 5 的四类数据处理

§4.6.2 的四类数据各自标了 handler:
- `structured_macro_indicators` → `program_collect_to_macro_headwind`
- `structured_event_calendar` → `program_collect_to_event_risk`
- `qualitative_event_summary` → `ai_generate`(v0.5 启用)
- `extreme_event_detection` → `program_detect_then_force_protection`

同时把每类的数据源列表或规则引用直接登记,便于代码自动加载。

---

## 4. 自主决策汇总

| 编号 | 决策 | 理由 |
|---|---|---|
| A | 迁移条件拆 `enumerable_conditions` + `runtime_conditions` | 复用 L3 规则表同款解释器;YAML 无法表达的逻辑委托代码 |
| B | `on_enter_effects` 只写动作名不带参数 | 避免"参数散两处",参数化数字已在 base/thresholds |
| C | POST_PROTECTION_REASSESS 六出口委托代码判定 | 建模未展开属于有意留白;YAML 拍板会越权 |
| D | permission_enum 从 thresholds 移到 layers | 枚举归结构契约;避免未来重复 |
| E | 跨文件引用用 `thresholds_ref: <key.path>` | 显式依赖利于一次性校验;代码投入可接受 |
| F | 新鲜度阈值转秒数 | 代码直接比对时间差,不必再转 |
| G | 为 event 类添加 86400 秒兜底 | 建模未覆盖但事件日历需要一个值 |
| H | Observation rules 用 "单键 dict" 形式 | 代码按 key 分发比较函数,扩展友好 |
| I | `runtime_conditions` 命名统一小写下划线 + 动词短语(例如 `hard_invalidation_breached_4h`) | 读起来像函数名,与代码约定一致 |

---

## 5. 建模覆盖自检

| 建模编号 | 是否落地 | 位置 |
|---|---|---|
| §5.1 14 状态 | ✓ | `states` + `categories` |
| §5.2 核心迁移规则 | ✓ | `transitions`(35 条) |
| §5.3 FLIP_WATCH 冷却 | ✓ | `flip_watch_cooldown` |
| §5.4 三条纪律 | ✓ | `disciplines` |
| §5.5 on_enter 副作用 | ✓ | `on_enter_effects` |
| §5.6 主/辅助周期 | ✓ | `timeframes` |
| §4.1 EvidenceReport | ✓ | `layers.evidence_report_common` |
| §4.2-4.6 五层专属字段 | ✓ | `layers.layer_N_*.output_fields` |
| §4.7 Observation Classifier | ✓ | `layers.observation_classifier` |
| §3.2.1 执行顺序 M30 | ✓ | `layers.execution_order` |
| §3.2.2 reference_timestamp M29 | ✓ | `layers.execution_order.reference_timestamp` |
| §3.2.3-3.2.4 新鲜度 + 处理 | ✓ | `layers.freshness_thresholds_sec` + `stale_data_policy` |
| §2.4 / M21 否决分类 | ✓ | `layers.veto_classification` |
| §4.4.6 opportunity_grade 三重封闭 | ✓ | `layers.layer_3_opportunity.opportunity_grade_write_permission` |
| §4.4.8 / P5 1H 访问边界 | ✓ | `state_machine.timeframes` + `layers.layer_3_opportunity.one_hour_access` |
| §4.5.4 / P4 hard_invalidation 权威 | ✓ | `layers.layer_4_risk.hard_invalidation_contract` |
| §4.6.3 / M18 stance_confidence 纪律 | ✓ | `layers.layer_2_direction.stance_confidence_discipline` |
| §4.6.2 四类数据处理 | ✓ | `layers.layer_5_macro.data_categories` |
| M14 FLIP_WATCH 动态冷却 | ✓ | `state_machine.flip_watch_cooldown` |
| M28 Observation Classifier | ✓ | `layers.observation_classifier` + 纪律 |
| M35 cold_start_warming_up 第四标签 | ✓ | `layers.observation_classifier.cold_start_category` |

**未在本批覆盖(由后续批或代码落地)**:
- `event_calendar.yaml` 的具体事件(批 4)
- 9 个 prompt 文件(批 4)
- schemas.yaml(优化一,单独任务)
- Pydantic model 生成(Sprint 1 代码落地)

---

## 6. 验证

```
config/base.yaml:         OK, leaves=63
config/data_sources.yaml: OK, leaves=150
config/ai.yaml:           OK, leaves=48
config/data_catalog.yaml: OK, leaves=780
config/thresholds.yaml:   OK, leaves=387
config/state_machine.yaml: OK, leaves=406
config/layers.yaml:       OK, leaves=319

state_machine.yaml:
  states: 14
  transitions: 35
  on_enter_effects for: 14 states
  disciplines: 3

layers.yaml:
  top_keys: [evidence_report_common, execution_order, freshness_thresholds_sec,
             stale_data_policy, veto_classification, layer_1_regime,
             layer_2_direction, layer_3_opportunity, layer_4_risk,
             layer_5_macro, observation_classifier]
  veto_hard: 2, veto_soft: 3
  observation rules: [disciplined, watchful, possibly_suppressed]
```

全部 YAML 均通过 PyYAML safe_load 解析,无语法错误。

---

## 7. 状态与 git 说明

**关于"批 2 微调 commit"的说明**:
你在本次请求里重复列了批 2 的 5 项微调并要求 commit message `"Batch 2 micro-adjustments based on review"`。实际上这 5 项微调**已经在上一个 commit** `c87f610` 里完成提交(message `"Config: base / data_sources / ai / data_catalog / thresholds with post-review adjustments"`,这是你上次选的 B 方案消息)。所以本批只生成一个 commit,message 按你本次指定的 `"Add state_machine.yaml and layers.yaml (Batch 3)"`。

本批 commit 包含:
- 新增 `config/state_machine.yaml`
- 新增 `config/layers.yaml`
- 修改 `config/thresholds.yaml`(移除冗余 `permission_enum` 块,改为注释引用)
- 新增 `docs/cc_reports/batch_3.md`(本报告)
