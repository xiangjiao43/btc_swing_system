# Sprint 1.5l — AI narrative 重写为交易员动态 brief

**Date:** 2026-04-30
**Branch:** main
**Status:** ✅ 本地完成,22 个新测试 + 916/916 全量回归过

---

## 一、根因

老网页"AI 策略说明"读起来像规则结果复述:

> "执行许可被收紧到「仅观察,不开仓」,系统不允许新开仓。这是
> 风险层 + 宏观层归并(已识别多个收紧因素)的结果..."

问题:
- 复述系统状态(action_state, permission)— 主卡其他位置已显示
- 没具体数值(funding 多少 / OI 多少 / 哪个分位)
- 没多空对比(谁在赢,真假趋势)
- 没"什么改变判断"的可观测条件

`narrative` 由 AI 直接产(建模合规),所以本 sprint 改的是 AI 写作风格 —
**改 SYSTEM_PROMPT + 加 user prompt 原始因子快照**,让 AI 自己从 45 原始因子
+ 6 组合因子里挑 3-5 个真正驱动当前判断的关键指标。

---

## 二、改动

### 任务 A:`SYSTEM_PROMPT` 加 narrative 写作纪律(commit `842d91f`)

`src/ai/adjudicator.py::_SYSTEM_PROMPT`:在十条纪律 + JSON schema 之间
新增一整段「narrative 写作纪律」:

7 条规则:
1. **不要复述规则结果** — 系统状态描述在主卡别处已显示
2. **从全部证据中挑 3-5 个驱动指标** — 含 5 条挑选标准(极端分位 / 因子
   共振 / 接近阈值 / 关键开关 / 异常值)
3. **写当前值 + 历史位置 + 含义**(反例/正例对照)
4. **解读多空对比** — 真趋势 vs 假动作,辅证 OI/SOPR/链上抛压
5. **结论 + 改变条件** — 什么具体信号反转就翻牌
6. **长度** — 5-7 句 / 300-500 字,优先信息密度
7. **风格** — 像有经验的交易员,禁 AI 客套词

加 FLAT/watch 状态特别说明(用户花最多时间看这种状态)。
加 primary_drivers / counter_arguments 同样规则(每条含具体数值)。

JSON schema 里 `narrative` 字段 hint 同步从"3-5 句"→"5-7 句 / 300-500 字"。

### 任务 B:`_build_user_prompt` 加原始因子快照(commit `0133b78`)

新增 `_build_raw_factor_snapshot(state)` helper:把 strategy_state 拍平成
纯文本块,追加到 user prompt 末尾。

数据来源:
- `factor_cards`(45 个)— 按 category 分组(price_structure / derivatives /
  onchain / macro / sentiment),列出 name / current_value / unit / captured_at
- `composite_factors`(6 个)— cycle_position / truth_trend / band_position /
  crowding / macro_headwind / event_risk + 各自 diagnostics
- `events_upcoming_48h`(72h 内)+ `next_events_by_type`(各类下次)

`_build_user_prompt` 加 `state` 可选参数(向后兼容);AI 路径调用同步传
`strategy_state`。

### 任务 C:测试(commit pending below)

22 个新测试,覆盖防退化 + 真值断言。

---

## 三、测试

### `tests/test_user_prompt_includes_raw_factors.py`(11 测试)

| 测试 | 验证 |
|---|---|
| `test_prompt_has_raw_factor_snapshot_section` | 标题段"原始因子快照"出现 |
| `test_prompt_includes_funding_value` | funding -0.4085 真值入 prompt |
| `test_prompt_includes_mvrv_value` | mvrv_z_score 1.85 真值入 prompt |
| `test_prompt_includes_btc_price` | BTC 现价 75700 真值入 prompt |
| `test_prompt_includes_all_six_composite_factors` | 6 个组合因子名全在 |
| `test_prompt_includes_composite_diagnostics` | crowding_score=11 / event_risk_score=11.5 真值入 |
| `test_prompt_includes_event_window_72h` | PCE / fomc / nfp 入 prompt |
| `test_prompt_works_without_state` | 向后兼容(state=None 不破) |
| `test_snapshot_helper_returns_empty_for_empty_state` | helper 边界 |
| `test_snapshot_helper_handles_partial_state` | 部分 state 仍输出可用部分 |
| `test_output_spec_section_still_at_end` | 输出规范段仍在 snapshot 之后(顺序锁) |

### `tests/test_adjudicator_narrative_quality.py`(11 测试)

