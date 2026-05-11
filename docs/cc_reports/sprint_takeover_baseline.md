# Sprint Takeover Baseline — Codex 接管基线整理

## Triggers

- 无建模偏离。本 sprint 不改交易策略、不改 AI prompt 决策原则,仅整理接管配置、旧说明与本地启动路径。
- 自主修复一处日期敏感测试:`tests/test_lsr_alias_dedup.py` 写死 `2026-04-29`,在 2026-05-11 已滚出 `lookback_days=10`。
- 本地 `.env` 只补 `BTC_USE_ORCHESTRATOR=true`,未读取、覆盖或输出任何真实 key。

## 完整改动文件列表

### 已提交到 GitHub

| 文件 | 变更 |
|---|---|
| `AGENTS.md` | 新增 Codex 接管说明文件,内容与 `CLAUDE.md` 保持一致,仅标题不同 |
| `CLAUDE.md` | 修正 v1.4 路径:Master / L5 / FRED / thesis lifecycle |
| `README.md` | 修正低频节奏、v1.4 输出链、migration 017、生产节奏、快速开始 |
| `.env.example` | 新增 `BTC_USE_ORCHESTRATOR=true`,修正 FRED / Yahoo / Anthropic SDK 注释 |
| `config/ai.yaml` | 修正 SDK 注释与 `protocol.sdk=anthropic` |
| `config/scheduler.yaml` | 修正 job 总览、主裁决 11:35 BJT、v1.4 orchestrator 注释 |
| `src/scheduler/jobs.py` | 修正 scheduler 顶部说明与旧 16:05/多档注释 |
| `scripts/init_v14_tables.py` | 幂等补齐 002/005 列迁移 + 016/017 表迁移,适配旧本地 DB |
| `tests/test_lsr_alias_dedup.py` | 将写死日期改为相对日期,避免测试随时间失效 |

### 本地已配置但未提交

| 对象 | 动作 |
|---|---|
| `.env` | 增加 `BTC_USE_ORCHESTRATOR=true`;真实 key 未触碰 |
| `data/btc_strategy.db` | 已先备份,再跑 `scripts/init_v14_tables.py` 幂等补齐 |
| `data/btc_strategy.db.bak_takeover_baseline_20260511` | 本地 DB 迁移前备份,gitignored |

### 未纳入本次提交

| 对象 | 原因 |
|---|---|
| `uv.lock` | 接手前已有本地镜像源改动,本 sprint 不触碰、不提交 |

## 关键 diff

1. `README.md` 将旧 “4h cron + event_onchain” 改为 “每日 11:35 BJT 主裁决 + event_price/event_macro + 1h hard_invalidation”。
2. `.env.example` 明确 v1.4 主路径必须保留 `BTC_USE_ORCHESTRATOR=true`。
3. `config/ai.yaml` 从旧注释 “openai SDK” 对齐为当前真实实现 “anthropic SDK + 历史 OPENAI_* 环境变量名”。
4. `scripts/init_v14_tables.py` 新增 `_add_column_if_missing()`,旧 DB 可安全补齐:
   - `derivatives_snapshots.liquidation_*`
   - 四张 metric 表 `inserted_at_utc`
   - `fetch_attempts`
   - drop 已废弃 `data_fetch_log`
5. `tests/test_lsr_alias_dedup.py` 使用 `_two_recent_days()` 生成测试 timestamp,不再随日历滚动失败。

## 设计决策

- 不改交易策略、不改 Master prompt、不改 validator 规则,避免在接管第一步引入业务行为变化。
- `AGENTS.md` 入仓,让 Codex 后续接手时能直接读取同一套项目纪律。
- `init_v14_tables.py` 不直接重复执行 `002/005` SQL,因为 SQLite 重复 `ADD COLUMN` 会失败;改用 PRAGMA 条件 ALTER。
- 本地 DB 迁移前保留备份,避免对用户已有本地数据做不可逆操作。
- `uv.lock` 是接手前脏改动,按“不回滚用户改动”原则保留原状。

## 验收记录

| 项目 | 结果 |
|---|---|
| upstream | ✅ `main` 已绑定 `origin/main` |
| 轻量测试 | ✅ 97 passed,150 warnings |
| 全量 pytest | ✅ 1751 passed,1 skipped,648 warnings |
| diff check | ✅ `git diff --check` 通过 |
| pre-commit gitleaks | ✅ commit 时通过 |
| 本地 DB 备份 | ✅ `data/btc_strategy.db.bak_takeover_baseline_20260511` |
| 本地 DB 迁移 | ✅ `fetch_attempts` 存在,`data_fetch_log` 已无表;四张数据表补齐 `inserted_at_utc` |

## 部署日志

- 代码提交并推送:`9aed58e chore: align takeover baseline with v1.4`
- 本次未 SSH 到服务器部署;服务端仍需用户按部署窗口拉取并重启。
- 本地 `.env` 已补 orchestrator 开关;生产 `.env` 是否已有该开关需 SSH 后核查。

## 未覆盖项

1. 生产服务器未执行 `git pull` / `systemctl restart`。
2. 生产 `.env` 未核查 `BTC_USE_ORCHESTRATOR=true`。
3. 生产 DB 未重新跑本次增强后的 `scripts/init_v14_tables.py`;若服务器已在 Sprint K++ 状态,大概率无需变更,但可幂等复核。
4. `uv.lock` 本地仍有接手前的镜像源差异,需用户决定是否保留。

## 风险提示

- 本 sprint 修改 `config/ai.yaml` 的 `protocol.sdk` 字段为 `anthropic`,当前代码未读取该字段,属于文档化对齐;若未来有人开始消费该字段,语义已与真实客户端一致。
- 本地 DB 已迁移并有备份;生产端是否需要同样操作取决于服务器实际 schema。
- `AGENTS.md` 与 `CLAUDE.md` 基本重复,这是为了兼容 Codex / Claude 两套工具读取入口。

## 本 sprint 删除清单

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| SQLite 表 `data_fetch_log` | 本地 `data/btc_strategy.db` | 已由 `fetch_attempts` 完整替代;本次通过 017 幂等 DROP 清理本地残留 |

自检:代码层无 `data_fetch_log` 读写路径;命中仅剩 migration / schema 注释 / DAO 废弃说明。

## 部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 1751 passed,1 skipped |
| GitHub push(commit hash:9aed58e) | ✅ |
| 服务器 git pull | 待用户执行:`ssh ubuntu@124.222.89.86 "cd /home/ubuntu/btc_swing_system && git pull origin main"` |
| 服务器 systemctl restart | 待用户执行:`ssh ubuntu@124.222.89.86 "sudo systemctl restart btc-strategy.service"` |
| 生产 DB 迁移 / 清污 | 待用户执行/可选核查:`ssh ubuntu@124.222.89.86 "cd /home/ubuntu/btc_swing_system && uv run python scripts/init_v14_tables.py data/btc_strategy.db"` |
