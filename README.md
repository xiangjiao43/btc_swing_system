# BTC 中长线低频双向波段交易辅助系统

一个面向 BTC 现货与永续合约的中长线、低频、双向波段**交易辅助**系统。
定位是"决策助手",不是自动交易机器人:生成带证据的策略状态与行动建议,交易下单仍由人执行。

## 核心特征

- **低频**:扫描节奏 4h / 事件触发,刻意避开日内噪音
- **双向**:LONG 与 SHORT 都是一等公民,但做空门槛更高
- **证据驱动**:五层证据(L1 市场状态 / L2 方向结构 / L3 机会执行 / L4 风险失效 / L5 背景事件)→ AI 裁决 → StrategyState
- **保护性默认**:数据新鲜度不足、证据冲突、事件高密度等情况下优先 HOLD / PROTECT

详细建模见 [docs/modeling.md](docs/modeling.md)(v1.2,编码唯一蓝本)。
项目决策与里程碑见 [docs/PROJECT_LOG.md](docs/PROJECT_LOG.md)。

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

当前:**v0.0 项目初始化(Sprint 1 前置工作)**

后续版本计划见 [docs/modeling.md](docs/modeling.md) §10.5。

## 快速开始

本项目使用 [uv](https://docs.astral.sh/uv/) 管理 Python 环境与依赖。

```bash
# 安装依赖(首次)
uv sync

# 复制环境变量模板并填入真实 Key
cp .env.example .env
# 然后用编辑器填写 .env 里的 BASE_URL / API_KEY

# 后续命令由 Sprint 1 代码落地后补充
```

## 目录结构

见 [docs/modeling.md](docs/modeling.md) §10.3。
