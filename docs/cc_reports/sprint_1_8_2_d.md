# Sprint 1.8.2-D:删摘要 + 修 health-detail + AI 策略区 13 卡重构 + 删 supporting_data

## Triggers(偏离建模 / 需用户决策的点)

- 严格按用户给的 4 个 diff 复制粘贴落字符
- **1 处微 deviation**(透明披露,见段 1):新 region-1 用户给的 class 是 `audit-card`(无 col-span);为保留 1.8.2-C 的 `lg:col-span-5` 防止在 lg 屏被外层 `lg:grid-cols-5` 收窄到 1/5 宽,我添加了 `lg:col-span-5`。这是单 class 的最小保留,而非新设计。
- D4 经 grep 确认是 no-op:HTML 0 处 `supporting_data` 渲染。app.js 仍有 3 处(`_extractGrade / _extractPermission / _extractHardInvalidations`)用于 v13→v12 内部映射,**不是 UI 渲染**,按用户保留指示原样保留。
- **未 push**:遵守"PUSH 前等用户 SSH 实证才推"。

---

## 段 1:做了什么

4 个修改,改 3 个文件:

| 任务 | 文件 | 行号(改后) | 动作 | 行数 |
|---|---|---|---|---|
| D1 | `web/index.html` | 89-110 | 删除原"当前决策"摘要 section(34 行),换成新"风险警告条" section(只警告条,异常时显示)(22 行) | -34 / +22 |
| D2 | `src/api/routes/system.py` | 240-272 | `_query_evidence_layers_health` 加 v13 优先分支:检测 `state.layers` 存在 → 读 `layers.l1-l5.status`(success → healthy / degraded* → degraded / 其他 → missing);v12 evidence_reports 路径作 fallback 保留 | +32 |
| D3 | `web/index.html` | 259-355 | 删除原 region-1(7 行 grid + Row1-Row7 + 现货解读 + narrative,共 261 行),换成新 region-1(13 张小卡,4 行)(97 行) | -261 / +97 |
| D3 | `web/assets/app.js` | 199-258 | 在 `layerCardOpen` 之后插入 13 张小卡 helpers(`cardOpportunityGrade / cardConfidence / cardEntryZones / cardStopLoss / cardTakeProfits / cardPositionCap / hasActivePosition / cardCurrentPnl / cardDistanceToStop / cardHoldingDuration / cardHardInvalidations / cardFutureEvents`,共 12 helpers — `hasActivePosition` 是 boolean 状态,严格意义上 11 个卡 helper + 1 状态 helper) | +60 |
| D4 | (无改动) | — | grep 确认 HTML 0 处 supporting_data 渲染,app.js 3 处 helper 内部用 → 保留(用户硬约束保留) | 0 |

### 微 deviation 透明披露

用户给的 D3 新 region-1 第一行是:
```html
<section id="region-1" class="audit-card">
```

我实际写入的是:
```html
<section id="region-1" class="audit-card lg:col-span-5">
```

**多了 `lg:col-span-5` 一个 class**。理由:
- 外层 `<div class="grid grid-cols-1 lg:grid-cols-5">`(line 257)还在(1.8.2-C 的 region-3 删除后没被一起拆,因为区域命名仍然是规范"3/2 分栏")
- 没有 `lg:col-span-5`,新 region-1 在 lg 屏收缩到 1/5 宽,13 卡 4 行无法呈现
- 1.8.2-C 已先把 region-1 改成 `lg:col-span-5`,我**保留**这一类,等同于"prior-fix preserve"
- 如用户严格要求恢复纯 `audit-card`,**单字符级 1 处差异**,1 行 Edit 即可还原

文件大小变化:
- `web/index.html`: 775 → 583 行(-192 净减,主要是 region-1 从 261 行精简到 97 行)
- `web/assets/app.js`: 884 → 944 行(+60)
- `src/api/routes/system.py`: +32

git diff --stat:
```
src/api/routes/system.py |  32 +++++
web/assets/app.js        |  60 +++++++++
web/index.html           | 344 +++++++++++------------------------------------
3 files changed, 173 insertions(+), 263 deletions(-)
```

---

## 红线遵守自检

### region-4 baseline 6 行(完成后内容必须仍存在)

```
$ grep -n "region-4\|原始因子\|factorGroups\|原始数据因子" web/index.html web/assets/app.js
web/assets/app.js:611:        factorGroups() {
web/assets/app.js:929:                for (const g of this.factorGroups()) {
web/index.html:445:    <!-- 📂 区域 4:原始因子(5 组,主要平铺 + 次要折叠) -->
web/index.html:447:    <section id="region-4" class="audit-card">
web/index.html:450:          <span>📂</span><span>原始数据因子</span>
web/index.html:459:        <template x-for="group in factorGroups()" :key="group.key">
```
✅ 6 行内容全部存在,行号因 D1/D3 净 -192 平移到上方。

