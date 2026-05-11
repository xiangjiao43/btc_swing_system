# Codex AGENTS 规则初始化报告

## 任务目标

只更新项目根目录 `AGENTS.md`，建立 Codex 专用工作规则；新增本报告 `docs/codex_reports/codex_agents_setup.md`。

本轮不修改交易逻辑，不运行真实 AI 主 pipeline，不运行真实数据抓取，不修改策略、仓位、止损止盈、scheduler、数据库 schema，也不触碰 `.env` 或真实 key。

## 读取过的关键文件

| 文件 | 读取目的 |
|---|---|
| `/Users/shenjun/Downloads/codex_update_agents_prompt_final_20260511.md` | 用户给定的本轮任务与 AGENTS 目标规则 |
| `AGENTS.md` | 确认旧 Codex/Claude 混用规则内容 |
| `README.md` | 确认当前项目真实运行口径 |
| `docs/cc_reports/sprint_takeover_baseline.md` | 确认 Codex 接管后的当前基线、部署事实和风险点 |
| `config/scheduler.yaml` | 确认当前主裁决时间 11:35 BJT、`position_health_check.enabled=false` |

## 改动文件

| 文件 | 改动 |
|---|---|
| `AGENTS.md` | 替换为 Codex 专用项目规则 |
| `docs/codex_reports/codex_agents_setup.md` | 新增本轮 Codex 报告 |

## 从 `CLAUDE.md` / `docs/modeling.md` 迁移的长期规则

1. `docs/modeling.md` 仍是建模蓝本，但 Codex 每轮只按任务相关性读取章节。
2. 保留双轨输出原则：机读版给 AI，规则化人读版给网页，禁止 AI 自由改写因子解释。
3. 保留执行顺序：数据采集 → L1-L5 → AI 裁决 → Validator → StrategyState / thesis / virtual account。
4. 保留 L3 `opportunity_grade` 唯一权威。
5. 保留 `hard_invalidation_levels` 是 stop loss 唯一来源。
6. 保留 1H 数据白名单。
7. 保留 position cap、execution permission、AI System Prompt、thesis 主线锁、反手三通道、Validator 24、fallback thesis-aware、周复盘、网页审计原则。
8. 保留工程三纪律：旧代码删除、commit 后立即 push、真实 DB 行数 / 字段值断言。

## 对 Codex 继续适用的旧 CC 规则

1. 用户是代码小白，回复必须使用中文“小白模式”。
2. 不把本地修复说成生产上线。
3. 报告必须真实写明测试、风险、部署状态。
4. 不读取、不输出、不提交真实 key / secret。
5. 不提交 `.env`、日志、数据库、截图、临时验证产物。
6. 旧代码被替代时必须删除，不堆叠。

## 已按当前真实配置处理的矛盾

| 旧口径 / 可能冲突 | Codex 当前规则 |
|---|---|
| `docs/modeling.md` 中旧的每日 16:00 BJT | 以 `config/scheduler.yaml` 当前 11:35 BJT 为准 |
| 旧 4h 持仓健康检查 | 当前 `position_health_check.enabled=false`，保持关闭 |
| Binance / Yahoo 旧数据源文字 | 当前不恢复 Binance / Yahoo；K 线和衍生品走 CoinGlass proxy，链上走 Glassnode proxy，宏观走 FRED |
| OPENAI_* 环境变量名 | 只是历史变量名；实际 AI SDK 是 `anthropic` |
| 旧 `/api/health` scheduler 字段 | 生产健康优先看 `/api/system/health` |
| 旧 14 档状态机 | 仅作为兼容映射；主线是 v1.4 `thesis.lifecycle_stage` |

## 第 4、第 5 条用户意见如何保留

用户确认保留旧 Claude Code 逻辑：

1. Codex 不是默认禁止 commit / push。产生交付改动后，必须 commit，并且每个 commit 后立即 `git push origin main`。
2. Codex 不是默认禁止部署 / SSH / systemctl / 生产 DB 迁移。如果本轮任务明确是上线、部署、生产修复、DB 迁移，或 sprint 交付需要生产验证，Codex 可以按既有部署流程执行。
3. 部署、SSH、systemctl、生产 DB 相关动作必须逐项真实核查，不能用“已上线”模糊概括。
4. 如果部署或 DB 迁移会影响策略、仓位、止损、真实交易、真实账户权限，仍必须先问用户。

## 实际运行命令

```bash
git status --short --branch
sed -n '1,220p' AGENTS.md
sed -n '1,140p' README.md
sed -n '1,130p' docs/cc_reports/sprint_takeover_baseline.md
sed -n '1,190p' config/scheduler.yaml
mkdir -p docs/codex_reports
```

收尾阶段已执行：

```bash
git status --short --branch
git diff --check
rg -n "sk-ant-|sk-[A-Za-z0-9_-]{20,}|AIza|xox[baprs]-|ghp_[A-Za-z0-9_]{20,}|-----BEGIN .*PRIVATE KEY-----" AGENTS.md docs/codex_reports/codex_agents_setup.md
```

结果：
- `git status`:仅本轮 `AGENTS.md` / `docs/codex_reports/` 变化,另有接手前已存在的 `uv.lock` 未暂存改动。
- `git diff --check`:通过。
- 敏感信息自检:无真实 key / secret。命中项仅为规则文档里用于提醒扫描的字面量模式,不是密钥。

## 测试结果

本轮仅文档规则更新，未修改 `src/`、`config/`、`tests/`、`web/`、`migrations/`，pytest 不适用。

已按文档任务要求执行或计划执行：
- `git status`
- `git diff --check`
- 敏感信息自检

## 是否触碰高风险区域

未触碰高风险区域：

- 未修改真实交易所下单逻辑；
- 未新增真实交易所 API 下单能力；
- 未修改仓位 sizing；
- 未修改止损止盈；
- 未修改杠杆、保证金、合约方向；
- 未修改开仓、平仓、反手规则；
- 未修改 hard_invalidation 规则平仓逻辑；
- 未修改 AI 裁决硬 prompt；
- 未修改 `.env`、API key、secret、token；
- 未恢复 Binance / Yahoo；
- 未启用 `position_health_check`；
- 未修改主裁决时间；
- 未修改 `BTC_USE_ORCHESTRATOR`；
- 未把虚拟账户系统改成真实自动交易机器人。

## 删除清单

本轮无替代关系，无删除项。

理由：本轮只替换 `AGENTS.md` 的规则文本并新增 Codex 报告，没有删除旧代码、旧配置、旧测试或旧文件。

## 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | N/A，本轮仅文档规则更新 |
| GitHub push(commit hash:提交后补记) | 待执行 |
| 服务器 git pull | N/A，本轮不部署 |
| 服务器 systemctl restart | N/A，本轮不重启服务 |
| 生产 DB 迁移 / 清污 | N/A，本轮不碰生产 DB |
| 生产健康检查 `/api/system/health` | N/A，本轮不部署 |

## 风险和未完成

1. `uv.lock` 仍有接手前已有的本地改动，本轮不触碰、不提交。
2. 本报告中的 commit hash 需要在提交后补充。
3. 本轮不做服务器部署，因此生产端只有 GitHub 规则文件更新，不涉及服务运行变化。

## 下一步建议

后续所有 Codex 任务按新的 `AGENTS.md` 执行：

1. 先用“小白模式”说明计划；
2. 只做本轮明确任务；
3. 报告写入 `docs/codex_reports/`；
4. 产生交付改动后 commit 并立即 push；
5. 只有任务明确需要部署时才 SSH / restart / 查生产健康。
