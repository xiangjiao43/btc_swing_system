# 批 4 详细报告 — event_calendar.yaml + 3 prompt files

**日期**:2026-04-23
**Sprint**:1 前置工作 · 优化二 · 第 4 批
**对应建模文档章节**:§3.3(M38)、§3.4(M39)、§6.5、§6.6、§6.7、§6.8

---

## ⚠️ Triggers for Human Attention

> 以下是本批次需要人类注意的决策点,可直接摘录给审阅者。

### 1. 上线前必须人工补齐的 TBD 日期(go-live 阻塞项)

`config/event_calendar.yaml` 中共有 **47 个 `TBD_CHECK_FED_SITE` 占位日期**,覆盖:
- FOMC 决议 × 8 + 新闻发布会 × 5 + 会议纪要 × 7 = 20 条
- CPI × 12
- PPI × 12
- GDP_advance × 4(季度)

**为什么要占位**:我的知识截止是 2026-01,但 FOMC / CPI / PPI 的具体日期由美联储 / BLS 在年初公告,我无法可靠确认每个 2026 日期。建模文档明确(§3.4.4)要求"**每年 12 月人工更新下一年度的 FOMC / CPI / NFP 日程**",所以占位不是疏漏,是按纪律处理。

**阻塞影响**:运行时 `event_loader` 在加载时会跳过 `date == "TBD_CHECK_FED_SITE"` 的条目(详见 event_calendar.yaml 文件尾的 "文件完整性规则"),这意味着:
- 事件触发运行(M38)中的 `event_macro` 对这些事件**不会激活**
- 直到人工核对日期并填入,这些事件对 `EventRisk` 的贡献为零

**建议操作**:Sprint 1 落地前,用户或运维人工去 `federalreserve.gov/monetarypolicy/fomccalendars.htm` 和 `bls.gov/schedule/news_release/cpi.htm` 把 2026 年日期填齐。

### 2. NFP 12 条日期我替你算好了,但你可能想复核

NFP 是"每月第一个周五",这是**纯日历计算**,无需外部数据源。我用已知的 2026-01-01 为周四推算了全年:`2026-01-02 / 02-06 / 03-06 / 04-03 / 05-01 / 06-05 / 07-03 / 08-07 / 09-04 / 10-02 / 11-06 / 12-04`。理论上确定,但如果 BLS 对某个月有特殊调整(历史上 2020 年过独立日提前过发布),**以 BLS 官网为准**。我对 `2026-07-03` 条目加了 notes 提醒可能因独立日(7-4)调整。

### 3. 期权月度到期 12 条我填了具体日期,可能需要复核

Deribit 的 BTC 期权月度到期为"每月**最后**一个周五 UTC 08:00"。我按这个规则填了 12 条具体日期。但存在两个风险:
- **2026-12-25 恰逢圣诞节**:Deribit 历史上可能调整到前一周或特殊处理。我在 notes 里标了"人工核对 deribit.com"。
- 季度到期(3-27、6-26、9-25、12-25)我给了 `impact_level: 3` 而不是月度的 2,因季度到期对市场影响更大。

### 4. 2028 第 5 次减半日期用 `TBD_ESTIMATE_2028_APR` 占位

建模 §3.8.4 要求减半前后 6 个月 CyclePosition 置信度降一档。我登记了 2024-04-20(第 4 次,已发生),第 5 次用占位(`status: estimated`)。**估算值 2028 年 4 月附近**由平均出块 10 分钟推算,临近时(2027 Q4)需更新。建议运行时代码对 `status: estimated` 的减半事件走"宽口径"(前后各 8 个月而非 6 个月)处理。

### 5. User Prompt 模板的 3 处".format() 兼容性改造"

`config/prompts/adjudicator_user_template.txt` 与建模文档 §6.6 原文**有 3 处形式差异**(语义完全等价,但为了 Python `.format()` 可直接解析):

