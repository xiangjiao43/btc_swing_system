# BTC Swing System - AGENTS.md

## 0. Codex 优先级说明

本文件是 Codex 专用项目规则。
`CLAUDE.md` 保留给 Claude Code 使用，Codex 默认不修改 `CLAUDE.md`。
如果本文件与 `CLAUDE.md`、旧 CC 规则冲突，Codex 以本文件为准。
如果本文件与 `docs/modeling.md` 的旧运行节奏冲突，先参考当前真实配置文件、`README.md` 和最新接管报告；涉及策略逻辑冲突时必须停下来问用户。

`docs/modeling.md` 仍是项目建模蓝本。Codex 不要把建模全文塞进上下文，而是每轮任务按相关性读取建模章节。

Codex 的任务原则：只做用户本轮明确要求的事，不顺手扩大范围，不把文档修复升级成策略修复，不把本地修复模糊说成生产上线。

## 1. 用户身份与沟通方式

用户是代码小白，不是工程师。
所有回复必须使用中文“小白模式”。
解释代码时，不要只说函数名，要说明“这对交易系统意味着什么”。

每个关键节点必须输出四段式结论：

一、完成了什么
二、证据是什么：改动文件、运行命令、测试结果、健康检查结果
三、风险和未完成：必须主动说明不确定点
四、下一步建议：只建议，不要擅自继续执行

关键节点包括：
- 只读诊断完成后；
- 计划完成后；
- 代码修改完成后；
- 测试或健康检查完成后；
- 本轮任务收尾时。

不要在对话里贴大段 diff、长日志、长测试输出。详细内容写入报告文件。

## 2. 项目定位

这是 BTC 中长线低频双向波段交易辅助系统。
当前定位是：

- 虚拟交易员账户；
- 策略建议系统；
- 决策审计系统；
- 用户跟单参考系统。

当前系统不是自动真实下单机器人。
系统可以生成 active thesis、虚拟挂单、虚拟账户盈亏、风控和失效位、周复盘。
系统默认不接真实交易所下单，不自动开仓，不自动平仓，不自动调杠杆，不自动修改用户真实账户。

任何“真实交易所执行 / 实盘下单 / 杠杆 / 真实账户 API”相关需求，Codex 必须暂停并请求用户确认。

## 3. 当前真实运行决议

以下是当前 Codex 必须采用的真实运行口径：

1. 主裁决时间：以 `config/scheduler.yaml` 为准，当前是每日 **11:35 BJT**。`docs/modeling.md` 中每日 16:00 BJT 属于旧建模节奏，Codex 不得擅自改回。
2. 持仓 4h 健康检查：当前 `position_health_check.enabled=false`，保持关闭。重新启用必须问用户。
3. 数据源：当前 Binance 已从实际数据源中移除；BTC K 线和衍生品主要走 CoinGlass via `api.alphanode.work`；链上走 Glassnode via `api.alphanode.work`；宏观走 FRED。Codex 不得擅自恢复 Binance 或 Yahoo。
4. AI SDK：当前实际使用 `anthropic` Python SDK；`OPENAI_API_BASE` / `OPENAI_API_KEY` / `OPENAI_MODEL` 是历史沿用环境变量名，不得为了“看起来一致”擅自改名。
5. Python：以 `pyproject.toml` 为准，当前 `requires-python >=3.12`。
6. 数据库：当前使用 SQLite；PostgreSQL 属于未来 v1.0 方向。Codex 不得擅自迁移数据库类型。
7. `PROJECT_LOG` 中“接入真实账户执行”的早期文字视为历史遗留，不得据此实现真实下单。
8. 生产健康判断优先看 `/api/system/health`，不要用旧 `/api/health` 误判 scheduler 状态。
9. 旧文档或旧注释里若还出现 Binance、Yahoo、16:00、4h 健康检查等旧口径，Codex 必须先按当前真实配置判断，不得直接恢复旧逻辑。

## 4. 项目阅读顺序

每轮任务开始前，按任务相关性阅读，不要全仓库乱翻。

