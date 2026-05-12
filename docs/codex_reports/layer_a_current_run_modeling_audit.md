# layer_a_current_run_modeling_audit

生成时间：2026-05-12  
任务性质：只读建模审查  
一句话结论：当前 Layer A 输出 `accumulation + dca_buy` 基本合理，但证据不足以支撑 `high confidence`；最大建模风险是数据覆盖不足时缺少更硬的 confidence cap，而不是 UI 或 Layer B 边界问题。

## 1. 任务目标

本轮目标是基于生产服务器最新一次 `strategy_run`，审查 Layer A「大周期策略」当前真实输出是否符合双层 BTC 策略系统的最终建模方向。

本轮只回答建模问题：

- A1-A5 现在的判断有没有站得住；
- `accumulation / 底部吸筹` 是否合理；
- `dca_buy / 分批买入` 是否合理；
- 缺失因子是否影响判断；
- Layer A 是否污染 Layer B，或被 Layer B 反向污染；
- 下一步应该优先补什么。

## 2. 本轮是否改代码

没有改代码，只读建模审查。

本轮没有修改：

- Layer A 代码；
- Layer A prompt；
- Layer B L1-L5 / Master / Validator / thesis / 虚拟账户；
- Layer B C 级机会行为；
- 仓位、止损、止盈、开仓、平仓、反手规则；
- 网页；
- 数据库；
- `.env`、API key、token、secret。

本轮只新增本报告文件：

- `docs/codex_reports/layer_a_current_run_modeling_audit.md`

## 3. 读取文件

按任务要求和项目规则，本轮读取 / 复核了：

| 文件 | 用途 |
|---|---|
| `AGENTS.md` | 项目边界、双层原则、安全规则 |
| `README.md` | 当前双层系统定位 |
| `docs/codex_reports/dual_layer_factor_inventory_and_data_source_audit.md` | Layer A/B 因子盘点和接口状态 |
| `docs/codex_reports/layer_a_spot_cycle_strategy_full_model_and_implementation.md` | Layer A 最终建模设计和实现说明 |
| `docs/codex_reports/layer_a_spot_validator_false_positive_fix.md` | Spot Validator 边界说明误判修复 |
| `docs/codex_reports/deploy_and_verify_layer_a_on_production_web.md` | 生产部署和最新 run 验证结果 |
| `src/ai/spot_cycle_context_builder.py` | Layer A 输入上下文构建 |
| `src/ai/spot_strategy_normalizer.py` | Layer A 输出归一化 |
| `src/ai/spot_validator.py` | Layer A 专用 validator |
| `src/ai/agents/prompts/a1_spot_cycle.txt` | A1 大周期阶段 prompt |
| `src/ai/agents/prompts/a2_onchain_macro.txt` | A2 链上与宏观 prompt |
| `src/ai/agents/prompts/a3_spot_opportunity.txt` | A3 现货策略机会 prompt |
| `src/ai/agents/prompts/a4_spot_risk.txt` | A4 现货风险 prompt |
| `src/ai/agents/prompts/a5_spot_adjudicator.txt` | A5 大周期主裁 prompt |
| `config/data_catalog.yaml` | 因子登记和历史删除项 |
| `config/data_sources.yaml` | 当前数据源配置 |
| `src/data/collectors/glassnode.py` | Glassnode collector 支持情况 |
| `src/data/collectors/coinglass.py` | CoinGlass collector 支持情况 |
| `src/data/collectors/fred.py` | FRED collector 支持情况 |
| `src/ai/orchestrator.py` | Layer A 接入方式 |
| `src/pipeline/state_builder.py` | `layer_a_spot_context` 构建位置 |
| `src/pipeline/_orchestrator_mapper.py` | `full_state_json.layer_a_spot_strategy` 持久化位置 |

## 4. 实际运行命令

本轮运行了以下只读命令：

```bash
git status --short
git log -3 --oneline
rg / sed 读取指定代码、prompt、配置和报告
ssh ubuntu@124.222.89.86 'cd /home/ubuntu/btc_swing_system && .venv/bin/python - <<PY ... PY'
uv run python - <<PY ... PY
git diff --check
```