| 原文 | 本文件 | 理由 |
|---|---|---|
| `{current_lifecycle_json or "无"}` | `{current_lifecycle_json_or_none}` | Python `.format()` 不支持 `or` 语法;改由代码层在填充前做 None → "无" 转换 |
| `(共 {N} 张)` | `(共 {evidence_cards_count} 张)` | `{N}` 单字母易歧义,改成描述性名称,同时避免与"共"之前的空格冲突 |
| `第一个字符必须是 {。` | `第一个字符必须是 {{。` | `.format()` 要求字面量 `{` 需转义为 `{{` |

**建议操作**:运行时代码用 `str.format(**context)` 填充时,把 `current_lifecycle_json_or_none` 计算好(`ctx["current_lifecycle_json_or_none"] = lifecycle_json if lifecycle_json else "无"`)。如果最终选择 `string.Template` 或自定义占位符,把 `{{` 再改回 `{`。

### 6. 可能与建模意图不完全一致的点

**(a) 事件 impact_level 是我拍的**
建模 §3.8.6 只给了"事件类型权重"(FOMC=4 / CPI=3 等);没给 `impact_level`。我引入 1-5 `impact_level` 字段作为"人肉可读的严重度标签",只用于 UI 展示和人工核对。代码侧的评分仍走 `thresholds.event_risk_scoring.event_type_weights`。所以 impact_level 是**冗余元信息**,不影响决策。如果你觉得冗余,可以删掉;但我建议保留,因为 UI 展示日历时需要直观的重要程度排序。

**(b) event_type_mapping 包含 34 条,比你列的多**
你列了 8-9 条映射;我补到 34 条(加了 `Fed_official_speech / Powell_testimony / CPI_YoY / CPI_MoM / Core_PPI / Core_Retail_Sales / Michigan_Consumer_Sentiment / JOLTS / Initial_Jobless_Claims` 等常见别名)。理由:`EventCalendar` 的财经数据源(investpy / Trading Economics)可能用不同名称,多一点映射减少未来 `other` 兜底。

**(c) `GDP_advance` 我只登记了初值,没登记修正值/终值**
BEA 同一个季度会发 3 次(advance / second / third),其中 advance 影响最大。我只登记了 advance,其他两次留给人工按需补。建模 §3.4.2 把 GDP 放在"受夏令时影响"清单,没细分三版。

### 7. 建模文档里发现的"轻度不一致"

**§3.8.6 与 §3.4.2 对"FOMC 纪要"的归类不完全一致**:
- §3.4.2 把 "FOMC 会议纪要" 作为受夏令时影响事件
- §3.8.6 只列了 "FOMC=4"(未区分决议 vs 纪要)
- 我的处理:FOMC 族全部映射到 `fomc` type(weight 4),impact_level 区分决议=5 / 纪要=4,**评分按 thresholds 的 fomc=4 一视同仁**。这个处理可能让"纪要"的风险分数偏高。Sprint 1 时可考虑在 event_risk_scoring 里拆分 `fomc_decision` vs `fomc_minutes` 两个 type(但那是下个 batch 的事,不在本批 scope)。

---

## 1. 产出概览

| 文件 | 行数 | 大小 |
|---|---|---|
| `config/event_calendar.yaml` | 645 | 14.5 KB |
| `config/prompts/adjudicator_system.txt` | 89 | 3.8 KB |
| `config/prompts/adjudicator_user_template.txt` | 51 | 1.4 KB |
| `config/prompts/layer5_context.txt` | 56 | 2.1 KB |
| **小计** | 841 | 21.8 KB |

同批清理:
- 删除 `config/prompts/.gitkeep`(目录已有文件,占位符冗余)

---

## 2. `event_calendar.yaml` 结构

### 2.1 顶层分块

| 块 | 条目数 | 说明 |
|---|---|---|
| `event_type_mapping` | 34 | 事件名 → thresholds.yaml event_type_weights 的 type |
| `macro_events` | 60 | 美国宏观事件(America/New_York);含 47 TBD |
| `utc_events` | 14 | UTC 基准事件(funding / glassnode / options expiry) |
| `halving_events` | 2 | 第 4 次(2024)已发生 + 第 5 次(2028)估算占位 |

### 2.2 `macro_events` 类型分布

