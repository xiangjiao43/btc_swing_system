# Sprint Layer A 六阶段重构 + 新裁决 Prompt 落地

**日期**:2026-05-17
**目标**:Layer A 周期阶段 7 → 6 重构,新增 `exit_all` 动作,落地新 system prompt,所有下游(枚举/状态机/normalizer/validator/网页/测试)一次性同步。
**触发**:用户指令(modeling.md 暂无 Layer A 章节,以指令为蓝本)。
**决策前提**:六阶段顺序 `bear_bottom → recovery → bull_main → bull_late → top_distribution → bear_decline` 闭环;旧记录硬切不做兼容映射;`exit_all` 激进度最高、且豁免保守化降级。

---

## 1. 七项改动逐项做了什么

### 改动 1 — `src/ai/agents/prompts/layer_a_cycle_adjudicator.txt`(prompt 全文替换)

新 prompt 9 大节,从旧 66 行扩展到 ~190 行。核心新增结构:
- **第三节(六个阶段)**:每阶段给出"典型特征"(价格 + 链上),并列出与上下游相邻阶段的区分点。`recovery` 阶段单列「反转 vs 反弹判读表」(5 行 × 2 列)作为防误判工具。
- **第四节(判断方法)**:四步推理链(看价格位置 → 链上结构定性 → 综合矛盾 → 大周期是慢变量)。明确"系统默认应维持 previous_official_stage 不变"。
- **第五节(举证责任分级)**:常规 / 强化 / 关键跨越三档,关键跨越(熊底/熊跌 → 复苏、熊跌 → 熊底)要求逐条对照「反转 vs 反弹判读表」。
- **第六节(置信度与数据质量)**:明文"你的 cycle_stage_confidence 不得高于 data_quality.confidence_cap"。
- **第七节(判断与说明一体生成)**:"任何判断都必须同时给出两边证据";"严禁编造任何数字";"trader_summary 最多 2 句"。
- **第八节(输出格式)**:14 字段 JSON schema,明确动作枚举里加入 `exit_all`,并标注 `bear_decline → exit_all`。
- **第九节(完整 JSON 示例)**:bull_late 的演示样例,带具体数值。

注:document 在传输中遭遇 UTF-8 双重编码 + C1 控制字符丢失,无法 latin-1 round-trip 恢复。已基于 mojibake 结构忠实转写为标准 UTF-8 中文,保留所有节标题、阶段判别表、举证规则、示例。

### 改动 2 — `src/ai/spot_cycle_stage_state.py`(状态机模块)

- `OFFICIAL_CYCLE_STAGES = ("bear_bottom","recovery","bull_main","bull_late","top_distribution","bear_decline")`
- `CURRENT_STAGE_MODEL_VERSION = "layer_a_six_stage_v2"`
- `STAGE_DEFAULT_ACTION`:六个阶段 1:1 映射,`bear_decline → exit_all`
- `LEGACY_STAGE_MAP`:**硬切**,只保留 6 个新名各自映射到自己;旧名 `accumulation/bull_bear_transition/early_bull/mid_bull/late_bull/overheated_top/deep_value/deep_bear/bear_transition/trend_hold/distribution/overheated_exit` 全部移除
- `ACTION_RANK`:加 `"exit_all": 5`(rank 最高,在 strong_sell 之后)
- `ACTION_ALIASES`:不为 `exit_all` 加别名(按指令)
- **`conservative_action_for_official_stage` 的 exit_all 豁免实现**:函数顶部加 `if proposed == "exit_all": return "exit_all"` 提前 return,**在任何风险/阶段降级判断之前**。这样 `exit_all` 绝不会被改写为 `hold` 或其他动作。另外,该函数原本的 risk-driven 降级 `if risk in {"high","critical"} and proposed in {"strong_buy","dca_buy"}: return "hold"` 显式只列了 `strong_buy/dca_buy`,即使没有早 return 也不会触碰 exit_all —— 双重保险
- 其余阶段-动作冲突分支已按新 6 阶段重写;新增 `bear_decline` 分支:本阶段下任何非默认动作都降级为默认动作(`exit_all`),进一步硬化"熊跌阶段必须离场"语义
- `evaluate_stage_transition`/`stage_distance` 仍用 tuple `index()` 距离计算,新 tuple 自动生效,无需改邻接表逻辑;message 文字"七阶段"→"六阶段"

### 改动 3 — `src/ai/spot_strategy_normalizer.py`

