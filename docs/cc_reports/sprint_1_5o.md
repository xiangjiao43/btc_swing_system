# Sprint 1.5o — 删除"五层证据推导细节"区 + 自检面板永远展开

**Date:** 2026-04-30
**Branch:** main
**Status:** ✅ 本地完成,23 个新测试 + 981/981 全量回归过

---

## 一、根因(用户 SSH 部署 1.5n 后反馈)

1. "五层证据推导细节"折叠区即使折叠也碍眼,占据屏幕空间,内容对用户无价值
2. 用户需要保留"数据是否成功抓取""五层是否成功初步分析"的健康信号
3. 自检面板(1.5n)默认折叠,起不到这个作用

用户决策:整块删除「五层证据推导细节」区(HTML + JS 渲染函数都删),
自检面板改成**永远展开 + 颜色醒目**,作为"系统是否在正常运作"的唯一入口。

---

## 二、改动

### 任务 A:整块删除「五层证据推导细节」区(commit `b4d5b78`)

**HTML(web/index.html)**:删除 `<section id="region-2">` 整段(142 行),
含 `<details>/<summary>` 折叠包装 + 5 层渲染模板(三支柱 / 四角度 /
L3 rule_trace / L4 chain / L5 macro / 综合结论 / 给下游建议 / 人话解读)。

**JS(web/assets/app.js)**:删除所有"为前端展示五层 evidence"的渲染函数:

| 函数 | 行 | 用途 |
|---|---|---|
| `_loadState` 中 evidence_summary 派生 5 层 for-of 循环(46 行) | 343-382 | 仅供已删区 |
| `_layer_verdict_from` | 443-451 | 同上 |
| `_confidence_numeric` | 437-442 | 同上 |
| `orderedLayers` | 467-471 | 同上 |
| `layerChineseName` | 869-871 | 同上 |
| `contributionLabel / contributionClass` | 800-810 | 同上 |
| `freshnessLabel / freshnessBadgeClass` | 175-187 | 同上 |
| `positionCapChainText / permissionChainText` | 697-720 | 同上 |

**保留**:`state.evidence_reports.layer_*` 数据本身(后端
`/api/system/health-detail` 仍直接读 health_status,自检面板正常工作)。

### 任务 B:自检面板永久展开 + 三段式视觉(commit `7f7b687`)

**HTML 改造**:
- 删除 `<button @click="toggleSelfCheck()">` + `x-show="selfCheckExpanded"`
- 5 层证据 + 5 数据源**永远直接显示**
- 容器边框:all_healthy → emerald-200 / partial → amber / critical → rose-400 + ring-1
- 每行加 `:title` hover tooltip:层显示 missing_reasons 或 pillars_summary;
  数据源显示 captured_at_bjt + expected_cadence

**视觉:三段式 glyph(替代原 1.5n 圆点)**:

| 状态 | Glyph | Tailwind class |
|---|---|---|
| healthy / ok | ● | text-emerald-500 |
| degraded / warn | ⚠ | text-amber-500 |
| missing / critical | ✗ | text-rose-500 font-bold |
| no_data | ○ | text-slate-400 |

文字颜色配套加强:critical 行 `font-medium/font-bold`,degraded 行 amber,
no_data 行 slate-400。

**JS 新 helper**:
- `layerHealthGlyph / layerHealthGlyphClass / layerHealthTextClass`
- `sourceStatusGlyph / sourceStatusGlyphClass`
- 删除 `toggleSelfCheck` / `selfCheckExpanded` / `_selfCheckUserToggled`

---

## 三、测试

### `tests/test_evidence_section_removed.py`(23 测试)

§X 反退化锁,确保未来不被恢复:

| 类别 | 测试 |
|---|---|
| HTML 删除 | region-2 整段 / "AI 分析过程" 标题 / 12 个老模板标记(【这层回答】等)|
| HTML 模板 | orderedLayers / layerChineseName / chain helpers / pillars 模板 0 处 |
| JS 函数定义 | 10 个函数(orderedLayers / layerChineseName / contributionLabel...) 0 处 |
| JS 数据派生 | evidence_summary 5 层 for-of 循环 0 处;chain text 字段 0 处 |
| 自检面板 | "🩺 系统自检" 仍在;无 toggleSelfCheck;有 layerHealthGlyph |

允许:Sprint 1.5o 解释性注释(标记已删除)— 测试用 `^\s*` 锚定函数定义
而非 substring,避免误伤注释。

### 全量回归

```
981 passed, 1 skipped, 7.33s
```

