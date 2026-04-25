# Sprint 2.5-cleanup — 审计后清理 + 登记 L5=AI 设计意图

**Date:** 2026-04-25
**Branch:** main
**Type:** chore + fix + docs
**触发:** sprint_2_5_ai_audit 报告的 3 项小清理 + 1 项架构对齐

---

## 任务执行结果总览

| 任务 | 状态 | commit | 备注 |
|---|---|---|---|
| A · 删 `src/ai/summary.py` | ⛔ **STOP** | 未执行 | 该文件被 `src/pipeline/state_builder.py:35,231` 和 `src/ai/__init__.py:7,14` 引用,非死代码;按指令"有调用 → 停下问用户" |
| B · 删 `config/prompts/adjudicator_system.txt` | ✅ | `124cd51` | 全代码库 0 引用,直接删除 |
| C · 修 3 张卡 narrator 占位文案 | ✅ | `08a9384` | truth_trend / crowding / macro_headwind 加 score-line 触发条件 + event_risk 同步;新加 6 个 pytest case |
| D · 登记 L5=AI 设计意图 | ✅ | `fc27bfa` | modeling §6.8 末段 + §2.5 对照表 + CLAUDE.md 双轨段同步 |

---

## 任务 A 详细停下原因

### 扫描结果

```
$ grep -rnE "from .*ai\.summary|from .*ai import summary|import.*ai\.summary|call_ai_summary" src/ scripts/
src/pipeline/state_builder.py:35:from ..ai.summary import call_ai_summary
src/pipeline/state_builder.py:223:            ai_caller:          覆盖默认的 call_ai_summary(测试注入)
src/pipeline/state_builder.py:224:            openai_client:      传给 call_ai_summary(mock 用)
src/pipeline/state_builder.py:231:        self._ai_caller = ai_caller or call_ai_summary
src/ai/__init__.py:7:    call_ai_summary,
src/ai/__init__.py:14:    "call_ai_summary",
```

### 现状分析

`src/ai/summary.py` 当前:
- 被 `state_builder.py` 在 pipeline 阶段 3.5 主动调用(`ai_summary` stage)
- 输出 `state.context_summary.summary_text` 写入 DB
- **无下游消费**:
  - adjudicator 只读 `context_summary.status`(facts.context_summary_status),不读 `summary_text`
  - 前端 grep 0 命中 `summary_text` / `context_summary`
  - 因此实际是"AI 调一次,结果只落 DB,没人用"

### 三个整改选项(同 sprint_2_5_ai_audit §4)

- **选项 A**:删 summary.py + 删 state_builder 的 `ai_summary` stage(行 33-477 调用链)+ 删 `__init__.py` 导出 → 节省每 4h 一次 AI 调用 + 简化 pipeline
- **选项 B**:重构成 modeling §6.8 真正的"L5 宏观摘要"AI(挪到 `src/evidence/layer5_macro.py` 内部),与 Sprint 2.6 的 L5=AI 实施一并做
- **选项 C**:保持现状 + 在文件 docstring 标注"v1.1 历史实现,产出无下游消费,作为 DB 归档"

**等用户决策。** 推荐 B(与 Sprint 2.6 合并),因为修 macro collector 时刚好一起重构。

---

## 任务 B(删冗余 prompt 文件)

```
$ grep -rn "adjudicator_system" src/ scripts/ tests/
(0 hits)
$ rm config/prompts/adjudicator_system.txt
$ ls config/prompts/
adjudicator_user_template.txt
layer5_context.txt
```

`adjudicator.py` 用的是 inline `_SYSTEM_PROMPT`(第 64 行起),不读文件。该文件是 v1.x 早期遗留。

---

## 任务 C(narrator 占位文案修复)

### 修改位置
`src/strategy/composite_composition.py` 4 个 narrator 函数:

| 函数 | 旧逻辑 | 新逻辑 |
|---|---|---|
| `_truth_trend_narrative` | `if score is not None: parts.append(f"合计 {N}/9")` | `if score is not None and (have_data or score != 0): parts.append(...)` |
| `_crowding_narrative` | `if score is not None: parts.append(f"合计 {N}/8")` | 同上 |
| `_macro_headwind_narrative` | `if score is not None: parts.append(f"综合 {X}")` | 同上 |
| `_event_risk_narrative` | `if score is not None: parts.append(f"加权 {X}")` | 同上(配合既有"未来 72 小时无登记事件"分支) |

`_band_position_narrative` 和 `_cycle_position_narrative` 不在修复列表 — 它们没有 score 行,本就是"全空 → fallback"。

### 测试新增
`tests/test_composite_narrative.py` 加新 class `TestEmptyDataPlaceholderSuppressed`,6 个 case:
- 3 个 fallback 验证(truth_trend / crowding / macro_headwind 全空 + score=0)
- 1 个 event_risk "无事件" 分支验证
- 1 个 "有数据时占位行仍输出" 反向验证(truth_trend score=0 + 1 项数据 → 应有 "合计 0/9")
- 1 个 "score 非 0 时无数据也输出" 验证(macro_headwind score=-3 + 全空 → "综合 -3.0")

