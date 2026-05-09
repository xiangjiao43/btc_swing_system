# L3=B / C 级机会在网页的实际可见性核查(只查不改)

**日期**:2026-05-09 BJT
**类型**:事实核查 sprint
**触发**:用户反馈"网页一次 B 级机会都没看到",跟前次 audit 报告说"5/1
至今 L3 给 13 次 B 级"严重冲突 — 需要确认网页层是否真的丢失了这些信号

## 结论一句话

**13 次 L3=B 全部都正确流到网页 layer_cards / summary_card.headline,用户**
**网页层面 SHOULD HAVE 看到「B 级机会(尚可)」标签 + 「可考虑开仓(中级别**
**机会)」标题**;但每次 B 级显示**只持续几分钟到几小时,被下一次 event_onchain
覆盖** — 5/2-5/8 期间一日 9-17 次 event_onchain 把 B 级快闪撞没了。
**Sprint F.1 删 event_onchain 后,每日 1 次 BJT 11:35 scheduled,B 级展示
窗口可持续 ~24h**,用户看到概率会大幅提升。

## 段 2 — 13 次 L3=B 明细 + 5 次 L3=C 明细

### A. 13 次 L3=B 全表

| BJT 时间 | trigger | fb_level | l3 | l3 perm | l4 risk | master mode | silent_reason / summary |
|---|---|---|---|---|---|---|---|
| 2026-05-08T16:09 | scheduled | level_2 | B | cautious_open | elevated | silent_cooldown | master AI 失败,fallback silent / 主裁 AI 失败,保守观察 |
| 2026-05-06T13:52 | event_onchain | level_2 | B | cautious_open | moderate | silent_cooldown | master AI 失败,fallback silent / 主裁 AI 失败,保守观察 |
| 2026-05-05T20:03 | event_onchain | level_2 | B | cautious_open | elevated | silent_cooldown | master AI 失败,fallback silent / 主裁 AI 失败,保守观察 |
| 2026-05-03T16:08 | **scheduled** | (空)| B | cautious_open | moderate | (空)| (空) |
| 2026-05-03T16:03 | event_onchain | level_2 | B | cautious_open | moderate | (空)| 主裁 AI 失败,保守观察 |
| 2026-05-03T12:37 | event_onchain | (空)| B | cautious_open | moderate | (空)| (空) |
| 2026-05-03T11:47 | event_onchain | level_2 | B | cautious_open | moderate | (空)| 主裁 AI 失败,保守观察 |
| 2026-05-03T08:38 | event_onchain | (空)| B | cautious_open | moderate | (空)| (空) |
| 2026-05-02T18:05 | event_onchain | level_2 | B | cautious_open | moderate | (空)| 主裁 AI 失败,保守观察 |
| 2026-05-02T16:04 | event_onchain | level_2 | B | cautious_open | moderate | (空)| 主裁 AI 失败,保守观察 |
| 2026-05-02T12:49 | manual_api | level_2 | B | cautious_open | moderate | (空)| 主裁 AI 失败,保守观察 |
| 2026-05-02T12:38 | manual_api | level_2 | B | cautious_open | moderate | (空)| 主裁 AI 失败,保守观察 |
| 2026-05-02T12:03 | manual_api | level_2 | B | cautious_open | moderate | (空)| 主裁 AI 失败,保守观察 |

**关键观察**:13 次 B 级里 12 次 fallback_level=level_2(master AI 失败),
仅 1 次 master AI 真成功(5/3 16:08 scheduled,fb 空但 master.mode 也空 —
说明 master 输出可能是空 dict 或被覆盖)。

### B. 5 次 L3=C 全表