通用入口：
1. `README.md`
2. `AGENTS.md`
3. `docs/cc_reports/sprint_takeover_baseline.md`
4. `docs/modeling.md` 的相关章节
5. `config/scheduler.yaml`、`config/data_sources.yaml`、`config/base.yaml` 中和任务相关的部分

核心模块路线：
- 调度：`config/scheduler.yaml`, `src/scheduler/jobs.py`, `src/scheduler/main.py`
- AI 主裁决：`src/ai/orchestrator.py`, `src/ai/validator.py`, `src/ai/agents/`
- 策略状态：`src/pipeline/state_builder.py`, `src/strategy/state_machine.py`
- thesis：`src/strategy/thesis_manager.py`, `src/strategy/thesis_persistence.py`
- 虚拟订单：`src/strategy/orders_engine.py`
- 虚拟账户：`src/strategy/virtual_account.py`
- 硬失效：`src/strategy/hard_invalidation_monitor.py`
- 数据采集：`src/data/collectors/`
- 数据库：`src/data/storage/dao.py`, `src/data/storage/schema.sql`, `migrations/`
- API：`src/api/routes/`
- 前端：`web/index.html`, `web/assets/app.js`, `src/web_helpers/`
- 测试：`tests/`

## 5. 建模硬纪律

Codex 修改代码时必须遵守以下长期建模硬纪律。

### 5.1 双轨输出原则

同一份系统初步分析数据必须产出两个版本：

- 机读版：给 AI orchestrator / Master，结构化 JSON；
- 人读版：给用户网页，中文叙述，规则化拼接。

硬约束：
1. 两份信息源必须同一；
2. 人读版必须由规则化代码生成；
3. 人读版严禁由 AI 生成；
4. 人读版严禁直接展示机读版 JSON 原文；
5. AI 只参与综合裁决，不参与因子解释、不参与规则转述。

用户打开网页是为了审计系统，不是看 AI 自由写报告。

### 5.2 执行顺序

必须遵守：

数据采集 → 证据层 L1/L2/L3/L4/L5 → AI 裁决 → Validator 校验 → StrategyState / thesis / virtual account 输出。

不允许跨阶段乱读上次结论。
不允许因为方便而跳过 Validator。

### 5.3 L3 grade 唯一权威

L3 是 `opportunity_grade` 的唯一来源。
Master AI 不能改 grade。
Master 只能在 narrative 里表达保留意见。
Validator 必须拒绝或覆盖不一致 grade。

### 5.4 hard_invalidation 唯一止损来源

`hard_invalidation_levels` 是 `stop_loss` 的唯一权威来源。
AI `trade_plan.stop_loss` 必须从 L4 / 规则给出的候选价位中选。
不得自创止损价。

### 5.5 1H 数据白名单

L1 / L2 / 组合因子禁止读 1H 数据。
只有执行确认、硬失效预警、事件触发能读 1H 数据。
任何新增 1H 读数路径都必须说明用途和边界。

### 5.6 position_cap 纪律

`position_cap_base` 基础 70%。
L4 risk_level、Crowding、Macro、EventRisk 等因子按建模串行合成仓位上限。
AI 给出的 `max_position_size_pct` 不能超过 `position_cap_base` 或最终合成上限。
任何仓位 sizing 改动都是高风险，必须先问用户。

### 5.7 execution_permission 归并

每个因子产出建议档位，最终取最严档位。
A 级缓冲：grade=A 且 regime 稳定时，permission 不得严于 `cautious_open`。
Codex 不得擅自弱化 permission 规则。

### 5.8 AI 裁决 System Prompt

AI 裁决 System Prompt 必须严格对齐 `docs/modeling.md` 的最终稿。
它包含 10 条纪律、核心决策原则和身份定位。
Codex 不得为了“更自然”擅自改 prompt 的硬约束。

### 5.9 thesis 主线锁

同时只能有一个 active thesis。
有 active thesis 时，Master 只能 `evaluate_existing` 或 `silent_cooldown`，不能直接 `new_thesis`。
必须先通过客观 break_conditions / stop_loss / 60 天上限 / PROTECTION 关闭旧 thesis，才能进入新方向。

### 5.10 v1.4 状态模型

当前状态模型以 `thesis.lifecycle_stage` 为主线：

