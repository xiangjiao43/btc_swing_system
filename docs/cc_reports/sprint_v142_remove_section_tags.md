# Sprint v1.4.2 涂装 — 移除卡片标题旁的 §章节标签

**日期**:2026-05-08
**类型**:前端涂装,无逻辑改动
**单文件改动**:`web/index.html`(-4 行)

## 背景

用户反馈:网页 4 个卡片标题旁挂着工程标记 `v1.4 §9.2.X`,
对普通用户而言这是建模文档章节号,语义不可读,属于工程内部信息泄漏给用户视图。
要求清理掉。

## 改动清单

删掉 4 个独立 `<span>` 元素(每行 1 个 span,删除后标题行对齐不受影响):

| 卡片 | 原文件位置 | 删除内容 |
|---|---|---|
| 💼 虚拟账户 | web/index.html:504 | `<span class="text-[11px] font-normal text-slate-500 ml-1">v1.4 §9.2.1</span>` |
| 📋 当前 thesis | web/index.html:574 | `<span class="text-[11px] font-normal text-slate-500 ml-1">v1.4 §9.2.2</span>` |
| 📦 挂单 + 持仓 | web/index.html:650 | `<span class="text-[11px] font-normal text-slate-500 ml-1">v1.4 §9.2.3</span>` |
| 📅 thesis 历史时间线 | web/index.html:817 | `<span class="text-[11px] font-normal text-slate-500 ml-1">v1.4 §9.2.4</span>` |

## 关键 diff

```diff
@@ -501,7 +501,6 @@
       <header class="px-4 py-2.5 border-b border-slate-200 dark:border-slate-800">
         <h2 class="text-base font-semibold flex items-center gap-2">
           <span>💼</span><span>虚拟账户</span>
-          <span class="text-[11px] font-normal text-slate-500 ml-1">v1.4 §9.2.1</span>
         </h2>
       </header>
@@ -571,7 +570,6 @@
           <span>📋</span><span>当前 thesis</span>
-          <span class="text-[11px] font-normal text-slate-500 ml-1">v1.4 §9.2.2</span>
         </h2>
@@ -647,7 +645,6 @@
           <span>📦</span><span>挂单 + 持仓</span>
-          <span class="text-[11px] font-normal text-slate-500 ml-1">v1.4 §9.2.3</span>
         </h2>
@@ -814,7 +811,6 @@
           <span>📅</span><span>thesis 历史时间线</span>
-          <span class="text-[11px] font-normal text-slate-500 ml-1">v1.4 §9.2.4</span>
         </h2>
```

## 验收:同类风险扫描

`grep -nE "§[0-9]+\.[0-9]+" web/index.html` 全量扫描结果:

| 行 | 内容 | 类型 | 用户可见? |
|---|---|---|---|
| 72 | `<!-- 🚨 review_pending 红色全局横幅(Sprint 1.10-I §9.3 + D2=a)  -->` | HTML 注释 | ❌ |
| 194 | `<!-- 顶部全局状态条(§9.3) -->` | HTML 注释 | ❌ |
| 478 | `<!-- ⚠️ AI 失败状态显示(Sprint 1.10-I §9.4 + §6.3.4) -->` | HTML 注释 | ❌ |
| 497 | `<!-- 💼 模块 1:虚拟账户面板(Sprint 1.10-I §9.2.1) -->` | HTML 注释 | ❌ |
| 568 | `<!-- 📋 模块 2:当前 thesis 卡(Sprint 1.10-I §9.2.2) -->` | HTML 注释 | ❌ |
| 644 | `<!-- 📦 模块 3:挂单 + 持仓状态(Sprint 1.10-I §9.2.3) -->` | HTML 注释 | ❌ |
| 810 | `<!-- 📅 模块 4:thesis 历史时间线(Sprint 1.10-I §9.2.4) -->` | HTML 注释 | ❌ |
| 1013 | `<!-- 📊 模块 5:周复盘报告(Sprint 1.10-I §9.2.5 + D3=a) -->` | HTML 注释 | ❌ |
| **1018** | **`<span class="...">v1.4 §9.2.5</span>` 在 📊 周复盘报告 卡** | **可渲染 span** | ⚠️ **是** |

**⚠️ 同类风险残留**:模块 5「📊 周复盘报告」卡(`web/index.html:1018`)还挂着
`v1.4 §9.2.5` 标签,与本次清掉的 4 个卡完全同语义。
**用户本次只点名 4 个卡,所以保留待用户拍板。**
建议方案 A:一并删掉(语义一致);方案 B:保留(若周复盘卡日后会单独迭代)。

## 验收:语法 / 排版

- 删除元素均为独立 `<span>`,且在 `<h2 class="...flex items-center gap-2">` 内。
- flex gap-2 由其它 span 维持,删 1 个 span 不影响标题行对齐 / spacing。
- HTML 注释中的 §X.Y 是工程注释(后端/CC 用),用户在浏览器看不到,不需要清。

