# Sprint 1.5p — 删除 Yahoo source(2.6-A.3 STOPPED)+ FRED 阈值改 30h/72h

**Date:** 2026-04-30
**Branch:** main
**Status:** ✅ 本地完成,8 个新测试 + 989/989 全量回归过

---

## 一、诊断结果(用户 Task A)

SSH 验证生产 health-detail endpoint 显示:
- `Yahoo 宏观    status=no_data    age=null`
- `FRED 宏观     status=warn       age=306 分前(5h 前)`

**根因调查**(git log + 代码核实):

Yahoo collector 已在 **Sprint 2.6-A.3**(2026-04-27)**决议 STOPPED**:

| Commit | 说明 |
|---|---|
| `3887020` | Yahoo batch API 重写(per-symbol 持续 429 后的尝试) |
| `7d23d27` | batch path 测试 |
| `818c8f4` | 报告:**STOPPED — 服务器 IP 被 Yahoo 全面 429 封禁,batch + fallback 两路径都不通** |
| `aca8873` | FRED 扩展为 sole macro source(覆盖 DXY/VIX/SP500/Nasdaq) |
| `5c6a186` | 删除 Yahoo / Stooq / batch 死代码 |

**1.5n 错误假设**:health-detail endpoint 硬编码"Yahoo 宏观"+"FRED 宏观"
两个 source,基于假设 Yahoo collector 还在跑。但 collector 早已删除,
DB 永远不会有 source LIKE 'yfinance%' 行 → `no_data` 永久。

**FRED 5 小时前是正常 daily cadence**(每天 UTC 00:00 后更新),1.5n 阈值
2h warn / 24h critical 是按 yfinance 高频源设的,对 FRED daily 完全错配。

**正确修复**(用户 Task §X 工程纪律):删除 Yahoo panel entry,FRED 阈值
改 30h/72h(跟 Glassnode 链上 daily 同档)。**不修复 Yahoo collector** —
它在 2.6-A.3 已被 §X 决议性删除,网络物理问题不可修。

---

## 二、改动

### Task A 诊断:Yahoo decommissioned(已记入此报告 + commit 注释)

### Task B 删除 Yahoo source

`src/api/routes/system.py`:
- `_SOURCE_CADENCE` 删除 `yahoo_macro` entry
- `_query_data_source_freshness` 删除 yahoo_macro SQL 查询
  (`WHERE source LIKE 'yfinance%' OR source LIKE 'yahoo%'`)
- 加注释引用 Sprint 2.6-A.3 决议

`config/data_sources.yaml`:
- 删除 `yahoo_finance:` 配置块(28 行,无 collector 读取它)
- 加注释引用 Sprint 2.6-A.3 决议

### Task C FRED 阈值修正

`_SOURCE_CADENCE["fred_macro"]`:

| | 1.5n | 1.5p |
|---|---|---|
| warn | 2h(120 min) | **30h**(1800 min) |
| critical | 24h(1440 min) | **72h**(4320 min) |
| expected_cadence | "交易日每小时" | **"每日 (daily bar)"** |

跟 Glassnode 链上 daily cadence 同档,反映 FRED 真实更新频率。

### Test 更新

- `tests/test_health_detail_endpoint.py::test_endpoint_returns_5_data_sources`
  → `test_endpoint_returns_4_data_sources` + 断言 Yahoo 不在
- `tests/test_health_detail_thresholds.py`(新,8 测试):
  - 阈值表自检:warn=30h / critical=72h / yahoo_macro 不在表 / 4 sources
  - 反退化:warn 不能 ≤ 2h
  - 端到端 真值断言:FRED 28h → ok / 32h → warn / 75h → critical
  - **关键反退化**:`test_fred_5h_old_is_ok_not_warn` — 5h 前是正常 daily,
    1.5n 误判 warn,1.5p 应 ok

---

## 三、测试

```
989 passed, 1 skipped, 8.15s
```

(981 baseline + 8 新 - 0 删 = 989;原有 1 个测试 rename + 加 Yahoo 不在断言)

---

## 四、改动文件

| 文件 | 改动 |
|---|---|
| `src/api/routes/system.py` | `_SOURCE_CADENCE` 删 yahoo_macro,FRED 阈值 30h/72h;SQL queries 删 yahoo |
| `config/data_sources.yaml` | 删除 yahoo_finance 配置块 28 行 |
| `tests/test_health_detail_endpoint.py` | 5 sources → 4 sources + Yahoo 不在断言 |
| `tests/test_health_detail_thresholds.py` | **新文件** 8 测试(阈值自检 + 真值断言) |

---

## 五、§X / §Y / §Z 自检

### §X(本 sprint 删除清单)