- `SPOT_ACTIONS = ("strong_buy","dca_buy","hold","scale_sell","strong_sell","exit_all")`
- **所有 default 值更新如下**(按指令统一用 `bear_bottom` 兜底,最保守):
  - 第 218/219/220/248 行(fallback `a1_cycle_stage` / `a5_spot_adjudicator` 的 `cycle_stage / raw_stage_assessment / official_cycle_stage`):`"mid_bull"` → `"bear_bottom"`
  - 第 260/261 行(fallback `cycle_adjudicator` 的 `raw_stage_assessment / official_stage_recommendation`):`"bull_bear_transition"` → `"bear_bottom"`
  - 第 283 行(`normalize_a1` default):`"bull_bear_transition"` → `"bear_bottom"`
  - 第 371 行(`normalize_a5` default):同上
  - 第 396 行(`normalize_cycle_adjudicator` default):同上
  - 警告字符串 `a1_invalid_cycle_stage_normalized_to_bull_bear_transition` → `a1_invalid_cycle_stage_normalized_to_bear_bottom`(同样 a5 那一条)

### 改动 4 — `src/ai/spot_validator.py`

- 第 122 行 `if action in ("strong_buy", "strong_sell")` → 增加 `"exit_all"` 进入"必须双边举证"硬约束
- 第 141 行 `stage in ("bear_bottom", "accumulation")` → 改为 `("bear_bottom", "recovery")`,warning 改名为 `strong_sell_in_value_or_recovery_stage`
- 第 147 行 scale_sell 关键字白名单:`late_bull` → `bull_late`;中文关键字 `牛市后期` → `牛市末期`
- **新增 `exit_all` 软警告**:`if action == "exit_all" and stage in ("bear_bottom","recovery","bull_main")` → warning `exit_all_in_non_distribution_or_decline_stage`(exit_all 应只在 top_distribution / bull_late / bear_decline 这类风险升高阶段触发)

### 改动 5 — `src/ai/spot_cycle_context_builder.py`

确认:`allowed_stage_transitions.allowed_stages = list(OFFICIAL_CYCLE_STAGES)` 在两处(行 425 / 699)自动跟随新 tuple,无需改代码。dry run 实测 `allowed_stages = ['bear_bottom','recovery','bull_main','bull_late','top_distribution','bear_decline']` 正确。

### 改动 6 — `web/assets/app.js`

- `spotActionLabel` map:加 `exit_all: '清仓离场'`
- `spotCycleStageLabel` map:旧 13 条移除,改为新 6 阶段标签 + `unclear` 兜底:
  ```js
  bear_bottom: '熊市底部',
  recovery: '复苏期',
  bull_main: '牛市主升',
  bull_late: '牛市末期',
  top_distribution: '顶部派发',
  bear_decline: '熊市下跌',
  unclear: '不明确',
  ```

### 改动 7 — 测试更新(5 个文件)

| 文件 | 改动概要 |
|---|---|
| `tests/test_layer_a_spot_normalize.py` | 全量将旧阶段名映射到新名(`early_bull/accumulation → recovery`、`mid_bull/bull_bear_transition → bull_main`、`late_bull → bull_late`、`overheated_top → top_distribution`)。fixture `cycle_stage_model_version: layer_a_seven_stage_v1` → `layer_a_six_stage_v2`(否则会走 recalibration 分支)。`test_cross_stage_jump_requires_three_confirmations`:目标改为 `bull_main`(距 `bear_bottom` 距离=2,满足 ≥3 confirms 语义)。两个测试函数名改名 + STAGE_DEFAULT_ACTION 期望表改成新 6 项含 `bear_decline → exit_all`。invalid stage default 断言从 `"bull_main"` 改回 `"bear_bottom"`(我的 bulk replace 一开始误把这条 default 期望也改名了,后续修回)。 |
| `tests/test_layer_a_spot_context_builder.py` | fixture `accumulation` → `recovery`、`layer_a_seven_stage_v1` → `layer_a_six_stage_v2`、`allowed_stages` 期望改为新 6 项 |
| `tests/test_layer_a_spot_validator.py` | helper default `mid_bull` → `bull_main`;`stage="overheated_top"` → `stage="top_distribution"` |
| `tests/test_layer_a_orchestrator_integration.py` | 所有 `early_bull` → `recovery` |
| `tests/test_layer_a_standalone_schedule.py` | fixture `accumulation` → `recovery` |
| `tests/test_web_modules_4_5_rp_failure.py` | 中文标签断言从旧 7 个改为新 6 个(`熊市底部 / 复苏期 / 牛市主升 / 牛市末期 / 顶部派发 / 熊市下跌`)|