说明：

- 没有跑新的 pipeline。
- 没有重启服务。
- 没有执行 sudo。
- 没有读取 `.env`。
- 没有查询或输出任何 API key / token / secret。

## 5. 最新 run 摘要

生产服务器目录：

```text
/home/ubuntu/btc_swing_system
```

最新 `strategy_run` 摘要：

| 字段 | 值 |
|---|---|
| run_id | `f99ce07de5af4467aad890933750f4d4` |
| generated_at_utc | `2026-05-12T06:26:17Z` |
| BTC price | `81175.9` |
| has_layer_a_spot_strategy | `true` |
| A1 cycle_stage | `accumulation` |
| A1 confidence | `high` |
| A2 onchain_macro_stance | `bullish` |
| A2 confidence | `high` |
| A3 preferred_action_candidate | `dca_buy` |
| A3 confidence | `high` |
| A4 spot_risk_level | `moderate` |
| A4 confidence | `high` |
| A5 spot_action | `dca_buy` |
| A5 cycle_stage | `accumulation` |
| A5 confidence | `high` |
| validator.passed | `true` |
| validator.violations | `[]` |
| validator.warnings | `['high_confidence_with_many_missing_factors']` |

重要说明：

`full_state_json` 当前保存了 `layer_a_spot_strategy` 输出和 `context_summary`，但没有完整保存 `spot_cycle_context` 输入。为审查输入覆盖，本轮用生产数据库只读重建了一份 Layer A 输入上下文摘要。该重建上下文用于审计当前数据覆盖，不代表当时 run 的逐字输入快照。

## 6. A1 审查：大周期阶段

### 6.1 A1 为什么判断 accumulation

A1 给出的核心逻辑是：

- BTC 价格约 `81175.9`，距离 ATH 回撤约 `-35%`；
- 价格高于 `200W MA`，但略低于 `200D MA`；
- MVRV Z `0.9436`、MVRV `1.5056`、NUPL `0.3358`，远未进入牛市过热区；
- LTH supply 90d 变化约 `+2.73%`，解释为长期持有者仍在积累；
- STH MVRV 接近 `1.0`，解释为短期持有者接近成本线；
- ETF 30 天净流入约 `$3.497B`，7 天净流入约 `$1.288B`；
- 交易所 30 天净流出约 `-46281 BTC`；
- BTC dominance `60.16%`，资金集中在 BTC。

用小白话说：A1 认为“价格不像牛顶那么贵，长期资金还在拿币，ETF 还在买，所以更像吸筹，而不是顶部派发”。

### 6.2 支持证据是否足够

支持 `不是顶部 / 可以积累` 的证据比较充分：

- MVRV Z 不高；
- NUPL 未到狂热；
- ETF 流入强；
- 交易所净流出；
- 价格仍高于 200W MA；
- LTH supply 增长。

但支持“明确就是 accumulation / 底部吸筹”的证据没有那么铁：

- 价格已经离 200W MA 较远，不是传统意义的深熊底部；
- 52 周变化仍为负，说明大周期恢复还不稳；
- 价格仍低于 200D MA，中期趋势尚未完全翻强；
- 宏观数据延迟 4 天，且强美元、高利率仍是逆风。

### 6.3 反方证据是否列出

A1 列出了较多反方证据，包括：

- 价格低于 200D MA；
- 距 ATH 回撤仍深；
- 52 周表现为负；
- STH realized price 高于当前价格；
- DXY 强、US10Y 高；
- OI 偏高；
- CPI 事件在即。

这说明 A1 不是完全单边看多。

### 6.4 有没有把 Layer B 波段逻辑误当大周期逻辑

有轻微混入。

A1 主要依据是大周期链上、ETF、200D/200W，这符合 Layer A。但它也引用了 funding、OI、long/short ratio、CPI 事件窗口等偏中短期风险因子。这些因子可以作为背景风险，但不应过度参与“cycle_stage”的阶段定性。

