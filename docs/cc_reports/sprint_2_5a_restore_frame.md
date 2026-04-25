# Sprint 2.5-A — 恢复 Region 1 / Region 3 外框(撤销 7e6a694)

**Date:** 2026-04-25
**Branch:** main
**Type:** style / layout fix

## 背景
Sprint 2.5-A(commit `7e6a694`)移除 Region 1 + Region 3 的 audit-card 外框,目的是消除冷启动期右栏底部留白。但:
1. Sprint 2.5-B-rewrite(`b67a75a`)上线后,Region 3 6 张卡每张有"📊 当前态势 / 🎯 对策略影响"双段叙事,内容自然变长,留白消失
2. 5 个区域中 3 个有外框、2 个没有,视觉不一致更难看

## 改动

| 文件 | +/− | 说明 |
|---|---|---|
| `web/index.html` | +2 / −5 | Region 1 / Region 3 `<section>` 恢复 `audit-card` class;header 恢复 `border-b border-slate-200 dark:border-slate-800`;删除 Sprint 2.5-A 的中文注释 |

## 关键 diff

```html
- <section id="region-1" class="lg:col-span-3">
-   <header class="px-4 py-2.5">
+ <section id="region-1" class="audit-card lg:col-span-3">
+   <header class="px-4 py-2.5 border-b border-slate-200 dark:border-slate-800">

- <section id="region-3" class="lg:col-span-2">
-   <header class="px-4 py-2.5">
+ <section id="region-3" class="audit-card lg:col-span-2">
+   <header class="px-4 py-2.5 border-b border-slate-200 dark:border-slate-800">
```

## 验收
- `grep -c 'audit-card' web/index.html` → 6(BTC header + Region 1/2/3/4/5)✅
- 用 `str_replace`(Edit 工具),非 git revert,无元数据污染 ✅

## 部署
1. commit + push 到 main
2. ssh 124.222.89.86 → git pull → sudo systemctl restart btc-strategy
