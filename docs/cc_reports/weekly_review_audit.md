# weekly_review 现状审计(纯查不改)

**日期**:2026-05-09 BJT
**类型**:事实核查
**触发**:用户希望系统通过周复盘随时间优化(识别建模偏差 / 给具体改进
建议 / 对比 AI 判断 vs 实际走势)

## 结论一句话

**当前 weekly_review 处于「中等版」**:✅ 5 段 JSON(performance /
system_health / strategy_quality / **23 条 Validator 逐条激活率评估** /
adjustment_recommendations)+ 用户期望#2(具体改进建议)**部分覆盖**(prompt
有 priority + 中文格式,但**没强制"X→Y 数字"**);**用户期望#1 部分覆盖**
(只看 Validator 激活率,**没看反模式触发率 / L3 grade 分布 / L4 risk_tier
分布,也不审视 L3/L4 prompt 阈值**);**用户期望#3 完全未覆盖**(weekly_review
input **从未接入 price_candles / 任何实际价格走势数据**,无法对比"5/3 系统说
做多 → 5/3-5/9 实际涨"的成败回顾);weekly_reviews 表当前 **0 行**(5/3 是周日,
但 BJT 22:00 触发的 cron 那时还没正常跑过)。

## 段 2 — 关键事实

### A. weekly_review prompt 5 段输出 schema

`src/ai/agents/prompts/weekly_review_analyst.txt`:

1. **performance_summary**:total_runs / successful_runs / ai_failures /
   thesis_created / thesis_closed_profit / thesis_closed_loss / weekly_pnl_pct /
   max_drawdown_pct(8 字段)

2. **system_health_diagnosis** [list]:每条 {issue, evidence, severity,
   suggested_action} — 识别 AI 失败 / 数据问题

3. **strategy_quality**:thesis_quality(good/acceptable/poor)+
   break_conditions_calibration(适中/太严/太松)+ false_signals 列表 +
   missed_opportunities 列表

4. **hard_constraint_activation_review**:**逐条 23 V Validator 激活率**
   + meta(position_cap_compressed_avg / thesis_lock_blocks_count /
   channel_c_uses_count / review_pending_triggers)+ overall_evaluation +
   suggested_actions 列表

   **激活率评估规则**(prompt 内置):
   - 触发率 > 5/7 days → 可能阈值太严,建议放宽
   - 0/7 days → 可能阈值太松或没用,建议审视
   - 1-3/7 days → 适中
   - 4-5/7 days → 偏高但可能符合预期

5. **adjustment_recommendations** [list]:每条 {目标, 建议, 优先级
   high/medium/low, 影响}。high 优先级触发 critical 告警。

### B. weekly_review input(`weekly_review_input_builder.py`)聚合 7 类数据

```python
build_weekly_review_input(conn, *, now_utc, window_days=7)
  ├── _aggregate_strategy_runs       (total / failures / by_trigger)
  ├── _aggregate_theses              (created/closed_profit/loss/...)
  ├── _aggregate_virtual_orders      (filled/cancelled/expired)
  ├── _aggregate_retry_log           (retry/master_fail/needs_review)
  ├── _aggregate_virtual_account     (weekly_pnl_pct/max_drawdown_pct/equity_curve)
  ├── _aggregate_fuse_and_states     (14d/60d/cooldown/state_distribution)
  └── _aggregate_constraint_activations  (23 V 激活率 + meta)
```

**没有的输入**(关键缺口):
- ❌ **price_candles / 任何 BTC 实际价格走势数据**
  `grep price_candles src/ai/weekly_review_input_builder.py` 0 命中
- ❌ **anti_pattern_signals**(L3 反模式触发率)
  `grep anti_pattern src/ai/weekly_review*` 0 命中
- ❌ **L3 grade 分布**(本周 A/B/C/none 各几次)
  仅总 runs,没拆 grade
- ❌ **L4 risk_tier 分布**(本周 low/moderate/elevated/extreme 各几次)
  仅 fallback_level 计数,没看 risk_tier

### C. weekly_reviews 表 schema + 内容

```sql
CREATE TABLE weekly_reviews (
    week_start_utc       TEXT PRIMARY KEY,  -- YYYY-MM-DD,周一 UTC
    triggered_at_utc     TEXT NOT NULL,
    output_json          TEXT NOT NULL,
    critical_count       INTEGER DEFAULT 0,
    notification_sent    INTEGER DEFAULT 0
);
```

**当前 0 行**。系统 4/24 才有第一条 strategy_run,期间经历:
- 4/27(周日)— 系统 4/24 才启动,数据不全,可能直接 skip
- 5/4(周日)— 应该是首次自动触发(BJT 22:00),但**没生成**
  (可能 master AI 失败 / 输入 builder 异常 / 没人查)

### D. cron 配置(`config/scheduler.yaml`)

```yaml
weekly_review:
  enabled: true
  cron: {day_of_week: 'sun', hour: 22, minute: 0}    # 周日 22:00 BJT
  misfire_grace_time: 3600                            # 1h 容忍度
  max_instances: 1
  description: '周复盘 AI(WeeklyReviewAnalyst);周日 22:00 BJT 自动跑,
                输出 4 段 JSON 写 weekly_reviews 表 + alerts'
```