| 事件类型 | 条目数 | 日期状态 |
|---|---|---|
| CPI | 12 | 全 TBD |
| NFP | 12 | 全具体日期(算出) |
| PPI | 12 | 全 TBD |
| FOMC_decision | 8 | 全 TBD |
| FOMC_minutes | 7 | 全 TBD |
| FOMC_press_conference | 5 | 全 TBD |
| GDP_advance | 4 | 全 TBD |

### 2.3 `utc_events` 细节

- **binance_funding_rate_settlement**:`recurrence: daily, times_utc: [00:00, 08:00, 16:00]`,代码在 event_loader 里展开为每日 3 个事件实例。
- **glassnode_daily_update**:`times_utc: ["00:00"]`,notes 里说明实际数据通常 UTC 00:15-00:30 可用。
- **options_expiry_monthly**:12 条具体日期(每月最后一个周五 UTC 08:00)。季度到期(3/6/9/12)impact_level = 3,其他 = 2。

### 2.4 时区硬纪律落地

文件顶部注释列出 3 条:
1. 美国事件必须 `America/New_York`,不得用 UTC
2. UTC 事件必须 `UTC`,不得用 America/New_York
3. **绝不直接存北京时间**

event_calendar.yaml 文件尾部"PART 5 — 文件完整性规则"列出 3 项加载时校验规则,供 event_loader 实现。

---

## 3. 3 个 Prompt 文件

### 3.1 `adjudicator_system.txt`(89 行,3.8 KB)

建模 §6.5 的逐字复刻。包含:
- 身份定位段落
- 十条纪律(1-10)
- 核心决策原则(8 条 bullet)
- 身份定位再强调
- 输出格式说明

**编码**:UTF-8 无 BOM,纯文本,无 markdown 包装。
**占位符**:无(System Prompt 不含变量)。

### 3.2 `layer5_context.txt`(56 行,2.1 KB)

建模 §6.8 System Prompt 的逐字复刻,并**附加 Layer5Output schema 段**(建模文档里的 schema 示例)放在文件末尾,作为 AI 的输出格式参考。

### 3.3 `adjudicator_user_template.txt`(51 行,1.4 KB)

建模 §6.6 的模板,保留所有 `{...}` 占位符。与建模文档的 3 处形式差异见 Triggers 第 5 条。

所有占位符(`.format()` 风格):

```
{generated_at_bjt}, {reference_timestamp_utc}, {btc_price_usd},
{current_state}, {run_trigger}, {allowed_transitions},
{observation_category}, {data_freshness_summary},
{max_position_cap_pct}, {position_cap_composition},
{hard_invalidation_levels_formatted}, {protection_mode_active},
{flip_watch_effective_min_hours}, {flip_watch_effective_max_hours},
{active_direction_thresholds.long}, {active_direction_thresholds.short},
{l3_opportunity_grade}, {current_lifecycle_json_or_none},
{layer1_report_json}, {layer2_report_json}, {layer3_report_json},
{layer4_report_json}, {layer5_report_json},
{evidence_cards_count}, {evidence_cards_summary_list},
{recent_runs_digest}
```

共 **26 个占位符**。

---

## 4. 自主决策汇总

| 编号 | 决策 | 理由 |
|---|---|---|
| A | FOMC/CPI/PPI/GDP 日期用 `TBD_CHECK_FED_SITE` 占位 | 知识截止 2026-01,不敢虚构日期;建模 §3.4.4 明确"人工更新" |
| B | NFP 12 条用日历公式算好具体日期 | "每月第一个周五"是纯日历规则,可计算 |
| C | 期权月度到期 12 条用日历公式算好 | "每月最后一个周五 UTC 08:00"是 Deribit 公开规则 |
| D | 2028 减半用 `TBD_ESTIMATE_2028_APR` | 估算值,临近时人工更新 |
| E | 引入 `impact_level` 1-5 冗余元信息 | UI 展示需要直观重要度排序 |
| F | `event_type_mapping` 扩展到 34 条 | 覆盖财经数据源常见别名,减少 other 兜底 |
| G | `GDP_advance` 只登记初值 | 影响最大;second/third 人工按需补 |
| H | `binance_funding_rate_settlement` 用 `recurrence: daily` 不逐条展开 | 1095 条(3×365)太冗余,代码 loader 层展开 |
| I | user_template.txt 有 3 处 `.format()` 兼容性改造 | 让模板直接可用;语义等价 |
| J | `layer5_context.txt` 附加 schema 段 | AI 看到 schema 输出更稳;文件尾段不破坏原纪律段 |
| K | 删除 `config/prompts/.gitkeep` | 目录已有文件,占位符冗余 |

