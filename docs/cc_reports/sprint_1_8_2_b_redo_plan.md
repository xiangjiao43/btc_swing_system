# Sprint 1.8.2-B 重做规划(Step 2:清单等用户审定)

## Triggers(偏离建模 / 需用户决策的点)

- 1.8.2-B 初版(commit 1d5f610)前端 wholesale rewrite,误删 region-4 原始因子区(45 项展示)
- 用户红线:region-4 不可改、normalize_state / decision_time 后端不可改、1.8.2-A 翻译表锁定、v12 fallback prompt 必须保留、不引入 npm / 新框架
- 用户决策点:本文件给的 4 张清单(删 / 留 / 增 / 必须确保) + 推荐布局,**等用户逐项审定后** CC 才动手 Step 3

---

## Step 1 已完成 — partial revert 实测

```
git checkout 67858bb -- web/index.html web/assets/app.js
wc -l → 735 web/index.html / 802 web/assets/app.js / 1537 total
```

(用户预期 855/906,实际 735/802。差额来自 1.5o 已经整块删过"五层证据推导细节",`67858bb` 文件本身就是 735/802;**内容仍包含 region-4 + 老 region-3 组合因子卡 + 全部 sticky nav / 系统自检 / 暗黑模式**。已抽样 verify。)

**保留的后端 1.8.2-A 工作**(未 revert):
- `src/web_helpers/normalize_state.py` — schema_version + summary_card + layer_cards + anti_patterns_active + extreme_events_active + raw + decision_time(BJT)
- `src/web_helpers/labels.py` — 11 张锁定翻译字典
- `src/api/routes/strategy.py` — `_row_to_model()` → `normalize_state(state, run_mode, generated_at_utc=...)`
- `tests/web_helpers/test_normalize_state.py` — 39 单测

**当前数据契约失配**(Step 3 必须解决):
- 后端返回的 `state` 现在是 normalize_state 后的 schema(`schema_version` / `summary_card` / `layer_cards` / `anti_patterns_active` / `extreme_events_active` / `raw`)
- 前端旧代码(已 revert 回来的版本)仍按 v12 老路径读 `state.main_strategy` / `state.evidence_reports.layer_X` / `state.adjudicator` / `state.factor_cards` / `state.composite_factors`
- 这些字段在新 schema 顶层不存在,但都被 `state.raw` 保留 → Step 3 用最小改动修桥(把读路径改成 `state.raw.*`),同时新增"上层叙事"消费 `state.summary_card` + `state.layer_cards`

---

## 清单 1:删除清单(Step 3 要删)

| # | 对象 | 位置 | 删除原因 | 替代 |
|---|---|---|---|---|
| 1.1 | 整个 `<section id="region-3">` 组合因子卡区 | `web/index.html:500-579` | 1.8.2-A 已用 `summary_card.headline` + `layer_cards[].label / summary` 替代"高阶信号"角色;旧组合卡靠 AI prompt 写 `composition / current_analysis / strategy_impact`,在 v1.3 orchestrator 下不再产出 | 新增 region-3'(layer_cards 6 张) |
| 1.2 | `compositeCards()` | `web/assets/app.js:403-423` | 仅服务于已删除的 region-3 | — |
| 1.3 | `_composite_raw()` | `web/assets/app.js:425-429` | 同上 | — |
| 1.4 | `compositeComposition()` / `compositeRule()` / `compositeInterpretation()` / `compositeAffects()` | `web/assets/app.js:430-445` | 同上 | — |
| 1.5 | `compositeCurrentAnalysis()` / `compositeStrategyImpact()` / `compositeMissingHint()` | `web/assets/app.js:447-466` | 2.5-B AI 双段分析,只服务 region-3 | — |
| 1.6 | 4 个 composite keys(`truth_trend / band_position / crowding / macro_headwind`) | `app.js:410-413` 的 order 数组 | v1.3 orchestrator 不产出 `composite_factors[*]`;5 个组合因子在 layer_cards 6 张里被新版"分层叙事"覆盖 | layer_cards.l1/l2/l4/l5 |
| 1.7 | `cycle_position` 专卡 | `app.js:409` 的 order 数组 | 在 layer_cards 中已由 L3 / master 综合体现;但用户特别点名"CyclePosition" → **此项请用户决策**(见决策点 D1) | layer_cards.l3 |
| 1.8 | `_to_display_state` 中 `evidence_reports` 派生段 | `app.js:308 / 336` | 后端 normalize_state 已经把所有 v12/v13 差异在后端拍平;前端不应再做派生 | 改读 `state.raw.evidence_reports` 临时桥接 |

