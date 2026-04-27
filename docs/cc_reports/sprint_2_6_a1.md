# Sprint 2.6-A.1 — backfill_macro 缺失 commit() 修复

**Date:** 2026-04-27
**Branch:** main · commit `92e2fe8`
**Type:** fix(backfill) · 单文件 2 行改动

---

## 一、bug 根因

Sprint 2.6-A 重写过的 `scripts/backfill_data.py::backfill_macro`(commit `15c2de3`)
直接调 `collect_and_save_all(conn, since_days)`,但**漏写 `conn.commit()`**。

三层证据:
1. `FredCollector.collect_and_save_all`(`src/data/collectors/fred.py`)内部调
   `MacroDAO.upsert_batch(conn, metrics)` — 只 execute SQL,不 commit
2. `backfill_macro` 函数返回后 `main()` 也没显式 commit
3. SQLite 默认开启自动事务,所有 INSERT 都在事务里;函数结束 + connection 关闭
   时如果没显式 commit,事务回滚 → 数据全丢

对比 `backfill_price / backfill_derivatives / backfill_onchain` 都在 metric
循环里调 `conn.commit()`,只有 `backfill_macro` 漏了。

---

## 二、修复 diff(2 行)

```diff
@@ scripts/backfill_data.py::backfill_macro @@

         else:
             stats = yf_coll.collect_and_save_all(conn, since_days=days)
+            conn.commit()  # Sprint 2.6-A.1:DAO.upsert_batch 不 commit,这里必须显式提交
             total = sum(v for v in stats.values() if isinstance(v, int))

         else:
             stats = fred_coll.collect_and_save_all(conn, since_days=days)
+            conn.commit()  # Sprint 2.6-A.1:同上,显式提交否则数据丢失
             total = sum(...)
```

---

## 三、生产端验证

```
$ ssh ubuntu@124.222.89.86 'cd ~/btc_swing_system && git pull && \
    .venv/bin/python scripts/backfill_data.py --only macro --days 180'

=== db before ===
-rw-r--r-- 1 ubuntu ubuntu 2359296 Apr 27 08:43 data/btc_strategy.db

=== running backfill ===
... (Yahoo 6 symbols 仍全部 429,与 2.6-A 报告一致)
[INFO] FRED collect done: total=308 rows, failures=0/4
[INFO] [macro.fred] fetched=308 upserted=308 elapsed_ms=3683
[INFO]   macro.fred.dgs10 upserted=121
[INFO]   macro.fred.dff upserted=177
[INFO]   macro.fred.cpi upserted=5
[INFO]   macro.fred.unemployment_rate upserted=5
[INFO] === Backfill done (total 9417 ms) ===

=== db after ===
-rw-r--r-- 1 ubuntu ubuntu 2400256 Apr 27 09:47 data/btc_strategy.db   ← 文件增长 +40 KB

=== macro_metrics by metric ===
  cpi                       5
  dff                       177
  dgs10                     121
  unemployment_rate         5
=== total rows: 308 ===
```

✅ DB 文件大小从 2,359,296 → 2,400,256 字节(+40 KB)
✅ 修改时间从 08:43 → 09:47(本次 backfill 的时间戳)
✅ `macro_metrics` 表 308 行,4 个 series 全部入库

---

## 四、未解决项(继承自 Sprint 2.6-A,本 sprint 不修)

1. **Yahoo Finance 6 个 symbol 全部 429**:Sprint 2.6-A 已记录,需另开 Sprint 修
   collector 加 sleep/retry 或换源(违反 2.6-A 硬约束 #1,本 sprint 也不动)
2. **`macro_metrics` 当前覆盖 4 个 FRED series**(dff / dgs10 / cpi /
   unemployment_rate),但建模 §3.8.5 MacroHeadwind 主要因子是 DXY / US10Y /
   VIX / 纳指 — 这些都是 Yahoo 出的。换言之,L5 现在拿到了 FRED 的次要数据,
   但主要因子(DXY 等)仍空。L5 `data_completeness_pct` 会从 0 提升到 ~25%,
   仍达不到 spec 验收的 ≥ 60% 门槛
3. 本 sprint 没动 scheduler `data_collection` 任务 — 它每小时跑一次,1 小时后
   会自动跑成功(FRED 部分);但只要 Yahoo 还 429,L5 完整度仍然不够

---

## 五、git log

```
92e2fe8 fix(backfill): add missing commit() in backfill_macro
0e39f89 docs(reports): sprint_2_6_a complete (code fixes + 2 env blockers)
d880bed test(scheduler): add data_collection job coverage
01ad99f feat(scheduler): implement data_collection job with 4 collectors
15c2de3 fix(backfill): repair Yahoo/FRED collector wiring + dedupe .env.example
```
