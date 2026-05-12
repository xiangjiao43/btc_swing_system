# layer_a_spot_cycle_strategy_full_model_and_implementation

生成时间：2026-05-12  
任务性质：Layer A 大周期现货策略最终建模设计 + 可运行闭环实现  
一句话结论：已新增独立 Layer A「大周期策略」闭环，写入 `full_state_json.layer_a_spot_strategy`，网页显示“大周期策略”；Layer B 的 L1-L5、Master、Validator、thesis、虚拟账户和 C 级机会行为保持原样。

## 1. 任务目标

本轮目标不是 MVP，而是按最终正确形态设计 Layer A：

- Layer A 只负责 BTC 现货大周期策略。
- Layer A 不做空、不加杠杆、不创建 thesis、不生成 entry / stop_loss / take_profit、不进入虚拟账户。
- Layer A 不使用 Layer B 的 A/B/C/NONE。
- Layer A 只输出五类现货动作：分批买入、强势买入、持有、分批卖出、强力卖出。
- Layer B 继续保持原有 L1-L5 + Master + Validator + thesis + virtual account。
- 虚拟账户只管理 Layer B。

## 2. 读取文件

本轮读取和复核了：

- `AGENTS.md`
- `README.md`
- `docs/codex_reports/dual_layer_factor_inventory_and_data_source_audit.md`
- `config/data_catalog.yaml`
- `config/data_sources.yaml`
- `config/schemas.yaml`
- `config/thresholds.yaml`
- `config/ai.yaml`
- `src/ai/orchestrator.py`
- `src/ai/context_builder.py`
- `src/ai/master_input_builder.py`
- `src/ai/agents/prompts/l1_regime.txt`
- `src/ai/agents/prompts/l2_direction.txt`
- `src/ai/agents/prompts/l3_opportunity.txt`
- `src/ai/agents/prompts/l4_risk.txt`
- `src/ai/agents/prompts/l5_macro.txt`
- `src/ai/agents/prompts/master_adjudicator.txt`
- `src/ai/validator.py`
- `src/strategy/thesis_persistence.py`
- `src/api/routes/strategy.py`
- `src/evidence/pillars.py`
- `src/evidence/plain_reading.py`
- `web/index.html`
- `web/assets/app.js`
- `tests/test_web_modules_1_2_3.py`
- `tests/test_web_modules_4_5_rp_failure.py`
- `tests/web_helpers/test_normalize_state.py`
- `src/data/collectors/glassnode.py`
- `src/data/collectors/coinglass.py`
- `src/data/collectors/fred.py`
- `src/data/storage/dao.py`
- `src/data/storage/schema.sql`
- 最近 weekly review / factor audit 报告

## 3. 改动文件

### 新增文件

- `src/ai/spot_cycle_context_builder.py`
- `src/ai/spot_strategy_normalizer.py`
- `src/ai/spot_validator.py`
- `src/ai/agents/spot_cycle_agents.py`
- `src/ai/agents/prompts/a1_spot_cycle.txt`
- `src/ai/agents/prompts/a2_onchain_macro.txt`
- `src/ai/agents/prompts/a3_spot_opportunity.txt`
- `src/ai/agents/prompts/a4_spot_risk.txt`
- `src/ai/agents/prompts/a5_spot_adjudicator.txt`
- `tests/test_layer_a_spot_context_builder.py`
- `tests/test_layer_a_spot_validator.py`
- `tests/test_layer_a_spot_normalize.py`
- `tests/test_layer_a_orchestrator_integration.py`
- `docs/codex_reports/layer_a_spot_cycle_strategy_full_model_and_implementation.md`

### 修改文件

- `README.md`
- `src/ai/agents/__init__.py`
- `src/ai/orchestrator.py`
- `src/pipeline/state_builder.py`
- `src/pipeline/_orchestrator_mapper.py`
- `src/web_helpers/normalize_state.py`
- `web/index.html`
- `web/assets/app.js`
- `tests/pipeline/test_orchestrator_mapper.py`
- `tests/test_web_modules_1_2_3.py`
- `tests/test_web_modules_4_5_rp_failure.py`
- `tests/web_helpers/test_normalize_state.py`

