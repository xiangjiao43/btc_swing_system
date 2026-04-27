# Sprint 2.6-A.4 — FRED 全覆盖 macro,L5 完整度 25% → 90%

**Date:** 2026-04-27
**Branch:** main · 当前 HEAD = `6620c0c`
**Status:** ✅ 完整完成,所有验收通过

---

## 一、commits 全清单(本 sprint 范围)

| commit | 摘要 |
|---|---|
| `aca8873` | feat(fred): expand to cover dxy/vix/sp500/nasdaq, replacing Yahoo |
| `5c6a186` | chore: remove Yahoo/Stooq/batch dead code (FRED is sole macro source now) |
| `88da7e8` | security: harden .gitignore + add pre-commit gitleaks |
| `6620c0c` | docs(security): incident report for 2026-04-27 .env.save leak |

> 安全相关的 `88da7e8` + `6620c0c` 在 sprint 中插入,详情见
> `docs/cc_reports/security_incident_2026_04_27.md`。本 sprint 只关注 FRED 收尾。

---

## 二、Yahoo → FRED 切换前后对比

### 数据覆盖

| 字段 | Sprint 2.6-A.3 之前 | Sprint 2.6-A.4 之后 | FRED series_id |
|---|---|---|---|
| dxy | Yahoo 429 / 0 行 | ✅ 117 行 | `DTWEXBGS` |
| vix | Yahoo 429 / 0 行 | ✅ 124 行 | `VIXCLS` |
| sp500 | Yahoo 429 / 0 行 | ✅ 122 行 | `SP500` |
| nasdaq | Yahoo 429 / 0 行 | ✅ 122 行 | `NASDAQCOM` |
| us10y | Yahoo 429 / 0 行 | ✅ 121 行 | `DGS10`(`_METRIC_ALIASES` 别名) |
| dgs10 | FRED ✅ 121 | FRED ✅ 121 | `DGS10` |
| dff | FRED ✅ 177 | FRED ✅ 177 | `DFF` |
| cpi | FRED ✅ 5 | FRED ✅ 5 | `CPIAUCSL` |
| unemployment_rate | FRED ✅ 5 | FRED ✅ 5 | `UNRATE` |
| gold_price | Yahoo 429 / 0 行 | ❌ 0 行(FRED 无黄金 series) | — |

`macro_metrics` 表 source=fred 总行数:**914**(308 → 914,3 倍增长)

### L5 完整度跃升

| 字段 | Sprint 2.6-A.1 后 | Sprint 2.6-A.4 后 |
|---|---|---|
| `data_completeness_pct` | ~25%(只 FRED 4 个) | **90.0%**(9 / 10 = 90%) |
| `macro_environment` | `unknown` / `unclear` | **`neutral`** |
| `macro_headwind_vs_btc` | `unknown` | **`neutral`** |
| `metrics_available` | 4 个 | **9 个** |
| `metrics_missing` | 6 个(全部 Yahoo 字段) | **1 个(只剩 gold_price)** |

---

## 三、关键设计决策

### 3.1 us10y / dgs10 双名同源(`_METRIC_ALIASES`)

`layer5_macro._ALL_MACRO_METRICS` 同时列出 `us10y` 和 `dgs10`,但两者实际是
同一份 10 年期国债收益率数据(Yahoo 用 `^TNX` 名称对应 us10y,FRED 用 `DGS10`)。

`fred.py` 加 `_METRIC_ALIASES = {"dgs10": ["us10y"]}`,`collect_and_save_all`
拉一次 DGS10 后,把同一份 raw rows 用 `metric_name="us10y"` 也写一遍 — 避免
拉两次相同 series 浪费 FRED 配额。

### 3.2 DTWEXBGS 替代 Yahoo DXY

Yahoo 用的是 ICE 美元指数(基于 6 种货币加权),FRED `DTWEXBGS` 是 Trade Weighted
USD Index Broad(基于全球贸易加权),数学不同但宏观语义等同。L5 用它判断"美元强弱"
对 BTC 的影响,不需要 ICE 标准。

### 3.3 gold_price 无 FRED 替代,接受缺失

FRED 没有黄金价格 series(LBMA / COMEX 数据需要付费源)。L5 的 `_ALL_MACRO_METRICS`
有 10 项,缺 1 项 → completeness 90%,系统判断为"接近完整"档,不影响主决策。
若用户后续需要黄金,可考虑接 Stooq 单 ticker(用户拿 apikey 后)或 metals-api。

### 3.4 Yahoo / Stooq 死代码全删

删除文件:
- `src/data/collectors/yahoo_finance.py`(180 行)
- `scripts/probe_stooq_tickers.py`(95 行,Sprint 2.6-A.2 探测)
- `scripts/test_macro_collector.py`(134 行,旧 Yahoo+FRED 验证脚本)
- `tests/test_yahoo_collector_batch.py`(166 行)