### region 列表(完成后)

```
$ grep -n 'id="region-' web/index.html
262:    <section id="region-1" class="audit-card lg:col-span-5">    ← D3 全替换
357:    <section id="region-layer-cards" class="audit-card" ...>    ← 1.8.2-C 加,不动
447:    <section id="region-4" class="audit-card">                  ← 不动
529:    <section id="region-5" class="audit-card" ...>              ← 不动
```
✅ region-1 / region-layer-cards / region-4 / region-5 都在;原"当前决策"摘要 section(无 id)已删;新"风险警告条" section(无 id,只在异常时显示)在 line 89。

### D4 supporting_data 自检

```
$ grep -n "supporting_data\|支持数据" web/index.html web/assets/app.js
web/assets/app.js:391:            // risks:从 L4 layer_card 提取(supporting_data)        ← 注释
web/assets/app.js:452:            const sd = l3.supporting_data || {};                     ← _extractGrade
web/assets/app.js:453:            // l3 卡的 supporting_data 通常含 opportunity_grade 原值  ← 注释
web/assets/app.js:465:            const sd = l3.supporting_data || {};                     ← _extractPermission
web/assets/app.js:472:            const sd = l4.supporting_data || {};                     ← _extractHardInvalidations
```
✅ HTML 0 处 supporting_data 渲染。app.js 5 处全部在 v13→v12 反向映射 helpers 内部,**用户硬约束:helpers 保留**(它们用于 main_strategy 兜底)。

### 后端硬纪律

```
$ git diff --stat src/web_helpers/
(empty)
```
✅ `src/web_helpers/normalize_state.py` / `labels.py` 0 改动。
仅 `src/api/routes/system.py` 加 32 行 v13 layers 分支(D2 任务允许)。

### orphan helper 风险(段 3 详述)

旧 region-1 用过的、新 region-1 不再用的 helpers(`directionHero* / primaryDriversDisplay / counterArgumentsDisplay / whatWouldChangeMindDisplay / activeRiskTags / gradeLabel / permissionClass / tradePlanTier* / stopLossBasis / positionCapExplain / jumpToCard / showPositionPreviewPlaceholder / strategyFallbackNarrative / strategyDirection`)**全部保留没删**。

理由:用户 diff 只新增 13 个 cardX helper,**未明确指示删除旧 helper**,严格按 diff 复制粘贴 → 不删。CLAUDE.md §X 工程纪律确实要求"新代码替代旧代码必须删旧代码",但本 sprint 严格按用户 diff,§X 留作 1.8.2-D.1 follow-up sprint。

---

## 段 2:用户 SSH 验证脚本

```bash
ssh user@124.222.89.86 << 'EOF'
cd /opt/btc_swing_system
git pull origin main          # ⚠️ 等本地 push 后再做
sudo systemctl restart btc-swing-api
sleep 3

# D2 验证:health-detail v13 路径
echo '=== /api/system/health-detail (v13 期望全 healthy)==='
curl -s -u admin:Y_RhcxeApFa0H- http://localhost:8000/api/system/health-detail \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
for layer in d.get('evidence_layers', []):
    print(f\"L{layer['layer_id']}: {layer.get('health')} ({layer.get('pillars_summary')})\")"

# state schema 验证
echo
echo '=== /api/strategy/current schema ==='
curl -s -u admin:Y_RhcxeApFa0H- http://localhost:8000/api/strategy/current \
  | python3 -c "
import sys, json
s = json.load(sys.stdin)['state']
print('schema:', s.get('schema_version'))
print('summary_card:', bool(s.get('summary_card')))
print('layer_cards count:', len(s.get('layer_cards') or []))
print('anti_patterns_active:', s.get('anti_patterns_active') or [])
print('extreme_events_active:', s.get('extreme_events_active') or [])
"
EOF
```

### 浏览器手测清单(F12 + 强制刷新 ⌘+Shift+R)

- ✅ 顶部"当前决策"摘要 **消失**
- ✅ 警告条 **正常时隐藏**(`anti_patterns_active` / `extreme_events_active` 都空 → x-show=false);**异常时显示**(任一非空 → 显示对应玫红/琥珀条)
- ✅ 🩺 系统自检:**5 层证据全显示 healthy 绿点**(D2 v13 layers 路径生效)
- ✅ region-1 AI 策略建议:
  - 第 1 行核心决策:方向 / 状态 / 机会等级 / 信心指数(4 卡)
  - 第 2 行交易计划:入场区间 / 止损价 / 止盈分批 / 仓位上限(4 卡)
  - 第 3 行持仓状态:**FLAT/PLANNED 状态下整行隐藏**;开仓后显示 4 卡(浮盈 / 距止损 / 时长 / 硬失效位)
  - 第 4 行未来 72H 事件:1 卡(列出事件或"无登记事件")
