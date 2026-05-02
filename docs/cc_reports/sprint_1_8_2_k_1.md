# Sprint 1.8.2-K.1:AI 策略 12 卡字号统一 + 多值合并 1 行

## Triggers

- 1.8.2-K 完成 12 卡平铺,但字号字重不统一(text-xl 单数字 vs text-sm 多行 HTML)
- 用户视觉对齐:**12 卡完全统一**,对齐顶部状态条 region-status
- 多值卡(入场区间/止盈/硬失效)从 HTML 多行改成纯字符串 1 行逗号分隔
- **未 push**:遵守"PUSH 前等用户浏览器实证才推"

## 段 1:做了什么

### 改动 2 个文件,2 处编辑(diff +37/-38,净精简 1 行)

| # | 文件:位置 | 动作 |
|---|---|---|
| 1 | `web/index.html:270-333` | 12 卡 HTML 字号字重完全统一 |
| 2 | `web/assets/app.js:204-241` | 3 个多值 helper 输出格式改 HTML→纯字符串 |

### 顶部状态条样式调研结论(对齐目标)

```css
/* styles.css */
.stat-label {
  font-size: 9.5px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #64748b;        /* slate-500 */
}
.dark .stat-label { color: #94a3b8; }  /* slate-400 */
```

顶部状态条数值大多是 `class="text-[13px]"`(或 `text-[13px] font-mono` 数字)。

### 12 卡统一规范

```html
<div>
  <div class="stat-label">{标签}</div>
  <div class="text-[13px] text-slate-900 dark:text-slate-100"
       x-text="..."></div>
</div>
```

数字字段(入场区间 / 止损价 / 止盈分批 / 距离止损 / 硬失效位)额外加 `font-mono`:
```html
  <div class="text-[13px] font-mono text-slate-900 dark:text-slate-100" ...>
```

| 卡 | 字号 | 字重 | 字体 | 颜色 |
|---|---|---|---|---|
| 方向 / 状态 / 机会等级 / 信心指数 / 仓位上限 / 当前浮盈 / 持仓时长 | text-[13px] | normal | sans | slate-900 |
| 入场区间 / 止损价 / 止盈分批 / 距离止损 / 硬失效位 | text-[13px] | normal | mono | slate-900 |

**所有 12 卡字号 / 字重 / 颜色完全一致**(只在数字字段加 mono 等宽字体,与顶部状态条做法一致)。

### 3 个多值 helper 输出格式重构

```javascript
// cardEntryZones — 改 HTML 多行 → 字符串单行
旧: '<div>$77000-77500 (40%)</div><div>$76000-76500 (40%)</div>'
新: '$77000-77500 (40%), $76000-76500 (40%)'

// cardTakeProfits — 同上,保留 TP 标签
旧: '<div>TP1 $80000 ×30%</div><div>TP2 $82000 ×30%</div>'
新: 'TP1 $80000 ×30%, TP2 $82000 ×30%'

// cardHardInvalidations — 只价格(用户决策"$75995, $73984, $71999.9")
旧: '<div>$75995 4H 收盘</div><div>$73984 EMA-50</div>'
新: '$75995, $73984, $71999.9'
```

3 个多值卡的 div 同步从 `x-html` 改 `x-text`(因为输出已是纯字符串)。

### 自检 grep

```
$ grep -n "x-html" web/index.html | head
(empty in region-1 area; 0 处 x-html ✅)

$ sed -n '270,335p' web/index.html | grep -cE "stat-label|text-\[13px\]"
25  ← 12 卡 × 2 hits + 1 from header area = 25 ✅
```

## 段 2:用户浏览器实证

强刷 `http://124.222.89.86`(admin / Y_RhcxeApFa0H-)→ AI 策略建议区:

- ✅ **12 张卡字号 / 字重 / 颜色完全一致**(对齐顶部状态条 region-status)
- ✅ "—" 占位符跟其他数值字号字重一致
- ✅ **硬失效位**:`$75995, $73984, $71999.9` 一行
- ✅ **入场区间**:`$77000-77500 (40%), $76000-76500 (40%)` 一行
- ✅ **止盈分批**:`TP1 $80000 ×30%, TP2 $82000 ×30%` 一行
- ✅ 标签灰小字 (.stat-label = 9.5px uppercase slate-500)
- ✅ 数值黑中字 (text-[13px] slate-900,数字加 font-mono)
- ✅ F12 console 无报错
- ✅ FLAT 状态:浮盈 / 距止损 / 时长 = `—`

## 段 3:同类风险

1. **数字字段 font-mono 视觉差异**:5 个数字字段(入场区间/止损价/止盈分批/距离止损/硬失效位)用 mono,7 个非数字用 sans。**这是顶部状态条同样做法**(BTC 现价 / 状态 都用 mono),视觉一致
   
2. **多值合并 1 行可能宽度不够**:lg 屏 6 列每列约 130-160px。如果 trade_plan 有 5+ 个止盈点,逗号字符串会撑出列宽 → 触发 wrap 到下一行。视觉变成"多行字符串",**不是 HTML 多行**
   - 缓解:用户实测后,如发现频繁 wrap,可在 helper 加 `slice(0, 3)` 截断显示前 3 个

3. **`text-[13px]` 在手机 2 列下可读性**:13px 对手机略小但可接受(顶部状态条同字号已通过用户验证)
   
4. **`stat-label` 全局 class 复用**:本 sprint 让 region-1 的 12 个 label 也用 `.stat-label`(原来 region-status / region-5 已用),增加耦合但视觉统一收益更大

5. **HTML→字符串重构是不可逆**:1.10 如要恢复彩色 size_pct 灰小字,需重写 helper 拼 HTML + div 改回 x-html。git history 可参考

## 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 980 passed, 1 skipped, 360 warnings in 8.92s |
| GitHub push(commit hash:见末尾) | ❌ **故意不 push** — 等用户浏览器实证字号统一 + 多值合并后才推 |
| 服务器 git pull | 待用户执行 |
| 服务器 systemctl restart | **不需要**(纯前端) |
| 浏览器强刷验证 | 待用户执行 |
| 生产 DB 迁移 / 清污 | N/A(纯前端) |

## 本 sprint 删除清单

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| 12 卡 `text-xl font-medium` / `text-sm font-mono` 不一致样式 | `web/index.html:270-336`(原) | 1.8.2-K.1 统一对齐顶部状态条 .stat-label + text-[13px] |
| 3 个 helper 的 HTML span/div 拼接逻辑 | `web/assets/app.js:204-241`(原) | 改纯字符串拼接 + 逗号分隔,div 改用 x-text 不再需要 HTML |
| 3 个 div 的 `x-html` 属性 | `web/index.html`(原 295/305/330) | 输出改字符串,改用 x-text |

**git grep 自检**(commit 后):
```
$ grep -n "x-html" web/index.html
(empty in region-1 area)
```

## 测试记录

```
$ python -m pytest tests/ -q --tb=no
980 passed, 1 skipped, 360 warnings in 8.92s
```

完整 980 测试通过 — 纯前端样式 + helper 输出格式改动,后端 / API 0 影响。

## 下一步

CC 故意不 push,等用户:
1. 主动 `git push origin main` 后浏览器强刷
2. 实证 12 卡字号统一 + 3 个多值合并 1 行 + console 无报错
3. 用户认可 → push 11 个 commit:1.8.2-B/C/D/D.1/E/G/H/I/J/K + 本 commit (1.8.2-K.1)
