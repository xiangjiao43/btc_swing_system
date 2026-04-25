# Sprint 2.5-meta — Dual-Track Output Principle 落档

**Date:** 2026-04-25
**Branch:** main
**Type:** docs / process

## 改动文件

| 文件 | +/− | 说明 |
|---|---|---|
| `docs/modeling.md` | +71 / 0 | §2.2 加第 9 条核心原则 + 新增 §2.5 完整双轨原则段(含当前实现对照表 + v1.3 待办) + 版本变更记录追加 Sprint 2.5-meta 一行 |
| `CLAUDE.md` | +18 / 0 | 在「系统硬纪律」之前插入新章节「## 双轨输出原则(每次开发必读 — 建模 §2.5)」,5 条硬约束的简短引用 + 例外审计提示 |
| `docs/cc_reports/sprint_2_5_meta.md` | +N / 0 | 本报告 |

## 关键插入点

### `docs/modeling.md` §2.5(新增)

完整 5 条硬约束 + 受众/格式/位置三联(机读 vs 人读) + 设计意图 + **当前实现对照表**:

| 内容 | 机读位置 | 人读位置 | AI 是否参与人读 |
|---|---|---|---|
| L1-L5 结论 | `state.evidence_reports.layer_*` raw | `inject_plain_readings()` | ❌ |
| L1-L5 三支柱 / 四角度 | `state.evidence_reports.layer_*.pillars` raw | `inject_pillars()` | ❌ |
| 6 组合因子 composition / 规则 / 影响层 | `state.composite_factors[k]` raw | `inject_composite_composition()` | ❌ |
| trade_plan / narrative | adjudicator 结构化字段 | adjudicator narrative | ✅(综合裁决) |
| 6 组合因子双段(2.5-B 引入) | adjudicator composite_factors[] | 同字段直接渲染 | ⚠ 例外 |

### `docs/modeling.md` §2.5 末段 — v1.3 待办

记录 Sprint 2.5-B 的"6 张组合因子双段 AI 分析"违反原则 #5 的事实。当前临时保留是因为:
- 用户明确需求
- 5 条硬约束兜住失真(数字必出 / 规则编号必引 / stance/regime/phase 必落地)
- 软约束记 notes 有事后审计

下次复盘需选择:
- (A) 改规则化生成
- (B) 在原则中追加"AI 生成的人读版必须满足审计性约束"的例外条款

### `CLAUDE.md` 新章节插入位置

放在「系统硬纪律」之前,确保 CC 每次启动都先读到。简短 5 条 + 设计意图 + 例外审计提示。

## 设计决策

1. **插入位置选 §2.5 而非 §0.5**:用户原话给了"建议第 1 章总览 或 新增 §0.5",但
   §0.5 不存在(没有 §0.x 编号体系),且双轨原则本质是"架构原则",归在第二部分
   总体架构 §2.5 比挂在 §0 更自然。同时在 §2.2 核心原则列表加第 9 条做指针。

2. **版本变更记录追加 Sprint 2.5-meta 一行**:让审计者能从 commit 历史回溯到本次落
   档的具体语境。

3. **当前实现对照表**:把"哪些是规则生成 / 哪些是 AI 生成"逐项列出,既是现状记录
   也是未来变更的 baseline。

4. **2.5-B 例外明文标注**:不掩盖 Sprint 2.5-B 的双段 AI 分析违反原则 #5 的事实,
   列入 v1.3 待办。让原则有刚性,不靠"沉默"绕过。

5. **CLAUDE.md 新章节插入位置**:放在「系统硬纪律」之前,而非合并进硬纪律列表。
   原因:硬纪律已有 10 条,加第 11 条会冗长;独立章节更醒目。

## 验收

- 双文件 diff 查 `git diff docs/modeling.md CLAUDE.md`
- 无代码 / 测试改动,无需跑 pytest
- 不需要部署到服务器(仅 docs)

## 未覆盖项 / 风险

1. **2.5-B 双段 AI 分析的整改路径未定**:是改规则化(选 A)还是写入例外(选 B),
   下次复盘必须定。如果选 A,需要为 6 个 composite 各写一个 narrative 模板函数,
   工作量小;如果选 B,需要把"5 条硬约束 + notes 审计"提升为正式条款。
2. **建模文档 v1.3 时机未定**:目前用"v1.2 增补"标注,严格说不算 v1.3。如果未来
   修订项累积,需要正式 bump v1.3。
3. **现有"人读版"代码未审计是否真的零 AI 介入**:`inject_plain_readings()` /
   `inject_pillars()` / `inject_composite_composition()` 是否真的全部规则化?需要下
   次扫描 import 路径确认无任何 anthropic / claude 调用混入。
