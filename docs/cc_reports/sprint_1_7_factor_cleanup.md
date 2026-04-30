# Sprint 1.7(缩减版)— 安全子集真删 3 噪音因子 + 1.8 前置 TODO

**Date:** 2026-04-30
**Branch:** main
**Status:** ✅ 本地完成,13 反退化 + 63 focused 回归过 + 4 commit

> 注:`docs/cc_reports/sprint_1_7.md` 是 2026-04-23 老 sprint(L1 Regime
> Evidence)。本文件是建模 v1.3 后重启的 1.7(因子地基删除)独立报告。

---

## 一、范围调整(实施前 grep 发现冲突)

### 原 spec 范围

删 8 个噪音因子 + 降级 3 个因子 = 11 个动作。

### grep 发现 7/11 因子被 L 层引用

CC 在动手前 `git grep` 11 个因子,发现:

| 因子 | 引用层(超出 spec 预期范围) |
|---|---|
| `basis_annualized` | `src/composite/crowding.py` |
| `dff` | `src/evidence/layer5_macro.py` |
| `cpi` | L5 + `state_builder.py` + `composite_composition.py` |
| `unemployment` | `src/evidence/layer5_macro.py` |
| `sp500` | L5 + `config/layers.yaml` |
| `gold_price` | L5(`macro_btc_gold` 相关性) |
| `put_call_ratio` | `src/composite/crowding.py` + `composite_composition.py` |

Spec 预期"只在 collector / catalog / emit / 测试 4 个地方有引用"被打破。
强删会破坏 pipeline,产生 KeyError 或起手就崩。

### 用户决策(选项 A,缩减范围)

只真删 3 个无 L 层引用的因子,其他 7 个 + 3 个降级留 1.8 在重写 L5/Crowding 时
一并处理。

---

## 二、改动(4 个 commit)

| # | Commit | 因子 | 删除范围 |
|---|---|---|---|
| 1 | `5fcf9e4` | reserve_risk | collector + catalog + emit + scheduler + test |
| 2 | `9ec2902` | puell_multiple | 同上 |
| 3 | `63f3214` | sopr(注意区分 aSOPR=sopr_adjusted)| 同上 |
| 4 | (本) | 反退化测试 + 报告 | tests/test_sprint_1_7_factor_deletions.py |

aSOPR (sopr_adjusted) 完整保留(1.6 已升级 primary)。

---

## 三、§X 真删清单

| 删除对象 | 路径 |
|---|---|
| `fetch_reserve_risk` 方法 | src/data/collectors/glassnode.py |
| `fetch_puell_multiple` 方法 | 同上 |
| `fetch_sopr` 方法(注意保留 fetch_sopr_adjusted)| 同上 |
| `_PATH_RESERVE_RISK / _PATH_PUELL / _PATH_SOPR` 路径常量 | 同上 |
| `collect_and_save_all` 中 3 项 task 注册 | 同上 |
| `_GLASSNODE_FETCHERS` 中 fetch_sopr / fetch_reserve_risk / fetch_puell_multiple | src/scheduler/jobs.py |
| `_ONCHAIN_EXPECTED_METRICS_TODAY` 中 sopr / reserve_risk / puell_multiple | 同上 |
| Reserve Risk 28 行 emit 段 | src/strategy/factor_card_emitter.py |
| _ref_specs tuple 中 sopr 行 + puell_multiple 行 | 同上 |
| 3 个 source 条目 + 3 个 factor 条目 | config/data_catalog.yaml |
| `tests/test_glassnode_collect_all.py` expected metric 集合 |  |
| `tests/test_preflight_alert_writer.py` fixture(sopr → sopr_adjusted) |  |

§X grep guard 通过:
- `git grep -wn "sopr" src/` 排除 `sopr_adjusted/sopr_lth/sopr_sth/aSOPR/
  fetch_sopr_adjusted/Sprint 1.7` 注释 → **0 行 active code**
- `git grep "reserve_risk" src/` → 仅 4 行删除标记注释
- `git grep "puell" src/` → 仅 5 行删除标记注释

---

## 四、测试(13 反退化 + 63 focused 回归)

### `tests/test_sprint_1_7_factor_deletions.py`(13 反退化)

| 类 | 测试 |
|---|---|
| Collector 方法已删 | 3 个 + aSOPR 保留断言 |
| 路径常量已删 | 3 个 + aSOPR 保留 |
| jobs.py 注册 | _GLASSNODE_FETCHERS / _ONCHAIN_EXPECTED_METRICS_TODAY |
| factor_card_emitter | 不再 emit 3 种 card_id;aSOPR 卡仍在 |
| catalog | sources / single_factors 不含;asopr.role_in_v1='primary' 仍在 |
| **e2e** | `test_emit_factor_cards_does_not_emit_deleted_factors` — 即使 context 提供这 3 个 series,emit 也不再产卡;aSOPR 卡仍产 |

### Focused 回归(63 个)

```
tests/test_sprint_1_6_new_factors.py        30 ✅
tests/test_sprint_1_7_factor_deletions.py   13 ✅
tests/test_glassnode_collect_all.py          5 ✅
tests/test_preflight_alert_writer.py         4 ✅
tests/test_factor_card_emitter.py           11 ✅
```

---

## 五、§X / §Y / §Z 自检