当前还没有严重越界，但建议后续让 A1 更聚焦周期因子，把衍生品和事件风险更多交给 A4。

### 6.5 accumulation 是否合理

结论：基本合理但证据不足。

更准确的表达是：

```text
当前不像牛市末期，也不像深熊底部；
更像“估值修复中的吸筹 / 早期恢复交界区”。
```

`accumulation` 可以接受，但 `early_bull`、`bear_transition`、`unclear` 也都有解释空间。

### 6.6 是否偏乐观或偏保守

偏乐观的地方：

- `confidence=high` 偏高；
- 把 `accumulation` 说得太确定；
- 对缺失 RHODL、Reserve Risk、Puell、Percent Supply in Profit/Loss、HODL Waves、Exchange Balance、US2Y、M2 等因子的影响低估了。

偏保守的地方：

- 没有直接给 `aggressive_buy`，而是给 `dca_buy`，这一点是合理保守。

## 7. A2 审查：链上与宏观

### 7.1 链上证据是否足够

链上证据能支持“估值不贵、适合观察或分批积累”：

- MVRV Z：`0.9436`
- MVRV：`1.5056`
- NUPL：`0.3358`
- Realized Price：`54276.13`
- LTH Realized Price：`45340.40`
- STH Realized Price：`82014.36`
- LTH Supply：`14839870.31`
- aSOPR：`1.0066`
- Exchange Netflow 30d sum：`-46281.84`

但链上证据还不足以支撑 `high confidence`：

- HODL Waves 缺失；
- STH supply 90d 变化缺失；
- LTH/STH SOPR 缺失；
- Exchange Balance 缺失；
- Percent Supply in Profit/Loss 缺失；
- RHODL / Reserve Risk / Puell 缺失。

### 7.2 宏观证据是否支持 dca_buy

宏观不是强支持，只能算“没有明显否决”。

当前宏观数据：

- DXY：`118.0392`
- US10Y：`4.38`
- VIX：`17.19`
- Nasdaq：`26247.08`
- BTC-Nasdaq 60d corr：`0.4489`
- 未来 168 小时内有 CPI 事件。

A2 将宏观描述为“中性偏紧，但风险偏好未崩溃”，这个判断合理。

但要注意：DXY 强、10Y 高、本周 CPI 事件在即，这不支持强买，只支持“分批、慢一点、别追高”。

### 7.3 哪些已有数据

当前可用 Layer A 主因子包括：

- MVRV Z；
- MVRV；
- NUPL；
- Realized Price；
- LTH/STH Realized Price；
- LTH/STH MVRV；
- LTH Supply；
- STH Supply；
- aSOPR；
- CDD；
- SSR；
- Exchange Netflow；
- ETF Flow；
- BTC Dominance；
- 200D / 200W；
- ATH drawdown；
- DXY；
- US10Y；
- VIX；
- Nasdaq；
- BTC-Nasdaq correlation；
- funding / OI / long-short / liquidation。

### 7.4 哪些关键因子缺失

当前缺失或未稳定接入的关键因子包括：

- RHODL Ratio；
- Reserve Risk；
- Puell Multiple；
- Percent Supply in Profit；
- Percent Supply in Loss；
- LTH SOPR；
- STH SOPR；
- HODL Waves 当前值缺失；
- Exchange Balance；
- LTH Net Position Change；
- Exchange Net Position Change；
- US2Y；
- Real Yield；
- Fed Funds Rate；
- CPI / Core CPI 数值；
- M2；
- Fed Balance Sheet。

### 7.5 A2 是否真正完成链上 + 宏观综合

基本完成了综合，不只是堆指标。

它把估值、持有人行为、ETF、交易所流量、美元、利率、VIX、Nasdaq、CPI 事件串起来了。

问题是：综合后的 `confidence=high` 不够克制。数据缺口明显时，A2 应该更接近 `medium`。

## 8. A3 审查：现货策略机会

### 8.1 为什么支持 dca_buy