`planned → opened → holding → trim → closed`

系统级特殊态：
- `FLAT`
- `PROTECTION`
- `review_pending`

旧 14 档状态只允许作为兼容映射，不得恢复为主逻辑。

### 5.11 反手三通道

通道 A：自然结束，3 天冷却。
通道 B：break_conditions 触发失效，24 小时冷却。
通道 C：紧急反手，0 冷却，但必须满足建模条件，并受 14 天熔断限制。

不允许凭感觉反手。
1H 信号不能单独触发方向切换。

### 5.12 虚拟账户和挂单

虚拟账户初始资金默认 100,000 USDT。
挂单必须是精确价格，不是区间。
1H K 线 `low <= price <= high` 即视为虚拟挂单触发。
入场价等于挂单价，不等于 1H 收盘价、high 或 low。
同一根 1H K 线可以触发多个挂单。
默认挂单有效期 7 天。

### 5.13 Validator 24 条

Validator 是硬约束层，必须保留。核心类别包括：

1. stop_loss 必须从 hard_invalidation_levels 选；
2. 仓位不能超过 position_cap_base；
3. entry_orders 总 size_pct 不能超过 100%；
4. PROTECTION 不允许新 thesis；
5. grade 与 execution_permission 必须匹配；
6. active thesis 主线锁；
7. invalidated 必须有客观 break 触发；
8. break_conditions 必须客观可判；
9. break_conditions 距离必须合理；
10. master grade 必须等于 L3 grade；
11. evaluate_existing 不能改 active thesis direction；
12. evidence_ref 必须真实存在；
13. objective_evidence 必须引用真实字段；
14. narrative 必须有 counter_arguments；
15. confidence 受数据完整度约束；
16. what_would_change_mind 至少 3 条客观条件；
17. weakened stop_loss 收紧有上限；
18. 14 天反复横跳熔断；
19. 60 天 thesis 上限；
20. 连续熔断进入 review_pending；
21. master AI 软抗拒识别；
22. master 连续 3 天失败进入 review_pending；
23. conflict_resolution 必须输出；
24. meta 约束：记录硬约束激活频率，供周复盘分析。

不得删除、绕过或弱化 Validator。

### 5.14 fallback thesis-aware

fallback 不能创建 thesis，也不能关闭 thesis。
有 active thesis + AI 失败：保留 thesis，挂单仍按计划触发，等下次重试。
无 active thesis + AI 失败：silent，不创建新 thesis。
L5 失败：Master 可以用 `macro_headwind_score=0` 的规则化 fallback 继续。
数据降级 Level 2+：不调 AI，进入 `review_pending`。

### 5.15 周复盘

周复盘 AI 输出 performance、system_health、strategy_quality、adjustment_recommendations、hard_constraint_activation_review。
周复盘结果不自动改参数。
用户根据建议手动调阈值或 prompt。
任何规则内容改动必须 bump `rules_version`。

### 5.16 网页原则

网页是审计系统，不是 AI 报告页面。
人读版解释必须规则化。
现有 UI 风格不允许随意大改。
前端展示改动必须小范围、可解释、可测试。

### 5.17 工程三纪律

继承建模工程三纪律：

- §X 删除纪律：旧代码必须删除，不堆叠；
- §Y commit 即 push：不允许累积本地 commit；
- §Z 端到端 DB 行数 / 字段值真实断言：不允许只 mock `.called=True`。

质量第一，不为成本妥协。

## 6. 高风险事项

以下事项属于高风险，Codex 必须谨慎处理。

必须先停下来问用户的事项：
1. 修改真实交易所下单逻辑；
2. 新增真实交易所 API 下单能力；
3. 修改仓位 sizing；
4. 修改止损止盈；
5. 修改杠杆、保证金、合约方向；
6. 修改开仓、平仓、反手规则；
7. 修改 hard_invalidation 规则平仓逻辑；
8. 修改 AI 裁决硬 prompt 的硬约束；
9. 修改 `.env`、API key、secret、token；
10. 恢复 Binance / Yahoo 等已退场数据源；
11. 启用 `position_health_check`；
12. 修改主裁决时间；
13. 修改 `BTC_USE_ORCHESTRATOR`；
14. 把当前虚拟账户系统改成真实自动交易机器人。