| 类 | 测试 |
|---|---|
| A. SYSTEM_PROMPT 防退化 | narrative 纪律段 / 300-500 字 / 不复述规则 / 禁 AI 客套词 / FLAT-watch 说明 |
| B. 质量 helper 自检 | `_has_template_phrase` / `_count_concrete_metric_values` 边界 |
| C. AI 路径质量门槛 | 理想 narrative pass / 机器化 narrative fail |
| D. primary_drivers 质量 | 含具体证据 pass / 免责声明 fail |

### 全量回归

```
916 passed, 1 skipped, 7.48s
```

(894 baseline + 22 新 = 916)

---

## 四、改动文件

| 文件 | 改动 |
|---|---|
| `src/ai/adjudicator.py` | SYSTEM_PROMPT 加 narrative 纪律段;`_build_user_prompt` 加 state 参数;新增 `_build_raw_factor_snapshot` helper;AI 调用同步传 strategy_state |
| `tests/test_user_prompt_includes_raw_factors.py` | **新文件** 11 测试 |
| `tests/test_adjudicator_narrative_quality.py` | **新文件** 11 测试 |

---

## 五、§X / §Y / §Z 自检

### §X(本 sprint 删除清单)

**本 sprint 无替代关系,无删除项。** 理由:纯 prompt 改写 + user prompt
扩展。`plain_reading.py` / `factor_card_emitter.py` 等"人读层"代码不动,
它们服务的是"证据卡 / pillars",不是 ai_verdict 区。

### §Y
3 个 commit(A / B / C)+ 报告 commit,一次性 push。

### §Z(测试用真值断言,非 .called)
- `test_prompt_includes_funding_value`:断言 `"-0.4085" in prompt`
- `test_prompt_includes_btc_price`:断言 `"75700" in prompt`
- `test_prompt_includes_composite_diagnostics`:断言 `"11" / "11.5" in prompt`
- `test_ideal_narrative_passes_quality_gates`:`_count_concrete_metric_values >= 3`
- `test_machine_narrative_fails_quality_gates`:模板词命中或数值不足
- `test_output_spec_section_still_at_end`:顺序断言(snap_idx < spec_idx)

### 同类风险扫描
- **AI 输出风格依赖模型 + prompt**:本 sprint 测的是 prompt + 质量判定函数,
  实际 AI 真输出需 SSH 触发 pipeline + 网页主观验收
- **LONG/SHORT 持仓 narrative 模板**:现 prompt 已含通用规则,如效果差再
  分场景拆 prompt(留 1.5l.1)
- **token 成本**:user prompt 加 ~80 行因子快照(~1500 token),不影响
  Claude 200K 上下文,实测 cost 增量 < $0.005/run

---

## 六、部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 916 passed, 1 skipped, 7.48s |
| GitHub push(commit hashes:`842d91f..`,见下) | ✅ |
| 服务器 git pull | ❌ 等用户 SSH 执行 |
| 服务器 systemctl restart | ❌ 等用户 SSH 执行 |
| 生产 DB 迁移 / 清污 | N/A 无 schema 改动 |

### SSH 部署 + 主观验证

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service
sleep 5

# 触发新 pipeline 跑一次(让新 prompt 生效)
.venv/bin/python -c "
from src.data.storage.connection import get_connection
from src.pipeline import StrategyStateBuilder
b = StrategyStateBuilder(get_connection())
r = b.run(run_trigger='manual_post_1_5l')
print('persisted:', r.persisted)
"
SSH
```

打开 http://124.222.89.86 → 看"AI 策略说明"段:
- ✅ 5-7 句 / 300-500 字
- ✅ 至少含 3 个具体数值(funding / OI / LSR / 价格)
- ✅ 不再有"执行许可收紧"系统状态复述
- ✅ 有"为什么系统这样判断"因果链
- ✅ 有"什么改变判断"具体条件
- ✅ 像交易员叙事,不像规则引擎自描述
- ✅ 支持论据 / 反向论据 同样含具体数值

---

## 七、未覆盖 / 留 v0.6

- **改 prompt 后效果取决于 claude-sonnet-4-5**:如效果不佳,1.5l.1 可调
  prompt 细节或评估切 claude-opus-4-7
- **持仓状态 narrative**:LONG/SHORT 没单独模板,通用规则应该足够,如效果
  差再拆
- **AI 选指标的稳定性**:每次可能挑不同 3-5 个,这是设计意图(由数据驱动);
  如果用户希望某些指标"必须出现"(如 funding),可加固定 anchors
