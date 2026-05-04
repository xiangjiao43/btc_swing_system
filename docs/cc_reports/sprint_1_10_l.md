# Sprint 1.10-L 报告(进行中 — 阶段 1)

**v1.4 项目最后一个 sprint(收尾 + 上线)**:K-A 留 7 项 + v1.4 §10.5 原计划 2 项,共 9 项。

工程量预估 5-7 天,15 commits,4 中断点(模式 B 分段审)。

---

## Triggers(本 sprint 启动决策记录)

### P0/P1/P2 决策(用户拍板,2026-05-04)

#### 歧义 #1 = 方案 P1A(严格 modeling §4.2.8/9 双向)
- **进 PROTECTION**:每个 active thesis 进 review_pending(reason='extreme_event_protection')
- **退 PROTECTION**:system_state='review_pending' 让用户决定出口(出口 A/B/C 已存在)
- 实施:新建 `src/strategy/protection_handler.py`,接入 state_builder._run_state_machine 后

#### 歧义 #2 = 方案 (A) 双调用 + 幂等
- lifecycle + hard_invalidation 都调 close_thesis(冗余兜底)
- thesis_manager.close_thesis 顶部加 `if status in CLOSED_STATUSES: return early`(幂等检查)
- 防双重 close 同时保留两条独立路径

#### 歧义 #3 = 改造 hard_invalidation_monitor 调 determine_close_channel
- 1.10-L 是收尾,统一调用路径(写死 "A" → 函数调用)
- stop_loss_filled 默认仍走 A(_REASON_TO_DEFAULT_CHANNEL),改造收益:invalidated reason 时 4 条件分级
- 工程量微小(行 189 一处改造)+ 测试覆盖

#### 歧义 #4 = (a) 等 1 cycle(2-8 小时)
- P2 #6 prompt V12/V15/V19 决策基于 1 cycle 真触发数据
- 1 cycle 后数据仍不充分 → 降级为留 future
- commit 12 报告写"基于 N 数据,决策 X"

### 重大澄清(启动确认调研发现)
- P0 #3 反手出口:**cooldown_manager.determine_close_channel 完整实现**(4 条件分级 §4.3.3),
  thesis_manager.close_thesis 已接收 close_channel 参数,master_input_builder 已消费
  is_in_cooldown — **工程量比启动指令预估小 5x**
- P0 #1 review_pending 模块完整(enter + 4 出口),只缺 PROTECTION trigger caller
- P0 #2 hard_invalidation_monitor 已调 close_thesis(line 189),lifecycle_manager 跟它是
  独立轨道,接通 + 幂等是真实差距

---

## 15 commit 计划 + 4 中断点(模式 B 分段审)

| # | 内容 | 影响文件 | 中断点 |
|---|---|---|---|
| **阶段 1:报告骨架 + P0 #1 review_pending 路由**| | | |
| 1 | 启动 + 报告骨架 + 接受 P0 决策 + 1.10-K-A 报告重复段落清理 | 2 | — |
| 2 | protection_handler.py 新建(on_protection_entered + check_protection_exit_conditions)+ 单测 | 2 | — |
| 3 | state_builder 接入 protection_handler + §Z 真启动验证 | 1 | — |
| **==中断点 8:P0 #1 完成,僵尸状态修复==**| | | 🛑 |
| **阶段 2:P0 #2 lifecycle→ThesesDAO + P0 #3 反手通道接通**| | | |
| 4 | thesis_manager.close_thesis 幂等检查 + 单测 | 2 | — |
| 5 | lifecycle_manager._archive_lifecycle 接入 close_thesis + 单测 | 2 | — |
| 6 | hard_invalidation_monitor 改 determine_close_channel + lifecycle_manager 同步 + 单测 | 3 | — |
| 7 | test_lifecycle_e2e_reversal Tick 7 反手测试重新覆盖 | 1 | — |
| **==中断点 9:P0 #2/#3 完成,反向闭环==**| | | 🛑 |
| **阶段 3:P1 + P2 + 报告清理**| | | |
| 8 | app.js 渐进迁移读 state_machine.thesis / system_state(P1 #4)| 1 | — |
| 9 | lifecycle_manager.py 5 处 FLIP_WATCH/PPR 引用语义对齐(P2 #5)| 1 | — |
| 10 | 1.10-K-A 报告段落重复清理(P2 #7,如果 commit 1 没做)| 0/1 | — |
| **==中断点 10:P1+P2 完成,准备真 API 验证==**| | | 🛑 |
| **阶段 4:任务 8 端到端真 API 验证**| | | |
| 11 | scripts/verify_e2e_real_api.py(端到端真 API 触发指令 + 验证)+ 用户 SSH 跑 | 1 | — |
| 12 | 真触发后基于 V 数据决策 prompt V12/V15/V19 是否加(P2 #6)| 1 | — |
| **==中断点 11:任务 8 真 API 验证通过==**| | | 🛑 |
| **阶段 5:任务 9 上线 + v1.4 文档最终化**| | | |
| 13 | scripts/verify_cleanup_l.py(50+ §Z)+ 跑通 | 1 | — |
| 14 | docs/modeling.md §11.5 修订项归档 + README 更新 | 2 | — |
| 15 | 最终报告 + v1.4 完成宣告 + 1.10-L checklist 全部结清(**v1.4 完成 commit**) | 1 | — |

**绝对不做**(本批次 commit 1):commits 2-15 全部。

---

## 9 项范围 + 阶段映射

| # | 项 | 优先级 | 来源 | 阶段 | commit |
|---|---|---|---|---|---|
| 1 | PROTECTION → review_pending 路由真接通 | P0 | K-A 留项 #12 | 1 | 2-3 |
| 2 | lifecycle_manager → ThesesDAO 接通 | P0 | K-A 留项 #7 | 2 | 4-5 |
| 3 | 反手出口 thesis_manager 真接通 | P0 | K-A 留项 #11 | 2 | 6-7 |
| 4 | 网页 thesis dict 渐进迁移 | P1 | K-A 留项 #8/9 | 3 | 8 |
| 5 | lifecycle_manager.py FLIP_WATCH/PPR 引用语义对齐 | P2 | K-A 留项 #13 | 3 | 9 |
| 6 | prompt V12/V15/V19 加 | P2 | K-A 留项 #10 | 4 | 12 |
| 7 | 报告 sprint_1_10_ka.md 段落重复清理 | P2 | K-A 留项 | 1 + 3 | 1 + 10 |
| 8 | 端到端真 API 验证 | 必做 | v1.4 §10.5 原计划 | 4 | 11 |
| 9 | 上线 + v1.4 文档最终化 | 必做 | v1.4 §10.5 原计划 | 5 | 13-15 |

---

## §Z 双验证记录

### Commit 1
- 文本验证:本 commit 写报告 + 决策记录 + 1.10-K-A 报告重复段落清理(行 174-225 删除)
- 启动验证:N/A
- 1.10-K-A 重复行清理验证:`grep -c "### Commit 2" docs/cc_reports/sprint_1_10_ka.md` → 1(原 2)

---

## 1.10-L checklist 9 项消化情况(commit 15 收尾时填)

待 commit 15 填写。

---

## 部署状态(待 commit 15 完成后填)

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ⏳ 待 commit 15 |
| GitHub push 15 commits | ⏳ 待 |
| 服务器 git pull | ⏳ 待用户执行 |
| 服务器 systemctl restart | ⏳ 待用户执行 |
| 端到端真 API 验证(任务 8)| ⏳ 中断点 11 用户 SSH 跑 |
| v1.4 完成宣告 commit 15 | ⏳ 待 |