特别说明：
- commit / push 不在默认禁止项内，按第 10 节执行。
- 部署、SSH、systemctl restart、生产 DB 迁移 / 清污不在默认禁止项内，按第 11 节执行。
- 但如果部署或 DB 迁移会间接改变策略、仓位、止损、真实交易、真实账户权限，仍必须先问用户。

## 7. 默认允许的低风险任务

以下任务可以在计划后执行：

- 补文档；
- 写 Codex 报告；
- 增加只读诊断脚本；
- 增加不触网的单元测试；
- 修复明显的测试写死日期；
- 小范围修复前端展示文案；
- 整理项目结构说明；
- 对已有测试做 targeted pytest；
- 生成 diff 摘要。

即使是低风险任务，也必须先给计划，不要上来就改。

## 8. 测试规则

优先运行和本轮改动相关的 targeted tests。
如果没有运行测试，必须明确说明原因。
不要假装测试通过。

常用轻量测试：

```bash
uv run pytest -q tests/test_ai_client.py tests/test_api_v14_routes.py tests/test_master_input_builder.py tests/test_event_trigger.py
```

如果修改 scheduler：

```bash
uv run pytest -q tests/test_scheduler.py tests/test_scheduler_2_7_a_cron.py tests/test_jobs_weekly_review_and_health_check.py
```

如果修改虚拟订单 / 虚拟账户：

```bash
uv run pytest -q tests/test_orders_engine.py tests/test_virtual_orders_dao.py tests/test_virtual_account_manager.py tests/test_virtual_account_dao.py
```

如果修改 hard_invalidation：

```bash
uv run pytest -q tests/test_hard_invalidation_monitor.py tests/test_sprint_k_plus_hard_invalidation_classifier.py tests/test_sprint_k_plus_plus_hard_invalidation_filter.py
```

如果修改前端数据归一化：

```bash
uv run pytest -q tests/test_web_modules_1_2_3.py tests/test_web_modules_4_5_rp_failure.py tests/web_helpers/test_normalize_state.py
```

如果修改 DAO / schema / migrations，必须遵守 §Z：
- 测真实 SQLite 测试库；
- 断言真实 DB 行数；
- 断言真实字段值；
- 不允许只 mock `.called=True`。

如果只是纯文档改动，可以不跑 pytest，但必须说明“本轮仅文档改动，pytest 不适用”，并至少执行 `git diff --check` 或说明为什么无法执行。

## 9. 报告规则

Codex 的新报告统一写到：

`docs/codex_reports/`

不要继续把 Codex 报告写进 `docs/cc_reports/`，除非用户明确要求。
`docs/cc_reports/` 是 Claude Code / 历史 sprint 报告区。

每轮报告文件必须包含：
- 任务目标；
- 读取过的关键文件；
- 改动文件；
- 实际运行命令；
- 测试结果；
- 是否触碰高风险区域；
- 删除清单；
- 部署状态四件事清单；
- 风险和未完成；
- 下一步建议。

每轮对话收尾必须输出四段式：

一、完成了什么
二、证据是什么
三、风险和未完成
四、下一步建议

## 10. Git / commit / push 规则

Codex 继承旧 CC 的 §Y：**commit 后必须立即 push**。

每个产生交付改动的子任务完成后，必须：
1. 写入本轮报告；
2. 运行相关测试或说明不适用；
3. 执行 `git status`；
4. 执行 `git diff --check`；
5. 检查敏感信息；
6. 按需要执行 pre-commit / gitleaks；
7. `git add` 本轮相关文件；
8. `git commit`；
9. commit 后立即 `git push origin main`。

不允许累积本地 commit 等 sprint 收尾再 push。
用户的部署流程依赖 GitHub `origin/main`，本地 commit 对生产端不可见。
用户的事实核查依赖 GitHub commit hash，未 push 的 commit 会被误判为“幻觉”。

例外：
- 进入 hard-stop 决策点等待用户授权时，不该 commit，也不该 push；
- 测试失败且不是用户明确要求提交失败现场时，不该 commit，也不该 push；
- 发现敏感信息泄露风险时，不该 commit，也不该 push；
- 只是只读诊断、没有文件改动时，不需要 commit / push。