注:cron 描述写"4 段 JSON"但实际 prompt 强制 5 段(注释 stale)。

### E. 网页展示

`web/index.html:1018` 模块 5「📊 周复盘」:
```html
<template x-if="!weeklyReviewSelected">
  <p>暂无周复盘报告(每周日 22:00 BJT 自动生成)</p>
</template>
```

读 `state.weeklyReviewSelected` + `weeklyReviewHistory`,从
`/api/review/weekly/latest` + `/api/review/weekly/history?limit=12` 接口拉取。
表 0 行 → 当前显示"暂无"。

## 段 3 — 风险扫描:用户三个诉求 vs 现状 + 扩展工程量

### 用户期望 vs 现状对照表

| 用户诉求 | 现状 | 缺什么 |
|---|---|---|
| **#1 识别建模偏差**(反模式触发率 / L3 L4 阈值偏松/严)| ⚠️ **部分覆盖** | 23 V Validator 逐条 ✅;反模式 ❌;L3 grade 分布 ❌;L4 risk_tier 分布 ❌;**L3/L4 prompt 阈值审视 ❌** |
| **#2 具体改进建议**(不泛泛,要"X 调成 Y")| ⚠️ **部分覆盖** | adjustment_recommendations 有 priority + 中文格式;**但 prompt 没强制"X 阈值改 Y 数值"** |
| **#3 AI 判断 vs 实际市场走势**(系统说做多,实际涨/跌的成败回顾)| ❌ **完全未覆盖** | input 没接 price_candles;prompt 没问 AI"对比"问题 |

### 扩展工程量评估

| 扩展项 | 工程量 | 实施路径 |
|---|---|---|
| 加 anti_pattern 触发率聚合 | **小**(0.5 天) | `weekly_review_input_builder.py` 加 `_aggregate_anti_patterns(conn)` 读 strategy_runs.full_state_json.layers.l3.anti_pattern_flags;prompt 加一段评估 |
| 加 L3 grade 分布(A/B/C/none/empty) | **小**(0.5 天) | 同上,SELECT json_extract(full_state_json, '$.layers.l3.opportunity_grade') 聚合 |
| 加 L4 risk_tier 分布 | **小**(0.5 天) | 同上 |
| 加 BTC 实际走势对比 | **中**(1-2 天) | `_aggregate_price_action(conn, week_start, week_end)` 读 price_candles 拿 7d open/high/low/close;prompt 加"对比 5/3 master 说做多 vs 实际 5/3-5/9 +2.3% 涨,系统判断准确度评估" |
| thesis 表现回顾(创建后实际 PnL)| **大**(2-3 天) | 需要 Sprint G P0 后真有 thesis 行;扩 _aggregate_theses 加 final_realized_pnl 等字段;prompt 加"thesis 命中率"段 |
| prompt 强制具体数值建议 | **小**(0.5 天) | prompt 改约束:adjustment_recommendations.建议 字段必须含具体阈值 / 文件名 / 行号(如"L3 prompt §四 B 级定义加 phase=early 强约束") |

### Sprint H 候选优先级

**P0(最直接对应用户诉求)**:
1. 加 BTC 价格走势对比(price_candles 7d)→ AI 能说"系统 5/3 给 long 准确"
2. 加 anti_pattern 触发率聚合 → AI 能说"extending_late_phase 49% 触发率
   过高,建议 L3 prompt §六调整 phase=late 判定"
3. 加 L3 grade / L4 risk_tier 分布 → AI 能说"L4 elevated 占 55% 偏多,
   建议审视 L4 prompt §四 elevated 档定义"

**P1**(等 Sprint G P0 真创建 thesis 后再加):
4. thesis 表现回顾(命中率 / 平均 PnL / 失效原因分布)

**P2**(prompt 强制具体数值)

### 现状最大风险

**weekly_review 表 0 行**:cron 配置存在(每周日 22:00 BJT),但 5/4 那次首
个周日没生成。**可能原因**:
- 5/4 master AI 失败率高(quota 期间)→ weekly_review_analyst 也可能 fail
- 或 cron 没触发 / scheduler 注册有问题
- 没用户手动核查

**Sprint H 候选 P3**:加 weekly_review fail 时的告警 + 网页可视化本周
quote 是否成功生成。

## 段 4 报告路径

`docs/cc_reports/weekly_review_audit.md`(本文件)

## 给用户的建议(纯查不改)

1. **5/10 周日 22:00 BJT 自然触发,等到时观察是否真生成 weekly_review 行**
   (Sprint G P0 + Sprint F.1 已部署,这次理论上有 1 行 master 跑通的数据
   可分析)
2. **如果 5/10 仍生成失败 → Sprint H P0 先 debug**(weekly_review_analyst
   AI 调用 / input builder 报错位置)
3. **生成成功后,先看输出质量**,再决定是否启动 Sprint H 扩展(加
   price_candles + anti_pattern + L3/L4 分布)
4. **价格走势对比是用户期望#3 的核心**,现 0% 覆盖,Sprint H 必上
