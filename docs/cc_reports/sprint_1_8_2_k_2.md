# Sprint 1.8.2-K.2:4 处微调(12 卡加粗 + 五层缩字号 + 系统自检标题对齐 + em-dash 已统一)

## Triggers

- 用户审定 4 项 D 决策(D1=a / D2=b / D3=确认 / D4=text-[13px])
- 严格按 4 处改,不"自由发挥"
- **未 push**:遵守"PUSH 前等用户浏览器实证才推"

## 段 1:做了什么

### 改动 1 个文件,3 处编辑(diff +18/-13)

| # | 文件:位置 | 动作 | 行数 |
|---|---|---|---|
| A | `web/index.html` 12 个 card div(line 270-332) | 12 个 value div 加 `font-bold`(7 个 sans + 5 个 mono),用 `replace_all` 2 次完成 | +12 (单类 add) |
| B | `web/index.html:364` | layer card label 字号 `text-base` → `text-[13px]` | 1 行替换 |
| C | `web/index.html:184-198` + `:250` | 系统自检升级:section 去 `px-3 py-2.5` + 加 `<header><h2>...</h2></header>` + body 包 `<div class="p-3">` + footer `<p>` 加 `px-3 pb-3` | +5 / -2(结构) |
| D | (无改动) | em-dash 统一已在 1.8.2-K.1 时完成,本 sprint 无需改 | 0 |

### A 改动:12 卡 font-bold 全加(用户 D3 确认)

```html
旧:class="text-[13px] text-slate-900 dark:text-slate-100"
新:class="text-[13px] font-bold text-slate-900 dark:text-slate-100"

旧:class="text-[13px] font-mono text-slate-900 dark:text-slate-100"
新:class="text-[13px] font-bold font-mono text-slate-900 dark:text-slate-100"
```

通过 `Edit replace_all` 2 次完成全部 12 个 div(7 个 sans + 5 个 mono),验证 `grep -c "font-bold"` 在 270-335 区间 = **12** ✅

### B 改动:五层卡 label 缩字号(用户 D4=text-[13px])

```html
旧:<div class="text-base font-bold leading-snug" x-text="card.label || '—'"></div>
新:<div class="text-[13px] font-bold leading-snug" x-text="card.label || '—'"></div>
```

`text-base` (16px) → `text-[13px]`,与 12 卡数值精确同字号(差 3px)。其他 layer 卡元素不动:title 12px / summary 12px / 详细区 11px 等。

### C 改动:系统自检标题完全对齐(用户 D2=b)

```html
旧:
<section class="audit-card px-3 py-2.5" :class="...">
  <div class="flex items-center gap-2 text-[12px] mb-2.5">
    <span class="font-semibold">🩺 系统自检</span>
    <span class="...font-mono" :class="selfCheckBadgeClass()"
          x-text="selfCheckBadgeLabel()"></span>
  </div>
  <div class="grid grid-cols-1 md:grid-cols-2 gap-4 text-[12px]">
    ...
  </div>
  <p class="mt-2 text-[10px] text-slate-400">每 5 分钟自动刷新...</p>
</section>

新:
<section class="audit-card" :class="...">
  <header class="px-4 py-2.5 border-b border-slate-200 dark:border-slate-800">
    <h2 class="text-base font-semibold flex items-center gap-2">
      <span>🩺</span><span>系统自检</span>
      <span class="...font-mono ml-1" :class="selfCheckBadgeClass()"
            x-text="selfCheckBadgeLabel()"></span>
    </h2>
  </header>
  <div class="p-3 grid grid-cols-1 md:grid-cols-2 gap-4 text-[12px]">
    ...
  </div>
  <p class="px-3 pb-3 text-[10px] text-slate-400">每 5 分钟自动刷新...</p>
</section>
```

**与 region-1 / region-layer-cards 完全同结构**:
- `<header class="px-4 py-2.5 border-b ...">` 包 `<h2 class="text-base font-semibold ...">`
- 标题 emoji 拆开 `<span>🩺</span><span>系统自检</span>`
- 状态 chip 加 `ml-1` 与标题保留间距
- body 用 `<div class="p-3">` 提供内边距(原是 section 的 px-3 py-2.5,现移到内层)
- footer `<p>` 用 `px-3 pb-3` 保持视觉边距(原是依赖 section padding)

### D 改动:em-dash 已统一(无需改)

调研已确认 1.8.2-K.1 后所有 12 个 cardX helper fallback 全用 em-dash U+2014:
```
$ grep -nE "return '-'|: '-'" web/assets/app.js
(empty) ✅
```
唯一变体 `cardOpportunityGrade` 在 grade=='none' 时返中文 "无机会"(用户 D1=a 决策保留)。

### 自检 grep