A3 支持 `dca_buy` 的理由是：

- 估值不高；
- 长期资金似乎仍在积累；
- ETF 流入强；
- 交易所净流出；
- 短期持有者接近成本线；
- 价格高于 200W MA；
- 宏观和技术面又没有好到可以重仓。

这个逻辑是合理的。

### 8.2 是否错误使用 Layer B A/B/C

没有发现。

Layer A 输出中没有 `A/B/C/NONE` 机会等级，也没有 `opportunity_grade`、`execution_permission` 字段。

### 8.3 是否把 Layer B 波段机会迁移到 Layer A

没有明显迁移。

不过 A3 的 `suggested_plan` 写了较具体的价格区间，例如 `$78,000-$80,000`、`$85,000` 等。它没有输出 `entry` 字段，也没有创建 trade plan，所以没有硬违规。

但从建模洁癖角度看，这有一点像“准入场计划”。后续可以考虑把 Layer A 的计划表达改成更大周期的话术，例如“回调分批”“突破后减少等待”，少写精确价格带，避免和 Layer B entry 语义混淆。

### 8.4 是否清楚区分五类动作

清楚。

A3 对为什么不是：

- `aggressive_buy`
- `hold`
- `scale_out`
- `aggressive_sell`

都给出了理由。

### 8.5 dca_buy vs hold

当前证据支持 `dca_buy` 胜过纯 `hold`，但不是强压倒。

支持 `dca_buy`：

- 估值不热；
- ETF 流入；
- 交易所净流出；
- LTH 供应增长；
- 价格高于 200W。

支持 `hold`：

- 价格低于 200D；
- 宏观偏紧；
- CPI 事件临近；
- 缺失因子较多；
- OI 偏高。

所以最合理的动作不是强买，而是“小步分批”。这和 A3 结论一致。

### 8.6 是否足够排除 aggressive_buy / scale_out / aggressive_sell

足够排除 `aggressive_buy`：

- 技术面未突破 200D；
- CPI 临近；
- DXY/US10Y 不友好；
- OI 偏高；
- 缺失因子较多。

足够排除 `scale_out / aggressive_sell`：

- 链上估值未过热；
- NUPL 未狂热；
- ETF 流入；
- 交易所净流出；
- 没有 LTH 分发证据。

## 9. A4 审查：现货风险

### 9.1 当前风险等级

A4 当前输出：

```text
spot_risk_level = moderate
confidence = high
```

### 9.2 风险考虑是否充分

A4 覆盖了主要风险：

- 高位追买风险：有，提到不能追高、低于 200D；
- 转熊风险：有，提到 200W 破位和长期趋势失效；
- 宏观风险：有，提到 DXY、US10Y、CPI；
- 链上分发风险：部分有，提到 LTH supply 转负、ETF 流出；
- 数据缺失风险：有，列出宏观延迟、HODL Waves、Exchange Balance、M2 等缺失。

### 9.3 A4 是否独立于 A2/A3

基本独立，但有复述。

A4 不只是复述 A2/A3，它额外做了风险控制、下行风险、失效观察清单。

但它的问题是：

- 仍然把很多价格位写得很细；
- `confidence=high` 与“宏观延迟 + 多项关键因子缺失”不匹配；
- 风险等级 `moderate` 可以接受，但若考虑 Layer B L4 同 run 为 `elevated`，A4 至少应强调“现货无杠杆所以 moderate，但短期市场风险 elevated”。

### 9.4 A4 给 A5 的约束是否清楚

清楚。

A4 明确约束了：

- 不要一次性重仓；
- CPI 前后放慢；
- ETF 连续流出则暂停；
- 200W 破位则重评；
- 宏观恶化则暂停。

这对 A5 形成了足够的“只适合 dca_buy，不适合 aggressive_buy”的约束。

## 10. A5 审查：大周期主裁

### 10.1 为什么最终给 dca_buy

A5 的综合逻辑是：

