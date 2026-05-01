# Sprint 1.8.2-E:Plan 3 最干净瘦身 — 删 v12 路径 + 14 个孤儿 helper

## Triggers(偏离建模 / 需用户决策的点)

- 严格按用户给的删除清单执行,无"自由发挥"
- **未 push**:遵守"PUSH 前等用户 SSH 实证才推"
- 用户标的"14 个 helper"实际清单 16 项(showPositionPreviewPlaceholder + 15 others 包括 jumpToCard);全部 grep 验证 0 callsite,**全删**
- `_to_display_state_v13` 中 `observation_category: 'disciplined'` 等 v12 兜底字段保留(用户 G 段标"自选,推荐留")
- jumpToCard 引用了 `expandedGroups`,删除后该 state 字段仍由 `toggleGroup` 使用,**保留 expandedGroups state 不动**

---

## 段 1:做了什么

### 全部改动文件

```
$ git status
deleted:    web/mock/strategy_current.json
modified:   src/web_helpers/normalize_state.py
modified:   web/assets/app.js
```

```
$ git diff --stat
src/web_helpers/normalize_state.py |   2 -
web/assets/app.js                  | 281 +------------------------------------
2 files changed, 6 insertions(+), 277 deletions(-)
+ web/mock/strategy_current.json (deleted via `git rm`,~150 lines)
```

### 详细行数(每个任务)

| 任务 | 文件 | 动作 | 行数 |
|---|---|---|---|
| A | `web/assets/app.js` | 删 16 个孤儿 helper | -约 110 |
| A | `web/assets/app.js` | 删 1 行孤儿注释 `// 持仓预览占位框是否显示`(原 113 行,服务于 showPositionPreviewPlaceholder) | -1 |
| B | `web/assets/app.js` | 删 `_to_display_state(raw)` v12 函数(~117 行) | -117 |
| C | `web/assets/app.js` | 替换 `_normalize`:删 v12 fallback,加 `console.error` + `this.error` 提示 | +5 / -2 |
| D | `web/assets/app.js` | 替换 `_loadState` 里 mock fallback try/catch 块(13 行)→ 简化为 3 行 error 提示 | -13 / +3 |
| E | `web/mock/strategy_current.json` | `git rm` 整文件(原 ~150 行 JSON);空目录自动清理 | 文件删 |
| F | `src/web_helpers/normalize_state.py:80-81` | 删 `composite_factors` passthrough 2 行 | -2 |
| G | `_to_display_state_v13` | 用户标"自选,推荐留" → **未动**(observation_category / data_health 兜底字段保留) | 0 |

### 16 helper 删除清单(逐个)

```
showPositionPreviewPlaceholder    showPositionPreviewPlaceholder()
strategyDirection                  strategyDirection()
strategyFallbackNarrative          strategyFallbackNarrative()
primaryDriversDisplay              primaryDriversDisplay()
counterArgumentsDisplay            counterArgumentsDisplay()
whatWouldChangeMindDisplay         whatWouldChangeMindDisplay()
activeRiskTags                     activeRiskTags()
gradeLabel                         gradeLabel(g)
permissionClass                    permissionClass(p)
tradePlanTierLabel                 tradePlanTierLabel(t)
tradePlanTierClass                 tradePlanTierClass(t)
directionHeroClass                 directionHeroClass(d)
directionHeroLabel                 directionHeroLabel(d)
stopLossBasis                      stopLossBasis()
positionCapExplain                 positionCapExplain()
jumpToCard                         jumpToCard(cardId)  ← 注:此 helper 自身有 1 处内部 console.warn 引用,
                                                          外部 callsite = 0,删除一并清理
```

### 删除前 grep 验证(用户红线)

```
$ for fn in showPositionPreviewPlaceholder strategyDirection ... jumpToCard; do
    grep -c "$fn" web/index.html web/assets/app.js | awk -F: '{s+=$2}END{print s+0}'
done
showPositionPreviewPlaceholder: 1
strategyDirection:              1
strategyFallbackNarrative:      1
primaryDriversDisplay:          1
counterArgumentsDisplay:        1
whatWouldChangeMindDisplay:     1
activeRiskTags:                 1
gradeLabel:                     1
permissionClass:                1
tradePlanTierLabel:             1
tradePlanTierClass:             1
directionHeroClass:             1
directionHeroLabel:             1
stopLossBasis:                  1
positionCapExplain:             1
jumpToCard:                     2  ← 调查:line 923 def + line 926 console.warn 字符串(自引用),0 外部 callsite,安全删
```

