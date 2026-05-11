# BTC 中长线低频双向波段交易辅助系统

一个面向 BTC 现货与永续合约的中长线、低频、双向波段**交易辅助**系统。
定位是"决策助手",不是自动交易机器人:生成带证据的策略状态与行动建议,交易下单仍由人执行。

## 核心特征

- **低频**:每日主裁决 + 事件触发 + 小时级硬失效位监控,刻意避开日内噪音
- **双向**:LONG 与 SHORT 都是一等公民,但做空门槛更高
- **证据驱动**:五层证据(L1 市场状态 / L2 方向结构 / L3 机会执行 / L4 风险失效 / L5 宏观)→ Master AI → Validator 24 → StrategyState / thesis / virtual account
- **保护性默认**:数据新鲜度不足、证据冲突、事件高密度等情况下优先 HOLD / PROTECT

详细建模见 [docs/modeling.md](docs/modeling.md)(v1.4,编码唯一蓝本)。
项目决策与里程碑见 [docs/PROJECT_LOG.md](docs/PROJECT_LOG.md);
sprint 实施报告见 [docs/cc_reports/](docs/cc_reports/)。

## v1.4 完整版上线状态(2026-05-04)

**13 sprint 全完成**(1.10-A → 1.10-L),v1.4 完整版正式上线。

| 类别 | 数据 |
|---|---|
| 累计 commit | 88+(1.10-A → L)|
| 单测 | 1534 passed, 1 skipped, 0 failed |
| §Z verify | 4 套累计 201 项全过(v14:37 + kb:40 + ka:79 + L:45) |
| migration | 017(fetch_attempts 替代 data_fetch_log) |
| 业务模块 | 16+(virtual_account / orders_engine / thesis_manager / fuse_monitor / lifecycle_manager / state_machine / protection_handler / cooldown_manager / review_pending / hard_invalidation_monitor / 等) |
| AI agent | 8(L1-L5 + master + weekly_review + emergency_simplified) |
| 网页模块 | 5 模块 + 12 卡 + 五层 6 卡 + 45 因子 + Validator 表 + RP 横幅 |
| 主 AI 真跑 | claude-sonnet-4-5-20250929(Anthropic 中转站)|
| Validator 24 + meta | 1.10-L commit 11a 真接通(1.10-E 起 4+ sprint 首次真写入 DB) |

生产部署:`http://124.222.89.86`(每日 11:35 BJT 主裁决 + event_price/event_macro + 1h hard_invalidation;实际部署状态以最新 cc_reports 为准)。

## Security

- This repository is public.
- All API keys are injected via `.env` (gitignored, never committed).
- Pre-commit gitleaks hook is configured; run `pre-commit install` after cloning.
  See [docs/dev_setup.md](docs/dev_setup.md).
- Production server credentials in historical sprint reports are intentionally public per owner's decision.

## 技术栈

- Python 3.12
- FastAPI(后端 API)
- SQLite(v0.x)→ PostgreSQL(v1.0)
- pandas / numpy(数据处理)
- APScheduler(调度)
- anthropic SDK(AI 裁决,经中转站)

## 开发阶段

当前:**v1.4 完整版上线**(2026-05-04,Sprint 1.10-L 完成,生产实时跑)

后续版本计划见 [docs/modeling.md](docs/modeling.md) §10.5(v1.5b 路线图)+ §11.5
(v1.4 实施期发现的修订项 + future 改进清单)。

## 快速开始

本项目使用 [uv](https://docs.astral.sh/uv/) 管理 Python 环境与依赖。

```bash
# 安装依赖(首次)
uv sync

# 复制环境变量模板并填入真实 Key
cp .env.example .env
# 然后用编辑器填写 .env 里的 BASE_URL / API_KEY,并保留 BTC_USE_ORCHESTRATOR=true

# 轻量 smoke test
uv run pytest -q tests/test_ai_client.py tests/test_api_v14_routes.py tests/test_master_input_builder.py tests/test_event_trigger.py
```

## 目录结构

见 [docs/modeling.md](docs/modeling.md) §10.3。