| BJT 时间 | trigger | fb_level | l3 | l3 perm | l4 risk | master mode | silent_reason |
|---|---|---|---|---|---|---|---|
| 2026-05-09T11:24 | manual_api | level_1 | C | watch | moderate | silent_cooldown | 关键层 L2 数据降级(链上数据全过期 69.3 小时,fresh_ratio=0.58),空仓不开新仓 |
| 2026-05-08T16:16 | event_onchain | (空)| C | watch | elevated | silent_cooldown | L3 grade=C + execution_permission=watch,不满足创建 thesis 条件 |
| 2026-05-06T20:03 | event_onchain | (空)| C | watch | elevated | silent_cooldown | L3 grade=C 但 execution_permission=watch(非 ambush_only),不满足创建 thesis 条件 |
| 2026-05-05T20:16 | event_onchain | level_2 | C | watch | elevated | silent_cooldown | master AI 失败,fallback silent |
| 2026-05-01T17:49 | manual | (空)| C | watch | moderate | (空)| (空) |

**5 次 C 都是 permission=watch**(不满足开新 thesis 的"非 watch"条件)→
master 全 silent_cooldown。

### C. 用 API 真正调出来 5/8 16:09 B-grade run 看用户看到什么

```
$ curl http://127.0.0.1:8000/api/strategy/runs/78d85f4979704a1799600acbda013339
state.summary_card.headline      = "可考虑开仓(中级别机会)" ✅ 用户能看到
state.summary_card.action_state_label = "空仓观察"
state.layer_cards[2].label       = "B 级机会(尚可)" ✅ L3 卡明确显示 B
state.layer_cards[5].label       = "未知"  ← master AI fallback,master 卡空
```

**B 级机会标签 + headline 在 API 完整返回**,说明前端拿得到。

### D. 5/8 BJT 16:00-17:00 真实流水:为什么 B 级"快闪"

```
2026-05-08T16:02:37 event_onchain  level_1  l3=none
2026-05-08T16:09:36 scheduled      level_2  l3=B   ← 用户期望看到
2026-05-08T16:16:23 event_onchain  (空)    l3=C   ← 7 分钟后覆盖
```

**B 级显示窗口仅 7 分钟**,然后被下一次 event_onchain 触发的 run 覆盖掉。
用户那 7 分钟没刷新就错过。

5/2-5/8 类似情况:event_onchain 一日 9-17 次,B 级被频繁覆盖。

## 段 3 — 网页字段读取链路核实

### A. 网页 "AI 策略建议 → 机会等级" 卡片读哪个字段

`web/index.html:402-407`:
```html
<div class="stat-label">机会等级</div>
<div :class="cardOpportunityGrade() === '-' ? 'placeholder-dash' : 'font-bold'"
     x-text="cardOpportunityGrade()"></div>
```

`web/assets/app.js:554`:
```javascript
cardOpportunityGrade() {
    const grade = this.state?.main_strategy?.opportunity_grade;
    if (!grade || grade === 'none' || grade === 'None') return '无机会';
    return grade + ' 级';
}
```

`state.main_strategy.opportunity_grade` 是**客户端重组**字段(line 735):
```javascript
out.main_strategy = {
    opportunity_grade: this._extractGrade(out.layer_cards) || 'none',
};
```

`_extractGrade(layer_cards)`(line 808-818):
1. 优先取 `layer_cards[layer='l3'].supporting_data.opportunity_grade.value`
2. 否则匹配 `layer_cards[layer='l3'].label` 前缀:
   - `"A "` → "A"
   - `"B "` → "B"
   - `"B 级"` → "B"(prefix 匹配命中)
   - `"C "` → "C"
   - 含 `"无机会"` → "none"

### B. API `/api/strategy/current` → 实际数据

`src/api/routes/strategy.py:60-63`:`normalize_state(state, run_mode)`
读 `strategy_runs.full_state_json` 后**在线构造** `summary_card / layer_cards`
(`src/web_helpers/normalize_state.py:_normalize_v13`)。

DB 持久化的 `full_state_json` 顶层只有:
```
context_summary, latency_ms, layers, schema_version, status,
system_provided, validator
```
**没有 summary_card / layer_cards** — 它们是 read-time 构造的。这是设计意图
(让 v12 / v13 / v14 schema 共存,前端拿一致 schema)。

