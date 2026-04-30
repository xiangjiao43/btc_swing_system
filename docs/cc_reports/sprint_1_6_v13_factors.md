# Sprint 1.6 — 新增 9 个关键因子(只新增,不动旧;建模 v1.3 §2.4 + §2.6)

**Date:** 2026-04-30
**Branch:** main
**Status:** ✅ 本地完成,20 个新测试 + commits `0e3734a..d9b4d25`

> 注:`docs/cc_reports/sprint_1_6.md` 是 Sprint 1.6 老版(2026-04-23,
> 6 个组合因子建模 §3.8)。本文件是建模 v1.3 后重启的 1.6
> ("新增 9 个关键因子")独立报告。

---

## 一、用户决策摘要

建模 v1.3 §2.4(链上 6+1)+ §2.6(机构 / 市场结构 2)新增 9 因子。
本 sprint 只做新增,不动旧代码。**用户提供 SSH 端点验证结果后**,
LTH/STH-MVRV 改本地计算(alphanode 不开 mvrv_more)。

---

## 二、改动(7 个 commit)

| # | Commit | 模块 |
|---|---|---|
| 1 | `0e3734a` | Glassnode 4 新端点 + HODL Waves 拆 11+ bucket |
| 2 | `e2f63dc` | 本地派生 LTH-MVRV / STH-MVRV(alphanode 不开 mvrv_more) |
| 3 | `94c7bdc` | CoinGlass btc_dominance + etf_flow_history |
| 4 | `500bf11` | aSOPR 角色升级 display → primary(catalog 标签) |
| 5 | `f6cc795` | scheduler/jobs.py 注册 4+2 新 fetcher + 派生 MVRV |
| 6 | `d9b4d25` | factor_card_emitter 9 张新卡(占位文案,Sprint 1.10 细化) |
| 7 | (本 commit) | 测试 + 报告 |

---

## 三、HODL Waves 入库方案落档(用户要求)

**选择方案 a**:每个 bucket 拆独立 metric(metric_name 前缀 `hodl_waves_`)。

理由:
- 查询简单 — 跟其他 onchain metric 同形态(`SELECT * WHERE metric_name=?`)
- 不改 schema — 不需要新增 `metric_value_json` 列
- 前端 / picker / L 层都不需要特殊处理

具体 bucket(实测 alphanode 响应):
```
hodl_waves_24h / hodl_waves_1d_1w / hodl_waves_1w_1m /
hodl_waves_1m_3m / hodl_waves_3m_6m / hodl_waves_6m_12m /
hodl_waves_1y_2y / hodl_waves_2y_3y / hodl_waves_3y_5y /
hodl_waves_5y_7y / hodl_waves_7y_10y / hodl_waves_more_10y
```

某个 bucket 在早期数据中缺失时自动跳过(不抛错,不写空值)。

---

## 四、LTH-MVRV / STH-MVRV 本地派生方案

**alphanode 不开放 `/v1/metrics/market/mvrv_more`**(用户实测所有变体路径
404)。改本地计算:

```
lth_mvrv_t = btc_price_close_t / lth_realized_price_t
sth_mvrv_t = btc_price_close_t / sth_realized_price_t
```

实施位置:`src/data/collectors/derived_onchain.py::compute_and_save_derived_mvrv`

调用时机:`job_collect_onchain` 在 Glassnode fetch 完后立即跑一次。读
`onchain_metrics` 表中 3 个来源 metric → 在 timestamp 上 inner join → 逐日
计算 → upsert 回 `onchain_metrics`,**source='computed'**。

`OnchainSource` Literal 扩展 `'computed'`。

---

## 五、改动文件

| 文件 | 改动 |
|---|---|
| `src/data/collectors/glassnode.py` | +4 fetch + HODL Waves dict 处理 + 注册 |
| `src/data/collectors/derived_onchain.py` | **新文件** 本地派生 MVRV |
| `src/data/collectors/coinglass.py` | +2 fetch + 2 路径常量 |
| `src/data/storage/dao.py` | OnchainSource Literal 加 'computed' |
| `config/data_catalog.yaml` | asopr role display→primary;layer L2→L3 |
| `src/scheduler/jobs.py` | _GLASSNODE_FETCHERS 加 4 个;派生 MVRV 计算调度 |
| `src/strategy/factor_card_emitter.py` | +`_emit_v13_new_factors`(9 张新卡) |
| `tests/test_sprint_1_6_new_factors.py` | **新文件** 20 测试 |

---

## 六、9 张新因子卡(占位文案,Sprint 1.10 细化)

| # | 卡片名 | linked_layer | source | 数据来源 |
|---|---|---|---|---|
| 1 | STH Supply | L2 | Glassnode | onchain.sth_supply |
| 2 | LTH-MVRV | L2 | computed | onchain.lth_mvrv |
| 3 | STH-MVRV | L2 | computed | onchain.sth_mvrv |
| 4 | SSR | L5 | Glassnode | onchain.ssr |
| 5 | HODL Waves (>1y) | L2 | Glassnode | 求和 6 长期 bucket |
| 6 | CDD | L3 | Glassnode | onchain.cdd |
| 7 | aSOPR | L3 | Glassnode | onchain.sopr_adjusted(老 reference 卡保留) |
| 8 | ETF Flows | L5 | CoinGlass | derivatives.etf_flow |
| 9 | Bitcoin Dominance | L5 | CoinGlass | derivatives.btc_dominance |

