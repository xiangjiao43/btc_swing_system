# 项目日志(PROJECT_LOG)

本文件记录 BTC 中长线低频双向波段交易辅助系统在开发过程中的关键决策、里程碑与版本变更。
流水式倒序排列(最新在上)。非决策性的细节或临时状态不写入本文件,保持信噪比。

---

## 2026-04-22 — 项目初始化 / v1.2 建模完成,Sprint 1 前置工作计划

### 里程碑

- 建模文档 v1.2 定稿并归档至 [docs/modeling.md](modeling.md),作为编码唯一蓝本。
- 初始化项目骨架:目录结构按建模文档 §10.3 搭建;`uv init --python 3.12`;基础依赖登记到 `pyproject.toml`(未安装)。
- 本地 Git 仓库初始化,首次提交 `Initial project structure with v1.2 modeling doc`。

### Sprint 1 前置工作(三项优化)

在进入 Sprint 1(v0.1 骨架编码)之前,先完成三项基础优化,以降低后续编码阶段的返工成本。

**优化一:Schemas 契约(字段唯一真相来源)**

- 抽取建模文档中所有字段:
  - `StrategyState` 的 12 个业务块
  - 五层 `EvidenceReport`(L1 regime / L2 direction / L3 opportunity / L4 risk / L5 macro)
  - 6 个组合因子的 output
  - `AIAdjudicatorInput` / `AIAdjudicatorOutput`
- 生成 `config/schemas.yaml` 或 `config/schemas.json`,作为全项目字段的唯一真相来源。
- 所有 Pydantic model 后续从这份 schema 生成或与之对齐。
- **目的**:避免编码期字段散落在 3000 行建模文档里,减少跨模块字段不一致。

**优化二:9 个 Config 文件骨架**

- 按建模文档 §10.3 填充 9 个 config 文件的字段结构:
  - `base.yaml`
  - `data_sources.yaml`
  - `data_catalog.yaml`
  - `layers.yaml`
  - `state_machine.yaml`
  - `thresholds.yaml`
  - `event_calendar.yaml`
  - 3 个 prompt 文件:`adjudicator_system.txt` / `layer5_context.txt` / `adjudicator_fewshot_*`
- 骨架包含字段名 + 类型 + 示例值,真实数值和 API key 留到后续填。
- 其中 `event_calendar.yaml` 按 v1.2 M39 要求,用 `America/New_York` 时区存储 2026 全年 FOMC / CPI / NFP。
- **目的**:config 格式固定,代码只是读取层;后续改参数改 config,不改代码。

**优化三:3 个测试快照(fixtures)**

- 准备 3 个历史日期的完整数据快照,服务于单元测试和 M26 可交易性验收:
  - **场景 1(主升浪)**:2020-10-15
  - **场景 2(主跌浪)**:2022-05-01
  - **场景 3(震荡)**:2023-07-01
- 每个快照含:当天的原始数据(K 线 / 衍生品 / 链上 / 宏观)+ 预期证据层输出(regime、stance、phase、cycle_position 等)。
- 存到 `tests/fixtures/{scenario_name}/` 下,JSON 格式。
- **目的**:写函数时可以快速单元测试(输入快照 → 期待输出),不需要每次跑完整管道。

### 下一步

- 优化二的第一小步:生成 9 个 config 文件骨架(将另起对话)。
- 优化一、三依次推进;三项全部完成后进入 Sprint 1(v0.1 数据管道 + L1+L2 规则)。

---