`src/data/collectors/__init__.py` 移除 Yahoo import / export。
`src/scheduler/jobs.py::job_data_collection` 删除 Yahoo 调用块。
`scripts/backfill_data.py::backfill_macro` 删除 Yahoo 调用块。
`src/data/storage/dao.py::MacroDAO._default_source` 改 `"yahoo_finance"` → `"fred"`。
`MacroSource = Literal["fred", "yahoo_finance"]` 保留 `"yahoo_finance"` 字面量,
因为历史 DB 行(Sprint 2.4 backfill 过)仍带这个 source 标签。

---

## 四、生产端 backfill 日志(摘要)

```
=== 1. git pull ===
14 files changed, 493 insertions(+), 795 deletions(-)
[fast-forward 7d23d27 → 6620c0c]

=== 2. backfill macro 180d ===
[INFO] FRED collect done: total=914 rows, failures=0/8
[INFO] [macro.fred] fetched=914 upserted=914 elapsed_ms=4118
  macro.fred.dgs10              upserted=121
  macro.fred.us10y              upserted=121     ← _METRIC_ALIASES 别名
  macro.fred.dff                upserted=177
  macro.fred.cpi                upserted=5
  macro.fred.unemployment_rate  upserted=5
  macro.fred.sp500              upserted=122
  macro.fred.nasdaq             upserted=122
  macro.fred.vix                upserted=124
  macro.fred.dxy                upserted=117

=== 3. db ===
TOTAL FRED: 914 rows across 9 distinct metric_names

=== 4. restart service ===
active

=== 5. trigger pipeline ===
"pipeline.failure_count": 0
```

---

## 五、L5 验证(curl 实测,2026-04-27 11:08 后)

```
$ curl -u admin:*** http://124.222.89.86/api/strategy/current | jq '.state.evidence_reports.layer_5'

macro_environment:       neutral          ← 不再是 unclear / unknown
macro_headwind_vs_btc:   neutral          ← 同上
data_completeness_pct:   90.0             ← 跃升 25 → 90
metrics_available:       ['dxy', 'us10y', 'vix', 'sp500', 'nasdaq',
                          'dgs10', 'dff', 'cpi', 'unemployment_rate']
metrics_missing:         ['gold_price']    ← 唯一缺
health_status:           cold_start_warming_up   ← 因 ATR/ADX 等技术指标仍冷启动
```

---

## 六、验收对照

| 验收项 | 目标 | 实际 | 结果 |
|---|---|---|---|
| `macro_metrics` source=fred 总行数 | ≥ 600 | **914** | ✅ |
| L5 `data_completeness_pct` | ≥ 80% | **90.0%** | ✅ |
| L5 `macro_environment` | ≠ `unclear` | **neutral** | ✅ |
| pre-commit `gitleaks` | Passed | Passed(`88da7e8` commit 时) | ✅ |
| `git status` 工作区干净 | 是 | 是 | ✅ |
| pytest | 不回归 | 420 passed(Sprint 2.6-A.4 提到的 427 是含 4 个 FRED 测试,在 commit 2 删 Yahoo 测试后回到 420)| ✅ |

---

## 七、未来优化(异步,不在 2.6-A 系列范围)

1. **gold_price 数据源**:Stooq(用户拿 apikey 后)/ metals-api / GLD ETF 净值估算
2. **CoinGlass / Glassnode key rotate**:中介确认后用户自己更新(pending)
3. **L5 health_status 仍 cold_start_warming_up**:这是因为 ATR / ADX 技术指标仍需 180 天 1D K 线,与 macro 无关 — 不是本 sprint 范围
4. **scheduler 1 小时后跑 data_collection 自动增量**:从 11:08 启动后,12:08 自动跑 — 届时 FRED 增量应继续成功
5. **`MacroSource` Literal 含 "yahoo_finance" 字面量**:为兼容历史 DB,本 sprint 保留;未来若清理历史可移除

---

## 八、安全事故注解

Sprint 2.6-A.4 Commit 2(`f9457c2`)期间发生 `.env.save` 泄露事故,详细处置见
`docs/cc_reports/security_incident_2026_04_27.md`:
- `.env.save` 含 6 个真 API key,推到公网 main ~30 分钟
- `git filter-repo --path .env.save --invert-paths --force` 全历史擦除
- 强制推送将 `f9457c2` 改写为 `5c6a186`(其它 109 个 commit hash 不变)
- `.gitignore` 加固 + pre-commit gitleaks 启用
- 用户 rotate 4/6 key,2 个 alphanode 中转 key 等中介确认

事故对本 sprint 主任务(FRED 扩展)无功能影响 — 代码层 commit 1+2 已正确推送,
filter-repo 只动了泄露文件不影响业务逻辑。

---

## 九、git log(本 sprint 所有 commit + 安全 commit)

```
6620c0c docs(security): incident report for 2026-04-27 .env.save leak
88da7e8 security: harden .gitignore + add pre-commit gitleaks
5c6a186 chore: remove Yahoo/Stooq/batch dead code (FRED is sole macro source now)  ← 原 f9457c2 改写后
aca8873 feat(fred): expand to cover dxy/vix/sp500/nasdaq, replacing Yahoo
```