**git grep 自检**(commit 前):
```
git grep -n composite_factors web/   # 期望 0 行
git grep -n compositeCards web/      # 期望 0 行
git grep -n truth_trend web/         # 期望 0 行
git grep -n band_position web/       # 期望 0 行
git grep -n macro_headwind web/      # 期望 0 行
git grep -n crowding web/            # 期望 0 行(注:crowding 也在因子库里,如确实存在则需手工识别是组合因子还是普通因子)
```

---

## 清单 2:保留清单(Step 3 必须不动 / 不破坏)

### 2.A 红线区域(用户特别点名)

| # | 对象 | 位置 |
|---|---|---|
| 2A.1 | `<section id="region-4">` 原始数据因子区,5 组(价格技术 / 衍生品 / 链上 / 宏观 / 事件日历) | `index.html:587-665` |
| 2A.2 | `factorGroups()` + `toggleGroup()` + `expandedGroups` 状态 | `app.js:469-493` |
| 2A.3 | `state.factor_cards.filter(c => c.tier !== 'composite')` 数据来源 | `app.js:470-471 / index.html:594` |

### 2.B 全局 UI(必须保留)

| # | 对象 | 位置 |
|---|---|---|
| 2B.1 | Sticky Top Nav(BTC Strategy 标识 + dataSource 标 + nowBjt + 日夜切换) | `index.html:30-69` |
| 2B.2 | BTC 现价 ticker(顶部全局状态条 8 列 grid) | `index.html:90-156` |
| 2B.3 | 🩺 系统自检面板(五层证据健康 + 数据源新鲜度) | `index.html:158-229` |
| 2B.4 | `livePrice* / _refreshLivePrice / _refreshSystemHealth / layerHealthGlyph / sourceStatusGlyph / selfCheckBadgeLabel` helpers | `app.js`(各处) |
| 2B.5 | dark mode toggle + `_initDarkMode` + Tailwind config | `index.html:9-22 / 48-66`、`app.js`(`_initDarkMode`) |
| 2B.6 | MOCK 数据顶部黄条 + loading / error 占位 | `index.html:71-84` |

### 2.C region-1 AI 策略建议(右侧 region-3 删除后此卡占满宽度)

| # | 对象 | 位置 |
|---|---|---|
| 2C.1 | 整个 `<section id="region-1">` Row1-Row7 七行(方向 / 机会 / 许可 / 交易计划 / 持仓预览占位 / 策略说明 / 论据 / 硬失效 / 事件 / 风险标签 / 改判触发 / 现货解读) | `index.html:237-497` |
| 2C.2 | 配套 helper:`tp() / strategyDirection() / hardInvalidationLevels() / eventWindows() / activeRiskTags() / primaryDriversDisplay() / counterArgumentsDisplay() / whatWouldChangeMindDisplay() / strategyFallbackNarrative() / positionCapExplain() / stopLossBasis() / showPositionPreviewPlaceholder()` | `app.js`(各处) |
| 2C.3 | region-1 grid 容器(`lg:col-span-3`)需在 Step 3 改成 `lg:col-span-5` 或独立行,**因为右侧 region-3 整块要删**(见布局推荐) | `index.html:235-237` |

### 2.D region-5 历史与复盘 + Footer

| # | 对象 | 位置 |
|---|---|---|
| 2D.1 | `<section id="region-5">` 历史时间线 + 复盘入口 | `index.html:667-722` |
| 2D.2 | Footer(rules_version / model / dataSource) | `index.html:724-731` |

### 2.E 后端不可动

- `src/web_helpers/normalize_state.py`(整文件)
- `src/web_helpers/labels.py`(整文件)
- `src/api/routes/strategy.py`(`_row_to_model` 调用 normalize_state 的部分)
- `tests/web_helpers/test_normalize_state.py`(39 单测)
- v12 fallback 路径(`_normalize_v12`)— 必须保留,Sprint 2.6/2.7 老历史 run 仍是 v12

---

## 清单 3:新增清单(Step 3 要加,消费 1.8.2-A 新 schema)

> 设计原则:**只增不改**。在 region-3 旧组合因子卡的位置,新插一个"分层证据卡"区。region-1 / region-4 / 系统自检 都不动。

### 3.1 区域 3'(新):分层证据卡(layer_cards 6 张)