说明：`uv.lock` 在本轮开始前已有本地改动，本轮未触碰、未提交。

## 4. Layer A 最终建模设计

Layer A 是独立于 Layer B 的大周期现货策略层。

它的最终模型是五层：

| 层 | 名称 | 职责 |
|---|---|---|
| A1 | 大周期阶段 | 判断 BTC 处于熊市底部、吸筹、牛市早期、中段、末期、派发、转熊、深熊或不明确 |
| A2 | 链上与宏观 | 判断链上估值、持有人行为、资金流、宏观环境是否支持现货买入、持有或减仓 |
| A3 | 现货策略机会 | 在五类现货动作里给候选动作，不使用 A/B/C |
| A4 | 现货风险 | 分析现货策略风险，不输出做空 |
| A5 | 大周期主裁 | 综合 A1-A4，输出最终现货动作 |

设计原则：

- AI 像交易员一样综合判断，不做机械规则打分器。
- 规则和 validator 只防止 AI 胡来，不替 AI 下策略判断。
- 缺失因子不伪造成中性，写进 `data_quality_notes` 和 `unavailable_factors`。
- 极端动作必须有多维证据和反方证据。

## 5. Layer A A1-A5 设计

### A1 大周期阶段

输出：

- `cycle_stage`
- `confidence`
- `headline`
- `human_summary`
- `bullish_evidence`
- `bearish_evidence`
- `conflicting_evidence`
- `data_quality_notes`

支持阶段：

- `bear_bottom` 熊市底部
- `accumulation` 底部吸筹
- `early_bull` 牛市早期
- `mid_bull` 牛市中段
- `late_bull` 牛市末期
- `distribution` 顶部派发
- `bear_transition` 转熊阶段
- `deep_bear` 深度熊市
- `unclear` 不明确

### A2 链上与宏观

输出：

- `onchain_macro_stance`
- `confidence`
- `valuation_reading`
- `holder_behavior`
- `macro_reading`
- `liquidity_reading`
- `human_summary`
- `supporting_evidence`
- `opposing_evidence`
- `data_quality_notes`

### A3 现货策略机会

输出：

- `preferred_action_candidate`
- `confidence`
- `human_summary`
- `buy_logic`
- `sell_logic`
- `why_not_other_actions`
- `suggested_plan`
- `do_not_do`
- `data_quality_notes`

五类动作：

- `dca_buy` 分批买入
- `aggressive_buy` 强势买入
- `hold` 持有
- `scale_out` 分批卖出
- `aggressive_sell` 强力卖出

### A4 现货风险

输出：

- `spot_risk_level`
- `confidence`
- `human_summary`
- `main_risks`
- `risk_controls`
- `overheat_signals`
- `downside_risks`
- `invalidation_watch`
- `data_quality_notes`

### A5 大周期主裁

输出：

- `spot_action`
- `cycle_stage`
- `confidence`
- `headline`
- `human_summary`
- `suggested_plan`
- `do_not_do`
- `supporting_evidence`
- `opposing_evidence`
- `what_would_change_mind`
- `next_review_focus`
- `data_quality_notes`

## 6. Layer A 完整因子模型

### 已进入本轮可运行输入的因子

| 类别 | 因子 |
|---|---|
| 链上估值 / 周期 | MVRV Z、MVRV、NUPL、Realized Price、LTH/STH Realized Price、LTH/STH MVRV |
| 持有人行为 | LTH Supply、STH Supply、LTH/STH Supply 90d change、aSOPR、HODL Waves、CDD、SSR |
| 交易所 / 资金流 | Exchange Netflow、Exchange Netflow 30d sum、ETF Flow、ETF Flow 7d/30d sum |
| 大周期价格结构 | ATH Drawdown、200D、200W、weekly 13w/52w change、multi-timeframe alignment |
| 宏观 | DXY、US10Y、VIX、Nasdaq、BTC-Nasdaq correlation、macro event calendar |
| 市场背景 / 风险 | BTC Dominance、funding、funding z-score、OI、OI z-score、long/short ratio、liquidation total |

