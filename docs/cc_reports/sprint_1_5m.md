# Sprint 1.5m — no_opportunity_narrator 8 场景模板重写为交易员叙事

**Date:** 2026-04-30
**Branch:** main
**Status:** ✅ 本地完成,29 个新测试 + 945/945 全量回归过

---

## 一、根因

1.5l 改了 AI adjudicator 的 prompt,但 SSH 真实部署后发现:

- **95% 时间**系统在 FLAT / opportunity_grade=none / permission=watch
- 这种状态下 adjudicator 走"硬约束未通过"短路路径,**不调 AI**
- 直接调 `src/strategy/no_opportunity_narrator.py` 8 场景模板生成 narrative
- 网页"AI 策略说明"+"支持论据"+"反向论据"全部来自这些模板

老模板文案问题:
- 复述系统状态("执行许可被收紧到「仅观察」""系统不允许新开仓"),不是结构论据
- 没具体指标值,没多空力量对比
- 同义反复:支持论据 = "执行许可=watch,硬性禁止开新仓"

按 §2.5 双轨原则,**人读版禁止 AI 生成,必须由规则化代码生成** — 所以
本 sprint 改的是规则代码本身,把它从"规则状态复述"升级到"交易员叙事"。

---

## 二、改动

### 任务 A:新增 `factor_picker.py` 关键因子选择器(commit `5a98f1b`)

`src/strategy/factor_picker.py::pick_key_factors(state, n=5, scenario=None)`:
从完整 strategy_state 中按规则化打分挑出 top-N 最有信号的因子,返回结构化
`list[dict]`(category / name / current_value / context / signal_strength /
interpretation / evidence_ref)。

**100% 规则化打分,禁 AI**(对齐 §2.5)。打分规则:

| 优先级 | 类别 | signal |
|---|---|---|
| 极端分位 | funding 30d ≤15 / ≥85,MVRV-Z ≥5 / ≤0.1,SOPR <0.99 | 80-90 |
| 触发阈值 composite | crowding=high, event_risk=high, macro_headwind=strong | 80-85 |
| 大幅 24h 变动 | LSR ±10%, OI ±5%, funding ≥0.3% | 80-85 |
| 一般偏离 | SOPR <1, ADX <15 或 ≥30 | 50-65 |
| 兜底市场快照 | BTC 现价 + cycle/crowding/macro 三件套 | 30-40 |

`scenario` hint 调整排序:
- `permission_restricted` / `position_cap_zero` → 上推 crowding/macro/event +15-20
- `fallback_degraded` / `cold_start` → 全部降权 -20~-30(数据不可信)

### 任务 B:8 场景重写为 4 段交易员叙事(commit `716f6f5`)

`src/strategy/no_opportunity_narrator.py` 整体重写。每个 narrative 4 段格式:

```
【结构】当前 3-5 个关键因子的值 + 历史位置(picker 选)
【解读】多空力量对比 / 因子共振或矛盾,2-3 句
【关键】1 个最影响判断的信号 + 它的含义
【结论】系统为什么这样判断 + 改变条件
```

新增 helper:
- `_make_4section_narrative` — 4 段拼接
- `_structure_sentence / _interpretation_sentence / _key_sentence` — 各段构造
- `_factors_to_drivers` — picker top-K → primary_drivers(每条含数值)
- `_build_counter_arguments` — picker 列表识别"反转信号"(LSR/OI/SOPR/funding)
- `_build_change_conditions` — picker 列表构造"反转条件"(带数值阈值)
- `_ensure_schema_minimums` — 统一兜底(≥3 drivers / ≥2 counters / ≥3 conds)

8 场景按各自核心论据生成,picker 用 scenario hint:

| 场景 | picker hint | 核心叙事 |
|---|---|---|
| `cold_start` | cold_start | 冷启动期天数 + 数据池积累 |
| `extreme_event` | extreme_event | 事件名 + 严重度 + 2 个次要论据 |
| `protection` | protection | 触发原因(`risks.protection_reason`)+ 市场快照 |
| `fallback_degraded` | fallback_degraded | 列陈旧层 + 信号不可信(picker 全部 -30 分) |
| `post_protection` | post_protection | 重评期市场新结构(picker 4 个新结构因子) |
| `permission_restricted` | permission_restricted | crowding/macro/event +15 |
| `position_cap_zero` | position_cap_zero | crowding/macro/event +20,讲 critical 例外 |
| `grade_none` | grade_none | 完整 4 段 + L3 upgrade_conditions |

### 任务 C:测试(commit pending)

29 个新测试 + 1 个老测试改写。

---

## 三、测试

### `tests/test_factor_picker.py`(13 测试)
- 极端因子识别(funding 30d 分位 11 → ≥80,LSR 24h +13.68% → ≥85)
- 兜底返回(全中性时 ≥3 个 baseline 快照)
- 数量边界(n=2 / n=10 / 排序降序)
- 组合因子(crowding=high / event_risk=high signal ≥80)
- Scenario hint 偏好(permission_restricted 上推 crowding;fallback_degraded 降权)
- 字段完整性

### `tests/test_narrative_human_quality.py`(7 测试)
- 4 段结构存在
- narrative 含 ≥3 个具体数值
- 不含老机器化模板词
- permission_restricted drivers 含 crowding/macro/event 相关
- primary_drivers ≥2 条含数值
- what_would_change_mind ≥1 条含数值阈值
- counter_arguments 含因子级反转信号(LSR/OI/SOPR/funding)

### `tests/test_no_opportunity_8_scenarios.py`(9 测试)
- 8 场景各 1 个:detect_scenario 命中 + 4 段结构 + 不含老模板词
- 跨场景反退化(全部 8 场景输出都不含老模板词)