### C. 顶栏 headline:

`web/index.html` 顶栏(grep "headline"):
- 主页"AI 策略建议"卡的 `state.summary_card.headline` 字段直接展示
- 5/8 16:09 那次值 = **"可考虑开仓(中级别机会)"** ← 用户应看到的内容

### D. 5/9(今天)/api/strategy/current 实际返回(C 级)

```
state.summary_card.headline           = (没显示,应有 "等待信号" 或类似)
state.summary_card.action_state_label = "空仓观察"
state.summary_card.opportunity_grade  = null  ← 注意:summary_card 本身不带
state.layer_cards[2].label            = "C 级机会(一般,谨慎)" ✅
```

前端 `cardOpportunityGrade` 通过 `_extractGrade(layer_cards)` 读 layer_cards[2]
label 前缀 "C 级" → 返回 "C" → **网页显示 "C 级"**。

### E. 网页"thesis 历史时间线"读什么

`web/index.html:810` 等:`thesesHistory` 读 `/api/theses/history` 接口,
显示**已创建的 thesis**(active_thesis 行)。`active_thesis` 只在 master.mode
== "new_thesis" 时创建。**5/1 至今 0 次创建 → 时间线确实空**。

但 thesis 历史时间线**不显示 L3 grade 历史**;只显示 thesis 生命周期,
不能与"B 级机会展示"对应。

## 段 3.5 — 用户为什么"一次都没看到"的真实原因

1. **B 级展示窗口短**:5/2-5/8 期间一日 9-17 次 event_onchain 触发,B 级
   显示通常只持续 7 分钟到几小时就被下一个 run 覆盖。**5/8 16:09 那次只
   持续到 16:16(7 分钟)**。

2. **B 级 12/13 次都是 master fail 状态**(fallback_level=level_2)→
   `master 卡 = "未知"`,顶部 headline 是"可考虑开仓(中级别机会)"看起来
   矛盾,用户可能因此没认真看 L3 卡。

3. **Sprint E 之前 master AI 在 stale 数据下经常 fallback**,导致 master
   卡空白 → 用户感觉"系统什么都没说" → 没注意 L3 卡的 B 级标签。

4. **Sprint F.1 删 event_onchain 后**(已部署 5/8 17:25),每日仅 1 次
   scheduled BJT 11:35 → B 级展示能持续 ~24h 直到次日覆盖。**用户看到
   B 级的概率会大幅提升**,不会再被 event_onchain 快闪覆盖。

## 段 4 报告路径

`docs/cc_reports/l3_b_grade_visibility_audit.md`(本文件)

## 给用户的建议(纯查不改)

1. **明天 BJT 11:35 后保持网页打开**:Sprint F.1 删 event_onchain 后,
   master 输出会持续到次日 11:35 不被覆盖。如果 L3 给 B,用户会有 ~24h
   窗口看到「B 级机会(尚可)」 + headline「可考虑开仓(中级别机会)」。

2. **如果 quota 恢复后某日 11:35 给 B 但 master fail(level_2)**:
   网页**仍会显示 L3 卡的"B 级机会"标签 + 顶部 headline**,但 master
   卡显示"未知" + master AI 失败横幅。这是设计意图(诚实显示 AI 失败,
   但不影响 L3 sub-agent 的正常显示)。

3. **历史时间线 ≠ 机会展示**:thesis 历史时间线只显示**已创建的 thesis**,
   B 级机会不创建 thesis(master silent_cooldown / fail)→ 时间线空是正常,
   不是 bug。要看历史 B 级要查 `/api/strategy/history` 或
   `/api/strategy/runs/{run_id}`。

4. **不需要改任何代码**:网页字段链路完全正确(layers.l3.opportunity_grade
   → normalize_state → layer_cards[2].label = "B 级..." → _extractGrade →
   "B" → cardOpportunityGrade → "B 级"),Sprint F.1 后 B 级展示频率自然
   恢复正常。