### 模型预留但本轮不接入决策的候选因子

这些会进入 `unavailable_factors`，不会被伪造成中性值：

- Market Cap / Realized Cap
- RHODL Ratio
- Reserve Risk
- Puell Multiple
- Percent Supply in Profit
- Percent Supply in Loss
- LTH Net Position Change
- LTH SOPR
- STH SOPR
- Liveliness
- Exchange Balance
- Exchange Net Position Change
- Stablecoin Supply / Liquidity
- 1M structure
- Major support / resistance for Layer A
- US2Y
- Real Yield
- Fed Funds Rate
- CPI / Core CPI 数值
- Unemployment
- M2
- Fed Balance Sheet
- Futures Basis / Premium
- Options IV / Skew
- Liquidation Heatmap / Levels

## 7. 当前已可用因子清单

代码级确认已可用：

- Glassnode：MVRV Z、MVRV、NUPL、Realized Price、LTH Supply、STH Supply、Exchange Netflow、aSOPR、HODL Waves、CDD、SSR、LTH/STH Realized Price。
- CoinGlass：BTC K 线、Funding、Open Interest、Long/Short Ratio、Liquidation history、ETF Flow、BTC Dominance。
- FRED：DXY proxy、US10Y、VIX、Nasdaq。
- local calendar：宏观事件日历。
- derived：ATH drawdown、200D、200W、LTH/STH MVRV、BTC-Nasdaq correlation、funding/OI z-score。

## 8. 新因子接口验证结果

本轮没有调用真实付费 API，只做代码级审计。

| 因子 | 状态 | 代码证据 |
|---|---|---|
| LTH SOPR | config_only | `config/data_catalog.yaml` 有登记；`glassnode.py` 无 fetch 方法 |
| STH SOPR | config_only | 同上 |
| RHODL Ratio | not_found | collector / scheduler / catalog 当前有效项未找到 |
| Percent Supply in Profit | not_found | 未找到 |
| Percent Supply in Loss | not_found | 未找到 |
| Liveliness | config_only | catalog delayed；collector 未实现 |
| Hash Ribbon | config_only | catalog delayed；collector 未实现 |
| Active Addresses | config_only | catalog delayed；collector 未实现 |
| Exchange Balance | not_found | 未找到 |
| LTH Net Position Change | not_found | 当前只有 LTH supply change |
| Exchange Net Position Change | not_found | 当前只有 exchange netflow |
| Reserve Risk | deprecated_candidate | Sprint 1.7 删除，当前 collector 无方法 |
| Puell Multiple | deprecated_candidate | Sprint 1.7 删除，当前 collector 无方法 |
| CoinGlass Net Position | collector_exists_not_scheduled | `fetch_net_position_history()` 存在；当前 scheduler 未纳入 |
| Liquidation Heatmap / Levels | not_found | 当前只有 liquidation history |
| Futures Basis / Premium | deprecated_candidate | basis / put-call 历史退场，collector 当前无 |
| Options Skew / IV | not_found | 未找到 |
| Stablecoin Supply / Exchange Flow | not_found | 未找到；SSR 已有但不是同一因子 |
| US2Y | not_found | `context_builder.py` 支持字段名，FRED collector 无 series |
| Fed Funds Rate | deprecated_candidate | FRED collector 当前无 DFF，历史删除 |
| Real Yield | not_found | 未找到 |
| CPI / Core CPI | partial | local calendar 有事件日期，未采集数值 |
| Unemployment | deprecated_candidate | 当前 FRED collector 未采集，历史删除 |
| M2 | not_found | context 预留，collector 未实现 |
| Fed Balance Sheet | not_found | context 预留，collector 未实现 |

## 9. Layer A 输出 schema

标准落点：