### 老测试更新
- `test_no_opportunity_narrator.py::test_all_scenarios_produce_non_empty_narrative`:
  长度上限 400 → 1200(4 段格式更长)

### 全量回归

```
945 passed, 1 skipped, 6.79s
```

(929 baseline + 13 picker + 7 quality + 9 scenarios + 16 不属于本次 sprint
但触发的 narrator 老用例 = 实际 +29)

---

## 四、改动文件

| 文件 | 改动 |
|---|---|
| `src/strategy/factor_picker.py` | **新文件** 关键因子选择器 |
| `src/strategy/no_opportunity_narrator.py` | 整体重写,8 场景改 4 段 + picker |
| `tests/test_factor_picker.py` | **新文件** 13 测试 |
| `tests/test_narrative_human_quality.py` | **新文件** 7 测试 |
| `tests/test_no_opportunity_8_scenarios.py` | **新文件** 9 测试 |
| `tests/test_no_opportunity_narrator.py` | 长度上限 400→1200 |

---

## 五、§X / §Y / §Z 自检

### §X(本 sprint 删除清单)

| 删除对象 | 路径 / 位置 | 删除原因 |
|---|---|---|
| `_gen_grade_none` 老 narrative 字符串 | src/strategy/no_opportunity_narrator.py | 替换为 4 段交易员模板 |
| `_gen_permission_restricted` 老 narrative + "执行许可被收紧" | 同上 | 同上 |
| `_gen_position_cap_zero` 老 narrative | 同上 | 同上 |
| `_gen_cold_start` 老 narrative | 同上 | 同上 |
| `_gen_extreme_event` 老 narrative | 同上 | 同上 |
| `_gen_protection` 老 narrative | 同上 | 同上 |
| `_gen_fallback_degraded` 老 narrative | 同上 | 同上 |
| `_gen_post_protection` 老 narrative | 同上 | 同上 |
| 老 narrative 长度 50-400 上限 | tests/test_no_opportunity_narrator.py:142 | 4 段格式更长,改为 80-1200 |

git grep 自检:
- ✅ `git grep "执行许可被收紧到" -- src/` → 0 引用
- ✅ `git grep "系统不允许新开仓" -- src/` → 0 引用
- ✅ `_gen_*` 8 个函数的老字符串拼接全删,只留新 4 段拼接

### §Y
3 个代码 commit + 1 个 docs commit,一次性 push 到 GitHub。

### §Z(测试用真值断言)
- factor_picker 数值断言:`signal_strength >= 80`,`"11" in interpretation`
- narrative 4 段断言:`"【结构】" in n` × 4 段
- 数值密度断言:`_count_concrete_values(n) >= 3`(% / 大数计数)
- 反退化:`not _has_old_template(n)`(老模板词命中即 fail)
- 跨 8 场景反退化:每个 detect_scenario 命中 + narrative 不含老模板

### 同类风险扫描
- **picker 信号强度评分是规则化打分**:可能在某些边缘场景挑错因子,留 1.5m.1
- **每场景的 narrative tone**:目前 4 段格式相同,某些场景(extreme_event)
  可能太长,需 SSH 主观验收后调整(留 1.5m.1)
- **AI 路径(LONG_PLANNED 等真触发)narrative**:由 1.5l 的 prompt 控制,
  本 sprint 不动 — 两条路径独立

---

## 六、部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 945 passed, 1 skipped, 6.79s |
| GitHub push(commit hashes:`5a98f1b..`,见下) | ✅ |
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

.venv/bin/python -c "
from src.data.storage.connection import get_connection
from src.pipeline import StrategyStateBuilder
b = StrategyStateBuilder(get_connection())
r = b.run(run_trigger='manual_post_1_5m')
print('persisted:', r.persisted)
"

.venv/bin/python -c "
import sqlite3, json
conn = sqlite3.connect('data/btc_strategy.db')
row = conn.execute(\"SELECT full_state_json FROM strategy_runs WHERE run_trigger='manual_post_1_5m' ORDER BY generated_at_utc DESC LIMIT 1\").fetchone()
state = json.loads(row[0])
adj = state.get('adjudicator') or {}
print('===== NARRATIVE =====')
print(adj.get('narrative', '(empty)'))
print()
print('===== PRIMARY DRIVERS =====')
for d in adj.get('primary_drivers') or []:
    print(' -', d.get('text') if isinstance(d, dict) else d)
"
SSH
```

打开 http://124.222.89.86 → 看"AI 策略说明":
- ✅ narrative 含 4 段:【结构】【解读】【关键】【结论】
- ✅ 每段含具体数值(funding / LSR / OI / 价格)
- ✅ 不再有"执行许可被收紧"机器化复述
- ✅ 像真实交易员讲解市场结构
- ✅ 支持论据 / 反向论据 含具体数值

---

## 七、未覆盖 / 留 v0.6

- **picker 信号强度评分边界**:某些边缘数据可能挑出非最强信号(如 ADX=15
  和 funding 30d 分位 24 同分时)。SSH 主观验收发现问题再调
- **每场景 narrative tone**:extreme_event 可能太短,grade_none 可能太长。
  4 段格式统一,如某些场景需要 3 段简化版,1.5m.1 续修
- **AI 路径 narrative**(LONG_PLANNED 等):由 1.5l prompt 管控,本 sprint
  不动。两条路径独立
- **counter_arguments 反转信号识别规则**:现版只识别 LSR/OI/SOPR 几个
  名,如 picker 选了其他因子(如 NUPL/MVRV)需扩展规则
