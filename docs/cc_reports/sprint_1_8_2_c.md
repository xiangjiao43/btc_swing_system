# Sprint 1.8.2-C:新增 layer_cards 渲染 + 删 region-3

## Triggers(偏离建模 / 需用户决策的点)

- 用户调研后明确:1.8.2-B 没加 layer_cards UI,Mod 1 改写为"从无到有"新增渲染区
- 严格按用户给的 ~50 行 HTML + 3 个 method 复制粘贴,无任何"自由发挥"
- 后端 0 改动(`src/web_helpers/normalize_state.py / labels.py / src/api/routes/strategy.py` 均未动)
- **未 push**:遵守用户红线"PUSH 前等用户 SSH 实证后才推"

---

## 段 1:做了什么

3 个修改,改 2 个文件:

| Mod | 文件 | 行号(改后) | 动作 | 行数 |
|---|---|---|---|---|
| 1 | `web/assets/app.js` | 189-198 | 新增 `layerCardsOpen / toggleLayerCard / layerCardOpen` 3 个 method(在 toggleDark 之后) | +12 |
| 1 | `web/index.html` | 539-624 | 新增 `<section id="region-layer-cards">`(6 张 layer 卡,密度 C 默认折叠,无 supporting_data) | +85 |
| 2 | `web/assets/app.js` | (原 539-592) | 删 `compositeCards / _composite_raw / compositeComposition / compositeRule / compositeInterpretation / compositeAffects / compositeCurrentAnalysis / compositeStrategyImpact / compositeMissingHint` 9 个 helper + 周围注释 | -56 |
| 2 | `web/index.html` | (原 533-615) | 删 `<!-- 右侧 40%:组合因子... -->` 注释 + 整个 `<section id="region-3">...</section>` | -82 |
| 2 | `web/index.html` | line 272 | `<section id="region-1" class="audit-card lg:col-span-3">` → `lg:col-span-5`(占满整行) | 替换 1 行 |

文件大小变化:
- `web/index.html`: 771 → 775 行(+4 净增:+85 layer_cards section, -82 region-3 删除, +1 col-span 替换)
- `web/assets/app.js`: 928 → 884 行(-44 净减:+12 layer card helpers, -56 composite helpers)

git diff --stat:
```
web/assets/app.js |  66 +++++--------------------
web/index.html    | 144 ++++++++++++++++++++++++++++--------------------------
2 files changed, 85 insertions(+), 125 deletions(-)
```

后端零改动验证:
```
$ git diff --stat src/
(empty)
```

---

## 红线遵守自检

### region-4 baseline 6 行(完成后内容必须仍存在)

```
$ grep -n "region-4\|原始因子\|factorGroups\|原始数据因子" web/index.html web/assets/app.js
web/assets/app.js:551:        factorGroups() {
web/assets/app.js:869:                for (const g of this.factorGroups()) {
web/index.html:627:    <!-- 📂 区域 4:原始因子(5 组,主要平铺 + 次要折叠) -->
web/index.html:629:    <section id="region-4" class="audit-card">
web/index.html:632:          <span>📂</span><span>原始数据因子</span>
web/index.html:641:        <template x-for="group in factorGroups()" :key="group.key">
```
✅ 6 行内容全部存在,行号因 Mod 1/2 净 +/- 平移(允许)。

### 其他保留区(不动)

```
$ grep -n 'id="region-' web/index.html
272:    <section id="region-1" class="audit-card lg:col-span-5">    ← 改 col-span,内容不动
539:    <section id="region-layer-cards" class="audit-card" ...>    ← 1.8.2-C 新增
629:    <section id="region-4" class="audit-card">                  ← 不动
711:    <section id="region-5" class="audit-card" ...>              ← 不动
```
✅ region-1 / region-4 / region-5 都在;region-3 已删除;新增 region-layer-cards;顶部 1.8.2-B 加的"当前决策"摘要区在 line ~89 仍存在(grep `当前决策` 验证)。

### 孤儿引用自检

```
$ grep -nE 'composite[A-Z][a-zA-Z]*\(|_composite_raw\(' web/index.html web/assets/app.js
(empty)
```
✅ 0 处遗留 — 9 个 composite helper 删干净了,且 region-3 模板里的 callsite 也全删。

```
$ grep -n "supporting_data\|支持数据" web/index.html
(empty)
```
✅ 0 处 supporting_data UI 渲染(用户硬约束:像代码,普通用户看不懂)。

> 注:`supporting_data` 在 `web/assets/app.js` 仍存在 3 处(`_extractGrade / _extractPermission / _extractHardInvalidations` 内),用于 v13→v12 反向映射喂给 region-1,**这是 1.8.2-B 加的内部 helper,不渲染给用户看**,符合用户硬约束。

---

## 段 2:用户 SSH 验证脚本 + 浏览器测试清单

### 后端 sanity 检查(应无变化)

```bash
ssh user@124.222.89.86 << 'EOF'
cd /opt/btc_swing_system
git pull origin main          # ⚠️ 等本地 push 后再做
sudo systemctl restart btc-swing-api
sleep 3
curl -s -u admin:Y_RhcxeApFa0H- http://localhost:8000/api/strategy/current \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
s = d['state']
print('schema_version:', s.get('schema_version'))
print('layer_cards count:', len(s.get('layer_cards') or []))
print('summary_card present:', bool(s.get('summary_card')))
"
EOF
```
**期望**(v13 run):`schema_version: v13` + `layer_cards count: 6` + `summary_card present: True`
**期望**(v12 run):`schema_version: v12` + `layer_cards count: 6`(normalize 后)/ 或更少(取决于 v12 evidence_reports 完整性)+ `summary_card present: True`