- **位置**:替换原 region-3 在 `index.html:499-579` 的位置
- **数据**:`state.layer_cards`(6 个元素:L1 / L2 / L3 / L4 / L5 / master,后端已经按顺序排好)
- **每卡**:
  - 顶部:`layer`(L1-L5 / master) + `title`(锁定中文如"L1 体制识别")+ `label`(主标如"中性偏多")
  - 第二行:`secondary_labels`(数组,如 `["阶段:整理", "趋势强度:0.62"]`)
  - 折叠区(默认收起,"查看详细 ▼"展开):`summary`(中文叙述)
- **i18n**:全部已经在后端 `labels.py` 翻译完,前端只 display
- **密度 C**:默认折叠,sm:grid-cols-2 lg:grid-cols-3,每卡 ≤ 80px 高
- **新 helper**:`layerCardOf(layerKey)`(返回 layer_cards 里 `layer === layerKey` 的卡)、`expandedLayerCards`(状态对象)、`toggleLayerCard(key)`

### 3.2 区域 0'(新):Schema 顶部薄条 + headline

- **位置**:在"顶部全局状态条"和"系统自检"之间,**或合并进顶部全局状态条第 9 列**(见布局决策点 D2)
- **数据**:`state.summary_card.headline`(一句话总结) + `state.summary_card.action_state_label`(中文档位) + `state.summary_card.stance_label`(中文 stance) + `state.summary_card.decision_time`(BJT)
- **样式**:1 行 hero 文字 + 时间戳右对齐;不破坏现有 8 列 grid

### 3.3 反模式 / 极端事件警告条(条件渲染)

- **位置**:region-1 之上(在系统自检和 region-1 之间插一行)
- **触发**:`state.anti_patterns_active.length > 0 || state.extreme_events_active.length > 0`
- **样式**:
  - 反模式(琥珀):`⚠️ 反模式触发:<逗号分隔列表>`
  - 极端事件(玫红):`🚨 极端事件触发:<逗号分隔列表>`
- 默认两个数组都为空时整段 `x-show=false`

### 3.4 v12 fallback 红 banner

- **位置**:在"系统自检"之上插一行(优先级最高,用户必须先看到)
- **触发**:`state.schema_version === 'v12' || state.schema_version === 'unknown'`
- **样式**:玫红边 + `⚠️ 当前展示的是兼容模式(v12 schema):此 run 由旧 pipeline 产生,部分新字段缺失。建议查看由 v1.3 orchestrator 生成的更新 run。`
- 新 schema(`v13`)运行时整段 `x-show=false`

### 3.5 数据契约桥接(最小改动)

- 把 `app.js:308 / 336` 的 `raw.evidence_reports` 改成 `(this.state.raw || {}).evidence_reports`,确保 `_to_display_state` 派生 main_strategy / risks 时能从 normalize_state 后的 `state.raw` 拿到原 v12/v13 字段
- 不改 region-1 / region-4 的任何 helper 内部逻辑,只改顶层"原始 state 在哪"的入口

---

## 清单 4:必须确保(Step 3 验收门)

| # | 验收点 | 怎么验证 |
|---|---|---|
| 4.1 | region-4 渲染前后视觉无差(45 个原始因子卡仍在,5 组分组,主要平铺 + 次要展开) | 浏览器手测 / Playwright snapshot |
| 4.2 | normalize_state 39 单测通过 | `pytest tests/web_helpers/` |
| 4.3 | 全部 ts 测 + 后端测通过 | `pytest tests/` |
| 4.4 | v12 老 run(2026-04 之前)展示 v12 fallback red banner + summary_card 仍能渲染 | 用 `/api/strategy/runs/{run_id}` 取一条 v12 run 手测 |
| 4.5 | v13 新 run(orchestrator 出的)展示 6 张 layer_cards + summary_card.headline + decision_time(BJT) | 用最新 16:05 BJT cron 出的 run 手测 |
| 4.6 | dark mode 切换正常 | UI 手测 |
| 4.7 | 系统自检面板的 layer 健康 + 数据源新鲜度仍正常刷新(每 5 分钟) | 等 5 分钟 / 手动刷新 |
| 4.8 | BTC live ticker 仍每 30 秒刷新 | DevTools Network 看请求 |
| 4.9 | SSE `/api/strategy/stream` 仍能 push 新 run 进 `state` | DevTools EventStream 看 |
| 4.10 | 反模式 / 极端事件 / v12 banner 三条触发条件下显示,否则隐藏 | 手测 + 单测 |

