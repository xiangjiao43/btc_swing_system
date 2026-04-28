# Sprint 2.7-B — jobs.py 拆 5 函数 + 衍生品 1h interval

**Date:** 2026-04-27
**Branch:** main
**Status:** ✅ 完成

---

## 一、改动

### `src/scheduler/jobs.py` 重构

**§X 删除:** `job_data_collection`(三合一函数)整段移除。

**新增 5 个独立 collector job(替代 `job_data_collection`):**

| 函数 | yaml job | 触发时刻(BJT) | 抓取内容 |
|---|---|---|---|
| `job_collect_klines_1h` | collect_klines_1h | 每整点 :00 | CoinGlass 1h K 线(limit=24)+ 5 衍生品端点 **interval='1h' limit=168** |
| `job_collect_klines_daily` | collect_klines_daily | 08:01 | 1d + 4h K 线(各 limit=24)|
| `job_collect_klines_weekly` | collect_klines_weekly | Mon 08:01 | 1w K 线(limit=12)|
| `job_collect_macro` | collect_macro | 06:00 | FRED 9 series via `collect_and_save_all` |
| `job_collect_onchain` | collect_onchain | 08:35 | Glassnode 12 fetcher(primary 5 + display 7,含 LTH/STH realized + aSOPR)|

**关键改动**:衍生品 5 端点(funding_rate / funding_rate_aggregated / open_interest / long_short_ratio / liquidation)从 `interval='1d', limit=7` → **`interval='1h', limit=168`**。
之前每天 1 行,现在每小时 1 行,用户视图能看到小时级精度。
`derivatives_snapshots` 仍是 wide 表 → 一天 24 行,撑得住(Sprint 2.6-J backlog "wide 表精度天花板"留作未来 schema 改造)。

**通用 wrapper**:`_wrap_job(name, body, conn_factory)` 处理 conn 异常 + 计时 + finally close。所有 5 个 collector 共用。

### `src/scheduler/__init__.py`
- 出口移除 `job_data_collection`
- 出口加入 5 个新 collector + `job_event_listener`

### §X 删除老测试
- `tests/test_data_collection_job.py` — 整个文件覆盖老的统合函数,删除
- `tests/test_funding_aggregated_actually_fetched.py` — guard 老 jobs.py 的 funding_rate_aggregated 注册,删除(新测试 `test_collect_klines_1h_uses_1h_interval_for_derivatives` 覆盖等价行为)
- `tests/test_glassnode_3_new_metrics_actually_fetched.py` — 同上,删除(新测试 `test_collect_onchain_iterates_glassnode_fetchers` 覆盖)

### tests/test_scheduler.py
- `test_scheduler_has_pipeline_job_registered` 改用新 yaml 名(`collect_klines_1h` 替代 `data_collection`)+ pipeline_run cron 替代 4h interval

---

## 二、新增测试 `tests/test_scheduler_2_7_b_collectors.py`(12 测试)

§X 验证(3 测试):
- `job_data_collection` 函数已删
- `_JOB_FUNCTIONS` registry 不含 `data_collection`
- 5 个新 collector 全注册

§Z 端到端 DB 行数断言(每个 job 一组,共 9 测试):
- `collect_klines_1h` 写 price_candles + derivatives_snapshots,断言 row count > 0
- **关键断言**:每个衍生品 fetcher 调用必须 `interval='1h' limit=168`
- partial_failure(单个 fetcher 抛异常)不让整 job 崩溃
- `collect_klines_daily` 调 fetch_klines 2 次 (1d + 4h)
- `collect_klines_weekly` 调 1 次 (1w)
- `collect_macro` 调 FredCollector.collect_and_save_all
- `collect_macro` 无 key 时 status=skipped
- `collect_onchain` 调 12 个 fetcher
- `fatal_error` path:conn_factory 抛异常 → status='fatal_error',scheduler 不 crash

---

## 三、用户验证(SSH 部署后)

```bash
ssh ubuntu@124.222.89.86 << 'SSH'
cd /home/ubuntu/btc_swing_system
git pull
sudo systemctl restart btc-strategy.service
sleep 5
journalctl -u btc-strategy.service -n 50 | grep -E "next run|collect_"
SSH

# 等下一个整点过后(:01),验证衍生品 1h 粒度
ssh ubuntu@124.222.89.86 "sqlite3 /home/ubuntu/btc_swing_system/data/btc_strategy.db \
  'SELECT COUNT(DISTINCT captured_at_utc) AS n_distinct_ts \
   FROM derivatives_snapshots \
   WHERE inserted_at_utc > datetime(\"now\", \"-2 hours\");'"
```

预期:`n_distinct_ts >= 2`(过去 2h 至少 2 个不同 captured_at_utc,小时级抓取生效)。

---

## 四、§X / §Y / §Z

- ✅ §X:`job_data_collection` 函数 + `_JOB_FUNCTIONS` 条目 + `__init__.py` 出口 + 3 个老测试文件全部删除,**没保留 deprecated 注释或 fallback 调用**
- ✅ §Y:本 commit 立即 push
- ✅ §Z:每个 job 测试断言真 SQLite + 真 DAO + DB 行数 / kwargs 字段值精确(尤其衍生品 `interval='1h' limit=168` 必须严格匹配)

---

## 五、后续

- 2.7-C:state_builder pre-flight 数据就绪(根据 run_trigger 不同档用不同阈值)
- 2.7-D:`job_event_listener` 实施 + 4 种 event 触发