### pytest 结果
```
$ .venv/bin/python -m pytest tests/ -q
391 passed, 1 skipped, 84 warnings in 1.92s
```
(385 → 391,新增 6 个)

---

## 任务 D(登记 L5=AI 设计意图)

### `docs/modeling.md` §6.8 末段新增「实施状态」

```
本层 AI 接入为已确认的设计意图,与双轨原则 §2.5 一致(AI 在此做综合判断,
非人读层文案改写)。具体实施排在 Sprint 2.6,前置条件:macro_metrics
数据回填完成(Yahoo + FRED collector 修复)。当前过渡期使用规则化 fallback,
产出 macro_headwind_score = 0.0,等价于"无宏观信号"。
```

### `docs/modeling.md` §2.5 对照表新增 1 行 + 修订 narrative 行注释

```diff
- | 综合 trade_plan / 主叙事 narrative | adjudicator 输出的结构化字段 | adjudicator 输出的 narrative 文本 | ✅ 是(唯一允许的"综合裁决"环节) |
+ | 综合 trade_plan / 主叙事 narrative | adjudicator 输出的结构化字段 | adjudicator 输出的 narrative 文本 | ✅ 是(允许的"综合裁决"出口 #1) |
+ | L5 宏观综合判断(规划中,待 Sprint 2.6 实施) | 宏观数据 / 事件输入 → AI → Layer5Output schema | adjudicator 通过 L5 输出消费,不直渲染 | ✅ 是(允许的 AI 出口 #2,详见 §6.8 实施状态段) |
```

### `CLAUDE.md` 双轨原则段新增「合规 AI 出口清单」

```
**合规 AI 出口清单**:
- #1 综合裁决 — src/ai/adjudicator.py,产 trade_plan + narrative,已实施
- #2 L5 宏观综合判断 — 规划中,实施待 Sprint 2.6(前置:macro collector 修复)
```

---

## 部署 + 验证

### 部署日志
```
$ git push  # 3 commits: 124cd51, 08a9384, fc27bfa
$ ssh ubuntu@124.222.89.86 'cd ~/btc_swing_system && git pull && sudo systemctl restart btc-strategy && .venv/bin/python scripts/run_pipeline_once.py'
active
pipeline.failure_count: 0
```

### 6 张卡 curl 验证(2026-04-25 部署后实拍)

| key | missing | current_analysis(前 60 字) |
|---|---|---|
| `truth_trend` | 5/5 | `基础数据暂未就绪,无法生成态势分析` ✅ fallback |
| `band_position` | 4/4 | `基础数据暂未就绪,无法生成态势分析` ✅ fallback(不在修复列表,但本就 fallback) |
| `cycle_position` | 1/4 | `MVRV-Z=0.83、NUPL=0.31、距 ATH -32.1%、判档 early_bull。` ✅ 正常 |
| `crowding` | 4/6 | `资金费率 -0.4900%、大户多空比 0.71、合计 2/8。` ✅ 正常(score=2,非 0,合计行保留) |
| `macro_headwind` | 5/5 | `基础数据暂未就绪,无法生成态势分析` ✅ fallback(原"综合 0.0"消失) |
| `event_risk` | 5/5 | `未来 72 小时无登记事件(FOMC / CPI / NFP / 期权大到期)。` ✅ 走"无事件"分支(原"加权 0.0"消失) |

### 验收对照
| 验收项 | 结果 |
|---|---|
| 1. `ls config/prompts/adjudicator_system.txt` → No such file | ✅ |
| 2. `ls src/ai/summary.py` → No such file | ❌ 未删(任务 A 停下问) |
| 3. truth_trend / macro_headwind / event_risk 不再出现"合计 0/9 / 综合 0.0 / 加权 0.0" | ✅ |
| 4. cycle_position / crowding / band_position 叙述照常 | ✅ |
| 5. modeling §6.8 末段 + CLAUDE.md L5 注记到位 | ✅ |
| 6. pytest 全过 | ✅ 391 passed |

---

## 决策项(等用户)

1. **任务 A 整改方向**:A 删除链 / B 与 Sprint 2.6 合并重构成真 §6.8 / C 保留+加注释。推荐 B
2. 是否在 `config/prompts/adjudicator_user_template.txt` / `layer5_context.txt` 也做同样的"是否被代码引用"扫描

## 风险

1. 当前 `summary.py` 每 4h pipeline 调一次 Claude AI,产生**真实 token 消耗**(约 800 tokens),但产出无下游消费 — 决策 A 之前每天浪费 6 × 800 = 4800 tokens
2. 任务 D 的 §6.8 末段说"实施排在 Sprint 2.6",但 Sprint 2.6 任务本身尚未明确定义,需用户开 Sprint 2.6 时确认