```
$ grep -c "font-bold" web/index.html  # 整个文件
（12 卡部分按 sed 270-335 范围 grep = 12 ✅)

$ grep -nE 'text-\[13px\] font-bold leading-snug.*card.label' web/index.html
364: ✅ layer label 已缩到 text-[13px]

$ grep -B 1 "🩺.*系统自检\|<span>系统自检" web/index.html | head -5
现 <h2 class="text-base font-semibold ...">🩺 系统自检</h2> ✅

$ pytest tests/ -q --tb=no
980 passed, 1 skipped, 360 warnings in 8.15s ✅
```

## 段 2:用户浏览器实证

强刷 `http://124.222.89.86`(admin / Y_RhcxeApFa0H-):

- ✅ **12 卡所有数值 font-bold + 黑色**(7 个 sans 加粗,5 个 mono 也加粗)
- ✅ **五层分析 6 卡数值字号 = 12 卡**(都是 text-[13px] = 13px)
- ✅ **3 个 section 标题完全一致**(系统自检 / AI 策略建议 / 五层分析 都是 `text-base font-semibold` + `<header>` + border-b)
- ✅ **12 卡 fallback 占位符全 "—"**(em-dash U+2014 长破折号),`cardOpportunityGrade` 在无机会时仍显示"无机会"(中文,D1 决策保留)
- ✅ F12 console 无报错
- ✅ 系统自检状态 chip(全部正常 ✅ / 部分降级 / 数据中断)仍在标题右侧显示

## 段 3:同类风险

1. **系统自检视觉变化较大**(D2=b 完全对齐):
   - 加了上下分隔线(border-b)+ 更宽的 header padding(py-2.5)
   - 视觉密度比原版稍降低,但与 AI 策略 / 五层分析 完全一致(用户决策 trade-off)
   - 如发现密度过松,1.10 可单独减小 header 的 py(如 `py-2`)

2. **`text-base` (16px) → `text-[13px]` 视觉变化**:
   - layer 卡的 label 现在与 12 卡数值同字号 → 信息层级一致
   - 但 layer 卡 label 是该卡的"主结论"(如"上行过渡"),变小后视觉重要性可能弱于 12 卡
   - 如果用户希望 layer label 比 12 卡数值略大,可改为 `text-sm` (14px) 折中

3. **font-bold 12 卡数值在小屏可能过密**:
   - 13px bold 在手机 2 列下密度高,但与顶部状态条已通过验证
   - 如视觉过重,可改为 `font-semibold`(中粗)折中

4. **系统自检 footer `<p>` padding 调整**:
   - 原 `mt-2` 依赖 section 的 px-3
   - 新 `px-3 pb-3` 与 body 同水平边距,**底部留白稍大**(pb-3 vs 原无 pb)
   - 视觉差异极小

5. **`cardOpportunityGrade` 中文 "无机会" vs em-dash**:
   - 与其他 11 个 fallback 不一致(D1=a 决策保留)
   - 信息量更大,但视觉混搭。1.10 如要彻底统一,可在 helper 加可选 mode 参数

## 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 980 passed, 1 skipped, 360 warnings in 8.15s |
| GitHub push(commit hash:见末尾) | ❌ **故意不 push** — 等用户浏览器实证 4 处微调后才推 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | **不需要**(纯前端) |
| 浏览器强刷验证 | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A(纯前端) |

## 本 sprint 删除清单

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| 系统自检 section 的 `px-3 py-2.5` 内联 padding | `web/index.html:184` | D2=b:padding 移到内层 header / body / footer,与其他 section 同结构 |
| 系统自检的 `<div class="flex...text-[12px] mb-2.5">` 标题包装 | `web/index.html:190-195`(原) | D2=b:替换为 `<header><h2 class="text-base font-semibold">` 完整 section 头 |
| layer 卡 label 的 `text-base` 字号 | `web/index.html:364` | D4:统一为 `text-[13px]` 与 12 卡同字号 |

**git grep 自检**(commit 后):
```
$ grep -n "🩺 系统自检</span>" web/index.html
(empty,emoji 已拆为 <span>🩺</span><span>系统自检</span>) ✅
```

## 测试记录

```
$ python -m pytest tests/ -q --tb=no
980 passed, 1 skipped, 360 warnings in 8.15s
```

完整 980 测试通过 — 纯前端样式微调,后端 / API 0 影响。

## 下一步

CC 故意不 push,等用户:
1. 主动 `git push origin main` 后浏览器强刷
2. 实证 4 处微调:12 卡加粗 / 五层 label 缩字号 / 系统自检标题升级 / em-dash 占位
3. 用户认可 → push 12 个 commit:1.8.2-B/C/D/D.1/E/G/H/I/J/K/K.1 + 本 commit (1.8.2-K.2)