### 浏览器手测清单(F12 + 强制刷新 ⌘+Shift+R)

- ✅ 顶部"当前决策"摘要区(1.8.2-B 加的)还在
- ✅ region-1 AI 策略建议区**占满整行**(原 60% → 100%,因为 region-3 删了)
- ✅ **新区"🔬 五层分析"出现**:6 张卡片(L1/L2/L3/L4/L5/master),默认折叠,展示 `title / label / secondary_labels / summary` + "查看详细 ▼" 按钮
- ✅ 点"查看详细 ▼" → 展开 `key_observations` + `narrative` + `contradicting_signals` 三段;**展开区无"支持数据"代码框**
- ✅ region-3 "组合因子" 模块**整个消失**
- ✅ region-4 "原始数据因子" **完整**(46 个原始因子,5 组分类:价格技术 / 衍生品 / 链上 / 宏观 / 事件)
- ✅ region-5 "历史与复盘" 在
- ✅ Footer 在
- ✅ F12 console **无 JS 报错**(特别注意:Alpine 不会因为 `compositeCards()` 没了而抱怨,因为 region-3 模板已删)

---

## 段 3:同类风险

1. **layer_cards 数据契约**:新区依赖 `state.layer_cards[i].{layer, title, label, secondary_labels, summary, key_observations, narrative, contradicting_signals}` — 这些字段全部由 `normalize_state.py` 后端产出。若后续 `normalize_state` 改字段名(比如把 `key_observations` 改成 `observations`),前端 `x-text="obs"` 会变 `undefined`,**不崩,但展开区会显示空 ul**。
   缓解:`tests/web_helpers/test_normalize_state.py` 已锁定 39 个字段断言;改 normalize_state 时同步检查 `web/index.html:539-624` 的 x-text/x-show 引用。

2. **`x-cloak` 依赖样式**:展开区用 `x-cloak`,需要 `web/assets/styles.css` 里有 `[x-cloak] { display: none !important; }` 规则才生效。**未验证 styles.css 是否有此规则**;如缺失,展开区会在 Alpine 加载前一闪。
   缓解:用户可 F12 看 DOM,如有闪现可在 styles.css 加 1 行规则修复。

3. **删除的 9 个 composite helpers 是否在其他地方被引用**:已 grep 确认 `web/` 子树 0 处遗留。但仓库其他地方(测试 / docs / 老 sprint 报告)可能有文字提及,**这不影响功能**,只影响读 docs 时的术语一致性。
   缓解:1.10 之后做 `docs/` cleanup 时同步处理。

---

## 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅(`tests/web_helpers/` 39 + `tests/test_api_routes*` + `tests/test_strategy_stream_overlays_latest.py` 共 65 pass) |
| GitHub push(commit hash:见末尾) | ❌ **故意不 push** — 等用户 SSH 实证看到 region-3 消失 + 五层分析 / region-4 完整再 push |
| 服务器 git pull | 待用户执行(且 push 后) |
| 服务器 systemctl restart | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A(纯前端,后端 0 改动) |

---

## 本 sprint 删除清单

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| `<section id="region-3">` 整段 | `web/index.html`(原 535-615) | 1.8.2-C 用"五层分析"卡区替代;v1.3 orchestrator 不再产 `composite_factors` 6 keys |
| `<!-- 右侧 40%:组合因子紧凑版... -->` 注释 | `web/index.html`(原 534) | region-3 一起删 |
| `compositeCards()` | `web/assets/app.js`(原 539-549) | 服务于 region-3 |
| `_composite_raw()` | `web/assets/app.js`(原 551-555) | 服务于 region-3 |
| `compositeComposition()` | `web/assets/app.js`(原 556-559) | 服务于 region-3 |
| `compositeRule()` | `web/assets/app.js`(原 560-563) | 服务于 region-3(注:仓库 grep 显示 region-3 模板没用 `compositeRule`,但用户 diff 让删,一并删) |
| `compositeInterpretation()` | `web/assets/app.js`(原 564-567) | 同上 |
| `compositeAffects()` | `web/assets/app.js`(原 568-571) | 同上 |
| `compositeCurrentAnalysis()` | `web/assets/app.js`(原 574-577) | 服务于 region-3 |
| `compositeStrategyImpact()` | `web/assets/app.js`(原 578-581) | 服务于 region-3 |
| `compositeMissingHint()` | `web/assets/app.js`(原 582-592) | 服务于 region-3 |

**git grep 自检**(commit 前):
```bash
$ grep -nE 'composite[A-Z][a-zA-Z]*\(|_composite_raw\(' web/
(empty) ✅
```

---

## 测试记录

```
$ python -m pytest tests/web_helpers/ tests/test_api_routes.py tests/test_api_routes_new.py tests/test_strategy_stream_overlays_latest.py -q
65 passed, 132 warnings in 1.23s
```

normalize_state 单测 39/39 全过 — Mod 1/2 都是纯前端改动,后端 0 影响。

---

## 下一步

CC 故意不 push,等用户:
1. 本地 dev server 起来看新"五层分析"区(可选)
2. 或用户主动 `git push origin main` 后 SSH 服务器看
3. 实证 region-3 消失 + 五层分析渲染 + region-4 完整 + console 无报错 → 用户认可后 push