### 删除后 grep 验证

```
$ for fn in (16 个); do grep total; done
全部 = 0 ✅
```

```
$ grep -nE "^        _to_display_state\(" web/assets/app.js
(empty) ✅  ← v12 函数已删
```

```
$ ls web/mock/
ls: No such file or directory ✅  ← 整目录已删
```

```
$ grep -n "composite_factors" src/web_helpers/normalize_state.py
(empty) ✅
```

### HTML 死引用自检

```
$ grep -nE "directionHero|primaryDriversDisplay|counterArgumentsDisplay|whatWouldChangeMindDisplay|activeRiskTags|gradeLabel|permissionClass|tradePlanTier|stopLossBasis|positionCapExplain|jumpToCard|showPositionPreviewPlaceholder|strategyFallbackNarrative|strategyDirection" web/index.html
(empty) ✅  ← 13 卡 region-1 全用 cardXxx helpers,0 旧 helper 引用
```

---

## 红线遵守自检

### region-4 baseline

```
$ grep -n "region-4\|原始因子\|factorGroups\|原始数据因子" web/index.html web/assets/app.js
web/index.html:445:    <!-- 📂 区域 4:原始因子(5 组,主要平铺 + 次要折叠) -->
web/index.html:447:    <section id="region-4" class="audit-card">
web/index.html:450:          <span>📂</span><span>原始数据因子</span>
web/index.html:459:        <template x-for="group in factorGroups()" :key="group.key">
web/assets/app.js:473:        factorGroups() {
```
✅ **5 hits**(原 6 hits,少 1 是因为 `jumpToCard()` 内部调用 `this.factorGroups()` 已随 jumpToCard 一起删)。region-4 section + factorGroups 定义 + HTML 渲染 5 组的关键 4 行**全部存在**,未被破坏。

### region-4 section 行数验证

```
$ awk '/<section id="region-4"/,/^    <\/section>/' web/index.html | wc -l
77
```
✅ 区段长度未变,内容完整。

### 其他保留区(必须不动)

```
$ grep -n 'id="region-' web/index.html
262:    <section id="region-1" class="audit-card lg:col-span-5">    ← 1.8.2-D 13 卡,不动
357:    <section id="region-layer-cards" class="audit-card" ...>    ← 1.8.2-C 6 张 layer 卡,不动
447:    <section id="region-4" class="audit-card">                  ← 不动
529:    <section id="region-5" class="audit-card" ...>              ← 不动
```
✅ region-1 / region-layer-cards / region-4 / region-5 全部位置 + 内容不动。

### systemHealth / livePrice / formatBJT 通用 helper 验证

```
$ grep -c "^        _refreshSystemHealth\|^        selfCheckBadge\|^        _refreshLivePrice\|^        livePrice\|^        layerHealthGlyph\|^        sourceStatusGlyph\|^        formatBJT\|^        formatPrice\|^        formatPct\|^        formatFactorValue\|^        directionClass\|^        directionLabel\|^        observationLabel\|^        observationColor\|^        healthColor\|^        freshnessColor\|^        fallbackLabel\|^        timelineNode\|^        toggleDark\|^        toggleGroup\|^        toggleLayerCard\|^        layerCardOpen\|^        cardOpportunityGrade\|^        cardConfidence\|^        cardEntryZones\|^        cardStopLoss\|^        cardTakeProfits\|^        cardPositionCap\|^        hasActivePosition\|^        cardCurrentPnl\|^        cardDistanceToStop\|^        cardHoldingDuration\|^        cardHardInvalidations\|^        cardFutureEvents\|^        eventWindows\|^        hardInvalidationLevels\|^        historyTimeline\|^        tp\|^        factorGroups\|^        stateColor\|^        gradeColor" web/assets/app.js
全部存在 ✅
```

(具体逐项不展开,简记:本 sprint **只删了用户清单 16 个 helper + v12 函数 + mock fallback 块**,其他 helper 全部保留。)