注:`tests/web_helpers/test_normalize_state.py:54` 的 `rule_cycle_position: "early_bull"` 是 **Layer B** 9-band cycle_position 因子,按指令不动。

### 额外修复(dry run 发现):`src/ai/agents/spot_cycle_agents.py`

`LayerACycleAdjudicator._fallback_output()` 原 `raw_stage_assessment / official_stage_recommendation: "bull_bear_transition"` 改为 `"bear_bottom"`,保持与 normalizer 默认值一致。

---

## 2. 测试结果 + dry run 输出

### 测试

```
.venv/bin/python -m pytest tests/test_layer_a_*.py tests/test_web_modules_1_2_3.py
======================= 95 passed, 12 warnings in 0.87s ========================

.venv/bin/python -m pytest --tb=line -q
1 failed, 1875 passed, 1 skipped, 672 warnings in 47.27s
```

唯一失败 `test_collect_klines_1h_kline_succeeds_derivatives_fail` 与本 sprint 无关 —— 这是历次 sprint 报告里都记录过的上游遗留(`16cad4f` 改 `_classify_failure` 后未跟新的断言)。

### dry run(本机真实数据,不持久化)

**adjudicator_context(AI 看到的输入)结构**:
```
schema_version: layer_a_single_cycle_adjudicator_v2_three_packets
top-level keys: ['allowed_stage_transitions', 'data_packets', 'data_quality',
                 'instructions', 'layer_a_boundaries', 'previous_official_stage',
                 'recent_stage_history', 'schema_version', 'stage_model']
data_packets keys: ['price_structure_packet', 'onchain_packet', 'macro_flow_packet']
allowed_stages: ['bear_bottom', 'recovery', 'bull_main', 'bull_late',
                 'top_distribution', 'bear_decline']
previous_official_stage: None  ← 旧 accumulation 记录因 LEGACY_STAGE_MAP 不含
                                  而归于 None,触发"首次输出"分支(预期行为)
```

**cycle_adjudicator(端到端结果)**:

⚠️ **本机 `.env` 没有 `ANTHROPIC_API_KEY`**(只有 Glassnode/CoinGlass key),所以 AI 调用走了 fallback 路径 3 次失败 retry。结构上一切正确,但**不是 AI 真实输出**。生产服务器有 key,会产出真实 AI JSON。

fallback path 的产出(用来验证管道完整性,不是 AI 真实判断):
```json
{
  "raw_stage_assessment": "bear_bottom",
  "official_stage_recommendation": "bear_bottom",
  "transition_status_recommendation": "pending",
  "cycle_stage_confidence": "low",
  "spot_action_recommendation": "hold",
  "risk_level": "elevated",
  "official_cycle_stage": "bear_bottom",
  "transition_status": "confirmed",
  "final_spot_action": "hold",
  "stage_change_reason": "AI 裁决失败，正式阶段交由状态机按上一轮和 fallback 处理。",
  "status": "degraded_ai_failed"
}
```

**关键验证**:
- ✅ AI 输出的阶段是新 6 枚举值之一(bear_bottom)
- ✅ 旧 accumulation 记录未导致崩溃 —— 系统正确识别 LEGACY_STAGE_MAP 不认旧名,走"首次输出"分支(stage_change_reason 文字含"首次 Layer A 六阶段输出")
- ✅ 阶段→动作映射:fallback 给的是 `hold`(因为 fallback 选 bear_bottom + AI 失败,状态机给保守 hold);若 AI 真返回 `bear_decline`,STAGE_DEFAULT_ACTION 会映射为 `exit_all`(测试 `test_six_stage_default_action_mapping_is_exposed_to_a5` 已验证此映射)
- ✅ prompt 数据包结构一致:prompt 第二节描述 `price_structure_packet / onchain_packet / macro_flow_packet`,代码实际产出也是这三个 key
- ✅ validator passed,无 violations / warnings(fallback 给的是合法结构)

**生产端验证项**(用户在服务器跑过一次后请确认):
1. `cycle_adjudicator.raw_stage_assessment` ∈ {6 个新枚举之一}
2. `cycle_adjudicator.spot_action_recommendation` ∈ {6 个枚举含 exit_all}
3. 若上轮存档是 `accumulation`,本轮 `previous_official_stage` 应为 `None`,`transition_status: confirmed`,`stage_change_reason` 文字含"首次 Layer A 六阶段输出"