如果 push 失败，必须如实写：
- commit hash；
- push 失败原因；
- 是否仍停留在本地；
- 用户需要执行的命令。

不得把“本地 commit”说成“已推送”。

## 11. 部署 / SSH / systemctl / 生产 DB 规则

Codex 不是默认禁止部署。
如果本轮任务明确包含以下目标，Codex 可以按既有交付流程执行：

- 上线；
- 部署；
- 生产修复；
- 服务器验证；
- 生产 DB 迁移；
- 生产 DB 清污；
- sprint 交付要求生产健康检查。

执行部署前必须先说明计划。
执行部署后必须真实核查，不得用“已上线”“已部署”模糊概括。

部署状态四件事清单必须写入每轮报告末尾：

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅/❌/N/A |
| GitHub push(commit hash:xxxx) | ✅/❌ |
| 服务器 git pull | ✅/❌/待用户执行 |
| 服务器 systemctl restart | ✅/❌/待用户执行/N/A |
| 生产 DB 迁移 / 清污 | ✅/❌/待用户执行/N/A |
| 生产健康检查 `/api/system/health` | ✅/❌/待用户执行/N/A |

“待用户执行”和“✅”是不同状态。
如果某步需要 SSH 但 Codex 自己跑不通，必须明确写“待用户执行 + 命令”，不能省略，也不能写成已完成。

对话里不得写“上线完成”，除非：
1. GitHub push 完成；
2. 服务器 git pull 完成；
3. systemctl restart 完成或确认无需 restart；
4. 必要 DB migration / 清污完成或确认 N/A；
5. `/api/system/health` 检查通过。

如果只做了本地和 push，只能写：
“本地完成 + 已推送，服务器部署待执行。”

生产 DB 迁移 / 清污要求：
- 只在任务明确需要时执行；
- 执行前必须确认 migration 幂等性或说明风险；
- 执行后必须真实查询 DB 行数 / 字段值；
- 不得只看脚本退出码就宣称成功。

## 12. 安全与敏感信息

不要读取、输出、复制、记录任何真实 API key、token、secret、私钥、数据库密码。
即使历史报告或文件里已经出现过公开凭据，也不要在新的回复或报告里重复。
统一写成：
- `<env: KEY_NAME>`
- `<secret-redacted>`
- `<public-credential-redacted>`
- `<db-password-redacted>`

不要把 `.env`、日志、数据库、截图、临时验证产物提交到 git。

任何报告 commit 前自检：
- 是否出现 `sk-ant-`；
- 是否出现长 base64 串；
- 是否出现 Glassnode / CoinGlass / FRED 真实 key；
- 是否出现数据库密码；
- 是否出现 SSH 私钥内容；
- 是否出现用户私人邮箱 / 手机号。

命中就替换为占位符。

## 13. 旧代码删除纪律

旧代码必须删除，而不是堆叠。
新实现替代旧实现时，必须检查并清理旧函数、旧文件、旧配置、旧测试。
删除前必须 `git grep` 确认没有仍被使用。
报告必须写删除清单。
如果没有删除项，写“本轮无替代关系，无删除项”。

删除清单格式：

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| 函数 `_xxx` | `src/x/y.py:NNN` | 被 `_yyy` 替代，已确认 0 处引用 |
| 整个文件 | `src/old.py` | 新实现替代，`git grep` 0 引用 |
| yaml key | `config/x.yaml:zzz` | 关联代码已删 |

判断“是否要删”的两个测试：
- 新代码部署后，旧代码永远不会被调用？必须删。
- 旧代码留下来，未来读代码的人会困惑？必须删。

例外：旧代码确实仍被生产端调用或作为明确 fallback，必须在报告里写清楚保留理由。

## 14. 本轮任务边界

Codex 默认只做用户本轮明确要求的任务。
不要顺手优化。
不要看到问题就扩大范围。
不要擅自把文档修复升级成策略修复。
不要擅自把本地修复模糊成服务器上线。
下一步只能建议，不能自己继续执行。
