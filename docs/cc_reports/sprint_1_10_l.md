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
| 1 | 启动 + 报告骨架 + 接受 P0 决策 + 1.10-K-A 报告重复段落清理 | 2 | ✅ `863affa` |
| 2 | protection_handler.py 新建(on_protection_entered + check_protection_exit_conditions)+ 14 单测 | 2 | ✅ `4c6fd20` |
| 3 | state_builder 接入 protection_handler + §Z 真启动验证 | 1 | ✅ `9cf5a9e` |
| **==中断点 8:P0 #1 完成,僵尸状态修复==**| | | ✅ 已通过(服务器同步成功)|
| 4 | thesis_manager.close_thesis 幂等检查 + 5 单测 | 2 | ✅ `cde6f7f` |
| 5 | _archive_lifecycle 接通 close_thesis(P0 #2 5A)+ 5 单测 | 2 | ✅ `68da502` |
| 6 | hard_invalidation_monitor + lifecycle_manager 改 determine_close_channel + 6 单测 | 3 | ✅ `03b9a08` |
| 7 | test_lifecycle_e2e_reversal 反手 channel C 端到端重新覆盖 + 2 新 e2e | 1 | ✅ `c49aefa` |
| **==中断点 9:P0 #2/#3 反向闭环完成==**| | | ✅ 已通过(服务器同步)|
| 8 | app.js 渐进迁移读 state_machine.thesis / system_state(P1 #4)+ 5 单测 | 2 | ✅ `c981838` |
| 9 | lifecycle_manager FLIP/PPR review only(P2 #5 降级 9A)+ 1 处过时注释修订 | 1 | ✅ `4459f55` |
| 10 | ~~K-A 报告重复段落清理~~ — 跳过(commit 1 P2 #7 已提前完成) | — | ⏭ 跳过 |
| **==中断点 10:P1 + P2 完成,准备真 API 验证==**| | | ✅ 已通过 |
| 11a | V24 写入通路修复(_orchestrator_mapper + state_builder INSERT 17→18 列)+ 5 单测 | 3 | ✅ `7af4844` |
| **==中断点 10.5:V24 写入修复,用户 SSH 真触发验证==**| | | ✅ 已通过(1 行真 V 数据)|
| 11b | scripts/verify_e2e_real_api.py 任务 8 端到端 §Z 12 项 | 1 | ✅ `9ce293b` |
| 12 | P2 #6 决策(基于 1 cycle 真数据)留 future + 文档 | 1 | ✅ 待 push |
| **==中断点 11:任务 8 真 API 验证通过==**| | | 🛑 已到达 |
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

### Commit 2(protection_handler.py 新建 + 14 单测)
- ✅ pytest tests/test_protection_handler.py → 14 passed
- ✅ 全量回归:1506 passed, 1 skipped, 0 failed(基准 1492 → +14 新单测)
- 模块常量:REASON_EXTREME_EVENT_PROTECTION / COOLING_PERIOD_MINUTES=30 / EXTREME_EVENT_RESOLVED_BTC_PCT=0.10 / VIX_MAX=25.0
- 2 函数:on_protection_entered(进 PROTECTION 时调,active thesis 进 review_pending)+ check_protection_exit_conditions(§4.2.9 三条件)
- 14 单测覆盖:0/1 active thesis + 幂等 + 各退出条件单独/全部/全部不满足/VIX 缺失/BTC 缺失/边界(10%/10.01%/30 min)/无效 ISO graceful

### Commit 4(thesis_manager.close_thesis 幂等 + 5 单测)
- 加 `_CLOSED_STATUSES = {closed_profit, closed_loss, invalidated, closed_60d_cap, closed_protection}`
- 顶部 `if existing.status in _CLOSED_STATUSES: return early(noop_already_closed=True)`
- 5 测试覆盖:已 closed_loss / 已 closed_profit / 已 invalidated → 二次 close noop;第一次正常 close 无 noop 标记;thesis 不存在仍正常走流程
- §Z:pytest 1511 / 1 / 0(基准 1506 → +5 新)

### Commit 5(_archive_lifecycle 接通 close_thesis — P0 #2 5A + 5 单测)
- `_archive_lifecycle` 末尾调 `_close_active_thesis_for_archive`
- helper 用 `ThesesDAO.get_active`(主线锁单 active)定位 thesis,close_thesis 默认 reason='invalidated' + channel='B'(commit 6 改函数)
- 边界覆盖:conn=None / 0 active / 双调用幂等 / btc_price 缺失全跳过
- 5 测试 + §Z pytest 1516 / 1 / 0

### Commit 6(determine_close_channel 改造 + 4 条件提取 + 6 单测)
- `hard_invalidation_monitor:189`:写死 `'A'` → `determine_close_channel('stop_loss_filled', stop_loss_breached=True)`
- `lifecycle_manager`:模块级新增 `_extract_4_conditions(state, direction)` 提取 §4.3.3 4 条件
- `_close_active_thesis_for_archive`:`'B'` → `determine_close_channel('invalidated', **conds)`
- 6 测试覆盖:default(无 state)/ long 完全反转 3/4 → C / short 1/4 → B / L5 极端单独 / transition_down 不算完全反转 / 端到端 channel C
- §Z pytest 1522 / 1 / 0

### Commit 8(app.js 渐进迁移 — P1 #4)
**设计纪律**:主路径不变,镜像作 fallback(冗余 + 防御):
- 主路径 1: GET /api/theses/active → activeThesis(真 thesis 行,字段最全)
- 主路径 2: GET /api/health.review_pending → reviewPending(RP 横幅)
- 镜像 fallback 1: smSystemState='review_pending' → 合成 RP 占位(防 health API 失败)
- 镜像 fallback 2: !activeThesis && smThesis → 最小占位(防 /api/theses/active 失败)
- 占位带 `_from_state_machine_mirror=true` 标记

`web/assets/app.js`:fetchAuxData() 末尾加 ~30 行 fallback 逻辑
`tests/test_web_modules_4_5_rp_failure.py`:5 新单测覆盖 K-A commit 7 字段消费
- ✅ pytest 1529 passed, 1 skipped, 0 failed(基准 1524 → +5)

### Commit 12(P2 #6 决策:V12/V15/V19 prompt 留 future)
**决策依据**(基于 commit 11a 修复 + 用户 SSH 跑 1 次 manual trigger 真数据):

**真数据现状**(用户 SSH 真核 2026-05-04 21:23):
- 累计 strategy_runs:139 行(原 138 全 NULL + 新增 1 行 has_data)
- 新 1 行 V meta 完整(28 字段 1181 字符 JSON)
- **V1-V23 全 silent(false)**:冷启动期符合预期
  - 无 active thesis → V6/V11/V17 等 thesis 相关静默
  - 不在 cooldown → V18/V19/V22 等系统级静默
  - master AI 输出 silent_cooldown(EMA-200 长期均线尚未转向)→ V21 软抗拒未触发(冷启动期合理)
- ai_status='ok',tokens 86k+7k(主 AI 真返回 + 真 V meta)

**决策**:**V12/V15/V19 prompt 留 future sprint**

**理由**(3 点):
1. **真数据不足**:1 cycle = 1 行 V data,所有 V 全 silent。无频率分布可决策"哪条 V 高频触发,加 prompt 收益最大"
2. **冷启动期符合预期**:V silent 不是 prompt 漏洞,是当前业务状态(无 thesis / 不在 cooldown / master 走 silent_cooldown 合理)
3. **K-A K-B 已加 4 V prompt(V3/V9/V21/V23)**,本 sprint 不擅自加无数据基础的 V12/V15/V19 — 跟"工程纪律 真数据驱动 prompt 优化"一致

**留 1.10-M / future sprint**:
- 等生产积累 50-100+ 行 V data(thesis 创建 / cooldown 触发 / master 真做出决策后)
- 看 V 真触发频率分布表(V21 / V14 / V13 / V8 等 thesis-aware V 应有数据)
- 决策"V12/V15/V19 加 prompt 是否能减少 master AI 违反频次"
- 工程量 0.3 天(类似 K-B commit 2 prompt 优化模式)

**这不是 cop-out**:
- 加 prompt 收益取决于 master AI 真违反 V 的频率
- 当前 0 数据 → 加 prompt 是"猜测"不是"数据驱动"
- 留 future = 真数据驱动 = K-B 同样模式("数据驱动失败 → 回退结构化分析" 是诚实)

**§Z 验证**:
- ✅ pytest 全量 1534 passed, 1 skipped, 0 failed(基准维持,纯文档 0 业务改动)
- ✅ 0 prompt 文件改动(`src/ai/agents/prompts/master_adjudicator.txt` 不动)

### Commit 11a(V24 写入通路修复)
**根因**(本地代码追踪 + SSH 真核 138 行 DB 数据交叉确认):
- 1.10-E 引入 `strategy_runs.constraint_activations_json` 列(migration 011)
- orchestrator.py:251 算好 `result['constraint_activations']` ✅
- _orchestrator_mapper 输出 17 列 mapped — **不含** constraint_activations_json ❌
- state_builder._run_v13_orchestrator INSERT 17 列 — **不写** constraint_activations_json ❌
- DB 138 行全 NULL(SSH 真核确认:null=138/empty=0/has_data=0)

**修复**:
- `src/pipeline/_orchestrator_mapper.py`:mapped 加 `constraint_activations_json` 字段(json.dumps with ensure_ascii=False)
- `src/pipeline/state_builder.py`:_run_v13_orchestrator INSERT SQL 17 → 18 列 + params
- `tests/pipeline/test_orchestrator_mapper.py`:test_returns_all_17 → 18 + 5 新单测

**真接通验证**(用户 SSH 跑 `scripts/run_pipeline_once.py --trigger manual`):
- run_id: 753cd250..., run_trigger='manual'
- constraint_activations_json: 1181 字符真有 V meta JSON
- ai.status: 'ok', tokens_in: 85790, tokens_out: 7367
- 累计:null=138, has_data=1, total=139
- **1.10-E V24 设计意图首次真接通,v1.4 完整版而非半残版**

**§Z 验证**:
- ✅ pytest tests/pipeline/test_orchestrator_mapper.py → 41 passed(原 36 + 5 新)
- ✅ 全量回归 1534 passed, 1 skipped, 0 failed(基准 1529 → +5 新)

### Commit 11b(verify_e2e_real_api.py 任务 8 §Z 12 项)
- 段 A V24 写入通路真接通(2 项)
- 段 B V meta JSON schema 完整性(4 项,V1-V23 + 28 字段)
- 段 C run_trigger 维度(1 项)
- 段 D 数据通路完整性 — 代码层 grep(4 项)
- 段 E 周复盘 AI 数据流通(1 项)

设计纪律:跑得通本地(代码层 ✅,数据层失败 + 给原因)+ 生产 DB 跑全过

### Commit 9(lifecycle_manager FLIP/PPR — P2 #5 降级方案 9A,review only)
**Scope 重判断**(commit 9 启动前 stop + 报告):
- 用户原指令"用 thesis-driven 替代 14 档判断"跟 K-A 方案 C(14 档枚举保留)反向
- lifecycle 无 thesis_id FK,改 thesis-driven 需每次 `ThesesDAO.get_active`(性能 + 耦合)
- "双 source of truth 是有意"— state_machine / thesis_manager / lifecycle_manager 各自职责

**用户拍板方案 9A:降级为 review only**
- ✅ 5 处业务条件**不动**(14 档判断符合方案 C,正确简洁)
- ✅ 4 处历史注释 review:
  - 行 15 / 203 / 499 docstring 准确描述当前行为(FLAT/FLIP_WATCH stable / *_EXIT 归档触发)+ 跟方案 C 一致 → **不动**
  - 行 510-511 注释**1 处过时**(说"FLIP_WATCH → *_PLANNED 路径能读到",但 K-A commit 5 _from_FLIP_WATCH 已 stub stay 该路径已废)→ 修订为"prev_cycle_side 镜像保留给 future thesis_manager 反手出口接通(checklist (11) P0)"

**§Z 验证**:
- ✅ pytest 全量:**1529 passed, 1 skipped, 0 failed**(基准 1529 维持,纯注释修订 0 regression)
- ✅ 0 业务行为改动 + 1 处过时注释修订
- 此 commit 是 1.10-L 第 2 个 review only commit(K-A commit 9 是第 1 个),工程纪律成熟形态:**做 review,不做无意义改动**

### Commit 7(反手 e2e 重新覆盖 — 替代 K-A commit 10 删除的 Tick 7)
**背景**:K-A commit 10 删除原 Tick 7 "FLIP_WATCH → SHORT_PLANNED 反手" 测试(理由:_from_FLIP_WATCH stub stay,反手出口由 thesis_manager 接管)。1.10-L commit 5/6 完成后,反手通道分级**真接通**(close_thesis 写入 close_channel='C'/'B'/'A',cooldown_manager.is_in_cooldown 据 channel 算 cooldown_end)。

**新加 2 端到端测试**(替代删除的 Tick 7):
- `test_lifecycle_archive_channel_c_zero_cooldown_e2e`:LONG_HOLD → LONG_EXIT(L1 trend_down + L2 bearish 0.85 + L5 risk_off + extreme_event,3/4)→ _archive_lifecycle 触发 → close_thesis(channel='C')→ is_in_cooldown 返 in_cooldown=False(C 是 0h)→ master AI 看到 cooldown_state.in_cooldown=False 后理论可创建反手
- `test_lifecycle_archive_channel_b_24h_cooldown_e2e`:0/4 invalidated 默认 channel B → 1h 后仍 in_cooldown=True / 25h 后已退出

**反手 thesis 创建留 future sprint**(master AI mock 跨多模块,本测试覆盖到 cooldown 真触发即止,Validator 6 主线锁 + master_input_builder 已消费 cooldown_state)。

**§Z 验证**:
- ✅ pytest tests/test_lifecycle_e2e_reversal.py → 3 passed(1 existing + 2 new)
- ✅ 全量回归 1524 passed, 1 skipped, 0 failed(基准 1522 → +2 新)

### Commit 3(state_builder 接入 protection_handler + §Z 三重验证)
- 文本接入位置:`src/pipeline/state_builder.py` 在 `state["state_machine"] = sm_block` 后(line 740 后)
- 触发条件:`current_state=='PROTECTION' AND previous_state != 'PROTECTION'`(避免每个 PROTECTION tick 重复触发,虽 enter_review_pending 内部已幂等)
- 路由:`self._safe(lambda: protection_handler.on_protection_entered(self.conn, run_id, run_ts_utc), stage="protection_entered_review_pending", ...)`

**§Z 三重验证**:
- ✅ uvicorn TestClient + GET / → 200
- ✅ scheduler.build_scheduler() → 10 cron jobs
- ✅ **端到端真触发模拟**:in-memory schema → seed active thesis → 调 on_protection_entered → 验证 system_states 表写入 1 行 review_pending(reason='extreme_event_protection', related_thesis_id='t_z_test', exit_at_utc=NULL)
- ✅ state_builder.py 含 `protection_entered_review_pending` stage 名(grep 1 hit)
- ✅ pytest 全量:**1506 passed, 1 skipped, 0 failed**(基准 1506 维持)

**P0 #1 修复完成**:POST_PROTECTION_REASSESS stub stay 不再是僵尸源 — 进 PROTECTION 时已自动 enter_review_pending,退出后 system_state='review_pending'(commit 7 镜像)+ 用户出口 A/B/C(已存在)。

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