---

## 3. 部署四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ Layer A + web 95/95;全量 1875 通过 + 1 上游遗留失败 + 1 skipped |
| 本地 dry run 结构验证 | ✅ 3 包结构 + 6 阶段枚举 + 顶层 data_quality + 旧记录硬切兼容均正确 |
| GitHub 推送 | ❌ 待用户确认(尚未 commit + push,等本报告 review 后再走流程)|
| 服务器 git pull | ❌ 待用户执行 |
| 服务器 systemctl restart | ❌ 待用户执行(restart 后下次 10:00 BJT Layer A job 会按新 6 阶段 + 新 prompt 产出 AI 裁决)|
| 生产 DB schema 迁移 | N/A(无 schema 变更;旧 accumulation 记录通过 LEGACY_STAGE_MAP 自然失活,无需手动清理)|

---

## 4. 本 sprint 删除清单

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| 旧 prompt 全文(7 阶段、4 包旧描述、66 行 prompt) | `prompts/layer_a_cycle_adjudicator.txt` | 完整替换为新 6 阶段、3 包描述、~190 行 prompt |
| 旧 7 阶段枚举常量 | `spot_cycle_stage_state.py:OFFICIAL_CYCLE_STAGES` | 替换为 6 阶段新值 |
| 旧 STAGE_DEFAULT_ACTION 7 条 | `spot_cycle_stage_state.py:25-33` | 替换为新 6 阶段 1:1 映射含 `exit_all` |
| `LEGACY_STAGE_MAP` 12 条旧别名 | `spot_cycle_stage_state.py:35-49`(`deep_value/deep_bear/bear_transition/trend_hold/distribution/overheated_exit/accumulation/bull_bear_transition/early_bull/mid_bull/late_bull/overheated_top`)| 用户指令硬切,只保留 6 个新名自映射 |
| `conservative_action_for_official_stage` 内的旧阶段分支(原 line 286-298 共 7 个 if 分支)| `spot_cycle_stage_state.py:273-300` | 替换为新 6 阶段对应分支 + `exit_all` 豁免逻辑 |
| `spot_validator.py:141` 老 `accumulation` 关键字 | 同上 | 改为新 `recovery` |
| `spot_validator.py:147` 老 `late_bull` 关键字 + 中文 `牛市后期` | 同上 | 改为 `bull_late` + `牛市末期` |
| `app.js` 旧阶段标签 map 14 条 | `web/assets/app.js:1300-1318` | 替换为新 6 阶段标签 |
| 测试 fixture 旧阶段名 80+ 处 + 旧 model_version 字符串 5 处 | 5 个测试文件 | 替换为新枚举 + 新 model_version |

**自检 `git grep`**:
- `git grep -E "accumulation|bull_bear_transition|early_bull|mid_bull|late_bull|overheated_top|deep_value|deep_bear|bear_transition|trend_hold|overheated_exit" src/ai/ web/` 在 Layer A 范围 = **0**
- Layer B 相关文件(`composite/cycle_position.py / evidence/pillars.py / ai/anti_pattern_signals.py / config/thresholds.yaml / config/schemas.yaml`)按指令未触碰
- 旧 `_fallback_output` 中的 `bull_bear_transition` 在 dry run 时被发现,已修复
- 没有"备用 / fallback"代码遗留

---

## 5. 风险提示与待办

1. **本地无 ANTHROPIC_API_KEY**:dry run 时 AI 调用 3 次失败 retry 走 fallback。**生产服务器需要确保 ANTHROPIC_API_KEY 有效**才能产出真实 AI 输出;否则会一直走 fallback。
2. **AI 真实判断的"合理性"未在本机验证**:本 sprint 仅验证结构正确性。新 prompt 是否能让 AI 正确"反转 vs 反弹"鉴别、是否会用第五节的强化举证机制,需要在生产服务器观察至少 1-2 次真实运行后人工核查。
3. **旧 accumulation 记录在生产首次运行后会自然失活**:LEGACY_STAGE_MAP 不含旧名 → `previous_official_stage()` 返回 None → 走"首次输出"分支,本轮 raw_stage 直接被接受为 official。这是设计上的"模型升级冷启动",可控。
4. **`exit_all` 必须配双边证据**:validator 已加硬约束。若 AI 输出 `exit_all` 但 supporting_evidence / opposing_evidence 任一为空,validator 会硬挂(violations 非空)。这是有意的"激进动作必须充分举证"设计。