## 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | N/A(纯前端 HTML 文本删除,无 Python 改动) |
| GitHub push(commit hash:c874342) | ❌ **待用户执行** — CC 在本机 `git push origin main` 被 GitHub 拒绝(`Permission denied (publickey)`,本机 SSH key `shenjun@btc-mac` 未在 GitHub 账户注册;`gh` CLI 未安装)。**用户需要在自己的工作站执行 `git push origin main`,或允许 CC 用其他方式 push。** |
| 服务器 git pull | ❌ **待用户执行** — 命令:`ssh ubuntu@<server> 'cd /home/ubuntu/btc_swing_system && git pull'`(CC 在本机也无 SSH 权限到生产服务器)|
| 服务器 systemctl restart | N/A(static HTML 由 nginx 直接读)|
| 生产 DB 迁移 / 清污 | N/A |

### 额外注意:本地 commit 作者身份

CC 用 git 默认身份 `沈俊 <shenjun@xiangjiaodeMacBook-Air.local>` 提交了 commit `c874342`,
与用户惯用的 `xiangjiao43 <172024219+xiangjiao43@users.noreply.github.com>` 不一致。
原因:本机 `git config user.email` 未配置,fallback 到系统默认。

CLAUDE.md「NEVER update the git config」+「Always create NEW commits rather than amending」,
所以 CC 没有自行修复。**用户可选择**:

- (A) 用户先 `git config user.name xiangjiao43 && git config user.email 172024219+xiangjiao43@users.noreply.github.com`
  再 `git commit --amend --reset-author --no-edit`,然后 push;
- (B) 直接 push 接受 commit author = 沈俊;
- (C) `git reset HEAD~1 --soft` 之后由用户重新 commit。

CC 推荐 (A),因为保持 commit history 风格一致。

## 本 sprint 删除清单

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| `<span>v1.4 §9.2.1</span>` | web/index.html:504 | 工程标记泄漏给用户视图,用户报告要求清理 |
| `<span>v1.4 §9.2.2</span>` | web/index.html:574 | 同上 |
| `<span>v1.4 §9.2.3</span>` | web/index.html:650 | 同上 |
| `<span>v1.4 §9.2.4</span>` | web/index.html:817 | 同上 |

`git grep "v1.4 §9.2.1"` `git grep "v1.4 §9.2.2"` `git grep "v1.4 §9.2.3"`
`git grep "v1.4 §9.2.4"` 在 web/index.html 中均 0 命中(只命中本报告内的引用)。

## 未覆盖项 / 风险

1. **§9.2.5 在「📊 周复盘报告」卡仍可见**(web/index.html:1018) — 同类风险,等用户拍板是否一并删。
2. 本次未触及 HTML 注释中的 §X.Y 引用,因为它们对用户不可见,且对工程 / CC
   定位代码有用,不属于"标记泄漏"。

---

## 续写:Sprint 收尾(2026-05-08 第二轮)

第一轮交付后,用户授权:
1. 把 SSH key 加到 GitHub(push 通道打通);
2. CC 可改 **local** git config 为 `xiangjiao43 / 172024219+xiangjiao43@users.noreply.github.com`;
3. 顺手把模块 5「📊 周复盘」的 §9.2.5 一并清掉。

### 收尾步骤(实际执行顺序)

1. `git config --local user.name "xiangjiao43"` + `user.email "172024219+xiangjiao43@users.noreply.github.com"` ✅
2. `git reset --soft HEAD~2` 把 c874342 + 8936a75 软回滚,4 处删除留在 staging ✅
3. 删 web/index.html:1018 的 §9.2.5 span(同 §9.2.1-§9.2.4 处理方式)✅
4. 一次性 commit 5 处删除(commit hash 见下)✅
5. `git push origin main` ✅

### 最终改动清单(5 处)

| 卡片 | 原文件位置 | 删除内容 |
|---|---|---|
| 💼 虚拟账户 | web/index.html(原 504) | `<span class="...">v1.4 §9.2.1</span>` |
| 📋 当前 thesis | web/index.html(原 574) | `<span class="...">v1.4 §9.2.2</span>` |
| 📦 挂单 + 持仓 | web/index.html(原 650) | `<span class="...">v1.4 §9.2.3</span>` |
| 📅 thesis 历史时间线 | web/index.html(原 817) | `<span class="...">v1.4 §9.2.4</span>` |
| 📊 周复盘 | web/index.html(原 1018) | `<span class="...">v1.4 §9.2.5</span>` |

合计 `web/index.html` -5 行,无其它逻辑变更。

### 验证

`grep -nE "v1\.4 §9\.2" web/index.html` → 0 命中 ✅
`grep -nE "§[0-9]+\.[0-9]+" web/index.html` 余下命中全部在 HTML 注释中(用户不可见)。

### 部署状态四件事清单(收尾后真实状态)

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | N/A(纯前端 HTML 文本删除,无 Python 改动) |
| GitHub push(commit hash) | ✅ 见正文 commit hash |
| 服务器 git pull | ❌ **待用户执行** — `ssh ubuntu@124.222.89.86 "cd /home/ubuntu/btc_swing_system && git pull && git log -1 --format='%h %s'"` |
| 服务器 systemctl restart | N/A(static HTML 由 nginx 直接读)|
| 生产 DB 迁移 / 清污 | N/A |

### Commit author 验证

收尾 commit 的 author 必须是 `xiangjiao43 <172024219+xiangjiao43@users.noreply.github.com>`,
原因:step 1 已配 local user.name/user.email,新 commit 自动用新身份(老的两个 commit 已被
`reset --soft` 撤回,仓库远端不会出现 author = 沈俊 的痕迹)。