---

## 5. 建模覆盖自检

| 建模编号 | 是否落地 | 位置 |
|---|---|---|
| §3.3.1-3.3.3 事件触发机制 M38 | 间接 | base.yaml + event_calendar.yaml 提供数据,触发逻辑在代码 |
| §3.4.1 时间存储规则 M39 | ✓ | event_calendar.yaml 文件头 + PART 5 校验规则 |
| §3.4.2 受夏令时影响的事件 | ✓ | `macro_events` 全部用 America/New_York |
| §3.4.3 不受夏令时影响的事件 | ✓ | `utc_events`(funding + glassnode + options) |
| §3.4.4 事件日历数据来源 | ✓ | 文件头注释:"每年 12 月人工更新" |
| §3.4.5 实施要求 | 部分 | 文件结尾 PART 5 + 注释引用 `tests/timezone_dst_test.py` |
| §6.5 Adjudicator System Prompt 10 条纪律 | ✓ | adjudicator_system.txt 一字不漏 |
| §6.6 Adjudicator User Prompt 模板 | ✓ | adjudicator_user_template.txt(3 处兼容性改造) |
| §6.8 Layer 5 Macro System Prompt | ✓ | layer5_context.txt(附加 schema 段) |
| event_type_mapping(本批用户要求) | ✓ | event_calendar.yaml PART 1(34 条) |
| halving_events(本批用户要求) | ✓ | event_calendar.yaml PART 4 |

**未在本批覆盖(由后续批或代码落地)**:
- §6.3 AIAdjudicatorOutput schema(优化一 schemas.yaml 任务)
- §6.4 程序校验规则(Sprint 1 代码:src/decision/validator.py)
- `adjudicator_fewshot_*.json`(建模里提到的 few-shot 示例;建模文档未展开,留后续批)
- tests/timezone_dst_test.py 具体内容(Sprint 1)
- M31 evidence_cards 50 张上限(代码层约束)

---

## 6. 验证

```
config/event_calendar.yaml: OK
  top_keys: [event_type_mapping, macro_events, utc_events, halving_events]
  event_type_mapping entries: 34
  macro_events total: 60
    CPI: 12, NFP: 12, PPI: 12, FOMC_decision: 8,
    FOMC_minutes: 7, FOMC_press_conference: 5, GDP_advance: 4
  utc_events: 14
  halving_events: 2
  leaf_count: 491
```

三个 prompt 文件 UTF-8 无 BOM 通过,纯文本。

---

## 7. 当前 config/ 目录总览

批 4 完成后 `config/` 已包含 8 个 YAML + 3 个 TXT(prompt)+ 1 个空子目录(prompts 现在有文件了)。完整列表:

```
config/
├── ai.yaml                                (批 1 微调)
├── base.yaml                              (批 1)
├── data_catalog.yaml                      (批 2)
├── data_sources.yaml                      (批 1)
├── event_calendar.yaml                    (批 4)
├── layers.yaml                            (批 3)
├── state_machine.yaml                     (批 3)
├── thresholds.yaml                        (批 2)
└── prompts/
    ├── adjudicator_system.txt             (批 4)
    ├── adjudicator_user_template.txt      (批 4)
    └── layer5_context.txt                 (批 4)
```

**优化二"9 个 config 文件 + 3 个 prompt"整体框架完成**。

还需另起一批的:
- `schemas.yaml`(优化一,需要抽取建模文档全部字段定义)
- `adjudicator_fewshot_1.json` / `adjudicator_fewshot_2.json`(建模文档没展开 few-shot 示例内容)
- Sprint 1 代码落地

---