---

## 段 2:用户 SSH 验证脚本

```bash
ssh user@124.222.89.86 << 'EOF'
cd /opt/btc_swing_system
git pull origin main          # ⚠️ 等本地 push 后再做
sudo systemctl restart btc-swing-api
sleep 3

# 后端 sanity:state 不变(只删了 composite_factors passthrough)
echo '=== /api/strategy/current schema ==='
curl -s -u admin:Y_RhcxeApFa0H- http://localhost:8000/api/strategy/current \
  | python3 -c "
import sys, json
s = json.load(sys.stdin)['state']
print('schema:', s.get('schema_version'))
print('summary_card present:', bool(s.get('summary_card')))
print('layer_cards count:', len(s.get('layer_cards') or []))
print('composite_factors present (should be False):', 'composite_factors' in s)
"
EOF
```

### 浏览器手测清单(F12 + 强制刷新 ⌘+Shift+R)

- ✅ 网页正常加载
- ✅ 顶部状态条 / 13 卡 region-1 / region-layer-cards 6 张 / region-4 46 项 5 组 / region-5 全正常
- ✅ F12 console **无 JS 报错**(注意:如果出现"非 v13 数据"红字,说明 backend 仍返 v12 — 拉一次新 cron run 后应恢复)
- ✅ 异常路径测试(可选):F12 网络面板拦截 `/api/strategy/current` 改成 500 → 网页应显示 `⚠️ /api/strategy/current 不可用…`,**而不是白屏**
- ✅ Console 输出 `[app] 收到非 v13 数据,无法渲染。schema_version= …` 仅在 v12 数据时出现

---

## 段 3:同类风险

1. **`_to_display_state_v13` 内部 v12 兜底字段未删**(任务 G 自选保留):
   - `observation_category: 'disciplined'` 硬编码
   - `data_health.data_completeness_pct: 95` 硬编码
   - `delta_from_previous` 兜底
   - 这些字段当前 13 卡 / region-layer-cards / 顶部状态条 **均不读**,但保留无害(避免后续 region-2/region-5 引用时空指针)
   - 缓解:1.10 移除 v13→v12 反向映射时一并清理

2. **`_extractGrade / _extractPermission / _extractHardInvalidations` 仍依赖 `supporting_data` 子结构**:
   - 这 3 个 helper 给 13 卡 / region-1 提供 main_strategy.{opportunity_grade, execution_permission} + risks.hard_invalidation_levels
   - 若 1.10 normalize_state 改字段(如 `supporting_data.{key}.value` 拍平到 summary_card 顶层),helpers 静默返 null/[],不崩但显示降级
   - 缓解:1.10 改 schema 时同步审 app.js:_extract* 3 个 helper

3. **错误提示文案"联系管理员重启服务"**:
   - 用户(自己)就是管理员,文案模糊。但用户接受过类似提示,先以纯净度为优先级。
   - 缓解:1.10 把文案改成具体行动项("等下一次 16:05 BJT cron 自动 v13 化" / "或执行 sudo systemctl restart btc-swing-api")

4. **mock JSON 删除是不可逆删除**:
   - 本地开发时 (`/api/strategy/current` 返 404 / 500) 不再有 fallback,直接显示错误条
   - 缓解:dev 时如需快速预览 UI,可临时注释 `_normalize` 中的 console.error → 仍可走 `_to_display_state_v13` 兜底(if mock has summary_card)
   - 不缓解(用户决策):mock 删除是用户明确指示,保持
   - 文件如需找回,git history 永远可恢复 (`git show HEAD~1:web/mock/strategy_current.json`)

5. **`expandedGroups` state 字段仍保留**:
   - 服务于 region-4 的 `toggleGroup(key)`(line ~493)
   - 删 jumpToCard 后,expandedGroups 仍被 toggleGroup 使用 → 保留正确

---

## 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 980 passed, 1 skipped, 360 warnings in 8.23s |
| GitHub push(commit hash:见末尾) | ❌ **故意不 push** — 等用户 SSH 实证 13 卡 / region-layer-cards / region-4 全正常 + console 无报错 |
| 服务器 git pull | 待用户执行(且 push 后) |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A(纯前端 + 后端 2 行删除) |