- A1：周期像积累；
- A2：链上偏多，宏观中性偏紧；
- A3：适合分批买，不适合强买；
- A4：风险中等，不能追高和重仓。

所以最终 `dca_buy` 合理。

### 10.2 A5 是否像最终交易员建议

部分像。

它清楚说了：

- 当前做什么：分批买入；
- 不做什么：不一次性重仓、不追高、不用杠杆；
- 为什么不是强买：技术、宏观、事件风险；
- 什么会改变判断：200W、ETF、LTH supply、MVRV Z、CPI 等。

但它还不够“最终主裁式简洁”。现在文字偏长，重复 A1-A4 较多。作为网页展示，小白会看懂，但交易员味道还可以更强：更短、更明确、更少指标堆叠。

### 10.3 是否有 Layer B 波段逻辑污染

没有严重污染。

没有出现：

- 做空；
- thesis；
- entry；
- stop_loss；
- take_profit；
- A/B/C/NONE；
- 虚拟账户字段。

轻微风险是：`suggested_plan` 中出现具体价格区间，容易让用户以为这是 Layer B 式入场区。当前 validator 不判违规是合理的，但下一步可以考虑把 Layer A 价格表达改成“大周期观察位”，而不是“入场位”。

### 10.4 A5 confidence 是否合理

不合理，偏高。

`dca_buy` 合理，但 `confidence=high` 不合理。

原因：

- `unavailable_factors` 有 25 项；
- validator 已经提示 `high_confidence_with_many_missing_factors`；
- 宏观数据延迟 4 天；
- HODL Waves / LTH-STH SOPR / Exchange Balance / Percent Supply Profit-Loss / RHODL / Reserve Risk / Puell 等关键周期因子缺失；
- 价格仍在 200D 下方；
- CPI 事件临近。

更合理的置信度：`medium`。

## 11. 数据覆盖和缺失因子影响

### 11.1 当前可用 Layer A 主因子

| 类别 | 可用因子 |
|---|---|
| 链上估值 | MVRV Z、MVRV、NUPL、Realized Price、LTH/STH Realized Price、LTH/STH MVRV |
| 持有人行为 | LTH Supply、STH Supply、LTH Supply 90d change、aSOPR、CDD、SSR |
| 交易所 / 资金流 | Exchange Netflow、Exchange Netflow 30d sum、ETF Flow、ETF 7d/30d sum |
| 价格结构 | 当前价格、ATH drawdown、200D、200W、13w/52w change |
| 宏观 | DXY、US10Y、VIX、Nasdaq、BTC-Nasdaq correlation、CPI event calendar |
| 辅助风险 | Funding、Funding Z、OI、OI Z、Long/Short Ratio、Liquidation Total、BTC Dominance |

### 11.2 当前缺失 Layer A 主因子

| 类别 | 缺失因子 | 影响 |
|---|---|---|
| 顶底判断 | RHODL、Reserve Risk、Puell、Percent Supply in Profit/Loss | 高 |
| 持有人行为 | LTH SOPR、STH SOPR、HODL Waves 当前值、LTH Net Position Change | 中高 |
| 交易所供应 | Exchange Balance、Exchange Net Position Change | 中高 |
| 宏观流动性 | US2Y、Real Yield、Fed Funds、M2、Fed Balance Sheet | 中高 |
| 通胀就业 | CPI/Core CPI 数值、Unemployment | 中 |
| 衍生品结构 | Futures Basis/Premium、Options IV/Skew、Liquidation Heatmap | 中 |

### 11.3 缺失因子对本次 dca_buy 的影响等级

总体影响：`medium-high`

解释：

- 对 `dca_buy` 这个动作本身：影响中等。已有 MVRV/NUPL/ETF/交易所净流出足以支持“可以分批，不要强买”。
- 对 `accumulation` 这个阶段：影响中高。缺 RHODL、Reserve Risk、Puell、Percent Supply Profit/Loss 会削弱顶底定位。
- 对 `high confidence`：影响高。当前不应 high。

### 11.4 是否应该有 confidence cap

应该。