---

## 推荐布局(等用户审定)

```
┌─────────────────────────────────────────────────────────────┐
│ Sticky Top Nav(2B.1)                                        │
├─────────────────────────────────────────────────────────────┤
│ MOCK banner(2B.6,条件)                                      │
├─────────────────────────────────────────────────────────────┤
│ 顶部全局状态条:8 列 grid(BTC ticker / 状态 / 生命周期 /     │
│ 机会-许可 / 观察 / 下次运行 / 数据-fallback)(2B.2)            │
├─────────────────────────────────────────────────────────────┤
│ ⚠️ v12 fallback red banner(3.4,条件)                         │
├─────────────────────────────────────────────────────────────┤
│ ⚠️ 反模式 / 🚨 极端事件警告条(3.3,条件)                      │
├─────────────────────────────────────────────────────────────┤
│ 🩺 系统自检(2B.3)                                           │
├─────────────────────────────────────────────────────────────┤
│ region-0' 新 Schema 顶部薄条:headline + decision_time(3.2)│
├─────────────────────────────────────────────────────────────┤
│ region-1 AI 策略建议(2C.1,占满宽度,lg:col-span-5)         │
├─────────────────────────────────────────────────────────────┤
│ region-3' 分层证据卡(3.1,6 张,2-3 列网格)                  │
├─────────────────────────────────────────────────────────────┤
│ region-4 原始数据因子(2A.1,5 组分组,不变)                  │
├─────────────────────────────────────────────────────────────┤
│ region-5 历史与复盘(2D.1)                                  │
├─────────────────────────────────────────────────────────────┤
│ Footer(2D.2)                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 用户决策点(等审定)

- **D1 — `cycle_position` 专卡保留 or 删除?**
  用户提到"保留 CyclePosition"。两条路:
  - (a) 删除整个 region-3 旧组合卡区(包括 cycle_position)+ 在 layer_cards.l3 里依赖后端 summary 文本带出 cycle 信息(**推荐**:统一新 schema)
  - (b) 单独留一张 CyclePosition 卡,但需要后端继续产出 `state.composite_factors.cycle_position`(orchestrator 是否产出?**待 CC 核**)
  → 倾向 (a),因为 v1.3 orchestrator 不再写 `composite_factors`,留 (b) 会变成永久 stub

- **D2 — region-0' 是单独一行,还是合并进顶部全局状态条第 9 列?**
  - (a) 单独一行 hero 文字(**推荐**,headline 通常 30-50 字,挤进 8 列 grid 太挤)
  - (b) 合进顶部状态条(节省 1 行,但视觉散乱)

- **D3 — `cycle_position` 删除自检要不要 grep `cycle_position`?**
  注意:`cycle_position` 也是 L3 内部规则名,在 `src/`(Python)和 `docs/modeling.md` 中肯定有大量合法引用。grep 限定在 `web/` 子树即可。

---

## Step 3 实施计划(等用户 D1/D2/D3 审定后再执行)

1. **app.js**:删 1.2-1.6 helpers + 1.8 数据契约桥接修(改 `evidence_reports` 入口)
2. **app.js**:加 `layerCardOf / expandedLayerCards / toggleLayerCard`(支持 region-3')
3. **index.html**:删 1.1 整个 region-3
4. **index.html**:在原 region-3 位置插 region-3'(分层证据 6 卡)
5. **index.html**:`region-1` 容器从 `lg:col-span-3` 改 `lg:col-span-5` 或独立行
6. **index.html**:在系统自检之上插 v12 banner(3.4)+ 反模式/极端事件条(3.3)
7. **index.html**:在系统自检和 region-1 之间插 region-0'(3.2)
8. 跑 4.1-4.10 验收
9. commit + push(本 sprint 删除清单 = 清单 1 全部 6 项)
10. 报告 `docs/cc_reports/sprint_1_8_2_b_redo.md`(同时更新原 `sprint_1_8_2_a_b.md` 的部署四件事表)

---

## 部署状态四件事(本 plan 文件层面)

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ❌(待 Step 3 跑) |
| GitHub push(commit hash:xxxx) | ❌(本文件 + Step 1 revert 同 commit 推) |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A(纯前端 + plan 文件) |

## 本 sprint 删除清单(本 plan 文件层面)

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| (尚未) | (Step 3 时执行) | 见清单 1 |

**本 plan 阶段无替代关系,无删除项**(只 partial revert + 写规划文档,Step 3 才删代码)。