- ✅ region-3 消失(1.8.2-C 已删)
- ✅ region-layer-cards 完整(6 卡,默认折叠)
- ✅ region-4 原始数据因子完整(46 项,5 组分类)
- ✅ region-5 历史与复盘在
- ✅ F12 console **无 JS 报错**

---

## 段 3:同类风险

1. **13 卡 helpers 依赖 `tp()` 和 v12 路径兜底**:`cardEntryZones / cardStopLoss / cardTakeProfits / cardPositionCap / cardConfidence` 全靠 `this.tp()`,`tp()` 优先读 `state.adjudicator.trade_plan`(v12) → fallback `state.trade_plan`。**v13 路径下 trade_plan 未在 normalize_state 中暴露在顶层**,只在 `_to_display_state_v13()` 把 master.trade_plan 映射到 main_strategy(可能);如未映射,这 5 卡显示 `—`。
   缓解:1.10 normalize_state 直接生成 `state.trade_plan` 顶层字段,前端可去掉派生。

2. **Orphan helpers 未删**(见红线段):约 14 个旧 region-1 helper 现已无 callsite,但仍占据约 200 行 app.js。**功能无影响,但 CLAUDE.md §X 工程纪律要求删除**。
   缓解:开 1.8.2-D.1 follow-up sprint,git grep 确认无 callsite 后批量删 + tests 跑一遍。

3. **微 deviation `lg:col-span-5`**(段 1 已披露):若用户严格要求纯 `audit-card`,1 行 Edit 即可还原;但页面将在 lg 屏被收窄到 1/5,需同步删外层 grid wrapper 才不破。

4. **D2 health-detail v13 路径的 `degraded*` 模糊匹配**:用户描述"status startswith 'degraded'"。我用 `status_raw.startswith("degraded")`,但实际 orchestrator 可能写 `"degraded_high_volatility"` / `"degraded_data_missing"` 等子状态。所有以 "degraded" 开头的都判 degraded — 符合用户意图。其他状态(如 `"failed"` / `"timeout"`)归 missing — 比较保守,可能掩盖某些"软错误"。
   缓解:必要时显式列出 status 枚举做精确映射,1.10 与 orchestrator schema 对齐。

5. **新警告条没 transition 入口**:1.8.2-B 老摘要里有 `validator_passed` 标识(✅/⚠️),新设计删了。但 `state.validator.passed` 仍能在 layer_cards 的 master 卡里看到(展开后)。如果用户希望 validator 状态有更显眼的入口,可在顶部全局状态条加 1 列。
   缓解:本 sprint 范围内不加,等用户反馈是否需要。

---

## 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅(全套 980 passed, 1 skipped) |
| GitHub push(commit hash:见末尾) | ❌ **故意不 push** — 等用户 SSH 实证摘要消失 + health-detail 全 healthy + 13 卡渲染对再 push |
| 服务器 git pull | 待用户执行(且 push 后) |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A(纯 endpoint 改动 + 前端) |

---

## 本 sprint 删除清单

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| `<section x-show="state.summary_card">...</section>` "当前决策"摘要 | `web/index.html`(原 89-122) | D1:用户要求删除,警告条迁移到独立 section |
| 旧 region-1 整段(7 行 grid + Row1-Row7 + Row 7 现货解读 + narrative + 论据 + 硬失效 + 事件 + 风险标签 + 改判触发) | `web/index.html`(原 259-519) | D3:替换为 13 张小卡新结构 |
| (helpers 未删) | `web/assets/app.js` | 见段 3 风险 #2:由 1.8.2-D.1 follow-up 处理 |

**git grep 自检**(commit 前):
```bash
$ grep -n "当前决策\|state.summary_card.headline" web/   # 期望 0
(empty) ✅
```

---

## 测试记录

```
$ python -m pytest tests/ -q --tb=no
980 passed, 1 skipped, 360 warnings in 8.94s
```

---

## 下一步

CC 故意不 push,等用户:
1. 本地 dev server 起来看(可选)
2. 或主动 `git push origin main` 后 SSH 服务器看
3. 实证 4 件事:
   - 顶部摘要消失(警告条仅异常时显示)
   - 系统自检 5 层全 healthy
   - region-1 13 卡分 4 行,FLAT 时第 3 行隐藏
   - region-4 46 项 5 组完整
4. 用户认可 → push 1.8.2-B + 1.8.2-C + 1.8.2-D 三个 commit