建议后续建模规则：

```text
如果 unavailable_factors 数量较多，或关键组缺失超过阈值，
A1/A2/A5 confidence 最高只能 medium。
```

当前 validator 只给 warning，没有把 confidence 直接压低。这是本轮审查发现的最大建模风险。

## 12. Layer A / Layer B 边界审查

### 12.1 Layer A 是否独立于 Layer B

是。

代码路径显示：

- `SpotCycleContextBuilder` 构建独立 `layer_a_spot_context`；
- Orchestrator 在 Layer B Master/Validator 后运行 Layer A；
- `layer_a_spot_strategy` 不进入 `layers`；
- `layer_a_spot_strategy` 不进入 thesis persistence；
- `layer_a_spot_strategy` 不进入 virtual account。

### 12.2 是否读取 Layer B C 级机会

没有发现。

Layer A 输入构建没有读取 L3 `opportunity_grade` 作为触发。

### 12.3 是否输出 A/B/C/NONE

没有。

### 12.4 是否输出 short / thesis / entry / stop_loss / take_profit

没有字段级输出。

文本中有“不要做空 / 不创建 thesis / 不用杠杆”等边界说明，这是正确的禁止性说明，不是行动建议。

注意：A3/A5 有具体价格区间的 DCA 建议，当前不算 `entry` 字段，但后续建议改成更大周期的“观察区域”表达，避免用户误解成 Layer B 入场单。

### 12.5 虚拟账户是否仍只管理 Layer B

是。

本轮没有发现 Layer A 进入虚拟账户。

### 12.6 Layer B 当前结论与 Layer A 是否一致

大方向一致，节奏不同。

Layer B 当前摘要：

| 层 | 当前输出 |
|---|---|
| L1 | `transition_up` |
| L2 | `phase=early`，偏多 |
| L3 | `B`，`cautious_open` |
| L4 | `elevated`，risk_score `58`，position_cap_multiplier `0.55` |
| L5 | `supportive` |
| Master | 倾向看多，但只允许回踩埋伏，不追涨 |

Layer A 是：

```text
大周期现货：分批买入
```

两者不冲突。Layer B 是波段仓，所以更在意短期追涨、回踩、止损、仓位；Layer A 是现货大周期，所以可以在估值不热时分批积累。

## 13. 当前判断是否合理

明确判断：

```text
基本合理但证据不足。
```

拆开看：

- `dca_buy`：合理；
- `accumulation`：可接受，但不应太确定；
- `high confidence`：不合理，应该降为 `medium`；
- `validator passed`：合理，因为没有越界硬违规；
- `validator warning`：非常关键，说明系统已经发现“缺失因子较多但置信度偏高”。

## 14. 当前最大建模风险

最大风险类别：

```text
context 构建不足 + normalizer / validator 缺少强制 confidence cap
```

不是 UI 问题，也不是 Layer A/B 边界问题。

具体表现：

1. `unavailable_factors` 多达 25 项；
2. A1/A2/A3/A4/A5 全部给 high confidence；
3. validator 只 warning，不压低 confidence；
4. prompt 已提醒“缺失很多不应 high”，但 AI 仍输出 high；
5. 说明单靠 prompt 不够，需要 normalizer / validator 层有更明确的置信度上限。

## 15. 下一步路线建议

### P0：必须马上处理，影响模型正确性

1. 增加 Layer A confidence cap。

建议规则：

- 如果 `unavailable_factors` 超过一定数量，A1/A2/A5 最高 `medium`；
- 如果关键组缺失，例如顶底因子、持有人行为、宏观流动性缺失过多，最高 `medium`；
- 如果宏观数据 stale 且有高影响事件临近，A5 最高 `medium`；
- 如果 validator 出现 `high_confidence_with_many_missing_factors`，normalizer 或 post-process 应把 `confidence=high` 降为 `medium`，并记录 `confidence_capped_by_data_coverage`。

2. 保存 Layer A 输入上下文快照摘要。