(958 baseline + 23 新 = 981)

---

## 四、改动文件

| 文件 | 改动 |
|---|---|
| `web/index.html` | 删除 region-2(142 行)+ 重写自检面板永久展开 |
| `web/assets/app.js` | 删除 ~120 行配套函数 + 新增 5 个 glyph helper |
| `tests/test_evidence_section_removed.py` | **新文件** 23 测试 §X 反退化 |

净影响:**-401 行,+231 行**(净 -170 行死代码)。

---

## 五、§X / §Y / §Z 自检

### §X(本 sprint 删除清单)

| 删除对象 | 路径 | 删除原因 |
|---|---|---|
| `<section id="region-2">` 整段 142 行 | web/index.html | 用户反馈无价值,健康信号已合并到自检面板 |
| `<details>/<summary>` 折叠包装 | 同上 | 整段已删 |
| `evidence_summary` 派生 5 层 for-of 循环 46 行 | web/assets/app.js | 仅供已删区 |
| `_layer_verdict_from` | 同上 | 同上 |
| `_confidence_numeric` | 同上 | 同上 |
| `orderedLayers` | 同上 | 同上 |
| `layerChineseName` | 同上 | 同上 |
| `contributionLabel` | 同上 | 同上 |
| `contributionClass` | 同上 | 同上 |
| `freshnessLabel` | 同上 | 同上 |
| `freshnessBadgeClass` | 同上 | 同上 |
| `positionCapChainText` | 同上 | 同上 |
| `permissionChainText` | 同上 | 同上 |
| `toggleSelfCheck / selfCheckExpanded / _selfCheckUserToggled` | 同上 | Task B 永久展开,toggle 不再需要 |

git grep 自检全过(`grep -c "<被删函数>" web/index.html web/assets/app.js`
全部 0 处,除 Sprint 1.5o 解释性注释 2 处)。

### §Y
3 个 commit + 1 个报告 commit,一次性 push。

### §Z(测试用 substring + 函数定义锚定)
- `^\s*<fn_name>\s*\(` 正则锚定函数定义(避免误伤注释引用)
- `[[1,'layer_1']` 关键签名断言数据派生循环已删
- 12 个老模板标记 substring 断言
- glyph helper 存在断言(确认 Task B 视觉实施)

### 同类风险扫描
- **alpine 模板渲染崩溃风险**:已删除 `state.evidence_summary` 派生,
  其他模块未引用 → SSH 主观验收前端不报错
- **后端 `/api/system/health-detail` 不依赖前端**:它直接读
  `state.evidence_reports.layer_*.health_status`,与前端 evidence_summary
  无关,Task A 删除前端不影响后端
- **未删除的 `evidence_reports` 数据**:仍在 strategy_state JSON 里完整保留,
  其他 sprint(如 lifecycle / review)若要用仍可读

---

## 六、部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 981 passed, 1 skipped, 7.33s |
| GitHub push(commit hashes:`b4d5b78..`,见下) | ✅ |
| 服务器 git pull | ❌ 等用户 SSH 执行 |
| 服务器 systemctl restart | ❌ 等用户 SSH 执行 |
| 生产 DB 迁移 / 清污 | N/A 无 schema 改动 |

### SSH 部署 + 主观验证

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service
sleep 5
SSH
```

打开 http://124.222.89.86 主观验收:
- ✅ 顶部:BTC 价格 + 系统状态条
- ✅ 顶栏正下方:🩺 系统自检面板,**永远展开**,5 层 + 5 数据源直接可见
- ✅ 当前若全 healthy:5 层全是 ● 绿点,5 数据源也是 ● 绿点
- ✅ 「AI 策略建议」区(策略说明 4 段)
- ✅ 持仓预览灰色虚框(FLAT 状态显示)
- ✅ 「组合因子 6 个」依然显示
- ✅ 「原始数据因子 41 个」依然显示
- ✅ **不再出现**「五层证据推导细节」「AI 分析过程」等区
- ✅ 历史区仍隐藏(没历史)

---

## 七、未覆盖 / 留 v0.6

- **自检面板布局在手机上**:`grid-cols-1 md:grid-cols-2` 处理,
  如效果差留 1.5o.1 续修
- **dark mode 颜色对比度**:三段式 glyph 在 dark 下用了 emerald-500 /
  amber-500 / rose-500,需要主观验收
- **hover tooltip 仅 desktop**:手机长按可能不触发,如要可见 missing_reasons,
  未来可考虑常驻显示而非 hover