### §X(本 sprint 真删,不软删)
✅ 3 个 collector 方法 / 3 个路径常量 / 6 个 catalog 条目 / 2 个 jobs 注册
项 / 3 处 emit 配置 — 全部 rm(替换为 1.7 删除标记注释)。
fixtures `tests/fixtures/scenario_*/raw_data.json` 中的历史值保留(per spec
"历史 DB 数据保留")。

### §Y
3 个删除 commit + 1 个测试/报告 commit,push 一次性。

### §Z(测试用真值断言)
- `test_emit_factor_cards_does_not_emit_deleted_factors`:跑真 emit_factor_cards,
  即使 context 提供 series 也不再产卡 — 不是 mock-only
- `test_no_fetch_reserve_risk_method`:`assert not hasattr(GlassnodeCollector, ...)`
  — 真 reflect
- catalog yaml 真 yaml.safe_load + 真断言 source_names / factor_names 集合

---

## 六、部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest | ✅ 13 反退化 + 63 focused 回归 |
| GitHub push(commit hashes:`5fcf9e4..` 4 个) | ✅(本 commit 后) |
| 服务器 git pull | ❌ 等用户 SSH 执行 |
| 服务器 systemctl restart | ❌ 等用户 SSH 执行 |
| 生产 DB 迁移 / 清污 | N/A 软停写(spec 明确历史数据保留) |

### SSH 验证脚本

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service && sleep 5

# 1. grep 自检
echo "=== sopr (active, exclude variants/comments) in src/ ==="
git grep -wn "sopr" src/ | grep -vE "sopr_adjusted|sopr_lth|sopr_sth|asopr|aSOPR|fetch_sopr_adjusted|Sprint 1\.7" | wc -l
# 预期:0
git grep "reserve_risk" src/ | grep -v "Sprint 1.7" | wc -l
git grep "puell" src/ | grep -v "Sprint 1.7" | wc -l

# 2. 触发 onchain collector,看 fetcher 集合
.venv/bin/python -c "
from src.scheduler.jobs import job_collect_onchain
result = job_collect_onchain()
print('onchain:', result.get('by_collector'))
"

# 3. 触发 pipeline 看 not crash
.venv/bin/python -c "
from src.data.storage.connection import get_connection
from src.pipeline import StrategyStateBuilder
b = StrategyStateBuilder(get_connection())
r = b.run(run_trigger='manual_post_1_7')
print('persisted:', r.persisted, 'degraded:', r.degraded_stages)
"

# 4. 验证 factor_cards 不含已删因子
.venv/bin/python -c "
from src.data.storage.connection import get_connection
from src.pipeline import StrategyStateBuilder
b = StrategyStateBuilder(get_connection())
r = b.run(run_trigger='manual_verify_1_7')
cards = r.state.get('factor_cards') or []
banned = ['Reserve Risk', 'Puell', 'onchain_sopr_']
for c in cards:
    cid = c.get('card_id', '')
    name = c.get('name', '')
    if 'asopr' in cid or 'sopr_adjusted' in cid:
        continue  # aSOPR 1.6 升级保留
    for ban in banned:
        assert ban not in cid and ban not in name, f'still has: {cid} / {name}'
print('OK: factor_cards clean')
"
SSH
```

---

## 七、Sprint 1.8 前置 TODO(本 sprint 未删,留 1.8)

本 sprint 因 L5 / Crowding 引用未先处理,以下因子未删,留 1.8 在重写
L5/Crowding 时一并处理:

| 因子 | 引用层 | 文件 |
|---|---|---|
| basis_annualized | 组合 Crowding | `src/composite/crowding.py` |
| put_call_ratio | 组合 Crowding + narrative | `src/composite/crowding.py` + `src/strategy/composite_composition.py` |
| dff | L5 宏观 | `src/evidence/layer5_macro.py` |
| cpi | L5 + state pipeline | `src/evidence/layer5_macro.py` + `src/pipeline/state_builder.py` + `src/strategy/composite_composition.py` |
| unemployment | L5 | `src/evidence/layer5_macro.py` |
| sp500 | L5 | `src/evidence/layer5_macro.py` + `config/layers.yaml` |
| gold_price | L5(`macro_btc_gold` 相关性) | `src/evidence/layer5_macro.py` |

降级到 display 的 3 个因子:
- `mvrv_ratio` — 1.7 grep 发现 src/ 0 active 引用(可能已不存在,无 catalog
  条目)。1.8 启动时再确认
- `sopr` — 1.7 已真删,无需降级
- `put_call_ratio` — 留 1.8 处理(降级涉及 catalog 标签 + factor_card tier
  双修改;Crowding 重写时一并)

**1.8 spec 应包含**:"重写 L5 + Crowding 时,把这些因子的引用一起删干净"。

---

## 八、风险扫描

- **历史 DB 数据保留**:spec 明确"软停写"。3 个因子的旧行
  (`source='glassnode_display'`)不删 — 生产 DB 多保留几百行历史数据,无负担
- **fixtures `scenario_*/raw_data.json`**:历史回测场景固化数据,保留
  reserve_risk / puell_multiple / sopr 字段值(M26 三场景验收用)。若未来
  evidence 层重写时这些 fixture 跑不通,1.8 一并改写
- **scheduler.yaml comment**:line 10 注释 "collect_onchain ... + sopr_adjusted ..."
  — 注释里 sopr_adjusted 是正确表达(aSOPR),不需改
- **BTC 现价 / 顶栏面板影响**:本 sprint 仅删 3 个 onchain reference 卡,
  不影响价格或决策路径