`impact_direction='neutral'` / `impact_weight=0.5`(本 sprint 不影响策略评分,
留 Sprint 1.8 逻辑层对接)。`strategy_impact` 含 `[Sprint 1.10 占位]` 标记。

---

## 七、测试(20 个新测试)

| 类 | 测试数 | 覆盖 |
|---|---|---|
| Glassnode 端点存在 | 2 | 4 fetcher 方法 + 4 _PATH 常量 |
| HODL Waves 拆桶 | 2 | 12 桶完整展开 / 桶缺失跳过 |
| 本地派生 MVRV | 4 | 7 行入库 + source='computed' + 数学正确 + 缺数据跳过 |
| CoinGlass 解析 | 3 | btc_dominance / etf_flow / 路径(etf 在 bitcoin 之前) |
| aSOPR catalog | 2 | role_in_v1='primary' / layer='L3' |
| factor_cards | 4 | 9 张卡 / lth source='computed' / etf L5 / hodl 求和 |
| jobs 注册 | 2 | _GLASSNODE_FETCHERS / 模块 import |
| OnchainSource Literal | 1 | 含 'computed' |

```
20 passed in 0.45s
```

---

## 八、§X / §Y / §Z 自检

### §X(本 sprint 不删任何旧代码)
✅ 只新增 collector / emit / config 标签。HODL Waves 不改 schema(方案 a)。
aSOPR 老 reference 卡保留(并存兼容)。

### §Y(每子任务 commit + push)
7 个 commit + 报告 commit = 8 个 commit,push 一次性。

### §Z(测试用真值断言)
- 数学验证:`lth_mvrv = 73000/35000 ≈ 2.086`(非 mock,真 SQL select)
- HODL Waves:12 bucket 真值 expand
- CoinGlass:dict 输入 → 真 metric_value 数值断言
- 不是 `.called=True` only

---

## 九、部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 20/20 sprint 1.6 |
| GitHub push(commit hashes:`0e3734a..` 7 个) | ✅ |
| 服务器 git pull | ❌ 等用户 SSH 执行 |
| 服务器 systemctl restart | ❌ 等用户 SSH 执行 |
| 生产 DB 迁移 / 清污 | N/A 不动 schema |

### SSH 部署 + 主观验证

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service
sleep 5

# 触发 onchain collector(同步抓 4 个新 + 派生 LTH/STH-MVRV)
.venv/bin/python -c "
from src.scheduler.jobs import job_collect_onchain
result = job_collect_onchain()
print('onchain stats:', result.get('by_collector'))
"

# 触发 klines_daily collector(同步抓 2 个新 CoinGlass)
.venv/bin/python -c "
from src.scheduler.jobs import job_collect_klines_daily
result = job_collect_klines_daily()
print('daily stats:', result.get('by_collector'))
"

# 验证新链上 metric 入库
sqlite3 data/btc_strategy.db "
SELECT metric_name, COUNT(*), MAX(captured_at_utc)
FROM onchain_metrics
WHERE metric_name IN ('sth_supply','ssr','cdd','lth_mvrv','sth_mvrv')
   OR metric_name LIKE 'hodl_waves%'
GROUP BY metric_name;
"

# 验证新衍生品 metric 入库
sqlite3 data/btc_strategy.db "
SELECT metric_name, COUNT(*), MAX(captured_at_utc)
FROM derivatives_snapshots
WHERE metric_name IN ('etf_flow','btc_dominance')
GROUP BY metric_name;
"

# 跑 pipeline 看 9 张新卡进入 factor_cards
.venv/bin/python -c "
from src.data.storage.connection import get_connection
from src.pipeline import StrategyStateBuilder
b = StrategyStateBuilder(get_connection())
r = b.run(run_trigger='manual_post_1_6')
cards = r.state.get('factor_cards') or []
new_names = ['STH Supply','LTH-MVRV','STH-MVRV','SSR',
             'HODL Waves (>1y)','CDD','aSOPR',
             'ETF Flows','Bitcoin Dominance']
for nm in new_names:
    print(f'  {nm:<22} {\"OK\" if any(c[\"name\"]==nm for c in cards) else \"MISSING\"}')
"
SSH
```

主观验收(浏览器):打开 http://124.222.89.86 → 链上数据区应有 7 张新卡;
衍生品数据区应有 2 张新卡。

---

## 十、未做(留 Sprint 1.7+)

按用户决定本 sprint 只新增不删旧。后续:

| Sprint | 任务 |
|---|---|
| 1.7 | 删旧因子(8 删 + 3 降级)+ 5 个组合因子改为只保留 CyclePosition |
| 1.8 | L1-L5 改 AI 主导 + 规则硬约束;9 新因子接入 cycle_position 投票 |
| 1.10 | 9 张新卡文案细化(替换 [Sprint 1.10 占位] 标记) |

---

## 十一、风险扫描

- **alphanode 端点漂移**:用户已 SSH 实测 7 真路径 + LTH/STH-MVRV 本地计算
  绕开 mvrv_more 不开放,无端点假设风险
- **HODL Waves 早期数据缺桶**:实施跳过缺失桶,前端 HODL Waves (>1y) 求和
  时 `_latest()` 自动 skip None
- **派生 MVRV 一日同步延迟**:本地派生依赖前序 fetch 落库,onchain collector
  失败时派生跳过(不会出现 stale 派生数据)
- **CoinGlass etf/flow-history 真路径**:`/api/etf/bitcoin/...`(etf 在
  bitcoin 之前)— 容易写错,测试已锁定