```json
{
  "layer_a_spot_strategy": {
    "enabled": true,
    "a1_cycle_stage": {},
    "a2_onchain_macro": {},
    "a3_spot_opportunity": {},
    "a4_spot_risk": {},
    "a5_spot_adjudicator": {},
    "validator": {
      "passed": true,
      "violations": [],
      "warnings": []
    },
    "unavailable_factors": [],
    "model_notes": []
  }
}
```

实现位置：

- normalize：`src/ai/spot_strategy_normalizer.py`
- full_state_json 写入：`src/pipeline/_orchestrator_mapper.py`
- API 归一化透传：`src/web_helpers/normalize_state.py`

## 10. Spot Validator 规则

实现位置：`src/ai/spot_validator.py`

硬违规：

- 输出做空 / hedge / trend_short。
- 输出 Layer B 的 A/B/C/NONE、opportunity_grade、execution_permission。
- 输出 Layer B 交易字段：thesis、entry、stop_loss、take_profit、position_size、leverage、trade_plan、virtual_account。
- `spot_action` 不在五类动作内。
- aggressive_buy / aggressive_sell 缺少 supporting_evidence 或 opposing_evidence。
- 缺 human_summary。
- 缺 what_would_change_mind。
- 输入有明显缺失但输出没有 data_quality_notes。

软警告：

- aggressive_buy 但风险 high / critical。
- aggressive_sell 但阶段是 bear_bottom / accumulation。
- dca_buy 但风险 critical。
- scale_out 没有过热 / 派发 / 宏观恶化证据。
- 输出单边、没有 opposing_evidence。
- 数据缺失多但 confidence=high。
- 输出看起来像 Layer B 波段交易计划。

## 11. Orchestrator 接入方式

接入位置：`src/ai/orchestrator.py`

执行方式：

1. 原有 Layer B L1-L5 + Master + Validator 按原顺序执行。
2. Layer B 结果完成后，读取 `context["layer_a_spot_context"]`。
3. 如果有 context，执行 A1 → A2 → A3 → A4 → A5。
4. normalize + spot validator。
5. 写入 `result["layer_a_spot_strategy"]`。

重要边界：

- Layer A 不写入 `result["layers"]`。
- Layer A 不进入 Layer B Validator。
- Layer A 失败不修改 Layer B status。
- Layer A 不参与 thesis persistence。
- Layer A 不参与 virtual account。

## 12. full_state_json 存储方式

新增字段写入：

```json
{
  "schema_version": "v14",
  "layers": {},
  "layer_a_spot_strategy": {},
  "validator": {},
  "status": "ok"
}
```

旧 run 没有该字段时，`normalize_state` 返回 `layer_a_spot_strategy: null`，网页显示：

> 暂无大周期策略，本 run 尚未记录 Layer A 输出。

## 13. API 返回方式

当前 `/api/strategy/current` 使用 `src/web_helpers/normalize_state.py`。

本轮做法：

- `normalize_state()` 对 v14 state 透传 `layer_a_spot_strategy`。
- API 不破坏 Layer B 原字段。
- 旧 run 无 Layer A 时返回 `null`，前端不报错。

## 14. 网页“大周期策略”模块实现

实现文件：

- `web/index.html`
- `web/assets/app.js`

位置：

- `region-1` AI 策略建议之后；
- 虚拟账户 / 当前 thesis / 挂单模块之前；
- Layer B “五层分析”之前。

展示内容：

- 顶部摘要：大周期阶段、策略、置信度、风险。
- A1-A5 卡片：标题、主结论、badge、一句人话 summary、查看详细。
- 详细区展示支持证据、反方证据、数据质量备注。

UI 边界：

- 复用 `audit-card`、`stat-label`、badge、现有字体字号。
- 不引入新前端库。
- 不显示原始 JSON。
- 不改变 Layer B 五层分析样式。

## 15. 删除清单 / 废弃清单