当前 `full_state_json` 没保存完整 `spot_cycle_context`，导致审查只能重建当前上下文。建议保存轻量版 input snapshot，不保存大 dataframe：

- available factor actual_value/status/as_of；
- unavailable_factors；
- data_quality_notes；
- source freshness；
- series tail 摘要。

这会显著提高以后复盘可信度。

### P1：近期处理，提升判断质量

1. 补优先级最高的 Layer A 因子：

- Percent Supply in Profit/Loss；
- RHODL；
- LTH SOPR / STH SOPR；
- Exchange Balance；
- US2Y；
- Fed Funds；
- M2 / Fed Balance Sheet；
- CPI/Core CPI 数值。

2. 调整 A1 prompt 职责重心。

A1 应更聚焦：

- 大周期估值；
- 长期价格结构；
- 持有人结构；
- 资金流。

Funding/OI/CPI 事件可以作为背景，但不要过度决定 `cycle_stage`。

3. 调整 A5 输出风格。

A5 应更像最终主裁：

- 短一点；
- 更像“现在怎么做”；
- 少重复 A1-A4；
- 少写过细价格位，避免像 Layer B entry plan。

### P2：框架稳定后处理的小问题

以下属于已知小问题，后续处理即可，本轮不展开修：

- Layer A 网页文字偏长；
- A1-A5 摘要不够交易员式简洁；
- 支持 / 反方证据和数据质量备注默认折叠；
- A5 主裁需要更像最终建议；
- Layer B C 级机会 prompt / persistence 语义不一致需后续对齐。

## 16. 风险和不确定项

1. 本轮没有跑新 pipeline，只审查最新已生成 run。
2. `full_state_json` 没有完整保存 Layer A 输入上下文，本轮重建上下文来自当前生产 DB，可能与 run 当时输入有轻微时间差。
3. 没有调用外部付费 API，无法验证缺失因子的外部可用性，只按代码和配置审计。
4. 未登录公网 Basic Auth 页面，本轮不审查网页登录后的视觉表现，因为用户明确要求不要继续 UI polish。
5. 本轮报告是建模建议，不自动改变任何策略参数或交易行为。

## 17. 删除清单 / 废弃清单

本轮无替代关系，无删除项。

原因：本轮为只读建模审查，只新增报告文件，没有新增实现，也没有替代旧逻辑。

## 18. 测试结果

本轮不改代码，不需要跑 pytest。

已运行：

```bash
git diff --check
```

结果：通过。

## 19. 是否触碰高风险区域

没有。

| 高风险区域 | 是否触碰 |
|---|---|
| Layer B L1-L5 / Master / Validator | 否 |
| Layer B thesis / 虚拟账户 | 否 |
| 仓位 / 止损 / 止盈 / 开平仓 / 反手 | 否 |
| 真实交易 / 真实下单 | 否 |
| `.env` / API key / token / secret | 否 |
| 数据库写入 / 清空 / migration | 否 |
| sudo / systemctl | 否 |

## 20. 部署状态四件事清单

| 项目 | 状态 |
|---|---|
| 是否部署 | N/A |
| 是否重启 | N/A |
| 是否影响生产任务 | 否 |
| 是否影响真实交易 | 否 |

AGENTS 部署清单口径：

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | N/A，本轮只读报告 |
| GitHub push | 待本报告提交后更新 |
| 服务器 git pull | N/A |
| 服务器 systemctl restart | N/A |
| 生产 DB 迁移 / 清污 | N/A |
| 生产健康检查 `/api/system/health` | N/A |

## 21. 总结给小白

这次 Layer A 没有“跑偏到实盘交易”，也没有污染 Layer B。它说“分批买入”这件事，本身是有道理的：估值不热、ETF 流入、交易所净流出、长期趋势没坏。

但它太自信了。

现在缺的关键数据还不少，尤其是顶底判断和宏观流动性相关因子。所以更稳妥的建模结论应该是：

```text
可以分批买，但不要 high confidence。
下一步先做 confidence cap 和输入快照保存，再谈更细 prompt 优化。
```