| 删除对象 | 路径 / 行 | 原因 |
|---|---|---|
| `_SOURCE_CADENCE["yahoo_macro"]` entry(4 行) | `src/api/routes/system.py:130-133` | Sprint 2.6-A.3 STOPPED |
| `yahoo_macro` SQL 查询(`WHERE source LIKE 'yfinance%' OR source LIKE 'yahoo%'`) | `src/api/routes/system.py:181-183` | 同上 |
| `yahoo_finance:` 配置块(28 行) | `config/data_sources.yaml:138-163` | 无 collector 读取 |
| 老测试 `test_endpoint_returns_5_data_sources`(改名 4 + 加 Yahoo 不在断言) | `tests/test_health_detail_endpoint.py` | 与新事实对齐 |

git grep 自检:
- ✅ `git grep "yahoo_macro" -- src/` 0 引用
- ✅ `git grep "yahoo_finance:" -- config/` 0 引用
- ✅ FRED 阈值在 `_SOURCE_CADENCE` 单一来源,无重复定义

### §Y
1 个 commit + 1 个报告 commit,一次性 push。

### §Z(测试用真值断言)
- FRED age 真值断言:28h ok / 32h warn / 75h critical / 5h ok(关键反退化)
- 阈值断言:`cfg["warn"] == 30 * 60` / `cfg["critical"] == 72 * 60`
- 反退化锁:`cfg["warn"] > 2 * 60`(不能回到 2h)
- 不是 `.called=True` only

### 同类风险扫描
- **`MacroSource = Literal["fred", "yahoo_finance"]`** in `src/data/storage/dao.py`:
  保留以容纳历史 DB 中可能的 source='yahoo_finance' 旧行(Sprint 2.4 backfill 残留)。
  本 sprint 不动 — schema 兼容性。
- **`config/data_catalog.yaml`** 6 处 `platform: yahoo_finance`:metric 语义记录,
  指明历史数据来源。FRED 现在产同名 metric_name(dxy/vix/etc)。本 sprint 不动 —
  改 catalog 是另一个语义重写,留 1.5p.1
- **阈值仍硬编码** `_SOURCE_CADENCE`:挪 thresholds.yaml 留 1.5p.1
- **网络物理问题(Tencent Cloud → Yahoo 429)不可修**:除非用户切 IP / proxy

---

## 六、部署状态四件事清单

| 步骤 | 状态 |
|---|---|
| 本地 pytest 通过 | ✅ 989 passed, 1 skipped, 8.15s |
| GitHub push(commit hash:`687bb6f` + 报告) | ✅ |
| 服务器 git pull | ❌ 等用户 SSH 执行 |
| 服务器 systemctl restart | ❌ 等用户 SSH 执行 |
| 生产 DB 迁移 / 清污 | N/A 不动 schema、不动数据 |

### SSH 部署 + 主观验证

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service
sleep 5

# 验证 health-detail 只剩 4 个 source,FRED 5h 前应 ok
curl -s -u admin:Y_RhcxeApFa0H- http://localhost/api/system/health-detail \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'overall_status: {d[\"overall_status\"]}')
for s in d['data_sources']:
    age = s.get('age_minutes')
    age_str = f'{age:.0f} 分前' if age is not None else 'null'
    print(f'  {s[\"name\"]:<25} status={s[\"status\"]:<10} age={age_str}')
"
SSH
```

预期输出:
```
overall_status: all_healthy
  Binance K 线 (1h)        status=ok    age=XX 分前
  CoinGlass 衍生品          status=ok    age=XX 分前
  Glassnode 链上            status=ok    age=XX 分前
  FRED 宏观                 status=ok    age=300+ 分前  ← 不再是 warn
```

打开 http://124.222.89.86 主观验收:
- ✅ 自检面板「数据源」列只有 4 行(Binance / CoinGlass / Glassnode / FRED)
- ✅ FRED 行是 ● 绿色("X 小时前"是正常 daily cadence)
- ✅ 不再出现 Yahoo 宏观行(已 STOPPED)

---

## 七、未覆盖 / 留 v0.6

- **`config/data_catalog.yaml` 6 处 `platform: yahoo_finance`** 语义记录:
  应改为 `platform: fred`(指明 FRED 接管),留 1.5p.1
- **阈值挪 thresholds.yaml**:1.5n.1 已留,1.5p 继续不挪,留同档 1.5p.1
- **MacroSource Literal 兼容**:保留以容纳历史 DB 旧行,如未来清理可改单 fred
- **网络物理问题**:Tencent Cloud → Yahoo 永久 429。如未来要恢复 Yahoo,
  需用户决策切 IP / proxy / 不同云