| 类型 | 对象 | 处理 | 原因 | 测试覆盖 |
|---|---|---|---|---|
| 旧说明对齐 | `README.md` 中单层系统描述 | 已更新为双层描述 | 避免代码已有 Layer A 但 README 仍只描述单层双向波段 | 静态审查 + diff check |
| 旧 Layer A 实验代码 | 全仓 `rg "layer_a|spot_cycle|大周期策略"` | 未发现可删除旧实现 | 本轮是首次正式新增 Layer A；无旧入口冲突 | rg 检查 |
| Layer B C 级语义 | Master / Validator / persistence 的既有差异 | 本轮不改行为，只在本报告标记 | 用户要求不借 Layer A 改 C 级行为 | Layer B 回归测试通过 |

本轮未删除代码文件。原因：没有发现可安全删除的旧 Layer A 逻辑；所有新增为独立模块。已检查无 Layer A 旧实现冲突。

## 16. 测试命令和结果

| 命令 | 结果 |
|---|---|
| `uv run pytest -q tests/test_layer_a_spot_context_builder.py tests/test_layer_a_spot_validator.py tests/test_layer_a_spot_normalize.py` | 8 passed |
| `uv run pytest -q tests/test_layer_a_orchestrator_integration.py` | 1 passed |
| `uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py` | 114 passed |
| `uv run pytest -q tests/test_jobs_weekly_review_and_health_check.py tests/test_weekly_review_input_builder.py tests/test_weekly_review_analyst.py` | 68 passed |
| `uv run pytest -q tests/pipeline/test_orchestrator_mapper.py tests/ai/test_orchestrator.py` | 48 passed |
| `git diff --check` | 通过 |

## 17. 是否触碰高风险交易逻辑

没有。

- 未改真实交易。
- 未新增真实交易接口。
- 未改仓位 sizing。
- 未改止损止盈。
- 未改开仓、平仓、反手规则。
- 未改 Layer B Master 交易硬约束。
- 未改 Layer B Validator 交易约束。
- 未改 Layer B thesis 创建规则。
- 未改 scheduler 主裁决时间。
- 未启用 position_health_check。

## 18. 是否影响 Layer B

不影响 Layer B 交易行为。

具体保证：

- Layer A 输出不进入 `layers`。
- Layer A 不读 L3 C 级机会作为触发。
- Layer A 不禁止 Layer B 开仓。
- Layer B 的 L1-L5、Master、Validator 原流程保持。
- Layer B C 级机会行为保持 Layer B 内部逻辑，本轮未改变。

## 19. 是否影响虚拟账户

不影响。

Layer A 不进入 virtual account。虚拟账户仍只管理 Layer B。

## 20. 是否影响真实交易

不影响。

本系统仍是交易辅助系统，不是自动下单机器人。本轮没有新增真实交易接口，也没有触碰 `.env`、API key、token、secret。

## 21. 风险和未完成

| 风险 / 未完成 | 说明 |
|---|---|
| Layer A 尚未经过真实生产 run 验证 | 本轮完成代码闭环和单测，未部署生产运行 |
| 未接入候选因子较多 | 已进入 `unavailable_factors`，不会被伪造成中性 |
| A1-A5 prompt 为新增 prompt | 已写边界，但未来仍需根据真实输出做审计 |
| C 级机会语义仍存在旧差异 | 本轮按用户要求不改变 C 级行为，只标记 |
| 1M 结构未可用 | 当前项目没有 1M K 线 collector / 入库路径 |
| README 已对齐双层定位 | 这是说明文档变化，不是交易逻辑变化 |
| 工作区 `uv.lock` 有既有改动 | 本轮未触碰、未提交 |

## 22. 下一步建议

1. 跑一次手动 pipeline，观察真实 `layer_a_spot_strategy` 输出质量。
2. 用 2-4 周周报审计 Layer A 是否过度激进。
3. 下一轮优先补低成本 FRED 因子：US2Y、Fed Funds、CPI/Core CPI、Unemployment、M2/Fed balance sheet。
4. 再评估 Glassnode：LTH SOPR、STH SOPR、Percent Supply Profit/Loss、RHODL。
5. 单独做 Layer B C 级机会语义裁决，不要混在 Layer A 里改。

## 23. 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ |
| GitHub push(commit hash:xxxx) | 待本报告随代码提交后执行；最终 hash 记录在对话和 audit bundle metadata |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | 待用户执行 |
