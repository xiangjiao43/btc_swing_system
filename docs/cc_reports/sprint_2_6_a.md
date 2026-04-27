# Sprint 2.6-A — macro 数据采集修复 + data_collection job 实施

**Date:** 2026-04-27
**Branch:** main
**Type:** fix(backfill) + feat(scheduler) + test
**Status:** ⚠ 代码修复完成,但生产端 macro 数据写入受环境因素阻塞,等用户决策

---

## 一、3 个独立 commit(代码层全部完成)

| commit | 文件 | 摘要 |
|---|---|---|
| `15c2de3` | `scripts/backfill_data.py` (+40/−89) + `.env.example`(去重) | Bug 1 修:`FREDCollector` → `FredCollector`(实际类名)。Bug 2 修:废弃 hasattr 探测,直接用 collector 自带的 `collect_and_save_all(conn, since_days)`。`.env.example` 删除重复 FRED 段 |
| `01ad99f` | `src/scheduler/jobs.py` (+184/−6) + `config/scheduler.yaml`(enabled true) | Bug 3 修:`job_data_collection` 真实实施,4 个 collector 优雅失败 + 单 collector 子方法独立 try/except;每小时跑一次 |
| `d880bed` | `tests/test_data_collection_job.py`(+184) | 5 个 case:任一 collector 成功→ok / 全失败→all_failed / conn_factory 抛错→fatal_error / FRED disabled 不算错 / coinglass 子方法部分失败不影响整体 |

pytest:411 → 416(+5),无回归。

---

## 二、生产部署状态

```
$ ssh ubuntu@124.222.89.86 'cd ~/btc_swing_system && git pull && sudo systemctl restart btc-strategy'
→ d880bed pulled, btc-strategy active (running)
```

scheduler 已加载新配置,下个 4h 周期 `pipeline_run` + 每小时 `data_collection` 都会跑。

---

## 三、⚠ 两项生产端环境阻塞(无法仅靠代码修复)

### 3.1 Yahoo Finance 429 (Too Many Requests) — backfill 全部失败

跑 `backfill_data.py --only macro --days 180` 实测:

```
2026-04-27 09:21:54 Yahoo fetch DX-Y.NYB → Too Many Requests
2026-04-27 09:21:56 Yahoo fetch ^TNX     → Too Many Requests
2026-04-27 09:21:57 Yahoo fetch ^VIX     → Too Many Requests
2026-04-27 09:21:57 Yahoo fetch ^GSPC    → Too Many Requests
2026-04-27 09:21:58 Yahoo fetch ^IXIC    → Too Many Requests
2026-04-27 09:21:58 Yahoo fetch GC=F     → Too Many Requests
[ERROR] All 6 Yahoo symbols failed; check network
```

**根因**:Yahoo Finance 不喜欢 5 秒内连发 6 次请求,触发 IP 级限速。这与 CLAUDE.md 早记录的"Yahoo Finance 经常被限速 429"一致。Sprint 2.6-A 代码层把 wiring 修对了 — 现在 collector 真的会被调到,但调到的接口被对方 ban。

**不是 Sprint 2.6-A 修复范围**:本 sprint 硬约束第 1 条"绝对不动 collector 内部实现"。这意味着我不能改 yahoo_finance.py 加 sleep / 重试 / proxy 切换。

### 3.2 FRED_API_KEY 在 `.env` 但实际为空字符串 — 触发"停下问用户"决策点 #3

诊断脚本:
```
$ ssh ubuntu@124.222.89.86 '...诊断脚本...'
[env_loader] loaded .env: 6 keys
FRED_API_KEY: empty string
FredCollector.enabled: False
FredCollector.api_key (length): 0
```

**根因**:服务器 `.env` 里有 `FRED_API_KEY=` 这一行,但等号后是空值(可能用户复制 `.env.example` 时未填实际 key,或填了又被清空)。FredCollector 的 `enabled = bool(self.api_key)` 把空字符串视为未设置,正确行为。

**用户操作清单**(2 选 1):
- (A) 注册 FRED 免费 key(https://fred.stlouisfed.org/docs/api/api_key.html),把 32 字符 key 填到服务器 `.env` 的 `FRED_API_KEY=` 后面,然后 `sudo systemctl restart btc-strategy`
- (B) 接受 FRED 不可用,只用 Yahoo(但 Yahoo 又 429,见 3.1)

---

## 四、L5 验证暂时无法完成

按 spec 第 4 步要求的:
```
预期:macro_environment 不再是 'unclear';data_completeness_pct ≥ 60%;
metrics_available 至少包含 dxy / us10y / vix / sp500 / nasdaq
```

当前因 3.1 + 3.2 阻塞,`macro_metrics` 表仍然 0 行,L5 仍然输出 `macro_environment: unknown`。

**需先解决 3.1 / 3.2 后才能验证**。

---

## 五、决策项(等用户选)

### A 选项 — 解决 FRED + 接受 Yahoo 429
1. 用户注册 FRED key 并填到服务器 `.env`
2. 跑 `.venv/bin/python scripts/backfill_data.py --only macro --days 180`
3. 预期 FRED 5 个 series 各 ~180 行成功;Yahoo 仍 429 全失败
4. L5 部分覆盖:有 `dgs10 / dff / cpi / unemployment_rate` 等 FRED metric,但 dxy / vix / 纳指仍空

### B 选项 — 修 Yahoo 限速(超出 2.6-A spec)
1. 在 `yahoo_finance.py` 加 `time.sleep(15)` 或加 retry-with-backoff
2. 或换 yfinance 的 batch download API(一次拉多 symbol 减少请求数)
3. 或绕道(走中转、缓存站点)
4. 此项明确**违反硬约束 #1**,本 sprint 不做,需用户开 Sprint 2.6-A.1

### C 选项 — 接受现状(数据残缺继续)
- L5 继续输出 `macro_environment: unknown`,降级 fallback 走规则路径
- 用户自己手动判断宏观

### D 选项 — 把 macro 数据源整体换掉
- 比如换 `polygon.io` 或 `alpha_vantage`(需付费)
- 或换 binance.com 的 K 线 + 自己算 DXY 替代
- 这是 sprint 级架构变更,远超 2.6-A 范围

**我倾向 A**:先用 FRED 拿到部分宏观,Yahoo 限速另开 sprint 解决。

---

## 六、git log(本 sprint 范围)

```
d880bed test(scheduler): add data_collection job coverage
01ad99f feat(scheduler): implement data_collection job with 4 collectors
15c2de3 fix(backfill): repair Yahoo/FRED collector wiring + dedupe .env.example
```