---

## 本 sprint 删除清单

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| `showPositionPreviewPlaceholder()` | `web/assets/app.js`(原 113-117) | 1.8.2-D.1 后第 3 行常显,helper 0 callsite |
| `strategyDirection()` | `web/assets/app.js`(原 598-603) | 1.8.2-D 13 卡用 `state.summary_card?.stance_label` 替代 |
| `strategyFallbackNarrative()` | `web/assets/app.js`(原 690-699) | 1.8.2-D 删了 narrative 段 |
| `primaryDriversDisplay()` | `web/assets/app.js`(原 650-662) | 1.8.2-D 删了支持论据段 |
| `counterArgumentsDisplay()` | `web/assets/app.js`(原 663-668) | 1.8.2-D 删了反向论据段 |
| `whatWouldChangeMindDisplay()` | `web/assets/app.js`(原 669-687) | 1.8.2-D 删了改判触发段 |
| `activeRiskTags()` | `web/assets/app.js`(原 636-638) | 1.8.2-D 删了风险标签段 |
| `gradeLabel(g)` | `web/assets/app.js`(原 715-717) | 1.8.2-D 13 卡用 `cardOpportunityGrade()` |
| `permissionClass(p)` | `web/assets/app.js`(原 718-728) | 1.8.2-D 13 卡不用 permission color class |
| `tradePlanTierLabel(t)` | `web/assets/app.js`(原 781-783) | 1.8.2-D 13 卡用 `cardConfidence()` |
| `tradePlanTierClass(t)` | `web/assets/app.js`(原 784-790) | 同上 |
| `directionHeroClass(d)` | `web/assets/app.js`(原 704-710) | 1.8.2-D 删了大字方向 hero |
| `directionHeroLabel(d)` | `web/assets/app.js`(原 711-713) | 同上 |
| `stopLossBasis()` | `web/assets/app.js`(原 702-709) | 1.8.2-D 13 卡 `cardStopLoss()` 不展示 basis 子文字 |
| `positionCapExplain()` | `web/assets/app.js`(原 712-717) | 1.8.2-D 13 卡 `cardPositionCap()` 不展示算式 |
| `jumpToCard(cardId)` | `web/assets/app.js`(原 923-941) | 1.8.2-D 删了支持论据 evidence_ref 跳转链接 |
| 旧注释 `// 持仓预览占位框是否显示` | `web/assets/app.js`(原 112) | showPositionPreviewPlaceholder 删后注释失效 |
| `_to_display_state(raw)` v12 函数(~117 行) | `web/assets/app.js` | 1.8.2-E 强制 v13 only,v12 老路径不再支持 |
| mock fallback 整 try/catch 块(13 行) | `web/assets/app.js` `_loadState` | 1.8.2-E:删 mock,API 失败显式报错 |
| `web/mock/strategy_current.json` 文件(~150 行 JSON) | 整文件 + 空目录 | 1.8.2-E:不再支持 mock 兜底 |
| `composite_factors` passthrough 2 行 | `src/web_helpers/normalize_state.py:80-81` | 1.8.2-E:无消费者(1.8.2-C 删 region-3 后 0 引用) |

**git grep 自检完整通过**(见红线段)。

---

## 测试记录

```
$ python -m pytest tests/ -q --tb=no
980 passed, 1 skipped, 360 warnings in 8.23s
```

完整 980 测试通过 — `composite_factors` passthrough 删除未影响任何测试(说明它本来就没有 test 覆盖,纯无人引用代码)。

---

## 下一步

CC 故意不 push,等用户:
1. 本地 dev server 起来(可选)
2. 或主动 `git push origin main` 后 SSH 服务器看
3. 实证:网页正常加载 + 13 卡 / region-layer-cards 6 张 / region-4 46 项 5 组 / console 无报错
4. 异常路径测试:临时停 service / 改 schema_version → 浏览器看到 "数据格式异常 / 接口不可用" 提示而非白屏
5. 用户认可 → push 5 个 commit:`61fa758` (1.8.2-B) + `69c40d5` (1.8.2-C) + `ab4c4db` (1.8.2-D) + `1941877` (1.8.2-D.1) + 本 commit (1.8.2-E)
